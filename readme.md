# Interesting Places Web Service

## Setup

1. Install PostgreSQL with PostGIS.
2. Create a database: `createdb poi_db`.
3. Enable PostGIS: `psql -d poi_db -c "CREATE EXTENSION postgis;"`.
4. Install Python dependencies: `pip install -r requirements.txt`.
5. Download OSM data (Central Federal District) from [Geofabrik](https://download.geofabrik.de/russia/central-fed-district.html) and place it in `data/central-fed-district-latest.osm.pbf`.
6. Import data: `python -m app.import_data`.
7. Run the server: `uvicorn app.main:app --reload`.
8. Open http://localhost:8000/static/index.html

## API Endpoints

- `POST /search/category` – body: `{lat, lon, radius, category}`
- `POST /search/name` – body: `{lat, lon, radius, name}`

Returns JSON with list of places including name, coordinates, distance, category.