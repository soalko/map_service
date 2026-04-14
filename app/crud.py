from sqlalchemy.orm import Session
from sqlalchemy import func
from geoalchemy2.functions import ST_Distance, ST_Transform, ST_SetSRID, ST_MakePoint
from . import models, schemas

def get_places_by_category(db: Session, lat: float, lon: float, radius: float, category: str):
    """
    Return places within `radius` meters of (lat, lon) that match the category.
    If category == "all", return all places.
    """
    # Create a point geometry from input coordinates
    point = ST_SetSRID(ST_MakePoint(lon, lat), 4326)

    query = db.query(
        models.Place,
        ST_Distance(ST_Transform(models.Place.geom, 3857), ST_Transform(point, 3857)).label("distance")
    ).filter(
        func.ST_DWithin(
            ST_Transform(models.Place.geom, 3857),
            ST_Transform(point, 3857),
            radius
        )
    )

    if category.lower() != "all":
        # Match either category or subclass (e.g., "amenity" or "cafe")
        query = query.filter(
            (models.Place.category == category) | (models.Place.subclass == category)
        )

    results = query.all()
    # Convert to Place schema and add distance
    places = []
    for place, dist in results:
        place_dict = {
            "id": place.id,
            "osm_id": place.osm_id,
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "category": place.category,
            "subclass": place.subclass,
            "tags": place.tags,
            "distance": dist
        }
        places.append(place_dict)
    return places

def get_places_by_name(db: Session, lat: float, lon: float, radius: float, name: str):
    """Return places within radius whose name contains the given substring."""
    point = ST_SetSRID(ST_MakePoint(lon, lat), 4326)

    query = db.query(
        models.Place,
        ST_Distance(ST_Transform(models.Place.geom, 3857), ST_Transform(point, 3857)).label("distance")
    ).filter(
        func.ST_DWithin(
            ST_Transform(models.Place.geom, 3857),
            ST_Transform(point, 3857),
            radius
        )
    ).filter(models.Place.name.ilike(f"%{name}%"))

    results = query.all()
    places = []
    for place, dist in results:
        place_dict = {
            "id": place.id,
            "osm_id": place.osm_id,
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "category": place.category,
            "subclass": place.subclass,
            "tags": place.tags,
            "distance": dist
        }
        places.append(place_dict)
    return places