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

INTERESTING_TAGS = {
    "amenity": ["cafe", "restaurant", "pub", "bar", "fast_food", "cinema", "theatre", "museum", "library",
                "place_of_worship", "hospital", "pharmacy", "bank", "post_office", "police", "fire_station"],
    "shop": ["supermarket", "bakery", "butcher", "clothes", "mall"],
    "tourism": ["hotel", "hostel", "attraction", "museum", "viewpoint", "picnic_site", "camp_site"],
    "historic": ["monument", "memorial", "archaeological_site"],
    "leisure": ["park", "garden", "playground", "sports_centre", "stadium"],
    "public_transport": ["station", "stop_position"]
}

def extract_places(osm_file):
    osm = OSM(osm_file)
    all_pois = []

    for tag_key, tag_values in INTERESTING_TAGS.items():
        custom_filter = {tag_key: tag_values}
        pois = osm.get_pois(custom_filter=custom_filter)
        if pois is not None and len(pois) > 0:
            pois['category'] = tag_key
            pois['subclass'] = pois[tag_key]
            all_pois.append(pois)

    if not all_pois:
        logger.warning("No interesting places found.")
        return gpd.GeoDataFrame()

    combined = gpd.GeoDataFrame(pd.concat(all_pois, ignore_index=True))
    if 'id' in combined.columns:
        combined = combined.drop_duplicates(subset='id')
    else:
        logger.warning("No 'id' column found; duplicates may remain.")

    keep_cols = ['id', 'name', 'geometry', 'category', 'subclass'] + list(INTERESTING_TAGS.keys())
    available_cols = [c for c in keep_cols if c in combined.columns]
    combined = combined[available_cols]

    # Use centroid to handle non-point geometries
    combined['lat'] = combined.geometry.centroid.y
    combined['lon'] = combined.geometry.centroid.x

    combined['osm_id'] = combined['id'].astype(str)

    tag_columns = [col for col in combined.columns if col not in ['id', 'osm_id', 'name', 'geometry', 'category', 'subclass', 'lat', 'lon']]
    combined['tags'] = combined.apply(lambda row: {col: row[col] for col in tag_columns if pd.notna(row[col])}, axis=1)

    return combined

def import_to_postgis(gdf):
    """Insert GeoDataFrame into places table with proper type handling."""
    db = SessionLocal()
    try:
        # Clear existing data (optional)
        db.query(models.Place).delete()
        db.commit()

        # Convert numpy types to Python native types for SQLAlchemy
        for _, row in gdf.iterrows():
            # Handle NaN values (convert to None for SQL NULL)
            name = row.get('name')
            if pd.isna(name):
                name = None

            # Ensure lat/lon are floats (they should be, but force conversion)
            lat = float(row['lat']) if not pd.isna(row['lat']) else None
            lon = float(row['lon']) if not pd.isna(row['lon']) else None

            # Skip if no valid coordinates
            if lat is None or lon is None:
                continue

            # Create WKT point string
            point_wkt = f"POINT({lon} {lat})"

            # Convert tags dict to JSON-compatible dict (remove NaN)
            tags = row['tags']
            if isinstance(tags, dict):
                # Clean NaN values from tags dict
                tags = {k: v for k, v in tags.items() if not (isinstance(v, float) and pd.isna(v))}

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
        logger.info(f"Successfully imported {len(gdf)} places.")

    except Exception as e:
        logger.error(f"Import failed: {e}")
        db.rollback()
        raise  # Re-raise to see full traceback

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