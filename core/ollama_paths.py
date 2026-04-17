"""
core/ollama_paths.py — single source of truth for Ollama storage locations.

Why this exists
---------------
When Plia calls ``POST /api/pull``, the running Ollama daemon writes blobs and
manifests into whichever directory it resolved for ``OLLAMA_MODELS`` at the
moment *it* was started. If Plia and the user's terminal see different values
for ``OLLAMA_MODELS`` — or if the daemon is running with a stale value — the
user can pull a model from the Plia Model Browser and then find that
``ollama list`` in a shell does not show it, because the two are effectively
talking past each other.

This module resolves the canonical directory the same way Ollama itself does
(see: Ollama FAQ → "How can I change where Ollama stores models?",
https://ollama.readthedocs.io/en/faq/) and exposes helpers that:

  * Return the resolved OLLAMA_MODELS directory.
  * Scan that directory's manifests/ tree for installed models.
  * Hit ``GET /api/tags`` on the running daemon for the authoritative list.
  * Compare the two and report any mismatch (i.e. wrong daemon / stale env).

Nothing in this module imports heavy dependencies — pure stdlib + requests.
"""

from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


# ---------------------------------------------------------------------------
# Resolving the OLLAMA_MODELS directory
# ---------------------------------------------------------------------------
def default_ollama_models_dir() -> Path:
    """
    Return the platform-default Ollama models directory when OLLAMA_MODELS is
    not set. Mirrors Ollama's own defaults per the official FAQ:

        macOS:   ~/.ollama/models
        Linux:   /usr/share/ollama/.ollama/models  (systemd service default)
                 or ~/.ollama/models               (user install)
        Windows: %USERPROFILE%\\.ollama\\models
    """
    home = Path.home()
    system = platform.system()

    if system == "Windows":
        return home / ".ollama" / "models"
    if system == "Darwin":
        return home / ".ollama" / "models"

    # Linux: prefer the per-user default. Callers that want the systemd path
    # can set OLLAMA_MODELS explicitly.
    return home / ".ollama" / "models"


def resolve_ollama_models_dir() -> Path:
    """
    Return the directory the running Ollama daemon *should* be writing to,
    based on the ``OLLAMA_MODELS`` environment variable, falling back to the
    platform default.

    This resolves the path but does not guarantee it exists — the daemon
    creates it on first pull. Use :func:`ollama_storage_exists` to check.
    """
    env_val = os.environ.get("OLLAMA_MODELS", "").strip()
    if env_val:
        return Path(env_val).expanduser()
    return default_ollama_models_dir()


def ollama_storage_exists() -> bool:
    """True if the resolved models directory exists on disk."""
    return resolve_ollama_models_dir().is_dir()


# ---------------------------------------------------------------------------
# Resolving the Ollama daemon URL
# ---------------------------------------------------------------------------
def resolve_ollama_host() -> str:
    """
    Return the base URL (no ``/api`` suffix) the Ollama daemon is listening on.

    Honours the ``OLLAMA_HOST`` env var the same way the ``ollama`` CLI does.
    ``OLLAMA_HOST`` may be in any of these forms:

        "127.0.0.1"          -> http://127.0.0.1:11434
        "127.0.0.1:11500"    -> http://127.0.0.1:11500
        "http://host:11434"  -> http://host:11434
        "https://host"       -> https://host:11434

    Falls back to ``http://localhost:11434`` when the variable is absent.
    """
    raw = os.environ.get("OLLAMA_HOST", "").strip()
    if not raw:
        return "http://localhost:11434"

    # Already fully-qualified
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")

    # host[:port] form
    if ":" in raw:
        return f"http://{raw}"
    return f"http://{raw}:11434"


# ---------------------------------------------------------------------------
# Scanning the on-disk manifests tree
# ---------------------------------------------------------------------------
_MANIFEST_REGISTRY = "registry.ollama.ai"


def scan_installed_from_disk() -> Dict[str, Path]:
    """
    Return ``{model_tag: manifest_path}`` for every model manifest found in the
    resolved ``OLLAMA_MODELS`` directory.

    ``model_tag`` is the same form ``ollama list`` prints, e.g. ``qwen3:1.7b``
    or ``library/llama3.2:latest`` for non-library namespaces. Library models
    are normalised to drop the ``library/`` prefix so matching against
    ``/api/tags`` names works directly.

    Works offline — does not contact the daemon.
    """
    root = resolve_ollama_models_dir() / "manifests" / _MANIFEST_REGISTRY
    if not root.is_dir():
        return {}

    results: Dict[str, Path] = {}
    # Layout:  manifests/registry.ollama.ai/<namespace>/<model>/<tag>
    # For library models the namespace is literally "library".
    for namespace_dir in root.iterdir():
        if not namespace_dir.is_dir():
            continue
        for model_dir in namespace_dir.iterdir():
            if not model_dir.is_dir():
                continue
            for tag_file in model_dir.iterdir():
                if not tag_file.is_file():
                    continue
                model_name = model_dir.name
                tag = tag_file.name
                if namespace_dir.name == "library":
                    full = f"{model_name}:{tag}"
                else:
                    full = f"{namespace_dir.name}/{model_name}:{tag}"
                results[full] = tag_file
    return results


# ---------------------------------------------------------------------------
# Hitting the daemon
# ---------------------------------------------------------------------------
def list_installed_from_api(
    base_url: Optional[str] = None,
    timeout: float = 3.0,
) -> Optional[List[str]]:
    """
    Call ``GET {base_url}/api/tags`` and return a list of model names
    (``["qwen3:1.7b", "llama3.2:latest", ...]``).

    Returns ``None`` if the daemon is unreachable — lets the caller distinguish
    "daemon down" from "daemon has zero models".
    """
    url_base = base_url or resolve_ollama_host()
    try:
        resp = requests.get(f"{url_base}/api/tags", timeout=timeout)
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None

    models = payload.get("models", []) or []
    return [m.get("name", "") for m in models if m.get("name")]


# ---------------------------------------------------------------------------
# Post-pull verification — the key helper
# ---------------------------------------------------------------------------
def _base_tag(name: str) -> str:
    """Strip the ``:tag`` portion; ``qwen3:1.7b`` -> ``qwen3``."""
    return name.split(":", 1)[0] if ":" in name else name


def verify_model_visible(
    model_name: str,
    base_url: Optional[str] = None,
    timeout: float = 3.0,
) -> Tuple[bool, str]:
    """
    After a pull, confirm that ``model_name`` now appears in
    ``GET /api/tags`` on the *same* daemon Plia talked to.

    Returns ``(ok, message)``.

    * ``ok=True``  → the model is visible and ``ollama list`` will show it
    * ``ok=False`` → caller should surface the message to the user

    Matches both the exact tag and base-name-only (``qwen3`` will match
    ``qwen3:latest`` and vice versa) because Ollama sometimes normalises tags.
    """
    api_list = list_installed_from_api(base_url=base_url, timeout=timeout)
    if api_list is None:
        return False, (
            "Ollama daemon is not reachable at "
            f"{base_url or resolve_ollama_host()}. "
            "The model was requested but cannot be verified."
        )

    if model_name in api_list:
        return True, f"{model_name} is registered with the Ollama daemon."

    wanted_base = _base_tag(model_name)
    for existing in api_list:
        if existing == model_name:
            return True, f"{model_name} is registered with the Ollama daemon."
        if _base_tag(existing) == wanted_base:
            return True, (
                f"{model_name} is registered as '{existing}' "
                "(Ollama resolved to a matching tag)."
            )

    return False, (
        f"Pull reported success but '{model_name}' is NOT in the daemon's "
        f"model list. This usually means Plia and your shell are talking to "
        f"different Ollama daemons. Check that OLLAMA_HOST is consistent."
    )


# ---------------------------------------------------------------------------
# Alignment diagnostic — surfaces config mismatches
# ---------------------------------------------------------------------------
def diagnose_alignment(base_url: Optional[str] = None) -> Dict[str, object]:
    """
    Return a dict describing the Plia ↔ Ollama alignment. Intended to be
    printed to logs on startup or shown in the Model Browser footer so the
    user can see at a glance whether pulls will round-trip into
    ``ollama list``.

    Keys in the returned dict:
        host                - URL Plia will call
        models_dir          - resolved OLLAMA_MODELS path
        models_dir_exists   - does the directory exist?
        daemon_reachable    - did /api/tags respond?
        api_model_count     - models seen by the daemon (None if unreachable)
        disk_model_count    - models seen on disk (manifests)
        matches             - True if api_model_count == disk_model_count
    """
    host = base_url or resolve_ollama_host()
    models_dir = resolve_ollama_models_dir()
    api_list = list_installed_from_api(base_url=host)
    disk_map = scan_installed_from_disk()

    api_count = len(api_list) if api_list is not None else None
    disk_count = len(disk_map)

    return {
        "host": host,
        "models_dir": str(models_dir),
        "models_dir_exists": models_dir.is_dir(),
        "daemon_reachable": api_list is not None,
        "api_model_count": api_count,
        "disk_model_count": disk_count,
        "matches": (api_count is not None and api_count == disk_count),
    }
