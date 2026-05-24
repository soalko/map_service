// ---------- Map init ----------
const map = L.map("map", { attributionControl: false }).setView([55.751624, 37.618585], 10);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OSM</a>",
}).addTo(map);
L.control.attribution({ prefix: false }).addTo(map);

// ---------- State ----------
const state = {
    appMode: "nav",
    analyticsMode: "detailed",
    authMode: "login",
    currentCenter: null,
    centerMarker: null,
    routeLayer: null,
    routeStartMarker: null,
    routeEndMarker: null,
    currentDistrictId: null,
    selectedDistrictLayer: null,
    clusterGroup: null,
    token: localStorage.getItem("auth_token") || "",
    user: null,
    reviewPhotos: [],
    reviewPhotoUrls: new Map(),
    layerCache: {
        nav: null,
        detailed: null,
        coarse: null,
    },
};

const el = {
    loadingChip: document.getElementById("loadingChip"),
    districtSidebar: document.getElementById("districtSidebar"),
    districtInfo: document.querySelector(".district-info"),
    statsBlock: document.querySelector(".stats-block"),
    reviewForm: document.querySelector(".review-form"),
    reviewsList: document.getElementById("reviewsList"),
    avgRating: document.getElementById("avgRating"),
    reviewComment: document.getElementById("reviewComment"),
    reviewRating: document.getElementById("reviewRating"),
    reviewPhotos: document.getElementById("reviewPhotos"),
    reviewPhotosPreview: document.getElementById("reviewPhotosPreview"),
    reviewAuthHint: document.getElementById("reviewAuthHint"),
    photoModalOverlay: document.getElementById("photoModalOverlay"),
    photoModalClose: document.getElementById("photoModalClose"),
    photoModalImage: document.getElementById("photoModalImage"),
    photoModalCaption: document.getElementById("photoModalCaption"),
    authUserLabel: document.getElementById("authUserLabel"),
    authUsername: document.getElementById("authUsername"),
    authPassword: document.getElementById("authPassword"),
    authDisplayName: document.getElementById("authDisplayName"),
    authModalOverlay: document.getElementById("authModalOverlay"),
    authModalTitle: document.getElementById("authModalTitle"),
    authModalSubtitle: document.getElementById("authModalSubtitle"),
    authSubmitBtn: document.getElementById("authSubmitBtn"),
    authSwitchBtn: document.getElementById("authSwitchBtn"),
    authModalClose: document.getElementById("authModalClose"),
    loginBtn: document.getElementById("loginBtn"),
    registerBtn: document.getElementById("registerBtn"),
    logoutBtn: document.getElementById("logoutBtn"),
};

function setLoading(visible, text = "Загрузка...") {
    if (!el.loadingChip) return;
    el.loadingChip.textContent = text;
    el.loadingChip.style.display = visible ? "block" : "none";
}

function bindClick(id, handler) {
    const node = document.getElementById(id);
    if (node) node.addEventListener("click", handler);
}

async function apiFetch(url, options = {}) {
    const headers = options.headers ? { ...options.headers } : {};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;

    const response = await fetch(url, { ...options, headers });
    let data;
    try {
        data = await response.json();
    } catch (e) {
        data = null;
    }
    if (!response.ok) {
        // Преобразуем detail в читабельную строку, если это массив ошибок
        let message = `HTTP ${response.status}`;
        if (data && data.detail) {
            if (Array.isArray(data.detail)) {
                message = data.detail.join(' ; ');
            } else if (typeof data.detail === 'string') {
                message = data.detail;
            } else {
                try { message = JSON.stringify(data.detail); } catch (e){ message = String(data.detail); }
            }
        }
        console.warn('apiFetch error', url, response.status, data);
        throw new Error(message);
    }
    return data;
}

function clearRoute() {
    if (state.routeLayer) map.removeLayer(state.routeLayer);
    if (state.routeStartMarker) map.removeLayer(state.routeStartMarker);
    if (state.routeEndMarker) map.removeLayer(state.routeEndMarker);
    state.routeLayer = null;
    state.routeStartMarker = null;
    state.routeEndMarker = null;
}

function clearMarkers() {
    if (state.clusterGroup) map.removeLayer(state.clusterGroup);
    state.clusterGroup = L.markerClusterGroup({
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        maxClusterRadius: 50,
    });
    map.addLayer(state.clusterGroup);
}

function clearNavigationMarkers() {
    clearMarkers();
    clearRoute();
    if (state.centerMarker) {
        map.removeLayer(state.centerMarker);
        state.centerMarker = null;
    }
    state.currentCenter = null;
}

function renderReviewPhotosPreview() {
    if (!el.reviewPhotosPreview) return;
    for (const url of state.reviewPhotoUrls.values()) {
        try { URL.revokeObjectURL(url); } catch (e) {}
    }
    state.reviewPhotoUrls.clear();
    if (!state.reviewPhotos.length) {
        el.reviewPhotosPreview.innerHTML = "";
        return;
    }
    el.reviewPhotosPreview.innerHTML = state.reviewPhotos
        .map((file, index) => `
            <div style="position:relative; display:inline-block; margin-right:6px; padding:4px; box-sizing:border-box;">
                <img src="${(() => { const url = URL.createObjectURL(file); state.reviewPhotoUrls.set(index, url); return url; })()}" alt="review photo ${index + 1}" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid #dce7f1;display:block;" />
                <button type="button" data-review-photo-index="${index}" style="position:absolute;top:8px;right:8px;width:20px;height:20px;border:none;border-radius:50%;background:#e74c3c;color:#fff;cursor:pointer;line-height:20px;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,0.2);">×</button>
            </div>
        `)
        .join("");
}

function openPhotoModal(src, alt = "Фото") {
    if (!el.photoModalOverlay || !el.photoModalImage) return;
    el.photoModalImage.src = src;
    el.photoModalImage.alt = alt;
    if (el.photoModalCaption) el.photoModalCaption.textContent = alt;
    el.photoModalOverlay.classList.add("visible");
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
}

function closePhotoModal() {
    if (el.photoModalOverlay) el.photoModalOverlay.classList.remove("visible");
    if (el.photoModalImage) el.photoModalImage.src = "";
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
}

function resetReviewPhotos() {
    for (const url of state.reviewPhotoUrls.values()) {
        try { URL.revokeObjectURL(url); } catch (e) {}
    }
    state.reviewPhotoUrls.clear();
    state.reviewPhotos = [];
    if (el.reviewPhotos) el.reviewPhotos.value = "";
    renderReviewPhotosPreview();
}

function syncReviewPhotosInput() {
    if (!el.reviewPhotos) return;
    if (typeof DataTransfer === "undefined") return;
    const dt = new DataTransfer();
    state.reviewPhotos.forEach((file) => dt.items.add(file));
    el.reviewPhotos.files = dt.files;
}

function addReviewPhotos(fileList) {
    const incoming = Array.from(fileList || []).filter((file) => {
        if (!file) return false;
        if (!file.type) return true;
        return file.type.startsWith("image/");
    });
    if (!incoming.length) return;

    const merged = state.reviewPhotos.slice();
    const seen = new Set(merged.map((file) => `${file.name}|${file.size}|${file.lastModified}`));
    let ignored = 0;

    for (const file of incoming) {
        const key = `${file.name}|${file.size}|${file.lastModified}`;
        if (seen.has(key)) continue;
        if (merged.length >= 10) {
            ignored += 1;
            continue;
        }
        merged.push(file);
        seen.add(key);
    }

    state.reviewPhotos = merged;
    syncReviewPhotosInput();
    renderReviewPhotosPreview();

    if (ignored > 0) {
        alert("Можно прикрепить не более 10 фото к одному отзыву");
    }
}

function setAuthModalMode(mode) {
    state.authMode = mode === "register" ? "register" : "login";
    if (el.authModalTitle) {
        el.authModalTitle.textContent = state.authMode === "register" ? "Регистрация" : "Вход";
    }
    if (el.authModalSubtitle) {
        el.authModalSubtitle.textContent = state.authMode === "register"
            ? "Создайте аккаунт, чтобы оставлять отзывы и прикреплять фото."
            : "Введите логин и пароль, чтобы войти в аккаунт.";
    }
    if (el.authSubmitBtn) {
        el.authSubmitBtn.textContent = state.authMode === "register" ? "Зарегистрироваться" : "Войти";
    }
    if (el.authSwitchBtn) {
        el.authSwitchBtn.textContent = state.authMode === "register"
            ? "Уже есть аккаунт? Войти"
            : "Нет аккаунта? Регистрация";
    }
    if (el.authDisplayName) {
        el.authDisplayName.style.display = state.authMode === "register" ? "block" : "none";
    }
}

function openAuthModal(mode = "login") {
    setAuthModalMode(mode);
    if (el.authModalOverlay) el.authModalOverlay.classList.add("visible");
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    if (el.authUsername) setTimeout(() => el.authUsername.focus(), 0);
}

function closeAuthModal() {
    if (el.authModalOverlay) el.authModalOverlay.classList.remove("visible");
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
}

async function submitAuthForm() {
    if (state.authMode === "register") {
        await registerUser();
    } else {
        await loginUser();
    }
}

function closeSidebar() {
    if (el.districtSidebar) el.districtSidebar.style.display = "none";
    if (state.selectedDistrictLayer && state.selectedDistrictLayer.feature) {
        state.selectedDistrictLayer.setStyle(styleDistrict(state.selectedDistrictLayer.feature));
        state.selectedDistrictLayer = null;
    }
}

function getDistrictColor(score) {
    if (score >= 0.4) return "#ffb400";
    if (score >= 0.3) return "#c0c0c0";
    if (score >= 0.2) return "#cd7f32";
    if (score >= 0.15) return "#00190e";
    if (score >= 0.1) return "#002b17";
    if (score >= 0.075) return "#00502a";
    if (score >= 0.050) return "#006837";
    if (score >= 0.025) return "#78c679";
    if (score >= 0.001) return "#c2e699";
    return "#ffffff";
}

function styleDistrict(feature) {
    return {
        fillColor: getDistrictColor(feature.properties.final_score || 0),
        weight: 2,
        opacity: 1,
        color: "white",
        fillOpacity: 0.7,
    };
}

function highlightDistrictStyle(feature) {
    return {
        fillColor: getDistrictColor(feature.properties.final_score || 0),
        weight: 4,
        opacity: 1,
        color: "#000000",
        fillOpacity: 0.75,
    };
}

async function loadCurrentUser() {
    if (!state.token) {
        state.user = null;
        syncAuthUi();
        return;
    }
    try {
        state.user = await apiFetch("/auth/me");
    } catch (e) {
        state.token = "";
        state.user = null;
        localStorage.removeItem("auth_token");
    }
    syncAuthUi();
}

function syncAuthUi() {
    const isAuth = !!state.user;
    if (el.authUserLabel) {
        el.authUserLabel.textContent = isAuth ? `👤 ${state.user.display_name || state.user.username}` : "Гость";
    }
    if (el.loginBtn) el.loginBtn.style.display = isAuth ? "none" : "inline-block";
    if (el.registerBtn) el.registerBtn.style.display = isAuth ? "none" : "inline-block";
    if (el.logoutBtn) el.logoutBtn.style.display = isAuth ? "inline-block" : "none";
    if (el.reviewAuthHint) {
        el.reviewAuthHint.textContent = isAuth
            ? "Вы авторизованы. Можно оставить отзыв и прикрепить до 10 фото."
            : "Оставлять отзывы могут только авторизованные пользователи.";
    }
    applySidebarAccess(isAuth);
    if (isAuth && state.currentDistrictId && el.districtSidebar && el.districtSidebar.style.display === "flex" && state.selectedDistrictLayer && state.selectedDistrictLayer.feature) {
        void showDistrictSidebar(state.selectedDistrictLayer.feature.properties, state.selectedDistrictLayer);
    }
    if (isAuth) closeAuthModal();
}

function applySidebarAccess(isAuth) {
    if (el.reviewForm) el.reviewForm.style.display = isAuth ? "block" : "none";

    ["reviewRating", "reviewComment", "reviewPhotos", "reviewPhotosPreview", "submitReview"].forEach((id) => {
        const node = document.getElementById(id);
        if (node) node.style.display = isAuth ? "" : "none";
    });
}

async function registerUser() {
    const username = (el.authUsername?.value || "").trim();
    const password = (el.authPassword?.value || "").trim();
    const displayName = (el.authDisplayName?.value || "").trim();
    if (!username || !password) return alert("Введите логин и пароль");
    if (username.length < 3) return alert("Логин должен быть не менее 3 символов");
    if (password.length < 6) return alert("Пароль должен быть не менее 6 символов");

    try {
        const data = await apiFetch("/auth/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password, display_name: displayName || null }),
        });
        state.token = data.token;
        localStorage.setItem("auth_token", state.token);
        await loadCurrentUser();
        if (el.authPassword) el.authPassword.value = "";
        closeAuthModal();
        alert("Регистрация успешна");
    } catch (e) {
        alert(`Ошибка регистрации: ${e.message}`);
    }
}

async function loginUser() {
    const username = (el.authUsername?.value || "").trim();
    const password = (el.authPassword?.value || "").trim();
    if (!username || !password) return alert("Введите логин и пароль");

    try {
        const data = await apiFetch("/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });
        state.token = data.token;
        localStorage.setItem("auth_token", state.token);
        await loadCurrentUser();
        if (el.authPassword) el.authPassword.value = "";
        closeAuthModal();
    } catch (e) {
        alert(`Ошибка входа: ${e.message}`);
    }
}

async function logoutUser() {
    try {
        await apiFetch("/auth/logout", { method: "POST" });
    } catch (e) {
        // no-op
    }
    state.token = "";
    state.user = null;
    localStorage.removeItem("auth_token");
    syncAuthUi();
}

function removeAllDistrictLayers() {
    ["nav", "detailed", "coarse"].forEach((key) => {
        const layer = state.layerCache[key];
        if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    });
}

// Дополнительный надёжный сброс: удаляем любые GeoJSON-слои районов, которые могли быть добавлены напрямую
function removeAnyDistrictGeoJSONFromMap() {
    map.eachLayer((layer) => {
        try {
            // У GeoJSON-слоёв есть поле feature или featureCollection в options
            if (layer && layer.feature && layer.feature.properties && (layer.feature.properties.id || layer.feature.properties.name)) {
                map.removeLayer(layer);
            }
        } catch (e) {
            // ignore
        }
    });
}

async function ensureNavLayer() {
    if (state.layerCache.nav) return state.layerCache.nav;
    setLoading(true, "Загрузка границ...");
    const data = await apiFetch("/districts/boundaries");
    state.layerCache.nav = L.geoJSON(data, {
        style: { color: "#243a53", weight: 2, fill: false, opacity: 0.8 },
        interactive: false,
    });
    setLoading(false);
    return state.layerCache.nav;
}

function renderStatsTable(groups) {
    if (!groups) return "<p>Нет данных по группам</p>";
    return `
        <table class="stats-table">
            <tr><th>Категория</th><th>Кол-во</th><th>Плотность</th><th>Вес</th><th>Норма плотности</th><th>Норма log(1+cnt)</th><th>Score</th></tr>
            <tr><td>Социальная</td><td>${groups.social?.count ?? 0}</td><td>${groups.social?.density ?? 0}</td><td>${groups.social?.weight ?? 0}</td><td>${groups.social?.norm_density ?? 0}</td><td>${groups.social?.norm_logcnt ?? 0}</td><td>${groups.social?.score ?? 0}</td></tr>
            <tr><td>Торговля</td><td>${groups.shops?.count ?? 0}</td><td>${groups.shops?.density ?? 0}</td><td>${groups.shops?.weight ?? 0}</td><td>${groups.shops?.norm_density ?? 0}</td><td>${groups.shops?.norm_logcnt ?? 0}</td><td>${groups.shops?.score ?? 0}</td></tr>
            <tr><td>Туризм</td><td>${groups.tourism?.count ?? 0}</td><td>${groups.tourism?.density ?? 0}</td><td>${groups.tourism?.weight ?? 0}</td><td>${groups.tourism?.norm_density ?? 0}</td><td>${groups.tourism?.norm_logcnt ?? 0}</td><td>${groups.tourism?.score ?? 0}</td></tr>
            <tr><td>Досуг</td><td>${groups.leisure?.count ?? 0}</td><td>${groups.leisure?.density ?? 0}</td><td>${groups.leisure?.weight ?? 0}</td><td>${groups.leisure?.norm_density ?? 0}</td><td>${groups.leisure?.norm_logcnt ?? 0}</td><td>${groups.leisure?.score ?? 0}</td></tr>
        </table>`;
}

function renderCalculationDetails(stats) {
    if (stats.base_score === undefined) return "<p>Расчет недоступен</p>";

    const groupRows = [
        ["social", "Социальная"],
        ["shops", "Торговля"],
        ["tourism", "Туризм/культура"],
        ["leisure", "Досуг/спорт"],
    ].map(([key, title]) => {
        const g = stats.groups?.[key] || {};
        return `
            <tr>
                <td style="text-align:left;">${title}</td>
                <td>${g.count ?? 0}</td>
                <td>${Number(g.density ?? 0).toFixed(3)}</td>
                <td>${g.weight ?? 0}</td>
                <td>${Number(g.norm_density ?? 0).toFixed(4)}</td>
                <td>${Number(g.norm_logcnt ?? 0).toFixed(4)}</td>
                <td><b>${Number(g.score ?? 0).toFixed(4)}</b></td>
            </tr>
        `;
    }).join("");

    const legendItems = [
        ["≥ 0.4", "#ffb400", "Золотой район*"],
        ["0.3–0.399", "#c0c0c0", "Серебряный район*"],
        ["0.2–0.299", "#cd7f32", "Бронзовый район*"],
        ["0.15–0.199", "#00190e", "Высокий"],
        ["0.1–0.149", "#002b17", "Выше среднего"],
        ["0.075–0.099", "#00502a", "Средний"],
        ["0.05–0.074", "#006837", "Ниже среднего"],
        ["0.025–0.049", "#78c679", "Низкий"],
        ["0.001–0.024", "#c2e699", "Очень низкий"],
        ["0", "#ffffff", "Нет данных / 0"],
    ].map(([range, color, label]) => `
        <div style="display:flex;align-items:center;gap:8px;margin:4px 0;">
            <span style="width:16px;height:16px;border-radius:4px;background:${color};border:1px solid #cfd7e3;display:inline-block;"></span>
            <span><code>${range}</code> — ${label}</span>
        </div>
    `).join("");

    return `
        <div style="font-size:14px;background:#f9f9f9;padding:10px;border-radius:6px;line-height:1.45;">
            <b>Как считается итоговый балл района</b><br>
            
            <b>Шаг 1. Нормализованные показатели групп</b><br>
            <table class="stats-table" style="font-size:12px;">
                <tr><th>Группа</th><th>Кол-во</th><th>Плотность</th><th>Вес</th><th>Нормализ. плотность</th><th>log(1+Норм.пл.)</th><th>Итог</th></tr>
                ${groupRows}
            </table>

            <b>Шаг 2. Формула score группы</b><br>
            <span><code>score = α × norm_density + (1 - α) × norm_logcnt</code>, где α = <b>${Number(stats.alpha || 0.5).toFixed(2)}</b></span><br><br>

            <b>Шаг 3. Базовый балл</b><br>
            <span><code>base_score = social×0.30 + shops×0.25 + tourism×0.25 + leisure×0.20</code></span><br>
            <span>Базовый балл: <b>${Number(stats.base_score || 0).toFixed(3)}</b></span><br><br>

            <b>Шаг 4. Коррекция по отзывам</b><br>
            <span>Средний рейтинг района: <b>${Number(stats.avg_rating || 0).toFixed(2)}</b> ★</span><br>
            <span><code>k_user = 0.8 + (avg_rating - 1) × 0.1</code> = <b>${Number(stats.k_user || 1).toFixed(3)}</b></span><br>
            <span><code>final_score = base_score × k_user</code> = <b>${Number(stats.final_score || 0).toFixed(3)}</b></span><br><br>

            <b>Легенда расцветки районов</b><br>
            <span>Цвета соответствуют <code>final_score</code> и используются на карте для заливки районов.</span>
            <div style="margin-top:8px;">${legendItems}</div>
            <br><b>*</b> Категории Бронзовый, Серебряный, Золотой район являются особой степенью оценки района, 
            так как районы с этими рейтингами являются высшими среди остальных, участвующих в подсчете.
        </div>
    `;
}

async function loadReviews(districtId) {
    const data = await apiFetch(`/reviews/${districtId}`);
    if (el.avgRating) el.avgRating.textContent = data.avg_rating ? Number(data.avg_rating).toFixed(2) : "Нет";

    if (!el.reviewsList) return;
    const reviews = data.reviews || [];
    if (!reviews.length) {
        el.reviewsList.innerHTML = "<h4>Отзывы:</h4><p>Пока нет отзывов.</p>";
        return;
    }

    el.reviewsList.innerHTML = "<h4>Отзывы:</h4>";
    reviews.forEach((r) => {
        const card = document.createElement("div");
        card.className = "review-card";
        const photosHtml = (r.photos || []).length
            ? `<div class="review-photos">${r.photos.map((p, idx) => `<img class="review-photo-thumb" src="${p.file_path}" data-fullsrc="${p.file_path}" alt="review photo ${idx + 1}" />`).join("")}</div>`
            : "";
        const deleteBtnHtml = r.is_mine
            ? `<div class="review-actions"><button class="review-delete-btn" data-review-id="${r.id}">Удалить</button></div>`
            : "";
        card.innerHTML = `
            <b>${r.user_name || "Пользователь"}</b> <span class="rating-stars">${"★".repeat(r.rating || 0)}</span><br>
            ${(r.comment || "").replace(/</g, "&lt;")}<br>
            ${photosHtml}
            <small>${r.created_at ? new Date(r.created_at).toLocaleString() : ""}</small>
            ${deleteBtnHtml}
        `;
        el.reviewsList.appendChild(card);
    });
}

async function deleteReview(reviewId) {
    if (!reviewId) return;
    if (!confirm("Удалить свой отзыв?")) return;
    try {
        const result = await apiFetch(`/reviews/${reviewId}`, { method: "DELETE" });
        if (state.currentDistrictId) {
            await loadReviews(state.currentDistrictId);
            const stats = await apiFetch(`/districts/${state.currentDistrictId}/stats`);
            document.getElementById("finalScore").innerText = Number(stats.final_score || result.final_score || 0).toFixed(3);
            document.getElementById("avgRating").innerText = Number(stats.avg_rating || result.avg_rating || 0).toFixed(2);
        }
    } catch (e) {
        alert(`Ошибка удаления отзыва: ${e.message}`);
    }
}

async function showDistrictSidebar(featureProps, clickedLayer) {
    state.currentDistrictId = featureProps.id;

    if (state.selectedDistrictLayer && state.selectedDistrictLayer.feature) {
        state.selectedDistrictLayer.setStyle(styleDistrict(state.selectedDistrictLayer.feature));
    }
    state.selectedDistrictLayer = clickedLayer;
    clickedLayer.setStyle(highlightDistrictStyle(clickedLayer.feature));

    document.getElementById("districtName").innerText = featureProps.name || "Без названия";
    document.getElementById("displayMode").innerText = state.analyticsMode === "coarse" ? "Округ" : "Район";

    applySidebarAccess(!!state.user);


    try {
        const stats = await apiFetch(`/districts/${featureProps.id}/stats`);
        document.getElementById("baseScore").innerText = Number(stats.base_score || 0).toFixed(3);
        document.getElementById("finalScore").innerText = Number(stats.final_score || 0).toFixed(3);
        document.getElementById("districtArea").innerText = stats.area_km2 ? Number(stats.area_km2).toFixed(2) : "?";
        const statsGroupsEl = document.getElementById("statsGroups");
        const calculationDetailsEl = document.getElementById("calculationDetails");
        // if (statsGroupsEl) statsGroupsEl.innerHTML = renderStatsTable(stats.groups);
        if (calculationDetailsEl) {
            calculationDetailsEl.innerHTML = `${renderCalculationDetails(stats)}`;
        }
    } catch (e) {
        const calculationDetailsEl = document.getElementById("calculationDetails");
        if (calculationDetailsEl) calculationDetailsEl.innerHTML = "<p>Ошибка загрузки статистики</p>";
    }

    try {
        await loadReviews(featureProps.id);
    } catch (e) {
        if (el.reviewsList) el.reviewsList.innerHTML = "<h4>Отзывы:</h4><p>Ошибка загрузки.</p>";
    }

    if (el.districtSidebar) el.districtSidebar.style.display = "flex";
}

async function ensureAnalyticsLayer(mode) {
    if (state.layerCache[mode]) return state.layerCache[mode];

    setLoading(true, mode === "coarse" ? "Загрузка округов..." : "Загрузка районов...");
    const data = await apiFetch(`/districts/geojson?mode=${mode}`);
    const sortedFeatures = (data.features || []).sort((a, b) => (a.properties.admin_level || 0) - (b.properties.admin_level || 0));

    state.layerCache[mode] = L.geoJSON(sortedFeatures, {
        style: styleDistrict,
        onEachFeature: (feature, layer) => {
            layer.on("click", (e) => {
                showDistrictSidebar(feature.properties, layer);
                L.DomEvent.stopPropagation(e);
            });
        },
    });
    setLoading(false);
    return state.layerCache[mode];
}

async function switchToMode(mode) {
    state.appMode = mode;

    const searchPanel = document.getElementById("searchPanel");
    const analyticsSwitch = document.getElementById("analyticsModeSwitch");
    const modeNav = document.getElementById("modeNav");
    const modeAnalytics = document.getElementById("modeAnalytics");

    if (modeNav) modeNav.classList.toggle("active", mode === "nav");
    if (modeAnalytics) modeAnalytics.classList.toggle("active", mode === "analytics");
    if (searchPanel) searchPanel.style.display = mode === "nav" ? "flex" : "none";
    if (analyticsSwitch) analyticsSwitch.style.display = mode === "analytics" ? "flex" : "none";

    removeAllDistrictLayers();
    removeAnyDistrictGeoJSONFromMap();
    if (mode === "analytics") {
        clearNavigationMarkers();
    }
    closeSidebar();

    if (mode === "nav") {
        const navLayer = await ensureNavLayer();
        navLayer.addTo(map);
    } else {
        const analyticsLayer = await ensureAnalyticsLayer(state.analyticsMode);
        analyticsLayer.addTo(map);
    }
}

async function setAnalyticsMode(mode) {
    state.analyticsMode = mode;
    const modeDetailed = document.getElementById("modeDetailed");
    const modeCoarse = document.getElementById("modeCoarse");
    if (modeDetailed) modeDetailed.classList.toggle("active", mode === "detailed");
    if (modeCoarse) modeCoarse.classList.toggle("active", mode === "coarse");

    if (state.appMode === "analytics") {
        removeAllDistrictLayers();
        removeAnyDistrictGeoJSONFromMap();
        closeSidebar();
        const analyticsLayer = await ensureAnalyticsLayer(mode);
        analyticsLayer.addTo(map);
    }
}

function getIconForPlace(category, subclass) {
    let color = "#ff6200";
    let faIcon = "fa-map-marker-alt";
    const categoryMap = {
        amenity: {
            cafe: { color: "#d35400", icon: "fa-mug-hot" },
            restaurant: { color: "#e67e22", icon: "fa-utensils" },
            pub: { color: "#8e44ad", icon: "fa-beer" },
            bar: { color: "#8e44ad", icon: "fa-cocktail" },
            hospital: { color: "#e74c3c", icon: "fa-hospital" },
            pharmacy: { color: "#27ae60", icon: "fa-prescription-bottle" },
        },
        shop: { supermarket: { color: "#2ecc71", icon: "fa-shopping-cart" } },
        tourism: { hotel: { color: "#3498db", icon: "fa-hotel" } },
    };

    if (categoryMap[category] && categoryMap[category][subclass]) {
        color = categoryMap[category][subclass].color;
        faIcon = categoryMap[category][subclass].icon;
    }

    return L.divIcon({
        html: `<div style="background:${color}; width:30px; height:30px; border-radius:50%; display:flex; align-items:center; justify-content:center; border:2px solid white;"><i class="fas ${faIcon}" style="color:white; font-size:14px;"></i></div>`,
        iconSize: [30, 30],
        className: "custom-div-icon",
    });
}

function buildPopupContent(place) {
    const safeName = (place.name || "").replace(/'/g, "\\'").replace(/</g, "&lt;");
    let content = `<b>${safeName || "Без названия"}</b><br>`;
    content += `🏷️ ${place.category || "-"} -> ${place.subclass || "-"}<br>`;

    if (state.currentCenter) {
        content += `<br><button onclick="window.routeToPlace(${place.lat}, ${place.lon}, '${safeName}')" style="background:#3498db;color:#fff;border:none;padding:6px 10px;border-radius:6px;cursor:pointer;">🚗 Маршрут</button>`;
    } else {
        content += "<br><i>Кликните по карте, чтобы поставить точку А</i>";
    }
    return content;
}

async function getRoute(startLat, startLon, endLat, endLon, placeName) {
    clearRoute();
    const url = `https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${endLon},${endLat}?overview=full&geometries=geojson`;
    const response = await fetch(url);
    const data = await response.json();
    if (data.code !== "Ok" || !data.routes || !data.routes.length) {
        throw new Error("Невозможно проложить маршрут");
    }

    const route = data.routes[0];
    const coords = route.geometry.coordinates.map((c) => [c[1], c[0]]);
    const distanceKm = (route.distance / 1000).toFixed(1);
    const durationMin = Math.round(route.duration / 60);

    state.routeLayer = L.polyline(coords, { color: "#08ff00", weight: 8, opacity: 0.75 }).addTo(map);
    state.routeStartMarker = L.marker([startLat, startLon], {
        icon: L.divIcon({ className: "route-start-marker", html: "🚩", iconSize: [20, 20] }),
    }).addTo(map);
    state.routeEndMarker = L.marker([endLat, endLon], {
        icon: L.divIcon({ className: "route-end-marker", html: "🏁", iconSize: [20, 20] }),
    }).addTo(map);

    L.popup().setLatLng([endLat, endLon]).setContent(`<b>${placeName || "Пункт назначения"}</b><br>🚗 ${distanceKm} км, ~${durationMin} мин`).openOn(map);
    map.fitBounds(state.routeLayer.getBounds(), { padding: [30, 30] });
}

window.routeToPlace = async function routeToPlace(lat, lon, placeName) {
    if (!state.currentCenter) {
        alert("Сначала задайте точку А");
        return;
    }
    try {
        await getRoute(state.currentCenter.lat, state.currentCenter.lng, lat, lon, placeName);
    } catch (e) {
        alert(e.message || "Ошибка маршрутизации");
    }
};

function displayResults(places) {
    clearMarkers();
    if (!places || !places.length) {
        alert("Ничего не найдено");
        return;
    }

    (places || []).forEach((place) => {
        const marker = L.marker([place.lat, place.lon], { icon: getIconForPlace(place.category, place.subclass) });
        marker.bindPopup(buildPopupContent(place));
        state.clusterGroup.addLayer(marker);
    });

    const bounds = L.latLngBounds(places.map((p) => [p.lat, p.lon]));
    map.fitBounds(bounds, { padding: [30, 30] });
}

async function performSearch(endpoint, params) {
    const radiusType = document.getElementById("radiusType")?.value || "custom";

    if (radiusType !== "district" && radiusType !== "neighbors" && !state.currentCenter) {
        alert("Сначала задайте точку отсчета");
        return;
    }

    try {
        if (radiusType === "custom") {
            const radius = parseFloat(document.getElementById("radiusInput")?.value || "1000");
            const body = {
                ...params,
                lat: state.currentCenter.lat,
                lon: state.currentCenter.lng,
                radius,
            };
            const data = await apiFetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            displayResults(data.results || []);
            return;
        }

        const found = await apiFetch("/find_district_by_point", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat: state.currentCenter.lat, lon: state.currentCenter.lng }),
        });
        if (!found.district_id) {
            alert("Точка отсчета не принадлежит ни одному району");
            return;
        }

        const targetEndpoint = radiusType === "neighbors" ? "/search/within_district_and_neighbors" : "/search/within_district";
        const data = await apiFetch(targetEndpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ district_id: found.district_id, ...params }),
        });
        displayResults(data.results || []);
    } catch (e) {
        alert(`Ошибка поиска: ${e.message}`);
    }
}

async function geocodeAddress(address) {
    const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}&limit=1`;
    const response = await fetch(url, { headers: { "Accept-Language": "ru" } });
    const data = await response.json();
    if (!data || !data.length) throw new Error("Адрес не найден");

    const lat = parseFloat(data[0].lat);
    const lon = parseFloat(data[0].lon);
    state.currentCenter = L.latLng(lat, lon);
    map.setView(state.currentCenter, 14);

    if (state.centerMarker) map.removeLayer(state.centerMarker);
    state.centerMarker = L.circleMarker(state.currentCenter, { color: "#e74c3c", radius: 6 }).addTo(map);
    state.centerMarker.bindPopup("Точка отсчета").openPopup();
    clearRoute();
}

async function submitReview() {
    if (!state.currentDistrictId) {
        alert("Сначала выберите район");
        return;
    }
    if (!state.token) {
        alert("Для отзыва нужно войти в аккаунт");
        return;
    }

    const files = state.reviewPhotos.slice();
    if (files.length > 10) {
        alert("Можно прикрепить до 10 фото");
        return;
    }

    const formData = new FormData();
    formData.append("district_id", String(state.currentDistrictId));
    formData.append("rating", String(parseInt(el.reviewRating?.value || "3", 10)));
    formData.append("comment", (el.reviewComment?.value || "").trim());
    files.forEach((f) => formData.append("photos", f));

    try {
        await apiFetch("/reviews", { method: "POST", body: formData });
        if (el.reviewComment) el.reviewComment.value = "";
        resetReviewPhotos();

        await loadReviews(state.currentDistrictId);
        const stats = await apiFetch(`/districts/${state.currentDistrictId}/stats`);
        document.getElementById("finalScore").innerText = Number(stats.final_score || 0).toFixed(3);
        document.getElementById("avgRating").innerText = Number(stats.avg_rating || 0).toFixed(2);
        alert("Отзыв сохранен");
    } catch (e) {
        alert(`Ошибка отправки отзыва: ${e.message}`);
    }
}

bindClick("modeNav", () => switchToMode("nav"));
bindClick("modeAnalytics", () => switchToMode("analytics"));
bindClick("modeDetailed", () => setAnalyticsMode("detailed"));
bindClick("modeCoarse", () => setAnalyticsMode("coarse"));
bindClick("closeSidebar", closeSidebar);
bindClick("clearMarkers", () => {
    clearMarkers();
    clearRoute();
});

bindClick("geocodeBtn", async () => {
    const address = (document.getElementById("geocoderInput")?.value || "").trim();
    if (!address) {
        alert("Введите адрес");
        return;
    }
    try {
        await geocodeAddress(address);
    } catch (e) {
        alert(e.message || "Ошибка геокодирования");
    }
});

bindClick("searchCategory", () => {
    const category = (document.getElementById("searchInput")?.value || "").trim();
    if (!category) {
        alert("Введите категорию");
        return;
    }
    performSearch("/search/category", { category });
});

bindClick("searchName", () => {
    const name = (document.getElementById("searchInput")?.value || "").trim();
    if (!name) {
        alert("Введите название");
        return;
    }
    performSearch("/search/name", { name });
});

bindClick("submitReview", submitReview);
bindClick("registerBtn", () => openAuthModal("register"));
bindClick("loginBtn", () => openAuthModal("login"));
bindClick("logoutBtn", logoutUser);
bindClick("authSubmitBtn", submitAuthForm);
bindClick("authSwitchBtn", () => openAuthModal(state.authMode === "login" ? "register" : "login"));
bindClick("authModalClose", closeAuthModal);
bindClick("photoModalClose", closePhotoModal);

if (el.reviewPhotos) {
    el.reviewPhotos.setAttribute("multiple", "multiple");
    el.reviewPhotos.addEventListener("change", (e) => {
        addReviewPhotos(e.target.files);
        e.target.value = "";
    });
}

if (el.reviewPhotosPreview) {
    el.reviewPhotosPreview.addEventListener("click", (e) => {
        const removeBtn = e.target.closest("button[data-review-photo-index]");
        if (!removeBtn) return;
        const index = parseInt(removeBtn.dataset.reviewPhotoIndex, 10);
        if (Number.isNaN(index)) return;
        for (const url of state.reviewPhotoUrls.values()) {
            try { URL.revokeObjectURL(url); } catch (err) {}
        }
        state.reviewPhotoUrls.clear();
        state.reviewPhotos.splice(index, 1);
        syncReviewPhotosInput();
        renderReviewPhotosPreview();
    });
}

if (el.authModalClose) {
    el.authModalClose.addEventListener("click", closeAuthModal);
}

if (el.authModalOverlay) {
    el.authModalOverlay.addEventListener("click", (e) => {
        if (e.target === el.authModalOverlay) closeAuthModal();
    });
}

if (el.photoModalOverlay) {
    el.photoModalOverlay.addEventListener("click", (e) => {
        if (e.target === el.photoModalOverlay) closePhotoModal();
    });
}

if (el.reviewsList) {
    el.reviewsList.addEventListener("click", (e) => {
        const deleteBtn = e.target.closest("button.review-delete-btn");
        if (deleteBtn) {
            const reviewId = parseInt(deleteBtn.dataset.reviewId, 10);
            if (!Number.isNaN(reviewId)) {
                deleteReview(reviewId);
            }
            return;
        }

        const img = e.target.closest("img.review-photo-thumb");
        if (img) {
            openPhotoModal(img.dataset.fullsrc || img.src, img.alt || "Фото");
        }
    });
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && el.photoModalOverlay && el.photoModalOverlay.classList.contains("visible")) {
        closePhotoModal();
        return;
    }
    if (e.key === "Escape") {
        closeAuthModal();
    }
    if (e.key === "Enter" && el.authModalOverlay && el.authModalOverlay.classList.contains("visible")) {
        const active = document.activeElement;
        if (active && ["INPUT", "BUTTON"].includes(active.tagName)) {
            e.preventDefault();
            submitAuthForm();
        }
    }
});

map.on("click", (e) => {
    if (state.appMode !== "nav") return;

    state.currentCenter = e.latlng;
    if (state.centerMarker) map.removeLayer(state.centerMarker);
    state.centerMarker = L.circleMarker(state.currentCenter, { color: "#e74c3c", radius: 6 }).addTo(map);
    state.centerMarker.bindPopup("Точка отсчета").openPopup();
    clearRoute();
});

map.on("click", closeSidebar);

(async function init() {
    clearMarkers();
    await loadCurrentUser();
    await setAnalyticsMode("detailed");
    await switchToMode("nav");

    // Прогреваем кэш аналитики в фоне, не блокируя старт карты.
    setTimeout(() => {
        ensureAnalyticsLayer("detailed").catch(() => null);
        ensureAnalyticsLayer("coarse").catch(() => null);
    }, 250);
})();




