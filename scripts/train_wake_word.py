#!/usr/bin/env python3
"""Pointer script — Plia trains custom wake words via openWakeWord's notebook.

openWakeWord ≥ 0.6 does not expose a stable Python training API; the
official path is the Jupyter / Colab notebook bundled in their repo:

    https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

Steps:

  1. Open the notebook in Google Colab (free GPU runtime) or run it
     locally with Jupyter.
  2. Set the target word (e.g. "plia"), run all cells.
  3. Download the resulting ``<word>.onnx`` artifact.
  4. Drop it into ``models/wake/bundled/`` (for built-ins) or
     ``models/wake/custom/`` (for personal use), or upload it via
     Plia → Settings → Voice & Audio → + Add Model….

This script intentionally has no Python entry point — there is nothing
sensible it could do locally that the notebook doesn't do better.
"""
from __future__ import annotations

import sys


def main() -> int:
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
