"""Assistant tools on the whole regional atlas, land prices / benefit per euro and the climate summary.

  dist/data/atlas/catalog-v2.json       194 thematic layers (themes, groups, variants -> source ids)
  dist/data/atlas/catalog.json          source registry (chunks, bounds, counts, status)
  dist/data/atlas/zones/<id>.json       objects per source in each 5 x 5 km square (Lambert-93 lower-left corner)
  dist/data/normandie/buyer_cells.json  DVF price per cell, RP and RP per 10 000 EUR
  dist/data/normandie/climate.json      ERA5 trends and anomalies, NDVI (when collected)
"""
from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache

import numpy as np

from . import tools
from .tools import ROOT, DATA, _norm, _num

ATLAS = ROOT / 'dist/data/atlas'
NAME_KEYS = ['nom_site', 'nom', 'name', 'libelle', 'nom_officiel', 'appellation', 'toponyme', 'nom_reserve', 'nom_zone',
             'lib', 'label', 'titre']


# ---------------------------------------------------------------- atlas catalogue

@lru_cache(maxsize=1)
def _catalog():
    tree = json.load(open(ATLAS / 'catalog-v2.json'))
    reg = {l['id']: l for l in json.load(open(ATLAS / 'catalog.json'))['layers']}
    layers, by_source = [], {}
    for t in tree['themes']:
        for g in t['groups']:
            for l in g['layers']:
                variants = []
                for v in l['variants']:
                    srcs = [s for s in v['source_ids'] if s in reg]
                    variants.append({'dimensions': v.get('dimensions') or {}, 'source_ids': srcs})
                    for s in srcs:
                        by_source.setdefault(s, (t['display_name'], g['display_name'], l['display_name']))
                ids = [s for v in variants for s in v['source_ids']]
                layers.append({'theme': t['display_name'], 'groupe': g['display_name'], 'couche': l['display_name'],
                               'variants': variants, 'objets': sum(int(reg[s].get('map_count') or 0) for s in set(ids)),
                               'partiel': any(reg[s].get('status') == 'PARTIAL' for s in ids)})
    return layers, by_source, reg


def _match_layers(query, theme=None):
    layers, _, _ = _catalog()
    q, th = _norm(query or ''), _norm(theme or '')
    words = [w for w in q.replace('-', ' ').split() if len(w) > 2]
    out = []
    for l in layers:
        if th and th not in _norm(l['theme']):
            continue
        text = _norm(' '.join([l['theme'], l['groupe'], l['couche']]))
        if not q or q in text or (words and all(w in text for w in words)):
            out.append(l)
    if not out and words:  # loose: any word
        out = [l for l in layers if any(w in _norm(l['theme'] + ' ' + l['groupe'] + ' ' + l['couche']) for w in words)
               and (not th or th in _norm(l['theme']))]
    return out


def atlas_layers(store, recherche=None, theme=None):
    """Thematic layers of the regional atlas (all 194), filtered by words or theme."""
    layers, _, _ = _catalog()
    hits = _match_layers(recherche, theme)
    themes = {}
    for l in layers:
        themes[l['theme']] = themes.get(l['theme'], 0) + 1
    return {'themes_et_nombre_de_couches': themes,
            'couches': [{'theme': l['theme'], 'groupe': l['groupe'], 'couche': l['couche'], 'objets_en_normandie': l['objets'],
                         'collecte': 'partielle (PARTIAL)' if l['partiel'] else 'complète',
                         'variantes': [' · '.join(str(x) for x in v['dimensions'].values()) for v in l['variants'] if v['dimensions']][:8]}
                        for l in hits[:40]],
            'nombre_de_couches_trouvees': len(hits),
            'note': "Utiliser atlas_zone pour savoir quelles couches touchent un lieu, atlas_objects pour nommer les objets."}


# ---------------------------------------------------------------- places -> 5 km squares

def _place_cells(store, cell_id=None, lon=None, lat=None, commune=None):
    if commune and not cell_id and lon is None:
        j = store.commune(commune)
        if j is None:
            return None, None
        return store.by_commune.get(j, []), f"commune de {store.communes[j]['name']}"
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return None, None
    return [store.index[cid]], f'maille {cid}'


def _zone_id(x, y):
    return f'N{int(x // 5000 * 5000)}_{int(y // 5000 * 5000)}'


@lru_cache(maxsize=256)
def _zone(zid):
    try:
        return json.load(open(ATLAS / 'zones' / f'{zid}.json'))
    except (OSError, ValueError):
        return None


def atlas_zone(store, cell_id=None, lon=None, lat=None, commune=None, recherche=None, theme=None):
    """Which atlas layers have objects in the 5 x 5 km square(s) of a place, by theme."""
    idx, label = _place_cells(store, cell_id, lon, lat, commune)
    if not idx:
        return {'erreur': 'lieu introuvable : commune inconnue, cell_id inconnu ou point hors de la grille'}
    _, by_source, reg = _catalog()
    zids = sorted({_zone_id(store.x[i], store.y[i]) for i in idx})
    counts = {}
    for z in zids:
        for e in (_zone(z) or {}).get('layers', []):
            counts[e['id']] = counts.get(e['id'], 0) + int(e.get('count') or 0)
    wanted = None
    if recherche or theme:
        wanted = {(l['theme'], l['groupe'], l['couche']) for l in _match_layers(recherche, theme)}
    out = {}
    for sid, n in counts.items():
        key = by_source.get(sid)
        if key is None or (wanted is not None and key not in wanted):
            continue
        th, _, name = key
        row = out.setdefault(th, {})
        row[name] = row.get(name, 0) + n
    return {'lieu': label, 'carres_5km': zids[:12], 'nombre_de_carres': len(zids),
            'couches_presentes_par_theme': {th: dict(sorted(v.items(), key=lambda kv: -kv[1])) for th, v in sorted(out.items())},
            'filtre': recherche or theme or 'aucun',
            'lecture': ("Nombre d'objets de chaque couche dans les carrés de 5 × 5 km qui contiennent le lieu "
                        "(comptes par source, non dédupliqués). Absence de couche ≠ preuve d'absence sur le terrain ; "
                        "une couche partielle (PARTIAL) peut manquer des objets.")}


# ---------------------------------------------------------------- objects of one layer near a place

def _feature_name(p):
    attrs = [(k, v) for k, v in p.items() if not str(k).startswith('_') and v is not None and str(v).strip()]
    bare = lambda k: str(k).split('}')[-1].lower()
    for key in NAME_KEYS:
        hit = next((v for k, v in attrs if bare(k) == key), None)
        if hit is not None:
            return str(hit)
    loose = next((v for k, v in attrs if bare(k)[:3] in ('nom', 'nam', 'lib') and isinstance(v, str)), None)
    return loose


@lru_cache(maxsize=48)
def _chunk(path):
    p = ATLAS / path
    try:
        if path.endswith('.gz'):
            return json.load(gzip.open(p, 'rt'))
        return json.load(open(p))
    except (OSError, ValueError):
        return None


def atlas_objects(store, couche, cell_id=None, lon=None, lat=None, commune=None, rayon_km=2, n=15):
    """Named objects of one atlas layer within a radius of a place (e.g. which ZNIEFF, which wind farms)."""
    hits = _match_layers(couche)
    if not hits:
        return {'erreur': f"aucune couche de l'atlas ne correspond à « {couche} » (voir atlas_layers)"}
    layer = hits[0]
    idx, label = _place_cells(store, cell_id, lon, lat, commune)
    if not idx:
        return {'erreur': 'lieu introuvable'}
    r = max(0.0, min(float(rayon_km or 2), 25.0))
    lons, lats = [store.lon[i] for i in idx], [store.lat[i] for i in idx]
    lat0 = float(np.mean(lats))
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57    # degrees -> km (local, enough for a few km)
    pts = [(lo * kx, la * ky) for lo, la in zip(lons, lats)]
    dlon, dlat = r / kx + 0.01, r / ky + 0.01
    box = (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)
    _, _, reg = _catalog()
    found, scanned = [], 0
    for v in layer['variants']:
        for sid in v['source_ids']:
            meta = reg[sid]
            bounds = meta.get('chunk_bounds') or {}
            for ch in meta.get('chunks') or []:
                b = bounds.get(ch)
                if b and (b[0] > box[2] or b[2] < box[0] or b[1] > box[3] or b[3] < box[1]):
                    continue
                if ch.startswith('browser:') or scanned >= 40:
                    continue
                scanned += 1
                fc = _chunk(ch)
                for f in (fc or {}).get('features', []):
                    parts = _geom_parts(f.get('geometry'))
                    if not parts:
                        continue
                    xs = [c[0] for kind, rings in parts for ring in rings for c in ring]
                    ys = [c[1] for kind, rings in parts for ring in rings for c in ring]
                    if min(xs) > box[2] or max(xs) < box[0] or min(ys) > box[3] or max(ys) < box[1]:
                        continue
                    sample = pts if len(pts) < 60 else pts[::max(1, len(pts) // 60)]
                    d = min(_distance(parts, p, kx, ky) for p in sample)
                    if d <= r:
                        p = f.get('properties') or {}
                        attrs = {str(k).split('}')[-1]: v2 for k, v2 in p.items()
                                 if not str(k).startswith('_') and v2 is not None and str(v2).strip() and len(str(v2)) < 80}
                        found.append({'nom': _feature_name(p) or 'objet sans nom', 'distance_km': round(d, 2),
                                      'variante': ' · '.join(str(x) for x in v['dimensions'].values()) or None,
                                      'attributs': dict(list(attrs.items())[:6])})
    found.sort(key=lambda o: o['distance_km'])
    seen, uniq = set(), []
    for o in found:
        k = (o['nom'], o['variante'])
        if k not in seen or o['nom'] == 'objet sans nom':
            seen.add(k)
            uniq.append(o)
    return {'couche': layer['couche'], 'theme': layer['theme'], 'groupe': layer['groupe'], 'lieu': label, 'rayon_km': r,
            'objets_trouves': len(uniq), 'objets': uniq[:max(1, min(int(n or 15), 40))],
            'autres_couches_correspondantes': [l['couche'] for l in hits[1:6]],
            'collecte': 'partielle (PARTIAL) : des objets peuvent manquer' if layer['partiel'] else 'complète',
            'lecture': 'distance_km = 0 : le lieu est dans l’objet. Géométries simplifiées pour l’affichage (≈ 30 m).'}


def _geom_parts(g):
    """GeoJSON geometry -> [(kind, [ring/line coords...])], kind in point|line|polygon (no dependency)."""
    if not g:
        return []
    t, c = g.get('type'), g.get('coordinates')
    if t == 'Point':
        return [('point', [[c]])]
    if t == 'MultiPoint':
        return [('point', [[p]]) for p in c]
    if t == 'LineString':
        return [('line', [c])]
    if t == 'MultiLineString':
        return [('line', [l]) for l in c]
    if t == 'Polygon':
        return [('polygon', c)]
    if t == 'MultiPolygon':
        return [('polygon', p) for p in c]
    if t == 'GeometryCollection':
        return [x for gg in g.get('geometries', []) for x in _geom_parts(gg)]
    return []


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _inside(px, py, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _distance(parts, p, kx, ky):
    """Distance in km from a point (already in km) to a geometry in lon/lat (local equirectangular scaling)."""
    px, py, best = p[0], p[1], float('inf')
    for kind, rings in parts:
        rings_km = [[(c[0] * kx, c[1] * ky) for c in ring] for ring in rings]
        if kind == 'point':
            best = min(best, math.hypot(px - rings_km[0][0][0], py - rings_km[0][0][1]))
            continue
        if kind == 'polygon' and rings_km and _inside(px, py, rings_km[0]) and not any(_inside(px, py, h) for h in rings_km[1:]):
            return 0.0
        for ring in rings_km:
            for a, b in zip(ring, ring[1:]):
                best = min(best, _seg_dist(px, py, a[0], a[1], b[0], b[1]))
    return best


# ---------------------------------------------------------------- land price and benefit per euro

@lru_cache(maxsize=1)
def _buyer():
    try:
        b = json.load(open(DATA / 'buyer_cells.json'))
    except (OSError, ValueError):
        return None
    cells = {c['id']: c for c in b['cells']}
    vals = np.array(sorted(c['rp_per_10k_eur'] for c in b['cells'] if c.get('rp_per_10k_eur') is not None))
    return b['meta'], cells, vals


def _price_card(c, vals):
    rank = None
    if c.get('rp_per_10k_eur') is not None and len(vals):
        rank = round(100 * np.searchsorted(vals, c['rp_per_10k_eur'], side='right') / len(vals), 1)
    pr = c.get('price') or {}
    fmt = lambda p: ({'mediane_eur_ha': p.get('median'), 'p25_eur_ha': p.get('p25'), 'p75_eur_ha': p.get('p75'),
                      'nombre_de_ventes': p.get('n'), 'niveau': p.get('level')} if p else 'donnée absente')
    return {'cell_id': c['id'], 'commune': c.get('commune'), 'surface_ha': c.get('area_ha'), 'RP': c.get('rp'),
            'prix_terres_agricoles': fmt(pr.get('agri')), 'prix_forets': fmt(pr.get('forest')),
            'prix_terrains_ruraux': fmt(pr.get('rural')), 'ventes_dans_la_maille': pr.get('sales_in_cell'),
            'points_de_RP_gagnes_pour_10000_eur_depenses': c.get('rp_per_10k_eur') if c.get('rp_per_10k_eur') is not None else 'donnée absente',
            'rang_regional_benefice_par_euro_0_100': rank, 'zonages': c.get('designations') or [],
            'corridor_ecologique': c.get('corridor')}


def price_benefit(store, cell_id=None, lon=None, lat=None, commune=None, departement=None, top=5):
    """Land price (DVF 2021-2025, EUR/ha) and restoration benefit per euro (RP per 10 000 EUR) for a place."""
    b = _buyer()
    if b is None:
        return {'erreur': 'prix non calculés (buyer_cells.json absent)'}
    meta, cells, vals = b
    base = {'periode_des_ventes': meta.get('period'), 'sources': meta.get('sources'), 'regles': meta.get('rules'),
            'lecture_benefice': ("Le bénéfice par euro est un nombre de POINTS de priorité de restauration (RP, 0-100) par "
                                 "tranche de 10 000 € de prix de terre agricole à l'hectare : RP / prix médian agricole (€/ha) × 10 000. "
                                 "Ce n'est PAS une somme en euros, ni le prix de la maille ; il sert à comparer les mailles entre elles.")}
    if commune or departement:
        if departement:
            d = str(departement).zfill(2)
            pool = [c for c in cells.values() if str(c.get('department')) == d]
            label = f'département {d}'
        else:
            j = store.commune(commune)
            if j is None:
                return {'erreur': 'commune inconnue'}
            pool = [cells[store.ids[i]] for i in store.by_commune.get(j, []) if store.ids[i] in cells]
            label = f"commune de {store.communes[j]['name']}"
        if not pool:
            return {**base, 'lieu': label, 'erreur': 'aucune maille avec prix'}
        base = {k: v for k, v in base.items() if k not in ('sources', 'regles')}
        base['source'] = 'DVF 2021-2025, ventes de terrains ruraux non bâtis (au moins 5 ventes par statistique)'
        med = lambda key: _num(np.median([c['price'][key]['median'] for c in pool if (c.get('price') or {}).get(key)]), 0) \
            if any((c.get('price') or {}).get(key) for c in pool) else 'donnée absente'
        best = sorted([c for c in pool if c.get('rp_per_10k_eur') is not None], key=lambda c: -c['rp_per_10k_eur'])
        return {**base, 'lieu': label, 'nombre_de_mailles_de_la_zone': len(pool),
                'prix_median_des_mailles_eur_ha': {'terres_agricoles': med('agri'), 'forets': med('forest'), 'terrains_ruraux': med('rural')},
                'points_de_RP_pour_10000_eur_median': _num(np.median([c['rp_per_10k_eur'] for c in best]), 1) if best else 'donnée absente',
                'meilleures_mailles_points_RP_pour_10000_eur': [
                    {'cell_id': c['id'], 'priorite_de_restauration_RP': c.get('rp'),
                     'points_de_RP_pour_10000_eur': c.get('rp_per_10k_eur'),
                     'prix_median_terres_agricoles_eur_ha': ((c.get('price') or {}).get('agri') or {}).get('median', 'donnée absente'),
                     'zonages': c.get('designations') or []}
                    for c in best[:max(1, min(int(top or 5), 10))]],
                'RP': 'Priorité de restauration (0-100), pas une « réputation »'}
    cid = store.resolve(cell_id, lon, lat, None)
    if cid is None or cid not in cells:
        return {**base, 'erreur': 'maille introuvable ou sans prix'}
    return {**base, **_price_card(cells[cid], vals)}


# ---------------------------------------------------------------- climate summary (all indicators at once)

def climate_summary(store, cell_id=None, lon=None, lat=None, commune=None):
    """Observed climate trends per decade, recent anomaly and NDVI for the climate point nearest a place."""
    clim = tools._climate()
    if clim is None:
        return {'erreur': 'climat non calculé (climate.json.gz absent)'}
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return {'erreur': 'lieu introuvable'}
    i = store.index[cid]
    lo, la = store.lon[i], store.lat[i]
    p = min(clim['points'], key=lambda q: (q['lon'] - lo) ** 2 + ((q['lat'] - la) * 1.5) ** 2)
    d = math.hypot((p['lon'] - lo) * 73, (p['lat'] - la) * 111)
    names = dict(tools.CLIMATE_VARS, ndvi_summer=("NDVI d'été (verdure)", ''))
    trends = {names.get(k, (k, ''))[0] + (f" ({names[k][1]})" if names.get(k, ('', ''))[1] else ''):
              {'pente_par_decennie': t.get('slope_per_decade'), 'p_value': t.get('p_value'),
               'significative': t.get('significant'), 'annees': t.get('n_years')}
              for k, t in (p.get('trends') or {}).items()}
    anom = {names.get(k, (k, ''))[0]: v for k, v in (p.get('anomaly_2016_2025_vs_1991_2020') or {}).items()}
    built = (clim.get('cells') or {}).get(cid, {})
    return {'maille': cid, 'point_climatique': f"{p['id']} à {d:.0f} km (ERA5, maille ~25-30 km)",
            'tendances_observees': trends, 'ecart_2016_2025_vs_1991_2020': anom,
            'ndvi': p.get('ndvi') or 'donnée absente (NDVI MODIS non collecté pour ce point)',
            'part_batie_maille_pct': {y: _num(100 * built[k], 1) if built.get(k) is not None else 'donnée absente'
                                      for y, k in (('2006', 'built_2006'), ('2017', 'built_2017'), ('2025', 'built_2025'))},
            'methode': (clim.get('meta') or {}).get('trend_method'),
            'limites': (clim.get('meta') or {}).get('caveats'),
            'lecture': 'Tendance observée, pas une projection climatique ; pour prolonger un indicateur, utiliser trend_projection.',
            **({'avertissement': (f"Point climatique à {d:.0f} km : la collecte ERA5 ne couvre que {len(clim['points'])} points "
                                  "(ouest de la Normandie). Ces tendances ne représentent pas bien ce lieu ; le dire explicitement.")}
               if d > 40 else {})}


# ---------------------------------------------------------------- registration

_loc = tools._loc
tools.TOOLS += [
    {'type': 'function', 'function': {'name': 'atlas_layers',
        'description': "Liste des 194 couches de l'Atlas régional (biodiversité, eau, occupation du sol, paysages et patrimoine, "
                       "littoral, énergie et climat (éolien, PCAET, méthaniseurs, photovoltaïque, hydroélectricité, géothermie), "
                       "risques, carrières, mobilité, réglementation). Filtrer par mots ou thème.",
        'parameters': {'type': 'object', 'properties': {'recherche': {'type': 'string'}, 'theme': {'type': 'string'}}}}},
    {'type': 'function', 'function': {'name': 'atlas_zone',
        'description': "Couches de l'Atlas régional présentes autour d'un lieu (carrés de 5 × 5 km) avec le nombre d'objets, "
                       "regroupées par thème. Filtre facultatif par mots (« éolien », « eau », « patrimoine »…) ou thème.",
        'parameters': {'type': 'object', 'properties': {**_loc, 'recherche': {'type': 'string'}, 'theme': {'type': 'string'}}}}},
    {'type': 'function', 'function': {'name': 'atlas_objects',
        'description': "Objets nommés d'une couche de l'Atlas près d'un lieu, avec leur distance (quelle ZNIEFF, quel parc éolien, "
                       "quel méthaniseur, quelle masse d'eau…). couche = nom ou mots de la couche.",
        'parameters': {'type': 'object', 'properties': {'couche': {'type': 'string'}, **_loc,
                                                        'rayon_km': {'type': 'number'}, 'n': {'type': 'integer'}},
                       'required': ['couche']}}},
    {'type': 'function', 'function': {'name': 'price_benefit',
        'description': "Prix des terrains (DVF 2021-2025, €/ha : médiane, quartiles, nombre de ventes) et bénéfice de restauration "
                       "par euro (RP gagné pour 10 000 €) d'une maille, d'une commune ou d'un département, avec les meilleures mailles.",
        'parameters': {'type': 'object', 'properties': {**_loc, 'departement': {'type': 'string'}, 'top': {'type': 'integer'}}}}},
    {'type': 'function', 'function': {'name': 'climate_summary',
        'description': "Toutes les tendances climatiques observées d'un lieu (température, jours chauds, gel, pluie, pluie d'été, "
                       "jours secs, plus longue période sèche, NDVI), écart 2016-2025 vs 1991-2020, et part bâtie 2006/2017/2025.",
        'parameters': {'type': 'object', 'properties': {**_loc}}}},
]
tools.FUNCS.update(atlas_layers=atlas_layers, atlas_zone=atlas_zone, atlas_objects=atlas_objects,
                   price_benefit=price_benefit, climate_summary=climate_summary)
