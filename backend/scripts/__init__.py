"""
Standalone dev-tooling scripts. Run from the `backend/` directory (same
convention as `alembic` and `uvicorn` in this project) so `core.config`,
`db.*`, `data.*`, and `seeding.*` import exactly as they do for the rest
of the application:

    python scripts/seed_dev_db.py --help
    python scripts/verify_graph_buildable.py

See `backend/data/README.md` for what each script does and when to use
the admin HTTP API instead.
"""
