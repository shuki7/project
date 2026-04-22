"""
Google Drive APIを使ったファイル同期。
ローカルのGoogle Drive同期アプリ（Drive for Desktop）を使っている場合は
このモジュールは不要で、config.py の GDRIVE_LOCAL_PATH を設定するだけでOK。

このモジュールはAPIを使った手動アップロードが必要な場合に使用する。

セットアップ:
    1. Google Cloud Consoleでプロジェクト作成
    2. Google Drive APIを有効化
    3. OAuth2認証情報をダウンロードして credentials.json として保存
    4. 初回実行時にブラウザで認証
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    GDRIVE_CREDENTIALS_PATH, GDRIVE_TOKEN_PATH, GDRIVE_FOLDER_ID,
    GDRIVE_SERVICE_ACCOUNT_PATH, DB_PATH, OBSIDIAN_DIR,
)

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    _GDRIVE_AVAILABLE = True
except ImportError:
    _GDRIVE_AVAILABLE = False

try:
    from google.oauth2 import service_account as _sa_module
    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False

# 全ファイルの読み書き権限（サービスアカウントは drive.file では不可）
SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_service():
    if not _GDRIVE_AVAILABLE:
        raise RuntimeError(
            "Google Drive APIライブラリが未インストールです。\n"
            "pip install google-api-python-client google-auth-oauthlib"
        )

    # ① サービスアカウント方式（サーバー推奨、ブラウザ認証不要）
    if (GDRIVE_SERVICE_ACCOUNT_PATH and GDRIVE_SERVICE_ACCOUNT_PATH.exists()
            and _SA_AVAILABLE):
        creds = _sa_module.Credentials.from_service_account_file(
            str(GDRIVE_SERVICE_ACCOUNT_PATH), scopes=SCOPES
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    # ② OAuth ユーザー方式（ローカル開発向け、フォールバック）
    creds = None
    if GDRIVE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GDRIVE_CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"認証情報が見つかりません。サービスアカウント JSON か credentials.json を配置してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GDRIVE_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        GDRIVE_TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """フォルダが存在しなければ作成してIDを返す。"""
    query = (
        f"name='{name}' and "
        f"'{parent_id}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and "
        "trashed=false"
    )
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _upload_file(service, local_path: Path, parent_id: str):
    """ファイルをアップロード（既存の場合は更新）。"""
    filename = local_path.name

    # 既存ファイルを検索
    query = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])

    media = MediaFileUpload(str(local_path), resumable=True)

    if files:
        # 更新
        service.files().update(
            fileId=files[0]["id"],
            media_body=media,
        ).execute()
        print(f"[Drive] 更新: {filename}")
    else:
        # 新規アップロード
        metadata = {"name": filename, "parents": [parent_id]}
        service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
        ).execute()
        print(f"[Drive] アップロード: {filename}")


def upload_receipt_bytes(image_bytes: bytes,
                          filename: str,
                          date_str: str = None,
                          project_name: str = None,
                          kind: str = "expenses") -> str:
    """
    レシート画像のバイト列を Google Drive にアップロードし、Drive ファイル ID を返す。
    ローカルディスクには保存しない。

    保存先:
        project_name 指定あり → projects/<project_name>/<kind>/YYYY-MM/
        project_name 未指定   → receipts/YYYY-MM/   （旧仕様、後方互換）

    Args:
        image_bytes:  圧縮済み JPEG バイト列
        filename:     保存するファイル名
        date_str:     "YYYY-MM-DD" 形式の日付（省略時は今日）
        project_name: プロジェクト名（指定するとプロジェクト配下に保存）
        kind:         "expenses" or "revenue"

    Returns:
        str: Drive ファイル ID。Drive 未設定・エラー時は空文字。
    """
    if not GDRIVE_FOLDER_ID or not image_bytes:
        return ""

    try:
        from googleapiclient.http import MediaIoBaseUpload
        import io as _io
        from datetime import datetime as _dt

        service = _get_service()
        month_label = date_str[:7] if date_str else _dt.now().strftime("%Y-%m")

        if project_name:
            # 新仕様: projects/<name>/<kind>/YYYY-MM/
            kind_folder = "revenue" if kind == "revenue" else "expenses"
            projects_root = _get_or_create_folder(service, "projects", GDRIVE_FOLDER_ID)
            proj_folder   = _get_or_create_folder(service, project_name, projects_root)
            type_folder   = _get_or_create_folder(service, kind_folder, proj_folder)
            month_folder  = _get_or_create_folder(service, month_label, type_folder)
        else:
            # 旧仕様（フォールバック）
            receipts_root = _get_or_create_folder(service, "receipts", GDRIVE_FOLDER_ID)
            month_folder  = _get_or_create_folder(service, month_label, receipts_root)

        # MIME タイプを拡張子から推定
        import mimetypes as _mt
        guessed, _ = _mt.guess_type(filename)
        mime = guessed or "application/octet-stream"

        buf   = _io.BytesIO(image_bytes)
        media = MediaIoBaseUpload(buf, mimetype=mime, resumable=False)
        meta  = {"name": filename, "parents": [month_folder]}
        result = service.files().create(
            body=meta, media_body=media, fields="id"
        ).execute()
        return result.get("id", "")

    except Exception:
        return ""


def upload_project_file_bytes(project_name: str,
                               file_bytes: bytes,
                               filename: str,
                               mime_type: str = "application/octet-stream",
                               subfolder: str = "info") -> dict:
    """
    プロジェクト用ファイル（契約書PDF、画像など）を
    Drive の projects/<project_name>/<subfolder>/ にアップロード。

    Returns:
        dict: {"file_id": str, "url": str, "name": str}  失敗時は file_id="" 。
    """
    if not GDRIVE_FOLDER_ID or not file_bytes:
        return {"file_id": "", "url": "", "name": filename}

    try:
        from googleapiclient.http import MediaIoBaseUpload
        import io as _io

        service       = _get_service()
        projects_root = _get_or_create_folder(service, "projects",     GDRIVE_FOLDER_ID)
        proj_folder   = _get_or_create_folder(service, project_name,   projects_root)
        target_folder = _get_or_create_folder(service, subfolder,      proj_folder)

        buf   = _io.BytesIO(file_bytes)
        media = MediaIoBaseUpload(buf, mimetype=mime_type, resumable=False)
        meta  = {"name": filename, "parents": [target_folder]}
        result = service.files().create(
            body=meta, media_body=media,
            fields="id,webViewLink,webContentLink",
        ).execute()
        return {
            "file_id": result.get("id", ""),
            "url":     result.get("webViewLink", "")
                       or result.get("webContentLink", ""),
            "name":    filename,
        }
    except Exception as e:
        return {"file_id": "", "url": "", "name": filename, "error": str(e)}


def delete_drive_file(file_id: str) -> bool:
    """Drive 上のファイルを削除。失敗時 False。"""
    if not file_id:
        return False
    try:
        service = _get_service()
        service.files().delete(fileId=file_id).execute()
        return True
    except Exception:
        return False


def sync_to_drive():
    """
    DBファイルとObsidianノートをGoogle Driveにアップロードする。

    NOTE: Google Drive for Desktop（ローカル同期アプリ）を使っている場合は
    この関数を呼ぶ必要はありません。config.py の GDRIVE_LOCAL_PATH を
    正しいパスに設定するだけで自動同期されます。
    """
    if not GDRIVE_FOLDER_ID:
        print("[Drive] GDRIVE_FOLDER_ID が未設定のためスキップ")
        return

    try:
        service = _get_service()
    except Exception as e:
        print(f"[Drive] 接続失敗: {e}")
        return

    # DBファイルをアップロード
    if DB_PATH.exists():
        data_folder_id = _get_or_create_folder(service, "data", GDRIVE_FOLDER_ID)
        _upload_file(service, DB_PATH, data_folder_id)

    # Obsidianノートをアップロード
    if OBSIDIAN_DIR.exists():
        obs_folder_id = _get_or_create_folder(service, "Obsidian", GDRIVE_FOLDER_ID)
        for md_file in OBSIDIAN_DIR.rglob("*.md"):
            # サブフォルダ構造を再現
            relative = md_file.relative_to(OBSIDIAN_DIR)
            parent_id = obs_folder_id
            for part in relative.parts[:-1]:
                parent_id = _get_or_create_folder(service, part, parent_id)
            _upload_file(service, md_file, parent_id)

    print("[Drive] 同期完了")
