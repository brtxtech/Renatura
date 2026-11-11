#!/usr/bin/env python3
"""BD Forêt V2 (IGN) for the whole of Normandy: region-wide forest mask.

The first collection asked the national WFS without a spatial filter: it read 5 500 features elsewhere in France,
then timed out, so the layer had no Normandy geometry. This tool pages the WFS tile by tile (20 km Lambert-93
tiles, BBOX filter, STARTINDEX paging, retries, resumable cache), clips to the regional boundary and writes:

  datasets/normandie_regional/bdforet_v2/bdforet_v2_normandie.geojson.gz  full-precision mask, EPSG:2154 (biomass work)
  dist/data/atlas/<layer id>/NNNN.geojson.gz + chunk_bounds               atlas display chunks (30 m, WGS84)
  dist/data/atlas/overviews/<layer id>.geojson.gz                         5 km overview (layer > 50 000 objects)
  dist/data/normandie/forest_cells.json                                   forest share per 1 km² regional cell
and registers the layer in catalog.json / catalog-v2.json (theme « Occupation du sol et urbanisme »).

Usage: .venv-normandie/bin/python tools/normandie/fetch_bdforet.py [--tile-km 20] [--workers 4]
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import datetime
import gzip
import json
import pathlib
import time

import numpy as np
import requests
import shapely
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

ROOT = pathlib.Path(__file__).resolve().parents[2]
ATLAS = ROOT / 'dist/data/atlas'
NORM = ROOT / 'dist/data/normandie'
WORK = ROOT / 'datasets/normandie_regional/bdforet_v2'
LAYER_ID = 'api_80511112b95c6311'           # existing catalogue entry « BD Forêt V2 »
TYPENAME = 'LANDCOVER.FORESTINVENTORY.V2:formation_vegetale'
WFS = 'https://data.geopf.fr/wfs/ows'
PAGE = 5000
TO_L93 = Transformer.from_crs(4326, 2154, always_xy=True).transform
TO_WGS = Transformer.from_crs(2154, 4326, always_xy=True).transform
UA = {'User-Agent': 'renatura-atlas/1.0 (open-data research client)'}


def dump_gz(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8', compresslevel=7) as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def fetch_tile(bounds, session):
    """All features of one tile (BBOX in Lambert-93), cached on disk."""
    x0, y0, x1, y1 = bounds
    cache = WORK / 'tiles' / f'{int(x0)}_{int(y0)}.json.gz'
    if cache.exists():
        return json.load(gzip.open(cache, 'rt'))
    feats, start = [], 0
    while True:
        params = {'SERVICE': 'WFS', 'REQUEST': 'GetFeature', 'VERSION': '2.0.0', 'TYPENAMES': TYPENAME,
                  'OUTPUTFORMAT': 'application/json', 'SRSNAME': 'EPSG:2154', 'COUNT': PAGE, 'STARTINDEX': start,
                  'SORTBY': 'id', 'BBOX': f'{x0},{y0},{x1},{y1},urn:ogc:def:crs:EPSG::2154'}
        for attempt in range(6):
            try:
                r = session.get(WFS, params=params, timeout=180, headers=UA)
                r.raise_for_status()
                page = r.json()
                break
            except Exception as e:  # network hiccup / 5xx / truncated JSON
                if attempt == 5:
                    raise RuntimeError(f'tile {x0},{y0} start {start}: {e}') from e
                time.sleep(3 * 2 ** attempt)
        got = page.get('features') or []
        feats += got
        if len(got) < PAGE:
            break
        start += PAGE
    dump_gz(cache, feats)
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tile-km', type=float, default=20)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()

    boundary = json.load(open(ATLAS / 'normandie.geojson'))
    region = shapely.make_valid(transform(TO_L93, shape(boundary['features'][0]['geometry'])))
    shapely.prepare(region)
    step = args.tile_km * 1000
    rx0, ry0, rx1, ry1 = region.bounds
    tiles = [(x, y, x + step, y + step) for x in np.arange(rx0 // step * step, rx1, step)
             for y in np.arange(ry0 // step * step, ry1, step) if region.intersects(box(x, y, x + step, y + step))]
    print(f'{len(tiles)} tiles of {args.tile_km:g} km', flush=True)

    raw = {}
    session = requests.Session()
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        for i, feats in enumerate(ex.map(lambda t: fetch_tile(t, session), tiles), 1):
            for f in feats:  # features crossing tile edges come back several times
                raw[f.get('id') or f['properties'].get('id')] = f
            if i % 10 == 0 or i == len(tiles):
                print(f'  tiles {i}/{len(tiles)} · {len(raw):,} unique features', flush=True)

    # ---- clip to Normandy
    kept, stats = [], collections.Counter()
    for fid, f in raw.items():
        if not f.get('geometry'):
            stats['no_geometry'] += 1
            continue
        g = shape(f['geometry'])
        if not g.is_valid:
            g = shapely.make_valid(g)
            stats['repaired'] += 1
        if not region.intersects(g):
            stats['outside'] += 1
            continue
        if not region.covers(g):
            g = g.intersection(region)
        if g.geom_type == 'GeometryCollection':
            g = shapely.union_all([p for p in g.geoms if p.geom_type in ('Polygon', 'MultiPolygon')])
        if g.is_empty:
            stats['outside'] += 1
            continue
        kept.append((fid, g, f['properties']))
    print(f'{len(kept):,} forest polygons in Normandy ({dict(stats)})', flush=True)

    # ---- 1. full-precision mask (Lambert-93) for biomass / modelling
    dump_gz(WORK / 'bdforet_v2_normandie.geojson.gz', {
        'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:EPSG::2154'}},
        'features': [{'type': 'Feature', 'id': fid, 'properties': p, 'geometry': mapping(g)} for fid, g, p in kept]})

    # ---- 2. atlas display chunks (same format as pipeline/atlas/build_atlas.py + compress_display.py)
    out = ATLAS / LAYER_ID
    for old in out.glob('*.geojson*'):
        old.unlink()
    chunks, bounds, display, size, n, shown = [], {}, [], 0, 0, 0

    def flush():
        nonlocal display, size
        if not display:
            return
        name = f'{LAYER_ID}/{len(chunks):04d}.geojson.gz'
        dump_gz(ATLAS / name, {'type': 'FeatureCollection', 'features': display})
        xs = [c for f in display for c in shapely.get_coordinates(shape(f['geometry']))[:, 0]]
        ys = [c for f in display for c in shapely.get_coordinates(shape(f['geometry']))[:, 1]]
        chunks.append(name)
        bounds[name] = [min(xs), min(ys), max(xs), max(ys)]
        display, size = [], 0

    # spatial order so that each chunk covers a compact area (viewport loading)
    kept.sort(key=lambda k: (int(k[1].centroid.x // 20000), int(k[1].centroid.y // 20000)))
    for fid, g, p in kept:
        n += 1
        simple = transform(TO_WGS, g.simplify(30, preserve_topology=True))
        if simple.is_empty:
            continue
        props = {**p, '_id': f'{LAYER_ID}:{n}', '_layer': LAYER_ID, '_origin': 'API collectée',
                 '_collection_status': 'COMPLETE', '_source_id': str(fid)}
        feat = {'type': 'Feature', 'id': props['_id'], 'properties': props,
                'geometry': json.loads(json.dumps(mapping(shapely.set_precision(simple, 1e-6))))}
        s = len(json.dumps(feat, ensure_ascii=False))
        if display and (size + s > 1_500_000 or len(display) >= 1200):
            flush()
        display.append(feat)
        size += s
        shown += 1
    flush()
    print(f'{len(chunks)} display chunks', flush=True)

    # ---- 3. 5 km overview (the atlas shows it below zoom 13 for layers > 50 000 objects)
    zones = json.load(open(ATLAS / 'zones.geojson'))['features']
    zgeoms = [transform(TO_L93, shape(z['geometry'])) for z in zones]
    tree = shapely.STRtree(zgeoms)
    counts = collections.Counter()
    for _, g, _ in kept:
        for j in tree.query(g.representative_point(), predicate='intersects'):
            counts[int(j)] += 1
    overview = [{'type': 'Feature', 'geometry': zones[j]['geometry'],
                 'properties': {'_layer': LAYER_ID, '_aggregation': True, '_count': c, '_source_id': zones[j]['properties']['id']}}
                for j, c in counts.items()]
    dump_gz(ATLAS / 'overviews' / f'{LAYER_ID}.geojson.gz', {'type': 'FeatureCollection', 'features': overview})

    # ---- 4. forest share per 1 km² regional cell
    cells = json.load(gzip.open(NORM / 'cells_display.geojson.gz', 'rt'))['features']
    cgeoms = np.array([transform(TO_L93, shape(c['geometry'])) for c in cells], dtype=object)
    careas = shapely.area(cgeoms)
    fgeoms = np.array([g for _, g, _ in kept], dtype=object)
    groups = np.array([(p.get('tfv_g11') or 'Inconnu') for _, _, p in kept])
    # reprojected cells / clipped polygons can carry tiny self-intersections: repair before overlay
    cgeoms = shapely.make_valid(cgeoms)
    fgeoms = shapely.make_valid(fgeoms)
    li, ci = shapely.STRtree(cgeoms).query(fgeoms, predicate='intersects')
    try:
        inter = shapely.area(shapely.intersection(fgeoms[li], cgeoms[ci]))
    except shapely.errors.GEOSException:  # last resort: snap to a 1 cm grid
        inter = shapely.area(shapely.intersection(fgeoms[li], cgeoms[ci], grid_size=0.01))
    share = collections.defaultdict(lambda: collections.Counter())
    for l, c, a in zip(li, ci, inter):
        share[int(c)][groups[l]] += a
    nonforest = ('lande', 'herbac')
    table = {}
    for c, cnt in share.items():
        total = sum(a for k, a in cnt.items() if not any(w in k.lower() for w in nonforest))
        table[cells[c]['properties']['id']] = {
            'forest_pct': round(min(100, 100 * total / careas[c]), 2),
            **{k: round(min(100, 100 * a / careas[c]), 2) for k, a in sorted(cnt.items())}}
    json.dump({'source': 'IGN BD Forêt V2 (formation_vegetale), WFS data.geopf.fr', 'unit': '% de la surface de la maille',
               'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
               'note': 'forest_pct exclut landes et formations herbacées. Mailles absentes = 0 % de forêt cartographiée.',
               'cells': table}, open(NORM / 'forest_cells.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'forest share computed for {len(table):,} / {len(cells):,} cells', flush=True)

    # ---- 5. register in the catalogues
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cat = json.load(open(ATLAS / 'catalog.json'))
    layer = next(l for l in cat['layers'] if l['id'] == LAYER_ID)
    previous = layer.get('map_count') or 0
    layer.update(status='COMPLETE', complete=True, records=len(raw), read_count=len(raw), map_count=shown,
                 outside_count=stats['outside'], no_geometry=stats['no_geometry'], repaired_count=stats['repaired'],
                 reason=None, errors=[], map_state='READY', chunks=chunks, chunk_bounds=bounds, collected_at=now,
                 crs_observed=['EPSG:2154'], overview_file=f'overviews/{LAYER_ID}.geojson.gz',
                 url=f'{WFS}?SERVICE=WFS&REQUEST=GetFeature&VERSION=2.0.0&TYPENAMES={TYPENAME}',
                 license=layer.get('license') or 'Licence Ouverte / Open Licence version 2.0',
                 collection_method=f'WFS paginé par tuiles de {args.tile_km:g} km (filtre BBOX Lambert-93), découpé au contour régional')
    st = cat['statistics']
    st['mapped_features'] = st.get('mapped_features', 0) - previous + layer['map_count']
    st['mapped_layers'] = sum(1 for l in cat['layers'] if l.get('map_count', 0) > 0)
    json.dump(cat, open(ATLAS / 'catalog.json', 'w'), ensure_ascii=False, separators=(',', ':'))

    v2 = json.load(open(ATLAS / 'catalog-v2.json'))
    v2['hidden_sources'] = [h for h in v2['hidden_sources'] if h['source_id'] != LAYER_ID]
    theme = next(t for t in v2['themes'] if t['id'] == 'landuse')
    group = next((g for g in theme['groups'] if g['id'] == 'g_forest_bdforet'), None)
    if group is None:
        group = {'id': 'g_forest_bdforet', 'display_name': 'Forêts et formations végétales', 'theme': 'landuse', 'facets': {}, 'selection': {}, 'layers': []}
        theme['groups'].insert(0, group)
        v2['statistics']['groups'] = v2['statistics'].get('groups', 0) + 1
    if not any(l['id'] == 'l_bdforet_v2' for l in group['layers']):
        v2['statistics']['logical_layers'] = v2['statistics'].get('logical_layers', 0) + 1
        v2['statistics']['variants'] = v2['statistics'].get('variants', 0) + 1
    group['layers'] = [l for l in group['layers'] if l['id'] != 'l_bdforet_v2'] + [{
        'id': 'l_bdforet_v2', 'display_name': 'Forêts — BD Forêt V2 (IGN)', 'theme': 'landuse', 'group': group['id'],
        'variants': [{'id': 'v_bdforet_v2', 'dimensions': {}, 'source_ids': [LAYER_ID], 'source_id': LAYER_ID,
                      'status': 'complete', 'map_count': layer['map_count'], 'updated': now, 'source': layer['url'],
                      'default_visible': False, 'geometry': 'polygon', 'variant_type': 'none', 'variant_value': None}]}]
    json.dump(v2, open(ATLAS / 'catalog-v2.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(f'catalogues updated: {layer["map_count"]:,} objects, layer visible in « {theme["display_name"]} »', flush=True)


if __name__ == '__main__':
    main()
