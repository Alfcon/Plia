#!/usr/bin/env python3
"""Train a custom openWakeWord model from synthetic Piper TTS speech.

Pipeline:
  1. Generate N synthetic positive samples of the target word using Piper
     with multiple voices, speaking rates, and small pitch perturbations.
  2. Use openWakeWord's built-in negative dataset (downloaded on first run)
     for hard negatives, RIRs, and general speech.
  3. Train a binary classifier with openwakeword.train.train_model.
  4. Export to ONNX.

Usage:
  python scripts/train_wake_word.py --word "plia" \
      --output models/wake/bundled/plia.onnx \
      --variants 5000
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

VOICES = [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-libritts-high",
    "en_GB-alba-medium",
    "en_GB-northern_english_male-medium",
]
RATES = [0.85, 1.0, 1.15, 1.3]
DEFAULT_VARIANTS = 5000


def synthesize_positives(word: str, out_dir: Path, variants: int) -> None:
    """Render `variants` WAV files of `word` to out_dir using Piper."""
    try:
        from piper.voice import PiperVoice
    except ImportError as exc:
        sys.exit(
            f"piper-tts is required for training: {exc}\n"
            f"Install with: pip install -r requirements-train.txt"
        )
    import random
    import wave

    out_dir.mkdir(parents=True, exist_ok=True)
    voices = {v: PiperVoice.load(v) for v in VOICES}
    print(f"Generating {variants} synthetic positives for '{word}'…")
    for i in range(variants):
        v = random.choice(VOICES)
        rate = random.choice(RATES)
        wav_path = out_dir / f"{i:05d}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            voices[v].synthesize(word, wf, length_scale=rate)
        if i % 250 == 0:
            print(f"  {i}/{variants}")


def train(word: str, output_onnx: Path, variants: int) -> None:
    try:
        from openwakeword.train import collect_neg_features, train_model
    except ImportError as exc:
        sys.exit(
            f"openwakeword's training helpers are required: {exc}\n"
            f"Install with: pip install -r requirements-train.txt"
        )

    with tempfile.TemporaryDirectory(prefix=f"oww_{word}_") as workdir:
        work = Path(workdir)
        positives = work / "positives"
        synthesize_positives(word, positives, variants)

        print("Collecting / downloading negative features "
              "(this may take a few minutes the first time)…")
        negative_features = collect_neg_features()

        print("Training model…")
        output_onnx.parent.mkdir(parents=True, exist_ok=True)
        train_model(
            positive_audio_dir=str(positives),
            negative_features=negative_features,
            output_path=str(output_onnx),
            wake_word=word,
        )
        print(f"Wrote {output_onnx}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--word", required=True,
                        help="Target wake phrase (e.g. 'plia')")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output .onnx path")
    parser.add_argument("--variants", type=int, default=DEFAULT_VARIANTS,
                        help=f"Number of synthetic positives "
                             f"(default {DEFAULT_VARIANTS})")
    args = parser.parse_args()

    if args.output.suffix != ".onnx":
        sys.exit("--output must end in .onnx")
    train(args.word, args.output, args.variants)
    return 0


if __name__ == "__main__":
    sys.exit(main())
