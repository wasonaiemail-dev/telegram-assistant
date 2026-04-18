"""
alfred/adapters/google_drive.py
================================
Google Drive adapter for Alfred notes sync.

Notes are mirrored from Google Tasks to a Drive folder called "Alfred Notes"
as plain .txt files. The Google Tasks note ID → Drive file ID mapping is
persisted to DRIVE_NOTES_MAP_FILE so updates and deletes can find the right file.

PUBLIC API
──────────
  sync_note_add(task_id, text)          → None
  sync_note_update(task_id, new_text)   → None
  sync_note_delete(task_id)             → None

All functions are fire-and-forget — they log errors but never raise,
so Drive sync failure never blocks the main note operation.
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_map() -> dict:
    from core.config import DRIVE_NOTES_MAP_FILE
    if not os.path.exists(DRIVE_NOTES_MAP_FILE):
        return {}
    try:
        with open(DRIVE_NOTES_MAP_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_map(mapping: dict) -> None:
    from core.config import DRIVE_NOTES_MAP_FILE
    try:
        with open(DRIVE_NOTES_MAP_FILE, "w") as f:
            json.dump(mapping, f)
    except Exception as e:
        logger.error(f"Drive notes map save failed: {e}")


def _get_or_create_folder(svc) -> str | None:
    """
    Return the Drive folder ID for "Alfred Notes".
    Checks the cache file first, then searches Drive, then creates it.
    """
    from core.config import DRIVE_NOTES_FOLDER_FILE

    # 1. Check disk cache
    if os.path.exists(DRIVE_NOTES_FOLDER_FILE):
        try:
            with open(DRIVE_NOTES_FOLDER_FILE) as f:
                folder_id = f.read().strip()
            if folder_id:
                return folder_id
        except Exception:
            pass

    # 2. Search Drive for existing folder
    try:
        results = svc.files().list(
            q="name='Alfred Notes' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)",
            pageSize=1,
        ).execute()
        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
            _cache_folder_id(folder_id, DRIVE_NOTES_FOLDER_FILE)
            return folder_id
    except Exception as e:
        logger.warning(f"Drive folder search failed: {e}")

    # 3. Create the folder
    try:
        folder = svc.files().create(
            body={
                "name": "Alfred Notes",
                "mimeType": "application/vnd.google-apps.folder",
            },
            fields="id",
        ).execute()
        folder_id = folder["id"]
        _cache_folder_id(folder_id, DRIVE_NOTES_FOLDER_FILE)
        logger.info(f"Created Alfred Notes folder in Drive: {folder_id}")
        return folder_id
    except Exception as e:
        logger.error(f"Drive folder creation failed: {e}")
        return None


def _cache_folder_id(folder_id: str, path: str) -> None:
    try:
        with open(path, "w") as f:
            f.write(folder_id)
    except Exception as e:
        logger.warning(f"Could not cache Drive folder ID: {e}")


def _safe_filename(text: str) -> str:
    """Turn note text into a safe filename (first 50 chars, no special chars)."""
    clean = re.sub(r"[^\w\s-]", "", text[:50]).strip()
    clean = re.sub(r"\s+", "_", clean)
    return clean or "note"


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def sync_note_add(task_id: str, text: str) -> None:
    """
    Create a .txt file in the Alfred Notes Drive folder for a new note.
    Records the task_id → drive_file_id mapping for future updates/deletes.
    """
    try:
        from core.google_auth import get_drive_service
        svc = get_drive_service()
        if not svc:
            logger.warning("Drive sync skipped: not authorized (run /auth).")
            return

        folder_id = _get_or_create_folder(svc)
        if not folder_id:
            return

        filename = f"{_safe_filename(text)}.txt"

        # Upload the note as a plain text file
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(text.encode("utf-8"), mimetype="text/plain")
        file_meta = {
            "name": filename,
            "parents": [folder_id],
        }
        result = svc.files().create(
            body=file_meta,
            media_body=media,
            fields="id",
        ).execute()

        drive_file_id = result["id"]

        # Save the mapping
        mapping = _load_map()
        mapping[task_id] = drive_file_id
        _save_map(mapping)

        logger.info(f"Note synced to Drive: {filename} ({drive_file_id})")

    except Exception as e:
        logger.error(f"Drive sync_note_add failed (note not affected): {e}")


def sync_note_update(task_id: str, new_text: str) -> None:
    """
    Update the Drive file content for an edited note.
    """
    try:
        from core.google_auth import get_drive_service
        svc = get_drive_service()
        if not svc:
            return

        mapping = _load_map()
        drive_file_id = mapping.get(task_id)
        if not drive_file_id:
            # No Drive file on record — create one instead
            sync_note_add(task_id, new_text)
            return

        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(new_text.encode("utf-8"), mimetype="text/plain")
        new_filename = f"{_safe_filename(new_text)}.txt"

        svc.files().update(
            fileId=drive_file_id,
            body={"name": new_filename},
            media_body=media,
        ).execute()

        logger.info(f"Drive note updated: {drive_file_id}")

    except Exception as e:
        logger.error(f"Drive sync_note_update failed (note not affected): {e}")


def sync_note_delete(task_id: str) -> None:
    """
    Move the Drive file to trash when a note is deleted.
    """
    try:
        from core.google_auth import get_drive_service
        svc = get_drive_service()
        if not svc:
            return

        mapping = _load_map()
        drive_file_id = mapping.pop(task_id, None)
        if not drive_file_id:
            return  # No Drive file on record — nothing to do

        svc.files().update(
            fileId=drive_file_id,
            body={"trashed": True},
        ).execute()

        _save_map(mapping)
        logger.info(f"Drive note trashed: {drive_file_id}")

    except Exception as e:
        logger.error(f"Drive sync_note_delete failed (note not affected): {e}")
