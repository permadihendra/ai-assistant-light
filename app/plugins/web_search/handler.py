import logging

import httpx

from app.config import settings
from app.llm.router import get_provider
from app.llm.base import LLMMessage
from app.plugins.base import BotContext, Plugin

logger = logging.getLogger(__name__)

SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchPlugin(Plugin):
    name = "web_search"
    commands = ["search"]
    description = "Search the web using Brave Search API"

    async def handle(self, ctx: BotContext) -> str | None:
        # Parse query from command: "/search apa itu fastapi" → "apa itu fastapi"
        query = ctx.message_text
        for cmd in self.commands:
            prefix = f"/{cmd} "
            if ctx.message_text.startswith(prefix):
                query = ctx.message_text[len(prefix) :]
                break

        if not query.strip():
            return "❓ Usage: `/search <query>` — search the web."

        if not settings.brave_api_key:
            return "⚠️ Brave Search API key not configured. Ask the admin to set `BRAVE_API_KEY`."

        try:
            results = await self._fetch_results(query)
            if not results:
                return f"🔍 *{query}*\n\nNo results found."

            reply = self._format_results(query, results)

            # Try to synthesize with LLM
            try:
                synthesis = await self._synthesize(query, results)
                if synthesis:
                    reply += f"\n\n💡 _{synthesis}_"
            except Exception as e:
                logger.warning("Search synthesis failed: %s", e)

            return reply

        except httpx.HTTPStatusError as e:
            logger.error("Brave API HTTP error: %s", e)
            return f"⚠️ Search API error: {e.response.status_code}"
        except httpx.TimeoutException:
            return "⏱ Search request timed out. Try again later."
        except Exception as e:
            logger.error("Search failed: %s", e, exc_info=True)
            return "⚠️ Search failed unexpectedly."

    async def _fetch_results(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                SEARCH_API_URL,
                headers={"X-Subscription-Token": settings.brave_api_key},
                params={
                    "q": query,
                    "count": settings.brave_search_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("web", {}).get("results", [])

    def _format_results(self, query: str, results: list[dict]) -> str:
        lines = [f"🔍 *{query}*"]
        for i, r in enumerate(results[: settings.brave_search_results], 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            desc = r.get("description", "")
            snippet = f" — {desc}" if desc else ""
            lines.append(f"{i}. [{title}]({url}){snippet}")
        return "\n".join(lines)

    async def _synthesize(self, query: str, results: list[dict]) -> str | None:
        snippets = "\n".join(
            f"- {r.get('title', '')}: {r.get('description', '')}"
            for r in results[:3]
        )
        messages = [
            LLMMessage(
                role="user",
                content=(
                    f"Search results for: {query}\n\n"
                    f"{snippets}\n\n"
                    "Provide a concise 2-3 sentence summary."
                ),
            )
        ]
        provider = get_provider()
        response = await provider.chat(
            messages,
            max_tokens=200,
            timeout=15.0,
        )
        return response.text
