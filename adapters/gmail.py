"""
alfred/adapters/gmail.py
========================
Low-level Gmail API wrapper for Alfred.

PUBLIC API
──────────
  get_unread_count(svc)                          → int
  get_vip_emails(svc, vip_addresses)             → list[dict]
  send_email(svc, to, subject, body)             → bool
  create_draft(svc, to, subject, body)           → str | None  (draft ID)
  search_emails(svc, query, max_results=5)       → list[dict]

All functions are fire-and-forget safe — they log errors but never raise,
so Gmail failures never crash the main bot flow.

EMAIL FORMAT
────────────
  Emails are sent as plain text (UTF-8).
  The 'to' field accepts: "John" (looked up via contacts), "john@email.com",
  or "John <john@email.com>".
"""

from __future__ import annotations

import base64
import email.mime.text
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_message(to: str, subject: str, body: str, sender: str = "me") -> dict:
    """Build a Gmail API message body from parts."""
    msg = email.mime.text.MIMEText(body, "plain", "utf-8")
    msg["to"]      = to
    msg["from"]    = sender
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def _strip_html(text: str) -> str:
    """Very basic HTML stripping for email snippets."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_email_summary(msg_data: dict) -> dict:
    """Extract useful fields from a Gmail message resource."""
    headers = {
        h["name"].lower(): h["value"]
        for h in msg_data.get("payload", {}).get("headers", [])
    }
    return {
        "id":       msg_data.get("id", ""),
        "from":     headers.get("from", "(unknown)"),
        "subject":  headers.get("subject", "(no subject)"),
        "date":     headers.get("date", ""),
        "snippet":  _strip_html(msg_data.get("snippet", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_unread_count(svc) -> int:
    """Return the number of unread messages in the user's inbox."""
    try:
        result = svc.users().messages().list(
            userId="me",
            q="is:unread in:inbox",
            maxResults=1,
        ).execute()
        # resultSizeEstimate is approximate but fast (no pagination needed)
        return result.get("resultSizeEstimate", 0)
    except Exception as e:
        logger.error(f"Gmail get_unread_count: {e}")
        return 0


def get_vip_emails(svc, vip_addresses: list[str]) -> list[dict]:
    """
    Return recent unread emails from VIP senders.

    Args:
        svc: Gmail API service
        vip_addresses: list of email addresses to check

    Returns:
        list of dicts with keys: from, subject, date, snippet
    """
    if not vip_addresses:
        return []

    results = []
    for addr in vip_addresses[:5]:  # cap at 5 VIPs to stay fast
        try:
            query = f"is:unread in:inbox from:{addr}"
            r = svc.users().messages().list(
                userId="me",
                q=query,
                maxResults=3,
            ).execute()
            messages = r.get("messages", [])
            for m in messages:
                detail = svc.users().messages().get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                summary = _parse_email_summary(detail)
                summary["snippet"] = _strip_html(detail.get("snippet", ""))
                results.append(summary)
        except Exception as e:
            logger.warning(f"Gmail get_vip_emails({addr}): {e}")

    return results


def send_email(svc, to: str, subject: str, body: str) -> bool:
    """
    Send an email from the user's Gmail account.

    Args:
        svc:     Gmail API service
        to:      recipient address (e.g. "john@example.com")
        subject: email subject line
        body:    plain-text email body

    Returns:
        True on success, False on failure
    """
    try:
        message = _build_message(to, subject, body)
        svc.users().messages().send(
            userId="me",
            body=message,
        ).execute()
        logger.info(f"Gmail sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Gmail send_email failed: {e}")
        return False


def create_draft(svc, to: str, subject: str, body: str) -> str | None:
    """
    Save an email to the user's Gmail Drafts folder.

    Returns:
        str — draft ID on success
        None — on failure
    """
    try:
        message = _build_message(to, subject, body)
        result = svc.users().drafts().create(
            userId="me",
            body={"message": message},
        ).execute()
        draft_id = result.get("id")
        logger.info(f"Gmail draft saved: {draft_id} → to:{to} subj:{subject}")
        return draft_id
    except Exception as e:
        logger.error(f"Gmail create_draft failed: {e}")
        return None


def search_emails(svc, query: str, max_results: int = 5) -> list[dict]:
    """
    Search the inbox and return email summaries.

    Args:
        svc:         Gmail API service
        query:       Gmail search query (e.g. "from:boss@work.com subject:invoice")
        max_results: max number of results to return (capped at 10)

    Returns:
        list of dicts: from, subject, date, snippet
    """
    try:
        r = svc.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(max_results, 10),
        ).execute()
        messages = r.get("messages", [])
        results  = []
        for m in messages:
            detail = svc.users().messages().get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            results.append(_parse_email_summary(detail))
        return results
    except Exception as e:
        logger.error(f"Gmail search_emails({query!r}): {e}")
        return []
