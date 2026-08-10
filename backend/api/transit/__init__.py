"""
Static transit-network API sub-package.

Groups everything for the read-only Agency / Route / Stop API together
(schemas, shared lookup helpers, and the router itself), analogous to how
`db/models/` groups the ORM models it serializes. Kept out of the top-level
`api/router.py` so that file stays a thin aggregator as more feature areas
(tickets, vehicles, users, ...) are added later.
"""
