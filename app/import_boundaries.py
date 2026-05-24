import sys
import logging
import pandas as pd
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import transform
import pyproj
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import models, config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_EXTENT_DEGREES = 10.0
MIN_AREA = 1e-7
MAX_SHAPE_FACTOR = 2000      # более строгий отсев линий

def project_to_metric(geom):
    """Проецирует геометрию из WGS84 в метрическую систему (EPSG:3857) для расчёта площади в м²."""
    transformer = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:3857', always_xy=True)
    return transform(transformer.transform, geom)

def is_valid_geometry(geom):
    if geom is None or geom.is_empty:
        return False
    bounds = geom.bounds
    if abs(bounds[2] - bounds[0]) > MAX_EXTENT_DEGREES or abs(bounds[3] - bounds[1]) > MAX_EXTENT_DEGREES:
        return False
    area = geom.area
    if area < MIN_AREA:
        return False
    perimeter = geom.length
    if perimeter > 0 and (perimeter * perimeter) / area > MAX_SHAPE_FACTOR:
        return False
    return True

def repair_geometry(geom):
    if geom is None or geom.is_empty:
        return None
    geom_repaired = geom.buffer(0)
    if geom_repaired.is_empty:
        return None
    if geom_repaired.geom_type == 'MultiPolygon':
        return geom_repaired if is_valid_geometry(geom_repaired) else None
    if geom_repaired.geom_type == 'Polygon':
        mp = MultiPolygon([geom_repaired])
        return mp if is_valid_geometry(mp) else None
    return None

def extract_districts(osm_file, admin_levels=[5,6,7,8,9,10,11]):
    from pyrosm import OSM
    osm = OSM(osm_file)
    logger.info("Извлечение административных границ...")
    boundaries = osm.get_boundaries()
    if boundaries is None or len(boundaries) == 0:
        return gpd.GeoDataFrame()
    if 'admin_level' in boundaries.columns:
        boundaries['admin_level'] = boundaries['admin_level'].astype(str)
        allowed = [str(lvl) for lvl in admin_levels]
        boundaries = boundaries[boundaries['admin_level'].isin(allowed)]
    boundaries = boundaries[boundaries.geometry.apply(lambda g: g.geom_type in ('Polygon', 'MultiPolygon'))]
    keep = ['osm_id', 'name', 'admin_level', 'geometry']
    boundaries = boundaries[[c for c in keep if c in boundaries.columns]]
    logger.info("Ремонт и проверка геометрий...")
    boundaries['geometry'] = boundaries['geometry'].apply(repair_geometry)
    boundaries = boundaries.dropna(subset=['geometry'])
    if len(boundaries) == 0:
        return gpd.GeoDataFrame()
    boundaries = boundaries.to_crs(4326)
    logger.info(f"Извлечено {len(boundaries)} районов.")
    return boundaries

def import_districts(db: Session, gdf):
    # db.query(models.District).delete()
    # db.commit()
    districts = []
    for _, row in gdf.iterrows():
        name = str(row['name']).strip() if pd.notna(row['name']) else None
        admin_level = int(row['admin_level']) if pd.notna(row['admin_level']) else None
        geom_wkt = row.geometry.wkt
        # Вычисляем площадь в км²
        geom_proj = project_to_metric(row.geometry)
        area_km2 = geom_proj.area / 1_000_000.0
        districts.append(models.District(
            name=name, admin_level=admin_level, geom=geom_wkt,
            base_score=0.0, final_score=0.0, area_km2=area_km2
        ))
    db.add_all(districts)
    db.commit()
    logger.info(f"Импортировано {len(districts)} районов (площади сохранены).")

if __name__ == "__main__":
    osm_path = config.settings.OSM_DATA_PATH
    gdf = extract_districts(osm_path)
    if len(gdf) > 0:
        db = SessionLocal()
        import_districts(db, gdf)
        db.close()
    else:
        logger.error("Нет данных для импорта.")