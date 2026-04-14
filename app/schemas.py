from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

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
    distance: Optional[float] = None   # computed in response

    class Config:
        from_attributes = True

class CategorySearch(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius: float = Field(..., gt=0)    # in meters
    category: str                        # e.g., "cafe", "museum", "all"

class NameSearch(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius: float = Field(..., gt=0)    # in meters
    name: str                            # substring to match place name

class SearchResponse(BaseModel):
    results: List[Place]