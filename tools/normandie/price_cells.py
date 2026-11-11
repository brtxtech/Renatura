#!/usr/bin/env python3
"""Extension 2 · land price per 1 km² cell from DVF (2021-2025) + official farmland price scale.

Sources
- geo-DVF (Etalab), datasets/normandie_price/dvf/*.csv.gz: notarial sales, rural land only.
- Barème indicatif de la valeur vénale moyenne des terres agricoles 2024 (JORF 29/08/2025,
  terres labourables et prairies naturelles), parsed for the 5 Normandy departments.

Rules (privacy + robustness)
- Rural sale = every lot without building and with a rural land-use code; any building plot,
  garden, built land or building in the sale excludes it. Price = sale value / total land area.
- Categories: agricultural (terres, prés, vergers…), forest (bois, futaies, taillis…), all rural.
- Published statistic needs >= 5 sales (DVF reuse terms forbid re-identification): cell, else
  5 km, else 10 km neighbourhood, else department; the level used is always shown.
- No single sale is ever written to the output.

Writes dist/data/normandie/prices.json (+ .gz) and dist/data/normandie/buyer_cells.json (+ .gz).
"""
from __future__ import annotations

import gzip
import json
import math
import pathlib
import re

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / 'datasets/normandie_price'
DATA = ROOT / 'dist/data/normandie'
AGRI = {'T', 'TP', 'P', 'PA', 'PC', 'PH', 'PP', 'VE'}
FOREST = {'B', 'BF', 'BM', 'BO', 'BP', 'BR', 'BS', 'BT', 'LB'}
NATURAL = {'L', 'E'}
RURAL = AGRI | FOREST | NATURAL
MIN_N = 5
DEPT_NAMES = {'14': 'Calvados', '27': 'Eure', '50': 'Manche', '61': 'Orne', '76': 'Seine-Maritime'}


def parse_bareme():
    txt = (SRC / 'bareme_2024_jorf.txt').read_text(encoding='utf-8')
    rows, dept = [], None
    num = r'(\d{1,3}(?: \d{3})*)'
    for line in txt.splitlines():
        line = line.strip()
        m = re.match(r'^(?:(\d{2})-)?(Calvados|Eure|Manche|Orne|Seine-Maritime)$', line)
        if m:
            dept = {v: k for k, v in DEPT_NAMES.items()}[m.group(2)]
            continue
        if re.match(r'^\d{2}-\S', line) or re.match(r'^\d{2} [A-ZÉ]', line):
            dept = None  # another department / region heading
            continue
        m = re.match(rf'^(.+?)\s+{num}\s+{num}\s+{num}\s*$', line)
        if dept and m:
            v = [int(x.replace(' ', '')) for x in m.groups()[1:]]
            rows.append({'department': dept, 'small_region': m.group(1).strip(), 'dominant': v[0], 'min': v[1], 'max': v[2]})
    # keep the first occurrence per (department, region): the arable/pasture table comes first
    seen, out = set(), []
    for r in rows:
        k = (r['department'], r['small_region'])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def load_sales():
    frames = [pd.read_csv(p, dtype=str, low_memory=False) for p in sorted((SRC / 'dvf').glob('*.csv.gz'))]
    d = pd.concat(frames, ignore_index=True)
    d = d[d['nature_mutation'] == 'Vente']
    d['surface_terrain'] = pd.to_numeric(d['surface_terrain'], errors='coerce')
    d['valeur_fonciere'] = pd.to_numeric(d['valeur_fonciere'], errors='coerce')
    d['lon'] = pd.to_numeric(d['longitude'], errors='coerce')
    d['lat'] = pd.to_numeric(d['latitude'], errors='coerce')
    d = d.drop_duplicates(['id_mutation', 'id_parcelle', 'code_nature_culture', 'surface_terrain', 'type_local'])
    g = d.groupby('id_mutation')
    built = g['type_local'].apply(lambda s: s.notna().any())
    codes = g['code_nature_culture'].apply(lambda s: set(s.dropna()))
    rural = codes.apply(lambda c: bool(c) and c <= RURAL) & ~built
    keep = rural[rural].index
    r = d[d['id_mutation'].isin(keep)]
    agg = r.groupby('id_mutation').agg(value=('valeur_fonciere', 'first'), area_m2=('surface_terrain', 'sum'),
                                        lon=('lon', 'mean'), lat=('lat', 'mean'), date=('date_mutation', 'first'),
                                        dept=('code_departement', 'first'), commune=('code_commune', 'first'))
    share = r.assign(cat=r['code_nature_culture'].map(lambda c: 'agri' if c in AGRI else 'forest' if c in FOREST else 'natural'))
    share = share.groupby(['id_mutation', 'cat'])['surface_terrain'].sum().unstack(fill_value=0)
    share = share.div(share.sum(1), axis=0)
    agg['category'] = share.idxmax(1).where(share.max(1) >= 0.8, 'mixed')
    agg = agg.dropna(subset=['value', 'area_m2', 'lon', 'lat'])
    agg = agg[(agg['area_m2'] >= 2500) & (agg['value'] > 0)]
    agg['eur_ha'] = agg['value'] / (agg['area_m2'] / 1e4)
    agg = agg[(agg['eur_ha'] >= 300) & (agg['eur_ha'] <= 150000)]
    # trim 1 % tails per category
    out = []
    for cat, grp in agg.groupby('category'):
        lo, hi = grp['eur_ha'].quantile([0.01, 0.99])
        out.append(grp[(grp['eur_ha'] >= lo) & (grp['eur_ha'] <= hi)])
    return pd.concat(out)


def stats(values):
    v = np.asarray(values)
    return {'median': round(float(np.median(v))), 'p25': round(float(np.percentile(v, 25))),
            'p75': round(float(np.percentile(v, 75))), 'n': int(len(v))}


def main():
    bareme = parse_bareme()
    print(f'barème rows: {len(bareme)}')
    sales = load_sales()
    print(f'rural sales kept: {len(sales)}', sales['category'].value_counts().to_dict())

    plain, packed = DATA / 'cells.geojson', DATA / 'cells.geojson.gz'
    # use the gzip copy only if it is not older than the plain file (another build may rewrite only one of them)
    if packed.exists() and (not plain.exists() or packed.stat().st_mtime >= plain.stat().st_mtime):
        cells = json.load(gzip.open(packed))
    else:
        cells = json.loads(plain.read_text())
    feats = cells['features']
    geoms = np.array([shape(f['geometry']) for f in feats], dtype=object)
    ids = [f['properties']['id'] for f in feats]
    tree = shapely.STRtree(geoms)
    pts = shapely.points(sales['lon'].values, sales['lat'].values)
    si, ci = tree.query(pts, predicate='within')
    sales['cell'] = None
    sales.iloc[si, sales.columns.get_loc('cell')] = [ids[i] for i in ci]
    # metric coordinates for neighbourhoods (Lambert-93 not needed: equirectangular at 49°N is fine for 5-10 km)
    k = 111.32 * math.cos(math.radians(49.2))
    cx = np.array([g.centroid.x for g in geoms]) * k
    cy = np.array([g.centroid.y for g in geoms]) * 111.32
    sx, sy = sales['lon'].values * k, sales['lat'].values * 111.32
    from scipy.spatial import cKDTree
    stree = cKDTree(np.column_stack([sx, sy]))

    dept_stats = {}
    for (dept, cat), grp in sales.groupby(['dept', 'category']):
        if len(grp) >= MIN_N:
            dept_stats[(dept, cat)] = stats(grp['eur_ha'])
    for dept, grp in sales.groupby('dept'):
        dept_stats[(dept, 'rural')] = stats(grp['eur_ha'])
    bareme_dept = {}
    for dept in DEPT_NAMES:
        rows = [r for r in bareme if r['department'] == dept]
        if rows:
            bareme_dept[dept] = {'dominant_median_of_regions': int(np.median([r['dominant'] for r in rows])),
                                 'min': min(r['min'] for r in rows), 'max': max(r['max'] for r in rows), 'regions': len(rows)}

    cat_values = {c: sales[sales['category'] == c] for c in ('agri', 'forest')}
    cat_values['rural'] = sales
    cat_idx = {c: cKDTree(np.column_stack([v['lon'].values * k, v['lat'].values * 111.32])) if len(v) else None
               for c, v in cat_values.items()}
    by_cell = {c: v.groupby('cell')['eur_ha'].apply(list).to_dict() for c, v in cat_values.items()}
    out_cells, levels = {}, {}
    for i, (cid, f) in enumerate(zip(ids, feats)):
        dept = f['properties'].get('department')
        rec = {}
        for c in ('agri', 'forest', 'rural'):
            own = by_cell[c].get(cid, [])
            if len(own) >= MIN_N:
                rec[c] = {**stats(own), 'level': 'maille'}
            else:
                got = None
                for radius in (5, 10):
                    if cat_idx[c] is None:
                        break
                    near = cat_idx[c].query_ball_point([cx[i], cy[i]], radius)
                    if len(near) >= MIN_N:
                        got = {**stats(cat_values[c]['eur_ha'].values[near]), 'level': f'voisinage {radius} km'}
                        break
                if got is None and dept and (dept, c) in dept_stats:
                    got = {**dept_stats[(dept, c)], 'level': f'département {dept}'}
                if got:
                    rec[c] = got
            if c in rec:
                levels[rec[c]['level'].split(' ')[0]] = levels.get(rec[c]['level'].split(' ')[0], 0) + 1
        rec['sales_in_cell'] = len(by_cell['rural'].get(cid, [])) if len(by_cell['rural'].get(cid, [])) >= MIN_N else f'<{MIN_N}'
        out_cells[cid] = rec

    meta = {
        'sources': ['geo-DVF Etalab 2021-2025 (ventes, terrains ruraux non bâtis)',
                    'Barème indicatif de la valeur vénale moyenne des terres agricoles 2024, JORF du 29/08/2025 (terres labourables et prairies naturelles)'],
        'rules': [f'Statistique publiée seulement si au moins {MIN_N} ventes (conditions de réutilisation DVF : pas de ré-identification).',
                  'Ventes rurales : tous les lots sans bâti et en nature rurale ; prix = valeur foncière / surface totale ; ventes < 0,25 ha et 1 % extrêmes exclus.',
                  'Niveau : maille, sinon voisinage 5 km, 10 km, sinon département ; prix indicatif, pas une estimation.'],
        'period': '2021-2025', 'rural_sales': int(len(sales)),
        'sales_by_category': {k: int(v) for k, v in sales['category'].value_counts().items()},
        'levels_used': levels,
        'department_dvf': {f'{d}|{c}': v for (d, c), v in dept_stats.items()},
        'bareme_2024': bareme, 'bareme_by_department': bareme_dept,
    }
    prices = {'meta': meta, 'cells': out_cells}
    write(DATA / 'prices.json', prices)

    # slim buyer dataset: what the buyer card needs, without the 84 MB cells file
    rp_w = (0.30, 0.30, 0.15, 0.25)
    corridor_cells = set()
    conn = json.loads((DATA / 'connectivity.json').read_text()) if (DATA / 'connectivity.json').exists() else {}
    for p_ in conn.get('paths', []):
        corridor_cells.update(p_.get('sites', []))
    flags = {'api_aea532ddcc6843c3': 'Natura 2000 ZSC', 'api_f30d120eeb7cbfc8': 'Natura 2000 ZPS',
             'api_f0dd68b11880e69a': 'ZNIEFF 1', 'api_40a2cf3f12eb594f': 'ZNIEFF 2', 'api_7947ac47fe6e663a': 'APB',
             'api_c843ac03b50af0c3': 'Réserve naturelle nationale', 'api_1dfe3e087c5226bc': 'Réserve naturelle régionale',
             'api_af32743665728b50': 'Parc naturel régional', 'api_672b19d8503f7be6': 'Secteur potentiel de restauration (SPRB)',
             'api_c99b206e0d1207f6': 'ORE existante', 'api_b24ca6c5fe3ce85d': 'Zone vulnérable nitrates'}
    buyer = []
    for f, g in zip(feats, geoms):
        p = f['properties']
        crit = [p.get(c) for c in 'VDPO']
        rp = sum(w * v for w, v in zip(rp_w, crit)) if all(v is not None for v in crit) else None
        ev_ids = {e['sourceId'] for c in 'VDPO' for e in (p.get('evidence') or {}).get(c, [])}
        price = out_cells[p['id']]
        agri = (price.get('agri') or price.get('rural') or {}).get('median')
        c = g.centroid
        buyer.append({'id': p['id'], 'lon': round(c.x, 5), 'lat': round(c.y, 5), 'commune': p.get('commune'),
                      'department': p.get('department'), 'area_ha': round(p.get('area_ha') or 0, 2),
                      'V': p.get('V'), 'D': p.get('D'), 'P': p.get('P'), 'O': p.get('O'),
                      'rp': None if rp is None else round(rp, 1), 'corridor': p['id'] in corridor_cells,
                      'designations': sorted(v for k_, v in flags.items() if k_ in ev_ids),
                      'price': price,
                      # benefit per euro: restoration priority points per 10 000 € of land (indicative)
                      'rp_per_10k_eur': None if (rp is None or not agri) else round(rp / agri * 1e4, 2)})
    write(DATA / 'buyer_cells.json', {'meta': {'weights': rp_w, 'note': 'RP = 0,30 V + 0,30 D + 0,15 P + 0,25 O (pondérations par défaut de l’explorateur).',
                                               **{k_: meta[k_] for k_ in ('sources', 'rules', 'period')}}, 'cells': buyer})
    print(json.dumps({'levels_used': levels, 'bareme_by_department': bareme_dept}, ensure_ascii=False, indent=1))


def write(path, value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    path.write_text(text, encoding='utf-8')
    with gzip.open(str(path) + '.gz', 'wt', encoding='utf-8', compresslevel=9) as f:
        f.write(text)
    print(f'wrote {path.name} ({len(text) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
