#!/usr/bin/env python3
"""CLI shim around core.wake_trainer.train_wake_word.

For most users the in-app paths (Settings → Voice & Audio → + Train Model…,
the chat tool ``tool_train_wake_word``, or the wake-word-trainer agent) are
easier. This script exists for headless / scripted use.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--word", required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--variants", type=int, default=5000)
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()

    from core.wake_trainer import train_wake_word, WakeTrainerError
    try:
        path = train_wake_word(
            args.word,
            variants=args.variants,
            epochs=args.epochs,
            output_dir=args.output,
            on_progress=lambda pct, msg: print(f"[{pct:5.1f}%] {msg}"),
        )
    except WakeTrainerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
