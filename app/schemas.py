from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class PlaceBase(BaseModel):
    name: Optional[str] = None
    lat: float
    lon: float
    category: Optional[str] = None
    subclass: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None


class PlaceCreate(PlaceBase):
    osm_id: str


class Place(PlaceBase):
    id: int
    osm_id: str
    distance: Optional[float] = None  # computed in response

    class Config:
        from_attributes = True


class CategorySearch(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius: float = Field(..., gt=0)  # in meters
    category: str  # e.g., "cafe", "museum", "all"


class NameSearch(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius: float = Field(..., gt=0)  # in meters
    name: str  # substring to match place name


class SearchResponse(BaseModel):
    results: List[Place]


class DistrictBase(BaseModel):
    name: str
    admin_level: Optional[int] = None
    base_score: Optional[float] = None
    final_score: Optional[float] = None


class District(DistrictBase):
    id: int

    class Config:
        from_attributes = True


class ReviewCreate(BaseModel):
    district_id: int
    rating: int  # 1-5
    comment: Optional[str] = None


class ReviewPhoto(BaseModel):
    id: int
    file_path: str

    class Config:
        from_attributes = True


class Review(ReviewCreate):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    is_mine: bool = False
    created_at: datetime
    photos: List[ReviewPhoto] = []

    class Config:
        from_attributes = True


class DistrictWithReviews(District):
    avg_rating: Optional[float] = None
    reviews: List[Review] = []


class RegisterRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=6)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: int
    username: str
    display_name: Optional[str] = None


class UserMe(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None

