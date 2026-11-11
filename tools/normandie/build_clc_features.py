#!/usr/bin/env python3
"""CORINE Land Cover 2000 / 2006 / 2012 / 2018 over Normandy -> feature table per (cell_id, observation_year).

Why CORINE: it is the only land-cover series in the project with the same method every 6 years, so it gives
comparable observations in time (the atlas copies were PARTIAL: collected without a spatial filter).
Revised editions are used (2000R, 2006R, 2012R) plus 2018, so that changes between dates are consistent.

Output (not versioned, datasets/ is git-ignored):
  datasets/normandie_regional/ml/features_clc.csv   one row per cell and year, NaN = not observed
Columns: cell_id, observation_year, artificial_fraction, urban_fabric_fraction, industrial_transport_fraction,
         mines_construction_fraction, green_urban_fraction, agri_fraction, forest_seminatural_fraction,
         wetland_fraction, water_fraction, artificial_neigh_3km

1990 (non-revised edition) is fetched only to compute the previous-period change of 2000.

Usage: .venv-normandie/bin/python tools/normandie/build_clc_features.py
"""
from __future__ import annotations

import concurrent.futures
import gzip
import json
import pathlib
import time

import numpy as np
import pandas as pd
import requests
import shapely
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / 'datasets/normandie_regional/clc'
OUT = ROOT / 'datasets/normandie_regional/ml/features_clc.csv'
WFS = 'https://data.geopf.fr/wfs/ows'
EDITIONS = {1990: 'LANDCOVER.CLC90_FR:clc90_fr', 2000: 'LANDCOVER.CLC0OR_FR:clc00r_fr', 2006: 'LANDCOVER.CLC06R_FR:clc06r_fr',
            2012: 'LANDCOVER.CLC12R_FR:clc12r_fr', 2018: 'LANDCOVER.CLC18_FR:clc18_fr'}
TO_L93 = Transformer.from_crs(4326, 2154, always_xy=True).transform
UA = {'User-Agent': 'renatura-atlas/1.0 (open-data research client)'}
PAGE = 5000


def polygonal(g):
    """make_valid can return a GeometryCollection with lines/points: keep only the surface part."""
    g = shapely.make_valid(g)
    if g.geom_type in ('Polygon', 'MultiPolygon'):
        return g
    parts = [p for p in shapely.get_parts(g) if p.geom_type in ('Polygon', 'MultiPolygon')]
    return shapely.union_all(parts) if parts else shapely.Polygon()


def fetch_tile(typename, bounds, session):
    x0, y0, x1, y1 = bounds
    cache = WORK / typename.split(':')[1] / f'{int(x0)}_{int(y0)}.json.gz'
    if cache.exists():
        return json.load(gzip.open(cache, 'rt'))
    feats, start = [], 0
    while True:
        params = {'SERVICE': 'WFS', 'REQUEST': 'GetFeature', 'VERSION': '2.0.0', 'TYPENAMES': typename,
                  'OUTPUTFORMAT': 'application/json', 'SRSNAME': 'EPSG:2154', 'COUNT': PAGE, 'STARTINDEX': start,
                  'SORTBY': 'id', 'BBOX': f'{x0},{y0},{x1},{y1},urn:ogc:def:crs:EPSG::2154'}
        for attempt in range(6):
            try:
                r = session.get(WFS, params=params, timeout=180, headers=UA)
                r.raise_for_status()
                page = r.json()
                break
            except Exception as e:
                if attempt == 5:
                    raise RuntimeError(f'{typename} tile {x0},{y0}: {e}') from e
                time.sleep(3 * 2 ** attempt)
        got = page.get('features') or []
        feats += got
        if len(got) < PAGE:
            break
        start += PAGE
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, 'wt') as f:
        json.dump(feats, f, separators=(',', ':'))
    return feats


def main():
    boundary = json.load(open(ROOT / 'dist/data/atlas/normandie.geojson'))
    region = shapely.make_valid(transform(TO_L93, shape(boundary['features'][0]['geometry'])))
    step = 40000
    rx0, ry0, rx1, ry1 = region.bounds
    tiles = [(x, y, x + step, y + step) for x in np.arange(rx0 // step * step, rx1, step)
             for y in np.arange(ry0 // step * step, ry1, step) if region.intersects(box(x, y, x + step, y + step))]

    cells = json.load(gzip.open(ROOT / 'dist/data/normandie/cells_display.geojson.gz', 'rt'))['features']
    ids = [c['properties']['id'] for c in cells]
    cgeoms = np.array([polygonal(transform(TO_L93, shape(c['geometry']))) for c in cells], dtype=object)
    careas = shapely.area(cgeoms)
    ctree = shapely.STRtree(cgeoms)
    centres = shapely.centroid(cgeoms)
    cx, cy = shapely.get_x(centres), shapely.get_y(centres)
    neigh = shapely.STRtree(centres).query(shapely.buffer(centres, 3000), predicate='intersects')  # (cell, neighbour)

    session = requests.Session()
    frames = []
    for year, typename in EDITIONS.items():
        raw = {}
        with concurrent.futures.ThreadPoolExecutor(4) as ex:
            for feats in ex.map(lambda t: fetch_tile(typename, t, session), tiles):
                for f in feats:
                    raw[f.get('id') or f['properties'].get('id')] = f
        geoms, codes = [], []
        for f in raw.values():
            if not f.get('geometry'):
                continue
            code = str(f['properties'].get(next(k for k in f['properties'] if k.startswith('code_'))) or '')
            if len(code) != 3:
                continue
            g = polygonal(shape(f['geometry']))
            if g.is_empty:
                continue
            geoms.append(g)
            codes.append(code)
        geoms = np.array(geoms, dtype=object)
        codes = np.array(codes)
        li, ci = ctree.query(geoms, predicate='intersects')
        inter = shapely.area(shapely.intersection(geoms[li], cgeoms[ci], grid_size=0.01))
        groups = {
            'artificial_fraction': lambda c: c[0] == '1', 'urban_fabric_fraction': lambda c: c[:2] == '11',
            'industrial_transport_fraction': lambda c: c[:2] == '12', 'mines_construction_fraction': lambda c: c[:2] == '13',
            'green_urban_fraction': lambda c: c[:2] == '14', 'agri_fraction': lambda c: c[0] == '2',
            'forest_seminatural_fraction': lambda c: c[0] == '3', 'wetland_fraction': lambda c: c[0] == '4',
            'water_fraction': lambda c: c[0] == '5'}
        covered = np.bincount(ci, weights=inter, minlength=len(ids)) / careas
        row = {'cell_id': ids, 'observation_year': year}
        for name, test in groups.items():
            mask = np.array([test(c) for c in codes[li]])
            row[name] = np.clip(np.bincount(ci[mask], weights=inter[mask], minlength=len(ids)) / careas, 0, 1)
        df = pd.DataFrame(row)
        # a cell CORINE does not cover (sea, outside the WFS answer) is not observed: NaN, never 0
        df.loc[covered < 0.5, list(groups)] = np.nan
        a = df['artificial_fraction'].to_numpy()
        s = np.bincount(neigh[0], weights=np.nan_to_num(a[neigh[1]]), minlength=len(ids))
        n = np.bincount(neigh[0], weights=~np.isnan(a[neigh[1]]), minlength=len(ids))
        df['artificial_neigh_3km'] = np.where(n > 0, s / np.maximum(n, 1), np.nan)
        frames.append(df)
        print(f'{year}: {len(raw):,} polygons · {int((covered >= .5).sum()):,} cells observed · '
              f'artificial {np.nanmean(df.artificial_fraction) * 100:.2f} % on average', flush=True)
    table = pd.concat(frames, ignore_index=True)
    table['x_l93'] = np.tile(cx, len(EDITIONS))
    table['y_l93'] = np.tile(cy, len(EDITIONS))
    # recent dynamics: change over the previous period, scaled to 6 years (1990->2000 is a 10-year step)
    years = sorted(EDITIONS)
    a = table.pivot(index='cell_id', columns='observation_year', values='artificial_fraction')
    nb = table.pivot(index='cell_id', columns='observation_year', values='artificial_neigh_3km')
    lag, lag_n = {}, {}
    for prev, cur in zip(years, years[1:]):
        lag[cur] = (a[cur] - a[prev]) * 6 / (cur - prev)
        lag_n[cur] = (nb[cur] - nb[prev]) * 6 / (cur - prev)
    table['artificial_change_prev'] = [lag.get(y, pd.Series(dtype=float)).get(c, np.nan) for c, y in zip(table.cell_id, table.observation_year)]
    table['artificial_neigh_change_prev'] = [lag_n.get(y, pd.Series(dtype=float)).get(c, np.nan) for c, y in zip(table.cell_id, table.observation_year)]
    table = table[table.observation_year > years[0]]   # 1990 only serves as the « previous period » of 2000
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False, float_format='%.5f')
    print(f'{len(table):,} rows -> {OUT.relative_to(ROOT)}', flush=True)


if __name__ == '__main__':
    main()
