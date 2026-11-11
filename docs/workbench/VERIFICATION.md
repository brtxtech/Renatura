# Verification — workflow-only revision

- 13 backend tests passed.
- JavaScript syntax and Python compilation passed.
- Integration: a schema-checked reference with 1 valid and 3 invalid elements becomes partial_ready; it creates no dataset before explicit population.
- Explicit population commits 1 valid element, not the 3 invalid ones.
- Category target can change before population; repeat population is blocked.
- Individual stored records and complete datasets can move to Trash and be restored.
- Stale record removal is rejected; restoration protects newer dataset edits.
- Mismatched JSON uploaded to a GeoJSON box becomes blocked and cannot be populated.
- Existing missing-data, weighted-coverage, spatial calculation, revision, worker, cancellation and token tests continue to pass.

Synthetic demo uploads used during browser QA are not included in the source archive. Original regional geometries are not bundled. Actual deployment users must import source data or retain their existing runtime directory.
