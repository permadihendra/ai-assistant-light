from app.plugins.base import PluginRegistry
from app.plugins.reminder.handler import ReminderPlugin
from app.plugins.script_runner.handler import ScriptRunnerPlugin
from app.plugins.summarizer.handler import SummarizerPlugin
from app.plugins.web_search.handler import WebSearchPlugin

import pytest


@pytest.fixture
def plugin_registry():
    """Provide a fresh PluginRegistry with all plugins loaded."""
    registry = PluginRegistry()
    registry._plugins = {}  # Reset for test isolation
    for plugin in [
        WebSearchPlugin(),
        ReminderPlugin(),
        SummarizerPlugin(),
        ScriptRunnerPlugin(),
    ]:
        registry.register(plugin)
    return registry
