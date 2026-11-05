# Roadmap and operational refresh

1. Validate pilot semantics with a landscape ecologist. Inspect three documented
   sites, verify hedgerow changes and check the effect of woodland succession.
2. Ingest licensed pressure and land-opportunity layers with explicit field mappings.
   Keep missing coverage null. Revisit confidence as a source-layer coverage index
   when a real multi-layer indicator specification exists.
3. Calibrate species/guild connectivity and resistance. Review core threshold,
   path alternatives, resource units and clipped-cell size bias.
4. Add region-wide partitions, commune/EPCI lookup and optional local terrain tiles.
   Benchmark payload, memory, first load and interaction on a named iPad model.
5. Add optional pymoo NSGA-II for a Pareto front only after ecological benefit and
   cost objectives are meaningful. Never label its heuristic front globally optimal.
6. Expand offline validation and user testing before operational recommendations.

## Regular updates

Run `bash run.sh` on the computer whenever inputs are intentionally refreshed.
The application itself does not schedule work while closed. An external scheduler
can invoke this command on a workstation or CI runner; review source changes and
publish the resulting static files only after the tests pass. Source snapshots
are intentionally reused until replaced. Keep the previous manifest for comparison.

No scheduler is installed or enabled by this project. No email or external
notification is sent. Pipeline timestamps and source hashes disclose the build.

## Resource choices

A static app avoids a continuously provisioned compute server. Local GeoParquet
makes repeated spatial input reads cheaper; raw layers are optional downloads.
MapLibre assets and data are self-hosted. Offline storage is bounded by the supplied
app payload, and users opt into historical layers. All data-processing costs still
exist; no carbon-saving number is claimed without measurement.

A national extension could partition jobs by region and distribute independent
stages. Hadoop/Spark are scaling options only, not requirements for this project.
Prefer local incremental rebuilds and measure bottlenecks first.
