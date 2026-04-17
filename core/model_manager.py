"""
Model Manager — utilities for loading, unloading, and verifying Ollama models.

Public API (unchanged from the original — callers are not affected):
    sync_unload_model(name)
    unload_model(name)
    unload_all_models(sync=False)
    get_running_models() -> list
    ensure_exclusive_qwen(target)

New in this revision:
    verify_model_downloaded(name) -> (bool, str)
        Confirms a freshly-pulled model is actually visible to the daemon so
        ``ollama list`` in a shell will show it. Call this *immediately after*
        a successful ``POST /api/pull`` response in the Model Browser.

    get_ollama_api_url() -> str
        Returns the ``{host}/api`` URL the way the Ollama CLI resolves it,
        honouring ``OLLAMA_HOST``. Used internally so env changes take effect
        without restarting Plia.
"""

from __future__ import annotations

import threading
from typing import Tuple

import requests

from config import OLLAMA_URL, GRAY, RESET
from core.ollama_paths import (
    resolve_ollama_host,
    verify_model_visible,
)


# ---------------------------------------------------------------------------
# Internal URL resolution — prefer the env-aware helper, fall back to config
# ---------------------------------------------------------------------------
def get_ollama_api_url() -> str:
    """
    Return ``{host}/api`` honouring the ``OLLAMA_HOST`` env var.

    Falls back to the ``OLLAMA_URL`` constant from ``config.py`` when the env
    var is unset, so existing behaviour is preserved for users who have not
    configured ``OLLAMA_HOST``.
    """
    # If OLLAMA_HOST is explicitly set, it wins. Otherwise stick with config.
    import os
    if os.environ.get("OLLAMA_HOST", "").strip():
        return f"{resolve_ollama_host()}/api"
    return OLLAMA_URL


def _api(path: str) -> str:
    """Build a full endpoint URL. ``path`` must start with ``/``."""
    return f"{get_ollama_api_url()}{path}"


# ---------------------------------------------------------------------------
# Unload helpers (unchanged public behaviour)
# ---------------------------------------------------------------------------
def sync_unload_model(model_name: str) -> None:
    """Synchronously unload a model from Ollama by setting keep_alive=0."""
    try:
        response = requests.post(
            _api("/generate"),
            json={
                "model": model_name,
                "prompt": "",
                "keep_alive": 0,   # immediately unload
            },
            timeout=5,
        )
        if response.status_code == 200:
            print(f"{GRAY}[ModelManager] Unloaded model: {model_name}{RESET}")
        else:
            print(
                f"{GRAY}[ModelManager] Failed to unload {model_name}: "
                f"{response.status_code}{RESET}"
            )
    except Exception as e:
        print(f"{GRAY}[ModelManager] Error unloading {model_name}: {e}{RESET}")


def unload_model(model_name: str) -> None:
    """Unload a model from Ollama asynchronously (does not block the UI)."""
    threading.Thread(
        target=sync_unload_model, args=(model_name,), daemon=True
    ).start()


def unload_all_models(sync: bool = False) -> None:
    """Unload every model currently loaded in Ollama."""
    try:
        response = requests.get(_api("/ps"), timeout=2)
        if response.status_code == 200:
            data = response.json()
            for model in data.get("models", []):
                model_name = model.get("name", "")
                if not model_name:
                    continue
                if sync:
                    sync_unload_model(model_name)
                else:
                    unload_model(model_name)
    except Exception as e:
        print(f"{GRAY}[ModelManager] Error getting running models: {e}{RESET}")


def get_running_models() -> list:
    """Return a list of currently-loaded model names (``/api/ps`` names)."""
    try:
        response = requests.get(_api("/ps"), timeout=2)
        if response.status_code == 200:
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass
    return []


def ensure_exclusive_qwen(target_model: str) -> None:
    """
    Unload every Qwen model that is NOT ``target_model`` — useful for VRAM-
    constrained systems that run one model at a time.
    """
    try:
        running = get_running_models()
        to_unload = [
            m for m in running
            if "qwen" in m.lower()
            and m != target_model
            and not target_model.startswith(m)
        ]
        for m in to_unload:
            unload_model(m)
    except Exception as e:
        print(f"{GRAY}[ModelManager] Error in exclusion logic: {e}{RESET}")


# ---------------------------------------------------------------------------
# NEW: post-pull verification
# ---------------------------------------------------------------------------
def verify_model_downloaded(model_name: str) -> Tuple[bool, str]:
    """
    Confirm that ``model_name`` was registered with the running Ollama daemon.

    Intended to be called *immediately after* a successful
    ``POST /api/pull`` so the Model Browser can display a clear error if the
    model will not show up in ``ollama list`` (typically a daemon-mismatch
    problem rather than a pull failure).

    Returns ``(ok, human_readable_message)``.

    Example
    -------
    After ``OllamaDownloadThread`` emits ``finished_ok``::

        ok, msg = verify_model_downloaded(name)
        if not ok:
            InfoBar.warning(title="Verification failed",
                            content=msg, ...)

    See :func:`core.ollama_paths.verify_model_visible` for details.
    """
    # Re-use the same base URL resolution the pull call uses so there is no
    # chance of checking a different daemon than we just pulled to.
    base = get_ollama_api_url().rsplit("/api", 1)[0]
    return verify_model_visible(model_name, base_url=base, timeout=5.0)
