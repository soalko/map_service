from sqlalchemy import Column, Integer, String, Float, JSON, ForeignKey, DateTime
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from sqlalchemy.orm import relationship
from .database import Base


class Place(Base):
    __tablename__ = "places"
    id = Column(Integer, primary_key=True, index=True)
    osm_id = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    lat = Column(Float)
    lon = Column(Float)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), index=True)
    tags = Column(JSON)
    category = Column(String)
    subclass = Column(String)


class DistrictStats(Base):
    __tablename__ = "district_stats"
    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'), unique=True)

    # Плотности (сырые)
    social_density = Column(Float, default=0.0)
    shops_density = Column(Float, default=0.0)
    tourism_density = Column(Float, default=0.0)
    leisure_density = Column(Float, default=0.0)

    # Нормированные (min-max)
    social_norm = Column(Float, default=0.0)
    shops_norm = Column(Float, default=0.0)
    tourism_norm = Column(Float, default=0.0)
    leisure_norm = Column(Float, default=0.0)

    # Базовый балл и коррекция
    base_score = Column(Float, default=0.0)
    k_user = Column(Float, default=1.0)
    final_score = Column(Float, default=0.0)

    # Вспомогательное поле для глобальных min/max (можно хранить отдельно)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    social_norm_logcnt = Column(Float, default=0.0)
    shops_norm_logcnt = Column(Float, default=0.0)
    tourism_norm_logcnt = Column(Float, default=0.0)
    leisure_norm_logcnt = Column(Float, default=0.0)
    social_score = Column(Float, default=0.0)
    shops_score = Column(Float, default=0.0)
    tourism_score = Column(Float, default=0.0)
    leisure_score = Column(Float, default=0.0)


class District(Base):
    __tablename__ = "districts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    admin_level = Column(Integer)
    geom = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), index=True)
    base_score = Column(Float, default=0.0)
    final_score = Column(Float, default=0.0)
    last_analyzed = Column(DateTime, default=func.now(), onupdate=func.now())
    area_km2 = Column(Float, default=0.0)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    auth_token = Column(String, unique=True, nullable=True, index=True)
    token_created_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    reviews = relationship("Review", back_populates="user")


class Review(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'))
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    user_name = Column(String, nullable=True)
    rating = Column(Integer, nullable=False)  # 1..5
    comment = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User", back_populates="reviews")
    photos = relationship("ReviewPhoto", back_populates="review", cascade="all, delete-orphan")


class ReviewPhoto(Base):
    __tablename__ = "review_photos"
    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey('reviews.id', ondelete='CASCADE'), nullable=False, index=True)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    review = relationship("Review", back_populates="photos")


class ProsperityMetric(Base):
    __tablename__ = "prosperity_metrics"
    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey('districts.id', ondelete='CASCADE'))
    metric_name = Column(String)  # e.g. 'amenity_density'
    metric_value = Column(Float)
    calculated_at = Column(DateTime, server_default=func.now())
