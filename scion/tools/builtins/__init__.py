"""Built-in tools, discovered at import time by the registry.

Each module defines ``@tool``-decorated functions. Drop a new module in here and
its tools register automatically. Keep tools small, well-documented (the docstring
*is* the spec), and honest about risk (the last decorator argument gates them).
"""
