import logging
import math
from sqlalchemy import func
from sqlalchemy.orm import Session
from geoalchemy2.functions import ST_Within
from shapely import wkb
from .database import SessionLocal
from . import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Коэффициент баланса между плотностью (α) и абсолютным количеством (1-α)
ALPHA = 0.5  # 0.5 — равный вклад, можно менять

# Группы категорий POI и их веса
GROUPS = {
    'social': {
        'cat': ['amenity'],
        'weight': 0.30
    },
    'shops': {
        'cat': ['shop'],
        'weight': 0.25
    },
    'tourism': {
        'cat': ['tourism', 'historic'],
        'weight': 0.25
    },
    'leisure': {
        'cat': ['leisure'],
        'weight': 0.20
    }
}


def create_stats_table_if_not_exists():
    """Создаёт таблицу district_stats, если её нет (простая миграция)."""
    from sqlalchemy import inspect
    engine = SessionLocal().get_bind()
    inspector = inspect(engine)
    if not inspector.has_table('district_stats'):
        logger.info("Creating district_stats table...")
        models.DistrictStats.__table__.create(engine)
        logger.info("Table created.")
    else:
        # Можно также добавить недостающие колонки (если обновляем структуру)
        pass


def recalc_all_stats():
    db = SessionLocal()
    try:
        # Убедимся, что таблица статистики существует
        create_stats_table_if_not_exists()

        # 1. Получаем все районы
        districts = db.query(models.District).all()
        if not districts:
            logger.warning("No districts found. Run import_boundaries.py first.")
            return

        # Словари для хранения данных по каждому району
        district_data = {}  # { district_id: { 'area': float, 'counts': {g: int}, 'densities': {g: float}, 'log_counts': {g: float} } }
        all_counts = {g: [] for g in GROUPS}
        all_densities = {g: [] for g in GROUPS}
        all_log_counts = {g: [] for g in GROUPS}

        # 2. Для каждого района считаем сырые значения
        for district in districts:
            geom = wkb.loads(bytes(district.geom.data))
            area_km2 = district.area_km2 if district.area_km2 > 0 else geom.area / 1e6
            if area_km2 <= 0:
                continue

            counts = {}
            densities = {}
            log_counts = {}
            for gname, ginfo in GROUPS.items():
                cnt = db.query(models.Place).filter(
                    ST_Within(models.Place.geom, district.geom),
                    models.Place.category.in_(ginfo['cat'])
                ).count()
                dens = cnt / area_km2
                log_cnt = math.log1p(cnt)  # ln(1+cnt), устойчиво для cnt=0
                counts[gname] = cnt
                densities[gname] = dens
                log_counts[gname] = log_cnt

                all_counts[gname].append(cnt)
                all_densities[gname].append(dens)
                all_log_counts[gname].append(log_cnt)

            district_data[district.id] = {
                'area': area_km2,
                'counts': counts,
                'densities': densities,
                'log_counts': log_counts
            }

        # 3. Глобальные минимумы и максимумы для нормализации
        min_max = {}
        for gname in GROUPS:
            min_max[gname] = {
                'count_min': min(all_counts[gname]),
                'count_max': max(all_counts[gname]),
                'density_min': min(all_densities[gname]),
                'density_max': max(all_densities[gname]),
                'log_min': min(all_log_counts[gname]),
                'log_max': max(all_log_counts[gname]),
            }

        # 4. Для каждого района вычисляем нормализованные значения и комбинированный score группы
        group_scores = {}  # { district_id: { gname: score_group } }
        base_scores = {}
        for d_id, data in district_data.items():
            scores = {}
            for gname in GROUPS:
                # Нормализация плотности
                d_min = min_max[gname]['density_min']
                d_max = min_max[gname]['density_max']
                if d_max == d_min:
                    norm_density = 0.5
                else:
                    norm_density = (data['densities'][gname] - d_min) / (d_max - d_min)

                # Нормализация логарифма количества
                l_min = min_max[gname]['log_min']
                l_max = min_max[gname]['log_max']
                if l_max == l_min:
                    norm_logcnt = 0.5
                else:
                    norm_logcnt = (data['log_counts'][gname] - l_min) / (l_max - l_min)

                # Комбинированный скоринг группы
                score_group = ALPHA * norm_density + (1 - ALPHA) * norm_logcnt
                scores[gname] = {
                    'norm_density': norm_density,
                    'norm_logcnt': norm_logcnt,
                    'score': score_group
                }
            group_scores[d_id] = scores

            # Взвешенная сумма по группам
            base = 0.0
            for gname, ginfo in GROUPS.items():
                base += scores[gname]['score'] * ginfo['weight']
            base_scores[d_id] = base

        # 5. Учитываем отзывы (средний рейтинг)
        reviews_avg = {}
        rev_res = db.query(
            models.Review.district_id,
            func.avg(models.Review.rating).label('avg')
        ).group_by(models.Review.district_id).all()
        for r in rev_res:
            reviews_avg[r.district_id] = float(r.avg)

        # 6. Сохраняем или обновляем записи в district_stats
        for d_id in district_data:
            avg_rating = reviews_avg.get(d_id, 3.0)
            k_user = 0.8 + (avg_rating - 1) * 0.1
            final_score = base_scores[d_id] * k_user

            # Получаем существующую запись или создаём новую
            stats = db.query(models.DistrictStats).filter(
                models.DistrictStats.district_id == d_id
            ).first()
            if not stats:
                stats = models.DistrictStats(district_id=d_id)
                db.add(stats)

            # Сохраняем сырые плотности
            stats.social_density = district_data[d_id]['densities']['social']
            stats.shops_density = district_data[d_id]['densities']['shops']
            stats.tourism_density = district_data[d_id]['densities']['tourism']
            stats.leisure_density = district_data[d_id]['densities']['leisure']

            # Сохраняем нормализованные значения (плотности)
            stats.social_norm = group_scores[d_id]['social']['norm_density']
            stats.shops_norm = group_scores[d_id]['shops']['norm_density']
            stats.tourism_norm = group_scores[d_id]['tourism']['norm_density']
            stats.leisure_norm = group_scores[d_id]['leisure']['norm_density']

            stats.social_norm_logcnt = group_scores[d_id]['social']['norm_logcnt']
            stats.shops_norm_logcnt = group_scores[d_id]['shops']['norm_logcnt']
            stats.tourism_norm_logcnt = group_scores[d_id]['tourism']['norm_logcnt']
            stats.leisure_norm_logcnt = group_scores[d_id]['leisure']['norm_logcnt']

            stats.social_score = group_scores[d_id]['social']['score']
            stats.shops_score = group_scores[d_id]['shops']['score']
            stats.tourism_score = group_scores[d_id]['tourism']['score']
            stats.leisure_score = group_scores[d_id]['leisure']['score']

            # Сохраняем нормализованные логарифмы количества и комбинированные scores
            # Для этого нужно расширить модель DistrictStats новыми полями.
            # Если вы не хотите расширять, можно просто не сохранять, а вычислять при запросе на основе сохранённых сырых данных.
            # Но для простоты и прозрачности лучше расширить модель.
            # Здесь я предполагаю, что вы добавили в модель поля:
            # social_norm_logcnt, shops_norm_logcnt, tourism_norm_logcnt, leisure_norm_logcnt,
            # social_score, shops_score, tourism_score, leisure_score.
            # Если их нет, можно сохранять только итоговые base_score и final_score.
            # В целях совместимости, пока сохраняем только то, что есть в модели.
            # Но вы можете позже расширить модель и добавить эти поля.

            stats.base_score = base_scores[d_id]
            stats.k_user = k_user
            stats.final_score = final_score

        db.commit()
        logger.info(f"Recalculated stats for {len(district_data)} districts (alpha={ALPHA}).")

    except Exception as e:
        logger.error(f"Error in recalc_all_stats: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    recalc_all_stats()
