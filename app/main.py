import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bot.gateway import router as bot_router
from app.config import settings
from app.database import init_db
from app.llm.router import get_provider
from app.plugins.base import PluginRegistry
from app.plugins.brain.handler import BrainPlugin
from app.plugins.reminder.handler import ReminderPlugin
from app.plugins.script_runner.handler import ScriptRunnerPlugin
from app.plugins.summarizer.handler import SummarizerPlugin
from app.plugins.system.handler import SystemPlugin
from app.plugins.web_search.handler import WebSearchPlugin
from app.scheduler.runner import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast — validate LLM config before serving any request
    try:
        get_provider()
        logger.info("LLM provider '%s' validated", settings.llm_provider)
    except RuntimeError as e:
        logger.warning("LLM provider not fully configured: %s", e)

    await init_db()

    registry = PluginRegistry.get()
    plugins = [
        BrainPlugin(),  # ← must be first — handles non-command messages
        SystemPlugin(),
        WebSearchPlugin(),
        ReminderPlugin(),
        SummarizerPlugin(),
        ScriptRunnerPlugin(),
    ]
    for plugin in plugins:
        registry.register(plugin)
        await plugin.on_load()
        logger.info("Plugin loaded: %s", plugin.name)

    await start_scheduler()

    yield

    await stop_scheduler()
    for p in registry.all():
        await p.on_unload()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan, title="ai-assistant-light")
app.include_router(bot_router)


@app.get("/health")
async def health():
    return {"status": "ok", "provider": settings.llm_provider}
    # Never expose key values here
