"""
alfred/features/reply_assist.py
================================
Screenshot and email reply drafting assistant.

CAPABILITIES
────────────
  • Photo of a text message conversation → 3 draft replies in the buyer's
    configured tone (warm / professional / casual / playful)
  • Photo of an email → draft email reply
  • Pasted email text → draft email reply
  • Context injection: buyer types a description before sending the photo
  • Contact lookup: if the sender is in contacts, Alfred knows their background
  • Clarifying question: if the screenshot is ambiguous, Alfred asks first
  • Iterative refinement: "make it shorter / warmer / more formal"
  • Style library: buyer can save example messages to fine-tune Alfred's voice

COMMANDS
────────
  None — triggered by:
    • Sending a photo (Alfred detects if it's a text/email screenshot)
    • Typing context then sending the photo
    • Explicit intent (REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD)

STATE
─────
  userdata["settings"]["_pending_reply_context"]  — brief context typed before photo
  userdata["settings"]["_last_reply_draft"]       — last draft sent (for refinement)
  style_library.json — buyer's saved style examples
"""

import logging
import os

from core.config import OPENAI_API_KEY, GPT_CHAT_MODEL
from core.intent import REPLY_ASSIST, EMAIL_ASSIST, REPLY_STYLE_ADD
from core.data import (
    load_data, save_data,
    load_contacts,
    load_style_library, save_style_library,
    get_reply_settings,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# TONE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

_TONE_LABELS = {
    "warm":         "Warm & friendly",
    "professional": "Professional & clear",
    "casual":       "Casual & relaxed",
    "playful":      "Playful & light",
}

_TONE_INSTRUCTIONS = {
    "warm":         "Write warmly and with genuine care. Friendly, supportive, personal.",
    "professional": "Write professionally and clearly. Concise, respectful, no slang.",
    "casual":       "Write casually as if texting a friend. Relaxed, natural, brief.",
    "playful":      "Write in a playful, light tone. A bit of humour is welcome.",
}

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT STORAGE
# ─────────────────────────────────────────────────────────────────────────────

def set_pending_context(text: str) -> None:
    """Store a user's pre-photo context note."""
    data = load_data()
    data.setdefault("settings", {})["_pending_reply_context"] = text.strip()
    save_data(data)


def pop_pending_context() -> str | None:
    """Retrieve and clear the pending reply context."""
    data    = load_data()
    ctx     = data.get("settings", {}).get("_pending_reply_context")
    if ctx:
        data["settings"]["_pending_reply_context"] = None
        save_data(data)
    return ctx


def set_last_draft(draft_text: str) -> None:
    data = load_data()
    data.setdefault("settings", {})["_last_reply_draft"] = draft_text
    save_data(data)


def get_last_draft() -> str | None:
    return load_data().get("settings", {}).get("_last_reply_draft")


# ─────────────────────────────────────────────────────────────────────────────
# GPT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _gpt_reply_from_image(image_b64: str, context_hint: str, tone: str,
                                 style_examples: list[str], contact_ctx: str,
                                 is_email: bool = False) -> str:
    """Use GPT-4o vision to read the screenshot and draft replies."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["warm"])
    medium           = "email" if is_email else "text message"

    style_block = ""
    if style_examples:
        examples_str = "\n".join(f"  - {e}" for e in style_examples[:5])
        style_block  = f"\n\nHere are examples of the user's preferred writing style:\n{examples_str}"

    contact_block = f"\n\nContext about the person in this conversation:\n{contact_ctx}" if contact_ctx else ""
    extra_context = f"\n\nAdditional context from the user: {context_hint}" if context_hint else ""

    system = (
        f"You are a skilled communication assistant helping draft {medium} replies. "
        f"Tone instruction: {tone_instruction}{style_block}{contact_block}"
    )

    user_text = (
        f"Please read this {medium} screenshot and draft 3 reply options.{extra_context}\n\n"
        f"Format your response as:\n"
        f"**Option 1 — [tone label]:**\n[reply text]\n\n"
        f"**Option 2 — [tone label]:**\n[reply text]\n\n"
        f"**Option 3 — [tone label]:**\n[reply text]\n\n"
        f"After the options, add a one-line: *To refine: say \"make it shorter\", \"more formal\", etc.*\n\n"
        f"If the screenshot is unclear or you need more context to write a good reply, "
        f"respond with only: NEED_CONTEXT: [your one question]"
    )

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text",       "text": user_text},
                    {"type": "image_url",  "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ]},
            ],
            max_tokens=800,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT vision reply failed: {e}")
        return "Couldn't generate replies right now. Try again."


async def _gpt_reply_from_text(email_text: str, context_hint: str, tone: str,
                                style_examples: list[str], contact_ctx: str) -> str:
    """Draft an email reply from pasted text (no vision needed)."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["warm"])
    style_block      = ""
    if style_examples:
        examples_str = "\n".join(f"  - {e}" for e in style_examples[:5])
        style_block  = f"\n\nUser's writing style examples:\n{examples_str}"

    contact_block = f"\n\nContext about sender:\n{contact_ctx}" if contact_ctx else ""
    extra_context = f"\n\nAdditional context: {context_hint}" if context_hint else ""

    prompt = (
        f"Draft 3 reply options for this email. Tone: {tone_instruction}{style_block}"
        f"{contact_block}{extra_context}\n\n"
        f"Email:\n{email_text[:3000]}\n\n"
        f"Format:\n**Option 1 — [tone]:**\n[reply]\n\n**Option 2 — [tone]:**\n[reply]\n\n"
        f"**Option 3 — [tone]:**\n[reply]\n\n"
        f"*To refine: say \"make it shorter\", \"more formal\", etc.*"
    )
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT text reply failed: {e}")
        return "Couldn't generate replies right now. Try again."


async def _gpt_refine_reply(original_draft: str, instruction: str, tone: str) -> str:
    """Refine the last draft based on a user instruction."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    tone_instruction = _TONE_INSTRUCTIONS.get(tone, "")
    prompt = (
        f"Refine this reply draft based on the instruction: \"{instruction}\"\n\n"
        f"Original draft:\n{original_draft}\n\n"
        f"Tone to maintain: {tone_instruction}\n\n"
        f"Return only the refined reply text, no preamble."
    )
    try:
        resp = await client.chat.completions.create(
            model=GPT_CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return original_draft


# ─────────────────────────────────────────────────────────────────────────────
# PHOTO HANDLER (called from bot.py on every photo message)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_photo_for_reply(photo_file_path: str, update, context,
                                  is_email: bool = False) -> None:
    """
    Main entry point for screenshot-based reply drafting.
    Called from bot.py when user sends a photo.
    """
    import base64
    data = load_data()

    # Pop any context the user typed before sending the photo
    pending_ctx = pop_pending_context()

    # Get buyer's preferred tone
    reply_settings = get_reply_settings(data)
    tone           = reply_settings.get("default_tone", "warm")

    # Load style library
    lib            = load_style_library()
    style_examples = lib.get("examples", [])

    # Check contacts for context
    contact_ctx = ""
    if pending_ctx:
        contacts = load_contacts()
        for name, facts in contacts.items():
            if name.lower() in pending_ctx.lower():
                contact_ctx = f"{name}: " + "; ".join(facts[:3])
                break

    # Encode image
    try:
        with open(photo_file_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read photo: {e}")
        await update.message.reply_text("Couldn't read that image. Try again.")
        return

    await update.message.reply_text("⏳ Reading screenshot and drafting replies...")

    draft = await _gpt_reply_from_image(
        image_b64   = image_b64,
        context_hint= pending_ctx or "",
        tone        = tone,
        style_examples=style_examples,
        contact_ctx = contact_ctx,
        is_email    = is_email,
    )

    # Check if GPT needs clarification
    if draft.startswith("NEED_CONTEXT:"):
        question = draft[len("NEED_CONTEXT:"):].strip()
        # Store that we're waiting for context to re-try
        data["settings"]["_pending_reply_context"] = f"[awaiting clarification: {question}]"
        save_data(data)
        await update.message.reply_text(
            f"❓ {question}\n\n_(Answer this then send the screenshot again.)_",
            parse_mode="Markdown",
        )
        return

    set_last_draft(draft)
    await update.message.reply_text(draft, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# REFINEMENT (called from bot.py for follow-up text after a draft)
# ─────────────────────────────────────────────────────────────────────────────

_REFINE_KEYWORDS = [
    "make it shorter", "shorter", "more formal", "less formal", "warmer",
    "friendlier", "more direct", "funnier", "more professional", "simpler",
    "longer", "more casual", "softer", "stronger",
]


def looks_like_refinement(text: str) -> bool:
    """Detect if user is asking to refine the last draft."""
    lower = text.lower().strip()
    if get_last_draft() is None:
        return False
    return any(kw in lower for kw in _REFINE_KEYWORDS)


async def handle_refinement(text: str, update, context) -> None:
    data       = load_data()
    tone       = get_reply_settings(data).get("default_tone", "warm")
    last_draft = get_last_draft()
    if not last_draft:
        await update.message.reply_text("No recent reply draft to refine. Send a screenshot first.")
        return
    await update.message.reply_text("⏳ Refining...")
    refined = await _gpt_refine_reply(last_draft, text, tone)
    set_last_draft(refined)
    await update.message.reply_text(refined, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# INTENT HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def handle_reply_intent(intent: str, entities: dict, update, context) -> None:
    msg = update.message

    if intent == REPLY_STYLE_ADD:
        example = entities.get("example", "").strip()
        if not example:
            await msg.reply_text(
                "What example message should I save? Try: \"save this as my style: [message]\""
            )
            return
        lib = load_style_library()
        lib.setdefault("examples", []).append(example)
        if len(lib["examples"]) > 20:
            lib["examples"] = lib["examples"][-20:]
        save_style_library(lib)
        await msg.reply_text(
            f"✓ Style example saved. I'll use it when drafting replies.\n"
            f"You have {len(lib['examples'])} example{'s' if len(lib['examples'])!=1 else ''} saved."
        )
        return

    if intent in (REPLY_ASSIST, EMAIL_ASSIST):
        context_hint = entities.get("context", "").strip()
        email_text   = entities.get("email_text", "").strip()
        is_email     = (intent == EMAIL_ASSIST)

        if email_text:
            # Pasted email text
            data           = load_data()
            tone           = get_reply_settings(data).get("default_tone", "warm")
            lib            = load_style_library()
            style_examples = lib.get("examples", [])
            await msg.reply_text("⏳ Drafting email reply...")
            draft = await _gpt_reply_from_text(
                email_text     = email_text,
                context_hint   = context_hint,
                tone           = tone,
                style_examples = style_examples,
                contact_ctx    = "",
            )
            set_last_draft(draft)
            await msg.reply_text(draft, parse_mode="Markdown")
        else:
            # Store context for when the photo arrives
            if context_hint:
                set_pending_context(context_hint)
            label = "email" if is_email else "text message"
            await msg.reply_text(
                f"Got it. Now send me a screenshot of the {label} you want to reply to."
            )
        return
