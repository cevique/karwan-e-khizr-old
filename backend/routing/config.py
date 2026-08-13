"""
Shared routing configuration constants.

Centralizes routing-wide values that more than one part of the routing
engine depends on, or that are inherently "policy" decisions worth having
in one obvious, easy-to-find place. This is deliberately NOT a home for
every routing constant: `routing.graph.WALKING_RADIUS_M`,
`routing.providers.WALKING_SPEED_KMH`,
`routing.ride_time.AVERAGE_BUS_SPEED_KMH`, and
`routing.snapping.DEFAULT_MAX_WALK_M`/`MAX_SNAP_CANDIDATES` each still live
beside their single, specific consumer and haven't (yet) needed a shared
home - see `routing.graph.WALKING_RADIUS_M`'s own docstring for the same
"move it once it's genuinely shared" principle this module follows.

`TRANSFER_PENALTY_S` moved here from `routing.search` now that it's used
by more than one routing objective's edge-cost function (Step 6's
`fastest` and `fewest_transfers` - see `routing.search`), even though only
`fastest` uses this specific value; `fewest_transfers` shares the same
transfer-*detection* logic (`routing.search._is_transfer`) without needing
the penalty's numeric value itself.
"""

from __future__ import annotations

# Fixed friction penalty applied when a path switches from one Route to a
# different Route (same-stop or walk-mediated - see
# `routing.search._is_transfer`). **New assumption, not yet in
# README.md**, approved as the current MVP placeholder: 4 minutes,
# representing wait/alighting/boarding friction at the new route, not
# sourced from Karwan-e-Khizr-specific data (none exists yet).
TRANSFER_PENALTY_S = 240.0
