#!/usr/bin/env python3
"""Extension 3 · historical climate, vegetation index and land change per 1 km² cell.

download-climate : ERA5 daily reanalysis (Open-Meteo archive API, no key) at a 0.5° grid over
                   Normandy, 1991-2025 -> yearly mean temperature, total rain, hot days (Tmax ≥ 30 °C),
                   frost days, dry days (rain < 1 mm), max dry spell, reference evapotranspiration.
download-ndvi    : MODIS MOD13Q1 NDVI (250 m, 16-day; NASA ORNL DAAC subset API, no key) averaged over a
                   5 × 5 km window at the same grid points, 2001-2025 -> yearly mean and summer (JJA) mean.
build            : trends (Sen slope + Mann-Kendall), 1991-2020 baseline anomalies, land change from the
                   atlas (built-up 2006 / 2017 / 2025), assignment of each cell to its nearest grid point.
                   Writes dist/data/normandie/climate.json (+ .gz).

Raw downloads are cached in datasets/normandie_climate/ so every step can be re-run offline.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / 'datasets/normandie_climate'
DATA = ROOT / 'dist/data/normandie'
BBOX = (-1.96, 48.17, 1.81, 50.08)
STEP = 0.5
YEARS = (1991, 2025)
UA = {'User-Agent': 'RenaturaNormandie/1.0 (research; climate history)'}


def grid_points():
    """0.5° points whose 25 km neighbourhood touches Normandy (cells assigned to nearest later)."""
    cells = json.load(gzip.open(DATA / 'cells.geojson.gz'))
    import shapely
    from shapely.geometry import shape
    region = shapely.union_all([shape(f['geometry']) for f in cells['features']]).buffer(0.2)
    pts = []
    lon = math.floor(BBOX[0] / STEP) * STEP
    while lon <= BBOX[2] + 1e-9:
        lat = math.floor(BBOX[1] / STEP) * STEP
        while lat <= BBOX[3] + 1e-9:
            if region.intersects(shapely.Point(lon, lat).buffer(STEP / 2)):
                pts.append((round(lon, 2), round(lat, 2)))
            lat += STEP
        lon += STEP
    return pts


def get(url, tries=12):
    import requests  # certifi bundle: the framework Python's urllib has no CA store on this Mac
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=180)
            if r.status_code == 429:
                raise RuntimeError('429 rate limited')
            r.raise_for_status()
            return r.json()
        except Exception as e:  # rate limit / transient
            wait = 120 * (i + 1) if '429' in str(e) else 5 * (i + 1)
            print(f'    retry in {wait}s ({e})', flush=True)
            time.sleep(wait)
    raise RuntimeError(url)


def download_climate():
    out = RAW / 'era5'
    out.mkdir(parents=True, exist_ok=True)
    pts = grid_points()
    print(f'{len(pts)} grid points', flush=True)
    for lon, lat in pts:
        f = out / f'{lon}_{lat}.json'
        if f.exists():
            continue
        q = urllib.parse.urlencode({'latitude': lat, 'longitude': lon, 'start_date': f'{YEARS[0]}-01-01',
                                    'end_date': f'{YEARS[1]}-12-31', 'models': 'era5', 'timezone': 'Europe/Paris',
                                    'daily': 'temperature_2m_mean,temperature_2m_max,precipitation_sum'})
        try:
            js = get('https://archive-api.open-meteo.com/v1/archive?' + q)
        except Exception as e:  # network down / quota: skip, a later pass resumes (saved points are kept)
            print(f'  ! ERA5 {lon},{lat} skipped for now: {e}', flush=True)
            continue
        f.write_text(json.dumps(js['daily']))
        print(f'  ERA5 {lon},{lat}: {len(js["daily"]["time"])} days', flush=True)
        time.sleep(210)  # a 35-year daily request weighs ~270 calls: stay under the free hourly/daily limits
    missing = [p for p in pts if not (out / f'{p[0]}_{p[1]}.json').exists()]
    print(f'ERA5 points missing: {len(missing)}', flush=True)
    return len(missing)


def dt_doy(year, month, day):
    import datetime
    return datetime.date(year, month, day).timetuple().tm_yday


def download_ndvi():
    out = RAW / 'ndvi'
    out.mkdir(parents=True, exist_ok=True)
    base = 'https://modis.ornl.gov/rst/api/v1/MOD13Q1'
    for lon, lat in grid_points():
        f = out / f'{lon}_{lat}.json'
        if f.exists():
            continue
        # summer composites only (June-August): one request per year (<= 10 dates), 2 x 2 km window.
        # The full 16-day series would take > 16 h on this slow public service.
        part = out / f'{lon}_{lat}.partial.json'  # years already fetched survive an interruption
        done = json.loads(part.read_text()) if part.exists() else {}
        failed = 0
        for year in range(2001, YEARS[1] + 1):
            if str(year) in done:
                continue
            start = f'A{year}{dt_doy(year, 6, 1):03d}'
            end = f'A{year}{dt_doy(year, 8, 31):03d}'
            try:
                js = get(f'{base}/subset?latitude={lat}&longitude={lon}&band=250m_16_days_NDVI'
                         f'&startDate={start}&endDate={end}&kmAboveBelow=1&kmLeftRight=1')
            except Exception as e:
                print(f'  ! NDVI {lon},{lat} {year} skipped for now: {e}', flush=True)
                failed += 1
                continue
            done[str(year)] = [{'date': s['calendar_date'],
                                'ndvi': float(np.mean(v)) * float(js.get('scale') or 0.0001) if (v := [x for x in s['data'] if x > -2000]) else None,
                                'valid_pixels': len(v)} for s in js.get('subset', [])]  # -3000 = fill value
            part.write_text(json.dumps(done))
        if failed:
            continue  # keep the partial file; the next pass completes it
        f.write_text(json.dumps([row for year in sorted(done) for row in done[year]]))
        part.unlink(missing_ok=True)
        print(f'  NDVI {lon},{lat}: {len(done)} summers', flush=True)
    missing = [p for p in grid_points() if not (out / f'{p[0]}_{p[1]}.json').exists()]
    print(f'NDVI points missing: {len(missing)}', flush=True)
    return len(missing)


def sen_mk(years, values):
    """Sen slope per decade + Mann-Kendall two-sided p-value (normal approximation, no tie correction)."""
    x, y = np.asarray(years, float), np.asarray(values, float)
    m = ~np.isnan(y)
    x, y = x[m], y[m]
    n = len(y)
    if n < 8:
        return None
    i, j = np.triu_indices(n, 1)
    slopes = (y[j] - y[i]) / (x[j] - x[i])
    s = np.sign(y[j] - y[i]).sum()
    var = n * (n - 1) * (2 * n + 5) / 18
    z = (s - np.sign(s)) / math.sqrt(var) if s != 0 else 0.0
    p = math.erfc(abs(z) / math.sqrt(2))
    return {'slope_per_decade': round(float(np.median(slopes)) * 10, 3), 'p_value': round(p, 4), 'significant': p < 0.05, 'n_years': n}


def yearly_climate(daily):
    t = np.array(daily['time'], dtype='datetime64[D]')
    yrs = t.astype('datetime64[Y]').astype(int) + 1970
    arr = {k: np.array([np.nan if v is None else v for v in daily[k]], float) for k in daily if k != 'time'}
    rows = {}
    for y in range(YEARS[0], YEARS[1] + 1):
        m = yrs == y
        if m.sum() < 360:
            continue
        rain = arr['precipitation_sum'][m]
        dry = rain < 1.0
        spell = best = 0
        for d in dry:
            spell = spell + 1 if d else 0
            best = max(best, spell)
        rows[y] = {'tmean': round(float(np.nanmean(arr['temperature_2m_mean'][m])), 2),
                   'rain_mm': round(float(np.nansum(rain)), 1),
                   'hot_days': int((arr['temperature_2m_max'][m] >= 30).sum()),
                   'frost_days': int((arr['temperature_2m_min'][m] < 0).sum()) if 'temperature_2m_min' in arr else None,
                   'dry_days': int(dry.sum()), 'max_dry_spell': int(best),
                   'summer_rain_mm': round(float(np.nansum(rain[np.isin((t[m].astype('datetime64[M]').astype(int) % 12) + 1, [6, 7, 8])])), 1)}
    return rows


def yearly_ndvi(series):
    rows = {}
    for y in range(2001, YEARS[1] + 1):
        vals = [s['ndvi'] for s in series if s['ndvi'] is not None and s['date'].startswith(str(y))]
        summer = [s['ndvi'] for s in series if s['ndvi'] is not None and s['date'].startswith(str(y)) and s['date'][5:7] in ('06', '07', '08')]
        if len(summer) >= 3:
            rows[y] = {'ndvi_summer': round(float(np.mean(summer)), 4)}
    return rows


def land_change():
    """Built-up fraction per cell in 2006 / 2017 / 2025 from the atlas (Tâche du bâti)."""
    sys.path.insert(0, str(ROOT / 'tools/normandie'))
    from multilayer_score import Catalog, Grid, territories, read
    cat = Catalog()
    grid = Grid(DATA / 'cells.geojson')
    terr, _ = territories(read(ROOT / 'tools/normandie/layer_scoring.json'), cat, grid)
    out = {'bn_mask': grid.covered_by(terr['BN'])}  # the 2006 edition only covers Basse-Normandie
    for year, lid in ((2006, 'file_f81fcae937122601e8'), (2017, 'file_0f50506e66d2519972'), (2025, 'file_96dc83a7d1807f4bc3')):
        g, _ = cat.features({'id': lid})
        raw, _ = grid.measure(g, 'area')
        out[year] = raw
        print(f'  built-up {year}: mean {raw.mean():.4f}', flush=True)
    return [p['id'] for p in grid.props], grid, out


def build():
    pts = sorted({tuple(map(float, f.stem.split('_'))) for f in (RAW / 'era5').glob('*.json')})
    points = []
    for lon, lat in pts:
        clim = yearly_climate(json.loads((RAW / 'era5' / f'{lon}_{lat}.json').read_text()))
        nf = RAW / 'ndvi' / f'{lon}_{lat}.json'
        ndvi = yearly_ndvi(json.loads(nf.read_text())) if nf.exists() else {}
        years = sorted(clim)
        base = [y for y in years if 1991 <= y <= 2020]
        trends, anomalies = {}, {}
        for k in ('tmean', 'rain_mm', 'hot_days', 'dry_days', 'max_dry_spell', 'summer_rain_mm'):
            trends[k] = sen_mk(years, [clim[y][k] for y in years])
            ref = float(np.mean([clim[y][k] for y in base])) if base else None
            recent = [clim[y][k] for y in years if y >= 2016]
            anomalies[k] = None if ref is None or not recent else round(float(np.mean(recent)) - ref, 2)
        if ndvi:
            ny = sorted(ndvi)
            trends['ndvi_summer'] = sen_mk(ny, [ndvi[y]['ndvi_summer'] if ndvi[y]['ndvi_summer'] is not None else np.nan for y in ny])
        points.append({'id': f'P{lon}_{lat}', 'lon': lon, 'lat': lat, 'climate': clim, 'ndvi': ndvi,
                       'trends': trends, 'anomaly_2016_2025_vs_1991_2020': anomalies})
    ids, grid, built = land_change()
    from scipy.spatial import cKDTree
    tree = cKDTree([(p['lon'], p['lat']) for p in points])
    lon = np.array([c.x for c in grid.centroids]) if False else None
    import shapely
    from pyproj import Transformer
    back = Transformer.from_crs(2154, 4326, always_xy=True)
    cx, cy = back.transform(grid.cx, grid.cy)
    _, nearest = tree.query(np.column_stack([cx, cy]))
    cells = {}
    for i, cid in enumerate(ids):
        b06, b17, b25 = (float(built[y][i]) for y in (2006, 2017, 2025))
        in_bn = bool(built['bn_mask'][i])
        cells[cid] = {'point': points[nearest[i]]['id'], 'built_2006': round(b06, 4) if in_bn else None,
                      'built_2017': round(b17, 4), 'built_2025': round(b25, 4),
                      # change only where both editions exist and use the same method (2006 = Basse-Normandie only)
                      'built_change_2006_2017_pts': round(100 * (b17 - b06), 2) if in_bn else None}
    meta = {
        'sources': ['ERA5 réanalyse ECMWF/Copernicus via Open-Meteo archive (journalier, ~25-30 km, regroupé sur grille 0,5°)',
                    'MODIS MOD13Q1 NDVI 250 m, composites de juin à août, NASA ORNL DAAC (moyenne fenêtre 2 × 2 km)',
                    'Tâche du bâti 2006 / 2017 / 2025 (atlas Renatura, simplification d’affichage 30 m)'],
        'baseline': '1991-2020', 'recent_period': '2016-2025',
        'trend_method': 'Pente de Sen par décennie + test de Mann-Kendall (p < 0,05 = significatif)',
        'caveats': ['Résolution climatique ~25-50 km : tendances régionales, pas un microclimat de maille.',
                    'Une tendance observée n’attribue pas à elle seule une cause climatique à un changement local.',
                    'NDVI MODIS d’été : nuages et mélange de pixels ; fenêtre 2 × 2 km autour du point, pas représentative de toute la maille climatique.',
                    'Bâti : l’édition 2006 ne couvre que la Basse-Normandie (14, 50, 61) ; l’évolution est donc calculée 2006 → 2017 sur ce territoire seulement. '
                    'L’édition 2025 n’est pas comparable (méthode différente : +64 % de surface bâtie dans l’Orne en 8 ans, nombre d’objets stable) ; elle est affichée comme niveau actuel, jamais comme évolution.',
                    'Projections (DRIAS / TRACC) et indice de vulnérabilité : étape suivante.'],
    }
    text = json.dumps({'meta': meta, 'points': points, 'cells': cells}, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (DATA / 'climate.json').write_text(text, encoding='utf-8')
    with gzip.open(DATA / 'climate.json.gz', 'wt', encoding='utf-8', compresslevel=9) as f:
        f.write(text)
    print(f'climate.json: {len(points)} points, {len(cells)} cells, {len(text) / 1e6:.1f} MB')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['points', 'download-climate', 'download-ndvi', 'build'])
    a = ap.parse_args()
    if a.step == 'points':
        print(len(grid_points()), grid_points())
    else:
        sys.exit(1 if {'download-climate': download_climate, 'download-ndvi': download_ndvi, 'build': build}[a.step]() else 0)
