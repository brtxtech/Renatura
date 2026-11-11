# Renatura extensions: photos, price & benefit, climate

All three use the 1 km² regional grid (`H1_x_y` cell ids) and stay **separate indicators**: none of
them changes V/D/P/O yet (default decision until they are validated).

| | Page | Data | Build / service |
|---|---|---|---|
| 1 · Photos nature | `dist/photos-normandie.html` | `user-data/nature/` (private), `dist/data/normandie/photo_evidence.json` | `ml/train_species.py`, `pipeline/nature/server.py` |
| 2 · Prix & bénéfice | `dist/acheteur-normandie.html` | `dist/data/normandie/prices.json`, `buyer_cells.json` | `tools/normandie/price_cells.py` |
| 3 · Climat | `dist/climat-normandie.html` | `dist/data/normandie/climate.json` | `tools/normandie/climate_history.py` |

Run everything locally (one server for the pages and the photo API):
```bash
.venv-normandie/bin/python -m uvicorn pipeline.nature.server:app --port 8090
# open http://localhost:8090/photos-normandie.html, /acheteur-normandie.html, /climat-normandie.html
```
The price and climate pages also work from the plain static server (port 8088); the photo page needs the API.

## 1 · Photos nature (MVP)

**Model.** `ml/train_species.py` fine-tunes EfficientNet-B0 (ImageNet weights, timm) on
`datasets/normandie_species/training_set` (739 species with ≥ 10 photos; photos of one observation never
cross splits). The best epoch is picked on validation, then measured once on test. A confidence threshold is chosen on
validation for 95 % precision: above it a prediction is labelled `auto`; it still needs a human to count.
Outputs: `datasets/normandie_species/model/{model.pt, classes.json, metrics.json, confusions.csv, test_predictions.csv}`.

**Service** (`pipeline/nature/server.py`, FastAPI):
- `POST /api/nature/photos`: partner key required; GPS + date read from EXIF (or manual position), photo re-encoded
  (all metadata dropped), faces blurred (OpenCV), must fall inside a Normandy cell, top-5 species stored as `pending`/`auto`.
- `POST /api/nature/photos/{id}/validate`: `confirm | correct | reject`; **confirmed** = 2 partners agree or 1 expert.
- `GET /api/nature/photos`: public list = confirmed only; sensitive species (protected in France or VU/EN/CR on the
  Normandy Red List) at 10 km precision and without cell id.
- `GET /api/nature/evidence`: per-cell layer: confirmed photos, species, protected / invasive species, groups,
  effort (observer × day), species per effort, months.
- Partner keys: `.venv-normandie/bin/python -m pipeline.nature.partners add "Name" [--expert]` (stored hashed).

## 2 · Prix & bénéfice

- **DVF** (geo-DVF Etalab 2021-2025, 5 departments): sales whose lots are all rural and unbuilt (land, meadows,
  orchards, woods, heath); €/ha = sale value / total land area; plots < 0.25 ha and 1 % tails removed; categories
  agricultural / forest / all rural.
- **Per cell:** median + 25-75 % over the cell's sales; if < 5 sales: 5 km, then 10 km neighbourhood, then department.
  The level is always shown. **No statistic on fewer than 5 sales; no individual sale is written** (DVF reuse terms).
- **Official reference:** barème indicatif 2024 (JORF 29/08/2025), arable land and meadows, by small agricultural region,
  used as department reference and as a check (see results).
- **Buyer card:** price range, order of magnitude for the cell, V/D/P/O, RP (default weights), RP per 10 000 €/ha,
  corridor membership, designations (Natura 2000, ZNIEFF, APB, reserves, PNR, SPRB, ORE, nitrate zone).
- Not done yet: carbon potential (ADEME ALDO factors), PLU zoning API, access control for an online deployment.

## 3 · Climat (historical series first)

- **Climate:** ERA5 daily reanalysis (Open-Meteo archive, no key) at 34 points of a 0.5° grid, 1991-2025 → yearly mean
  temperature, rain, days ≥ 30 °C, dry days, longest dry spell, summer rain. Trend = Sen slope per decade + Mann-Kendall;
  anomaly = 2016-2025 minus 1991-2020.
- **Vegetation:** MODIS MOD13Q1 NDVI (NASA ORNL subset API), June-August composites, 2 × 2 km window per point,
  2001-2025 → summer NDVI trend (greenness / summer stress). The full 16-day series would take > 16 h on this public
  service; summer-only keeps the drought signal.
- **Land change:** built-up area 2006 → 2017 **in Basse-Normandie only** (the 2006 edition covers only Calvados, Manche
  and Orne). The 2025 edition is **not comparable** (method change: +64 % built area in the Orne in 8 years with a stable
  number of objects) and is shown as a current level only.
- Next: DRIAS projections on the French reference warming trajectory (TRACC), then vulnerability = exposure ×
  sensitivity × adaptive capacity per cell, then photo phenology (Extension 1) as a biological signal.

## Data issues found and fixed along the way
- 8 "photos" were JSON/IIIF manifests saved as `.jpg` by GBIF media servers → removed; the downloader now verifies every image.
- The regional D criterion used "built-up growth 2006 → 2025": outside Basse-Normandie this was an artefact (no 2006 data)
  and 2025 is not comparable. It now uses 2006 → 2017 on Basse-Normandie only (`layer_scoring.json`); rerun
  `tools/normandie/multilayer_score.py` to apply it.
- `cells.geojson.gz` was older than `cells.geojson` after another build; tools and pages now use the gzip copy only when it is not older.
