"""
alfred/core/google_auth.py
==========================
Google OAuth2 authentication for Alfred.

HOW GOOGLE AUTH WORKS IN ALFRED
────────────────────────────────
1. Buyer runs /auth in Telegram.
   Alfred generates an OAuth URL and sends it.

2. Buyer opens the URL, signs in with Google, and approves the requested
   permissions (Calendar + Tasks read/write).

3. Google redirects to http://localhost — which shows an error page.
   That is completely normal. The buyer copies the `code=...` value from
   the address bar and sends it to Alfred with /code <paste here>.

4. Alfred exchanges the code for a token, saves it to TOKEN_FILE on the
   Railway /data volume, and confirms the connection.

5. The token expires after 7 days. Alfred auto-refreshes it on every API
   call as long as the process is running. If the process has been offline
   and the token is stale, Alfred warns the buyer each morning (6:50 AM)
   and provides reconnect instructions.

PUBLIC INTERFACE
────────────────
  get_creds()                → google.oauth2.credentials.Credentials | None
  get_calendar_service()     → googleapiclient Resource | None
  get_tasks_service()        → googleapiclient Resource | None
  is_authorized()            → bool
  token_expires_in_hours()   → float | None

  cmd_auth(update, context)       Telegram /auth command handler
  cmd_code(update, context)       Telegram /code command handler
  cmd_checkauth(update, context)  Telegram /checkauth command handler
  job_google_health_check(context) Daily job — warn if token expired
"""

import os
import json
import logging
import datetime

logger = logging.getLogger(__name__)

from core.config import (
    TELEGRAM_TOKEN,
    ALLOWED_USER_ID,
    GOOGLE_CREDENTIALS,
    GOOGLE_SCOPES,
    TOKEN_FILE,
    AUTH_STATE_FILE,
    TIMEZONE,
    HEALTH_CHECK_HOUR,
    HEALTH_CHECK_MINUTE,
    BOT_NAME,
)
from core.data import audit_log


# ═══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL CREDENTIAL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_creds():
    """
    Load Google credentials from TOKEN_FILE and auto-refresh if expired.

    Returns:
        google.oauth2.credentials.Credentials — valid and ready to use
        None — not authorized yet (buyer needs to run /auth)

    Never raises. Logs errors internally.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not os.path.exists(TOKEN_FILE):
        return None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GOOGLE_SCOPES)
    except Exception as e:
        logger.error(f"get_creds: could not load token file: {e}")
        return None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_creds(creds)
            logger.info("Google token auto-refreshed successfully.")
        except Exception as e:
            logger.error(f"get_creds: token refresh failed: {e}")
            return None

    if creds and creds.valid:
        return creds

    return None


def _save_creds(creds):
    """Write credentials to TOKEN_FILE. Raises on IO error."""
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def is_authorized():
    """Return True if Alfred has a valid, usable Google token right now."""
    return get_creds() is not None


def token_expires_in_hours():
    """
    Return how many hours until the current token expires.

    Returns:
        float — hours until expiry (may be negative if already expired)
        None  — no token on disk

    Google OAuth tokens typically expire after 7 days. Alfred auto-refreshes
    on every API call, but if the bot has been offline, this tells you
    how much time is left.
    """
    from google.oauth2.credentials import Credentials

    if not os.path.exists(TOKEN_FILE):
        return None

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GOOGLE_SCOPES)
        if creds.expiry:
            # creds.expiry is a naive UTC datetime
            now_utc = datetime.datetime.utcnow()
            delta = creds.expiry - now_utc
            return delta.total_seconds() / 3600
    except Exception as e:
        logger.warning(f"token_expires_in_hours: {e}")

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_calendar_service():
    """
    Return an authorized Google Calendar API service object.

    Returns:
        googleapiclient.discovery.Resource — ready to use
        None — not authorized or an error occurred
    """
    creds = get_creds()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"get_calendar_service: {e}")
        return None


def get_tasks_service():
    """
    Return an authorized Google Tasks API service object.

    Returns:
        googleapiclient.discovery.Resource — ready to use
        None — not authorized or an error occurred
    """
    creds = get_creds()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("tasks", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"get_tasks_service: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_auth(update, context):
    """
    /auth — Start the Google OAuth flow.

    Sends the buyer an authorization URL. After they approve, they copy
    the code from the redirect URL and send it via /code.
    """
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    try:
        from google_auth_oauthlib.flow import Flow

        creds_data = json.loads(GOOGLE_CREDENTIALS)
        flow = Flow.from_client_config(creds_data, scopes=GOOGLE_SCOPES)
        flow.redirect_uri = "http://localhost"

        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )

        # Persist state + code_verifier so /code can complete the exchange
        auth_state = {
            "state":          state,
            "code_verifier":  getattr(flow, "code_verifier", None),
        }
        with open(AUTH_STATE_FILE, "w") as f:
            json.dump(auth_state, f)

        msg = (
            f"<b>Connect {BOT_NAME} to Google</b>\n\n"
            "1️⃣ Open this link and sign in with your Google account:\n\n"
            f"<code>{auth_url}</code>\n\n"
            "2️⃣ Approve the Calendar and Tasks permissions.\n\n"
            "3️⃣ Your browser will redirect to a page that shows an error — "
            "<b>that is completely normal.</b>\n\n"
            "4️⃣ Look at the address bar. Copy everything after <code>code=</code> "
            "and before <code>&scope</code>.\n\n"
            "5️⃣ Send it here like this:\n"
            "<code>/code 4/0Afr... (your full code)</code>"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
        audit_log("AUTH_STARTED")

    except Exception as e:
        logger.error(f"cmd_auth error: {e}")
        await update.message.reply_text(
            "Something went wrong starting the auth flow.\n"
            "Make sure GOOGLE_CREDENTIALS is set correctly in Railway.",
        )


async def cmd_code(update, context):
    """
    /code <auth_code> — Complete the Google OAuth flow.

    Exchanges the code for a token and saves it to disk.
    """
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    if not context.args:
        await update.message.reply_text(
            "Paste your auth code after the command.\n\n"
            "Example: <code>/code 4/0Afr...</code>",
            parse_mode="HTML",
        )
        return

    auth_code = " ".join(context.args).strip()

    if not os.path.exists(AUTH_STATE_FILE):
        await update.message.reply_text(
            "No active auth session found. Run /auth first to get a new link."
        )
        return

    try:
        with open(AUTH_STATE_FILE, "r") as f:
            auth_state = json.load(f)
    except Exception:
        await update.message.reply_text(
            "The auth session file is corrupted. Run /auth to start over."
        )
        return

    try:
        from google_auth_oauthlib.flow import Flow

        creds_data = json.loads(GOOGLE_CREDENTIALS)
        flow = Flow.from_client_config(
            creds_data,
            scopes=GOOGLE_SCOPES,
            state=auth_state.get("state"),
        )
        flow.redirect_uri = "http://localhost"

        # Restore PKCE code verifier if it was saved
        code_verifier = auth_state.get("code_verifier")
        if code_verifier:
            flow.code_verifier = code_verifier

        # Allow the insecure localhost redirect (required by Google's library).
        # Save and restore the env var so we don't leak the setting if an
        # exception occurs mid-exchange.
        _prev_insecure = os.environ.get("OAUTHLIB_INSECURE_TRANSPORT")
        try:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
            flow.fetch_token(code=auth_code)
        finally:
            if _prev_insecure is None:
                os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)
            else:
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = _prev_insecure

        _save_creds(flow.credentials)

        # Clean up auth state file — no longer needed
        try:
            os.remove(AUTH_STATE_FILE)
        except OSError:
            pass

        audit_log("AUTH_SUCCESS")
        await update.message.reply_text(
            f"✅ <b>Google connected successfully!</b>\n\n"
            f"{BOT_NAME} now has access to your Google Calendar and Tasks.\n\n"
            "Try <code>/briefing</code> to run your morning briefing, or "
            "<code>/checkauth</code> to confirm the connection any time.",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"cmd_code error: {e}")
        await update.message.reply_text(
            f"That code didn't work.\n\n"
            f"Error: <code>{str(e)[:150]}</code>\n\n"
            "Run /auth to get a fresh link and try again.",
            parse_mode="HTML",
        )


async def cmd_checkauth(update, context):
    """
    /checkauth — Show the current Google connection status.

    Reports whether the token is valid, when it was last refreshed,
    and approximately how many hours remain before it expires.
    """
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    creds = get_creds()
    if not creds:
        await update.message.reply_text(
            "❌ <b>Google is not connected.</b>\n\n"
            "Run /auth to connect your Google account.",
            parse_mode="HTML",
        )
        return

    # Try a lightweight real API call to confirm the token actually works
    calendar_ok = False
    tasks_ok    = False
    try:
        svc = get_calendar_service()
        if svc:
            svc.calendarList().list(maxResults=1).execute()
            calendar_ok = True
    except Exception:
        pass

    try:
        svc = get_tasks_service()
        if svc:
            svc.tasklists().list(maxResults=1).execute()
            tasks_ok = True
    except Exception:
        pass

    hours_left = token_expires_in_hours()
    if hours_left is not None:
        if hours_left < 0:
            expiry_line = "⚠️ Token appears expired (auto-refresh may be needed)"
        elif hours_left < 24:
            expiry_line = f"⚠️ Token expires in ~{hours_left:.0f} hours"
        else:
            days = hours_left / 24
            expiry_line = f"✅ Token valid for ~{days:.0f} more days"
    else:
        expiry_line = "Token expiry unknown"

    cal_icon   = "✅" if calendar_ok else "❌"
    tasks_icon = "✅" if tasks_ok    else "❌"

    await update.message.reply_text(
        f"<b>Google Auth Status</b>\n\n"
        f"{cal_icon} Calendar API\n"
        f"{tasks_icon} Tasks API\n"
        f"🕐 {expiry_line}\n\n"
        + ("Everything looks good." if calendar_ok and tasks_ok
           else "One or more services failed. Run /auth to reconnect."),
        parse_mode="HTML",
    )


async def cmd_disconnect(update, context):
    """
    /disconnect — Wipe the stored Google token and revoke the session.

    Use this when:
      - You need to reconnect with a different Google account
      - Auth is broken and you want a clean slate
      - You want to revoke Alfred's Google access entirely

    After running this, use /auth to reconnect.
    """
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    removed = False
    if os.path.exists(TOKEN_FILE):
        # Attempt to revoke the token with Google before deleting locally
        try:
            import requests as _req
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, GOOGLE_SCOPES)
            if creds.token:
                _req.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    timeout=5,
                )
        except Exception:
            pass  # Revoke is best-effort — local deletion still happens

        try:
            os.remove(TOKEN_FILE)
            removed = True
        except OSError as e:
            logger.error(f"cmd_disconnect: could not delete token file: {e}")

    # Clean up any in-progress auth state
    if os.path.exists(AUTH_STATE_FILE):
        try:
            os.remove(AUTH_STATE_FILE)
        except OSError:
            pass

    audit_log("DISCONNECT")

    if removed:
        await update.message.reply_text(
            f"🔌 <b>Google disconnected.</b>\n\n"
            f"{BOT_NAME} no longer has access to your Google account.\n\n"
            "Run /auth when you're ready to reconnect.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "No active Google connection found. Run /auth to connect.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY HEALTH CHECK JOB
# Registered in bot.py as: app.job_queue.run_daily(job_google_health_check, ...)
# ═══════════════════════════════════════════════════════════════════════════════

async def job_google_health_check(context):
    """
    Daily job: fires at HEALTH_CHECK_HOUR:HEALTH_CHECK_MINUTE.

    Silently passes if the token is healthy.
    Sends a warning to the buyer if:
      - No token exists (never authenticated)
      - Token cannot be refreshed
      - Token will expire within 48 hours
    """
    creds = get_creds()

    if not creds:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=(
                f"⚠️ <b>{BOT_NAME} is not connected to Google.</b>\n\n"
                "Your morning briefing will be missing calendar and task data.\n\n"
                "Run /auth now to reconnect before your briefing."
            ),
            parse_mode="HTML",
        )
        audit_log("HEALTH_CHECK: token missing or invalid")
        return

    hours_left = token_expires_in_hours()
    if hours_left is not None and hours_left < 48:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text=(
                f"⚠️ Your Google token expires in ~{hours_left:.0f} hours.\n\n"
                "Run /auth to reconnect and avoid interruptions."
            ),
            parse_mode="HTML",
        )
        audit_log(f"HEALTH_CHECK: token expiring soon ({hours_left:.0f}h)")
        return

    # Token is fine — log quietly, do not message the user
    audit_log("HEALTH_CHECK: OK")
