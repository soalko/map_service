import sys
import logging
import json
import gc
import psycopg2.extras
import pandas as pd
import geopandas as gpd
from sqlalchemy import text
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, config

# Регистрация адаптера JSONB для корректной обработки словарей
try:
    psycopg2.extras.register_default_jsonb(load=False)
    psycopg2.extras.register_default_json(load=False)
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Настройки фильтрации POI ----------
INTERESTING_TAGS = {
    "amenity": [
        "cafe", "restaurant", "pub", "bar", "fast_food", "cinema", "theatre",
        "museum", "library", "place_of_worship", "hospital", "pharmacy",
        "bank", "post_office", "police", "fire_station", "school", "university",
        "college", "kindergarten", "dentist", "doctors", "clinic", "veterinary",
        "fuel", "car_wash", "parking", "bicycle_parking", "bus_station",
        "taxi", "atm", "bench", "toilets", "drinking_water", "shelter"
    ],
    "shop": [
        "supermarket", "bakery", "butcher", "clothes", "mall", "convenience",
        "hairdresser", "beauty", "books", "stationery", "electronics",
        "furniture", "hardware", "jewelry", "sports", "toys", "gift",
        "florist", "greengrocer", "chemist", "optician", "shoes", "beverages"
    ],
    "tourism": [
        "hotel", "hostel", "attraction", "museum", "viewpoint", "picnic_site",
        "camp_site", "guest_house", "apartment", "chalet", "information",
        "artwork", "gallery", "zoo", "aquarium", "theme_park"
    ],
    "historic": [
        "monument", "memorial", "archaeological_site", "castle", "ruins",
        "church", "chapel", "manor", "wayside_cross", "wayside_shrine"
    ],
    "leisure": [
        "park", "garden", "playground", "sports_centre", "stadium", "fitness_centre",
        "swimming_pool", "pitch", "golf_course", "nature_reserve", "dog_park",
        "sauna", "water_park", "marina", "slipway"
    ],
    "public_transport": [
        "station", "stop_position", "platform", "bus_stop", "tram_stop",
        "subway_entrance"
    ],
    "office": True,
    "man_made": [
        "tower", "water_tower", "windmill", "lighthouse", "pier", "bridge",
        "monitoring_station", "surveillance", "chimney", "flagpole"
    ],
    "natural": [
        "peak", "volcano", "spring", "cave_entrance", "tree", "waterfall",
        "bay", "beach", "cliff", "hill", "valley"
    ]
}

EXTRA_TAGS = [
    'phone', 'website', 'opening_hours', 'wheelchair', 'cuisine', 'brand',
    'addr:street', 'addr:housenumber', 'addr:city', 'addr:postcode',
    'capacity', 'operator', 'email', 'payment:cash', 'payment:cards',
    'internet_access', 'smoking', 'outdoor_seating', 'takeaway', 'delivery'
]


def process_category(osm, tag_key, tag_values, db: Session):
    """Обрабатывает одну категорию и вставляет в БД (пакетно)."""
    # Фильтр
    if tag_values is True:
        custom_filter = {tag_key: True}
    else:
        custom_filter = {tag_key: tag_values}

    pois = osm.get_pois(custom_filter=custom_filter, extra_attributes=EXTRA_TAGS)
    if pois is None or len(pois) == 0:
        logger.info(f"Категория {tag_key}: нет данных")
        return 0

    # Добавляем мета-информацию
    pois['category'] = tag_key
    if tag_key in pois.columns:
        pois['subclass'] = pois[tag_key]
    else:
        pois['subclass'] = tag_key

    # Геометрия -> точки (центроиды)
    pois['geometry'] = pois.geometry.centroid
    pois['lat'] = pois.geometry.y
    pois['lon'] = pois.geometry.x
    pois['osm_id'] = pois['id'].astype(str)

    # Формируем JSON-поле tags
    fixed_cols = ['id', 'osm_id', 'name', 'geometry', 'category', 'subclass', 'lat', 'lon']
    tag_columns = [col for col in pois.columns if col not in fixed_cols]
    pois['tags'] = pois.apply(
        lambda row: {col: row[col] for col in tag_columns if pd.notna(row[col])},
        axis=1
    )

    # Подготовка записей
    records = []
    for _, row in pois.iterrows():
        name = row.get('name')
        if pd.isna(name):
            name = None

        lat = float(row['lat']) if not pd.isna(row['lat']) else None
        lon = float(row['lon']) if not pd.isna(row['lon']) else None
        if lat is None or lon is None:
            continue

        # Обработка тегов: удаляем мусорный ключ и преобразуем в JSON-строку
        tags_dict = row['tags']
        if isinstance(tags_dict, dict):
            if 'tags' in tags_dict:
                del tags_dict['tags']
            # Очищаем от None
            tags_dict = {k: v for k, v in tags_dict.items() if v is not None}
            tags_json = json.dumps(tags_dict, ensure_ascii=False)
        else:
            tags_json = '{}'

        category = str(row['category'])[:50] if not pd.isna(row['category']) else None
        subclass = str(row['subclass'])[:50] if not pd.isna(row['subclass']) else None

        records.append({
            'osm_id': str(row['osm_id']),
            'name': name,
            'lat': lat,
            'lon': lon,
            'geom': f'POINT({lon} {lat})',
            'tags': tags_json,
            'category': category,
            'subclass': subclass
        })

    if not records:
        logger.info(f"Категория {tag_key}: нет валидных записей после фильтрации")
        return 0

    # Пакетная вставка / обновление
    stmt = text("""
        INSERT INTO places (osm_id, name, lat, lon, geom, tags, category, subclass)
        VALUES (:osm_id, :name, :lat, :lon, ST_GeomFromText(:geom, 4326), CAST(:tags AS JSONB), :category, :subclass)
        ON CONFLICT (osm_id) DO UPDATE SET
            name = EXCLUDED.name,
            lat = EXCLUDED.lat,
            lon = EXCLUDED.lon,
            geom = EXCLUDED.geom,
            tags = EXCLUDED.tags,
            category = EXCLUDED.category,
            subclass = EXCLUDED.subclass
    """)

    batch_size = 1000
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        db.execute(stmt, batch)
        db.commit()
        logger.info(f"Категория {tag_key}: вставлено {len(batch)} записей (всего {len(records)})")

    count = len(records)
    # Освобождаем память
    del pois
    del records
    gc.collect()
    return count


def import_osm_data():
    from pyrosm import OSM
    osm = OSM(config.settings.OSM_DATA_PATH)
    db = SessionLocal()
    total = 0
    try:
        for tag_key, tag_values in INTERESTING_TAGS.items():
            logger.info(f"Обработка категории: {tag_key}")
            cnt = process_category(osm, tag_key, tag_values, db)
            total += cnt
            logger.info(f"Категория {tag_key} завершена: {cnt} объектов")
        logger.info(f"Импорт завершён. Всего обработано: {total}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import_osm_data()