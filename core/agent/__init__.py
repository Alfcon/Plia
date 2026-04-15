# core/agent package
#
# browser_agent has been removed from this project.
# Import DesktopAgent directly from its own module:
#
#   from core.agent.desktop_agent import DesktopAgent
#
# The previous line  `from .browser_agent import BrowserAgent`  caused:
#   ModuleNotFoundError: No module named 'core.agent.browser_agent'
# which prevented the Desktop Agent from showing a Ready status in the
# Active Agents panel and blocked function_executor from loading it.

__all__ = ["DesktopAgent"]