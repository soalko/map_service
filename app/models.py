from sqlalchemy import Column, Integer, String, Float, JSON
from geoalchemy2 import Geometry
from .database import Base

class Place(Base):
    __tablename__ = "places"

    id = Column(Integer, primary_key=True, index=True)
    osm_id = Column(String, unique=True, index=True)  # OSM id as string
    name = Column(String, index=True)
    lat = Column(Float)
    lon = Column(Float)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), index=True)
    tags = Column(JSON)          # all OSM tags
    category = Column(String)     # derived primary category (amenity, tourism, etc.)
    subclass = Column(String)     # more specific (cafe, museum, etc.)