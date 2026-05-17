"""System prompts for all features — kept in one place for easy auditing."""

SEARCH_SYSTEM_PROMPT = (
    "You are a helpful assistant that synthesizes web search results into clear, "
    "concise answers. Write 2-3 sentences in the user's language summarising the "
    "search results. Focus on the most relevant information."
)

SUMMARIZE_SYSTEM_PROMPT = (
    "Summarize the following group chat conversation in 5 bullet points. "
    "Focus on key decisions, questions asked, and important announcements. "
    "Be concise and objective."
)
