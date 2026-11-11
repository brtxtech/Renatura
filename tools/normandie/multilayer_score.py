#!/usr/bin/env python3
"""Regional multi-layer scoring of V/D/P/O from the atlas layers (see docs/PLAN_REGIONAL_SCORING.md).

Replaces the pilot-only V/D, the 3-layer P and the empty O of dist/data/normandie/cells.geojson by
criteria computed from the real atlas layers, each with a declared role, weight and coverage class
(tools/normandie/layer_scoring.json). Then re-runs complete_region (graph, corridors, ILP, Monte Carlo)
and writes an audit of the result (coverage, spread, agreement with the pilot).

    python tools/normandie/multilayer_score.py              # full run
    python tools/normandie/multilayer_score.py --no-complete  # scores only
"""
from __future__ import annotations

import argparse
import collections
import datetime
import gzip
import json
import math
import pathlib
import re
import sys

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import shape

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ATLAS = ROOT / 'dist/data/atlas'
DATA = ROOT / 'dist/data/normandie'
KEYS = ('V', 'D', 'P', 'O')
TO_L93 = Transformer.from_crs(4326, 2154, always_xy=True)
UNITS = {'area': 'part de surface', 'length': 'm/ha', 'count': 'objets/km²', 'inverse_area': 'part non bâtie',
         'growth': 'Δ part bâtie', 'pilot': 'score pilote'}
CRITERION_NAMES = {'V': 'valeur écologique reconnue', 'D': 'dégradation / besoin de restauration',
                   'P': 'pression anthropique', 'O': "opportunité d'action documentée"}


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))


def write(p, v):
    pathlib.Path(p).write_text(json.dumps(v, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def l93(geoms):
    return shapely.transform(geoms, lambda xy: np.column_stack(TO_L93.transform(xy[:, 0], xy[:, 1])))


def clean(geoms):
    """Repair invalid geometries one by one; reduce collections to their highest-dimension parts."""
    out = geoms.copy()
    for i in np.flatnonzero(~shapely.is_valid(geoms) | (shapely.get_type_id(geoms) == 7)):
        g = geoms[i]
        try:
            if g.geom_type == 'GeometryCollection':
                parts = list(g.geoms)
                dims = [int(shapely.get_dimensions(p)) for p in parts]
                dim = max(dims) if dims else 0
                g = shapely.union_all([p for p, d in zip(parts, dims) if d == dim]) if parts else shapely.Point()
            out[i] = g if g.is_valid else shapely.make_valid(g)
        except shapely.errors.GEOSException:
            out[i] = g.buffer(0) if int(shapely.get_dimensions(g)) == 2 else shapely.Point()
    return out


def strip(props):
    return {k.split('}')[-1]: v for k, v in (props or {}).items()}


# ------------------------------------------------------------------ inputs
class Catalog:
    def __init__(self):
        self.cat = read(ATLAS / 'catalog.json')
        self.by_id = {l['id']: l for l in self.cat['layers']}
        self.cache = {}

    def resolve(self, lid):
        if lid in self.by_id:
            return self.by_id[lid]
        hits = [l for k, l in self.by_id.items() if k.startswith(lid)]
        if len(hits) != 1:
            raise KeyError(f'layer id {lid!r}: {len(hits)} matches')
        return hits[0]

    def features(self, spec):
        """(geometries in EPSG:2154, list of stripped properties) for a layer spec."""
        key = spec.get('path') or self.resolve(spec['id'])['id']
        if key in self.cache:
            return self.cache[key]
        feats = []
        if spec.get('path'):
            feats = json.load(gzip.open(ROOT / spec['path']))['features']
        else:
            for ch in self.resolve(spec['id']).get('chunks') or []:
                if not (ATLAS / ch).exists():
                    print(f'  ! chunk missing, skipped: {ch}', flush=True)
                    continue
                feats += json.load(gzip.open(ATLAS / ch))['features']
        feats = [f for f in feats if f.get('geometry')]
        geoms = np.array([shape(f['geometry']) for f in feats], dtype=object)
        geoms = clean(l93(geoms)) if len(geoms) else geoms
        props = [strip(f.get('properties')) for f in feats]
        self.cache[key] = (geoms, props)
        return geoms, props

    def year(self, spec):
        m = re.search(r'(19|20)\d\d', spec.get('label', '') + ' ' + (self.by_id.get(spec['id'], {}).get('name') or ''))
        if m:
            return int(m.group(0))
        try:
            return int((self.resolve(spec['id']).get('collected_at') or '')[:4])
        except (KeyError, ValueError):
            return datetime.date.today().year


class Grid:
    def __init__(self, path):
        self.path = path
        self.collection = read(path)
        self.props = [f['properties'] for f in self.collection['features']]
        geoms = np.array([shape(f['geometry']) for f in self.collection['features']], dtype=object)
        self.geoms = l93(geoms)
        self.area_ha = shapely.area(self.geoms) / 1e4
        self.centroids = shapely.centroid(self.geoms)
        self.cx, self.cy = shapely.get_x(self.centroids), shapely.get_y(self.centroids)
        self.tree = shapely.STRtree(self.geoms)
        self.n = len(self.props)

    def measure(self, geoms, agg, factors=None):
        """Raw value per cell + feature hits per cell."""
        raw = np.zeros(self.n)
        hits = np.zeros(self.n, dtype=int)
        if len(geoms) == 0:
            return raw, hits
        factors = np.ones(len(geoms)) if factors is None else np.asarray(factors, dtype=float)
        keep = factors > 0
        li, ci = self.tree.query(geoms, predicate='intersects')
        hits = np.bincount(ci, minlength=self.n)
        mask = keep[li]
        li, ci = li[mask], ci[mask]
        if agg == 'count':
            raw = np.bincount(ci, weights=factors[li], minlength=self.n) / (self.area_ha / 100)
        else:
            inter = shapely.intersection(geoms[li], self.geoms[ci])
            if agg == 'length':
                raw = np.bincount(ci, weights=shapely.length(inter) * factors[li], minlength=self.n) / self.area_ha
            else:  # area-based
                raw = np.bincount(ci, weights=shapely.area(inter) * factors[li], minlength=self.n) / 1e4 / self.area_ha
                raw = np.minimum(raw, 1.0)
        return raw, hits

    def covered_by(self, geom):
        if geom is None or geom.is_empty:
            return np.zeros(self.n, dtype=bool)
        shapely.prepare(geom)
        return shapely.contains_xy(geom, self.cx, self.cy)


# ------------------------------------------------------------------ maths
def pilot_percentile(values, covered):
    """Midrank percentile over covered cells; 0 stays 0 (pilot rule); None where not covered."""
    out = np.full(len(values), np.nan)
    ref = np.sort(values[covered])
    if len(ref) == 0:
        return out
    v = values[covered]
    lo = np.searchsorted(ref, v, side='left')
    hi = np.searchsorted(ref, v, side='right')
    pct = 100 * (lo + (hi - lo) / 2) / len(ref)
    pct[v == 0] = 0.0
    out[covered] = pct
    return out


def presence_percentile(values):
    """Presence-only layers: absent = unknown (NaN); present = 50..100 by within-layer rank."""
    out = np.full(len(values), np.nan)
    pos = values > 0
    if pos.any():
        ref = np.sort(values[pos])
        v = values[pos]
        lo = np.searchsorted(ref, v, 'left')
        hi = np.searchsorted(ref, v, 'right')
        out[pos] = 50 + 50 * (lo + (hi - lo) / 2) / len(ref)
    return out


def spearman(a, b):
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 3:
        return None
    ra = np.argsort(np.argsort(a[m])).astype(float)
    rb = np.argsort(np.argsort(b[m])).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


# ------------------------------------------------------------------ territories
def territories(cfg, cat, grid):
    out, dept_of_cell = {}, np.array([None] * grid.n, dtype=object)
    geoms, props = cat.features({'id': 'api_a6d7ddcd921b8ae9'})  # all Normandy communes (milieux humides list)
    depts = collections.defaultdict(list)
    for g, p in zip(geoms, props):
        code = str(p.get('insee_com') or '')[:2]
        if code in ('14', '27', '50', '61', '76'):
            depts[code].append(g)
    dept_geom = {d: shapely.union_all(gs) for d, gs in depts.items()}
    for d, g in dept_geom.items():
        dept_of_cell[grid.covered_by(g)] = d
    out['BN'] = shapely.union_all([dept_geom[d] for d in ('14', '50', '61') if d in dept_geom])
    out['HN'] = shapely.union_all([dept_geom[d] for d in ('27', '76') if d in dept_geom])
    for key, prefix in cfg['tvb_territories'].items():
        corners = []
        for l in cat.cat['layers']:
            if (l.get('name') or '').startswith(prefix) and l.get('map_count'):
                g, _ = cat.features({'id': l['id']})
                b = shapely.bounds(g)
                b = b[~np.isnan(b).any(axis=1)]
                corners.append(np.vstack([b[:, [0, 1]], b[:, [2, 3]], b[:, [0, 3]], b[:, [2, 1]]]))
        out[key] = shapely.convex_hull(shapely.multipoints(np.vstack(corners))).buffer(500) if corners else None
    return out, dept_of_cell


# ------------------------------------------------------------------ main computation
def run(cfg_path, do_complete=True, runs=300, seconds=20):
    cfg = read(cfg_path)
    cat = Catalog()
    grid = Grid(DATA / 'cells.geojson')
    print(f'cells: {grid.n}')

    # preserve the original pilot criteria the first time
    for p in grid.props:
        if p.get('scoring') != 'multilayer_v1':
            p['pilot_V'], p['pilot_D'] = p.get('V'), p.get('D')
    pilot_V = np.array([np.nan if p.get('pilot_V') is None else p['pilot_V'] for p in grid.props], dtype=float)
    pilot_D = np.array([np.nan if p.get('pilot_D') is None else p['pilot_D'] for p in grid.props], dtype=float)

    terr, dept_of_cell = territories(cfg, cat, grid)
    terr_cover = {k: grid.covered_by(g) for k, g in terr.items()}
    terr_cover['pilot'] = ~np.isnan(pilot_V)
    print('territories:', {k: int(v.sum()) for k, v in terr_cover.items()})

    layer_scores, layer_raw, used = [], [], []
    for spec in cfg['layers']:
        agg, cov = spec['agg'], spec['coverage']
        if agg == 'pilot':
            src = pilot_V if spec['id'] == 'pilot_V' else pilot_D
            covered = ~np.isnan(src)
            score = np.where(covered, src, np.nan)
            raw = np.nan_to_num(src)
        else:
            geoms, props = cat.features(spec)
            factors = None
            if spec.get('field'):
                cls = spec['classes']
                factors = [cls.get(str(p.get(spec['field']) or '').strip(), 0.0) for p in props]
            mode = 'area' if agg in ('inverse_area', 'growth') else agg
            raw, _ = grid.measure(geoms, mode, factors)
            if agg == 'inverse_area':
                raw = 1.0 - raw
            elif agg == 'growth':
                g2, _ = cat.features({'id': spec['minus']})
                before, _ = grid.measure(g2, 'area')
                raw = np.maximum(0.0, raw - before)
            if cov == 'regional':
                covered = np.ones(grid.n, dtype=bool)
            elif cov == 'territorial' and agg == 'growth':
                # change between editions is only defined where BOTH editions exist: never outside the territory
                covered = terr_cover.get(spec['territory'], np.zeros(grid.n, bool))
            elif cov == 'territorial':
                covered = terr_cover.get(spec['territory'], np.zeros(grid.n, bool)) | (raw > 0)
            else:
                covered = raw > 0
            if agg == 'growth':
                raw = np.where(covered, raw, 0.0)  # no evidence row outside the comparable area
            score = presence_percentile(raw) if cov == 'presence' else pilot_percentile(raw, covered)
        layer_scores.append(score)
        layer_raw.append(raw)
        used.append(spec)
        print(f"  {spec['c']} {spec['label'][:60]:60s} covered={int((~np.isnan(score)).sum()):6d} positive={int((raw > 0).sum()):6d}", flush=True)

    # criterion composites
    composite, cov_share = {}, {}
    for c in KEYS:
        idx = [i for i, s in enumerate(used) if s['c'] == c]
        w = np.array([used[i]['w'] for i in idx])
        S = np.vstack([layer_scores[i] for i in idx])
        have = ~np.isnan(S)
        num = np.nansum(S * w[:, None], axis=0)
        den = (have * w[:, None]).sum(axis=0)
        share = den / w.sum()
        comp = np.where((den > 0) & (share >= cfg['min_weight_coverage']), num / np.maximum(den, 1e-9), np.nan)
        composite[c], cov_share[c] = comp, share

    # opportunity spills over to neighbouring cells (feasibility near documented action frameworks)
    so = cfg.get('opportunity_spillover')
    if so:
        from scipy.spatial import cKDTree
        pts = np.column_stack([grid.cx, grid.cy])
        tree = cKDTree(pts)
        own = np.nan_to_num(composite['O'])
        pairs = tree.query_pairs(so['radius_m'], output_type='ndarray')
        d = np.hypot(*(pts[pairs[:, 0]] - pts[pairs[:, 1]]).T)
        wgt = np.exp(-d / so['scale_m'])
        acc = np.bincount(pairs[:, 0], wgt * own[pairs[:, 1]], grid.n) + np.bincount(pairs[:, 1], wgt * own[pairs[:, 0]], grid.n)
        wsum = np.bincount(pairs[:, 0], wgt, grid.n) + np.bincount(pairs[:, 1], wgt, grid.n)
        neigh = np.where(wsum > 0, acc / np.maximum(wsum, 1e-9), 0)
        composite['O'] = np.where(np.isnan(composite['O']), np.nan, so['own_share'] * own + (1 - so['own_share']) * neigh)

    final = {}
    for c in KEYS:
        comp = composite[c]
        final[c] = pilot_percentile(np.nan_to_num(comp), ~np.isnan(comp)) if cfg.get('criterion_percentile') else comp

    # global hits: every mappable atlas layer intersecting each cell
    themes_of = {l['id']: l.get('category_ids') or [] for l in cat.cat['layers']}
    hit_layers = np.zeros(grid.n, dtype=int)
    cell_themes = [set() for _ in range(grid.n)]
    for l in cat.cat['layers']:
        if not l.get('map_count') or not l.get('chunks'):
            continue
        geoms, _ = cat.features({'id': l['id']})
        if not len(geoms):
            continue
        _, ci = grid.tree.query(geoms, predicate='intersects')
        cells_hit = np.unique(ci)
        hit_layers[cells_hit] += 1
        for i in cells_hit:
            cell_themes[i].update(themes_of[l['id']])
        cat.cache.pop(l['id'], None)  # free memory
    n_mappable = sum(1 for l in cat.cat['layers'] if l.get('map_count'))

    # write cells
    years = [cat.year(s) if s['agg'] != 'pilot' else 2016 for s in used]
    methods = {c: (f"{CRITERION_NAMES[c]} : moyenne pondérée des rangs percentiles de "
                   f"{sum(1 for s in used if s['c'] == c)} couches ({', '.join(sorted({s['label'] for s in used if s['c'] == c}))[:600]}…), "
                   "renormalisée sur les couches qui couvrent la maille (régionales : absence = 0 ; territoriales : hors territoire = non couvert ; "
                   "partielles : présence seulement), puis rang percentile régional (0 reste 0)."
                   + (" Diffusion de voisinage 5 km (60 % maille / 40 % voisinage)." if c == 'O' and so else ''))
               for c in KEYS}
    methods['O'] += " Opportunité documentée (SPRB, ORE, actions SRCE, continuités prioritaires, PNR…) : ce n'est ni une disponibilité foncière ni un consentement."
    for i, p in enumerate(grid.props):
        ev = {c: [] for c in KEYS}
        for j, s in enumerate(used):
            r = layer_raw[j][i]
            sc = layer_scores[j][i]
            if r > 0 and not np.isnan(sc):
                ev[s['c']].append({'sourceId': s['id'] if s['agg'] in ('pilot',) or s.get('path') else cat.resolve(s['id'])['id'],
                                   'year': years[j], 'metric': s['label'], 'value': round(float(r), 4),
                                   'unit': UNITS[s['agg']], 'score': round(float(sc), 1)})
        for c in KEYS:
            v = final[c][i]
            p[c] = None if np.isnan(v) else round(float(v), 2)
            p[f'{c}_raw'] = None if np.isnan(composite[c][i]) else round(float(composite[c][i]), 3)
            p[f'{c}_weight_coverage'] = round(float(cov_share[c][i]), 3)
        p['evidence'] = ev
        p['methods'] = methods
        p['missing_reasons'] = {c: f'Moins de {int(cfg["min_weight_coverage"] * 100)} % du poids des couches {c} couvre la maille.' for c in KEYS}
        p['normalization_reference'] = f"Normandie / {len(used)} couches pondérées (layer_scoring.json {cfg['version']}) / {datetime.date.today().isoformat()}"
        p['coverage'] = 25 * sum(p[c] is not None for c in KEYS)
        p['hit_layers'] = int(hit_layers[i])
        p['hit_layers_pct'] = round(100 * hit_layers[i] / n_mappable, 1)
        p['hit_themes'] = sorted(cell_themes[i])
        if dept_of_cell[i] and not p.get('department'):
            p['department'] = dept_of_cell[i]
        p['scoring'] = 'multilayer_v1'
        # regional habitat-size proxy for the connectivity graph (pilot keeps its observed woodland_ha too)
        p['habitat_ha'] = None if p['V'] is None else round(float(grid.area_ha[i]) * p['V'] / 100, 3)
        m = p.setdefault('metrics', {})
        for j, s in enumerate(used):
            if s.get('key'):
                m[s['key']] = round(float(layer_raw[j][i]), 4)
    write(grid.path, grid.collection)
    with open(grid.path, 'rb') as src, gzip.open(str(grid.path) + '.gz', 'wb', compresslevel=9) as dst:
        dst.write(src.read())

    # data catalogue: mark used layers
    dcat_path = DATA / 'data_catalog.json'
    dcat = read(dcat_path)
    by = {d['id']: d for d in dcat}
    for s in used:
        rid = s['id'] if s['agg'] == 'pilot' or s.get('path') else cat.resolve(s['id'])['id']
        entry = by.get(rid) or {'id': rid, 'title': s['label'], 'categories': [], 'licence': 'Voir source', 'years': [],
                                'url': s.get('path'), 'resolution': '1 km²', 'crs': 'EPSG:2154', 'sha256': None}
        entry.update(status='used', processing=f"{s['c']} · poids {s['w']} · {s['agg']} · couverture {s['coverage']}"
                     + (f" ({s.get('territory')})" if s.get('territory') else ''),
                     usage=f"Critère {s['c']} ({CRITERION_NAMES[s['c']]}) : {s['label']}")
        if rid not in by:
            dcat.append(entry)
            by[rid] = entry
    write(dcat_path, dcat)

    # audit
    audit = {'layers_used': len(used), 'distinct_sources': len({s['id'] for s in used}), 'mappable_layers': n_mappable,
             'criteria': {}}
    for c in KEYS:
        v = final[c][~np.isnan(final[c])]
        vals, counts = np.unique(np.round(v, 2), return_counts=True) if len(v) else (np.array([]), np.array([0]))
        audit['criteria'][c] = {
            'covered_cells': int(len(v)), 'covered_pct': round(100 * len(v) / grid.n, 2),
            'distinct_values': int(len(vals)), 'modal_share_pct': round(100 * counts.max() / max(len(v), 1), 1),
            'quantiles': [round(float(q), 1) for q in np.percentile(v, [5, 25, 50, 75, 95])] if len(v) else None,
            'layers': sum(1 for s in used if s['c'] == c)}
    def without_pilot(c):
        idx = [i for i, s in enumerate(used) if s['c'] == c and s['agg'] != 'pilot']
        w = np.array([used[i]['w'] for i in idx])
        S = np.vstack([layer_scores[i] for i in idx])
        den = (~np.isnan(S) * w[:, None]).sum(axis=0)
        return np.where(den > 0, np.nansum(S * w[:, None], axis=0) / np.maximum(den, 1e-9), np.nan)
    audit['pilot_agreement'] = {'spearman_V_vs_pilot_V': spearman(final['V'], pilot_V),
                                'spearman_D_vs_pilot_D': spearman(final['D'], pilot_D),
                                'independent_spearman_V_regional_layers_only': spearman(without_pilot('V'), pilot_V),
                                'independent_spearman_D_regional_layers_only': spearman(without_pilot('D'), pilot_D),
                                'pilot_cells': int((~np.isnan(pilot_V)).sum())}
    eligible = np.nan_to_num(final['V'], nan=-1) >= 10
    audit['eligible_cells'] = int(eligible.sum())
    audit['eligible_pct'] = round(100 * eligible.mean(), 1)
    audit['hits'] = {'mean_layers_per_cell': round(float(hit_layers.mean()), 1), 'max': int(hit_layers.max())}
    checks = {
        'coverage_ge_95': bool(all(audit['criteria'][c]['covered_pct'] >= 95 for c in KEYS)),
        'modal_share_le_60': bool(all(audit['criteria'][c]['modal_share_pct'] <= 60 for c in KEYS)),
        'eligible_ge_50': bool(audit['eligible_pct'] >= 50),
        'pilot_V_corr_gt_0_3': bool((audit['pilot_agreement']['spearman_V_vs_pilot_V'] or 0) > 0.3),
    }
    audit['acceptance'] = checks
    print(json.dumps(audit, ensure_ascii=False, indent=1))

    rc = read(DATA / 'regional_config.json')
    rc['core_threshold'] = cfg.get('core_threshold', 60)
    write(DATA / 'regional_config.json', rc)
    if do_complete:
        sys.path.insert(0, str(HERE))
        from complete_region import complete
        complete(DATA, runs, seconds, False)
    # patch readiness / summary texts
    readiness = read(DATA / 'readiness.json')
    readiness['blockers'] = {c: f"{CRITERION_NAMES[c]} : {audit['criteria'][c]['layers']} couches pondérées, "
                                f"{audit['criteria'][c]['covered_pct']} % des mailles couvertes." for c in KEYS}
    readiness['interpretation'] = ('Critères régionaux calculés à partir des couches de l’atlas (layer_scoring.json) ; '
                                   'pondérations expertes documentées, non calibrées sur des résultats de terrain.')
    readiness['scoring_audit'] = audit
    write(DATA / 'readiness.json', readiness)
    summary = read(DATA / 'summary.json')
    summary['regional_readiness'] = readiness
    summary['scoring_audit'] = audit
    summary['status'] = 'regional_multilayer'
    summary['limits'] = [x for x in summary.get('limits', []) if not x.startswith('P (pression')] + [
        'V, D, P et O sont des indices composites de couches réelles de l’atlas (docs/PLAN_REGIONAL_SCORING.md) : '
        'désignations et inventaires pour V, dégradations observées pour D, emprises humaines pour P, cadres d’action documentés pour O.',
        'Les couches partielles (extractions WFS tronquées) ne peuvent qu’augmenter un score ; leur absence n’est jamais un zéro.',
        'Pondérations expertes modifiables ; la sensibilité Monte-Carlo (±20 %) mesure l’incertitude de préférence, pas la qualité des données.']
    write(DATA / 'summary.json', summary)
    import hashlib
    write(DATA / 'manifest.json', {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                                   for p in DATA.glob('*') if p.is_file() and p.name != 'manifest.json'})
    sys.path.insert(0, str(HERE))
    from build_display import build as build_display  # light files for the explorer (skipped if unchanged)
    build_display()
    return audit


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=pathlib.Path, default=HERE / 'layer_scoring.json')
    ap.add_argument('--no-complete', action='store_true')
    ap.add_argument('--runs', type=int, default=300)
    ap.add_argument('--seconds', type=float, default=20)
    a = ap.parse_args()
    run(a.config, not a.no_complete, a.runs, a.seconds)
