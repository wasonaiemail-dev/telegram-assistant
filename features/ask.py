"""
alfred/features/ask.py
=======================
General question-answering with persistent 8-hour conversation thread,
memory context injection, and optional live web search.

PUBLIC INTERFACE
────────────────
  handle_ask(text, update, context) → None
      Main entry point. Called by bot.py for ASK and UNKNOWN intents.
      Runs GPT with memory context, maintains conversation history,
      and auto-suggests memorable facts via suggest_memory_fact().

  handle_text_message(text, update, context) → None
      Called for unrecognized free-text messages (falls through from
      intent classifier). Routes to handle_ask() with full context.

CONVERSATION THREAD
────────────────────
  Alfred maintains one rolling 8-hour conversation window stored in
  ask_history.json. If the thread is silent for more than ASK_CONTEXT_HOURS,
  it auto-resets so old context doesn't pollute new conversations.
  Max history is capped at ASK_MAX_HISTORY entries (oldest dropped first).

MEMORY INJECTION
─────────────────
  Memory context is injected into the GPT system prompt using
  get_context_for_message(text) — only relevant categories are included
  (Me + Preferences always; others by keyword match). This adds ~100–500
  tokens on average vs. injecting all ~12,000 tokens.

WEB SEARCH
──────────
  If SERPER_API_KEY is set, Alfred can search the web for current info.
  The search step is triggered automatically by the intent classifier when
  the query looks like it needs real-time data, or can be forced with
  /ask -search [query].
  Falls back to GPT knowledge only if the search fails or key is missing.

TOPIC SHIFT DETECTION
──────────────────────
  If the user asks something completely different from the thread topic,
  Alfred auto-resets the thread and starts fresh rather than confusing GPT
  with unrelated history. Powered by a lightweight GPT check.
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from core.config import (
    BOT_NAME,
    OPENAI_API_KEY,
    SERPER_API_KEY,
    GPT_CHAT_MODEL,
    ASK_MAX_HISTORY,
    MEMORY_SYSTEM_PREFIX,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: WEB SEARCH
# ─────────────────────────────────────────────────────────────────────────────

async def _web_search(query: str) -> str | None:
    """
    Search the web via Serper.dev and return a formatted snippet string.
    Returns None if SERPER_API_KEY is not set or the request fails.
    """
    if not SERPER_API_KEY:
        return None

    import aiohttp
    url     = "https://google.serper.dev/search"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "num": 5}

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        snippets = []
        # Answer box (highest quality)
        if "answerBox" in data:
            ab = data["answerBox"]
            answer = ab.get("answer") or ab.get("snippet") or ab.get("title", "")
            if answer:
                snippets.append(f"Answer: {answer}")

        # Knowledge graph
        if "knowledgeGraph" in data:
            kg = data["knowledgeGraph"]
            desc = kg.get("description", "")
            if desc:
                snippets.append(f"Overview: {desc}")

        # Organic results
        for r in data.get("organic", [])[:3]:
            title   = r.get("title", "")
            snippet = r.get("snippet", "")
            if snippet:
                snippets.append(f"{title}: {snippet}")

        return "\n\n".join(snippets) if snippets else None

    except Exception as e:
        logger.warning(f"_web_search error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: TOPIC SHIFT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

async def _is_topic_shift(new_text: str, topic_summary: str) -> bool:
    """
    Lightweight check: is the new message completely off-topic from the
    current thread's topic_summary?

    Returns True → reset thread and start fresh.
    Returns False → keep appending to the thread.
    """
    if not topic_summary or not new_text:
        return False

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"Current topic: \"{topic_summary}\"\n"
                    f"New message: \"{new_text[:200]}\"\n\n"
                    "Is the new message on a completely different topic "
                    "(not a follow-up or related question)? "
                    "Reply with only: YES or NO"
                ),
            }],
            max_tokens=5,
            temperature=0,
            timeout=5,
        )
        answer = resp.choices[0].message.content.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.debug(f"_is_topic_shift error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: TOPIC SUMMARY UPDATE
# ─────────────────────────────────────────────────────────────────────────────

async def _summarize_topic(text: str) -> str:
    """Generate a 1-line topic summary for the current message."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"Summarize this message in 8 words or fewer:\n\"{text[:200]}\""
                ),
            }],
            max_tokens=20,
            temperature=0,
            timeout=5,
        )
        return resp.choices[0].message.content.strip().strip('"')
    except Exception:
        return text[:50]


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: handle_ask
# ─────────────────────────────────────────────────────────────────────────────

async def handle_ask(
    text:    str,
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    force_search: bool = False,
) -> None:
    """
    Handle a general question or conversation message.

    1. Load ask thread (or start fresh if expired/topic-shifted).
    2. Optionally fetch web search results.
    3. Build GPT messages with memory context injected.
    4. Call GPT and send response.
    5. Persist updated thread.
    6. Non-blocking: auto-suggest memorable facts.
    """
    from openai import AsyncOpenAI
    from core.data import load_ask_history, save_ask_history, clear_ask_history
    from features.memory import get_context_for_message, suggest_memory_fact

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    # ── Load thread ───────────────────────────────────────────────────────────
    hist = load_ask_history()
    messages: list[dict] = hist.get("messages", [])
    topic_summary: str   = hist.get("topic_summary", "")

    # ── Topic shift check ─────────────────────────────────────────────────────
    if messages and topic_summary:
        is_shift = await _is_topic_shift(text, topic_summary)
        if is_shift:
            clear_ask_history()
            hist          = {"messages": [], "topic_summary": ""}
            messages      = []
            topic_summary = ""

    # ── Memory context ────────────────────────────────────────────────────────
    memory_block = get_context_for_message(text)
    if memory_block:
        system_content = MEMORY_SYSTEM_PREFIX.format(
            bot_name=BOT_NAME,
            memory_block=memory_block,
        )
    else:
        system_content = (
            f"You are {BOT_NAME}, a personal assistant. "
            "Be concise, helpful, and direct."
        )

    # ── Web search (if enabled and useful) ───────────────────────────────────
    search_context = ""
    if force_search or (SERPER_API_KEY and _looks_like_search_query(text)):
        search_results = await _web_search(text)
        if search_results:
            search_context = (
                f"\n\nCurrent web search results for \"{text[:100]}\":\n"
                f"{search_results}\n\n"
                "Use this information to answer accurately. "
                "Acknowledge if your answer is based on these results."
            )

    # ── Build GPT messages ────────────────────────────────────────────────────
    system_msg = {"role": "system", "content": system_content + search_context}

    # Cap history to avoid token overflow
    trimmed = messages[-ASK_MAX_HISTORY:] if len(messages) > ASK_MAX_HISTORY else messages

    gpt_messages = [system_msg] + trimmed + [{"role": "user", "content": text}]

    # ── Call GPT ──────────────────────────────────────────────────────────────
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=gpt_messages,
            temperature=0.7,
            max_tokens=1200,
            timeout=30,
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"handle_ask GPT error: {e}")
        await update.message.reply_text(
            "Sorry, I couldn't get a response right now. Please try again."
        )
        return

    # ── Send reply ────────────────────────────────────────────────────────────
    await update.message.reply_text(answer)

    # ── Persist thread ────────────────────────────────────────────────────────
    messages.append({"role": "user",      "content": text})
    messages.append({"role": "assistant", "content": answer})

    # Update or set topic summary on first message in thread
    if not topic_summary:
        topic_summary = await _summarize_topic(text)

    hist["messages"]      = messages[-ASK_MAX_HISTORY:]
    hist["topic_summary"] = topic_summary
    save_ask_history(hist)

    # ── Auto-suggest memorable fact (non-blocking) ────────────────────────────
    asyncio.create_task(
        suggest_memory_fact(text, answer, update, context)
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: simple heuristic to decide if web search helps
# ─────────────────────────────────────────────────────────────────────────────

def _looks_like_search_query(text: str) -> bool:
    """
    Return True if the query looks like it needs current information.
    Lightweight — no GPT call. Checks for temporal keywords.
    """
    lower = text.lower()
    triggers = [
        "latest", "current", "today", "now", "recent", "news",
        "price of", "how much is", "what is the", "who is the",
        "score", "weather", "stock", "rate", "release date",
        "when did", "when does", "what happened",
    ]
    return any(t in lower for t in triggers)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: handle_text_message
# ─────────────────────────────────────────────────────────────────────────────

async def handle_text_message(
    text:    str,
    update:  Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Handle free-text messages that fall through the intent classifier.
    Routes to handle_ask() so nothing gets dropped silently.
    """
    await handle_ask(text, update, context)
