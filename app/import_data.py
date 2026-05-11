import sys
import logging
import pandas as pd
from pyrosm import OSM
import geopandas as gpd
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== EXPANDED INTERESTING TAGS ==========
# Now covers more OSM keys and values, without being too huge.
# Each entry: key -> list of values (or True to get all values for that key)
INTERESTING_TAGS = {
    "amenity": [  # keep original + add more
        "cafe", "restaurant", "pub", "bar", "fast_food", "cinema", "theatre",
        "museum", "library", "place_of_worship", "hospital", "pharmacy",
        "bank", "post_office", "police", "fire_station", "school", "university",
        "college", "kindergarten", "dentist", "doctors", "clinic", "veterinary",
        "fuel", "car_wash", "parking", "bicycle_parking", "bus_station",
        "taxi", "atm", "bench", "toilets", "drinking_water", "shelter"
    ],
    "shop": [  # more shop types
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
    # NEW CATEGORIES:
    "office": True,          # catch all offices (True means any value)
    "man_made": [            # interesting man-made features
        "tower", "water_tower", "windmill", "lighthouse", "pier", "bridge",
        "monitoring_station", "surveillance", "chimney", "flagpole"
    ],
    "natural": [             # natural features
        "peak", "volcano", "spring", "cave_entrance", "tree", "waterfall",
        "bay", "beach", "cliff", "hill", "valley"
    ]
}

# Additional tags we want to extract from OSM (will become columns in the DataFrame,
# then later moved into the `tags` JSON column)
EXTRA_TAGS = [
    'phone', 'website', 'opening_hours', 'wheelchair', 'cuisine', 'brand',
    'addr:street', 'addr:housenumber', 'addr:city', 'addr:postcode',
    'capacity', 'operator', 'email', 'payment:cash', 'payment:cards',
    'internet_access', 'smoking', 'outdoor_seating', 'takeaway', 'delivery',
    # NEW ONES:
    'wheelchair:description', 'fee', 'charge', 'payment:bitcoin', 'building',
    'height', 'diet:vegetarian', 'organic', 'heritage', 'wikipedia',
    'healthcare', 'vaccination', 'parking:access', 'sport', 'lit',
    'social_facility', 'community_centre', 'emergency'
]


def extract_places(osm_file):
    osm = OSM(osm_file)
    all_pois = []

    for tag_key, tag_values in INTERESTING_TAGS.items():
        # Build the filter dictionary
        if tag_values is True:
            custom_filter = {tag_key: True}
        else:
            custom_filter = {tag_key: tag_values}

        # Use get_pois with extra attributes
        pois = osm.get_pois(
            custom_filter=custom_filter,
            extra_attributes=EXTRA_TAGS
        )

        if pois is not None and len(pois) > 0:
            pois['category'] = tag_key
            # For subclass: use the tag_key value if it's a single column,
            # otherwise try to infer the most specific tag.
            if tag_key in pois.columns:
                pois['subclass'] = pois[tag_key]
            else:
                # For filters with True, there's no single column; use first matching tag
                # For simplicity, set subclass to tag_key itself.
                pois['subclass'] = tag_key

            all_pois.append(pois)

    if not all_pois:
        logger.warning("No interesting places found in the OSM file.")
        return gpd.GeoDataFrame()

    # Combine all POIs
    combined = gpd.GeoDataFrame(pd.concat(all_pois, ignore_index=True))

    # Drop duplicates based on OSM id (if present)
    if 'id' in combined.columns:
        combined = combined.drop_duplicates(subset='id')
    else:
        logger.warning("No 'id' column found; duplicates may remain.")

    # Ensure we have a geometry column
    if 'geometry' not in combined.columns:
        logger.error("No geometry column found in extracted data.")
        return gpd.GeoDataFrame()

    # Convert all geometries to points (centroid if polygon/line)
    combined['geometry'] = combined.geometry.centroid
    combined['lat'] = combined.geometry.y
    combined['lon'] = combined.geometry.x

    # Create OSM id as string
    combined['osm_id'] = combined['id'].astype(str)

    # Build the `tags` JSON column: collect all OSM tag columns
    # These include the original tag_key columns (amenity, shop, etc.) and the extra tags
    tag_columns = []
    # All columns that are not in our fixed list
    fixed_cols = ['id', 'osm_id', 'name', 'geometry', 'category', 'subclass', 'lat', 'lon', 'tags']
    for col in combined.columns:
        if col not in fixed_cols:
            tag_columns.append(col)

    # Create a dictionary for each row
    combined['tags'] = combined.apply(
        lambda row: {col: row[col] for col in tag_columns if pd.notna(row[col])},
        axis=1
    )

    # Keep only the columns required by the Place model
    keep_cols = ['osm_id', 'name', 'lat', 'lon', 'geometry', 'category', 'subclass', 'tags']
    # Some rows may have no name – that's fine (will become NULL in DB)
    combined = combined[keep_cols]

    return combined


def import_to_postgis(gdf):
    """Insert GeoDataFrame into places table with proper type handling."""
    db = SessionLocal()
    try:
        # Clear existing data (optional – comment out if you want to append)
        db.query(models.Place).delete()
        db.commit()

        for _, row in gdf.iterrows():
            # Handle NaN values
            name = row.get('name')
            if pd.isna(name):
                name = None

            lat = float(row['lat']) if not pd.isna(row['lat']) else None
            lon = float(row['lon']) if not pd.isna(row['lon']) else None
            if lat is None or lon is None:
                continue

            point_wkt = f"POINT({lon} {lat})"

            # tags is already a dict, clean it
            tags = row['tags']
            if isinstance(tags, dict):
                # Remove any NaN values inside dict
                tags = {k: v for k, v in tags.items() if not (isinstance(v, float) and pd.isna(v))}
            else:
                tags = {}

            place = models.Place(
                osm_id=str(row['osm_id']),
                name=name,
                lat=lat,
                lon=lon,
                geom=point_wkt,
                tags=tags,
                category=str(row['category']),
                subclass=str(row['subclass']) if not pd.isna(row['subclass']) else None
            )
            db.add(place)

        db.commit()
        logger.info(f"Successfully imported {len(gdf)} places with enriched tags.")

    except Exception as e:
        logger.error(f"Import failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    osm_path = config.settings.OSM_DATA_PATH
    logger.info(f"Reading OSM data from {osm_path}")
    gdf = extract_places(osm_path)
    if len(gdf) > 0:
        import_to_postgis(gdf)
    else:
        logger.error("No places extracted. Check OSM file and tags.")