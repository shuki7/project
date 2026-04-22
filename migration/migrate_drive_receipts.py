"""
既存の Drive `receipts/YYYY-MM/*` を
`projects/🇮🇩BALI 🇯🇵JAPAN 🌎️DREAM/expenses/YYYY-MM/` 配下に移動する。

Drive のファイル移動は `addParents`+`removeParents` で行うため、
ファイル ID は変わらず DB の `gdrive:<id>` 参照はそのまま使える。

実行: python -m migration.migrate_drive_receipts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync.gdrive import _get_service, _get_or_create_folder
from config import GDRIVE_FOLDER_ID

TARGET_PROJECT = "🇮🇩BALI 🇯🇵JAPAN 🌎️DREAM"


def main():
    if not GDRIVE_FOLDER_ID:
        print("GDRIVE_FOLDER_ID が未設定")
        return

    service = _get_service()

    # 旧 receipts ルートを取得（無ければ何もしない）
    q = (
        f"name='receipts' and "
        f"'{GDRIVE_FOLDER_ID}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = service.files().list(q=q, fields="files(id,name)").execute()
    receipts = res.get("files", [])
    if not receipts:
        print("[skip] 旧 receipts/ フォルダが見つかりません。マイグレーション不要。")
        return
    receipts_root = receipts[0]["id"]
    print(f"[found] receipts root: {receipts_root}")

    # 移動先 projects/<TARGET>/expenses を用意
    projects_root = _get_or_create_folder(service, "projects", GDRIVE_FOLDER_ID)
    proj_folder   = _get_or_create_folder(service, TARGET_PROJECT, projects_root)
    expenses_root = _get_or_create_folder(service, "expenses", proj_folder)
    print(f"[target] projects/{TARGET_PROJECT}/expenses → {expenses_root}")

    # 月フォルダ一覧を取得
    q_months = (
        f"'{receipts_root}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    months = service.files().list(
        q=q_months, fields="files(id,name)", pageSize=200,
    ).execute().get("files", [])
    print(f"[months] {len(months)} found")

    moved_files = 0
    moved_months = 0
    for m in sorted(months, key=lambda x: x["name"]):
        old_month_id = m["id"]
        month_name   = m["name"]  # "YYYY-MM"

        # 移動先月フォルダを用意
        new_month_id = _get_or_create_folder(service, month_name, expenses_root)

        # 月フォルダ内のファイルをページネーションで全部取得
        page_token = None
        count = 0
        while True:
            r = service.files().list(
                q=f"'{old_month_id}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,parents)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            for f in r.get("files", []):
                fid = f["id"]
                # 親を付け替え
                try:
                    service.files().update(
                        fileId=fid,
                        addParents=new_month_id,
                        removeParents=old_month_id,
                        fields="id, parents",
                    ).execute()
                    count += 1
                except Exception as e:
                    print(f"  ✗ {f.get('name')} ({fid}): {e}")
            page_token = r.get("nextPageToken")
            if not page_token:
                break

        moved_files += count
        moved_months += 1
        print(f"  [{month_name}] moved {count} file(s)")

        # 空になった旧月フォルダを削除
        try:
            service.files().delete(fileId=old_month_id).execute()
        except Exception as e:
            print(f"  - 旧 {month_name} 削除失敗（残しても支障なし）: {e}")

    # 旧 receipts ルート自体も削除（中身がなくなっていれば）
    try:
        service.files().delete(fileId=receipts_root).execute()
        print("[cleanup] 旧 receipts/ ルートを削除")
    except Exception as e:
        print(f"[cleanup] 旧 receipts/ 削除はスキップ: {e}")

    print(f"\n[done] {moved_months} 月 / {moved_files} ファイルを移動")


if __name__ == "__main__":
    main()
