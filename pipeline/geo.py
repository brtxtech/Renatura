"""Pilot spatial preparation in Lambert-93 with explicit boundary clipping."""
from __future__ import annotations

import math
from pathlib import Path
import geopandas as gpd
from shapely import make_valid
from shapely.geometry import Polygon
from .scoring import percentile_scores


def load_layer(path):
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f'Missing CRS in {path}')
    frame = frame.to_crs(2154)
    frame.geometry = frame.geometry.map(make_valid)
    frame = frame[~frame.geometry.is_empty & frame.geometry.notna()].copy()
    if not frame.geometry.is_valid.all():
        raise ValueError('Geometry repair failed')
    # Exact duplicate geometries cannot contribute twice to area or length.
    frame = frame.loc[~frame.geometry.to_wkb().duplicated()].copy()
    return frame


def hexagons(boundary, area=1_000_000):
    radius = math.sqrt(2 * area / (3 * math.sqrt(3)))
    dx, dy = 1.5 * radius, math.sqrt(3) * radius
    minx, miny, maxx, maxy = boundary.bounds
    result = []
    for column in range(math.floor(minx / dx) - 1, math.ceil(maxx / dx) + 1):
        for row in range(math.floor(miny / dy) - 1, math.ceil(maxy / dy) + 1):
            x = column * dx
            y = (row + (column % 2) / 2) * dy
            ring = [(x + radius * math.cos(i * math.pi / 3),
                     y + radius * math.sin(i * math.pi / 3)) for i in range(6)]
            polygon = Polygon(ring).intersection(boundary)
            if polygon.is_empty or polygon.area < 10_000:
                continue
            result.append({'id': f'HEX-{column}-{row}', 'geometry': polygon,
                           'center': [polygon.centroid.x, polygon.centroid.y],
                           'area_ha': polygon.area / 10000})
    return sorted(result, key=lambda item: item['id'])


def measure(frame, geometry, kind):
    indices = frame.sindex.query(geometry, predicate='intersects')
    if len(indices) == 0:
        return 0.0
    clipped = frame.iloc[indices].geometry.intersection(geometry)
    if kind == 'area':
        return clipped.union_all().area
    return clipped.length.sum()


def prepare(raw, analysis_area=1_000_000):
    raw = Path(raw)
    natura = load_layer(next((raw / 'natura').rglob('*.shp')))
    selected = natura[natura['SITECODE'] == 'FR2502014']
    if selected.empty:
        raise ValueError('Official pilot boundary FR2502014 absent')
    boundary = selected.geometry.union_all()
    hedges = {}
    woods = {}
    for year in (1947, 2010, 2016):
        hedges[year] = load_layer(next((raw / 'pilot').rglob(f'*{year}_l_061.shp')))
        # Exclude CR (woodland-edge connectors) and ZB (became woodland).
        hedges[year] = hedges[year][hedges[year]['Nature'].str.lower() == 'haie']
        woods[year] = load_layer(next((raw / 'pilot').rglob(f'*{year}_s_061.shp')))
    communes = load_layer(raw / 'communes.geojson')
    cells = hexagons(boundary, area=analysis_area)
    for cell in cells:
        geometry = cell['geometry']
        for year in (1947, 2010, 2016):
            cell[f'hedge_{year}_m'] = float(measure(hedges[year], geometry, 'length'))
            cell[f'wood_{year}_ha'] = float(measure(woods[year], geometry, 'area') / 10000)
        cell['woodland_ha'] = cell['wood_2016_ha']
        cell['hedge_density'] = cell['hedge_2016_m'] / cell['area_ha']
        # Net length change is an indicator, not causal degradation evidence.
        original = cell['hedge_2010_m']
        cell['loss_fraction'] = max(0, 1 - cell['hedge_2016_m'] / original) if original > 0 else None
        candidates = communes.iloc[communes.sindex.query(geometry, predicate='intersects')]
        names = []
        for _, commune in candidates.iterrows():
            overlap = geometry.intersection(commune.geometry).area
            if overlap > 0:
                names.append((overlap, str(commune['nom']), str(commune['code'])))
        names.sort(reverse=True)
        cell['commune'] = names[0][1] if names else 'Hors référentiel communal'
        cell['commune_codes'] = [item[2] for item in names]
        cell['department'] = '61'
        cell['P'] = None
        cell['O'] = None
        # Hectare proxy: no monetary interpretation, no invented cost multiplier.
        cell['proxy_cost'] = cell['area_ha']
    densities = percentile_scores([c['hedge_density'] for c in cells])
    woodland = percentile_scores([c['woodland_ha'] / c['area_ha'] for c in cells])
    for cell, hedge_rank, woodland_rank in zip(cells, densities, woodland):
        cell['V'] = (hedge_rank + woodland_rank) / 2
        cell['D'] = None if cell['loss_fraction'] is None else 100 * cell['loss_fraction']
        cell['coverage'] = 25 * sum(cell[k] is not None for k in ('V', 'D', 'P', 'O'))
    return cells, boundary, hedges, woods, selected


def to_features(cells):
    frame = gpd.GeoDataFrame(cells, crs=2154)
    frame = frame.drop(columns=['center'])
    return frame.to_crs(4326).__geo_interface__
