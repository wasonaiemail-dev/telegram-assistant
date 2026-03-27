"""
alfred/features/shopping.py
============================
Shopping list management via Google Tasks.

COMMANDS
────────
  /shopping                 — show all shopping lists (grouped by list)
  /shopping [list]          — show one list  e.g. /shopping grocery
  /shopping clear [list]    — remove all checked items from a list

INTENT HANDLER
──────────────
  handle_shopping_intent(intent, entities, update, context)

  Supported intents:
    SHOP_ADD      — "add milk to grocery list" / "add soap to household"
                    entities: {"item": "...", "list": "grocery|household|wishlist"}
    SHOP_LIST     — "show grocery list" / "what do I need to buy"
                    entities: {"list": "grocery|household|wishlist|all"}
    SHOP_COMPLETE — "got the milk" / "check off milk"
                    entities: {"item": "...", "list": "..."}
    SHOP_DELETE   — "remove milk from list" / "delete milk"
                    entities: {"item": "...", "list": "..."}
    SHOP_CLEAR    — "clear completed from grocery" / "clean up shopping list"
                    entities: {"list": "..."}

AUTO-ROUTING
────────────
  When an item is added without specifying a list, Alfred checks
  SHOPPING_KEYWORDS to auto-route it (e.g. "detergent" → household).
  Falls back to "grocery" if no keyword matches.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME, SHOPPING_KEYWORDS


def _get_lists() -> dict:
    """
    Return effective shopping list dict {key: display_label}.
    Uses buyer-configured list names from userdata if set (setup wizard);
    falls back to the static _get_lists() config dict.
    """
    try:
        from core.data import load_data, get_shopping_list_names
        data  = load_data()
        names = get_shopping_list_names(data)
        return {n.lower().replace(" ", "_"): n.title() for n in names}
    except Exception:
        return dict(_get_lists())
from core.intent import (
    SHOP_ADD, SHOP_LIST, SHOP_COMPLETE, SHOP_DELETE, SHOP_CLEAR,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    from core.google_auth import get_tasks_service
    return get_tasks_service()


def _auth_error_msg() -> str:
    return "❌ Google Tasks isn't connected. Run /auth to connect your Google account."


def _auto_route_list(item_text: str) -> str:
    """
    Guess which shopping list an item belongs to by keyword matching.
    Returns a list key (e.g. "grocery", "household", "wishlist").
    Defaults to "grocery".
    """
    item_lower = item_text.lower()
    for list_key, keywords in SHOPPING_KEYWORDS.items():
        if any(kw in item_lower for kw in keywords):
            return list_key
    return "grocery"


def _normalize_list_key(raw: str) -> str | None:
    """
    Map user input to a valid list key.
    Accepts exact keys, label matches, and common shorthands.
    Returns None if no match.
    """
    raw = raw.lower().strip()
    # Direct key match
    if raw in _get_lists():
        return raw
    # Label match (case-insensitive)
    for key, label in _get_lists().items():
        if raw == label.lower():
            return key
    # Partial match (first letter or prefix)
    matches = [k for k in _get_lists() if k.startswith(raw)]
    if len(matches) == 1:
        return matches[0]
    return None


def _format_list(items: list[dict], list_label: str) -> str:
    """Format a single shopping list for Telegram."""
    if not items:
        return f"🛒 *{list_label}*\n  _Nothing on this list._"
    lines = [f"🛒 *{list_label}*"]
    for i, item in enumerate(items, 1):
        title = item.get("title", "(untitled)")
        lines.append(f"  {i}. {title}")
    return "\n".join(lines)


def _format_all_lists(all_items: dict[str, list[dict]]) -> str:
    """Format all shopping lists together."""
    sections = []
    for key, label in _get_lists().items():
        items = all_items.get(key, [])
        sections.append(_format_list(items, label))
    combined = "\n\n".join(sections)
    return combined or "🛒 *Shopping Lists*\n  _All lists are empty._"


def _find_item(items: list[dict], query: str) -> dict | None:
    """Fuzzy-find an item by title."""
    if not query:
        return None
    q = query.lower()
    for item in items:
        if item.get("title", "").lower() == q:
            return item
    matches = [i for i in items if q in i.get("title", "").lower()]
    if not matches:
        return None
    return min(matches, key=lambda i: len(i.get("title", "")))


# ─────────────────────────────────────────────────────────────────────────────
# /shopping COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /shopping [list_name | clear list_name]
    """
    args = context.args or []

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # /shopping clear [list]
    if args and args[0].lower() == "clear":
        list_key = _normalize_list_key(args[1]) if len(args) > 1 else None
        if not list_key:
            keys_str = ", ".join(_get_lists().keys())
            await update.message.reply_text(
                f"Which list? Options: {keys_str}\n"
                f"Example: /shopping clear grocery",
            )
            return
        from adapters.google_tasks import clear_completed_shopping
        removed = clear_completed_shopping(svc, list_key)
        label   = _get_lists()[list_key]
        await update.message.reply_text(
            f"✓ Cleared {removed} checked item(s) from *{label}*.",
            parse_mode="Markdown",
        )
        return

    # /shopping [list_name] — show one list
    if args:
        list_key = _normalize_list_key(args[0])
        if not list_key:
            keys_str = ", ".join(_get_lists().keys())
            await update.message.reply_text(
                f"Unknown list. Options: {keys_str}"
            )
            return
        from adapters.google_tasks import list_shopping
        items = list_shopping(svc, list_key, include_done=False)
        label = _get_lists()[list_key]
        await update.message.reply_text(
            _format_list(items, label),
            parse_mode="Markdown",
        )
        return

    # /shopping — show all lists
    from adapters.google_tasks import list_all_shopping
    all_items = list_all_shopping(svc)
    await update.message.reply_text(
        _format_all_lists(all_items),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_shopping_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all SHOP_* intents."""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # ── SHOP_ADD ──────────────────────────────────────────────────────────────
    if intent == SHOP_ADD:
        item_text = entities.get("item", "").strip()
        if not item_text:
            await update.message.reply_text(
                "What should I add? Try: \"add milk to the grocery list\""
            )
            return

        list_key = _normalize_list_key(entities.get("list", "")) or _auto_route_list(item_text)
        label    = _get_lists().get(list_key, list_key.title())

        from adapters.google_tasks import add_shopping_item
        result = add_shopping_item(svc, list_key, item_text)
        if result:
            await update.message.reply_text(
                f"✓ Added *{item_text}* to *{label}*.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"Couldn't add that to {label}. Try again.")
        return

    # ── SHOP_LIST ─────────────────────────────────────────────────────────────
    if intent == SHOP_LIST:
        raw_list = entities.get("list", "all")
        if raw_list in ("all", "", None):
            from adapters.google_tasks import list_all_shopping
            all_items = list_all_shopping(svc)
            await update.message.reply_text(
                _format_all_lists(all_items),
                parse_mode="Markdown",
            )
        else:
            list_key = _normalize_list_key(raw_list)
            if not list_key:
                keys_str = ", ".join(_get_lists().keys())
                await update.message.reply_text(f"Unknown list. Options: {keys_str}")
                return
            from adapters.google_tasks import list_shopping
            items = list_shopping(svc, list_key, include_done=False)
            label = _get_lists()[list_key]
            await update.message.reply_text(
                _format_list(items, label),
                parse_mode="Markdown",
            )
        return

    # ── SHOP_COMPLETE ─────────────────────────────────────────────────────────
    if intent == SHOP_COMPLETE:
        item_query = entities.get("item", "").strip()
        list_key   = _normalize_list_key(entities.get("list", "")) if entities.get("list") else None

        # Search in specified list, or all lists
        from adapters.google_tasks import list_shopping, complete_shopping_item
        lists_to_search = [list_key] if list_key else list(_get_lists().keys())

        for key in lists_to_search:
            items = list_shopping(svc, key, include_done=False)
            match = _find_item(items, item_query)
            if match:
                label = _get_lists()[key]
                if complete_shopping_item(svc, key, match["id"]):
                    await update.message.reply_text(
                        f"✓ Checked off *{match['title']}* from *{label}*.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text("Couldn't check that off. Try again.")
                return

        await update.message.reply_text(
            f"I couldn't find \"{item_query}\" on any shopping list."
        )
        return

    # ── SHOP_DELETE ───────────────────────────────────────────────────────────
    if intent == SHOP_DELETE:
        item_query = entities.get("item", "").strip()
        list_key   = _normalize_list_key(entities.get("list", "")) if entities.get("list") else None

        from adapters.google_tasks import list_shopping, delete_shopping_item
        lists_to_search = [list_key] if list_key else list(_get_lists().keys())

        for key in lists_to_search:
            items = list_shopping(svc, key, include_done=False)
            match = _find_item(items, item_query)
            if match:
                label = _get_lists()[key]
                if delete_shopping_item(svc, key, match["id"]):
                    await update.message.reply_text(
                        f"✓ Removed *{match['title']}* from *{label}*.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text("Couldn't remove that. Try again.")
                return

        await update.message.reply_text(
            f"I couldn't find \"{item_query}\" on any shopping list."
        )
        return

    # ── SHOP_CLEAR ────────────────────────────────────────────────────────────
    if intent == SHOP_CLEAR:
        raw_list = entities.get("list", "")
        list_key = _normalize_list_key(raw_list) if raw_list else None

        if not list_key:
            # Clear all lists
            from adapters.google_tasks import clear_completed_shopping
            total = 0
            for key in _get_lists():
                total += clear_completed_shopping(svc, key)
            await update.message.reply_text(
                f"✓ Cleared {total} checked item(s) from all shopping lists.",
            )
        else:
            from adapters.google_tasks import clear_completed_shopping
            removed = clear_completed_shopping(svc, list_key)
            label   = _get_lists()[list_key]
            await update.message.reply_text(
                f"✓ Cleared {removed} checked item(s) from *{label}*.",
                parse_mode="Markdown",
            )
        return


# ─────────────────────────────────────────────────────────────────────────────
# RECEIPT SCANNING
# ─────────────────────────────────────────────────────────────────────────────

async def handle_receipt_photo(file_path: str, update, context) -> None:
    """
    Process a receipt photo: GPT-4o vision extracts purchased items,
    then removes matching items from all shopping lists.
    """
    import base64
    from openai import AsyncOpenAI
    from core.config import OPENAI_API_KEY
    import json as _json

    await update.message.reply_text("📄 Reading receipt…")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "This is a shopping receipt. Extract all purchased item names as a JSON array of lowercase strings. "
                            "Normalize names (e.g. 'ORGANIC WHOLE MILK 1GAL' → 'whole milk'). "
                            "Include only grocery/household items, not taxes, totals, or store name. "
                            "Return ONLY valid JSON like: [\"milk\", \"eggs\", \"bread\"]"
                        )
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}}
                ]
            }],
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        parsed = _json.loads(raw)
        # GPT sometimes returns {"items": [...]} or just [...]
        if isinstance(parsed, dict):
            receipt_items = parsed.get("items", parsed.get("products", []))
        else:
            receipt_items = parsed
        receipt_items = [str(i).lower().strip() for i in receipt_items if i]
    except Exception as e:
        logger.warning(f"Receipt extraction failed: {e}")
        await update.message.reply_text("Sorry, I couldn't read that receipt.")
        return

    if not receipt_items:
        await update.message.reply_text("I couldn't find any items on that receipt.")
        return

    # Match and remove from shopping lists using Google Tasks
    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    from adapters.google_tasks import list_shopping, delete_shopping_item

    removed = []
    unmatched_receipt = list(receipt_items)

    for list_key in _get_lists():
        items = list_shopping(svc, list_key, include_done=False)
        label = _get_lists()[list_key]

        for item in items:
            item_lower = item.get("title", "").lower()
            matched = False
            for ri in receipt_items:
                # Match if receipt item is contained in shopping item or vice versa
                if ri in item_lower or item_lower in ri or _fuzzy_match(ri, item_lower):
                    removed.append(f"{item.get('title')} ({label})")
                    delete_shopping_item(svc, list_key, item.get("id"))
                    if ri in unmatched_receipt:
                        unmatched_receipt.remove(ri)
                    matched = True
                    break

    if not removed:
        # No matches, but still show what was found
        await update.message.reply_text(
            f"No items from this receipt matched your shopping lists.\n\n"
            f"Items on the receipt: {', '.join(receipt_items[:10])}"
        )
        return

    # Build response showing removed items and remaining list
    lines = [f"✅ Removed {len(removed)} items from your shopping lists:"]
    for r in removed:
        lines.append(f"  • {r}")

    still_on_list = []
    for list_key in _get_lists():
        items = list_shopping(svc, list_key, include_done=False)
        label = _get_lists()[list_key]
        for item in items:
            still_on_list.append(f"{item.get('title')} ({label})")

    if still_on_list:
        lines.append(f"\n📋 Still on your lists ({len(still_on_list)} items):")
        for item in still_on_list[:10]:
            lines.append(f"  • {item}")
        if len(still_on_list) > 10:
            lines.append(f"  … and {len(still_on_list) - 10} more")

    await update.message.reply_text("\n".join(lines))


def _fuzzy_match(a: str, b: str) -> bool:
    """Very simple fuzzy match: check if all words in shorter string appear in longer."""
    words_a = set(a.split())
    words_b = set(b.split())
    shorter = words_a if len(words_a) <= len(words_b) else words_b
    longer  = words_a if len(words_a) > len(words_b) else words_b
    if not shorter:
        return False
    return len(shorter & longer) / len(shorter) >= 0.6
