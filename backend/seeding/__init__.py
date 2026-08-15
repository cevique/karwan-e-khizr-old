"""
Data/seeding/import tooling for the static transit-network tables
(Agency, Route, Stop, RouteStop).

Submodules:

- `seed` - apply/reset the deterministic demo dataset in `data.seed_dataset`.
- `import_schema` - the normalized, source-agnostic shape external data is
  parsed into (`ImportDataset`) before validation/persistence.
- `parsers` - turn raw JSON or CSV input into an `ImportDataset`. Contains
  all source-format-specific parsing; nothing else in this package knows
  about JSON or CSV syntax.
- `validation` - pure, side-effect-free checks against an `ImportDataset`
  (used for both real imports and dry-run "validate only" requests).
- `importer` - persists a validated `ImportDataset` to the database.

Deliberately does not import anything from `db.session`, `api.*`, or
`routing.*` at package-import time, so this package stays cheap and
side-effect-free to import (e.g. from a standalone script or a test that
only wants the pure validation logic).
"""
