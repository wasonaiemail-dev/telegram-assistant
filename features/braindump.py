"""
alfred/features/braindump.py
=============================
Brain Dump — stream-of-consciousness → auto-sorted todos, reminders, notes.

HOW IT WORKS
─────────────
1. User sends a raw dump of everything on their mind (can be messy, unstructured)
2. GPT parses it and returns a categorized JSON object:
     {todos: [str], reminders: [{text, time}], notes: [str], shopping: [str]}
3. Alfred creates each item in the right place and confirms with a summary
4. User gets "here's what I captured" — no back-and-forth needed

TRIGGERS
─────────
  /braindump               → prompt user to send their dump
  /braindump [text]        → process immediately
  "brain dump: [text]"     → keyword bypass
  "dump this: [text]"      → keyword bypass

DISCORD
────────
  !braindump               → same as above
  !braindump [text]        → process immediately
"""

from __future__ import annotations

import json
import logging

from core.alfred_context import AlfredContext
from core.config import GPT_CHAT_MODEL, OPENAI_API_KEY, BOT_NAME

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = f"""You are {BOT_NAME}, a personal assistant. The user is doing a brain dump —
a raw, unfiltered stream of thoughts they want to offload.

Your job is to parse it and sort each item into the right bucket:
- todos: tasks to do (no specific time required)
- reminders: things that need to happen at a specific time or date
- notes: ideas, thoughts, or information to save
- shopping: items to buy

Return ONLY valid JSON — no markdown, no explanation, no wrapper.
Format:
{{
  "todos": ["task 1", "task 2"],
  "reminders": [{{"text": "call dentist", "time": "Thursday 3pm"}}],
  "notes": ["idea about the app"],
  "shopping": ["milk", "eggs"]
}}

Rules:
- If something has a time or date → reminder
- If it's a task with no time → todo
- If it's an idea, thought, or info → note
- If it's something to buy → shopping
- Keep each item short and clean (remove filler like "I need to", "don't forget to")
- If the dump is empty or nonsensical, return all empty lists
"""


# ════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLER
# ════════════════════════════════════════════════════════════════════════════

async def cmd_braindump(ctx: AlfredContext, args: str = "") -> None:
    """
    /braindump [text]
    If no text provided, prompt the user to send their dump.
    """
    text = args.strip()
    if not text:
        await ctx.reply_markdown(
            "🧠 *Brain Dump Mode*\n\n"
            "Send me everything on your mind — tasks, reminders, ideas, shopping. "
            "Just dump it all out, messy is fine. I'll sort it.\n\n"
            "_Reply with your brain dump text, or use:_\n"
            "`/braindump [your thoughts here]`"
        )
        return

    await _process_dump(ctx, text)


# ════════════════════════════════════════════════════════════════════════════
# INTENT HANDLER
# ════════════════════════════════════════════════════════════════════════════

async def handle_braindump_intent(intent: str, ents: dict, ctx: AlfredContext) -> None:
    text = ents.get("text", "").strip()
    if not text:
        await cmd_braindump(ctx)
        return
    await _process_dump(ctx, text)


# ════════════════════════════════════════════════════════════════════════════
# CORE — PARSE + CREATE
# ════════════════════════════════════════════════════════════════════════════

async def _process_dump(ctx: AlfredContext, raw_text: str) -> None:
    """Parse the brain dump text with GPT and create all items."""

    await ctx.reply("🧠 Sorting your brain dump…")

    # ── Step 1: Parse with GPT ───────────────────────────────────────────
    parsed = await _parse_dump(raw_text)
    if parsed is None:
        await ctx.reply("Sorry, I couldn't parse that brain dump. Try again?")
        return

    todos    = parsed.get("todos", [])
    rems     = parsed.get("reminders", [])
    notes    = parsed.get("notes", [])
    shopping = parsed.get("shopping", [])

    if not any([todos, rems, notes, shopping]):
        await ctx.reply("I couldn't find anything to capture in that. Try rephrasing?")
        return

    # ── Step 2: Create everything ─────────────────────────────────────────
    from core.google_auth import is_authorized, get_tasks_service, get_calendar_service
    from adapters.google_tasks import add_todo, add_note, add_shopping_item

    if not is_authorized():
        await ctx.reply("⚠️ Not connected to Google — please run /auth first.")
        return

    svc = get_tasks_service()

    created_todos    = []
    created_rems     = []
    created_notes    = []
    created_shopping = []
    errors           = []

    # Todos
    for t in todos:
        try:
            result = add_todo(svc, t)
            if result:
                created_todos.append(t)
            else:
                errors.append(f"todo: {t}")
        except Exception as e:
            logger.warning(f"braindump: add_todo error: {e}")
            errors.append(f"todo: {t}")

    # Reminders — go through the reminder add flow
    from core.data import load_data, save_data
    import datetime
    from zoneinfo import ZoneInfo
    from core.config import TIMEZONE

    data = load_data()
    for r in rems:
        try:
            text_r = r.get("text", "")
            time_r = r.get("time", "")
            # Store as a reminder in userdata.json
            from core.data import _next_id
            rid = _next_id(data.get("reminders", []))
            data.setdefault("reminders", []).append({
                "id":         rid,
                "text":       text_r,
                "time":       time_r,
                "done":       False,
                "recur":      "none",
                "recur_next": None,
            })
            created_rems.append(f"{text_r}" + (f" ({time_r})" if time_r else ""))
        except Exception as e:
            logger.warning(f"braindump: reminder error: {e}")
            errors.append(f"reminder: {r.get('text', '?')}")

    if created_rems:
        save_data(data)

    # Notes
    for n in notes:
        try:
            result = add_note(svc, n)
            if result:
                created_notes.append(n[:60])
            else:
                errors.append(f"note: {n[:40]}")
        except Exception as e:
            logger.warning(f"braindump: add_note error: {e}")
            errors.append(f"note: {n[:40]}")

    # Shopping
    for s in shopping:
        try:
            result = add_shopping_item(svc, "grocery", s)
            if result:
                created_shopping.append(s)
            else:
                errors.append(f"shopping: {s}")
        except Exception as e:
            logger.warning(f"braindump: shopping error: {e}")
            errors.append(f"shopping: {s}")

    # ── Step 3: Send summary ──────────────────────────────────────────────
    lines = ["✅ *Brain dump captured!*\n"]

    if created_todos:
        lines.append("📋 *Todos*")
        for t in created_todos:
            lines.append(f"  • {t}")

    if created_rems:
        lines.append("\n⏰ *Reminders*")
        for r in created_rems:
            lines.append(f"  • {r}")

    if created_notes:
        lines.append("\n📝 *Notes*")
        for n in created_notes:
            lines.append(f"  • {n}")

    if created_shopping:
        lines.append("\n🛒 *Shopping*")
        for s in created_shopping:
            lines.append(f"  • {s}")

    if errors:
        lines.append(f"\n⚠️ _Failed to create: {', '.join(errors)}_")

    await ctx.reply_markdown("\n".join(lines))


# ════════════════════════════════════════════════════════════════════════════
# GPT PARSING
# ════════════════════════════════════════════════════════════════════════════

async def _parse_dump(raw_text: str) -> dict | None:
    """Send raw dump to GPT, return parsed JSON dict or None on failure."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": raw_text},
            ],
            temperature=0.2,
            max_tokens=400,
            timeout=20,
        )
        raw_json = resp.choices[0].message.content.strip()

        # Strip markdown code fences if GPT wraps it
        if raw_json.startswith("```"):
            raw_json = raw_json.split("```")[1]
            if raw_json.startswith("json"):
                raw_json = raw_json[4:]

        return json.loads(raw_json)

    except json.JSONDecodeError as e:
        logger.error(f"braindump: JSON parse error: {e}")
        return None
    except Exception as e:
        logger.error(f"braindump: GPT error: {e}")
        return None
