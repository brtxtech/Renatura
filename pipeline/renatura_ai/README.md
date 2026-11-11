# RENATURA AI — 3 environmental ML models (research baseline)

**Status: implementation delivered, NOT trained or validated on the user's actual database.**
This package deliberately refuses to claim predictive accuracy without accessible training data and observed ground truth.

## Actual known Renatura integration points

- Regional atlas: 193 declared thematic layers / 2,995,848 source records (user's current catalog snapshot).
- 146 thematic layers / 3 sources activated on the current screen. **Display counts do not prove 146 ingested sources.**
- Past pilot `dist/data/normandie/cells.geojson` fields `V`, `D`, `P`, `O`, `P_preview`; V and D were partly available, P/O unvalidated, P_preview exploratory.
- Initial prioritisation formula: 30% V, 30% D, 15% P, 25% O, normalised over available criteria only in explicit partial mode. **Do not use this derived score as a supervised target** without independent labels.
- Prior datasets local organisation: `MyDrive/Dataset-final/Sec1...Sec4`; CRS EPSG:2154 for spatial analysis. Historical hedgerow observations 1947, 2010, 2016 are potential temporal inputs but must be checked for comparable measurement methods.

## Three implemented models

1. `human_pressure`: supervised regression toward `observed_human_pressure` (required independent measurement) using transport, built, industry, population and imperviousness predictors. If no independent observations exist, do NOT train. An exploratory hand-defined composite can be displayed, clearly labeled "proxy".
2. `eco_vulnerability`: supervised regression toward `observed_ecological_impact` (required independent measured impact) using forest, canopy, hedgerow loss, corridors, wetland, protected status, drought and biodiversity. Correlations do not establish causation. Protected designation is a context variable, not synonymous with good ecological condition.
3. `territory_forecast`: predicts **next-year built fraction** (not all environmental change at once), using paired cell/year observations. `horizon_years` and aligned historical years can be changed in config; the default 1 year requires consecutive years. No temporal pairs => no trained forecast.

Algorithm: HistGradientBoostingRegressor; median imputation fitted ONLY on train, plus missingness indicators; strict missing-data preservation. Evaluation: holdout on last available label-year and disjoint cell identifiers. **For publication: replace hash cell split with spatial block holdout and spatial/temporal cross-validation; independent ground truth and uncertainty intervals.**

## Install

```bash
cd renatura_ai_models
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Audit the previous pilot

```bash
python -m renatura_ai.from_cells --input /path/to/Renatura/dist/data/normandie/cells.geojson --output data/cells_audit.csv
python -m renatura_ai.inspect --data data/cells_audit.csv
```

This outputs only existing V/D/P/O properties; it is **not** a valid training table, and the training step must not treat `P_preview` as verified ground truth.

## 2. Build spatial feature table

Build one record per `cell_id` + `observation_year` after aggregating real spatial layers into a stable EPSG:2154 grid (e.g., 1 km² OR the existing Renatura 5-km grid, choose one and version it):

- Roads/rail: clip by cell, sum intersected line lengths / cell area (km/km²).
- Built/forests/canopy/wetlands/protected areas: dissolve geometries to prevent double-counting, intersect each cell, union area / cell land area (0..1).
- ICPE: point-in-polygon count / cell area (events per km²).
- Biodiversity: observation counts must account for sampling effort; species richness is biased if camera coverage differs.
- Time: source **observation date**, not file download year or layer publication date.
- Raster layers: zonal statistics, preserve raster resolution, nodata and coverage metadata.
- Every source: dataset ID, source URL, license, collection state, observation period, CRS, footprint, completeness.
- Store missing values as NULL/NaN, **not 0**. Mask unavailable regions.

Expected canonical feature schema is `configs/features.yaml`. Create a mapping from actual SQL columns/layer IDs to these names; no live SQL schema was available in this session, so no SQL table names are assumed.

### Example canonical CSV header (do not fabricate training values)

```csv
cell_id,observation_year,road_density_km_km2,rail_density_km_km2,built_fraction,icpe_density_km2,quarry_fraction,population_density,impervious_fraction,forest_fraction,canopy_fraction,hedgerow_loss_fraction,habitat_fragmentation,corridor_density_km_km2,wetland_fraction,protected_fraction,human_pressure_observed,drought_index,species_richness,observed_human_pressure,observed_ecological_impact
```

`observed_human_pressure`, `observed_ecological_impact` are ground truth targets **only if independently measured**; rename or substitute an actual suitable observed endpoint. Do not leak target into features; notably ensure `human_pressure_observed` is not the target of model 1.

## 3. Train with data, then test

```bash
python -m renatura_ai.inspect --data data/features.parquet
python -m renatura_ai.training --data data/features.parquet --model human_pressure
python -m renatura_ai.training --data data/features.parquet --model eco_vulnerability
python -m renatura_ai.training --data data/features.parquet --model territory_forecast
pytest -q
```

Each command fails explicitly if labels/features/historical years are not present. When ready: `artifacts/<model>.joblib` and `<model>_metrics.json`.

## 4. API (do not expose publicly without auth/rate limits)

```bash
uvicorn renatura_ai.api:app --host 127.0.0.1 --port 8001
curl http://127.0.0.1:8001/health
```

`POST /predict/human_pressure`, `/predict/eco_vulnerability`, `/predict/territory_forecast` with `{ "rows": [{"road_density_km_km2": ..., ...}] }` according to the trained feature manifest. API returns `null` for rows with no observed features. Trusted artifacts only: joblib is pickle-based and must never be loaded from untrusted users.

## Remaining integrations (user's extra data)

| Dataset | Use | Next step |
|---|---|---|
| Animal camera/photos | Grounded wildlife observation, occupancy/detection with sampling effort | Geotag and timestamp; species labels, camera effort, permissions; protect sensitive endangered locations |
| Plant photos | Species inference as optional feature, not direct ecological ground truth | Human-confirmed taxonomy, photo geolocation/date, confidence/unknown class; evaluate FLORO locally |
| Forest biomass model (Vertify) | Additional predictor; satellite model outputs by cell | Check model card/license/inputs, calibration for Normandy rather than assume tropical transfer |
| Land price screenshot/maps | Opportunity indicator O if transaction/reference year and location verified | Extract with human QA or obtain underlying DVF/official price records; no unverified image-derived prices |
| Additional citizen uploads | New observations | Quarantine, provenance, moderation, dedup, consent, validation; never auto-retrain on unverified uploads |
| Climate historical series | Drought / anomalies / forecast features | Comparable years, source provenance and spatial interpolation uncertainty |
| Urbanisation historical layers | Observed time pairs for model 3 | CORINE 1990/2000/2006/2012/2018/2024 etc **only if actually ingested and temporally harmonised**; align horizon to available year gaps |

## Priority for integration in existing Renatura app

1. Add `AI Chatbot` page, with selected map geometry, explicit data-coverage badges and cited datasets.
2. Add backend tool operations `get_cell_features`, `get_data_provenance`, `run_human_pressure`, `run_eco_vulnerability`, `run_territory_forecast` with parameter validation.
3. Never let an LLM invent model scores: use actual API results; show absent model as `Non disponible / Données insuffisantes`.
4. Separate atlas layers loaded in frontend from validated computation layers.
5. Keep initial V/D/P/O prioritisation and version new ML outputs separately. An exploratory P proxy is NOT equal to validated P.
6. Allow opt-in user observations after moderation and scientific data validation; retrain offline versioned, not on each chat request.

## Why there are no claimed results

We have the atlas metadata, past notebook descriptions and pilot file format, **not the live Renatura database, field records or independent labels in this session**. Hence artifacts contain runnable model implementations, validation and adapters, but not fabricated model weights or scores.
