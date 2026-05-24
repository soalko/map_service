from pathlib import Path
import hashlib
import os
import secrets
import json

from fastapi import FastAPI, Depends, HTTPException, Header, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, selectinload
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from . import crud, schemas
from .database import SessionLocal, engine, Base
from . import models
from sqlalchemy import func, or_, inspect
from geoalchemy2.functions import ST_AsGeoJSON
from shapely import wkb
from shapely.ops import transform
import pyproj
from .update_stats import recalc_all_stats
from geoalchemy2.functions import ST_Within, ST_AsText

app = FastAPI(title="Interesting Places API")

# Mount static files for frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_REVIEW_DIR = Path("static/uploads/reviews")
UPLOAD_REVIEW_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_review_user_column()


def ensure_review_user_column():
    inspector = inspect(engine)
    review_columns = {col["name"] for col in inspector.get_columns("reviews")}
    if "user_id" not in review_columns:
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE reviews ADD COLUMN IF NOT EXISTS user_id INTEGER")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_reviews_user_id ON reviews (user_id)")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Return simpler validation errors as a list of human-readable messages."""
    errors = exc.errors()
    messages = []
    for err in errors:
        loc = ".".join([str(x) for x in err.get("loc", [])])
        msg = err.get("msg", "")
        messages.append(f"{loc}: {msg}")
    return JSONResponse(status_code=422, content={"detail": messages})


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${pwd_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, stored_hash = password_hash.split("$", 1)
    except ValueError:
        return False
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return secrets.compare_digest(pwd_hash, stored_hash)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db)
) -> models.User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    user = db.query(models.User).filter(models.User.auth_token == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


def get_current_user_optional(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db)
) -> models.User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return db.query(models.User).filter(models.User.auth_token == token).first()


def is_review_owner(review: models.Review, user: models.User | None) -> bool:
    if not user:
        return False
    if review.user_id == user.id:
        return True
    if review.user_id is None and review.user_name:
        candidate = review.user_name.strip().lower()
        possible_names = {user.username.strip().lower()}
        if user.display_name:
            possible_names.add(user.display_name.strip().lower())
        return candidate in possible_names
    return False


def serialize_review(review: models.Review, current_user: models.User | None = None) -> dict:
    return {
        "id": review.id,
        "district_id": review.district_id,
        "user_id": review.user_id,
        "user_name": review.user_name,
        "rating": review.rating,
        "comment": review.comment,
        "created_at": review.created_at,
        "is_mine": is_review_owner(review, current_user),
        "photos": [
            {"id": photo.id, "file_path": photo.file_path}
            for photo in (review.photos or [])
        ],
    }


def save_uploaded_review_photos(files: list[UploadFile]) -> list[str]:
    saved_paths: list[str] = []
    for file in files:
        if not file or not file.filename:
            continue
        content_type = (file.content_type or "").lower()
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")
        ext = os.path.splitext(file.filename)[1].lower() or ".jpg"
        filename = f"{secrets.token_hex(16)}{ext}"
        dst_path = UPLOAD_REVIEW_DIR / filename
        with open(dst_path, "wb") as out:
            out.write(file.file.read())
        saved_paths.append(f"/static/uploads/reviews/{filename}")
    return saved_paths


def recalc_district_review_adjustment(db: Session, district_id: int):
    avg_rating = db.query(func.avg(models.Review.rating)).filter(
        models.Review.district_id == district_id
    ).scalar() or 3.0
    avg_rating = float(avg_rating)
    k_user = 0.8 + (avg_rating - 1) * 0.1

    stats = db.query(models.DistrictStats).filter(models.DistrictStats.district_id == district_id).first()
    if stats:
        stats.k_user = k_user
        stats.final_score = float(stats.base_score or 0.0) * k_user

    district = db.query(models.District).filter(models.District.id == district_id).first()
    if district:
        district.final_score = float(district.base_score or 0.0) * k_user


def expand_category_terms(category: str) -> set[str]:
    raw = (category or "").strip().lower()
    terms = {raw}
    terms.update(crud.RU_CATEGORY_MAP.get(raw, []))
    return {t for t in terms if t}


@app.post("/search/category", response_model=schemas.SearchResponse)
def search_by_category(request: schemas.CategorySearch, db: Session = Depends(get_db)):
    places = crud.get_places_by_category(db, request.lat, request.lon, request.radius, request.category)
    return {"results": places}


@app.post("/search/name", response_model=schemas.SearchResponse)
def search_by_name(request: schemas.NameSearch, db: Session = Depends(get_db)):
    places = crud.get_places_by_name(db, request.lat, request.lon, request.radius, request.name)
    return {"results": places}


@app.post("/search/within_district_and_neighbors")
def search_within_district_and_neighbors(request: dict, db: Session = Depends(get_db)):
    district_id = request.get("district_id")
    category = request.get("category")
    name = request.get("name")
    if not district_id:
        raise HTTPException(400, "Missing district_id")

    # Получаем целевой район
    target_district = db.query(models.District).filter(models.District.id == district_id).first()
    if not target_district:
        raise HTTPException(404, "District not found")

    # Находим соседние районы (ST_Touches)
    neighbors = db.query(models.District).filter(
        models.District.admin_level >= 8,
        models.District.id != district_id,
        func.ST_Touches(target_district.geom, models.District.geom)
    ).all()

    # Собираем геометрии всех районов (целевой + соседи)
    all_geoms = [target_district.geom] + [n.geom for n in neighbors]

    # Объединяем геометрии в один мультиполигон (или выполняем UNION)
    # Для простоты будем проверять принадлежность POI любому из полигонов через OR
    query = db.query(models.Place).filter(
        func.ST_Within(models.Place.geom, target_district.geom) |
        func.ST_Within(models.Place.geom, func.ST_Union(*all_geoms))
    )

    all_geom = db.query(func.ST_Collect(models.District.geom)).filter(
        models.District.id.in_([district_id] + [n.id for n in neighbors])
    ).scalar()
    if all_geom:
        query = db.query(models.Place).filter(func.ST_Within(models.Place.geom, all_geom))
    else:
        query = db.query(models.Place).filter(func.ST_Within(models.Place.geom, target_district.geom))

    if category:
        terms = expand_category_terms(category)
        filters = []
        for term in terms:
            filters.extend([
                models.Place.category.ilike(term),
                models.Place.subclass.ilike(term),
            ])
        query = query.filter(or_(*filters))
    if name:
        query = query.filter(models.Place.name.ilike(f"%{name}%"))

    places = query.all()
    results = []
    for p in places:
        results.append({
            "id": p.id, "osm_id": p.osm_id, "name": p.name,
            "lat": p.lat, "lon": p.lon, "category": p.category,
            "subclass": p.subclass, "tags": p.tags, "distance": 0.0
        })
    return {"results": results}


def get_area_km2_from_geom(geom):
    """Вспомогательная функция – перепроецирует и возвращает площадь в км²."""
    transformer = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    geom_proj = transform(transformer.transform, geom)
    return geom_proj.area / 1_000_000.0


@app.get("/districts/geojson")
def get_districts_geojson(mode: str = "detailed", db: Session = Depends(get_db)):
    # Выбираем районы по режиму
    if mode == "detailed":
        districts = db.query(models.District).filter(models.District.admin_level >= 8).all()
    else:
        districts = db.query(models.District).filter(models.District.admin_level < 8).all()

    # Получаем статистику для всех районов (словарь)
    stats_rows = db.query(models.DistrictStats).all()
    stats_dict = {s.district_id: s for s in stats_rows}

    features = []
    for dist in districts:
        geom = wkb.loads(bytes(dist.geom.data))
        stats = stats_dict.get(dist.id)
        if stats:
            base_score = float(stats.base_score or 0.0)
            final_score = float(stats.final_score or 0.0)
            area_km2 = dist.area_km2 if dist.area_km2 > 0 else (geom.area / 1e6)
        else:
            # Если статистики нет, используем 0
            base_score = 0.0
            final_score = 0.0
            area_km2 = dist.area_km2 if dist.area_km2 > 0 else (geom.area / 1e6)

        # Разбивка мультиполигонов для корректной отрисовки
        if geom.geom_type == 'MultiPolygon':
            for poly in geom.geoms:
                coords = list(poly.exterior.coords)
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {
                        "id": dist.id,
                        "name": dist.name,
                        "base_score": base_score,
                        "final_score": final_score,
                        "admin_level": dist.admin_level,
                        "area_km2": area_km2,
                        "mode": mode
                    }
                })
        else:
            geom_str = db.scalar(ST_AsGeoJSON(dist.geom))
            geom_dict = json.loads(geom_str)
            features.append({
                "type": "Feature",
                "geometry": geom_dict,
                "properties": {
                    "id": dist.id,
                    "name": dist.name,
                    "base_score": base_score,
                    "final_score": final_score,
                    "admin_level": dist.admin_level,
                    "area_km2": area_km2,
                    "mode": mode
                }
            })

    return {"type": "FeatureCollection", "features": features}


@app.get("/districts/geojson/{level}")
def get_districts_geojson_by_level(level: str, db: Session = Depends(get_db)):
    mode = "detailed" if level == "small" else "coarse"
    return get_districts_geojson(mode=mode, db=db)


@app.get("/districts/{district_id}/stats")
def get_district_stats(district_id: int, db: Session = Depends(get_db)):
    district = db.query(models.District).filter(models.District.id == district_id).first()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")
    stats = db.query(models.DistrictStats).filter(
        models.DistrictStats.district_id == district_id
    ).first()
    if not stats:
        raise HTTPException(status_code=404, detail="Stats not found (run update_stats first)")

    area_km2 = district.area_km2 if district.area_km2 > 0 else 0.0

    # Вычисляем средний рейтинг по отзывам
    avg_rating = db.query(func.avg(models.Review.rating)).filter(
        models.Review.district_id == district_id
    ).scalar() or 3.0
    avg_rating = float(avg_rating)

    groups_config = {
        'social': {'weight': 0.30, 'density': stats.social_density, 'norm': stats.social_norm,
                   'norm_logcnt': stats.social_norm_logcnt, 'score': stats.social_score},
        'shops': {'weight': 0.25, 'density': stats.shops_density, 'norm': stats.shops_norm,
                  'norm_logcnt': stats.shops_norm_logcnt, 'score': stats.shops_score},
        'tourism': {'weight': 0.25, 'density': stats.tourism_density, 'norm': stats.tourism_norm,
                    'norm_logcnt': stats.tourism_norm_logcnt, 'score': stats.tourism_score},
        'leisure': {'weight': 0.20, 'density': stats.leisure_density, 'norm': stats.leisure_norm,
                    'norm_logcnt': stats.leisure_norm_logcnt, 'score': stats.leisure_score},
    }

    groups_data = {}
    for key, cfg in groups_config.items():
        density = cfg['density'] or 0.0
        cnt = density * area_km2 if area_km2 > 0 else 0
        groups_data[key] = {
            'count': round(cnt, 0),
            'density': round(density, 2),
            'weight': cfg['weight'],
            'norm_density': round(cfg['norm'] or 0.0, 4),
            'norm_logcnt': round(cfg['norm_logcnt'] or 0.0, 4),
            'score': round(cfg['score'] or 0.0, 4),
        }


    return {
        'area_km2': area_km2,
        'groups': groups_data,
        'base_score': float(stats.base_score or 0.0),
        'avg_rating': avg_rating,
        'k_user': float(stats.k_user or 1.0),
        'final_score': float(stats.final_score or 0.0),
        'alpha': 0.5
    }


@app.get("/districts/boundaries")
def get_district_boundaries(db: Session = Depends(get_db)):
    districts = db.query(models.District).filter(models.District.admin_level >= 8).all()
    features = []
    for d in districts:
        geom = wkb.loads(bytes(d.geom.data))
        if geom.geom_type == 'MultiPolygon':
            for poly in geom.geoms:
                coords = list(poly.exterior.coords)
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {"id": d.id, "name": d.name}
                })
        else:
            geom_str = db.scalar(ST_AsGeoJSON(d.geom))
            geom_dict = json.loads(geom_str)
            features.append({"type": "Feature", "geometry": geom_dict, "properties": {"id": d.id, "name": d.name}})
    return {"type": "FeatureCollection", "features": features}


@app.post("/reviews", response_model=schemas.Review)
def add_review(
    district_id: int = Form(...),
    rating: int = Form(...),
    comment: str | None = Form(default=None),
    photos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating should be in range 1..5")
    if len(photos) > 10:
        raise HTTPException(status_code=400, detail="You can attach up to 10 photos")

    district = db.query(models.District).filter(models.District.id == district_id).first()
    if not district:
        raise HTTPException(status_code=404, detail="District not found")

    new_review = models.Review(
        district_id=district_id,
        user_id=current_user.id,
        user_name=current_user.display_name or current_user.username,
        rating=rating,
        comment=comment,
    )
    db.add(new_review)
    db.flush()

    saved_paths = save_uploaded_review_photos(photos)
    for path in saved_paths:
        db.add(models.ReviewPhoto(review_id=new_review.id, file_path=path))

    recalc_district_review_adjustment(db, district_id)
    db.commit()
    db.refresh(new_review)
    db.refresh(new_review, attribute_names=["photos"])
    return serialize_review(new_review, current_user)


@app.get("/reviews/{district_id}")
def get_reviews(district_id: int, db: Session = Depends(get_db), current_user: models.User | None = Depends(get_current_user_optional)):
    reviews = db.query(models.Review).options(selectinload(models.Review.photos)).filter(
        models.Review.district_id == district_id
    ).order_by(models.Review.created_at.desc()).all()
    avg_rating = db.query(func.avg(models.Review.rating)).filter(
        models.Review.district_id == district_id
    ).scalar() or 0
    avg_rating = float(avg_rating) if avg_rating else 0.0
    return {"reviews": [serialize_review(r, current_user) for r in reviews], "avg_rating": avg_rating}


@app.delete("/reviews/{review_id}")
def delete_review(review_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    review = db.query(models.Review).options(selectinload(models.Review.photos)).filter(
        models.Review.id == review_id
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if not is_review_owner(review, current_user):
        raise HTTPException(status_code=403, detail="You can delete only your own reviews")

    district_id = review.district_id
    photo_paths = [photo.file_path for photo in (review.photos or [])]
    db.delete(review)
    db.flush()

    recalc_district_review_adjustment(db, district_id)
    db.commit()

    for file_path in photo_paths:
        try:
            relative_path = file_path.lstrip("/")
            absolute_path = Path(__file__).resolve().parent.parent / relative_path
            if absolute_path.exists():
                absolute_path.unlink()
        except Exception:
            pass

    avg_rating = db.query(func.avg(models.Review.rating)).filter(
        models.Review.district_id == district_id
    ).scalar() or 0
    avg_rating = float(avg_rating) if avg_rating else 0.0
    district = db.query(models.District).filter(models.District.id == district_id).first()
    final_score = float(district.final_score or 0.0) if district else 0.0

    return {"ok": True, "district_id": district_id, "avg_rating": avg_rating, "final_score": final_score}


@app.post("/auth/register", response_model=schemas.AuthResponse)
def register_user(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 chars")
    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = models.User(
        username=username,
        display_name=(payload.display_name or "").strip() or username,
        password_hash=hash_password(payload.password),
        auth_token=secrets.token_urlsafe(32),
        token_created_at=func.now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "token": user.auth_token,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


@app.post("/auth/login", response_model=schemas.AuthResponse)
def login_user(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user.auth_token = secrets.token_urlsafe(32)
    user.token_created_at = func.now()
    db.commit()
    return {
        "token": user.auth_token,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


@app.get("/auth/me", response_model=schemas.UserMe)
def auth_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "display_name": current_user.display_name,
    }


@app.post("/auth/logout")
def logout(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.auth_token = None
    current_user.token_created_at = None
    db.commit()
    return {"ok": True}


@app.post("/analyze/prosperity")
def analyze_prosperity():
    recalc_all_stats()
    return {"message": "Prosperity scores recalculated and saved to district_stats"}


@app.post("/find_district_by_point")
def find_district_by_point(request: dict, db: Session = Depends(get_db)):
    lat = request.get("lat")
    lon = request.get("lon")
    if lat is None or lon is None:
        raise HTTPException(400, "Missing lat/lon")
    point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    district = db.query(models.District).filter(
        models.District.admin_level >= 8,
        ST_Within(point, models.District.geom)
    ).first()
    if not district:
        return {"district_id": None, "geom_wkt": None}
    geom_wkt = db.scalar(ST_AsText(district.geom))
    return {"district_id": district.id, "geom_wkt": geom_wkt}


@app.post("/search/within_district")
def search_within_district(request: dict, db: Session = Depends(get_db)):
    district_id = request.get("district_id")
    category = request.get("category")
    name = request.get("name")
    if not district_id:
        raise HTTPException(400, "Missing district_id")
    district = db.query(models.District).filter(models.District.id == district_id).first()
    if not district:
        raise HTTPException(404, "District not found")
    query = db.query(models.Place).filter(ST_Within(models.Place.geom, district.geom))
    if category:
        category_terms = expand_category_terms(category)
        filters = []
        for term in category_terms:
            filters.extend([
                models.Place.category.ilike(term),
                models.Place.subclass.ilike(term),
            ])
        query = query.filter(or_(*filters))
    if name:
        query = query.filter(models.Place.name.ilike(f"%{name}%"))
    places = query.all()
    results = []
    for p in places:
        results.append({
            "id": p.id, "osm_id": p.osm_id, "name": p.name,
            "lat": p.lat, "lon": p.lon, "category": p.category,
            "subclass": p.subclass, "tags": p.tags, "distance": 0.0
        })
    return {"results": results}


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")
