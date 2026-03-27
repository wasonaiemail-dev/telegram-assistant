"""
alfred/features/contacts.py
============================
Personal contacts — notes about people the buyer knows.

COMMANDS
────────
  /contacts                  — list all contacts
  /contacts [name]           — view notes for a specific person
  /contacts add [name]       — add a new contact (prompts for notes)
  /contacts delete [name]    — delete a contact

INTENT HANDLER
──────────────
  handle_contact_intent(intent, entities, update, context)

  Supported intents:
    CONTACT_VIEW    — "what do I know about Sarah" / "tell me about John"
                      entities: {"name": "..."}
    CONTACT_ADD     — "add a note about Mike: he prefers email"
                      entities: {"name": "...", "note": "..."}
    CONTACT_UPDATE  — "update notes for Sarah: she moved to Austin"
                      entities: {"name": "...", "note": "..."}

STORAGE
───────
  Contacts live in contacts.json:
  {
    "Sarah Johnson": ["prefers text over calls", "birthday: June 12"],
    "John Smith":    ["coffee always, no meetings before 10am"],
    ...
  }

CONTEXT INJECTION
─────────────────
  When Alfred detects a name in a /ask query, contact notes are prepended
  to the GPT system prompt via get_contact_context(name) below.
  This is consumed by features/ask.py when CONTACT_SYSTEM_ADDON is relevant.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME
from core.intent import CONTACT_VIEW, CONTACT_ADD, CONTACT_UPDATE

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load() -> dict:
    from core.data import load_contacts
    return load_contacts()


def _save(contacts: dict) -> None:
    from core.data import save_contacts
    save_contacts(contacts)


def _find_contact(contacts: dict, query: str) -> tuple[str, list] | tuple[None, None]:
    """
    Fuzzy-find a contact by name (case-insensitive, substring OK).
    Returns (canonical_name, notes) or (None, None) if not found.
    """
    q = query.lower().strip()
    # Exact match
    for name in contacts:
        if name.lower() == q:
            return name, contacts[name]
    # Substring match
    matches = [(n, contacts[n]) for n in contacts if q in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Return closest (shortest name)
        return min(matches, key=lambda x: len(x[0]))
    return None, None


def _format_contact(name: str, notes: list) -> str:
    """Format a contact and their notes for display."""
    if not notes:
        return f"👤 *{name}*\n  _No notes yet._"
    lines = [f"👤 *{name}*"]
    for note in notes:
        lines.append(f"  • {note}")
    return "\n".join(lines)


def _format_contacts_list(contacts: dict) -> str:
    """Format all contacts as a compact list."""
    if not contacts:
        return "👥 *Contacts*\n  _No contacts saved yet._\n\nAdd one with: /contacts add [name]"
    lines = [f"👥 *Contacts* ({len(contacts)})"]
    for name in sorted(contacts.keys()):
        note_count = len(contacts[name])
        lines.append(f"  • {name} _({note_count} note(s))_")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC: get_contact_context  (used by ask.py for context injection)
# ─────────────────────────────────────────────────────────────────────────────

def get_contact_context(name: str) -> str:
    """
    Return contact notes as a formatted string for injecting into GPT context.
    Returns empty string if contact not found.
    """
    contacts = _load()
    canon, notes = _find_contact(contacts, name)
    if not canon or not notes:
        return ""
    lines = [f"Notes about {canon}:"]
    for note in notes:
        lines.append(f"  - {note}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# /contacts COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /contacts [name | add name | delete name]
    """
    args = context.args or []
    contacts = _load()

    if not args:
        await update.message.reply_text(
            _format_contacts_list(contacts),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()

    # /contacts add [name]
    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text("Usage: /contacts add [name]")
            return
        name = " ".join(args[1:]).strip().title()
        if name in contacts:
            await update.message.reply_text(
                f"*{name}* already exists. "
                f"To add notes, say: \"add note about {name}: [note]\"",
                parse_mode="Markdown",
            )
            return
        contacts[name] = []
        _save(contacts)
        await update.message.reply_text(
            f"✓ Added *{name}* to contacts. "
            f"Add notes with: \"note about {name}: [detail]\"",
            parse_mode="Markdown",
        )
        return

    # /contacts delete [name]
    if sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("Usage: /contacts delete [name]")
            return
        query = " ".join(args[1:]).strip()
        canon, _ = _find_contact(contacts, query)
        if not canon:
            await update.message.reply_text(
                f"No contact found matching \"{query}\"."
            )
            return
        del contacts[canon]
        _save(contacts)
        await update.message.reply_text(
            f"✓ Deleted contact: *{canon}*",
            parse_mode="Markdown",
        )
        return

    # /contacts [name] — view a specific contact
    query = " ".join(args).strip()
    canon, notes = _find_contact(contacts, query)
    if not canon:
        await update.message.reply_text(
            f"No contact found matching \"{query}\". Run /contacts to see your list."
        )
        return
    await update.message.reply_text(
        _format_contact(canon, notes or []),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_contact_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all CONTACT_* intents."""

    contacts = _load()

    # ── CONTACT_VIEW ──────────────────────────────────────────────────────────
    if intent == CONTACT_VIEW:
        name = (entities.get("name") or "").strip()
        if not name:
            await update.message.reply_text(
                _format_contacts_list(contacts),
                parse_mode="Markdown",
            )
            return
        canon, notes = _find_contact(contacts, name)
        if not canon:
            await update.message.reply_text(
                f"No contact found matching \"{name}\". Run /contacts to see your list."
            )
            return
        await update.message.reply_text(
            _format_contact(canon, notes or []),
            parse_mode="Markdown",
        )
        return

    # ── CONTACT_ADD ───────────────────────────────────────────────────────────
    if intent == CONTACT_ADD:
        name = (entities.get("name") or "").strip()
        note = (entities.get("note") or "").strip()

        if not name:
            await update.message.reply_text(
                "Who should I add? Try: \"add a note about [name]: [detail]\""
            )
            return

        # Normalize name
        name_title = name.title()

        # Find or create contact
        canon, existing_notes = _find_contact(contacts, name)
        if canon:
            # Add note to existing contact
            if note:
                contacts[canon].append(note)
                _save(contacts)
                await update.message.reply_text(
                    f"✓ Added note to *{canon}*: _{note}_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"*{canon}* already exists. What note should I add?\n"
                    f"Try: \"add note about {canon}: [detail]\"",
                    parse_mode="Markdown",
                )
        else:
            # New contact
            contacts[name_title] = [note] if note else []
            _save(contacts)
            if note:
                await update.message.reply_text(
                    f"✓ Added *{name_title}* with note: _{note}_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"✓ Added *{name_title}* to contacts.",
                    parse_mode="Markdown",
                )
        return

    # ── CONTACT_UPDATE ────────────────────────────────────────────────────────
    if intent == CONTACT_UPDATE:
        name = (entities.get("name") or "").strip()
        note = (entities.get("note") or "").strip()

        if not name:
            await update.message.reply_text(
                "Who should I update? Try: \"update [name]: [new note]\""
            )
            return

        canon, existing_notes = _find_contact(contacts, name)
        if not canon:
            # Create them if they don't exist
            name_title = name.title()
            contacts[name_title] = [note] if note else []
            _save(contacts)
            await update.message.reply_text(
                f"✓ Added *{name_title}* with note: _{note}_",
                parse_mode="Markdown",
            )
            return

        if not note:
            await update.message.reply_text(
                f"What should I add for *{canon}*? "
                f"Try: \"update {canon}: [note]\"",
                parse_mode="Markdown",
            )
            return

        contacts[canon].append(note)
        _save(contacts)
        await update.message.reply_text(
            f"✓ Updated *{canon}*: _{note}_",
            parse_mode="Markdown",
        )
        return
