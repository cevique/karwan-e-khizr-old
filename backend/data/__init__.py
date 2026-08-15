"""
Development data package: the deterministic demo transit dataset used by
`seeding.seed` to populate a local database for the hackathon demo.

Kept separate from `seeding/` (which contains the *behavior* - how to
apply a dataset to the database, validate it, or import an external one)
so the dataset definition itself (`seed_dataset.py`) stays a plain,
side-effect-free data file that's easy to read, diff, and extend.
"""
