# Plia — Codebase Overview (Focused Debug Report: Settings page blank)

## Summary
Plia is a PySide6 + qfluentwidgets “Fluent Design” desktop app that runs most AI features locally via Ollama (with optional integrations like Google/Outlook Calendar, and optional Internet-search custom agents). The “Settings” tab is implemented as a lazily-loaded QWidget (`SettingsTab`) and is expected to construct many UI cards (models, Ollama URL, voice, weather, redaction, calendar, etc.). In your current environment the Settings page was blank because `SettingsTab._init_ui()` threw an exception during lazy initialization; that exception prevented the tab’s widget tree from being built.

## Architecture
- **Pattern**: Qt GUI app with **lazy-loaded tabs**.
- **Lazy loading entry point**: `gui/app.py` uses a `LazyTab` wrapper; `MainWindow._on_tab_changed()` calls `widget.initialize()` for `LazyTab` widgets.
- **SettingsTab**: `gui/tabs/settings.py` defines `SettingsTab(ScrollArea)` and builds the entire UI in `_init_ui()`. It also starts a background `ModelFetcher(QThread)` in `_fetch_models()`.
- **Key runtime behavior**:
  - If `SettingsTab.__init__` (or `_init_ui`) raises, the tab can appear blank.
  - The app was instrumented to surface lazy-tab initialization failures to the terminal and (when possible) display an error label.

## Directory Structure (relevant parts)
```text
project-root/
├── gui/
│   ├── app.py                     — MainWindow, lazy tab loading, tab init error logging
│   └── tabs/
│       └── settings.py          — SettingsTab UI construction
└── core/
    └── settings_store.py        — persisted settings accessor used by SettingsTab
```

## Key Abstractions
### `LazyTab`
- **File**: `gui/app.py` (class `LazyTab`)
- **Responsibility**: Delay creation of heavyweight tabs until the user navigates to them.
- **Interface**: `initialize()` builds the actual tab widget once and stores it in `actual_widget`.
- **Lifecycle**: Created at app startup; initialized on first tab switch.

### `MainWindow` lazy init + error instrumentation
- **File**: `gui/app.py` (`MainWindow._on_tab_changed`)
- **Responsibility**: Initialize lazy tabs and map them to `self.chat_tab`, `self.planner_tab`, etc.
- **Important behavior**:
  - `initialize()` is now wrapped in `try/except` (added during debugging).
  - On failure, it prints a traceback and attempts to add an error label to the placeholder widget’s layout.

### `SettingsTab`
- **File**: `gui/tabs/settings.py` (`SettingsTab.__init__`, `_init_ui`)
- **Responsibility**: Build the Settings UI (many card groups and controls) and start model fetching.
- **Important behavior added for debugging**:
  - `SettingsTab.__init__` now wraps `_init_ui()` and `_fetch_models()` in `try/except`.
  - On exception, it prints a traceback and adds an on-screen `QLabel` with the error message into the settings scroll layout.

## Data Flow (Settings lazy initialization failure path)
1. App starts and constructs a `LazyTab(SettingsTab, "settingsInterface")` in `_init_window()` (`gui/app.py`).
2. User navigates to Settings.
3. `MainWindow._on_tab_changed()` detects that the widget is a `LazyTab` and calls `widget.initialize()`.
4. `LazyTab.initialize()` calls `SettingsTab()` constructor.
5. `SettingsTab.__init__` calls `_init_ui()` which constructs cards using qfluentwidgets icons (`FIF.*`).
6. During `_init_ui`, `FIF.LOCK` (and previously `FIF.SHIELD`) is accessed, raising `AttributeError`.
7. `SettingsTab.__init__` catches the exception, prints a traceback, and adds an error label to the scroll content (instead of leaving it blank).
8. The app also catches lazy init failure at `MainWindow._on_tab_changed()` and attempts to show an error label and prints traceback.

## Non-Obvious Behaviors & Design Decisions
### 1) qfluentwidgets icon constants are version-dependent
The Settings UI relies on `from qfluentwidgets import FluentIcon as FIF` and expects certain icon enum members to exist (e.g. `FIF.SHIELD`, `FIF.LOCK`). Your runtime shows:
- Previous crash: `AttributeError: SHIELD`
- Current crash after substitution attempt: `AttributeError: LOCK`

This indicates your installed `qfluentwidgets` build does not define `FIF.SHIELD` nor `FIF.LOCK`. Other icons like `FIF.SYNC`, `FIF.BRUSH`, `FIF.ROBOT`, `FIF.LINK`, `FIF.MICROPHONE`, etc. do exist (confirmed via project-wide `FIF.*` search results).

**Why it matters**: If you pick an icon constant that doesn’t exist in your installed version, the exception occurs during `_init_ui()` construction, which (because the tab is lazily initialized) makes the entire Settings page blank.

### 2) “Blank window” can be just “construction exception”
The Settings page didn’t show widgets because `SettingsTab._init_ui()` failed before any meaningful UI was added. Lazy tab initialization means there’s no global error handler unless you add one (which is now done in both `SettingsTab` and `MainWindow`).

### 3) Console output may be the only reliable signal without error labels
Initially there was no terminal output for the blank UI. Instrumentation revealed the actual exception only after logging was added both at the tab constructor and at lazy-tab initialization.

## Root Cause of the Settings page failure
**Current failing exception (from your terminal):**
- `[SettingsTab] Settings failed to load: LOCK`
- `AttributeError: LOCK` arising from `gui/tabs/settings.py` inside `_init_ui()` at the line using `FIF.LOCK`.

**Earlier failing exception (from your terminal):**
- `AttributeError: SHIELD` from the line using `FIF.SHIELD`.

**Conclusion**: The Settings page is failing during UI construction because **`FIF.LOCK` (and `FIF.SHIELD`) do not exist in your installed qfluentwidgets version**.

## Suggested Fix (for Act Mode)
Replace all occurrences of icon constants that are not supported by your qfluentwidgets version inside `gui/tabs/settings.py`:
- Replace `FIF.LOCK` in:
  - `self.redaction_enabled_card = SwitchCard(FIF.LOCK, ...)`
  - `self.redaction_strictness_card = ComboBoxCard(FIF.LOCK, ...)`

Pick an icon constant that your installation supports. Based on usages found elsewhere in the project, safe candidates include:
- `FIF.EDIT`, `FIF.HIDE`, `FIF.CANCEL`, `FIF.INFO`, `FIF.ROBOT`, `FIF.SYNC`, `FIF.SHIELD` is *not* safe, `FIF.LOCK` is *not* safe.

After updating icons, the Settings tab should construct successfully.

## Module Reference
- `gui/app.py`
  - `MainWindow._on_tab_changed()` — lazy initialization of tabs; now logs initialization exceptions.
- `gui/tabs/settings.py`
  - `SettingsTab.__init__()` — wraps `_init_ui()` and `_fetch_models()` with a try/except for visible error reporting.
  - `SettingsTab._init_ui()` — constructs the Settings UI; currently fails at icon enum lookup (`FIF.LOCK`).

## Suggested Reading Order
1. `gui/app.py` → `LazyTab` + `MainWindow._on_tab_changed()` (understand lazy init + where exceptions surface)
2. `gui/tabs/settings.py` → `SettingsTab.__init__` (understand the new debug guard)
3. `gui/tabs/settings.py` → `SettingsTab._init_ui` (identify qfluentwidgets enum usage points)
4. `core/settings_store.py` (to understand what settings keys the UI writes/reads)
