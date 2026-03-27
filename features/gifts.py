"""
alfred/features/gifts.py
=========================
Gift idea tracker via Google Tasks.

COMMANDS
────────
  /gifts                    — show all gift ideas
  /gifts [name]             — show gift ideas for a specific person

INTENT HANDLER
──────────────
  handle_gift_intent(intent, entities, update, context)

  Supported intents:
    GIFT_ADD     — "add gift idea for John: wireless headphones for his birthday"
                   entities: {"recipient": "...", "idea": "...",
                              "occasion": "...", "date": "YYYY-MM-DD or text"}
    GIFT_LIST    — "show gift ideas" / "what are my gift ideas for Sarah"
                   entities: {"recipient": "..."} (optional)
    GIFT_DONE    — "bought the headphones for John"
                   entities: {"recipient": "...", "idea": "..."}
    GIFT_DELETE  — "remove gift idea for John"
                   entities: {"recipient": "...", "idea": "..."}

STORAGE
───────
  Gift ideas live in the Google Tasks "Alfred: Gifts" list.
  Each task title: "{Person}: {Idea}"
  Notes: JSON with {"occasion": "...", "date": "..."}
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME
from core.intent import GIFT_ADD, GIFT_LIST, GIFT_DONE, GIFT_DELETE

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    from core.google_auth import get_tasks_service
    return get_tasks_service()


def _auth_error_msg() -> str:
    return "❌ Google Tasks isn't connected. Run /auth to connect your Google account."


def _format_gift(gift: dict, idx: int) -> str:
    """Format a single gift idea for display."""
    person   = gift.get("_person", "Unknown")
    idea     = gift.get("_idea", "(no idea)")
    meta     = gift.get("_meta", {})
    occasion = meta.get("occasion", "")
    date     = meta.get("date", "")

    extras = []
    if occasion:
        extras.append(occasion)
    if date:
        extras.append(date)

    suffix = f" _({', '.join(extras)})_" if extras else ""
    return f"  {idx}. *{person}*: {idea}{suffix}"


def _format_gifts_list(gifts: list[dict], title: str = "🎁 *Gift Ideas*") -> str:
    """Format gift list for Telegram, grouped by person."""
    if not gifts:
        return f"{title}\n  _No gift ideas saved yet._"

    # Group by person
    by_person: dict[str, list] = {}
    for g in gifts:
        person = g.get("_person", "Unknown")
        by_person.setdefault(person, []).append(g)

    sections = [title]
    for person, ideas in sorted(by_person.items()):
        sections.append(f"\n*{person}*")
        for i, g in enumerate(ideas, 1):
            idea     = g.get("_idea", "(no idea)")
            meta     = g.get("_meta", {})
            occasion = meta.get("occasion", "")
            date     = meta.get("date", "")
            extras   = [x for x in [occasion, date] if x]
            suffix   = f" _({', '.join(extras)})_" if extras else ""
            sections.append(f"  {i}. {idea}{suffix}")

    return "\n".join(sections)


def _find_gift(gifts: list[dict], person: str, idea: str = "") -> dict | None:
    """Find a gift by person name (and optionally idea substring)."""
    p_lower = person.lower().strip() if person else ""
    i_lower = idea.lower().strip() if idea else ""

    matches = []
    for g in gifts:
        gp = g.get("_person", "").lower()
        gi = g.get("_idea", "").lower()
        if p_lower and p_lower not in gp:
            continue
        if i_lower and i_lower not in gi:
            continue
        matches.append(g)

    if not matches:
        return None
    # Return best match (shortest idea title if multiple)
    return min(matches, key=lambda g: len(g.get("_idea", "")))


# ─────────────────────────────────────────────────────────────────────────────
# /gifts COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_gifts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /gifts [person_name]
    """
    args = context.args or []

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    from adapters.google_tasks import list_gifts

    if args:
        person = " ".join(args).strip()
        gifts  = list_gifts(svc, person=person)
        title  = f"🎁 *Gift Ideas for {person.title()}*"
    else:
        gifts = list_gifts(svc)
        title = "🎁 *Gift Ideas*"

    await update.message.reply_text(
        _format_gifts_list(gifts, title=title),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_gift_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all GIFT_* intents."""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # ── GIFT_ADD ──────────────────────────────────────────────────────────────
    if intent == GIFT_ADD:
        recipient = (entities.get("recipient") or "").strip()
        idea      = (entities.get("idea")      or "").strip()
        occasion  = (entities.get("occasion")  or "").strip()
        date      = (entities.get("date")      or "").strip()

        if not recipient:
            await update.message.reply_text(
                "Who is this gift for? Try: \"add gift idea for [name]: [idea]\""
            )
            return

        if not idea:
            await update.message.reply_text(
                f"What's the gift idea for {recipient}? "
                f"Try: \"gift idea for {recipient}: [idea]\""
            )
            return

        from adapters.google_tasks import add_gift
        result = add_gift(svc, person=recipient, idea=idea, occasion=occasion, date=date)
        if result:
            extras = [x for x in [occasion, date] if x]
            suffix = f" _({', '.join(extras)})_" if extras else ""
            await update.message.reply_text(
                f"🎁 Added: *{recipient}* — {idea}{suffix}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't save that gift idea. Try again.")
        return

    # ── GIFT_LIST ─────────────────────────────────────────────────────────────
    if intent == GIFT_LIST:
        recipient = (entities.get("recipient") or "").strip()
        from adapters.google_tasks import list_gifts

        if recipient:
            gifts = list_gifts(svc, person=recipient)
            title = f"🎁 *Gift Ideas for {recipient.title()}*"
        else:
            gifts = list_gifts(svc)
            title = "🎁 *Gift Ideas*"

        await update.message.reply_text(
            _format_gifts_list(gifts, title=title),
            parse_mode="Markdown",
        )
        return

    # ── GIFT_DONE ─────────────────────────────────────────────────────────────
    if intent == GIFT_DONE:
        recipient = (entities.get("recipient") or "").strip()
        idea      = (entities.get("idea")      or "").strip()

        if not recipient and not idea:
            await update.message.reply_text(
                "Which gift did you purchase? Try: \"bought [idea] for [name]\""
            )
            return

        from adapters.google_tasks import list_gifts, complete_gift
        gifts = list_gifts(svc)
        match = _find_gift(gifts, recipient, idea)

        if not match:
            query = f"{recipient}: {idea}".strip(": ")
            await update.message.reply_text(
                f"I couldn't find a gift idea matching \"{query}\". Run /gifts to see your list."
            )
            return

        if complete_gift(svc, match["id"]):
            await update.message.reply_text(
                f"🎁 Marked as purchased: *{match['_person']}* — {match['_idea']}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't mark that as purchased. Try again.")
        return

    # ── GIFT_DELETE ───────────────────────────────────────────────────────────
    if intent == GIFT_DELETE:
        recipient = (entities.get("recipient") or "").strip()
        idea      = (entities.get("idea")      or "").strip()

        if not recipient and not idea:
            await update.message.reply_text(
                "Which gift idea should I remove? Try: \"remove gift idea for [name]\""
            )
            return

        from adapters.google_tasks import list_gifts, delete_gift
        gifts = list_gifts(svc)
        match = _find_gift(gifts, recipient, idea)

        if not match:
            query = f"{recipient}: {idea}".strip(": ")
            await update.message.reply_text(
                f"I couldn't find a gift idea matching \"{query}\". Run /gifts to see your list."
            )
            return

        if delete_gift(svc, match["id"]):
            await update.message.reply_text(
                f"✓ Removed: *{match['_person']}* — {match['_idea']}",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't remove that. Try again.")
        return
