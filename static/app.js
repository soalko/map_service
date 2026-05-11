// ---------- Initialize map ----------
var map = L.map('map', { attributionControl: false }).setView([55.7558, 37.6173], 10);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

L.control.attribution({
    position: 'bottomright',
    prefix: false
}).addTo(map).addAttribution('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors');

// ---------- Global variables ----------
var clusterGroup = null;
var centerMarker = null;
var currentCenter = null;
var lastSearchResults = [];
var currentRouteLayer = null;      // polyline
var currentRouteStartMarker = null;
var currentRouteEndMarker = null;
var currentMarkersMap = new Map();

// ---------- Category icon mapping (unchanged) ----------
function getIconForPlace(category, subclass) {
    let color = '#ff6200';
    let faIcon = 'fa-map-marker-alt';
    const categoryMap = {
        'amenity': {
            'cafe': { color: '#d35400', icon: 'fa-mug-hot' },
            'restaurant': { color: '#e67e22', icon: 'fa-utensils' },
            'pub': { color: '#8e44ad', icon: 'fa-beer' },
            'bar': { color: '#8e44ad', icon: 'fa-cocktail' },
            'fast_food': { color: '#f39c12', icon: 'fa-hamburger' },
            'cinema': { color: '#3498db', icon: 'fa-film' },
            'theatre': { color: '#9b59b6', icon: 'fa-mask' },
            'museum': { color: '#e74c3c', icon: 'fa-landmark' },
            'library': { color: '#2c3e50', icon: 'fa-book' },
            'hospital': { color: '#e74c3c', icon: 'fa-hospital' },
            'pharmacy': { color: '#27ae60', icon: 'fa-prescription-bottle' },
            'bank': { color: '#f1c40f', icon: 'fa-university' }
        },
        'shop': {
            'supermarket': { color: '#2ecc71', icon: 'fa-shopping-cart' },
            'bakery': { color: '#f39c12', icon: 'fa-bread-slice' },
            'clothes': { color: '#9b59b6', icon: 'fa-tshirt' }
        },
        'tourism': {
            'hotel': { color: '#3498db', icon: 'fa-hotel' },
            'attraction': { color: '#e84393', icon: 'fa-camera' },
            'museum': { color: '#e74c3c', icon: 'fa-landmark' },
            'viewpoint': { color: '#1abc9c', icon: 'fa-eye' }
        },
        'leisure': {
            'park': { color: '#2ecc71', icon: 'fa-tree' },
            'garden': { color: '#2ecc71', icon: 'fa-leaf' }
        }
    };
    if (categoryMap[category] && categoryMap[category][subclass]) {
        color = categoryMap[category][subclass].color;
        faIcon = categoryMap[category][subclass].icon;
    } else if (categoryMap[category]) {
        color = '#95a5a6';
        faIcon = 'fa-tag';
    }
    const html = `<div style="background-color: ${color}; width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 2px solid white; box-shadow: 0 0 5px rgba(0,0,0,0.5);"><i class="fas ${faIcon}" style="color: white; font-size: 14px;"></i></div>`;
    return L.divIcon({
        html: html,
        iconSize: [30, 30],
        className: 'custom-div-icon'
    });
}

// ---------- Clear route completely ----------
function clearRoute() {
    if (currentRouteLayer) {
        map.removeLayer(currentRouteLayer);
        currentRouteLayer = null;
    }
    if (currentRouteStartMarker) {
        map.removeLayer(currentRouteStartMarker);
        currentRouteStartMarker = null;
    }
    if (currentRouteEndMarker) {
        map.removeLayer(currentRouteEndMarker);
        currentRouteEndMarker = null;
    }
}

// ---------- Fetch and draw route (non‑interactive) ----------
async function getRoute(startLat, startLon, endLat, endLon, placeName) {
    clearRoute(); // remove previous route

    const url = `https://router.project-osrm.org/route/v1/driving/${startLon},${startLat};${endLon},${endLat}?overview=full&geometries=geojson`;

    try {
        const response = await fetch(url);
        const data = await response.json();
        if (data.code !== 'Ok' || !data.routes || data.routes.length === 0) {
            alert('Невозможно проложить маршрут между этими точками.');
            return;
        }
        const route = data.routes[0];
        const distanceKm = (route.distance / 1000).toFixed(1);
        const durationMin = Math.round(route.duration / 60);
        const coordinates = route.geometry.coordinates.map(coord => [coord[1], coord[0]]);

        // Draw route line (non‑interactive so it doesn't block clicks)
        currentRouteLayer = L.polyline(coordinates, {
            color: '#2c3e50',
            weight: 5,
            opacity: 0.7,
            dashArray: '10, 10',
            interactive: false   // CRITICAL: allows clicking through to markers
        }).addTo(map);

        // Add start and end markers (also non‑interactive)
        currentRouteStartMarker = L.marker([startLat, startLon], {
            icon: L.divIcon({ className: 'route-start-marker', html: '🚩', iconSize: [20,20] }),
            interactive: false
        }).addTo(map);

        currentRouteEndMarker = L.marker([endLat, endLon], {
            icon: L.divIcon({ className: 'route-end-marker', html: '🏁', iconSize: [20,20] }),
            interactive: false
        }).addTo(map);

        // Show info popup at destination
        L.popup()
            .setLatLng([endLat, endLon])
            .setContent(`<b>${placeName || 'Destination'}</b><br>🚗 ${distanceKm} km, ${durationMin} min`)
            .openOn(map);

        map.fitBounds(currentRouteLayer.getBounds(), { padding: [30,30] });

    } catch (err) {
        console.error(err);
        alert('Routing service error. Please try again.');
    }
}

window.routeToPlace = function(lat, lon, name) {
    if (!currentCenter) {
        alert('Пожалуйста, задайте центр построения маршрута.');
        return;
    }
    getRoute(currentCenter.lat, currentCenter.lng, lat, lon, name);
};

// ---------- Rich popup content ----------
function buildPopupContent(place) {
    let content = `<b>${place.name || 'Unnamed place'}</b><br>`;
    content += `📏 Distance: ${place.distance ? place.distance.toFixed(0) : '?'} m<br>`;
    content += `🏷️ ${place.category} → ${place.subclass}<br>`;

    const tags = place.tags || {};
    let hoursHtml = '';

    // Address
    if (tags['addr:street'] || tags['addr:housenumber']) {
        let address = '';
        if (tags['addr:street']) address += tags['addr:street'];
        if (tags['addr:housenumber']) address += ' ' + tags['addr:housenumber'];
        if (tags['addr:city']) address += ', ' + tags['addr:city'];
        content += `📍 <i>${address}</i><br>`;
    }

    if (tags['opening_hours']) {
        let hours = tags['opening_hours'];
        if (hours === '24/7') hours = '🕒 Open 24/7';
        else if (hours === 'off') hours = '🚫 Permanently closed';
        else hours = `🕒 ${hours}`;
        content += `${hours}<br>`;
    }

    if (tags['phone']) content += `📞 <a href="tel:${tags['phone']}">${tags['phone']}</a><br>`;
    if (tags['website']) content += `🌐 <a href="${tags['website']}" target="_blank">Website</a><br>`;
    if (tags['wheelchair'] === 'yes') content += `♿ Wheelchair accessible<br>`;
    else if (tags['wheelchair'] === 'no') content += `🚫 Not wheelchair accessible<br>`;

    // Directions button
    if (currentCenter) {
        content += `<br><button onclick="window.routeToPlace(${place.lat}, ${place.lon}, '${place.name?.replace(/'/g, "\\'") || ''}')" style="background:#3498db; color:white; border:none; padding:5px 10px; border-radius:4px; cursor:pointer;">🚗 Directions from search center</button>`;
    } else {
        content += `<br><i>Click on the map to set a start point first</i>`;
    }
    return content;
}

// ---------- Sidebar rendering (same as before, no change) ----------
function showSidebar(places) {
    const sidebar = document.getElementById('resultsSidebar');
    const resultsList = document.getElementById('resultsList');
    const resultCountSpan = document.getElementById('resultCount');
    if (!places || places.length === 0) {
        sidebar.style.display = 'none';
        return;
    }
    const sorted = [...places].sort((a,b) => (a.distance || Infinity) - (b.distance || Infinity));
    resultCountSpan.innerText = sorted.length;
    resultsList.innerHTML = '';
    sorted.forEach(place => {
        const card = document.createElement('div');
        card.className = 'result-card';
        const distanceText = place.distance ? `${place.distance.toFixed(0)} m` : '? m';
        card.innerHTML = `
        <h4>${escapeHtml(place.name || 'Unnamed place')}</h4>
        <p><span class="distance">📏 ${distanceText}</span> &nbsp; 🏷️ ${place.category} → ${place.subclass}</p>
        <button class="directions-btn-card" data-lat="${place.lat}" data-lon="${place.lon}" data-name="${escapeHtml(place.name || '')}">🚗 Directions from search center</button>
        `;
        card.addEventListener('click', (e) => {
            if (e.target.classList && e.target.classList.contains('directions-btn-card')) return;
            const marker = currentMarkersMap.get(place.id || `${place.lat},${place.lon}`);
            if (marker) {
                map.setView([place.lat, place.lon], 16);
                marker.openPopup();
            } else {
                map.setView([place.lat, place.lon], 16);
            }
        });
        const btn = card.querySelector('.directions-btn-card');
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const lat = parseFloat(btn.dataset.lat);
            const lon = parseFloat(btn.dataset.lon);
            const name = btn.dataset.name;
            window.routeToPlace(lat, lon, name);
        });
        resultsList.appendChild(card);
    });
    sidebar.style.display = 'flex';
}

function closeSidebar() {
    document.getElementById('resultsSidebar').style.display = 'none';
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

// ---------- Marker clustering and display ----------
function clearMarkers() {
    if (clusterGroup) {
        map.removeLayer(clusterGroup);
    }
    clusterGroup = L.markerClusterGroup({
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        zoomToBoundsOnClick: true,
        maxClusterRadius: 50
    });
    map.addLayer(clusterGroup);
    currentMarkersMap.clear();
}

function displayResults(places) {
    clearMarkers();
    lastSearchResults = places;
    places.forEach(place => {
        const icon = getIconForPlace(place.category, place.subclass);
        const marker = L.marker([place.lat, place.lon], { icon: icon });
        marker.bindPopup(buildPopupContent(place));
        clusterGroup.addLayer(marker);
        const key = place.id || `${place.lat},${place.lon}`;
        currentMarkersMap.set(key, marker);
    });
    if (places.length > 0) {
        const bounds = L.latLngBounds(places.map(p => [p.lat, p.lon]));
        map.fitBounds(bounds, { padding: [30, 30] });
    }
    showSidebar(places);
}

// ---------- Search functions ----------
async function performSearch(endpoint, params) {
    if (!currentCenter) {
        alert('Пожалуйста, задайте центр поиска.');
        return;
    }
    params.lat = currentCenter.lat;
    params.lon = currentCenter.lng;
    params.radius = parseFloat(document.getElementById('radiusInput').value);

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
        const data = await response.json();
        displayResults(data.results);
        clearRoute();   // remove any existing route
    } catch (err) {
        alert('Search error: ' + err);
    }
}

// ---------- Geocoding ----------
async function geocodeAddress(address) {
    const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}&limit=1`;
    try {
        const response = await fetch(url, {
            headers: { 'User-Agent': 'InterestingPlacesApp/1.0' }
        });
        const data = await response.json();
        if (data && data.length > 0) {
            const lat = parseFloat(data[0].lat);
            const lon = parseFloat(data[0].lon);
            currentCenter = L.latLng(lat, lon);
            map.setView(currentCenter, 14);
            if (centerMarker) map.removeLayer(centerMarker);
            centerMarker = L.circleMarker(currentCenter, { color: 'red', radius: 5 }).addTo(map);
            centerMarker.bindPopup('Центр поиска').openPopup();
            clearRoute();
        } else {
            alert('Address not found');
        }
    } catch (err) {
        alert('Geocoding failed: ' + err);
    }
}


// ---------- Event listeners ----------
map.on('click', function(e) {
    currentCenter = e.latlng;
    if (centerMarker) map.removeLayer(centerMarker);
    centerMarker = L.circleMarker(currentCenter, { color: 'red', radius: 5 }).addTo(map);
    centerMarker.bindPopup('Центр поиска').openPopup();
    clearRoute();
});

document.getElementById('searchCategory').addEventListener('click', () => {
    const category = document.getElementById('searchInput').value.trim();
    if (!category) return alert('Введите категорию');
    performSearch('/search/category', { category: category });
});

document.getElementById('searchName').addEventListener('click', () => {
    const name = document.getElementById('searchInput').value.trim();
    if (!name) return alert('Введите название места');
    performSearch('/search/name', { name: name });
});

document.getElementById('geocodeBtn').addEventListener('click', () => {
    const address = document.getElementById('geocoderInput').value.trim();
    if (!address) return alert('Введите название места');
    geocodeAddress(address);
});

document.getElementById('exportGeoJSON').addEventListener('click', exportGeoJSON);

document.getElementById('clearMarkers').addEventListener('click', () => {
    clearMarkers();
    lastSearchResults = [];
    clearRoute();
    closeSidebar();
});

document.getElementById('closeSidebar').addEventListener('click', closeSidebar);

// Initialise
clearMarkers();