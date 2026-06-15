"""The tool registry: import-time discovery + runtime hot-loading.

* Built-in tools are discovered by importing :mod:`scion.tools.builtins` and
  scanning every module for functions carrying a ``_scion_tool`` marker (the
  Hermes "drop a file in, it registers itself" pattern).
* Authored tools are *hot-loaded by path* from ``authored_tools/`` so a tool the
  agent just wrote becomes callable immediately and is version-controllable
  (Voyager's portable skill folder).
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path

from scion.logging import get_logger
from scion.tools.base import Tool

log = get_logger("tools.registry")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # ---- core ops --------------------------------------------------------- #
    def register(self, t: Tool, *, overwrite: bool = True) -> None:
        if t.name in self._tools and not overwrite:
            return
        self._tools[t.name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def anthropic_tools(self) -> list[dict]:
        """All tools as Anthropic tool definitions (stable, sorted order = cache-friendly)."""
        return [t.to_anthropic() for t in sorted(self._tools.values(), key=lambda x: x.name)]

    # ---- discovery -------------------------------------------------------- #
    def discover_package(self, package_name: str = "scion.tools.builtins") -> int:
        """Import every submodule of *package_name* and register its tools."""
        count = 0
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("could not import %s: %s", package_name, exc)
            return 0
        for mod_info in pkgutil.iter_modules(package.__path__):
            full = f"{package_name}.{mod_info.name}"
            try:
                module = importlib.import_module(full)
            except Exception as exc:
                log.error("skipping %s (import error: %s)", full, exc)
                continue
            count += self._register_from_module(module, source="builtin")
            # optional explicit hook for tools that need custom wiring
            hook = getattr(module, "register", None)
            if callable(hook):
                try:
                    hook(self)
                except Exception as exc:
                    log.error("register() hook failed in %s: %s", full, exc)
        return count

    def load_path(self, path: Path, source: str = "authored") -> list[Tool]:
        """Hot-load a single ``.py`` file and register the tools it defines."""
        path = Path(path)
        mod_name = f"scion_authored_{path.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        found: list[Tool] = []
        for attr in vars(module).values():
            marker = getattr(attr, "_scion_tool", None)
            if isinstance(marker, Tool):
                marker.source = source
                self.register(marker)
                found.append(marker)
        return found

    def discover_dir(self, directory: Path, source: str = "authored") -> int:
        """Hot-load every ``*.py`` in *directory* (non-underscore)."""
        directory = Path(directory)
        if not directory.exists():
            return 0
        count = 0
        for py in sorted(directory.glob("*.py")):
            if py.name.startswith("_"):
                continue
            try:
                found = self.load_path(py, source=source)
                count += len(found)
                if found:
                    log.info("loaded %d tool(s) from %s", len(found), py.name)
            except Exception as exc:
                log.error("failed to load authored tool %s: %s", py.name, exc)
        return count

    def _register_from_module(self, module, source: str) -> int:
        count = 0
        for attr in vars(module).values():
            marker = getattr(attr, "_scion_tool", None)
            if isinstance(marker, Tool):
                marker.source = source
                self.register(marker)
                count += 1
        return count


_REGISTRY: ToolRegistry | None = None


def get_registry(*, fresh: bool = False) -> ToolRegistry:
    """Return the process-wide registry, building it on first use.

    Loads built-ins, then authored tools from ``authored_tools/``.
    """
    global _REGISTRY
    if _REGISTRY is not None and not fresh:
        return _REGISTRY
    from scion.config import get_settings

    reg = ToolRegistry()
    reg.discover_package("scion.tools.builtins")
    settings = get_settings()
    reg.discover_dir(settings.authored_tools_dir, source="authored")
    _REGISTRY = reg
    log.info("registry ready: %d tools (%s)", len(reg), ", ".join(reg.names()))
    return reg
