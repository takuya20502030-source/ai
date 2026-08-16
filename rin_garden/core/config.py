"""YAML設定の読み込みとパス解決。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_system_config(root: Path | None = None) -> dict[str, Any]:
    root = root or PROJECT_ROOT
    return load_yaml(root / "config" / "system.yaml")


def load_sport_config(sport: str, root: Path | None = None) -> dict[str, Any]:
    root = root or PROJECT_ROOT
    return load_yaml(root / "config" / f"{sport}.yaml")


def resolve_paths(system_config: dict[str, Any], root: Path | None = None) -> dict[str, Path]:
    root = root or PROJECT_ROOT
    paths = system_config.get("paths", {})
    return {key: (root / value) for key, value in paths.items()}
