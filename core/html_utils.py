"""
marvin/core/html_utils.py
==========================
Utilities for converting Telegram HTML formatting to other platform formats.

Telegram uses a subset of HTML for message formatting:
    <b>bold</b>
    <i>italic</i>
    <u>underline</u>
    <s>strikethrough</s>
    <code>inline code</code>
    <pre>code block</pre>
    <a href="url">link text</a>

Discord uses Markdown:
    **bold**
    *italic*
    __underline__
    ~~strikethrough~~
    `inline code`
    ```code block```
    [link text](url)

IMPORTANT: Discord does NOT render HTML. Always run html_to_discord()
before sending any HTML-formatted text to a Discord channel.
"""

import re
import html as _html_module


def html_to_discord(text: str) -> str:
    """
    Convert Telegram HTML tags to Discord Markdown.

    Handles the tags Marvin actually uses. Unknown tags are stripped.

    Examples:
        "<b>bold</b>"         → "**bold**"
        "<i>italic</i>"       → "*italic*"
        "<code>x</code>"      → "`x`"
        "<pre>block</pre>"    → "```\\nblock\\n```"
        "<a href='u'>t</a>"   → "[t](u)"
        "&amp;", "&lt;", etc. → unescaped
    """
    if not text:
        return text

    # ── Block-level tags (must come before inline to avoid nesting issues) ────

    # <pre>...</pre> → ```\n...\n```
    text = re.sub(
        r'<pre[^>]*>(.*?)</pre>',
        lambda m: f"```\n{m.group(1).strip()}\n```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # ── Inline tags ───────────────────────────────────────────────────────────

    # <b>...</b> or <strong>...</strong> → **...**
    text = re.sub(
        r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>',
        r'**\1**',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # <i>...</i> or <em>...</em> → *...*
    text = re.sub(
        r'<(?:i|em)[^>]*>(.*?)</(?:i|em)>',
        r'*\1*',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # <u>...</u> → __...__
    text = re.sub(
        r'<u[^>]*>(.*?)</u>',
        r'__\1__',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # <s>...</s> or <del>...</del> → ~~...~~
    text = re.sub(
        r'<(?:s|del|strike)[^>]*>(.*?)</(?:s|del|strike)>',
        r'~~\1~~',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # <code>...</code> → `...`
    text = re.sub(
        r'<code[^>]*>(.*?)</code>',
        r'`\1`',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # <a href="url">text</a> → [text](url)
    text = re.sub(
        r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        r'[\2](\1)',
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # ── Strip any remaining unknown tags ─────────────────────────────────────
    text = re.sub(r'<[^>]+>', '', text)

    # ── Unescape HTML entities ────────────────────────────────────────────────
    text = _html_module.unescape(text)

    return text


def strip_html(text: str) -> str:
    """
    Remove all HTML tags and unescape entities, returning plain text.
    Useful for logging or platforms that don't support any markdown.
    """
    if not text:
        return text
    text = re.sub(r'<[^>]+>', '', text)
    text = _html_module.unescape(text)
    return text


def discord_to_html(text: str) -> str:
    """
    Convert Discord Markdown to Telegram HTML (reverse of html_to_discord).
    Useful if Discord users send formatted messages that need to be
    forwarded to Telegram.

    Note: This is a best-effort conversion — some Discord markdown
    (e.g. headers with #) has no Telegram equivalent.
    """
    if not text:
        return text

    # Escape HTML special chars first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ```block``` → <pre>...</pre>
    text = re.sub(
        r'```(?:\w+\n)?(.*?)```',
        r'<pre>\1</pre>',
        text,
        flags=re.DOTALL,
    )

    # **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)

    # *italic* (single) → <i>italic</i>
    # Careful not to match the ** pairs already replaced
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text, flags=re.DOTALL)

    # __underline__ → <u>underline</u>
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text, flags=re.DOTALL)

    # ~~strikethrough~~ → <s>strikethrough</s>
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text, flags=re.DOTALL)

    # `code` → <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    return text
