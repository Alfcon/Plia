"""
FunctionGemma Router - Routes user prompts to appropriate functions.
Supports 9 functions: 6 actions, 1 context, 2 passthrough.

IMPORTANT – torch / transformers lazy-import fix
─────────────────────────────────────────────────
The original router.py imported torch and the heavy transformers
classes at *module level*.  This caused a fatal circular import on
startup:

    preload_models()
      → from core.router import FunctionGemmaRouter    ← module-level
        → import torch                                  ← line 13
          → torch.nested → torch.fx → torch.fx.interpreter
            → from torch.hub import tqdm
              ↑ torch.hub is still being initialised → ImportError

That broken import left sys.modules['torch'] in a poisoned state,
which then cascaded into the STT thread:

    _patch_torchaudio_if_broken()
      → import torchaudio
        → from torch.hub import …
          → KeyError: 'torch'   ← torch not in sys.modules cleanly

Fix: ALL torch and transformers AutoModel/AutoTokenizer imports have
been moved inside FunctionGemmaRouter.__init__().  Importing this
module no longer touches torch at all.  get_json_schema (from
transformers.utils) is torch-free and stays at module level so that
the TOOLS list can still be built at import time.
"""

import os
import warnings
import time
import re
import json
import types
from typing import Literal, Tuple, Dict, Any

# Suppress transformers warnings before importing
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
warnings.filterwarnings("ignore", message=".*generation flags are not valid.*")

# ── transformers.utils.get_json_schema is torch-free ─────────────────────
# It only reads Python function signatures; no model loading occurs.
try:
    from transformers.utils import get_json_schema
    _HAS_GET_JSON_SCHEMA = True
except ImportError:
    _HAS_GET_JSON_SCHEMA = False
    def get_json_schema(fn):
        """Fallback: return a minimal schema if transformers is unavailable."""
        return {"name": fn.__name__, "description": fn.__doc__ or ""}

from huggingface_hub import snapshot_download

from config import LOCAL_ROUTER_PATH, HF_ROUTER_REPO

# Debug flag - set to True to see Gemma's raw response
DEBUG_ROUTER = False


# --- Tool Definitions (all functions) ---

def control_light(action: str, device_name: str = None, brightness: int = None, color: str = None) -> str:
    """
    Control smart lights - turn on, off, dim, or change color.

    Args:
        action: Action to perform: on, off, dim, toggle
        device_name: Name of the light or room
        brightness: Brightness level 0-100
        color: Color name or hex code
    """
    return "result"

def set_timer(duration: str, label: str = None) -> str:
    """
    Set a countdown timer.

    Args:
        duration: Duration like '5 minutes' or '1 hour'
        label: Optional label for the timer
    """
    return "result"

def set_alarm(time: str, label: str = None) -> str:
    """
    Set an alarm for a specific time.

    Args:
        time: Time for alarm like '7am' or '14:30'
        label: Optional label
    """
    return "result"

def create_calendar_event(title: str, date: str = None, time: str = None, duration: int = None) -> str:
    """
    Create a calendar event.

    Args:
        title: Event title
        date: Date like 'tomorrow' or '2024-01-15'
        time: Time like '3pm'
        duration: Duration in minutes
    """
    return "result"

def add_task(text: str, priority: str = None) -> str:
    """
    Add a task to the to-do list.

    Args:
        text: Task description
        priority: Priority level
    """
    return "result"

def web_search(query: str) -> str:
    """
    Search the web for information using DuckDuckGo.
    Returns up to 5 search results including titles, snippets, and URLs.

    Use this when the user asks to:
    - Search for information online
    - Look up current events or news
    - Find facts, definitions, or explanations
    - Research a topic

    Args:
        query: Search query string (e.g., "Python programming best practices")

    Returns:
        Search results with titles, body snippets (200 chars), and URLs
    """
    return "result"

def get_system_info() -> str:
    """
    Get comprehensive current system state snapshot.

    Returns information about:
    - Current time and date
    - Active countdown timers (label, remaining time)
    - Upcoming alarms (time, label)
    - Today's calendar events (title, time)
    - Pending tasks from to-do list (text, completion status)
    - Smart home devices (name, on/off status, type)
    - Current weather (temperature, condition, high/low)
    - Recent news headlines (title, category, URL)

    Use this when the user asks:
    - "What's on my schedule today?"
    - "What's my current status?"
    - "What do I have coming up?"
    - "Give me a summary of everything"
    - Questions about their timers, tasks, or calendar
    """
    return "result"

def thinking(prompt: str) -> str:
    """
    Use for complex queries requiring reasoning, math, coding, or multi-step analysis.

    Args:
        prompt: The user's original prompt
    """
    return "result"

def nonthinking(prompt: str) -> str:
    """
    Use for simple queries, greetings, factual questions not requiring deep reasoning.

    Args:
        prompt: The user's original prompt
    """
    return "result"


def control_desktop(task: str) -> str:
    """
    Control the Windows desktop environment using natural language.
    Use this when the user wants to open, switch to, or interact with
    any Windows application or desktop feature.

    Examples of when to use:
    - "Open Discord"
    - "Launch Spotify"
    - "Open File Explorer and go to Downloads"
    - "Switch to the browser"
    - "Close Notepad"

    Args:
        task: A plain English description of the desktop task to perform.
    """
    return "result"


def browse_web(task: str) -> str:
    """
    Control a web browser to complete a multi-step task on the internet.
    Use this when the user wants to navigate a website, fill a form,
    click buttons, scroll, or perform any visual browser interaction
    that goes beyond a simple search.

    Examples of when to use:
    - "Go to amazon.com and search for headphones"
    - "Navigate to my bank and check the balance"
    - "Browse to reddit.com and find the top post"
    - "Open YouTube and play relaxing music"
    - "Navigate to..."
    - "Browse to..."

    Do NOT use for simple factual lookups — use web_search instead.

    Args:
        task: A plain English description of the browser task to perform.
    """
    return "result"


# Pre-compute tool schemas at module level (get_json_schema is torch-free)
TOOLS = [
    get_json_schema(control_light),
    get_json_schema(set_timer),
    get_json_schema(set_alarm),
    get_json_schema(create_calendar_event),
    get_json_schema(add_task),
    get_json_schema(web_search),
    get_json_schema(get_system_info),
    get_json_schema(thinking),
    get_json_schema(nonthinking),
    get_json_schema(control_desktop),
    get_json_schema(browse_web),
]

SYSTEM_MSG = "You are a model that can do function calling with the following functions"

# All valid function names
VALID_FUNCTIONS = {
    "control_light", "set_timer", "set_alarm", "create_calendar_event",
    "add_task", "web_search", "get_system_info", "thinking", "nonthinking",
    "control_desktop", "browse_web",
}


def ensure_model_available(model_path: str = LOCAL_ROUTER_PATH) -> str:
    """
    Ensure the router model is available locally.
    Downloads from Hugging Face if not found.

    Returns:
        str: Path to the model (local or downloaded)
    """
    if os.path.exists(model_path) and os.path.isdir(model_path):
        # Check for essential files
        if os.path.exists(os.path.join(model_path, "model.safetensors")):
            return model_path

    # Download from Hugging Face
    print(f"[Router] Model not found at {model_path}")
    print(f"[Router] Downloading from Hugging Face: {HF_ROUTER_REPO}...")

    try:
        downloaded_path = snapshot_download(
            repo_id=HF_ROUTER_REPO,
            local_dir=model_path,
            local_dir_use_symlinks=False
        )
        print(f"[Router] ✓ Model downloaded to {downloaded_path}")
        return downloaded_path
    except Exception as e:
        raise RuntimeError(
            f"Failed to download model from {HF_ROUTER_REPO}: {e}\n"
            f"Train the model locally with: python train_function_gemma.py"
        )


class FunctionGemmaRouter:
    """Routes user prompts to appropriate functions using fine-tuned FunctionGemma.

    torch and the heavy transformers classes (AutoTokenizer, AutoModelForCausalLM)
    are imported *lazily* inside __init__ so that importing this module does NOT
    trigger torch's initialisation chain.  This prevents the circular import
    error that used to crash the ModelPreloaderThread on startup.
    """

    def __init__(self, model_path: str = LOCAL_ROUTER_PATH, compile_model: bool = False):
        # ── Lazy torch + transformers imports ────────────────────────────
        # These are deferred to here (not module level) to avoid the
        # torch.hub → tqdm circular import that breaks startup.
        import torch  # noqa: PLC0415  (intentional late import)
        from transformers import (  # noqa: PLC0415
            AutoTokenizer,
            AutoModelForCausalLM,
            logging as transformers_logging,
        )
        transformers_logging.set_verbosity_error()

        # Ensure model is available (download from HF if needed)
        model_path = ensure_model_available(model_path)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading FunctionGemma Router on {device.upper()}...")
        start = time.time()

        self.tokenizer = AutoTokenizer.from_pretrained(model_path)

        # CPU often doesn't support bfloat16 natively
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=dtype,
            device_map=device,
        )
        self.model.eval()

        # Keep a local reference to torch for inference methods
        self._torch = torch

        # Compile for speed (PyTorch 2.0+)
        if compile_model:
            try:
                self.model = torch.compile(self.model, mode="reduce-overhead")
                print("Model compiled with torch.compile()")
            except Exception as e:
                print(f"torch.compile() not available: {e}")

        print(f"Router loaded in {time.time() - start:.2f}s")
        print(f"Device: {self.model.device}, Dtype: {self.model.dtype}")

    def route(self, user_prompt: str) -> Tuple[str, Dict[str, Any]]:
        """
        Route a user prompt to the appropriate function.

        Returns:
            Tuple of (function_name, arguments_dict)
        """
        torch = self._torch

        with torch.inference_mode():
            # Build messages
            messages = [
                {"role": "developer", "content": SYSTEM_MSG},
                {"role": "user", "content": user_prompt},
            ]

            # Apply chat template
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tools=TOOLS,
                add_generation_prompt=True,
                tokenize=False
            )

            # Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

            # Generate with minimal settings for speed
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=100,
                do_sample=False,
                use_cache=True,
                pad_token_id=self.tokenizer.pad_token_id,
            )

            # Decode new tokens only
            new_tokens = outputs[0][inputs['input_ids'].shape[1]:]
            response = self.tokenizer.decode(new_tokens, skip_special_tokens=False)

        # Debug: Print raw Gemma response
        if DEBUG_ROUTER:
            print(f"\n{'='*50}")
            print(f"[Router DEBUG] User prompt: {user_prompt}")
            print(f"[Router DEBUG] Raw Gemma response:")
            print(f"  {repr(response)}")
            print(f"{'='*50}")

        # Parse function call
        return self._parse_function_call(response, user_prompt)

    def _parse_function_call(self, response: str, user_prompt: str) -> Tuple[str, Dict[str, Any]]:
        """Parse the model's response to extract function name and arguments."""

        # Try to find function call pattern: call:function_name
        for func_name in VALID_FUNCTIONS:
            if f"call:{func_name}" in response:
                # Try to extract arguments
                args = self._extract_arguments(response, func_name, user_prompt)
                return func_name, args

        # Fallback to nonthinking if no function found
        return "nonthinking", {"prompt": user_prompt}

    def _extract_arguments(self, response: str, func_name: str, user_prompt: str) -> Dict[str, Any]:
        """Extract arguments from the response."""

        # Default arguments for passthrough functions
        if func_name in ("thinking", "nonthinking"):
            return {"prompt": user_prompt}

        # For get_system_info, no args needed
        if func_name == "get_system_info":
            return {}

        # Parse the model's custom format: {key:<escape>value<escape>,key2:<escape>value2<escape>}
        pattern = rf"call:{func_name}\{{([^}}]+)\}}"
        match = re.search(pattern, response)

        if match:
            args_str = match.group(1)
            args = {}

            arg_pattern = r'(\w+):(?:<escape>([^<]*)<escape>|([^,]+))'
            for arg_match in re.finditer(arg_pattern, args_str):
                key = arg_match.group(1)
                val_escaped = arg_match.group(2)
                val_unescaped = arg_match.group(3)

                value = val_escaped if val_escaped is not None else val_unescaped

                # Try to convert to appropriate type
                if value.isdigit():
                    args[key] = int(value)
                elif value.lower() in ('true', 'false'):
                    args[key] = value.lower() == 'true'
                else:
                    args[key] = value

            if args:
                return args

        # Fallback: return user prompt as main argument
        if func_name == "control_light":
            return {"action": "toggle", "device_name": user_prompt}
        elif func_name == "set_timer":
            return {"duration": user_prompt}
        elif func_name == "set_alarm":
            return {"time": user_prompt}
        elif func_name == "create_calendar_event":
            return {"title": user_prompt}
        elif func_name == "add_task":
            return {"text": user_prompt}
        elif func_name == "web_search":
            return {"query": user_prompt}
        elif func_name == "control_desktop":
            return {"task": user_prompt}
        elif func_name == "browse_web":
            return {"task": user_prompt}

        return {}

    def route_with_timing(self, user_prompt: str) -> Tuple[Tuple[str, Dict], float]:
        """Route with timing info."""
        start = time.time()
        result = self.route(user_prompt)
        elapsed = time.time() - start
        return result, elapsed


if __name__ == "__main__":
    router = FunctionGemmaRouter(compile_model=False)

    test_prompts = [
        ("Turn on the living room lights", "control_light"),
        ("Set a timer for 10 minutes", "set_timer"),
        ("Wake me up at 7am", "set_alarm"),
        ("Schedule meeting tomorrow at 3pm", "create_calendar_event"),
        ("Add buy groceries to my list", "add_task"),
        ("Search for Italian recipes", "web_search"),
        ("How much time is left on my timer?", "get_system_info"),
        ("What's on my calendar today?", "get_system_info"),
        ("Explain quantum computing", "thinking"),
        ("Hello there!", "nonthinking"),
        ("What's the capital of France?", "nonthinking"),
    ]

    print("\n" + "="*70)
    print("FUNCTION CALLING ROUTER TEST")
    print("="*70)

    total_time = 0
    correct = 0

    for prompt, expected in test_prompts:
        (func_name, args), elapsed = router.route_with_timing(prompt)
        total_time += elapsed
        match = "✓" if func_name == expected else "✗"
        if func_name == expected:
            correct += 1

        print(f"\n[{match}] {prompt}")
        print(f"    → {func_name}({args}) [{elapsed*1000:.0f}ms]")

    avg_time = total_time / len(test_prompts)
    print(f"\n{'='*70}")
    print(f"Accuracy: {correct}/{len(test_prompts)} ({100*correct/len(test_prompts):.0f}%)")
    print(f"Average routing time: {avg_time*1000:.0f}ms per prompt")
    print(f"Total time: {total_time:.2f}s for {len(test_prompts)} prompts")
