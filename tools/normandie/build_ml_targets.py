#!/usr/bin/env python3
"""Independent observed targets for the Renatura AI models.

1. human_pressure  <- INSEE Filosofi population, 1 km squares (2015, 2017), area-weighted into the 1 km² cells.
   observed_human_pressure = log10(1 + inhabitants per km²). Census-based measurement, independent from the
   atlas layers used to build P. Absent square = no inhabited square published = 0 inhabitants.
   Features come from the closest CORINE edition (2015 -> CLC 2012, 2017 -> CLC 2018).
   -> datasets/normandie_regional/ml/features_pressure.csv
2. eco_vulnerability <- natural habitat loss observed by CORINE over the next 6 years:
   natural_fraction = forests & semi-natural (3xx) + wetlands (4xx);
   observed_ecological_impact(t) = natural(t) - natural(t + 6)  (positive = habitat lost).
   natural_loss_prev = loss over the previous period (reference rule).
   -> columns added to datasets/normandie_regional/ml/features_clc.csv

Usage: .venv-normandie/bin/python tools/normandie/build_ml_targets.py
"""
from __future__ import annotations

import gzip
import json
import pathlib

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

ROOT = pathlib.Path(__file__).resolve().parents[2]
ML = ROOT / 'datasets/normandie_regional/ml'
INSEE = ROOT / 'datasets/normandie_regional/insee'
TO_L93 = Transformer.from_crs(4326, 2154, always_xy=True).transform
CLC_FOR = {2015: 2012, 2017: 2018}


def polygonal(g):
    g = shapely.make_valid(g)
    if g.geom_type in ('Polygon', 'MultiPolygon'):
        return g
    parts = [p for p in shapely.get_parts(g) if p.geom_type in ('Polygon', 'MultiPolygon')]
    return shapely.union_all(parts) if parts else shapely.Polygon()


def ecological_targets():
    path = ML / 'features_clc.csv'
    t = pd.read_csv(path)
    t['natural_fraction'] = t['forest_seminatural_fraction'] + t['wetland_fraction']
    nat = t.pivot(index='cell_id', columns='observation_year', values='natural_fraction')
    years = sorted(nat.columns)
    nxt = {y: nat[y] - nat[n] for y, n in zip(years, years[1:])}          # loss over the next period
    prv = {n: nat[y] - nat[n] for y, n in zip(years, years[1:])}          # loss over the previous period
    t['observed_ecological_impact'] = [nxt[y].get(c, np.nan) if y in nxt else np.nan for c, y in zip(t.cell_id, t.observation_year)]
    t['natural_loss_prev'] = [prv[y].get(c, np.nan) if y in prv else np.nan for c, y in zip(t.cell_id, t.observation_year)]
    t.to_csv(path, index=False, float_format='%.5f')
    lost = t.groupby('observation_year').observed_ecological_impact.apply(lambda s: float((s > 0.01).mean() * 100))
    print('habitat loss > 1 pt over the next 6 years (% of cells):', lost.round(2).to_dict())
    return t


def human_context(ids):
    """Per-cell human-presence measurements already in the project (cells_detail metrics + built 2017)."""
    if hasattr(human_context, 'cache'):
        return human_context.cache
    det = {}
    for f in (ROOT / 'dist/data/normandie/cells_detail').glob('*.json'):
        for cid, d in json.load(open(f)).items():
            det[cid] = d.get('metrics') or {}
    clim = json.load(gzip.open(ROOT / 'dist/data/normandie/climate.json.gz', 'rt'))['cells']
    m = lambda k: np.array([det.get(c, {}).get(k, np.nan) if det.get(c, {}).get(k) is not None else np.nan for c in ids], float)
    human_context.cache = {'roads_m_ha': m('roads'), 'transit_stops': m('stops'), 'icpe': m('icpe'), 'rail': m('rail'),
                           'built_share_2017': np.array([clim.get(c, {}).get('built_2017', np.nan) if clim.get(c, {}).get('built_2017') is not None else np.nan for c in ids], float)}
    return human_context.cache


def population_targets(clc):
    cells = json.load(gzip.open(ROOT / 'dist/data/normandie/cells_display.geojson.gz', 'rt'))['features']
    ids = np.array([c['properties']['id'] for c in cells])
    cg = np.array([polygonal(transform(TO_L93, shape(c['geometry']))) for c in cells], dtype=object)
    carea = shapely.area(cg)
    tree = shapely.STRtree(cg)
    bbox = tuple(shapely.total_bounds(cg))
    rows = []
    for year, clc_year in CLC_FOR.items():
        files = sorted(INSEE.glob(f'f{year}/**/*met*.gpkg')) or sorted(INSEE.glob(f'f{year}/**/*.gpkg'))
        if not files:
            print(f'Filosofi {year}: file not found, skipped')
            continue
        f = files[0]
        layer = pyogrio.list_layers(f)[0][0]
        info = pyogrio.read_info(f, layer=layer)
        fields = list(info['fields'])
        ind = next(c for c in fields if c.lower() == 'ind')
        sq = pyogrio.read_dataframe(f, layer=layer, columns=[ind], bbox=bbox)
        if str(info['crs']) not in ('EPSG:2154',):
            sq = sq.to_crs(2154)
        geoms = np.array([polygonal(g) for g in sq.geometry.values], dtype=object)
        li, ci = tree.query(geoms, predicate='intersects')
        share = shapely.area(shapely.intersection(geoms[li], cg[ci], grid_size=0.01)) / shapely.area(geoms[li])
        pop = np.bincount(ci, weights=sq[ind].to_numpy()[li] * share, minlength=len(ids))
        density = pop / (carea / 1e6)
        feats = clc[clc.observation_year == clc_year].set_index('cell_id').reindex(ids)
        df = feats.reset_index().rename(columns={'index': 'cell_id'})
        df['observation_year'] = year
        df['clc_year_used'] = clc_year
        df['population'] = pop
        for k, v in human_context(ids).items():   # P-layer measurements as predictors (the target stays INSEE)
            df[k] = v
        df['observed_human_pressure'] = np.log10(1 + density)
        rows.append(df)
        print(f'Filosofi {year}: {len(sq):,} squares in the bbox · {pop.sum():,.0f} inhabitants in Normandy cells')
    if rows:
        out = pd.concat(rows, ignore_index=True)
        out.to_csv(ML / 'features_pressure.csv', index=False, float_format='%.5f')
        print(f'{len(out):,} rows -> features_pressure.csv')


if __name__ == '__main__':
    population_targets(ecological_targets())
