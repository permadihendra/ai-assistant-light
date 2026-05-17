import logging

import warnings
from typing import Any

from app.config import settings
from app.llm.base import LLMMessage
from app.llm.router import get_provider
from app.plugins.base import BotContext, Plugin

# Suppress the ddgs rename warning
warnings.filterwarnings("ignore", message=".*ddgs.*")

logger = logging.getLogger(__name__)


class WebSearchPlugin(Plugin):
    name = "web_search"
    commands = ["search"]
    description = "Search the web using DuckDuckGo (free, no API key needed)"

    async def handle(self, ctx: BotContext) -> str | None:
        # Parse query from command: "/search apa itu fastapi" → "apa itu fastapi"
        query = ctx.message_text
        for cmd in self.commands:
            prefix = f"/{cmd} "
            if ctx.message_text.startswith(prefix):
                query = ctx.message_text[len(prefix):].strip()
                break

        if not query:
            return "❓ Usage: `/search <query>` — search the web."

        try:
            results = await self._fetch_results(query)
            if not results:
                return f"🔍 *{query}*\n\nNo results found."

            reply = self._format_results(query, results)

            # Try to synthesize with LLM (optional)
            try:
                synthesis = await self._synthesize(query, results)
                if synthesis:
                    reply += f"\n\n💡 _{synthesis}_"
            except Exception as e:
                logger.warning("Search synthesis failed: %s", e)

            return reply

        except Exception as e:
            logger.error("Search failed: %s", e, exc_info=True)
            return "⚠️ Search failed. DuckDuckGo may be rate-limiting. Try again later."

    async def _fetch_results(self, query: str) -> list[dict[str, Any]]:
        """Fetch search results from DuckDuckGo."""
        from ddgs import DDGS

        def _search() -> list[dict[str, Any]]:
            with DDGS() as ddgs:
                return ddgs.text(
                    query,
                    max_results=settings.search_results or 5,
                )

        # Run in thread pool to avoid blocking the event loop
        import asyncio
        results = await asyncio.to_thread(_search)
        return results

    def _format_results(self, query: str, results: list[dict[str, Any]]) -> str:
        lines = [f"🔍 *{query}*"]
        for i, r in enumerate(results[: settings.search_results or 5], 1):
            title = r.get("title", "Untitled")
            url = r.get("href", "")
            desc = r.get("body", "")
            snippet = f" — {desc[:150]}" if desc else ""
            lines.append(f"{i}. [{title}]({url}){snippet}")
        return "\n".join(lines)

    async def _synthesize(self, query: str, results: list[dict[str, Any]]) -> str | None:
        """Use LLM to synthesize search results into a concise answer."""
        snippets = "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')[:200]}"
            for r in results[:3]
        )
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a helpful assistant that synthesizes web search results "
                    "into clear, concise answers. Write 2-3 sentences in the user's "
                    "language summarising the search results."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Search results for: {query}\n\n"
                    f"{snippets}\n\n"
                    "Provide a concise 2-3 sentence summary."
                ),
            ),
        ]
        provider = get_provider()
        response = await provider.chat(
            messages,
            max_tokens=200,
            timeout=15.0,
        )
        return response.text
