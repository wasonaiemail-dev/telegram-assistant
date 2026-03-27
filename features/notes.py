"""
alfred/features/notes.py
=========================
Notes management via Google Tasks (Alfred Notes list).

COMMANDS
────────
  /notes              — list all notes
  /notes [#]          — show a specific note by number
  /notes delete [#]   — delete a note by number

INTENT HANDLER
──────────────
  handle_note_intent(intent, entities, update, context)

  Supported intents:
    NOTE_ADD     — "save a note: [text]" / "note: pick up dry cleaning"
                   entities: {"text": "..."}
    NOTE_LIST    — "show my notes" / "what did I save"
    NOTE_DELETE  — "delete note 2" / "remove note about dry cleaning"
                   entities: {"number": 2} or {"text": "..."}

STORAGE
───────
  Notes live in a dedicated Google Tasks list named by GTASKS_NOTES_LIST.
  The list is auto-created if it doesn't exist.
  Each note is a task whose title is the full note text.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.config import BOT_NAME
from core.intent import NOTE_ADD, NOTE_LIST, NOTE_DELETE, NOTE_EDIT, NOTE_APPEND

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_service():
    from core.google_auth import get_tasks_service
    return get_tasks_service()


def _auth_error_msg() -> str:
    return "❌ Google Tasks isn't connected. Run /auth to connect your Google account."


def _format_note(note: dict, idx: int) -> str:
    """Format a single note for display."""
    title = note.get("title", "(empty)")
    # Truncate long notes in list view
    if len(title) > 100:
        title = title[:97] + "…"
    return f"  {idx}. {title}"


def _format_notes_list(notes: list[dict]) -> str:
    """Format all notes for Telegram."""
    if not notes:
        return "📝 *Notes*\n  _No notes saved yet._"
    lines = [f"📝 *Notes* ({len(notes)})"]
    for i, n in enumerate(notes, 1):
        lines.append(_format_note(n, i))
    return "\n".join(lines)


def _resolve_note_ref(ref, notes: list[dict]) -> dict | None:
    """Resolve a ref (int index or keyword string) to a note dict."""
    if ref is None:
        return None
    try:
        idx = int(ref) - 1
        if 0 <= idx < len(notes):
            return notes[idx]
    except (TypeError, ValueError):
        pass
    # Fall back to text search
    return _find_note_by_text(notes, str(ref))


def _find_note_by_text(notes: list[dict], query: str) -> dict | None:
    """Fuzzy-find a note by text content."""
    if not query:
        return None
    q = query.lower()
    for note in notes:
        if q in note.get("title", "").lower():
            return note
    return None


# ─────────────────────────────────────────────────────────────────────────────
# /notes COMMAND
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /notes [# | delete #]
    """
    args = context.args or []

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    from adapters.google_tasks import list_notes, delete_note

    # /notes delete [#]
    if args and args[0].lower() == "delete":
        notes = list_notes(svc)
        if not notes:
            await update.message.reply_text("No notes to delete.")
            return
        if len(args) < 2:
            await update.message.reply_text(
                "Which note? Usage: /notes delete [number]\n"
                "Run /notes to see your list."
            )
            return
        try:
            idx = int(args[1]) - 1
        except ValueError:
            await update.message.reply_text("Please provide a note number, e.g. /notes delete 2")
            return
        if not (0 <= idx < len(notes)):
            await update.message.reply_text(f"Note #{idx + 1} doesn't exist.")
            return
        note = notes[idx]
        if delete_note(svc, note["id"]):
            title = note.get("title", "(note)")[:60]
            await update.message.reply_text(
                f"✓ Deleted: _{title}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't delete that note. Try again.")
        return

    # /notes [#] — show a specific note
    if args:
        try:
            idx = int(args[0]) - 1
            notes = list_notes(svc)
            if not (0 <= idx < len(notes)):
                await update.message.reply_text(f"Note #{idx + 1} doesn't exist.")
                return
            note  = notes[idx]
            title = note.get("title", "(empty)")
            await update.message.reply_text(
                f"📝 *Note #{idx + 1}*\n\n{title}",
                parse_mode="Markdown",
            )
        except ValueError:
            await update.message.reply_text(
                "Usage: /notes [number] to view a specific note."
            )
        return

    # /notes — list all
    notes = list_notes(svc)
    await update.message.reply_text(
        _format_notes_list(notes),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_note_intent(
    intent:   str,
    entities: dict,
    update:   Update,
    context:  ContextTypes.DEFAULT_TYPE,
) -> None:
    """Dispatch all NOTE_* intents."""

    svc = _get_service()
    if not svc:
        await update.message.reply_text(_auth_error_msg())
        return

    # ── NOTE_ADD ──────────────────────────────────────────────────────────────
    if intent == NOTE_ADD:
        text = entities.get("text", "").strip()
        if not text:
            await update.message.reply_text(
                "What should I save? Try: \"note: remember to call the dentist\""
            )
            return

        from adapters.google_tasks import add_note
        result = add_note(svc, text)
        if result:
            preview = text[:80] + ("…" if len(text) > 80 else "")
            await update.message.reply_text(
                f"📝 Saved: _{preview}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't save that note. Try again.")
        return

    # ── NOTE_LIST ─────────────────────────────────────────────────────────────
    if intent == NOTE_LIST:
        from adapters.google_tasks import list_notes
        notes = list_notes(svc)
        await update.message.reply_text(
            _format_notes_list(notes),
            parse_mode="Markdown",
        )
        return

    # ── NOTE_DELETE ────────────────────────────────────────────────────────────
    if intent == NOTE_DELETE:
        number = entities.get("number")
        text   = entities.get("text", "").strip()

        from adapters.google_tasks import list_notes, delete_note
        notes = list_notes(svc)

        if not notes:
            await update.message.reply_text("No notes to delete.")
            return

        # Delete by number if provided
        if number is not None:
            try:
                idx = int(number) - 1
            except (TypeError, ValueError):
                idx = -1
            if not (0 <= idx < len(notes)):
                await update.message.reply_text(
                    f"Note #{number} doesn't exist. Run /notes to see your list."
                )
                return
            note = notes[idx]
        elif text:
            note = _find_note_by_text(notes, text)
            if not note:
                await update.message.reply_text(
                    f"Couldn't find a note matching \"{text}\". Run /notes to see your list."
                )
                return
        else:
            await update.message.reply_text(
                "Which note should I delete? Try: \"delete note 2\" or \"delete note about [topic]\""
            )
            return

        if delete_note(svc, note["id"]):
            preview = note.get("title", "(note)")[:60]
            await update.message.reply_text(
                f"✓ Deleted: _{preview}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't delete that. Try again.")
        return

    # ── NOTE_EDIT ──────────────────────────────────────────────────────────────
    if intent == NOTE_EDIT:
        ref      = entities.get("ref")
        new_text = entities.get("new_text", "").strip()
        if not new_text:
            await update.message.reply_text(
                "What should the note say? Try: \"edit note 2 to say [new text]\""
            )
            return
        from adapters.google_tasks import list_notes, update_note
        notes = list_notes(svc)
        if not notes:
            await update.message.reply_text("No notes to edit.")
            return
        note = _resolve_note_ref(ref, notes)
        if not note:
            await update.message.reply_text(
                f"Couldn't find that note. Run /notes to see your list."
            )
            return
        if update_note(svc, note["id"], new_text):
            await update.message.reply_text(
                f"✓ Note updated: _{new_text[:80]}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't update that note. Try again.")
        return

    # ── NOTE_APPEND ────────────────────────────────────────────────────────────
    if intent == NOTE_APPEND:
        ref         = entities.get("ref")
        append_text = entities.get("append_text", "").strip()
        if not append_text:
            await update.message.reply_text(
                "What should I add? Try: \"append to note 2: also bring passport\""
            )
            return
        from adapters.google_tasks import list_notes, update_note
        notes = list_notes(svc)
        if not notes:
            await update.message.reply_text("No notes to append to.")
            return
        note = _resolve_note_ref(ref, notes)
        if not note:
            await update.message.reply_text(
                f"Couldn't find that note. Run /notes to see your list."
            )
            return
        combined = note.get("title", "").rstrip(". ") + ". " + append_text
        if update_note(svc, note["id"], combined):
            await update.message.reply_text(
                f"✓ Note updated: _{combined[:80]}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Couldn't update that note. Try again.")
        return
