"""Renatura assistant · data store and tools on the real regional data.

Adapted from the assistant.py prototype: same rules (numbers only from tools, "donnée absente" never 0,
PARTIAL flagged), but the store reads what the project already builds instead of values.parquet:

  dist/data/normandie/cells_points.json.gz   id, lon/lat, Lambert-93 centre, area, V D P O, commune index
  dist/data/normandie/cells_detail/<col>.json per-cell evidence: layer, measured value, regional percentile, year
  dist/data/normandie/layer_scoring.json     layer -> criterion weights (the definition of V, D, P, O)
  dist/data/normandie/forest_cells.json      BD Forêt V2 share per cell (optional)
"""
from __future__ import annotations

import gzip
import json
import math
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'dist/data/normandie'
TO_L93 = Transformer.from_crs(4326, 2154, always_xy=True).transform
KEYS = ['V', 'D', 'P', 'O']
RP_WEIGHTS = {'V': 0.30, 'D': 0.30, 'P': 0.15, 'O': 0.25}
NAMES = {'V': 'Valeur écologique', 'D': 'Dégradation à réparer', 'P': 'Pression humaine',
         'O': "Opportunité d'action", 'RP': 'Priorité de restauration'}
METHODS = {
    'V': "Moyenne pondérée des rangs percentiles régionaux des couches de valeur écologique (zonages "
         "d'inventaire et de protection, trames vertes et bleues, naturalité, milieux humides), puis "
         "rang percentile régional du composite.",
    'D': "Moyenne pondérée des rangs des couches de dégradation (croissance du bâti, cours d'eau dégradés, "
         "nitrates, changements d'occupation du sol, obstacles à l'écoulement), puis rang régional.",
    'P': "Moyenne pondérée des rangs des couches de présence humaine (bâti, routes, ICPE, arrêts de "
         "transport, voies ferrées, risques industriels et miniers), puis rang régional.",
    'O': "Moyenne pondérée des rangs des couches qui documentent un levier d'action (secteurs de "
         "restauration, ORE, actions prioritaires SRCE, corridors TVB, PNR), puis rang régional.",
    'RP': "RP = 0,30 V + 0,30 D + 0,15 P + 0,25 O, renormalisé sur les critères disponibles.",
}
COVERAGE = {'regional': 'toute la région', 'territorial': 'territoire limité (hors territoire = donnée absente)',
            'presence': 'collecte partielle (PARTIAL) : ne peut que relever un score'}


def _norm(s):
    return unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower().strip()


def _num(v, d=1):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), d)


class Store:
    def __init__(self):
        p = json.load(gzip.open(DATA / 'cells_points.json.gz', 'rt'))
        self.ids = p['id']
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        self.x, self.y = np.array(p['x'], float), np.array(p['y'], float)
        self.lon, self.lat = p['lon'], p['lat']
        self.area = np.array(p['area'], float)
        self.crit = {k: np.array([np.nan if v is None else v for v in p[k]], float) for k in KEYS}
        self.communes = p['communes']
        self.commune_of = p['commune']
        self.by_commune = {}
        for i, c in enumerate(self.commune_of):
            if c >= 0:
                self.by_commune.setdefault(c, []).append(i)
        self.commune_lookup = {_norm(c['name']): j for j, c in enumerate(self.communes)}
        scoring = json.load(open(DATA / 'layer_scoring.json'))
        self.layers = scoring['layers']
        try:
            self.forest = json.load(open(DATA / 'forest_cells.json'))['cells']
        except (OSError, ValueError, KeyError):
            self.forest = {}
        rp = self.rp_all()
        self.rp = rp
        feats = np.column_stack([np.nan_to_num(self.crit[k], nan=0) for k in KEYS]
                                + [[self.forest.get(c, {}).get('forest_pct', 0) for c in self.ids]])
        mu, sd = feats.mean(0), feats.std(0) + 1e-9
        z = (feats - mu) / sd
        self.emb = z / (np.linalg.norm(z, axis=1, keepdims=True) + 1e-9)

    # ---- helpers
    def rp_all(self):
        num = sum(RP_WEIGHTS[k] * np.nan_to_num(self.crit[k]) for k in KEYS)
        den = sum(RP_WEIGHTS[k] * ~np.isnan(self.crit[k]) for k in KEYS)
        with np.errstate(invalid='ignore', divide='ignore'):
            return np.where(den > 0, num / den, np.nan)

    @lru_cache(maxsize=64)
    def _chunk(self, col):
        try:
            return json.load(open(DATA / 'cells_detail' / f'{col}.json'))
        except OSError:
            return {}

    def detail(self, cid):
        return self._chunk(cid.split('_')[1]).get(cid, {})

    def commune(self, name):
        j = self.commune_lookup.get(_norm(name))
        if j is None:  # loose match: "caen" -> "Caen", "st lo" -> "Saint-Lô"
            n = _norm(name).replace('st ', 'saint-').replace(' ', '-')
            j = next((v for k, v in self.commune_lookup.items() if k == n or k.startswith(n)), None)
        return j

    def resolve(self, cell_id=None, lon=None, lat=None, commune=None):
        if cell_id:
            return cell_id if cell_id in self.index else None
        if lon is not None and lat is not None:
            x, y = TO_L93(float(lon), float(lat))
            d = np.hypot(self.x - x, self.y - y)
            i = int(d.argmin())
            return self.ids[i] if d[i] <= 700 else None  # hexagon circumradius ≈ 620 m
        if commune:
            j = self.commune(commune)
            if j is None:
                return None
            idx = self.by_commune.get(j, [])
            if not idx:
                return None
            return self.ids[min(idx, key=lambda i: -np.nan_to_num(self.rp[i], nan=-1))]
        return None

    def cell_card(self, i):
        cid = self.ids[i]
        c = self.commune_of[i]
        return {'cell_id': cid, 'commune': self.communes[c]['name'] if c >= 0 else 'donnée absente',
                'lon': self.lon[i], 'lat': self.lat[i], 'surface_ha': _num(self.area[i], 0),
                **{k: _num(self.crit[k][i]) if not np.isnan(self.crit[k][i]) else 'donnée absente' for k in KEYS},
                'RP': _num(self.rp[i]) if not np.isnan(self.rp[i]) else 'donnée absente'}

    @staticmethod
    def legend():
        return {k: NAMES[k] for k in [*KEYS, 'RP']}


# ---------------------------------------------------------------- tools

def get_cell_profile(store, cell_id=None, lon=None, lat=None, commune=None, top=3):
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return {'erreur': 'maille introuvable : point hors de la grille Renatura, cell_id inconnu ou commune inconnue'}
    i = store.index[cid]
    out = store.cell_card(i)
    if commune and not cell_id:
        out['note'] = 'Maille de plus forte priorité (RP) de la commune.'
    d = store.detail(cid)
    out['sources_par_critere'] = {
        k: [{'couche': e['metric'], 'valeur': e.get('value'), 'unite': e.get('unit'), 'annee': e.get('year'),
             'rang_regional_0_100': _num(e.get('score'))}
            for e in sorted(d.get('evidence', {}).get(k, []), key=lambda e: -(e.get('score') or 0))[:int(top)]]
        or 'aucune couche de ce critère ne touche la maille'
        for k in KEYS}
    f = store.forest.get(cid)
    out['noms_des_criteres'] = store.legend()
    out['foret_bd_foret_v2'] = ({k: v for k, v in f.items()} if f else
                                ('0 % de forêt cartographiée' if store.forest else 'donnée absente'))
    return out


def explain_index(store, index_id, cell_id=None, lon=None, lat=None, commune=None):
    k = str(index_id).upper()
    if k not in NAMES:
        return {'erreur': f'indice inconnu ; disponibles : {list(NAMES)}'}
    res = {'indice': k, 'nom': NAMES[k], 'methode': METHODS[k]}
    if k == 'RP':
        res['poids'] = RP_WEIGHTS
    else:
        layers = [l for l in store.layers if l['c'] == k]
        res['couches'] = [{'couche': l['label'], 'poids': l['w'], 'couverture': COVERAGE.get(l.get('coverage'), l.get('coverage'))}
                          for l in sorted(layers, key=lambda l: -l['w'])]
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is not None:
        i = store.index[cid]
        card = store.cell_card(i)
        res['maille'] = {'cell_id': cid, 'commune': card['commune'], 'valeur': card[k]}
        if k == 'RP':
            present = {c: w for c, w in RP_WEIGHTS.items() if not np.isnan(store.crit[c][i])}
            den = sum(present.values()) or 1
            res['maille']['contributions'] = [{'critere': c, 'valeur': _num(store.crit[c][i]), 'poids': w,
                                               'contribution': _num(w * store.crit[c][i] / den)}
                                              for c, w in present.items()]
        else:
            weights = {l['label']: l['w'] for l in store.layers if l['c'] == k}
            ev = store.detail(cid).get('evidence', {}).get(k, [])
            res['maille']['composants'] = [{'couche': e['metric'], 'poids': weights.get(e['metric']),
                                           'valeur_mesuree': e.get('value'), 'unite': e.get('unit'),
                                           'rang_regional_0_100': _num(e.get('score'))}
                                          for e in sorted(ev, key=lambda e: -(e.get('score') or 0))] \
                or "aucune couche de ce critère ne touche la maille : valeur basse par absence de signal"
    return res


def similar_cells(store, cell_id=None, lon=None, lat=None, commune=None, k=5):
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return {'erreur': 'maille introuvable'}
    i = store.index[cid]
    sims = store.emb @ store.emb[i]
    order = [j for j in np.argsort(-sims) if j != i][:max(1, min(int(k), 20))]
    return {'reference': store.cell_card(i), 'profil_compare': 'V, D, P, O et part de forêt (standardisés)',
            'similaires': [{**store.cell_card(j), 'similarite': round(float(sims[j]), 3)} for j in order]}


def commune_summary(store, commune, top=5):
    j = store.commune(commune)
    if j is None:
        return {'erreur': f'commune inconnue : {commune}'}
    idx = store.by_commune.get(j, [])
    if not idx:
        return {'erreur': 'aucune maille régionale dans cette commune'}
    a = store.area[idx]

    def wmean(v):
        v = v[idx]
        ok = ~np.isnan(v)
        return _num((v[ok] * a[ok]).sum() / a[ok].sum()) if ok.any() else 'donnée absente'
    forest = [store.forest.get(store.ids[i], {}).get('forest_pct', 0) * store.area[i] for i in idx]
    best = sorted(idx, key=lambda i: -np.nan_to_num(store.rp[i], nan=-1))[:int(top)]
    return {'commune': store.communes[j]['name'], 'insee': store.communes[j]['insee'], 'mailles': len(idx),
            'surface_ha': _num(a.sum(), 0), **{k: wmean(store.crit[k]) for k in KEYS}, 'RP': wmean(store.rp),
            'foret_pct': _num(sum(forest) / a.sum()) if store.forest else 'donnée absente',
            'mailles_prioritaires': [store.cell_card(i) for i in best], 'noms_des_criteres': store.legend(),
            'lecture': 'Moyennes pondérées par la surface des mailles de 1 km² dont le centre est dans la commune.'}


_loc = {'cell_id': {'type': 'string', 'description': 'identifiant de maille, ex. H1_485_6425'},
        'lon': {'type': 'number', 'description': 'longitude WGS84'},
        'lat': {'type': 'number', 'description': 'latitude WGS84'},
        'commune': {'type': 'string', 'description': 'nom de commune normande (prend sa maille la plus prioritaire)'}}
TOOLS = [
    {'type': 'function', 'function': {
        'name': 'get_cell_profile',
        'description': "Profil d'une maille de 1 km² : V, D, P, O, RP, couches qui expliquent chaque critère, part de forêt.",
        'parameters': {'type': 'object', 'properties': {**_loc}}}},
    {'type': 'function', 'function': {
        'name': 'explain_index',
        'description': "Explique le calcul d'un indice (V, D, P, O ou RP) et, si une maille est donnée, la contribution de chaque composant.",
        'parameters': {'type': 'object', 'properties': {'index_id': {'type': 'string', 'enum': ['V', 'D', 'P', 'O', 'RP']}, **_loc},
                       'required': ['index_id']}}},
    {'type': 'function', 'function': {
        'name': 'similar_cells',
        'description': 'Mailles au profil le plus proche (V, D, P, O, forêt) dans toute la Normandie.',
        'parameters': {'type': 'object', 'properties': {**_loc, 'k': {'type': 'integer'}}}}},
    {'type': 'function', 'function': {
        'name': 'commune_summary',
        'description': "Synthèse d'une commune : moyennes V, D, P, O, RP, part de forêt et mailles prioritaires.",
        'parameters': {'type': 'object', 'properties': {'commune': {'type': 'string'}}, 'required': ['commune']}}},
]
FUNCS = {'get_cell_profile': get_cell_profile, 'explain_index': explain_index,
         'similar_cells': similar_cells, 'commune_summary': commune_summary}


# ---------------------------------------------------------------- question 2 · relations between variables

VARIABLES = {
    'V': 'Valeur écologique (rang 0-100)', 'D': 'Dégradation à réparer (rang 0-100)',
    'P': 'Pression humaine (rang 0-100)', 'O': "Opportunité d'action (rang 0-100)",
    'RP': 'Priorité de restauration (0-100)', 'foret': 'Part de forêt BD Forêt V2 (%)',
    'bati_2025': 'Part bâtie 2025 (%)', 'croissance_bati_2006_2017': 'Croissance du bâti 2006→2017 (points, Basse-Normandie)',
}


def _climate():
    if not hasattr(_climate, 'data'):
        try:
            _climate.data = json.load(gzip.open(DATA / 'climate.json.gz', 'rt'))
        except (OSError, ValueError):
            _climate.data = None
    return _climate.data


def _dept(store, i):
    c = store.commune_of[i]
    return store.communes[c]['insee'][:2] if c >= 0 else None


def variable(store, name):
    """Value per cell (numpy array, NaN = donnée absente)."""
    if name in KEYS:
        return store.crit[name]
    if name == 'RP':
        return store.rp
    if name == 'foret':
        if not store.forest:
            return np.full(len(store.ids), np.nan)
        return np.array([store.forest.get(c, {}).get('forest_pct', 0.0) for c in store.ids])
    clim = _climate()
    if clim is None:
        return np.full(len(store.ids), np.nan)
    cells = clim['cells']
    if name == 'bati_2025':
        return np.array([100 * (cells.get(c, {}).get('built_2025') if cells.get(c, {}).get('built_2025') is not None else np.nan) for c in store.ids])
    if name == 'croissance_bati_2006_2017':
        bn = {'14', '50', '61'}  # the 2006 built layer only covers Basse-Normandie
        out = []
        for i, c in enumerate(store.ids):
            v = cells.get(c, {})
            ok = _dept(store, i) in bn and v.get('built_2006') is not None and v.get('built_2017') is not None
            out.append(100 * (v['built_2017'] - v['built_2006']) if ok else np.nan)
        return np.array(out)
    raise KeyError(name)


def zone_cells(store, commune=None, rayon_km=None, departement=None, cell_id=None, lon=None, lat=None):
    """Indices of the cells of a zone + its label. Default radius 10 km around a commune or a point."""
    if departement:
        d = str(departement).zfill(2)
        idx = [i for i in range(len(store.ids)) if _dept(store, i) == d]
        return idx, f'département {d}'
    if commune or cell_id or (lon is not None and lat is not None):
        if commune and not (cell_id or lon is not None):
            j = store.commune(commune)
            if j is None:
                return [], f'commune inconnue : {commune}'
            members = store.by_commune.get(j, [])
            if not members:
                return [], 'aucune maille dans cette commune'
            cx, cy = store.x[members].mean(), store.y[members].mean()
            label = store.communes[j]['name']
        else:
            cid = store.resolve(cell_id, lon, lat)
            if cid is None:
                return [], 'maille introuvable'
            i = store.index[cid]
            cx, cy, label = store.x[i], store.y[i], cid
        r = float(rayon_km or 10) * 1000
        idx = np.flatnonzero(np.hypot(store.x - cx, store.y - cy) <= r).tolist()
        return idx, f'{label} + {r / 1000:g} km'
    return list(range(len(store.ids))), 'Normandie'


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    # average ranks for ties
    for r, v in ((ra, a), (rb, b)):
        _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
        sums = np.bincount(inv, weights=r)
        r[:] = (sums / cnt)[inv]
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else float('nan')


def correlate(store, x, y, commune=None, rayon_km=None, departement=None, cell_id=None, lon=None, lat=None):
    if x not in VARIABLES or y not in VARIABLES:
        return {'erreur': f'variables disponibles : {VARIABLES}'}
    idx, label = zone_cells(store, commune, rayon_km, departement, cell_id, lon, lat)
    if not idx:
        return {'erreur': label}
    a, b = variable(store, x)[idx], variable(store, y)[idx]
    ok = ~np.isnan(a) & ~np.isnan(b)
    n = int(ok.sum())
    if n < 12:
        return {'zone': label, 'n_mailles_renseignees': n, 'erreur': 'trop peu de mailles renseignées pour les deux variables (12 minimum)'}
    rho = _spearman(a[ok], b[ok])
    # neighbouring cells are not independent: a crude effective sample size (÷ 4) keeps the test honest
    n_eff = max(3, n // 4)
    t = rho * math.sqrt((n_eff - 2) / max(1e-9, 1 - rho ** 2))
    p = math.erfc(abs(t) / math.sqrt(2))  # normal approximation
    strength = 'forte' if abs(rho) >= .6 else 'modérée' if abs(rho) >= .3 else 'faible' if abs(rho) >= .1 else 'quasi nulle'
    q = lambda v: [_num(np.nanpercentile(v[ok], k)) for k in (25, 50, 75)]
    return {'zone': label, 'x': VARIABLES[x], 'y': VARIABLES[y], 'n_mailles': len(idx), 'n_mailles_renseignees': n,
            'spearman_rho': round(rho, 3), 'intensite': strength, 'sens': 'positif' if rho > 0 else 'négatif',
            'p_value_approx': round(p, 4), 'significatif_5pct': p < 0.05,
            'quartiles_x': q(a), 'quartiles_y': q(b),
            'lecture': "Corrélation de rang : ces indicateurs varient ensemble dans la zone ; ce n'est pas une relation de cause. "
                       "Les mailles voisines se ressemblent (autocorrélation spatiale) : la p-value utilise un effectif réduit (n/4)."}


# ---------------------------------------------------------------- question 3 · trends if they continue

CLIMATE_VARS = {'tmean': ('Température moyenne annuelle', '°C'), 'rain_mm': ('Cumul annuel de pluie', 'mm'),
                'summer_rain_mm': ("Pluie d'été (juin-août)", 'mm'), 'hot_days': ('Jours chauds (> 25 °C)', 'jours'),
                'frost_days': ('Jours de gel', 'jours'), 'dry_days': ('Jours secs', 'jours'),
                'max_dry_spell': ('Plus longue période sèche', 'jours')}


def _sen_mk(years, values):
    """Sen slope (per year) and Mann-Kendall p-value (normal approximation, no tie correction)."""
    y, v = np.asarray(years, float), np.asarray(values, float)
    slopes = [(v[j] - v[i]) / (y[j] - y[i]) for i in range(len(v)) for j in range(i + 1, len(v)) if y[j] != y[i]]
    s = sum(np.sign(v[j] - v[i]) for i in range(len(v)) for j in range(i + 1, len(v)))
    n = len(v)
    var = n * (n - 1) * (2 * n + 5) / 18
    z = (s - np.sign(s)) / math.sqrt(var) if var > 0 else 0
    return float(np.median(slopes)), math.erfc(abs(z) / math.sqrt(2))


def trend_projection(store, indicateur='tmean', horizon=2050, cell_id=None, lon=None, lat=None, commune=None):
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return {'erreur': 'maille introuvable (donner une commune, une maille ou des coordonnées)'}
    i = store.index[cid]
    horizon = int(min(max(int(horizon), 2030), 2100))
    base = {'maille': store.cell_card(i), 'horizon': horizon,
            'avertissement': "Extrapolation linéaire « si la tendance observée se poursuit » : ce n'est pas une projection "
                             "climatique (scénarios DRIAS / TRACC) ni une prévision."}
    clim = _climate()
    if indicateur in ('bati', 'croissance_bati'):
        v = (clim or {}).get('cells', {}).get(cid, {})
        if _dept(store, i) not in {'14', '50', '61'} or v.get('built_2006') is None:
            return {**base, 'indicateur': 'Part bâtie', 'valeur': 'donnée absente',
                    'raison': "le bâti 2006 ne couvre que la Basse-Normandie (14, 50, 61) ; 2025 n'est pas comparable à 2006"}
        b06, b17 = 100 * v['built_2006'], 100 * v['built_2017']
        rate = (b17 - b06) / 11
        proj = min(100.0, max(0.0, b17 + rate * (horizon - 2017)))
        return {**base, 'indicateur': 'Part bâtie de la maille (%)', 'observe': {'2006': _num(b06, 2), '2017': _num(b17, 2)},
                'pente_points_par_an': _num(rate, 3), 'projection': _num(proj, 2), 'methode': 'pente 2006 → 2017 prolongée'}
    if indicateur not in CLIMATE_VARS:
        return {'erreur': f"indicateurs : {list(CLIMATE_VARS) + ['bati']}"}
    if clim is None:
        return {**base, 'erreur': 'données climatiques absentes'}
    # nearest ERA5 point actually downloaded; refuse when it is too far to describe this cell
    pts = clim['points']
    dist = [(math.hypot((p['lon'] - store.lon[i]) * 73, (p['lat'] - store.lat[i]) * 111), p) for p in pts]
    d, p = min(dist, key=lambda t: t[0])
    if d > 40:
        return {**base, 'indicateur': CLIMATE_VARS[indicateur][0], 'valeur': 'donnée absente',
                'raison': f'point climatique ERA5 le plus proche à {d:.0f} km (téléchargement incomplet : {len(pts)} points sur la région)'}
    series = sorted((int(y), r[indicateur]) for y, r in p['climate'].items() if r.get(indicateur) is not None)
    years, vals = zip(*series)
    slope, pval = _sen_mk(years, vals)
    recent = [v for y, v in series if y >= years[-1] - 9]
    level = float(np.mean(recent))
    mid = (years[-1] + years[-1] - 9) / 2
    name, unit = CLIMATE_VARS[indicateur]
    return {**base, 'indicateur': f'{name} ({unit})', 'point_climatique': f"{p['id']} à {d:.0f} km (ERA5, maille ~25-30 km)",
            'periode': f'{years[0]}-{years[-1]}', 'moyenne_10_dernieres_annees': _num(level, 2),
            'pente_par_decennie': _num(slope * 10, 3), 'mann_kendall_p': round(pval, 4),
            'tendance_significative': pval < 0.05,
            'projection': _num(level + slope * (horizon - mid), 2) if pval < 0.05 else 'pas de tendance significative à prolonger',
            'methode': 'pente de Sen + test de Mann-Kendall sur la série annuelle, prolongée depuis la moyenne des 10 dernières années'}


FORMULA = {
    'etapes': [
        "1. Pour chaque couche : valeur brute par maille (part de surface, m/ha ou objets/km² selon le type).",
        "2. Rang percentile régional par couche (rang moyen des ex æquo) ; une absence réelle reste 0.",
        "3. Couverture : couche régionale -> absence = 0 ; territoriale -> hors territoire = donnée absente ; "
        "partielle (PARTIAL) -> ne peut que relever le score.",
        "4. Critère = moyenne pondérée des rangs des couches présentes (poids de layer_scoring.json), "
        "si les couches renseignées portent au moins {min_cov} % du poids ; sinon donnée absente.",
        "5. Le composite du critère est converti en rang percentile régional (0-100).",
        "6. RP = (0,30 V + 0,30 D + 0,15 P + 0,25 O) / somme des poids des critères disponibles.",
    ],
    'source': 'tools/normandie/multilayer_score.py et dist/data/normandie/layer_scoring.json',
}


def _explain_with_formula(store, index_id, **kw):
    res = explain_index(store, index_id, **kw)
    if 'erreur' not in res:
        cov = int(100 * float(json.load(open(DATA / 'layer_scoring.json')).get('min_weight_coverage', 0.3)))
        res['formule'] = {**FORMULA, 'etapes': [e.format(min_cov=cov) for e in FORMULA['etapes']]}
    return res


TOOLS += [
    {'type': 'function', 'function': {
        'name': 'correlate',
        'description': "Relation entre deux variables sur une zone (corrélation de Spearman) : commune + rayon, département ou Normandie.",
        'parameters': {'type': 'object', 'properties': {
            'x': {'type': 'string', 'enum': list(VARIABLES)}, 'y': {'type': 'string', 'enum': list(VARIABLES)},
            'commune': {'type': 'string'}, 'rayon_km': {'type': 'number', 'description': 'rayon autour de la commune, défaut 10'},
            'departement': {'type': 'string', 'description': '14, 27, 50, 61 ou 76'}}, 'required': ['x', 'y']}}},
    {'type': 'function', 'function': {
        'name': 'trend_projection',
        'description': "Tendance observée d'un indicateur (climat ERA5 ou bâti) et sa valeur à un horizon si elle se poursuit.",
        'parameters': {'type': 'object', 'properties': {
            'indicateur': {'type': 'string', 'enum': list(CLIMATE_VARS) + ['bati']},
            'horizon': {'type': 'integer', 'description': 'année, défaut 2050'}, **_loc}, 'required': ['indicateur']}}},
]
FUNCS.update(correlate=correlate, trend_projection=trend_projection, explain_index=_explain_with_formula)


# ---------------------------------------------------------------- Renatura AI models (pipeline/renatura_ai)

def _ml(name):
    try:
        return json.load(open(DATA / name))
    except (OSError, ValueError):
        return None


def _metrics(m):
    b = m.get('baseline') or {}
    if m.get('task') == 'classification':
        return {'auc_test': _num(m.get('auc'), 3), 'auc_reference': _num(b.get('auc'), 3),
                'precision_moyenne_test': _num(m.get('average_precision'), 3), 'taux_de_base': _num(m.get('base_rate'), 3),
                'reference': b.get('name')}
    return {'r2_test': _num(m.get('r2'), 3), 'r2_reference': _num(b.get('r2'), 3),
            'erreur_moyenne_test': _num(m.get('mae'), 3), 'erreur_moyenne_reference': _num(b.get('mae'), 3), 'reference': b.get('name')}


def model_status(store):
    """State of the three Renatura AI models with their test metrics against a simple reference."""
    s = _ml('ml_status.json')
    if s is None:
        return {'erreur': 'modèles non lancés : python -m pipeline.renatura_ai.run_normandie'}
    out = {}
    for k, m in s['models'].items():
        if m.get('status') == 'blocked':
            out[k] = {'statut': 'Non disponible / données insuffisantes', 'raison': m.get('reason')}
        else:
            out[k] = {'statut': m['status'], 'question': m.get('question'), 'cible': m.get('target_label'),
                      'apprentissage': m.get('train'), 'test': m.get('test'), **_metrics(m), 'limites': m.get('caveats')}
    return {'calcule_le': s['built_at'], 'modeles': out}


def run_models(store, cell_id=None, lon=None, lat=None, commune=None):
    """Predictions of the three models for one cell (newest state: CORINE 2018 / INSEE 2017)."""
    f, s = _ml('ml_predictions.json'), _ml('ml_status.json')
    if f is None or s is None:
        return {'erreur': 'prédictions non calculées'}
    cid = store.resolve(cell_id, lon, lat, commune)
    if cid is None:
        return {'erreur': 'maille introuvable'}
    v = f['cells'].get(cid) or {}
    st = s['models']
    pct = lambda x: 'donnée absente' if x is None else round(100 * x, 1)
    dens = lambda x: 'donnée absente' if x is None else round(10 ** x - 1)
    reliable = lambda k: st.get(k, {}).get('status') in ('performant', 'trained_exploratory')
    return {'maille': store.cell_card(store.index[cid]),
            'risque_artificialisation_2018_2024_pct': pct(v.get('artificialisation_risk')),
            'risque_perte_habitat_naturel_2018_2024_pct': pct(v.get('habitat_loss_risk')),
            'pression_humaine_estimee_hab_km2': dens(v.get('human_pressure_estimated')),
            'pression_humaine_observee_2017_hab_km2': dens(v.get('human_pressure_observed_2017')),
            'fiabilite': {k: st.get(k, {}).get('status') for k in ('territory_forecast', 'eco_vulnerability', 'human_pressure')},
            'lecture': ("Probabilités d'événements observés par CORINE (unité 25 ha) sur 6 ans, à comparer au taux de base "
                        "(environ 1 % des mailles) ; pression humaine = population INSEE estimée depuis l'occupation du sol."),
            'utilisable': all(reliable(k) for k in ('territory_forecast', 'eco_vulnerability', 'human_pressure'))}


TOOLS += [
    {'type': 'function', 'function': {'name': 'model_status',
        'description': "État et précision mesurée des 3 modèles Renatura AI (risque d'artificialisation, pression humaine, risque de perte d'habitat).",
        'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {'name': 'run_models',
        'description': "Prédictions des modèles IA pour une maille : risque d'artificialisation et de perte d'habitat d'ici 2024, pression humaine (habitants/km²).",
        'parameters': {'type': 'object', 'properties': {**_loc}}}},
]
FUNCS.update(model_status=model_status, run_models=run_models)


# ---------------------------------------------------------------- knowledge base (RAG)

def search_knowledge(store, query, k=4):
    """Passages of the Renatura knowledge base (species, ecosystems, regional sheets, method docs, user additions)."""
    from . import knowledge
    hits = knowledge.search(query, k=max(1, min(int(k), 8)))
    if not hits:
        return {'resultats': [], 'note': 'aucun passage trouvé (base vide ou documents désactivés)'}
    return {'resultats': [{'titre': h['titre'], 'origine': h['origine'], 'categorie': h['categorie'],
                           'passage': h['passage'][:900], 'score': h['score']} for h in hits],
            'consigne': 'Citer les titres entre crochets ; ne rien affirmer qui ne soit dans ces passages ou un résultat d’outil.'}


TOOLS += [{'type': 'function', 'function': {'name': 'search_knowledge',
    'description': "Recherche dans la base de connaissances Renatura : espèces, écosystèmes, maladies, règles de cohabitation, "
                   "méthode de calcul, documents ajoutés par l'équipe. À utiliser pour toute question qualitative.",
    'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}, 'k': {'type': 'integer'}}, 'required': ['query']}}}]
FUNCS.update(search_knowledge=search_knowledge)
