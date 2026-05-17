"""Wake-word model discovery and reconciliation with settings.

The settings list (`voice.wake_models`) is the source of truth for *enabled*
and *sensitivity*. Discovery is a one-way reconciliation:
  - new files on disk → appended as disabled rows
  - settings rows whose file is missing → flagged broken (not removed)
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_SENSITIVITY = 0.5


def models_dir() -> Path:
    """Absolute path to the project's models/wake/ directory."""
    # core/wake_models.py → parents[1] is the project root.
    return Path(__file__).resolve().parents[1] / "models" / "wake"


def _iter_onnx(base: Path) -> Iterable[tuple[Path, bool]]:
    """Yield (onnx_path, is_builtin) for every .onnx under base/{bundled,custom}/."""
    for subdir, builtin in (("bundled", True), ("custom", False)):
        d = base / subdir
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.onnx")):
            yield path, builtin


def discover_wake_models(base: Path) -> list[dict]:
    """Scan base/{bundled,custom}/*.onnx and return a list of model entries.

    If a custom file shares a stem with a bundled file, the custom entry's
    `id` is suffixed with `_1`, `_2`, … to disambiguate. Bundled wins the
    bare stem.
    """
    entries: list[dict] = []
    seen_ids: set[str] = set()

    # Two passes so bundled keeps the bare stem.
    bundled = [(p, True) for p, b in _iter_onnx(base) if b]
    custom = [(p, False) for p, b in _iter_onnx(base) if not b]

    for path, builtin in bundled + custom:
        stem = path.stem
        candidate = stem
        n = 1
        while candidate in seen_ids:
            candidate = f"{stem}_{n}"
            n += 1
        seen_ids.add(candidate)
        subdir = "bundled" if builtin else "custom"
        entries.append({
            "id": candidate,
            "display": stem.replace("_", " ").title(),
            "path": f"{subdir}/{path.name}",
            "enabled": False,
            "sensitivity": DEFAULT_SENSITIVITY,
            "builtin": builtin,
        })
    return entries


def reconcile_with_settings(existing: list[dict], base: Path) -> list[dict]:
    """Merge disk-discovered models with the settings list.

    - Files on disk not in settings → appended as disabled.
    - Settings rows whose path is missing on disk → `broken: True`.
    - Settings rows whose path exists → `broken` cleared if previously set.
    """
    out = [m.copy() for m in existing]
    by_path = {m["path"]: m for m in out}

    discovered = discover_wake_models(base)

    for m in out:
        full = base / m["path"]
        if full.exists():
            if m.get("broken"):
                m.pop("broken", None)
        else:
            m["broken"] = True

    # Track which entries came from settings (anchored — never rename) vs newly
    # discovered. We use object identity since multiple entries can share an id
    # during the dedupe window.
    anchored_ids = {m["id"] for m in out}
    seen_ids: set[str] = set(anchored_ids)
    new_entries: list[dict] = []
    for d in discovered:
        if d["path"] not in by_path:
            new_entries.append(d)

    for entry in new_entries:
        stem = Path(entry["path"]).stem
        candidate = entry["id"]
        n = 1
        while candidate in seen_ids:
            candidate = f"{stem}_{n}"
            n += 1
        entry["id"] = candidate
        seen_ids.add(candidate)
        out.append(entry)

    return out
