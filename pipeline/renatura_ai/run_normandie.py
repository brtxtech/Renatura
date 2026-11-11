"""Train / evaluate the three Renatura AI models on the real Normandy tables, honestly.

  .venv-normandie/bin/python tools/normandie/build_clc_features.py     # CORINE 1990-2018 -> features_clc.csv
  .venv-normandie/bin/python tools/normandie/build_ml_targets.py       # INSEE population + habitat loss targets
  .venv-normandie/bin/python -m pipeline.renatura_ai.run_normandie

Each model: temporal + spatial holdout of the package (test = latest period on cells never seen), compared with
a simple reference (rule or one-variable regression). « performant » only if it clearly beats that reference.
Writes
  datasets/normandie_regional/ml/artifacts/<model>.joblib + metrics (git-ignored, trusted local files only)
  dist/data/normandie/ml_status.json        status, metrics, references, model cards (for the site)
  dist/data/normandie/ml_predictions.json   per cell: risk of artificialisation and of habitat loss by 2024,
                                            human pressure estimated from 2018 land cover, observed 2017 pressure
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import yaml

from .training import load_table, predict, train_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name('configs') / 'features.yaml'
ARTIFACTS = ROOT / 'datasets/normandie_regional/ml/artifacts'
SITE = ROOT / 'dist/data/normandie'
ORDER = ('territory_forecast', 'human_pressure', 'eco_vulnerability')

LABELS = {
    'artificial_fraction': 'Part artificialisée (CORINE 1xx)', 'urban_fabric_fraction': 'Tissu urbain (11x)',
    'industrial_transport_fraction': 'Zones industrielles, commerciales, transports (12x)',
    'mines_construction_fraction': 'Mines, décharges, chantiers (13x)', 'green_urban_fraction': 'Espaces verts urbains (14x)',
    'agri_fraction': 'Terres agricoles (2xx)', 'forest_seminatural_fraction': 'Forêts et milieux semi-naturels (3xx)',
    'wetland_fraction': 'Zones humides (4xx)', 'water_fraction': 'Surfaces en eau (5xx)',
    'artificial_neigh_3km': 'Artificialisation moyenne dans un rayon de 3 km',
    'artificial_change_prev': 'Artificialisation de la maille pendant la période précédente',
    'artificial_neigh_change_prev': 'Artificialisation du voisinage (3 km) pendant la période précédente',
    'natural_loss_prev': 'Perte d’habitat naturel pendant la période précédente',
    'roads_m_ha': 'Réseau routier OSM (m/ha)', 'transit_stops': 'Arrêts de transport OSM', 'icpe': 'Établissements ICPE',
    'rail': 'Voies ferrées', 'built_share_2017': 'Part bâtie 2017 (tâche du bâti)'}
CARDS = {
    'territory_forecast': {'title': 'TerritoryForecast', 'question': 'Quelles mailles vont s’artificialiser dans les 6 prochaines années ?',
                           'sources': ['CORINE Land Cover 1990, 2000R, 2006R, 2012R, 2018 (IGN, WFS)'],
                           'train': 'paires 2000→2006 et 2006→2012', 'test': 'paire 2012→2018, mailles jamais vues (20 %)',
                           'output': 'Probabilité d’artificialisation > 1 point d’ici 2024 (depuis l’état 2018)'},
    'human_pressure': {'title': 'HumanPressure', 'question': 'Quelle pression humaine (population) s’exerce sur la maille ?',
                       'sources': ['INSEE Filosofi 2015 et 2017, carreaux de 1 km (population)', 'CORINE Land Cover 2012 et 2018'],
                       'train': 'population 2015 (occupation du sol CORINE 2012)', 'test': 'population 2017 (CORINE 2018), mailles jamais vues (20 %)',
                       'output': 'Pression humaine estimée depuis l’occupation du sol 2018, à côté de la valeur observée 2017'},
    'eco_vulnerability': {'title': 'EcoVulnerability', 'question': 'Quelles mailles risquent de perdre de l’habitat naturel ?',
                          'sources': ['CORINE Land Cover 1990, 2000R, 2006R, 2012R, 2018 (IGN, WFS)'],
                          'train': 'paire 2000→2006', 'test': 'paire 2006→2012, mailles jamais vues (20 %) — 2012→2018 n’a que 0,09 % de mailles avec perte, trop peu pour évaluer',
                          'output': 'Probabilité de perte d’habitat naturel > 1 point d’ici 2024 (depuis l’état 2018)'},
}
CAVEATS = {
    'territory_forecast': ['CORINE : unité minimale 25 ha (changements 5 ha) ; les petites extensions urbaines ne sont pas vues.',
                           'Une seule période de test (2012→2018), où l’artificialisation détectée a ralenti.',
                           'Prédire le NIVEAU futur ne bat pas « rien ne change » (tuning.json) : le modèle indique où le changement est probable.'],
    'human_pressure': ['La population est une mesure de présence humaine ; elle ne couvre ni le trafic de transit, ni l’industrie sans habitants.',
                       'Filosofi publie les carreaux habités ; un carreau absent est compté 0 habitant.',
                       'Les variables viennent de l’édition CORINE la plus proche (2012 pour 2015, 2018 pour 2017) ; routes, arrêts, ICPE et bâti 2017 sont des mesures récentes, supposées stables sur 2015-2017.'],
    'eco_vulnerability': ['La perte d’habitat est vue par CORINE (25 ha) : haies, mares et petits boisements ne sont pas mesurés.',
                          'Test sur 2006→2012 : CORINE 2018 ne détecte presque aucune perte sur 2012→2018 (0,09 % des mailles).',
                          'Probabilité d’un événement observé, pas un indice d’état écologique.'],
}


def judge(r):
    """(beats the simple reference clearly, strong in absolute terms)."""
    b = r.get('baseline') or {}
    if r['task'] == 'classification':
        beats = r.get('auc') is not None and b.get('auc') is not None and r['auc'] >= b['auc'] + 0.05 \
            and (r.get('average_precision') or 0) > (b.get('average_precision') or 0)
        return beats, r.get('auc') is not None and r['auc'] >= 0.7
    return 'mae' in b and r['mae'] < 0.95 * b['mae'], (r.get('r2') or 0) >= 0.6


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    status = {'built_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'models': {}}
    preds = {}
    for name in ORDER:
        spec = cfg['models'][name]
        data = ROOT / spec['data']
        card = {**CARDS[name], 'caveats': CAVEATS[name], 'task': spec.get('task', 'regression'), 'target_label': spec.get('target_label', spec['target']),
                'algorithm': ('HistGradientBoostingClassifier (scikit-learn) · probabilité d’un événement observé'
                              if spec.get('task') == 'classification' else 'HistGradientBoostingRegressor (scikit-learn)')}
        if not data.exists():
            status['models'][name] = {**card, 'status': 'blocked', 'reason': f'table absente : {spec["data"]}',
                                      'features': [], 'target_spec': {'id': spec['target'], 'label': spec.get('target_label'), 'available': False}}
            continue
        df = load_table(data)
        card['features'] = [{'id': f, 'label': LABELS.get(f, f), 'available': f in df.columns} for f in spec['features']]
        card['target_spec'] = {'id': spec['target'], 'label': spec.get('target_label', spec['target']),
                               'available': spec['target'] in df.columns, 'horizon_years': spec.get('horizon_years'),
                               'mode': spec.get('target_mode', 'level')}
        try:
            r = train_model(data, CONFIG, name, ARTIFACTS)
        except ValueError as e:
            status['models'][name] = {**card, 'status': 'blocked', 'reason': str(e)}
            continue
        beats, strong = judge(r)
        status['models'][name] = {**card, **{k: v for k, v in r.items() if k not in ('model', 'status', 'warning')},
                                  'status': 'performant' if beats and strong else 'trained_exploratory' if beats
                                  else 'trained_not_better_than_baseline', 'beats_baseline': beats}
        latest = df[df.observation_year == df.observation_year.max()].reset_index(drop=True)   # apply to the newest state
        preds[name] = dict(zip(latest.cell_id, predict(ARTIFACTS / f'{name}.joblib', latest)))
        if name == 'human_pressure':
            preds['human_pressure_observed'] = dict(zip(latest.cell_id, latest[spec['target']]))
        if name == 'territory_forecast':
            years = sorted(int(y) for y in df.observation_year.unique())
            piv = df.pivot(index='cell_id', columns='observation_year', values='artificial_fraction')
            periods = [{'periode': f'{a}→{b}', 'changement_moyen_pts': round(float((piv[b] - piv[a]).mean() * 100), 3),
                        'mailles_qui_changent': int(((piv[b] - piv[a]) > 0.01).sum())} for a, b in zip(years, years[1:])]
            status['data_summary'] = {'cells': int(df.cell_id.nunique()), 'years': years, 'rows': int(len(df)),
                                      'source': 'CORINE Land Cover 1990 (période précédente), 2000R, 2006R, 2012R, 2018 · INSEE Filosofi 2015, 2017',
                                      'grid': 'Mailles hexagonales de 1 km² (Lambert-93), 30 850 sur la Normandie', 'periods': periods}
    r4 = lambda v: None if v is None or pd.isna(v) else round(float(v), 4)
    cells = sorted(set().union(*[set(v) for v in preds.values()])) if preds else []
    json.dump({'built_at': status['built_at'],
               'fields': {'artificialisation_risk': 'probabilité (0-1) d’artificialisation > 1 point entre 2018 et 2024',
                          'habitat_loss_risk': 'probabilité (0-1) de perte d’habitat naturel > 1 point entre 2018 et 2024',
                          'human_pressure_estimated': 'log10(1 + hab/km²) estimé depuis CORINE 2018',
                          'human_pressure_observed_2017': 'log10(1 + hab/km²) observé, INSEE Filosofi 2017'},
               'status': {k: v['status'] for k, v in status['models'].items()},
               'cells': {c: {'artificialisation_risk': r4(preds.get('territory_forecast', {}).get(c)),
                             'habitat_loss_risk': r4(preds.get('eco_vulnerability', {}).get(c)),
                             'human_pressure_estimated': r4(preds.get('human_pressure', {}).get(c)),
                             'human_pressure_observed_2017': r4(preds.get('human_pressure_observed', {}).get(c))} for c in cells}},
              open(SITE / 'ml_predictions.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    (SITE / 'ml_status.json').write_text(json.dumps(status, ensure_ascii=False, indent=1))
    old = SITE / 'forecast_artificial.json'
    if old.exists():
        old.unlink()  # replaced by ml_predictions.json
    for k, m in status['models'].items():
        b = m.get('baseline') or {}
        if m['status'] == 'blocked':
            print(f'{k}: BLOCKED — {m["reason"]}')
        elif m['task'] == 'classification':
            print(f"{k}: {m['status']} · AUC {m['auc']:.3f} vs référence {b.get('auc', float('nan')):.3f} · AP {m['average_precision']:.3f} "
                  f"vs {b.get('average_precision', float('nan')):.3f} (taux de base {m['base_rate']:.3f}) · n_test {m['n_test']}")
        else:
            print(f"{k}: {m['status']} · MAE {m['mae']:.3f} vs référence {b.get('mae', float('nan')):.3f} · "
                  f"R² {m['r2']:.3f} vs {b.get('r2', float('nan')):.3f} · n_test {m['n_test']}")


if __name__ == '__main__':
    main()
