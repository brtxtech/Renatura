#!/usr/bin/env python3
"""Precompute the files the Normandy explorer loads, so the browser does not parse 215 MB on every visit.

From dist/data/normandie/cells.geojson (the full result of the regional build) it writes:
  cells_display.geojson (+ .gz)  geometry (5 decimals) + the scalar fields the map / ranking / panel use,
                                 plus the default restoration score and rank (precomputed once)
  cells_meta.json                texts identical in every cell (methods, missing reasons, reference, years)
  cells_detail/<column>.json     heavy per-cell details (evidence, metrics, layers hit…), loaded on click only
  display_manifest.json          fingerprint of the source; the build is skipped when nothing changed

    python tools/normandie/build_display.py          # rebuild only if cells.geojson changed
    python tools/normandie/build_display.py --force
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / 'dist/data/normandie'
SHARED = ('methods', 'missing_reasons', 'normalization_reference', 'observation_years', 'context_methods')
HEAVY = ('evidence', 'metrics', 'hit_themes', 'context_themes_list', 'V_raw', 'D_raw', 'P_raw', 'O_raw',
         'V_weight_coverage', 'D_weight_coverage', 'P_weight_coverage', 'O_weight_coverage', 'pilot_V', 'pilot_D')
WEIGHTS = (0.30, 0.30, 0.15, 0.25)
KEYS = ('V', 'D', 'P', 'O')


def fingerprint(path):
    st = path.stat()
    h = hashlib.sha256()
    with open(path, 'rb') as f:  # head + tail + size/mtime: fast and enough to detect a rebuild
        h.update(f.read(1 << 20))
        f.seek(max(0, st.st_size - (1 << 20)))
        h.update(f.read())
    return f'{st.st_size}-{int(st.st_mtime)}-{h.hexdigest()[:16]}'


def round_coords(c):
    return [round_coords(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 5), round(c[1], 5)]


def default_score(p):
    """Same rule as the browser (scoreSite, partial mode): eligible if V >= 10, renormalised on present criteria."""
    v = p.get('V')
    if not isinstance(v, (int, float)) or v < 10:
        return None
    have = [(w, p[k]) for w, k in zip(WEIGHTS, KEYS) if isinstance(p.get(k), (int, float)) and math.isfinite(p[k])]
    wsum = sum(w for w, _ in have)
    return round(sum(w * x for w, x in have) / wsum, 3) if wsum else None


def chunk_key(cell_id):
    parts = cell_id.split('_')
    return parts[1] if len(parts) >= 3 else 'misc'  # one file per grid column (~120 cells)


def build(force=False):
    src = DATA / 'cells.geojson'
    if not src.exists():
        raise SystemExit('cells.geojson absent')
    fp = fingerprint(src)
    man_path = DATA / 'display_manifest.json'
    if not force and man_path.exists() and json.loads(man_path.read_text()).get('source') == fp \
            and (DATA / 'cells_display.geojson.gz').exists():
        print('display files up to date (source unchanged)')
        return False
    fc = json.loads(src.read_text(encoding='utf-8'))
    feats = fc['features']
    shared = {}
    for k in SHARED:
        vals = {json.dumps(f['properties'].get(k), sort_keys=True, ensure_ascii=False) for f in feats}
        if len(vals) == 1:  # truly identical everywhere -> store once
            shared[k] = feats[0]['properties'].get(k)
    scores = [(default_score(f['properties']), f['properties']['id']) for f in feats]
    order = sorted((s, i) for s, i in scores if s is not None)
    order = sorted(order, key=lambda t: (-t[0], t[1]))
    rank = {i: n + 1 for n, (_, i) in enumerate(order)}
    out_feats, chunks = [], {}
    for f, (score, cid) in zip(feats, scores):
        p = f['properties']
        light = {k: v for k, v in p.items() if k not in HEAVY and k not in shared}
        light['rp_default'] = score
        light['rank_default'] = rank.get(cid)
        out_feats.append({'type': 'Feature', 'geometry': {'type': f['geometry']['type'], 'coordinates': round_coords(f['geometry']['coordinates'])},
                          'properties': light})
        chunks.setdefault(chunk_key(cid), {})[cid] = {k: p[k] for k in HEAVY if k in p}
    display = {'type': 'FeatureCollection', 'features': out_feats}
    text = json.dumps(display, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (DATA / 'cells_display.geojson').write_text(text, encoding='utf-8')
    with gzip.open(DATA / 'cells_display.geojson.gz', 'wt', encoding='utf-8', compresslevel=9) as g:
        g.write(text)
    (DATA / 'cells_meta.json').write_text(json.dumps(shared, ensure_ascii=False), encoding='utf-8')
    detail_dir = DATA / 'cells_detail'
    tmp = DATA / 'cells_detail.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for key, rows in chunks.items():
        (tmp / f'{key}.json').write_text(json.dumps(rows, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    shutil.rmtree(detail_dir, ignore_errors=True)
    tmp.rename(detail_dir)
    man_path.write_text(json.dumps({'source': fp, 'cells': len(feats), 'chunks': len(chunks), 'chunk_rule': 'id H1_<column>_<row> -> cells_detail/<column>.json',
                                    'shared_fields': list(shared), 'heavy_fields': list(HEAVY), 'eligible_ranked': len(rank)}, indent=1))
    print(f'cells_display.geojson {len(text) / 1e6:.1f} MB · {len(chunks)} detail chunks · shared {list(shared)} · ranked {len(rank)}')
    city_files(feats)
    return True


def city_files(feats):
    """Compact cell table + commune outlines for the city / cell-size page (ville-normandie.html).

    cells_points.json : columnar arrays (id, Lambert-93 x/y, lon/lat, area, V, D, P, O, commune index)
    communes.geojson  : 2,651 Normandy communes (insee, name), simplified ~30 m, from the atlas layer
                        'Communes concernées par les milieux humides' (complete list of the region's communes)
    """
    import shapely
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    geoms = [shape(f['geometry']) for f in feats]
    cent = shapely.centroid(geoms)
    lon, lat = shapely.get_x(cent), shapely.get_y(cent)
    x, y = Transformer.from_crs(4326, 2154, always_xy=True).transform(lon, lat)
    comm, names = [], []
    for ch in sorted((ROOT / 'dist/data/atlas/api_a6d7ddcd921b8ae9').glob('*.geojson.gz')):
        for f in json.load(gzip.open(ch))['features']:
            p = {k.split('}')[-1]: v for k, v in (f.get('properties') or {}).items()}
            if f.get('geometry') and p.get('insee_com'):
                comm.append(shape(f['geometry']).buffer(0))
                names.append({'insee': str(p['insee_com']), 'name': str(p.get('nom_m') or p['insee_com']).title()})
    tree = shapely.STRtree(comm)
    pi, ci = tree.query(cent, predicate='within')
    commune_of = [-1] * len(feats)
    for a, b in zip(pi, ci):
        commune_of[int(a)] = int(b)
    r = lambda v, d: None if not isinstance(v, (int, float)) or not math.isfinite(v) else round(v, d)
    props = [f['properties'] for f in feats]
    table = {'fields': 'columnar arrays aligned by index; x/y Lambert-93 (m); commune = index in communes',
             'communes': names, 'id': [p['id'] for p in props],
             'x': [int(v) for v in x], 'y': [int(v) for v in y],
             'lon': [round(float(v), 5) for v in lon], 'lat': [round(float(v), 5) for v in lat],
             'area': [r(p.get('area_ha'), 2) for p in props],
             **{k: [r(p.get(k), 1) for p in props] for k in KEYS},
             'commune': commune_of}
    t = json.dumps(table, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (DATA / 'cells_points.json').write_text(t, encoding='utf-8')
    with gzip.open(DATA / 'cells_points.json.gz', 'wt', encoding='utf-8', compresslevel=9) as g:
        g.write(t)
    simple = shapely.simplify(comm, 0.0003, preserve_topology=True)
    fc = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {**n, 'index': i}, 'geometry': {'type': m['type'], 'coordinates': round_coords(m['coordinates'])}}
        for i, (n, m) in enumerate((n, mapping(g)) for n, g in zip(names, simple))]}
    c = json.dumps(fc, ensure_ascii=False, separators=(',', ':'))
    (DATA / 'communes.geojson').write_text(c, encoding='utf-8')
    with gzip.open(DATA / 'communes.geojson.gz', 'wt', encoding='utf-8', compresslevel=9) as g:
        g.write(c)
    print(f'cells_points.json {len(t) / 1e6:.1f} MB · communes.geojson {len(c) / 1e6:.1f} MB · '
          f'{sum(v >= 0 for v in commune_of)}/{len(feats)} cells inside a commune')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    build(ap.parse_args().force)
