from __future__ import annotations

import importlib.util
import inspect
import sys
from uuid import uuid4
import tomllib
from pathlib import Path
from typing import Any

from xbot.core.exceptions import PluginLoadError
from xbot.plugins.manifest import PluginManifest


class PluginLoader:
    def load_manifest(self, plugin_dir: Path) -> PluginManifest:
        manifest_path = plugin_dir / "plugin.toml"
        if not manifest_path.exists():
            raise PluginLoadError(f"Missing plugin manifest: {manifest_path}")
        with manifest_path.open("rb") as fh:
            return PluginManifest.model_validate(tomllib.load(fh))

    def load_instance(self, plugin_dir: Path, manifest: PluginManifest) -> Any:
        module_name, _, attr = manifest.entry.partition(":")
        if not module_name or not attr:
            raise PluginLoadError(f"Invalid plugin entry: {manifest.entry}")
        module_path = plugin_dir / f"{module_name}.py"
        importlib.invalidate_caches()
        module_key = f"xbot_plugin_{manifest.name}_{uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_key, module_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot load plugin module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        try:
            spec.loader.exec_module(module)
            cls = getattr(module, attr)
            return cls() if inspect.isclass(cls) else cls
        finally:
            sys.modules.pop(module_key, None)
