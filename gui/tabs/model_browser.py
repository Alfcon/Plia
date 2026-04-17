"""
Model Browser — hardware-aware LLM model browser powered by llmfit data.

Shows models from https://github.com/AlexsJones/llmfit (MIT licence)
scored against the user's actual RAM, VRAM, and CPU.
Falls back to a built-in model list if GitHub is unreachable.
"""

import json
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psutil
import requests

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QBrush

from qfluentwidgets import (
    TitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    PushButton, PrimaryPushButton, LineEdit, ComboBox,
    FluentIcon as FIF, CardWidget, InfoBar, InfoBarPosition,
)

from config import OLLAMA_URL

# ---------------------------------------------------------------------------
# Remote DB + local cache settings
# ---------------------------------------------------------------------------
LLMFIT_DB_URL = (
    "https://raw.githubusercontent.com/AlexsJones/llmfit/main/data/hf_models.json"
)
CACHE_PATH = Path.home() / ".plia" / "llmfit_models.json"
CACHE_TTL  = timedelta(days=7)

# ---------------------------------------------------------------------------
# Embedded fallback model list — always shown if GitHub unreachable
# Schema: name, provider, parameter_count, min_ram_gb, recommended_ram_gb,
#         min_vram_gb, quantization, context_length, use_case
# ---------------------------------------------------------------------------
FALLBACK_MODELS = [
    {"name":"Qwen/Qwen2.5-0.5B-Instruct","provider":"Qwen","parameter_count":"0.5B","min_ram_gb":0.4,"recommended_ram_gb":0.8,"min_vram_gb":0.4,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-1.5B-Instruct","provider":"Qwen","parameter_count":"1.5B","min_ram_gb":1.0,"recommended_ram_gb":2.0,"min_vram_gb":0.9,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-3B-Instruct","provider":"Qwen","parameter_count":"3B","min_ram_gb":2.0,"recommended_ram_gb":4.0,"min_vram_gb":1.8,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-7B-Instruct","provider":"Qwen","parameter_count":"7.6B","min_ram_gb":4.7,"recommended_ram_gb":9.4,"min_vram_gb":4.2,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-14B-Instruct","provider":"Qwen","parameter_count":"14.8B","min_ram_gb":9.1,"recommended_ram_gb":18.2,"min_vram_gb":8.2,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-32B-Instruct","provider":"Qwen","parameter_count":"32B","min_ram_gb":19.7,"recommended_ram_gb":39.4,"min_vram_gb":17.8,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen2.5-72B-Instruct","provider":"Qwen","parameter_count":"72B","min_ram_gb":44.3,"recommended_ram_gb":88.6,"min_vram_gb":40.0,"quantization":"Q4_K_M","context_length":32768,"use_case":"Chat"},
    {"name":"Qwen/Qwen3-0.6B","provider":"Qwen","parameter_count":"0.6B","min_ram_gb":0.4,"recommended_ram_gb":0.8,"min_vram_gb":0.4,"quantization":"Q4_K_M","context_length":32768,"use_case":"General"},
    {"name":"Qwen/Qwen3-1.7B","provider":"Qwen","parameter_count":"1.7B","min_ram_gb":1.1,"recommended_ram_gb":2.2,"min_vram_gb":1.0,"quantization":"Q4_K_M","context_length":32768,"use_case":"General"},
    {"name":"Qwen/Qwen3-4B","provider":"Qwen","parameter_count":"4B","min_ram_gb":2.5,"recommended_ram_gb":5.0,"min_vram_gb":2.3,"quantization":"Q4_K_M","context_length":32768,"use_case":"General"},
    {"name":"Qwen/Qwen3-8B","provider":"Qwen","parameter_count":"8B","min_ram_gb":4.9,"recommended_ram_gb":9.8,"min_vram_gb":4.4,"quantization":"Q4_K_M","context_length":32768,"use_case":"General"},
    {"name":"Qwen/Qwen3-14B","provider":"Qwen","parameter_count":"14B","min_ram_gb":8.6,"recommended_ram_gb":17.2,"min_vram_gb":7.8,"quantization":"Q4_K_M","context_length":32768,"use_case":"Reasoning"},
    {"name":"Qwen/Qwen3-32B","provider":"Qwen","parameter_count":"32B","min_ram_gb":19.7,"recommended_ram_gb":39.4,"min_vram_gb":17.8,"quantization":"Q4_K_M","context_length":32768,"use_case":"Reasoning"},
    {"name":"Qwen/Qwen2.5-Coder-1.5B-Instruct","provider":"Qwen","parameter_count":"1.5B","min_ram_gb":1.0,"recommended_ram_gb":2.0,"min_vram_gb":0.9,"quantization":"Q4_K_M","context_length":32768,"use_case":"Coding"},
    {"name":"Qwen/Qwen2.5-Coder-7B-Instruct","provider":"Qwen","parameter_count":"7.6B","min_ram_gb":4.7,"recommended_ram_gb":9.4,"min_vram_gb":4.2,"quantization":"Q4_K_M","context_length":32768,"use_case":"Coding"},
    {"name":"Qwen/Qwen2.5-Coder-14B-Instruct","provider":"Qwen","parameter_count":"14.8B","min_ram_gb":9.1,"recommended_ram_gb":18.2,"min_vram_gb":8.2,"quantization":"Q4_K_M","context_length":32768,"use_case":"Coding"},
    {"name":"Qwen/Qwen2.5-Coder-32B-Instruct","provider":"Qwen","parameter_count":"32B","min_ram_gb":19.7,"recommended_ram_gb":39.4,"min_vram_gb":17.8,"quantization":"Q4_K_M","context_length":32768,"use_case":"Coding"},
    {"name":"meta-llama/Llama-3.2-1B-Instruct","provider":"Meta","parameter_count":"1.2B","min_ram_gb":0.8,"recommended_ram_gb":1.6,"min_vram_gb":0.7,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"meta-llama/Llama-3.2-3B-Instruct","provider":"Meta","parameter_count":"3.2B","min_ram_gb":2.0,"recommended_ram_gb":4.0,"min_vram_gb":1.8,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"meta-llama/Llama-3.1-8B-Instruct","provider":"Meta","parameter_count":"8B","min_ram_gb":4.9,"recommended_ram_gb":9.8,"min_vram_gb":4.4,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"meta-llama/Llama-3.1-70B-Instruct","provider":"Meta","parameter_count":"70B","min_ram_gb":43.1,"recommended_ram_gb":86.2,"min_vram_gb":38.9,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"meta-llama/Llama-3.3-70B-Instruct","provider":"Meta","parameter_count":"70B","min_ram_gb":43.1,"recommended_ram_gb":86.2,"min_vram_gb":38.9,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"mistralai/Mistral-7B-Instruct-v0.3","provider":"Mistral","parameter_count":"7.2B","min_ram_gb":4.4,"recommended_ram_gb":8.8,"min_vram_gb":4.0,"quantization":"Q4_K_M","context_length":32768,"use_case":"General"},
    {"name":"mistralai/Mistral-Nemo-Instruct-2407","provider":"Mistral","parameter_count":"12B","min_ram_gb":7.4,"recommended_ram_gb":14.8,"min_vram_gb":6.7,"quantization":"Q4_K_M","context_length":128000,"use_case":"General"},
    {"name":"mistralai/Mixtral-8x7B-Instruct-v0.1","provider":"Mistral","parameter_count":"46.7B","min_ram_gb":6.7,"recommended_ram_gb":13.4,"min_vram_gb":6.1,"quantization":"Q4_K_M","context_length":32768,"use_case":"General","is_moe":True},
    {"name":"microsoft/Phi-3.5-mini-instruct","provider":"Microsoft","parameter_count":"3.8B","min_ram_gb":2.3,"recommended_ram_gb":4.6,"min_vram_gb":2.1,"quantization":"Q4_K_M","context_length":128000,"use_case":"General"},
    {"name":"microsoft/Phi-4","provider":"Microsoft","parameter_count":"14B","min_ram_gb":8.6,"recommended_ram_gb":17.2,"min_vram_gb":7.8,"quantization":"Q4_K_M","context_length":16384,"use_case":"Reasoning"},
    {"name":"microsoft/phi-4-mini-instruct","provider":"Microsoft","parameter_count":"3.8B","min_ram_gb":2.3,"recommended_ram_gb":4.6,"min_vram_gb":2.1,"quantization":"Q4_K_M","context_length":16384,"use_case":"Reasoning"},
    {"name":"google/gemma-2-2b-it","provider":"Google","parameter_count":"2.6B","min_ram_gb":1.6,"recommended_ram_gb":3.2,"min_vram_gb":1.4,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"google/gemma-2-9b-it","provider":"Google","parameter_count":"9.2B","min_ram_gb":5.7,"recommended_ram_gb":11.4,"min_vram_gb":5.1,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"google/gemma-2-27b-it","provider":"Google","parameter_count":"27.2B","min_ram_gb":16.7,"recommended_ram_gb":33.4,"min_vram_gb":15.1,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"google/gemma-3-1b-it","provider":"Google","parameter_count":"1B","min_ram_gb":0.6,"recommended_ram_gb":1.2,"min_vram_gb":0.6,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"google/gemma-3-4b-it","provider":"Google","parameter_count":"4B","min_ram_gb":2.5,"recommended_ram_gb":5.0,"min_vram_gb":2.2,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"google/gemma-3-12b-it","provider":"Google","parameter_count":"12B","min_ram_gb":7.4,"recommended_ram_gb":14.8,"min_vram_gb":6.7,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"google/gemma-3-27b-it","provider":"Google","parameter_count":"27B","min_ram_gb":16.6,"recommended_ram_gb":33.2,"min_vram_gb":15.0,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B","provider":"DeepSeek","parameter_count":"1.5B","min_ram_gb":1.0,"recommended_ram_gb":2.0,"min_vram_gb":0.9,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Qwen-7B","provider":"DeepSeek","parameter_count":"7.6B","min_ram_gb":4.7,"recommended_ram_gb":9.4,"min_vram_gb":4.2,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Llama-8B","provider":"DeepSeek","parameter_count":"8B","min_ram_gb":4.9,"recommended_ram_gb":9.8,"min_vram_gb":4.4,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Qwen-14B","provider":"DeepSeek","parameter_count":"14.8B","min_ram_gb":9.1,"recommended_ram_gb":18.2,"min_vram_gb":8.2,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Qwen-32B","provider":"DeepSeek","parameter_count":"32B","min_ram_gb":19.7,"recommended_ram_gb":39.4,"min_vram_gb":17.8,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"deepseek-ai/DeepSeek-R1-Distill-Llama-70B","provider":"DeepSeek","parameter_count":"70B","min_ram_gb":43.1,"recommended_ram_gb":86.2,"min_vram_gb":38.9,"quantization":"Q4_K_M","context_length":131072,"use_case":"Reasoning"},
    {"name":"ibm-granite/granite-3.1-2b-instruct","provider":"IBM","parameter_count":"2B","min_ram_gb":1.2,"recommended_ram_gb":2.4,"min_vram_gb":1.1,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"ibm-granite/granite-3.1-8b-instruct","provider":"IBM","parameter_count":"8B","min_ram_gb":4.9,"recommended_ram_gb":9.8,"min_vram_gb":4.4,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"HuggingFaceTB/SmolLM2-135M-Instruct","provider":"HuggingFace","parameter_count":"135M","min_ram_gb":0.1,"recommended_ram_gb":0.2,"min_vram_gb":0.1,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"HuggingFaceTB/SmolLM2-360M-Instruct","provider":"HuggingFace","parameter_count":"360M","min_ram_gb":0.2,"recommended_ram_gb":0.4,"min_vram_gb":0.2,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"HuggingFaceTB/SmolLM2-1.7B-Instruct","provider":"HuggingFace","parameter_count":"1.7B","min_ram_gb":1.1,"recommended_ram_gb":2.2,"min_vram_gb":1.0,"quantization":"Q4_K_M","context_length":8192,"use_case":"General"},
    {"name":"nomic-ai/nomic-embed-text-v1.5","provider":"Nomic","parameter_count":"137M","min_ram_gb":0.1,"recommended_ram_gb":0.2,"min_vram_gb":0.1,"quantization":"Q8_0","context_length":8192,"use_case":"Embedding"},
    {"name":"allenai/OLMo-2-1124-7B-Instruct","provider":"Allen AI","parameter_count":"7B","min_ram_gb":4.3,"recommended_ram_gb":8.6,"min_vram_gb":3.9,"quantization":"Q4_K_M","context_length":4096,"use_case":"General"},
    {"name":"CohereForAI/c4ai-command-r7b-12-2024","provider":"Cohere","parameter_count":"7B","min_ram_gb":4.3,"recommended_ram_gb":8.6,"min_vram_gb":3.9,"quantization":"Q4_K_M","context_length":131072,"use_case":"General"},
    {"name":"bigcode/starcoder2-7b","provider":"BigCode","parameter_count":"7B","min_ram_gb":4.3,"recommended_ram_gb":8.6,"min_vram_gb":3.9,"quantization":"Q4_K_M","context_length":16384,"use_case":"Coding"},
    {"name":"bigcode/starcoder2-15b","provider":"BigCode","parameter_count":"15B","min_ram_gb":9.2,"recommended_ram_gb":18.4,"min_vram_gb":8.3,"quantization":"Q4_K_M","context_length":16384,"use_case":"Coding"},
]

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Use-case normalisation — maps raw llmfit database strings to the canonical
# labels that populate the "Use Case" combo box filter.  The live
# hf_models.json from GitHub uses verbose strings such as
# "Instruction Following", "Code Generation", "Text Generation", etc.
# Without this step the filter does an exact == match and always returns 0.
# ---------------------------------------------------------------------------
_UC_NORM_MAP = [
    # Order matters: more-specific patterns must come before broader ones.
    ("embed",                "Embedding"),
    ("code",                 "Coding"),
    ("math",                 "Reasoning"),
    ("reason",               "Reasoning"),
    ("instruct",             "Chat"),
    ("chat",                 "Chat"),
    ("conversation",         "Chat"),
    ("multimodal",           "Multimodal"),
    ("vision",               "Multimodal"),
    ("vlm",                  "Multimodal"),
]

def _normalize_use_case(raw: str) -> str:
    """Map an arbitrary use_case string to one of the canonical filter labels."""
    lower = raw.lower().strip()
    for fragment, canonical in _UC_NORM_MAP:
        if fragment in lower:
            return canonical
    return "General"


QUANT_HIERARCHY = ["Q8_0","Q6_K","Q5_K_M","Q4_K_M","Q4_0","Q3_K_M","Q2_K"]
QUANT_BITS      = {"Q8_0":8.0,"Q6_K":6.0,"Q5_K_M":5.0,"Q4_K_M":4.5,"Q4_0":4.0,"Q3_K_M":3.0,"Q2_K":2.0}
BACKEND_SPEED   = {"cuda":220,"metal":160,"rocm":180,"sycl":100,"cpu_arm":90,"cpu_x86":70}
FIT_ORDER       = {"perfect":0,"good":1,"marginal":2,"too_tight":3}
FIT_COLOURS     = {"perfect":"#4caf50","good":"#33b5e5","marginal":"#ffb300","too_tight":"#ef5350"}

# HuggingFace → Ollama name map
OLLAMA_MAP = {
    "Qwen/Qwen2.5-0.5B-Instruct":"qwen2.5:0.5b","Qwen/Qwen2.5-1.5B-Instruct":"qwen2.5:1.5b",
    "Qwen/Qwen2.5-3B-Instruct":"qwen2.5:3b","Qwen/Qwen2.5-7B-Instruct":"qwen2.5:7b",
    "Qwen/Qwen2.5-14B-Instruct":"qwen2.5:14b","Qwen/Qwen2.5-32B-Instruct":"qwen2.5:32b",
    "Qwen/Qwen2.5-72B-Instruct":"qwen2.5:72b",
    "Qwen/Qwen2.5-Coder-1.5B-Instruct":"qwen2.5-coder:1.5b",
    "Qwen/Qwen2.5-Coder-7B-Instruct":"qwen2.5-coder:7b",
    "Qwen/Qwen2.5-Coder-14B-Instruct":"qwen2.5-coder:14b",
    "Qwen/Qwen2.5-Coder-32B-Instruct":"qwen2.5-coder:32b",
    "Qwen/Qwen3-0.6B":"qwen3:0.6b","Qwen/Qwen3-1.7B":"qwen3:1.7b",
    "Qwen/Qwen3-4B":"qwen3:4b","Qwen/Qwen3-8B":"qwen3:8b",
    "Qwen/Qwen3-14B":"qwen3:14b","Qwen/Qwen3-32B":"qwen3:32b",
    "meta-llama/Llama-3.2-1B-Instruct":"llama3.2:1b","meta-llama/Llama-3.2-3B-Instruct":"llama3.2:3b",
    "meta-llama/Llama-3.1-8B-Instruct":"llama3.1:8b","meta-llama/Llama-3.1-70B-Instruct":"llama3.1:70b",
    "meta-llama/Llama-3.3-70B-Instruct":"llama3.3:70b",
    "mistralai/Mistral-7B-Instruct-v0.3":"mistral:7b",
    "mistralai/Mistral-Nemo-Instruct-2407":"mistral-nemo",
    "mistralai/Mixtral-8x7B-Instruct-v0.1":"mixtral:8x7b",
    "microsoft/Phi-3.5-mini-instruct":"phi3.5:3.8b","microsoft/Phi-4":"phi4:14b",
    "microsoft/phi-4-mini-instruct":"phi4-mini:3.8b",
    "google/gemma-2-2b-it":"gemma2:2b","google/gemma-2-9b-it":"gemma2:9b",
    "google/gemma-2-27b-it":"gemma2:27b","google/gemma-3-1b-it":"gemma3:1b",
    "google/gemma-3-4b-it":"gemma3:4b","google/gemma-3-12b-it":"gemma3:12b",
    "google/gemma-3-27b-it":"gemma3:27b",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B":"deepseek-r1:1.5b",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B":"deepseek-r1:7b",
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B":"deepseek-r1:8b",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B":"deepseek-r1:14b",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B":"deepseek-r1:32b",
    "deepseek-ai/DeepSeek-R1-Distill-Llama-70B":"deepseek-r1:70b",
    "deepseek-ai/DeepSeek-V3":"deepseek-v3",
    "ibm-granite/granite-3.1-2b-instruct":"granite3.1-dense:2b",
    "ibm-granite/granite-3.1-8b-instruct":"granite3.1-dense:8b",
    "HuggingFaceTB/SmolLM2-135M-Instruct":"smollm2:135m",
    "HuggingFaceTB/SmolLM2-360M-Instruct":"smollm2:360m",
    "HuggingFaceTB/SmolLM2-1.7B-Instruct":"smollm2:1.7b",
    "nomic-ai/nomic-embed-text-v1.5":"nomic-embed-text",
    "bigcode/starcoder2-7b":"starcoder2:7b","bigcode/starcoder2-15b":"starcoder2:15b",
    "allenai/OLMo-2-1124-7B-Instruct":"olmo2:7b",
}


def _hf_to_ollama(name: str) -> str:
    if name in OLLAMA_MAP:
        return OLLAMA_MAP[name]
    return (name.split("/")[-1] if "/" in name else name).lower().replace("_", "-")


# ---------------------------------------------------------------------------
# Parameter parsing — FIX: handles M/B/T suffixes correctly
# ---------------------------------------------------------------------------
def _parse_params_b(pc: str) -> float:
    s = str(pc).strip().upper()
    m = re.match(r"^([0-9.]+)\s*M$", s)
    if m:
        return float(m.group(1)) / 1000.0
    m = re.match(r"^([0-9.]+)\s*B$", s)
    if m:
        return float(m.group(1))
    m = re.match(r"^([0-9.]+)\s*T$", s)
    if m:
        return float(m.group(1)) * 1000.0
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Hardware detection — FIX: handle pynvml returning bytes for GPU name
# ---------------------------------------------------------------------------
class HardwareInfo:
    def __init__(self):
        self.ram_gb    = 0.0
        self.vram_gb   = 0.0
        self.gpu_name  = "Unknown"
        self.backend   = "cpu_x86"
        self.cpu_cores = 0

    def detect(self) -> "HardwareInfo":
        mem = psutil.virtual_memory()
        self.ram_gb    = round(mem.available / (1024 ** 3), 1)
        self.cpu_cores = psutil.cpu_count(logical=False) or 2

        try:
            import pynvml
            pynvml.nvmlInit()
            h    = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(h)
            self.vram_gb  = round(info.free / (1024 ** 3), 1)
            raw = pynvml.nvmlDeviceGetName(h)
            # FIX: some pynvml versions return bytes, others return str
            self.gpu_name = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            self.backend  = "cuda"
            pynvml.nvmlShutdown()
            return self
        except Exception:
            pass

        try:
            out   = subprocess.check_output(
                ["nvidia-smi","--query-gpu=memory.free,name","--format=csv,noheader,nounits"],
                timeout=4, text=True
            ).strip().split("\n")[0]
            parts = out.split(",")
            self.vram_gb  = round(float(parts[0].strip()) / 1024.0, 1)
            self.gpu_name = parts[1].strip() if len(parts) > 1 else "NVIDIA GPU"
            self.backend  = "cuda"
        except Exception:
            pass

        import platform
        if platform.machine().lower() in ("arm64", "aarch64"):
            self.backend = "cpu_arm"

        return self


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def _qmult(q): return {"Q8_0":0.95,"Q6_K":0.90,"Q5_K_M":0.87,"Q4_K_M":0.85,"Q4_0":0.82,"Q3_K_M":0.75,"Q2_K":0.65}.get(q,0.85)
def _fsz(p, q): return round(p*1e9*QUANT_BITS.get(q,4.5)/8/(1024**3),1)
def _vram(p, q): return round(p*1e9*QUANT_BITS.get(q,4.5)/8/(1024**3)*1.1,1)
def _ram(p, q):  return round(p*1e9*QUANT_BITS.get(q,4.5)/8/(1024**3)*1.2,1)


def score_model(m: dict, hw: HardwareInfo) -> Optional[dict]:
    params_b = m.get("params_b", 0.0) or _parse_params_b(m.get("parameter_count", "0"))
    if params_b <= 0:
        return None

    is_moe   = bool(m.get("is_moe", False))
    use_case = _normalize_use_case(m.get("use_case", "General"))
    ctx_len  = m.get("context_length", 4096)

    best_quant = None
    run_mode   = "cpu"
    mem_req    = 0.0

    for q in QUANT_HIERARCHY:
        vr = _vram(params_b, q) * (0.28 if is_moe else 1.0)
        rr = _ram(params_b, q)
        if hw.vram_gb > 0 and vr <= hw.vram_gb:
            best_quant, run_mode, mem_req = q, "gpu", vr
            break
        elif rr <= hw.ram_gb:
            best_quant = q
            run_mode   = "cpu" if hw.vram_gb == 0 else "cpu+gpu"
            mem_req    = rr
            break

    if best_quant is None:
        return {**m, "use_case": use_case, "params_b":params_b,"best_quant":"—","run_mode":"none",
                "fit_level":"too_tight","fit_label":"Too Tight","score":0.0,
                "estimated_tps":0.0,"memory_required_gb":_ram(params_b,"Q4_K_M"),
                "file_size_gb":_fsz(params_b,"Q4_K_M"),"is_moe":is_moe}

    avail = hw.vram_gb if run_mode == "gpu" else hw.ram_gb
    util  = mem_req / avail if avail > 0 else 1.0

    if   run_mode == "gpu" and 0.5 <= util <= 0.80: fl, flb = "perfect","Perfect"
    elif run_mode == "gpu":                          fl, flb = "good",   "Good"
    elif run_mode == "cpu+gpu":                      fl, flb = "good",   "Good"
    else:                                            fl, flb = "marginal","Marginal"

    tps = BACKEND_SPEED.get(hw.backend, 70) / params_b * _qmult(best_quant)
    if run_mode == "cpu+gpu": tps *= 0.5
    if run_mode == "cpu":     tps *= 0.3
    if is_moe:                tps *= 0.8
    tps = round(tps, 1)

    q_score = min(100.0, 40 + params_b*3.0 - (7 - QUANT_HIERARCHY.index(best_quant))*2)
    s_score = min(100.0, tps*2.0)
    f_score = 100.0 if 0.5<=util<=0.80 else (60+util*80 if util<0.5 else max(0.0,100-(util-0.80)*300))
    c_score = min(100.0, ctx_len/327.68)

    W = {"General":(0.35,0.25,0.25,0.15),"Chat":(0.25,0.35,0.25,0.15),
         "Coding":(0.40,0.20,0.25,0.15),"Reasoning":(0.55,0.15,0.20,0.10),
         "Multimodal":(0.40,0.20,0.25,0.15),"Embedding":(0.30,0.30,0.25,0.15)}
    wq,ws,wf,wc = W.get(use_case, W["General"])
    score = round(wq*q_score + ws*s_score + wf*f_score + wc*c_score, 1)

    return {**m, "use_case": use_case, "params_b":params_b,"best_quant":best_quant,"run_mode":run_mode,
            "fit_level":fl,"fit_label":flb,"score":score,"estimated_tps":tps,
            "memory_required_gb":round(mem_req,1),"file_size_gb":_fsz(params_b,best_quant),
            "is_moe":is_moe}


# ---------------------------------------------------------------------------
# Database loader — FIX: handle list OR dict JSON, validate, fallback
# ---------------------------------------------------------------------------
def _load_raw_db() -> tuple:
    """Returns (list_of_models, source_description_string)."""

    def _extract(data) -> list:
        """Pull list from a JSON value regardless of top-level structure."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("models","data","results","items"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []

    def _ok(lst) -> bool:
        return bool(lst) and isinstance(lst[0], dict) and "name" in lst[0]

    # 1 — local cache
    if CACHE_PATH.exists():
        try:
            age = datetime.now() - datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
            if age < CACHE_TTL:
                with open(CACHE_PATH, encoding="utf-8") as f:
                    lst = _extract(json.load(f))
                if _ok(lst):
                    print(f"[ModelBrowser] Cache: {len(lst)} models")
                    return lst, f"llmfit database (cached · {len(lst)} models)"
        except Exception as e:
            print(f"[ModelBrowser] Cache error: {e}")

    # 2 — GitHub
    try:
        print("[ModelBrowser] Fetching from GitHub…")
        r   = requests.get(LLMFIT_DB_URL, timeout=20)
        r.raise_for_status()
        lst = _extract(r.json())
        if _ok(lst):
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(lst, f)
            print(f"[ModelBrowser] Downloaded {len(lst)} models")
            return lst, f"llmfit database (live · {len(lst)} models)"
        print(f"[ModelBrowser] Unexpected JSON structure")
    except Exception as e:
        print(f"[ModelBrowser] GitHub fetch failed: {e}")

    # 3 — embedded fallback (always works)
    print(f"[ModelBrowser] Using built-in fallback ({len(FALLBACK_MODELS)} models)")
    return FALLBACK_MODELS, f"Built-in model list ({len(FALLBACK_MODELS)} models)"


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------
class ModelDatabaseThread(QThread):
    loaded   = Signal(list, str)
    progress = Signal(str)
    hardware = Signal(object)

    def run(self):
        self.progress.emit("Detecting hardware…")
        hw = HardwareInfo().detect()
        self.hardware.emit(hw)

        self.progress.emit("Loading model database…")
        raw, source = _load_raw_db()

        if not raw:
            self.loaded.emit([], "No data available")
            return

        self.progress.emit(f"Scoring {len(raw)} models against your hardware…")
        scored = []
        for m in raw:
            try:
                r = score_model(m, hw)
                if r:
                    scored.append(r)
            except Exception as e:
                print(f"[ModelBrowser] Score error {m.get('name','?')}: {e}")

        scored.sort(key=lambda x: (FIT_ORDER.get(x["fit_level"], 9), -x["score"]))
        print(f"[ModelBrowser] Ready: {len(scored)} scored models")
        self.loaded.emit(scored, source)


class OllamaDownloadThread(QThread):
    progress_update = Signal(str, float)
    finished_ok     = Signal(str)
    failed          = Signal(str, str)

    def __init__(self, name: str):
        super().__init__()
        self.ollama_name = name

    def run(self):
        try:
            resp = requests.post(f"{OLLAMA_URL}/pull",
                                 json={"name":self.ollama_name,"stream":True},
                                 stream=True, timeout=3600)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    try:
                        c   = json.loads(line.decode("utf-8"))
                        tot = c.get("total",0)
                        don = c.get("completed",0)
                        self.progress_update.emit(c.get("status",""), (don/tot) if tot else 0.0)
                    except Exception:
                        pass
            self.finished_ok.emit(self.ollama_name)
        except Exception as e:
            self.failed.emit(self.ollama_name, str(e))


class OllamaDeleteThread(QThread):
    """Calls DELETE /api/delete to remove a local Ollama model and free disk space."""
    finished_ok = Signal(str)
    failed      = Signal(str, str)

    def __init__(self, name: str):
        super().__init__()
        self.ollama_name = name

    def run(self):
        try:
            resp = requests.delete(
                f"{OLLAMA_URL}/delete",
                json={"name": self.ollama_name},
                timeout=60,
            )
            if resp.status_code in (200, 204):
                self.finished_ok.emit(self.ollama_name)
            else:
                self.failed.emit(self.ollama_name, f"HTTP {resp.status_code}: {resp.text[:120]}")
        except Exception as e:
            self.failed.emit(self.ollama_name, str(e))

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------
COLUMNS = [
    ("Model",     260), ("Provider", 105), ("Params",   68),
    ("Use Case",   95), ("Fit",       88), ("Quant",    78),
    ("File Size",  82), ("VRAM",      72), ("Speed",    72),
    ("Path",      230),                    # manifest path for installed models
    ("",          168),   # wide enough for Pull (80) or Installed+Delete (74+74)
]

# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------
class ModelBrowserTab(QWidget):

    # Emitted from the background thread once installed-model detection is done.
    # Wiring it to _apply_filters (a slot on the Qt thread) is the safe way to
    # trigger a table refresh from a daemon thread.
    _installed_ready = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modelBrowserView")
        self._all_models  = []
        self._hw          = None
        self._dl_threads  = {}
        self._del_threads = {}   # tracks in-progress deletions
        self._installed      = set()
        self._install_paths  = {}   # model_tag → manifest file path
        self._db_thread   = None
        self._loaded      = False  # FIX: guard — filters must not run before data arrives

        # Refresh the table once installed-model detection has finished.
        # _apply_filters already guards with self._loaded, so connecting
        # unconditionally here is safe even if the DB hasn't loaded yet.
        self._installed_ready.connect(self._apply_filters)

        self._setup_ui()
        self._load()
        self._fetch_installed()

    # ── Build UI ──────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 20)
        root.setSpacing(14)

        # Header
        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(TitleLabel("Model Browser", self))
        self._subtitle = BodyLabel("Loading model database…", self)
        self._subtitle.setStyleSheet("color: #8a8a8a;")
        col.addWidget(self._subtitle)
        hdr.addLayout(col)
        hdr.addStretch()
        self._refresh_btn = PushButton(FIF.SYNC, "Refresh")
        self._refresh_btn.clicked.connect(self._load)
        hdr.addWidget(self._refresh_btn)
        root.addLayout(hdr)

        # Hardware bar
        hw_card = CardWidget()
        hw_card.setBorderRadius(10)
        hw_lay = QHBoxLayout(hw_card)
        hw_lay.setContentsMargins(16, 10, 16, 10)
        self._hw_ram  = self._stat("RAM Available", "Detecting…")
        self._hw_vram = self._stat("VRAM Free",     "Detecting…")
        self._hw_gpu  = self._stat("GPU",           "Detecting…")
        self._hw_back = self._stat("Backend",       "Detecting…")
        for w in (self._hw_ram, self._hw_vram, self._hw_gpu, self._hw_back):
            hw_lay.addWidget(w)
            hw_lay.addSpacing(28)
        hw_lay.addStretch()
        root.addWidget(hw_card)

        # Filter row
        frow = QHBoxLayout()
        frow.setSpacing(10)
        self._search = LineEdit()
        self._search.setPlaceholderText("Search model, provider, use case…")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(36)
        self._search.textChanged.connect(self._on_filter)
        frow.addWidget(self._search, 1)

        self._fit_combo = ComboBox()
        self._fit_combo.addItems(["All Fit Levels","Perfect","Good","Marginal","Too Tight"])
        self._fit_combo.setFixedWidth(148)
        self._fit_combo.currentTextChanged.connect(self._on_filter)
        frow.addWidget(self._fit_combo)

        self._uc_combo = ComboBox()
        self._uc_combo.addItems(["All Use Cases","General","Chat","Coding","Reasoning","Multimodal","Embedding"])
        self._uc_combo.setFixedWidth(148)
        self._uc_combo.currentTextChanged.connect(self._on_filter)
        frow.addWidget(self._uc_combo)

        self._installed_combo = ComboBox()
        self._installed_combo.addItems(["All Models", "Installed Only"])
        self._installed_combo.setFixedWidth(130)
        self._installed_combo.currentTextChanged.connect(self._on_filter)
        frow.addWidget(self._installed_combo)

        root.addLayout(frow)

        # Status
        self._status = CaptionLabel("Initialising…")
        self._status.setStyleSheet("color: #555e70;")
        root.addWidget(self._status)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(False)
        self._table.setStyleSheet("""
            QTableWidget { background:transparent; border:none; color:#e8eaed; font-size:12px; }
            QTableWidget::item { padding:5px 8px; border-bottom:1px solid #0d1526; }
            QTableWidget::item:selected { background:#1a2a50; color:#e8eaed; }
            QHeaderView::section { background:#0a0f1e; color:#8b9bb4; border:none;
                border-bottom:1px solid #1a2236; padding:5px 8px; font-size:11px; font-weight:bold; }
        """)
        h = self._table.horizontalHeader()
        h.setMinimumSectionSize(40)          # prevent columns collapsing to zero
        h.setSectionsMovable(False)          # lock order — prevents header/data misalignment
        for i, (_, w) in enumerate(COLUMNS):
            h.setSectionResizeMode(i, QHeaderView.Interactive)  # all cols draggable
            h.resizeSection(i, w)            # apply the initial widths from COLUMNS
        h.setStretchLastSection(False)
        root.addWidget(self._table)

    def _stat(self, label: str, value: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lbl = CaptionLabel(label)
        lbl.setStyleSheet("color:#555e70; font-size:10px;")
        val = StrongBodyLabel(value)
        val.setStyleSheet("color:#33b5e5;")
        lay.addWidget(lbl)
        lay.addWidget(val)
        f.setProperty("_v", val)
        return f

    def _set_stat(self, f: QFrame, text: str):
        w = f.property("_v")
        if w:
            w.setText(text)

    # ── Load ──────────────────────────────────────────────────────────────

    def _load(self):
        self._loaded = False
        self._refresh_btn.setEnabled(False)
        self._table.setRowCount(0)
        self._status.setText("Loading…")

        if self._db_thread and self._db_thread.isRunning():
            return
        self._db_thread = ModelDatabaseThread()
        self._db_thread.progress.connect(self._status.setText)
        self._db_thread.hardware.connect(self._on_hardware)
        self._db_thread.loaded.connect(self._on_loaded)
        self._db_thread.start()

    def _on_hardware(self, hw):
        self._hw = hw
        self._set_stat(self._hw_ram,  f"{hw.ram_gb:.1f} GB")
        self._set_stat(self._hw_vram, f"{hw.vram_gb:.1f} GB" if hw.vram_gb > 0 else "None")
        self._set_stat(self._hw_gpu,  hw.gpu_name[:30] if hw.gpu_name != "Unknown" else "No GPU")
        self._set_stat(self._hw_back, hw.backend.upper().replace("_"," "))

    def _on_loaded(self, models: list, source: str):
        self._all_models = models
        self._refresh_btn.setEnabled(True)
        self._loaded = True
        runnable = sum(1 for m in models if m.get("fit_level") != "too_tight")
        self._subtitle.setText(f"{source}  ·  {runnable} of {len(models)} compatible with your hardware")
        self._apply_filters()

    # ── Installed-model detection ─────────────────────────────────────────

    @staticmethod
    def _scan_ollama_dir() -> set:
        """Scan ~/.ollama/models/manifests/ to find models stored on disk.

        Ollama stores one manifest file per tag under:
            <manifests_root>/<registry>/<namespace>/<model>/<tag>
        e.g.
            ~/.ollama/models/manifests/registry.ollama.ai/library/llama3.2/3b

        This lets the Model Browser detect installed models even when the
        Ollama daemon is not running.
        """
        found = set()
        manifests_root = Path.home() / ".ollama" / "models" / "manifests"
        if not manifests_root.exists():
            return found
        try:
            for registry in manifests_root.iterdir():       # e.g. registry.ollama.ai
                if not registry.is_dir():
                    continue
                for namespace in registry.iterdir():        # e.g. library
                    if not namespace.is_dir():
                        continue
                    for model_dir in namespace.iterdir():   # e.g. llama3.2
                        if not model_dir.is_dir():
                            continue
                        for tag_file in model_dir.iterdir():  # e.g. 3b, latest
                            if tag_file.is_file():
                                found.add(f"{model_dir.name}:{tag_file.name}")
        except Exception as exc:
            print(f"[ModelBrowser] Ollama dir scan error: {exc}")
        if found:
            print(f"[ModelBrowser] Filesystem scan found {len(found)} installed model(s): {found}")
        return found

    def _fetch_installed(self):
        """Detect installed Ollama models via two sources (merged):
          1. Direct filesystem scan of ~/.ollama/models/manifests/ — works offline.
          2. Ollama REST API GET /api/tags — authoritative when Ollama is running.
        Emits _installed_ready on the Qt thread when done so the table refreshes.
        """
        def _go():
            # ── 1. Filesystem scan (works even if Ollama daemon is offline) ──
            found = self._scan_ollama_dir()

            # ── Build path map: model_tag → manifest file path (str) ────────
            manifests_root = Path.home() / ".ollama" / "models" / "manifests"
            paths: dict[str, str] = {}
            if manifests_root.exists():
                try:
                    for registry in manifests_root.iterdir():
                        if not registry.is_dir():
                            continue
                        for namespace in registry.iterdir():
                            if not namespace.is_dir():
                                continue
                            for model_dir in namespace.iterdir():
                                if not model_dir.is_dir():
                                    continue
                                for tag_file in model_dir.iterdir():
                                    if tag_file.is_file():
                                        key = f"{model_dir.name}:{tag_file.name}"
                                        paths[key] = str(tag_file)
                except Exception:
                    pass
            self._install_paths = paths

            # ── 2. REST API (authoritative, adds any non-library-registry models) ──
            try:
                r = requests.get(f"{OLLAMA_URL}/tags", timeout=3)
                if r.status_code == 200:
                    for m in r.json().get("models", []):
                        found.add(m["name"])
            except Exception:
                pass  # Ollama not running — filesystem scan is sufficient

            self._installed = found
            # Signal the Qt thread to refresh the table now that we know
            # which models are installed.
            self._installed_ready.emit()

        threading.Thread(target=_go, daemon=True).start()

    # ── Filter — FIX: only runs after _loaded is True ────────────────────

    def _on_filter(self, _=None):
        if self._loaded:
            self._apply_filters()

    # ── Installed-model matching helpers ──────────────────────────────────

    def _installed_bases(self) -> set:
        """Return the set of base model names (without :tag) from _installed.

        Example: {"qwen3:1.7b", "qwen2.5:latest", "qwen3-v1:4b"}
                 → {"qwen3", "qwen2.5", "qwen3-v1"}
        """
        return {n.split(":")[0] for n in self._installed}

    def _is_db_model_installed(self, hf_name: str) -> bool:
        """Return True only when the DB model's *exact* Ollama tag is
        present in ``self._installed``.

        Rationale
        ---------
        An earlier revision used base-name matching (strip ``:tag`` and
        compare) so that, e.g. ``qwen2.5:latest`` would match the DB entry
        ``qwen2.5:7b``. That turned out to be *too permissive*: if the user
        has only ``deepseek-r1:1.5b`` installed, every other DB variant
        (``deepseek-r1:7b``, ``:8b``, ``:14b``, ``:32b``, ``:70b``) shared
        the same base ``deepseek-r1`` and was wrongly flagged as installed.

        Ollama names follow the ``model:tag`` format (Ollama API docs —
        https://docs.ollama.com/api) and ``/api/tags`` returns each
        installed model's *specific* tag (e.g. ``deepseek-r1:1.5b`` or
        ``qwen2.5:latest``). We therefore require an exact match here.
        Installed models whose tag does not correspond to any DB entry —
        typically generic ``:latest`` pulls or custom models — are picked
        up by ``_matched_ollama_names`` / the synthetic-row mechanism in
        ``_apply_filters`` so they still show up in the table as
        ``Custom`` rows with a green Installed badge.
        """
        return _hf_to_ollama(hf_name) in self._installed

    def _matched_ollama_names(self) -> set:
        """Return the subset of ``self._installed`` whose exact Ollama tag
        is represented by a DB entry. Everything NOT in this set is treated
        as a custom/unrecognised install and gets a synthetic row in the
        table (see ``_apply_filters``).

        Exact matching only — see ``_is_db_model_installed`` for rationale.
        """
        matched = set()
        installed = self._installed
        for m in self._all_models:
            ol = _hf_to_ollama(m.get("name", ""))
            if ol in installed:
                matched.add(ol)
        return matched

    def _apply_filters(self):
        q      = self._search.text().lower().strip()
        fitf   = self._fit_combo.currentText()
        ucf    = self._uc_combo.currentText()
        instf  = self._installed_combo.currentText()

        visible = []
        for m in self._all_models:
            if fitf != "All Fit Levels" and m.get("fit_label","") != fitf:
                continue
            if ucf != "All Use Cases" and m.get("use_case","") != ucf:
                continue
            # FIX: use base-name matching so e.g. qwen2.5:latest is
            # recognised as the installed version of qwen2.5:7b in the DB.
            if instf == "Installed Only" and not self._is_db_model_installed(m.get("name","")):
                continue
            if q:
                hay = (m.get("name","")+" "+m.get("provider","")+" "+
                       m.get("use_case","")+" "+str(m.get("parameter_count",""))).lower()
                if q not in hay:
                    continue
            visible.append(m)

        # ── Inject raw / custom installed models not found in the DB ────────
        # These are Ollama models the user has pulled (e.g. qwen3-v1:4b)
        # that have no entry in the llmfit database.  We synthesise a
        # minimal row so they always appear as "Installed" regardless of
        # which filters are active.
        unmatched = self._installed - self._matched_ollama_names()
        for raw_name in sorted(unmatched):
            if q and q not in raw_name.lower():
                continue
            # Raw models are always "General" use-case and "Good" fit;
            # skip only when the user has narrowed to an incompatible filter.
            if ucf not in ("All Use Cases", "General"):
                continue
            if fitf not in ("All Fit Levels", "Good", "Perfect"):
                continue
            visible.append({
                "name":               raw_name,   # already an Ollama name
                "provider":           "Custom",
                "parameter_count":    "?",
                "params_b":           0.0,
                "use_case":           "General",
                "fit_label":          "Good",
                "fit_level":          "good",
                "best_quant":         "—",
                "file_size_gb":       0.0,
                "memory_required_gb": 0.0,
                "estimated_tps":      0.0,
                "is_moe":             False,
                "run_mode":           "gpu",
                "score":              0.0,
                "_raw_ollama":        True,   # flag: name IS already the Ollama name
            })

        # ── Sort: installed first, then fit_level → score ────────────────────
        def _sort_key(x):
            is_raw  = x.get("_raw_ollama", False)
            is_inst = is_raw or self._is_db_model_installed(x.get("name", ""))
            return (
                0 if is_inst else 1,
                FIT_ORDER.get(x.get("fit_level", "too_tight"), 9),
                -x.get("score", 0.0),
            )
        visible.sort(key=_sort_key)

        self._status.setText(f"{len(visible)} models shown")
        self._populate(visible)

    # ── Table ─────────────────────────────────────────────────────────────

    def _populate(self, models: list):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(models))

        RA = Qt.AlignRight | Qt.AlignVCenter
        LA = Qt.AlignLeft  | Qt.AlignVCenter

        # Pre-bind set for O(1) installed checks per row.
        _inst_exact = self._installed

        for row, m in enumerate(models):
            name     = m.get("name","")
            provider = m.get("provider","")
            params   = str(m.get("parameter_count", f"{m.get('params_b',0):.1f}B"))
            uc       = m.get("use_case","General")
            flab     = m.get("fit_label","—")
            flev     = m.get("fit_level","too_tight")
            quant    = m.get("best_quant","—")
            fsz      = m.get("file_size_gb", 0.0)
            vram     = m.get("memory_required_gb", 0.0)
            tps      = m.get("estimated_tps", 0.0)
            is_moe   = m.get("is_moe", False)
            rmode    = m.get("run_mode","cpu")

            # Raw/custom rows already carry their Ollama name; DB rows need
            # the HF→Ollama conversion.
            is_raw = m.get("_raw_ollama", False)
            ol     = name if is_raw else _hf_to_ollama(name)

            # Exact-match only — see _is_db_model_installed for rationale.
            # Fixes the bug where having e.g. deepseek-r1:1.5b installed
            # incorrectly flagged every deepseek-r1:* DB variant as installed.
            is_installed = ol in _inst_exact

            dname = (name.split("/")[-1] if "/" in name else name) + ("  [MoE]" if is_moe else "")
            fc    = FIT_COLOURS.get(flev, "#8b9bb4")

            def mk(txt, align=LA, colour=None):
                it = QTableWidgetItem(str(txt))
                it.setTextAlignment(align)
                if colour:
                    it.setForeground(QBrush(QColor(colour)))
                return it

            self._table.setItem(row, 0, mk(dname))
            self._table.setItem(row, 1, mk(provider, colour="#8b9bb4"))
            self._table.setItem(row, 2, mk(params, RA))
            self._table.setItem(row, 3, mk(uc, colour="#8b9bb4"))
            self._table.setItem(row, 4, mk(f"● {flab}", colour=fc))
            self._table.setItem(row, 5, mk(quant, colour="#33b5e5"))
            self._table.setItem(row, 6, mk(f"{fsz:.1f} GB"  if fsz  else "—", RA))
            self._table.setItem(row, 7, mk(f"{vram:.1f} GB" if vram else "—", RA,
                                            "#ffb300" if rmode=="cpu" else None))
            self._table.setItem(row, 8, mk(f"{tps:.0f} t/s" if tps  else "—", RA))

            # Path column (col 9) — manifest file path for installed models
            if is_installed:
                actual    = self._resolve_install_name(ol)
                raw_path  = self._install_paths.get(actual, "")
                disp_path = raw_path.replace(str(Path.home()), "~") if raw_path else "—"
            else:
                actual    = ""
                raw_path  = ""
                disp_path = "—"
            path_item = mk(disp_path, LA, "#8b9bb4")
            path_item.setToolTip(raw_path)
            self._table.setItem(row, 9, path_item)

            # Button
            bw = QWidget()
            bw.setStyleSheet("background:transparent;")
            bl = QHBoxLayout(bw)
            bl.setContentsMargins(4,2,4,2)

            if is_installed:
                # ── Installed: green badge + red Delete button ──────────
                installed_lbl = PushButton(FIF.ACCEPT, "Installed")
                installed_lbl.setEnabled(False)
                installed_lbl.setFixedWidth(84)
                installed_lbl.setStyleSheet("color:#4caf50;")

                del_btn = PushButton(FIF.DELETE, "Delete")
                del_btn.setFixedWidth(74)
                del_btn.setStyleSheet(
                    "QPushButton{color:#ef5350;border:1px solid #ef5350;border-radius:5px;}"
                    "QPushButton:hover{background:#3a1010;}"
                    "QPushButton:disabled{color:#555e70;border-color:#555e70;}"
                )
                _ol = ol
                del_btn.clicked.connect(lambda _=False, n=_ol: self._delete_model(self._resolve_install_name(n)))
                if ol in self._del_threads:
                    del_btn.setEnabled(False)
                    del_btn.setText("Deleting…")

                bl.addWidget(installed_lbl)
                bl.addSpacing(4)
                bl.addWidget(del_btn)

            elif flev == "too_tight":
                btn = PushButton(FIF.CANCEL, "Too Large")
                btn.setEnabled(False)
                btn.setFixedWidth(90)
                btn.setStyleSheet("color:#555e70;")
                bl.addWidget(btn)

            else:
                btn = PrimaryPushButton(FIF.DOWNLOAD, "Pull")
                btn.setFixedWidth(80)
                _ol = ol
                btn.clicked.connect(lambda _=False, n=_ol: self._download(n))
                bl.addWidget(btn)
            self._table.setCellWidget(row, 10, bw)
            self._table.setRowHeight(row, 40)

        self._table.setSortingEnabled(True)
        # Re-enforce Interactive resize on every column.
        # Qt internally resets QHeaderView section modes when toggling
        # setSortingEnabled — without this, some titles stop tracking their
        # columns after the first populate.
        _h = self._table.horizontalHeader()
        _h.setStretchLastSection(False)
        _h.setSectionsMovable(False)
        for _i in range(len(COLUMNS)):
            _h.setSectionResizeMode(_i, QHeaderView.Interactive)

    # ── Download ──────────────────────────────────────────────────────────

    def _download(self, name: str):
        if name in self._dl_threads:
            return
        InfoBar.info(title="Downloading", content=f"Pulling {name} via Ollama…",
                     orient=Qt.Horizontal, isClosable=True,
                     position=InfoBarPosition.TOP_RIGHT, duration=4000, parent=self.window())
        t = OllamaDownloadThread(name)
        t.progress_update.connect(lambda s,p,n=name: self._status.setText(f"Downloading {n}: {s} ({p*100:.0f}%)"))
        t.finished_ok.connect(self._dl_done)
        t.failed.connect(self._dl_fail)
        # FIX: Remove the thread reference only AFTER Qt's own 'finished' signal fires
        # (i.e. after Qt has fully cleaned up the thread internals).  Removing the
        # Python reference earlier — e.g. inside _dl_done / _dl_fail which fire from
        # the custom finished_ok / failed signals that are emitted while run() is still
        # technically on the stack — causes Python's GC to destroy the QThread wrapper
        # before Qt is done with it.  Qt then prints "QThread: Destroyed while thread
        # '' is still running" and, on Windows, that abrupt destruction breaks the
        # named-pipe IPC that multiprocessing (used by RealtimeSTT) relies on,
        # producing [WinError 109] BrokenPipeError in the STT subprocess.
        t.finished.connect(lambda n=name: self._dl_threads.pop(n, None))
        self._dl_threads[name] = t
        t.start()

    def _dl_done(self, name: str):
        # NOTE: do NOT pop _dl_threads here — the finished signal handler does it
        # once Qt's thread is truly complete (see _download above).
        self._installed.add(name)
        self._status.setText(f"✓ {name} downloaded")
        InfoBar.success(title="Download Complete", content=f"{name} is now available in Ollama.",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self.window())
        self._apply_filters()

    def _dl_fail(self, name: str, error: str):
        # NOTE: do NOT pop _dl_threads here — the finished signal handler does it
        # once Qt's thread is truly complete (see _download above).
        self._status.setText(f"✗ Failed: {error}")
        InfoBar.error(title="Download Failed", content=f"{name}: {error}",
                      orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP_RIGHT, duration=6000, parent=self.window())

    def _resolve_install_name(self, mapped_name: str) -> str:
        """Given a mapped name like 'qwen2.5:7b', return the actual installed
        Ollama tag (e.g. 'qwen2.5:7b-instruct-q8_0') from self._installed."""
        if mapped_name in self._installed:
            return mapped_name
        base = mapped_name.split(":")[0]
        for inst in self._installed:
            if inst.split(":")[0] == base:
                return inst
        return mapped_name
        
    # ── Delete ────────────────────────────────────────────────────────────

    def _delete_model(self, name: str):
        """Ask for confirmation then delete a local Ollama model to free disk space."""
        if name in self._del_threads:
            return   # already deleting

        from PySide6.QtWidgets import QMessageBox
        mb = QMessageBox(self.window())
        mb.setWindowTitle("Delete Model")
        mb.setText(f"Delete <b>{name}</b> from Ollama?")
        ollama_models_path = Path.home() / ".ollama" / "models"
        mb.setInformativeText(
            f"This will remove the model files from Ollama "
            f"({ollama_models_path}) and free the disk space. "
            "You can re-download it later from the Model Browser."
        )
        mb.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        mb.setDefaultButton(QMessageBox.Cancel)
        mb.setIcon(QMessageBox.Warning)
        if mb.exec() != QMessageBox.Yes:
            return

        self._status.setText(f"Deleting {name}…")
        InfoBar.info(title="Deleting Model", content=f"Removing {name} from Ollama…",
                     orient=Qt.Horizontal, isClosable=True,
                     position=InfoBarPosition.TOP_RIGHT, duration=4000, parent=self.window())

        t = OllamaDeleteThread(name)
        t.finished_ok.connect(self._del_done)
        t.failed.connect(self._del_fail)
        # Clean up the QThread reference only after Qt's finished signal fires
        t.finished.connect(lambda n=name: self._del_threads.pop(n, None))
        self._del_threads[name] = t
        t.start()
        # Refresh the row immediately so the Delete button shows "Deleting…"
        self._apply_filters()

    def _del_done(self, name: str):
        self._installed.discard(name)
        self._status.setText(f"✓ {name} deleted")
        InfoBar.success(title="Model Deleted",
                        content=f"{name} has been removed and disk space freed.",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=5000, parent=self.window())
        self._apply_filters()

    def _del_fail(self, name: str, error: str):
        self._status.setText(f"✗ Delete failed: {error}")
        InfoBar.error(title="Delete Failed", content=f"{name}: {error}",
                      orient=Qt.Horizontal, isClosable=True,
                      position=InfoBarPosition.TOP_RIGHT, duration=6000, parent=self.window())
