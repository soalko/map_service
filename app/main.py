from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles
from . import crud, schemas
from .database import SessionLocal

app = FastAPI(title="Interesting Places API")

# Mount static files for frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/search/category", response_model=schemas.SearchResponse)
def search_by_category(request: schemas.CategorySearch, db: Session = Depends(get_db)):
    places = crud.get_places_by_category(db, request.lat, request.lon, request.radius, request.category)
    return {"results": places}

@app.post("/search/name", response_model=schemas.SearchResponse)
def search_by_name(request: schemas.NameSearch, db: Session = Depends(get_db)):
    places = crud.get_places_by_name(db, request.lat, request.lon, request.radius, request.name)
    return {"results": places}

@app.get("/")
def root():
    return {"message": "Go to /static/index.html for the map interface"}