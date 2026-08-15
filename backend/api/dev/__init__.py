"""
Development API: read-only inspection and dry-run validation. Unlike
`api/admin/`, nothing here mutates the database - still not registered on
the main application (see `router.py`'s module docstring), out of an
abundance of caution rather than necessity.
"""
