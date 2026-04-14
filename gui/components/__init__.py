"""
gui/components package — exports all public component classes.
Import from here (e.g. `from gui.components import ThinkingExpander`)
or directly from the submodule (both patterns are used in the codebase).
"""

from gui.components.alarm import AlarmComponent, AddAlarmDialog
from gui.components.message_bubble import MessageBubble
from gui.components.news_card import NewsCard
from gui.components.schedule import ScheduleComponent, AddEventDialog
from gui.components.search_indicator import SearchIndicator, RotatingSearchIcon
from gui.components.system_monitor import SystemMonitor
from gui.components.thinking_expander import ThinkingExpander, RotatingSpinner
from gui.components.timer import TimerComponent
from gui.components.toast import ToastNotification
from gui.components.toggle_switch import ToggleSwitch
from gui.components.voice_indicator import VoiceIndicator, EmbeddedVoiceWidget
from gui.components.weather_window import WeatherWindow

__all__ = [
    "AlarmComponent", "AddAlarmDialog",
    "MessageBubble",
    "NewsCard",
    "ScheduleComponent", "AddEventDialog",
    "SearchIndicator", "RotatingSearchIcon",
    "SystemMonitor",
    "ThinkingExpander", "RotatingSpinner",
    "TimerComponent",
    "ToastNotification",
    "ToggleSwitch",
    "VoiceIndicator", "EmbeddedVoiceWidget",
    "WeatherWindow",
]
