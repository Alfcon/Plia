"""Regression tests for SettingsTab's tabbed layout geometry.

After the Pivot-tab restructure, the Pivot and QStackedWidget must sit
*immediately* below the pinned Apply Changes group — not be pushed
hundreds of pixels off-screen by a layout that's still tracking the
reparented SettingCardGroups.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _build_tab(qapp):
    from PySide6.QtWidgets import QMainWindow
    from gui.tabs.settings import SettingsTab

    host = QMainWindow()
    host.resize(1200, 900)
    tab = SettingsTab()
    host.setCentralWidget(tab)
    host.show()
    qapp.processEvents()
    qapp.processEvents()
    return host, tab


def test_pivot_sits_directly_under_apply_group(qapp):
    """Pivot must be ≤ 50px below the bottom of apply_group."""
    host, tab = _build_tab(qapp)
    apply_bottom = tab.apply_group.y() + tab.apply_group.height()
    pivot_y = tab.pivot.y()
    gap = pivot_y - apply_bottom
    assert 0 <= gap <= 50, (
        f"Pivot is {gap}px below apply_group (expected ≤ 50). "
        f"apply_group.y={tab.apply_group.y()}, h={tab.apply_group.height()}; "
        f"pivot.y={pivot_y}"
    )


def test_tab_stack_has_visible_height(qapp):
    """tab_stack must have enough height to show its current panel."""
    host, tab = _build_tab(qapp)
    assert tab.tab_stack.height() >= 100, (
        f"tab_stack height is {tab.tab_stack.height()} — content is invisible. "
        f"Expected ≥ 100px so cards are reachable."
    )


def test_tab_stack_sits_below_pivot(qapp):
    """tab_stack must be vertically after the pivot, with a small gap."""
    host, tab = _build_tab(qapp)
    pivot_bottom = tab.pivot.y() + tab.pivot.height()
    stack_y = tab.tab_stack.y()
    gap = stack_y - pivot_bottom
    assert 0 <= gap <= 30, (
        f"tab_stack is {gap}px below pivot — expected 0–30px. "
        f"pivot.y={tab.pivot.y()}, h={tab.pivot.height()}; stack.y={stack_y}"
    )


def test_clicking_each_pivot_item_switches_to_that_tab(qapp):
    """Clicking each PivotItem must land on its corresponding stack index."""
    host, tab = _build_tab(qapp)
    keys = ["core", "voice", "features", "about"]
    for expected_idx, key in enumerate(keys):
        item = tab.pivot.widget(key)
        assert item is not None, f"no pivot item for routeKey={key!r}"
        item.click()
        qapp.processEvents()
        assert tab.tab_stack.currentIndex() == expected_idx, (
            f"clicking {key!r} should switch to index {expected_idx}, "
            f"got {tab.tab_stack.currentIndex()}"
        )


def test_stack_sizehint_tracks_current_panel(qapp):
    """The stack widget's sizeHint must shrink/grow with the active panel,
    so the scroll area doesn't reserve space for the largest tab."""
    host, tab = _build_tab(qapp)

    # Switch to About (smallest panel, 1 group)
    tab.pivot.widget("about").click()
    qapp.processEvents()
    about_hint = tab.tab_stack.sizeHint().height()

    # Switch to Features (largest panel, 7 groups)
    tab.pivot.widget("features").click()
    qapp.processEvents()
    features_hint = tab.tab_stack.sizeHint().height()

    assert features_hint > about_hint + 300, (
        f"Features sizeHint ({features_hint}) should be much taller than "
        f"About sizeHint ({about_hint}). If they're equal the stack is "
        f"reserving max-panel space on every tab."
    )


def test_pivot_remembers_last_tab_across_constructions(qapp):
    """The last-selected tab must persist via settings and restore on rebuild."""
    from core.settings_store import settings

    host, tab = _build_tab(qapp)

    # User clicks Features
    tab.pivot.widget("features").click()
    qapp.processEvents()
    assert tab.tab_stack.currentIndex() == 2
    assert settings.get("ui.settings_last_tab") == "features"

    # Tear down host/tab (simulate closing settings)
    host.close()
    del tab, host
    qapp.processEvents()

    # Build a fresh SettingsTab — should restore to Features
    host2, tab2 = _build_tab(qapp)
    assert tab2.tab_stack.currentIndex() == 2, (
        f"Expected restored tab index 2 (features); got {tab2.tab_stack.currentIndex()}"
    )

    # Reset for other tests so they don't get a stale default
    settings.set("ui.settings_last_tab", "core")
