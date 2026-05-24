from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy import or_
from geoalchemy2.functions import ST_Distance, ST_Transform, ST_SetSRID, ST_MakePoint
from . import models, schemas


RU_CATEGORY_MAP = {
    "кафе": ["cafe"],
    "ресторан": ["restaurant"],
    "бар": ["bar", "pub"],
    "аптека": ["pharmacy"],
    "больница": ["hospital", "clinic", "doctors", "dentist"],
    "школа": ["school", "college", "kindergarten"],
    "университет": ["university"],
    "магазин": ["shop", "supermarket", "convenience", "mall"],
    "развлечения": ["cinema", "theatre", "stadium", "sports_centre", "fitness_centre", "theme_park"],
    "супермаркет": ["supermarket"],
    "парк": ["park", "garden", "dog_park", "nature_reserve"],
    "музей": ["museum"],
    "отель": ["hotel", "hostel", "guest_house", "apartment"],
    "транспорт": ["public_transport", "bus_station", "station", "platform", "bus_stop", "tram_stop"],
    "банкомат": ["atm"],
    "банк": ["bank"],
    "заправка": ["fuel"],
    "парковка": ["parking", "bicycle_parking"],
}


def _expand_category_terms(raw_category: str) -> list[str]:
    category = (raw_category or "").strip().lower()
    if not category:
        return []
    terms = {category}
    if category in RU_CATEGORY_MAP:
        terms.update(RU_CATEGORY_MAP[category])
    return list(terms)

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
        terms = _expand_category_terms(category)
        filters = []
        for term in terms:
            filters.extend([
                models.Place.category.ilike(term),
                models.Place.subclass.ilike(term),
            ])
        if filters:
            query = query.filter(or_(*filters))

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