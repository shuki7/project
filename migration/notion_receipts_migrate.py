"""
Notion に添付されている領収書画像を Google Drive へ移行するスクリプト。

使い方（サーバーの venv で実行）:
    python -m migration.notion_receipts_migrate
    python -m migration.notion_receipts_migrate --dry-run   # 確認のみ

動作:
    1. SQLite の expenses/revenue から notion_id を持つレコードを取得
    2. Notion API でページを取得し、ファイル添付・画像ブロックを探す
    3. ダウンロード → 圧縮 → Google Drive にアップロード
    4. receipt_path を "gdrive:<fileId>" で更新

注意:
    - Notion のファイル URL は期限付き（約1時間）なので、すぐに実行してください
    - Google Drive が未設定の場合は RECEIPTS_DIR にローカル保存します
"""

import sys
import time
import argparse
import requests
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notion_client import Client
from notion_client.errors import APIResponseError

from config import NOTION_TOKEN, NOTION_DB, RECEIPTS_DIR
from core.database import init_db, get_connection, transaction
from bot.ocr import compress_image
from sync.gdrive import upload_receipt_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Notion ページからファイル URL を取得
# ─────────────────────────────────────────────────────────────────────────────

def _get_file_urls_from_page(client: Client, page_id: str) -> list[str]:
    """
    ページのプロパティとコンテンツブロックから画像/ファイル URL を収集する。
    """
    urls = []

    # 1) プロパティの files 型を探す
    try:
        page = client.pages.retrieve(page_id)
        for prop in page["properties"].values():
            if prop.get("type") == "files":
                for f in prop.get("files", []):
                    if f.get("type") == "file":
                        url = f["file"].get("url")
                        if url:
                            urls.append(url)
                    elif f.get("type") == "external":
                        url = f["external"].get("url")
                        if url:
                            urls.append(url)
    except Exception as e:
        print(f"      プロパティ取得失敗: {e}")

    if urls:
        return urls  # プロパティで見つかればコンテンツは不要

    # 2) ページのブロックコンテンツから image ブロックを探す
    try:
        blocks = client.blocks.children.list(page_id)
        for block in blocks.get("results", []):
            btype = block.get("type")
            if btype == "image":
                img = block["image"]
                if img.get("type") == "file":
                    url = img["file"].get("url")
                    if url:
                        urls.append(url)
                elif img.get("type") == "external":
                    url = img["external"].get("url")
                    if url:
                        urls.append(url)
    except Exception as e:
        print(f"      ブロック取得失敗: {e}")

    return urls


def _download(url: str) -> bytes:
    """URL から画像バイト列をダウンロードする。"""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


# ─────────────────────────────────────────────────────────────────────────────
# 1レコードを処理
# ─────────────────────────────────────────────────────────────────────────────

def _process_record(client: Client, record: dict,
                    table: str, dry_run: bool) -> str:
    """
    1件のレコードに対して画像を取得し Drive にアップロードして receipt_path を返す。
    失敗時は空文字を返す。
    """
    notion_id = record["notion_id"]
    date_str  = record.get("date", "")[:10] or datetime.now().strftime("%Y-%m-%d")
    name      = record.get("name", "")[:30]

    print(f"  [{table}] {date_str} {name} ...", end=" ", flush=True)

    urls = _get_file_urls_from_page(client, notion_id)
    if not urls:
        print("画像なし → スキップ")
        return ""

    # 最初の1枚だけ処理
    try:
        raw_bytes = _download(urls[0])
    except Exception as e:
        print(f"DL失敗: {e}")
        return ""

    compressed = compress_image(raw_bytes)
    orig_kb    = len(raw_bytes) // 1024
    comp_kb    = len(compressed) // 1024
    filename   = f"{date_str.replace('-', '')}_{notion_id[:8]}.jpg"

    if dry_run:
        print(f"[DRY-RUN] {orig_kb}KB → {comp_kb}KB  ファイル名: {filename}")
        return "dry-run"

    # Google Drive へアップロード
    drive_id = upload_receipt_bytes(compressed, filename, date_str)
    if drive_id:
        print(f"Drive保存 {orig_kb}KB→{comp_kb}KB  id={drive_id[:12]}...")
        return f"gdrive:{drive_id}"

    # Drive 未設定 → ローカル保存
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = RECEIPTS_DIR / filename
    local_path.write_bytes(compressed)
    print(f"ローカル保存 {comp_kb}KB  {filename}")
    return str(local_path)


# ─────────────────────────────────────────────────────────────────────────────
# DB 更新
# ─────────────────────────────────────────────────────────────────────────────

def _update_receipt_path(table: str, record_id: str, receipt_path: str):
    with transaction() as conn:
        conn.execute(
            f"UPDATE {table} SET receipt_path = ? WHERE id = ?",
            (receipt_path, record_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    if not NOTION_TOKEN:
        print("[ERROR] NOTION_TOKEN が未設定です。")
        sys.exit(1)

    init_db()
    client = Client(auth=NOTION_TOKEN)
    conn = get_connection()

    # receipt_path が空で notion_id がある経費を取得
    expenses = conn.execute(
        "SELECT id, notion_id, date, name FROM expenses "
        "WHERE notion_id IS NOT NULL AND (receipt_path IS NULL OR receipt_path = '') "
        "ORDER BY date"
    ).fetchall()

    # 売上も同様
    revenues = conn.execute(
        "SELECT id, notion_id, date, name FROM revenue "
        "WHERE notion_id IS NOT NULL AND (receipt_path IS NULL OR receipt_path = '') "
        "ORDER BY date"
    ).fetchall()

    total = len(expenses) + len(revenues)
    print(f"\n対象: 経費 {len(expenses)} 件 + 売上 {len(revenues)} 件 = {total} 件")
    if dry_run:
        print("※ DRY-RUN モード（DB・Drive への書き込みなし）\n")
    else:
        print()

    done = skip = fail = 0

    for rec in expenses:
        receipt_path = _process_record(client, dict(rec), "expenses", dry_run)
        if receipt_path == "":
            skip += 1
        elif receipt_path == "dry-run":
            done += 1
        elif receipt_path:
            _update_receipt_path("expenses", rec["id"], receipt_path)
            done += 1
        else:
            fail += 1
        time.sleep(0.4)  # Notion API レート制限対策

    for rec in revenues:
        receipt_path = _process_record(client, dict(rec), "revenue", dry_run)
        if receipt_path == "":
            skip += 1
        elif receipt_path == "dry-run":
            done += 1
        elif receipt_path:
            _update_receipt_path("revenue", rec["id"], receipt_path)
            done += 1
        else:
            fail += 1
        time.sleep(0.4)

    print(f"\n完了: {done} 件保存 / {skip} 件スキップ（画像なし）/ {fail} 件失敗")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notion 添付画像を Drive へ移行")
    parser.add_argument("--dry-run", action="store_true",
                        help="書き込まずに対象件数と画像有無だけ確認する")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
