"""
Route planning engine: graph construction and search.

See README.md §13 "Route Planning Architecture" for the design this module
implements, and §10 "Backend Architecture" for why `routing` is its own
top-level module (never imports from `payments`/`ticketing`/etc., and is
never imported by the realtime/vehicle-tracking modules - route planning
stays deterministic and independent of live GPS, simulated or official).

Only graph construction (`graph.py`) exists so far. Search (Dijkstra),
origin/destination snapping, walking/time-estimation providers, journey
(leg) reconstruction, and the HTTP endpoint are later, separate steps.
"""
