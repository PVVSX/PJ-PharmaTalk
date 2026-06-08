"""
Upload WAV files to a shared Google Drive folder, under a subfolder named by English month (march, april, ...).

Requires a service account JSON and the Drive root folder shared with that service account (Editor).
Set GOOGLE_APPLICATION_CREDENTIALS to the JSON path, or GDRIVE_SERVICE_ACCOUNT_JSON.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional, Tuple

# Root folder from user link: https://drive.google.com/drive/folders/19z1neaTpHjJ57101faZTwaAwcVkj2A-Q
DEFAULT_DRIVE_ROOT_FOLDER_ID = "19z1neaTpHjJ57101faZTwaAwcVkj2A-Q"

_SCOPES = ("https://www.googleapis.com/auth/drive",)


def _credentials_path() -> Optional[str]:
    p = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON") or os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS"
    )
    return p if p and os.path.isfile(p) else None


def drive_enabled() -> bool:
    return _credentials_path() is not None


def _build_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    path = _credentials_path()
    if not path:
        return None
    creds = service_account.Credentials.from_service_account_file(
        path, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape_drive_query_name(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _find_child_folder(service, parent_id: str, folder_name: str) -> Optional[str]:
    safe = _escape_drive_query_name(folder_name)
    q = (
        f"name = '{safe}' and '{parent_id}' in parents and "
        f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id,name)", pageSize=10)
        .execute()
    )
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _get_or_create_month_folder(service, root_folder_id: str, month_name: str) -> str:
    found = _find_child_folder(service, root_folder_id, month_name)
    if found:
        return found
    body = {
        "name": month_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [root_folder_id],
    }
    created = service.files().create(body=body, fields="id").execute()
    return created["id"]


def upload_wav_to_drive(
    local_path: str,
    drive_file_name: str,
    month_folder_name: str,
    root_folder_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Upload local_path to Drive as drive_file_name inside root/month_folder_name/.
    Returns (ok, message).
    """
    if not drive_enabled():
        return False, "ไม่ได้ตั้งค่า credentials (GOOGLE_APPLICATION_CREDENTIALS หรือ GDRIVE_SERVICE_ACCOUNT_JSON)"

    root = root_folder_id or os.environ.get(
        "GDRIVE_ROOT_FOLDER_ID", DEFAULT_DRIVE_ROOT_FOLDER_ID
    )

    try:
        service = _build_service()
        if service is None:
            return False, "สร้าง Drive service ไม่ได้"

        parent_id = _get_or_create_month_folder(service, root, month_folder_name)

        from googleapiclient.http import MediaFileUpload

        file_metadata = {"name": drive_file_name, "parents": [parent_id]}
        media = MediaFileUpload(local_path, mimetype="audio/wav", resumable=True)
        service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        return True, f"อัปโหลด Google Drive แล้ว ({month_folder_name}/{drive_file_name})"
    except Exception as e:
        return False, f"อัปโหลด Drive ล้มเหลว: {e}"


def month_folder_name_from_date(dt) -> str:
    """English lowercase month, matching folders like march, april."""
    return dt.strftime("%B").lower()


def local_wav_to_drive_target(local_filename: str, mtime: float) -> Tuple[str, str]:
    """
    From a local basename like 21-03-26_14-30_000.wav, return (drive_name, month_folder).
    drive_name uses colons as on Drive; month is English lowercase from that date.
    Other filenames: use same basename on Drive, month from file mtime.
    """
    m = re.match(
        r"^(\d{2})-(\d{2})-(\d{2})_(\d{2})-(\d{2})_(\d{3})\.wav$",
        local_filename,
        re.IGNORECASE,
    )
    if m:
        d, mo, y2, h, mi, seq = m.groups()
        drive = f"{d}:{mo}:{y2}_{h}:{mi}_{seq}.wav"
        full_year = 2000 + int(y2)
        dt = datetime(full_year, int(mo), int(d))
        return drive, dt.strftime("%B").lower()
    dt = datetime.fromtimestamp(mtime)
    return local_filename, dt.strftime("%B").lower()
