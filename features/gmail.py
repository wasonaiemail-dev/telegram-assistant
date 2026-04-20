"""
alfred/features/gmail.py
========================
Gmail integration for Alfred.

COMMANDS
────────
  (none — all interaction is via natural language)

INTENT HANDLER
──────────────
  handle_gmail_intent(intent, entities, ctx)

  Supported intents:
    GMAIL_SEND   — "email John that I'll be 10 minutes late"
                   "send an email to boss@work.com saying I'm out today"
                   entities: {"to": "...", "subject": "...", "body": "..."}

    GMAIL_DRAFT  — "draft an email to my landlord about the broken heater"
                   "save a draft email to mom about the birthday party"
                   entities: {"to": "...", "subject": "...", "body": "..."}

    GMAIL_UNREAD — "how many unread emails do I have?"
                   "check my inbox"
                   "any emails from my VIPs?"
                   entities: {}

HOW SEND WORKS
──────────────
  1. GPT extracts to/subject/body from the user's message
  2. If body is missing or vague, GPT drafts the full email body
  3. Alfred sends a preview and asks for confirmation
  4. User confirms by replying "yes", "send it", "do it", etc.
  5. Alfred sends via Gmail API

HOW DRAFT WORKS
───────────────
  1. GPT extracts to/subject/body
  2. GPT drafts the email body if body is vague
  3. Alfred saves to Gmail Drafts and confirms
  4. No confirmation step needed — saving a draft is non-destructive

HOW UNREAD WORKS
────────────────
  Returns unread count + VIP email highlights (if GMAIL_VIP_SENDERS is set)
"""

import logging
import re as _re

from core.alfred_context import AlfredContext
from core.config import BOT_NAME, OPENAI_API_KEY, GPT_CHAT_MODEL, GMAIL_VIP_SENDERS, GMAIL_DEFAULT_SIGNATURE
from core.intent import GMAIL_SEND, GMAIL_DRAFT, GMAIL_UNREAD

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _auth_error() -> str:
    return "❌ Gmail isn't connected. Run /auth to connect your Google account."


def _get_service():
    from core.google_auth import get_gmail_service
    return get_gmail_service()


def _resolve_recipient(raw_to: str) -> str:
    """
    Try to resolve a name like "John" to a full email address via contacts.
    Returns the raw_to unchanged if no match found.
    """
    if "@" in raw_to:
        return raw_to  # Already an email address

    try:
        from core.data import load_contacts
        contacts = load_contacts()
        name_lower = raw_to.lower().strip()
        for c in contacts:
            if name_lower in c.get("name", "").lower():
                email = c.get("email", "")
                if email:
                    return email
    except Exception:
        pass

    return raw_to  # Return unchanged — user may need to clarify


async def _gpt_extract_email_fields(raw_text: str) -> dict:
    """
    Use GPT to extract to/subject/body from a raw send-email instruction.
    Returns dict with keys: to, subject, body.
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            'Extract the email fields from this instruction. Return JSON only.\n\n'
            f'Instruction: "{raw_text}"\n\n'
            'Return: {"to": "recipient name or email", "subject": "inferred subject", "body": "message content or instruction"}\n'
            'If a field cannot be determined, use an empty string. Subject should be inferred from context.'
        )
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        import json as _json
        return _json.loads(resp.choices[0].message.content.strip())
    except Exception as e:
        logger.error(f"_gpt_extract_email_fields: {e}")
        return {"to": "", "subject": "", "body": raw_text}


async def _gpt_draft_email(to: str, subject: str, user_instruction: str) -> str:
    """
    Use GPT to write a complete email body from the user's instruction.
    """
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            f"Write a short, natural email body (no greeting or sign-off needed — "
            f"I'll add those) based on this instruction:\n\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"Instruction: {user_instruction}\n\n"
            "Write only the body text. 2–4 sentences. Casual but professional tone."
        )

        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"_gpt_draft_email: {e}")
        return user_instruction  # Fall back to raw instruction as body


def _format_email_preview(to: str, subject: str, body: str) -> str:
    lines = [
        "📧 *Email Preview*",
        f"*To:* {to}",
        f"*Subject:* {subject}",
        "",
        body,
    ]
    if GMAIL_DEFAULT_SIGNATURE:
        lines.extend(["", f"—\n{GMAIL_DEFAULT_SIGNATURE}"])
    return "\n".join(lines)


def _add_signature(body: str) -> str:
    if GMAIL_DEFAULT_SIGNATURE:
        return f"{body}\n\n—\n{GMAIL_DEFAULT_SIGNATURE}"
    return body


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_gmail_intent(
    intent:   str,
    entities: dict,
    ctx:      AlfredContext,
) -> None:
    """Dispatch all GMAIL_* intents."""

    # ── GMAIL_UNREAD ─────────────────────────────────────────────────────────
    if intent == GMAIL_UNREAD:
        svc = _get_service()
        if not svc:
            await ctx.reply(_auth_error())
            return

        from adapters.gmail import get_unread_count, get_vip_emails
        count = get_unread_count(svc)

        lines = [f"📬 *Inbox*\n  {count} unread email{'s' if count != 1 else ''}"]

        if GMAIL_VIP_SENDERS:
            vip_emails = get_vip_emails(svc, GMAIL_VIP_SENDERS)
            if vip_emails:
                lines.append("\n⭐ *VIP Unread*")
                for e in vip_emails[:5]:
                    sender = e["from"].split("<")[0].strip().rstrip(",").strip()
                    subj   = e["subject"][:60]
                    lines.append(f"  • *{sender}* — {subj}")

        await ctx.reply_markdown("\n".join(lines))
        return

    # ── GMAIL_SEND ────────────────────────────────────────────────────────────
    if intent == GMAIL_SEND:
        svc = _get_service()
        if not svc:
            await ctx.reply(_auth_error())
            return

        raw_to  = entities.get("to", "").strip()
        subject = entities.get("subject", "").strip()
        body    = entities.get("body", "").strip()
        original_instruction = ctx.text if hasattr(ctx, "text") else body

        # Keyword route sends empty entities — extract to/subject/body
        if not raw_to:
            raw_text = ctx.text or body
            # 1) Quick regex: pull email address directly if present (fast, no GPT needed)
            _email_match = _re.search(r'\b[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}\b', raw_text)
            if _email_match:
                raw_to = _email_match.group(0)
            else:
                # 2) Fallback: ask GPT to parse name-based recipients ("email John that...")
                extracted = await _gpt_extract_email_fields(raw_text)
                raw_to  = extracted.get("to", "").strip()
                subject = extracted.get("subject", "").strip()
                body    = extracted.get("body", "").strip()

        if not raw_to:
            await ctx.reply('Who should I email? Try: "email john@example.com that I\'ll be late"')
            return

        to = _resolve_recipient(raw_to)

        # Auto-generate subject if missing
        if not subject:
            subject = f"Message from {BOT_NAME}"

        # Draft body via GPT if body is vague or missing
        if not body or len(body) < 15:
            await ctx.reply("✍️ Drafting your email...")
            body = await _gpt_draft_email(to, subject, original_instruction)

        # Show preview + ask for confirmation using pending state
        preview = _format_email_preview(to, subject, body)
        await ctx.reply_markdown(
            f"{preview}\n\n"
            "_Reply *yes* to send, or *no* to cancel._"
        )

        # Save the pending email in data so the confirmation handler can find it
        try:
            from core.data import load_data, save_data
            data = load_data()
            data["pending_gmail"] = {
                "action":  "send",
                "to":      to,
                "subject": subject,
                "body":    _add_signature(body),
            }
            save_data(data)
        except Exception as e:
            logger.error(f"GMAIL_SEND: could not save pending: {e}")
        return

    # ── GMAIL_DRAFT ───────────────────────────────────────────────────────────
    if intent == GMAIL_DRAFT:
        svc = _get_service()
        if not svc:
            await ctx.reply(_auth_error())
            return

        raw_to  = entities.get("to", "").strip()
        subject = entities.get("subject", "").strip()
        body    = entities.get("body", "").strip()
        original_instruction = ctx.text if hasattr(ctx, "text") else body

        # Keyword route sends empty entities — extract to/subject/body
        if not raw_to:
            raw_text = ctx.text or body
            _email_match = _re.search(r'\b[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}\b', raw_text)
            if _email_match:
                raw_to = _email_match.group(0)
            else:
                extracted = await _gpt_extract_email_fields(raw_text)
                raw_to  = extracted.get("to", "").strip()
                subject = extracted.get("subject", "").strip()
                body    = extracted.get("body", "").strip()

        if not raw_to:
            await ctx.reply('Who\'s the draft for? Try: "draft an email to my landlord about..."')
            return

        to = _resolve_recipient(raw_to)

        if not subject:
            subject = f"Draft from {BOT_NAME}"

        if not body or len(body) < 15:
            await ctx.reply("✍️ Drafting your email...")
            body = await _gpt_draft_email(to, subject, original_instruction)

        from adapters.gmail import create_draft
        draft_id = create_draft(svc, to, subject, _add_signature(body))

        if draft_id:
            preview = _format_email_preview(to, subject, body)
            await ctx.reply_markdown(
                f"{preview}\n\n"
                "✅ _Saved to Gmail Drafts. Open Gmail to review and send._"
            )
        else:
            await ctx.reply("Couldn't save the draft. Try again.")
        return


# ─────────────────────────────────────────────────────────────────────────────
# CONFIRMATION HANDLER
# Called by bot.py when user replies "yes" / "send it" to a pending email
# ─────────────────────────────────────────────────────────────────────────────

_CONFIRM_WORDS = {"yes", "send", "send it", "do it", "confirm", "ok", "okay", "go", "yep", "yup", "sure"}
_CANCEL_WORDS  = {"no", "cancel", "stop", "nope", "don't", "dont", "nevermind", "never mind", "abort"}


def is_gmail_confirmation(text: str) -> bool:
    """Return True if the text looks like a confirmation or cancellation of a pending email."""
    tl = text.lower().strip().rstrip(".")
    return tl in _CONFIRM_WORDS or tl in _CANCEL_WORDS


async def handle_gmail_confirmation(text: str, ctx: AlfredContext) -> bool:
    """
    Handle a confirmation or cancellation for a pending email send.

    Returns True if a pending email was found and handled, False otherwise.
    """
    try:
        from core.data import load_data, save_data
        data = load_data()
        pending = data.get("pending_gmail")
        if not pending or pending.get("action") != "send":
            return False

        tl = text.lower().strip().rstrip(".")

        if tl in _CANCEL_WORDS:
            data.pop("pending_gmail", None)
            save_data(data)
            await ctx.reply("Cancelled. Email not sent.")
            return True

        if tl in _CONFIRM_WORDS:
            svc = _get_service()
            if not svc:
                data.pop("pending_gmail", None)
                save_data(data)
                await ctx.reply(_auth_error())
                return True

            from adapters.gmail import send_email
            ok = send_email(svc, pending["to"], pending["subject"], pending["body"])

            data.pop("pending_gmail", None)
            save_data(data)

            if ok:
                to_display = pending["to"]
                subj_display = pending["subject"][:60]
                await ctx.reply_markdown(
                    f"✅ Email sent to *{to_display}*\n_{subj_display}_"
                )
            else:
                await ctx.reply("Couldn't send the email. Check your Gmail connection with /checkauth.")
            return True

    except Exception as e:
        logger.error(f"handle_gmail_confirmation: {e}")

    return False


# ─────────────────────────────────────────────────────────────────────────────
# BRIEFING SECTION
# Called by features/briefing.py
# ─────────────────────────────────────────────────────────────────────────────

async def get_gmail_briefing_section() -> str:
    """
    Returns unread count + VIP emails for the morning briefing.
    Returns empty string if Gmail isn't connected or inbox is empty.
    """
    try:
        from core.google_auth import get_gmail_service
        svc = get_gmail_service()
        if not svc:
            return ""

        from adapters.gmail import get_unread_count, get_vip_emails
        count = get_unread_count(svc)

        if count == 0 and not GMAIL_VIP_SENDERS:
            return ""

        lines = [f"📬 *Inbox — {count} unread*"]

        if GMAIL_VIP_SENDERS:
            vip_emails = get_vip_emails(svc, GMAIL_VIP_SENDERS)
            if vip_emails:
                lines.append("⭐ *VIP*")
                for e in vip_emails[:3]:
                    sender = e["from"].split("<")[0].strip().rstrip(",").strip()
                    subj   = e["subject"][:55]
                    lines.append(f"  • *{sender}* — {subj}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"get_gmail_briefing_section: {e}")
        return ""
