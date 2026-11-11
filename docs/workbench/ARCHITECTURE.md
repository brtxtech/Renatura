# Reference-driven workflow architecture

The frontend displays a single workflow graph, a selected-box inspector, execution activity, category state cards and stored dataset records. Upload configuration binds a file reference to a declared element type and a target category. An optional expected properties schema and non-null fields govern validation.

`POST /api/intake/uploads` stores the reference and source file, then starts subprocess stages `reference → type_check → validation → routing`. Accepted records and anomalies stay attached to the staged batch. Routing yields ready, partial_ready, or blocked; it does not populate the active datastore. A wrong element type produces a visible blocked batch without bringing down the application.

`POST /api/intake/uploads/{id}/populate` runs `populate → datastore`. Only accepted records are written; population and batch state commit in one SQLite transaction. A populated reference cannot be revalidated into an editable state or populated twice. The rejected branch remains as provenance.

`GET /api/intake/state` combines the reference catalogue with actual stored data. Category states and counts derive from real imports, while reported source counts retain their own labels. The latest activity is available on the workspace; a selected reference can retrieve its own persisted job logs independently of recent global activity.

`GET /api/intake/datasets/{id}/records` pages actual elements. Removing a selection checks the dataset revision, preserves the previous state and writes a new revision. Removing a dataset moves it to logical Trash. Restore protects against overwriting subsequent edits. Population, removal and restoration refresh the retained exploratory calculation engine; missing source data stays unavailable rather than becoming zero.

The runtime directory holds SQLite documents/events, original staged upload files and normalized JPEGs. It is excluded from the source ZIP. Retain it to access previously implemented data. This is a local single-workspace implementation, with optional shared API token; per-user authorization and regional-scale PostGIS/object-storage infrastructure are future deployment work.
