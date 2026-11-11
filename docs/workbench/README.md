# Atelier de données (ex « renatura-workbench »), intégré à Renatura

The standalone `renatura-workbench` folder has been merged into the Renatura project:

| Part | Location in Renatura |
|---|---|
| Backend (FastAPI, workflow engine, validation, SQLite) | `pipeline/workbench/` (was `backend/`) |
| Frontend | `dist/workbench/` (was `frontend/`); also the **Workflow de validation** tab of `dist/data.html` |
| Reference catalogue, synthetic examples | `pipeline/workbench/data/`, `pipeline/workbench/examples/` |
| Tests | `tests/workbench/` (`python -m unittest discover -s tests/workbench -t .`) |
| Docs, catalogue builder | `docs/workbench/`, `tools/workbench_build_catalog.py` |
| Runtime data (SQLite, uploads, images, **log files**) | `user-data/workbench/` (override: `RENATURA_WORKBENCH_DATA`; not versioned) |

**Run:** it is mounted in both Renatura servers, at `/workbench` (UI) and `/workbench/api` (API):
- `.venv-normandie/bin/python -m uvicorn pipeline.nature.server:app --port 8090` → http://localhost:8090/workbench/
- or `./run-renatura.command` / `./run-atlas.sh` → http://localhost:8080/workbench/

The old standalone launchers (`run.sh`, `run.ps1`, `preview.py`, `Dockerfile`, `compose.yaml`) were not carried over:
Renatura's own launchers serve it.

**Added during the merge**
- **Link / API intake** (`POST /api/intake/fetch`, field « Fetch from link / API » in the form): secure download
  (HTTPS only, no credentials/secrets in the URL, public addresses only and re-checked on every redirect, 25 MB cap,
  timeouts; WFS converted to GeoJSON, first 10 000 features) then the same validation pipeline as a file.
- **Log files**: every pipeline event is also appended as a JSON line to
  `user-data/workbench/logs/workbench-YYYY-MM-DD.log` (in addition to the SQLite `events` table).
- **Use in the views**: a populated GeoJSON / land dataset is published to `user-data/datasets/wb_<id>.json`, the
  registry read by the Atlas (`/api/datasets`); removal and restoration keep it in sync. Non-geographic data stays
  in the workbench datastore. Only validated (accepted) elements are ever published.

---

# Renatura — Reference data workflow, v2

A **workflow-only interface** for reference uploads, typed input boxes, validation, quarantine, explicit category population, and management of existing information. The interface has no chat panel. The earlier observation/model backend APIs remain available for compatibility, but are not part of this screen.

## Run

Requires Python 3.10+ (3.12 recommended).

```bash
cd renatura-workbench
bash run.sh
```

Open http://127.0.0.1:8000. Windows: run `run.ps1`. Docker: `docker compose up --build` (Docker configuration supplied, not executed during verification).

Manual install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

No npm installation or frontend build is needed. SQLite and uploaded files persist in `runtime/`, or an absolute path set through `RENATURA_DATA`. The source ZIP does not contain a runtime database or uploaded user files.

## The workflow

1. **Upload reference**: give the file a reference name; optionally record its source URL, dataset ID or document reference. A UUID and SHA-256 preserve its identity and provenance.
2. **Element type box**: explicitly choose GeoJSON layer, JSON records, climate records, land/parcels or species image. The file must match the declared structure.
3. **Validation gate**: check the file type, expected properties schema, required non-null fields, nulls, duplicate feature IDs and WGS84 geometry.
4. **Valid elements**: accepted records are ready; they have not yet been populated.
5. **Invalid elements**: rejected records are quarantined. A mismatched file type or entirely invalid file blocks population. The application reports the error instead of crashing.
6. **Populate category**: select or change the target category, then explicitly populate the accepted elements. Invalid elements remain excluded.
7. **Datastore**: browse actual stored datasets, individual records, schemas, distributions and category information. Remove information to recoverable Trash when needed.

Click a box to configure or inspect it. Each executable box has run/stop controls; shared routing produces the accepted and rejected branches. Every Python stage logs execution events. The engine uses subprocess workers, with up to four jobs and a 120-second node timeout. Run the service with one Uvicorn worker. Stop prevents downstream execution but does not undo writes already committed. Interrupted jobs are marked on restart; upload a corrected reference to retry an interrupted import.

This is a fixed reference-ingestion pipeline with configurable input types, not a general-purpose arbitrary code/graph editor.

## Test valid and invalid elements

The files in `examples/` are **synthetic fixtures**, not real territorial measurements.

- Create a reference named “Synthetic canopy quality check”.
- Select **GeoJSON layer**, upload `examples/anomalies.geojson`, and select a target category.
- Expand **Schema & catalogue reference**. Paste `examples/canopy.schema.json` into the expected schema field. Set collection state to Partial.
- Validate. The reference becomes **partial ready**: one accepted element and three rejected elements (null numeric value, wrong field type, bad coordinate).
- Inspect the green Valid elements box and red Invalid elements box. Open their reports.
- Choose Populate category and click **Populate 1 valid element**. Only that one element appears in the datastore.
- Inspect the populated dataset, select its element and remove it. Open Trash to restore it.

To test a wrong box, upload `examples/climate.json` into a **GeoJSON layer** box. The type gate blocks it and population is unavailable. Use a **Climate records** box for that file.

A missing expected schema cannot validate agreement with an unseen authoritative schema. If no schema is provided, a permissive descriptive schema is inferred from observed valid fields. JSON Schema applies to each GeoJSON `properties` object or plain JSON record, not the FeatureCollection wrapper. `required` means present; a non-null type or the separate required non-null fields setting is needed to reject nulls. Warnings do not automatically reject a record; errors do.

Box contracts:

| Type | Accepted input structure |
| --- | --- |
| GeoJSON layer | WGS84 FeatureCollection with valid feature geometries |
| Land & parcels | WGS84 FeatureCollection; use the expected schema for parcel-specific attributes |
| JSON records | JSON record object or array of objects |
| Climate records | JSON record object/array; use the expected schema for units, time and numeric climate fields |
| Species image | Decodable image; image metadata can also be checked against the expected schema |

Image files are verified, converted to JPEG and stripped of EXIF for normalized storage. Species recognition is not performed by this ingestion workflow. No model weights or external services are required.

## Access existing information

The lower part of the same screen shows categories and populated datasets.

- **Category card**: actual dataset count, actual valid element count and current collection state. Open its information to compare actual imports against source catalogue references and their reported statuses.
- **Inspect dataset**: browse actual records in pages of 30; view schema, accepted-data distribution and validation anomalies; download stored data.
- **Remove selected elements**: creates a revised dataset and saves the preceding state in recoverable Trash. Stale edits are rejected using the dataset revision ID.
- **Remove dataset**: moves the full dataset into Trash, updates category counts and recalculates configured indicators. A rule referencing it becomes unavailable, not zero.
- **Restore**: returns a removed dataset or record selection. Restoring records is blocked if it would overwrite subsequent edits.
- **Create category**: adds a new named destination with a description.

Remove means logical removal from the active datastore, not irreversible erasure. Source uploads, validation reports and history remain for traceability. The interface does not implement a permanent purge. Back up the entire runtime directory, including SQLite and binary uploads/images.

## Catalogue and existing project data

The supplied inventory contains **146 parsed layer references**, 10 broad categories and 26 thematic groups. Three additional destination categories (Climate, Foncier, Images et espèces) are initialized for new references; more can be created. Original reported counts and collection states remain separate from actual imported record counts. `verified_file` is a claim in the provided snapshot, not an independent verification by this app.

Original source geometries, authoritative schemas, API endpoints and source records were not supplied. The catalogue therefore starts as metadata, and categories remain empty until populated. No data is fabricated to fill them. To access datasets already stored by the earlier version, retain the same `runtime/` directory or `RENATURA_DATA` location. Datasets from the earlier app are matched to categories by their existing names.

The original text is preserved in `docs/supplied-requirements.txt`; `python tools/build_catalog.py` regenerates the bundled catalogue metadata.

## Calculations and model APIs

Saved indicator rules from the previous backend continue to recalculate on population, removal and restoration. A rule binds to an imported dataset ID. Missing values remain null/not calculable; partial extraction cannot establish absence. The fixed numeric index remains exploratory and requires scientific review. New datasets are not silently added to existing rules. Configure rules through `/api/config` (API docs: `/docs`). The calculation editor and species chat are intentionally not visible in this workflow-only UI.

Earlier observation nodes and optional AlexNet/LLM adapters remain in `backend/nodes/` for reuse through the API. They are not part of the reference-validation pipeline. See `.env.example` for optional model variables; `.env` files are not automatically loaded by direct Python launches. No model credentials or weights are bundled.

## Limits and deployment

Local, single-workspace application; not a multi-tenant SaaS. Default server binds to localhost. Optional `RENATURA_TOKEN` protects APIs with a shared `X-Workspace-Token`; enter it with the header settings button. It is not per-user authentication. Internet hosting requires HTTPS, user authorization, rate limits, durable worker infrastructure and a production storage design.

Limits: 25 MiB per upload and 100,000 records per JSON/GeoJSON validation batch; images up to 24 megapixels. Large regional datasets need chunked imports and, in a full production implementation, PostGIS and spatial indexes. Remote source APIs are not automatically queried. The UI can use system fonts offline, with Google Fonts optional when reachable.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

13 tests passed during verification: previous calculations/validation/cancellation tests plus reference gating, partial acceptance without automatic population, target change, valid-only population, duplicate-population prevention, selected-record removal/restoration, dataset removal/restoration, wrong-type blocking and stale-edit protection. Browser checks cover real upload, schema validation, routing and populated-data inspection. Real external model requests, Docker and large regional-scale workloads are not claimed tested.

## Source layout

- `frontend/`: workflow-only interface and interactive boxes.
- `backend/intake_api.py`: staged reference upload, categories, records, removal and restoration.
- `backend/ingestion.py`: Python reference/type/validation/routing/population/datastore stage functions.
- `backend/workflow.py`: subprocess jobs, run/stop controls and persisted logs.
- `backend/validation.py`: schema/geometry validation and distributions.
- `backend/db.py`: SQLite documents and events.
- `backend/calculation.py`: retained exploratory indicator engine.
- `backend/nodes/`: retained observation/model adapters.
- `data/`, `examples/`, `tests/`, `docs/`: inventory, synthetic fixtures, tests and context.

Third-party dependencies, original source data and any future model weights retain their respective licenses.
