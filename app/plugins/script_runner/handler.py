import asyncio
import logging
import os
import re

from app.config import settings
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

SCRIPT_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.sh$")
MAX_OUTPUT_CHARS = 2000


class ScriptRunnerPlugin(Plugin):
    name = "script_runner"
    commands = ["run"]
    description = "Execute sandboxed shell scripts (admin only)"

    async def handle(self, ctx: BotContext) -> str | None:
        text = ctx.message_text.strip()

        if not text.startswith("/run "):
            return None

        # Security: only allowed chat IDs can run scripts
        if ctx.chat_id not in settings.allowed_chat_ids:
            return "⛔ You are not authorized to run scripts."

        # Parse: /run <script_name> [args...]
        rest = text[len("/run "):].strip()
        parts = rest.split()
        if not parts:
            return "❓ Usage: `/run <script_name> [args...]`"

        script_name = parts[0]
        script_args = parts[1:]

        # Validate script name
        if not SCRIPT_NAME_RE.match(script_name):
            return "❌ Invalid script name. Use only `[a-zA-Z0-9_-].sh`."

        # Build safe path
        scripts_dir = os.path.normpath(settings.scripts_dir)
        script_path = os.path.join(scripts_dir, script_name)
        script_path = os.path.normpath(script_path)

        # Prevent path traversal
        if not script_path.startswith(os.path.abspath(scripts_dir)):
            return "❌ Path traversal detected."

        if not os.path.isfile(script_path):
            return f"❌ Script `{script_name}` not found in `{scripts_dir}/`."

        # Execute with explicit args — shell=True is FORBIDDEN
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                script_path,
                *script_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=scripts_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=settings.script_timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return "⏱ Script timed out and was killed."

            output = (stdout + stderr).decode(errors="replace")[:MAX_OUTPUT_CHARS]
            if not output.strip():
                return "✅ Script executed successfully (no output)."

            return f"```\n{output}\n```"

        except FileNotFoundError:
            return f"❌ Script `{script_name}` not found."
        except Exception as e:
            logger.error("Script execution failed: %s", e, exc_info=True)
            return "⚠️ Script execution failed unexpectedly."
