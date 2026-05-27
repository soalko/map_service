# Веб-сервис "Мой район"

## Запуск

1. Установите PostgreSQL с помощью PostGIS.
2. Создайте базу данных: `createdb poi_db`.
3. Создайте расширение PostGIS: `psql -d poi_db -c "CREATE EXTENSION postgis;"`.
4. Установите зависимости: `pip install -r requirements.txt`.
5. Скачайте данные OSM (Central Federal District) с
   сайта [Geofabrik](https://download.geofabrik.de/russia/central-fed-district.html) и разместите их по пути
   `data/central-fed-district-latest.osm.pbf`.
6. Импортируйте данные: `python -m app.import_data`.
7. Запустите сервер: `uvicorn app.main:app --reload`.
8. Откройте http://localhost:8000/static/index.html

## Auth API

- `POST /auth/register` – body: `{username, password, display_name?}`
- `POST /auth/login` – body: `{username, password}`
- `GET /auth/me` – requires `Authorization: Bearer <token>`
- `POST /auth/logout` – requires `Authorization: Bearer <token>`

## API Endpoints

- `POST /search/category` – body: `{lat, lon, radius, category}`
- `POST /search/name` – body: `{lat, lon, radius, name}`
- `POST /reviews` – multipart form: `district_id`, `rating`, `comment`, `photos[]` (0..10), auth required
- `GET /reviews/{district_id}`

Возвращает JSON со списком мест, включая name, coordinates, distance, category.