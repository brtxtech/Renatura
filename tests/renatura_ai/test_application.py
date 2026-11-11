"""How the Renatura AI models are applied: direct prediction, REST API, assistant tool, refusals.

- tests on the REAL artefacts (CORINE + INSEE tables, trained models): skipped if not built
  (tools/normandie/build_clc_features.py, tools/normandie/build_ml_targets.py, python -m pipeline.renatura_ai.run_normandie);
- one FIXTURE test in a temp folder shows the application path when a model is retrained elsewhere; its numbers are
  test data, nothing is written to dist/.
"""
import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from pipeline.renatura_ai import apply as A
from pipeline.renatura_ai.training import predict, train_model

ROOT = Path(A.__file__).resolve().parents[2]
CFG = yaml.safe_load(A.CONFIG.read_text(encoding='utf-8'))
ART = {m: A.ARTIFACTS / f'{m}.joblib' for m in A.MODELS}
needs_real = pytest.mark.skipif(not (all(p.exists() for p in ART.values()) and A.STATUS.exists()), reason='real artefacts not built')


def status():
    return json.loads(A.STATUS.read_text())['models']


# ---------------------------------------------------------------- 1. applied to real cells

@needs_real
def test_three_models_applied_to_a_real_commune():
    ids, _ = A.cells_of('Caen')
    res = A.apply(ids)
    for cid in ids:
        r = res[cid]
        assert 0 <= r['territory_forecast']['probabilite'] <= 1
        assert 0 <= r['eco_vulnerability']['probabilite'] <= 1
        assert r['human_pressure']['estime_hab_km2'] >= 0 and r['human_pressure']['observe_hab_km2'] >= 0
    risk = np.mean([res[c]['territory_forecast']['probabilite'] for c in ids])
    est = np.median([res[c]['human_pressure']['estime_hab_km2'] for c in ids])
    obs = np.median([res[c]['human_pressure']['observe_hab_km2'] for c in ids])
    print(f'\n  Caen ({len(ids)} mailles) : risque d’artificialisation moyen {risk:.1%}, '
          f'pression humaine médiane estimée {est:.0f} hab/km² (observée INSEE 2017 : {obs:.0f})')


@needs_real
def test_urban_cell_has_more_pressure_than_rural_cell():
    res = A.apply(['H1_487_6424', 'H1_539_6423'])           # centre of Caen vs Fauguernon countryside
    city, rural = res['H1_487_6424']['human_pressure'], res['H1_539_6423']['human_pressure']
    assert city['estime_hab_km2'] > 10 * max(rural['estime_hab_km2'], 1)


@needs_real
def test_models_beat_their_reference_on_the_test_period():
    for name, m in status().items():
        b = m['baseline']
        if m['task'] == 'classification':
            assert m['auc'] > b['auc'] and m['average_precision'] > m['base_rate']
        else:
            assert m['mae'] < b['mae'] and m['r2'] > b['r2']
        assert m['status'] in ('performant', 'trained_exploratory')


@needs_real
def test_risk_ranks_cells_that_really_changed():
    """On the test period the cells that changed must get a higher mean probability than the others."""
    t = pd.read_csv(ROOT / CFG['models']['territory_forecast']['data'])
    a = t.pivot(index='cell_id', columns='observation_year', values='artificial_fraction')
    changed = (a[2018] - a[2012]) > 0.01
    rows = t[t.observation_year == 2012].set_index('cell_id').loc[a.index].reset_index()
    p = predict(ART['territory_forecast'], rows).to_numpy()
    assert p[changed.to_numpy()].mean() > 3 * p[~changed.to_numpy()].mean()


@needs_real
def test_forecast_is_deterministic():
    ids = ['H1_538_6422', 'H1_487_6422']
    assert A.apply(ids) == A.apply(ids)


@needs_real
def test_missing_features_give_no_prediction():
    feats = CFG['models']['territory_forecast']['features']
    assert predict(ART['territory_forecast'], pd.DataFrame([{c: np.nan for c in feats}])).isna().all()


# ---------------------------------------------------------------- 2. REST API (pipeline/renatura_ai/api.py)

def _api(artifact_dir, monkeypatch):
    monkeypatch.setenv('RENATURA_ARTIFACT_DIR', str(artifact_dir))
    import pipeline.renatura_ai.api as api
    return TestClient(importlib.reload(api).app)


@needs_real
def test_api_applies_the_three_models(monkeypatch):
    client = _api(A.ARTIFACTS, monkeypatch)
    assert set(client.get('/health').json()['available_models']) == set(A.MODELS)
    for name in A.MODELS:
        t = pd.read_csv(ROOT / CFG['models'][name]['data'])
        row = t[t.observation_year == t.observation_year.max()].query('cell_id == "H1_538_6422"').iloc[0]
        feats = {f: (None if pd.isna(row[f]) else float(row[f])) for f in CFG['models'][name]['features']}
        r = client.post(f'/predict/{name}', json={'rows': [feats, {k: None for k in feats}]})
        assert r.status_code == 200, r.text
        assert r.json()['predictions'][0] is not None and r.json()['predictions'][1] is None


def test_api_refuses_unknown_and_untrained_models(tmp_path, monkeypatch):
    client = _api(tmp_path, monkeypatch)
    assert client.post('/predict/nope', json={'rows': [{'a': 1}]}).status_code == 404
    assert client.post('/predict/human_pressure', json={'rows': [{'a': 1}]}).status_code == 503
    assert client.post('/predict/territory_forecast', json={'rows': []}).status_code == 422


# ---------------------------------------------------------------- 3. retraining path (fixture, temp folder)

def test_retraining_path_on_a_fixture_table(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    rows = []
    for year in (2015, 2017):
        built = rng.uniform(0, .6, 400)
        rows += [{'cell_id': f'c{i}', 'observation_year': year, 'artificial_fraction': built[i],
                  'observed_human_pressure': 3 * built[i] + rng.normal(0, .1)} for i in range(400)]
    data = tmp_path / 'fixture.csv'
    pd.DataFrame(rows).to_csv(data, index=False)
    cfg = {'cell_id': 'cell_id', 'year': 'observation_year', 'models': {'human_pressure': {
        'features': ['artificial_fraction'], 'target': 'observed_human_pressure', 'baseline_feature': 'artificial_fraction'}}}
    (tmp_path / 'c.yaml').write_text(yaml.safe_dump(cfg))
    report = train_model(data, tmp_path / 'c.yaml', 'human_pressure', tmp_path / 'artifacts')
    assert report['n_test'] > 0 and report['r2'] > .8
    client = _api(tmp_path / 'artifacts', monkeypatch)
    hi, lo = client.post('/predict/human_pressure', json={'rows': [{'artificial_fraction': .5}, {'artificial_fraction': .02}]}).json()['predictions']
    assert hi > lo


# ---------------------------------------------------------------- 4. assistant tool

@needs_real
def test_assistant_tool_returns_the_three_predictions():
    from pipeline.assistant import tools as T
    s = T.Store()
    r = T.run_models(s, commune='Caen')
    assert isinstance(r['risque_artificialisation_2018_2024_pct'], float)
    assert isinstance(r['pression_humaine_observee_2017_hab_km2'], int)
    assert set(r['fiabilite']) == set(A.MODELS)
    st = T.model_status(s)['modeles']
    assert st['territory_forecast']['auc_test'] > st['territory_forecast']['auc_reference']
