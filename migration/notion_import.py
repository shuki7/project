"""
NotionデータベースからSQLiteへの一括インポートスクリプト。

使い方:
    python -m migration.notion_import

事前準備:
    1. .env に NOTION_TOKEN を設定
    2. Notionの各データベースにIntegrationを「接続」しておく
       （ページの「...」→「接続」から追加）
"""

import sys
import time
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from notion_client import Client
from notion_client.errors import APIResponseError

from config import NOTION_TOKEN, NOTION_DB
from core.database import init_db, upsert_category, insert_expense, insert_revenue


def get_client() -> Client:
    if not NOTION_TOKEN:
        print("[ERROR] NOTION_TOKEN が設定されていません。.env を確認してください。")
        sys.exit(1)
    return Client(auth=NOTION_TOKEN)


def fetch_all_pages(client: Client, database_id: str) -> list[dict]:
    """ページネーションを処理してデータベースの全レコードを取得する。"""
    results = []
    cursor = None
    while True:
        kwargs = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        try:
            response = client.databases.query(**kwargs)
        except APIResponseError as e:
            print(f"[ERROR] Notion API エラー: {e}")
            print("→ データベースにIntegrationが「接続」されているか確認してください。")
            return results
        results.extend(response["results"])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
        time.sleep(0.3)  # レート制限対策
    return results


# ─────────────────────────────────────────────────────────────────────────────
# プロパティ取得ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _text(props: dict, key: str) -> str:
    p = props.get(key, {})
    ptype = p.get("type")
    if ptype == "title":
        parts = p.get("title", [])
    elif ptype == "rich_text":
        parts = p.get("rich_text", [])
    else:
        return ""
    return "".join(t.get("plain_text", "") for t in parts).strip()


def _number(props: dict, key: str) -> float:
    p = props.get(key, {})
    return p.get("number") or 0.0


def _date(props: dict, key: str) -> str:
    p = props.get(key, {})
    d = p.get("date") or {}
    return (d.get("start") or "")[:10]


def _select(props: dict, key: str) -> str:
    p = props.get(key, {})
    s = p.get("select") or {}
    return s.get("name") or ""


def _checkbox(props: dict, key: str) -> bool:
    p = props.get(key, {})
    return bool(p.get("checkbox", False))


def _relation_titles(client: Client, props: dict, key: str) -> list[str]:
    """リレーション先のページタイトルを取得する。"""
    p = props.get(key, {})
    ids = [r["id"] for r in p.get("relation", [])]
    titles = []
    for pid in ids:
        try:
            page = client.pages.retrieve(pid)
            title_prop = next(
                (v for v in page["properties"].values() if v["type"] == "title"), None
            )
            if title_prop:
                t = "".join(x.get("plain_text", "") for x in title_prop["title"])
                titles.append(t.strip())
        except Exception:
            pass
        time.sleep(0.2)
    return titles


# ─────────────────────────────────────────────────────────────────────────────
# カテゴリマスタのインポート
# ─────────────────────────────────────────────────────────────────────────────

def import_categories(client: Client) -> dict[str, str]:
    """カテゴリをインポートし、{NotionPageID: DB内ID} のマップを返す。"""
    print("\n[1/3] カテゴリマスタをインポート中...")
    pages = fetch_all_pages(client, NOTION_DB["category"])
    notion_to_db: dict[str, str] = {}
    for page in pages:
        props = page["properties"]
        name = _text(props, "名前") or _text(props, "Name") or _text(props, "カテゴリ名")
        if not name:
            # titleプロパティを探す
            for v in props.values():
                if v.get("type") == "title":
                    name = "".join(t.get("plain_text", "") for t in v["title"]).strip()
                    break
        if name:
            cat_id = upsert_category(name, notion_id=page["id"])
            notion_to_db[page["id"]] = cat_id
    print(f"   → {len(notion_to_db)} カテゴリ完了")
    return notion_to_db


# ─────────────────────────────────────────────────────────────────────────────
# 経費のインポート
# ─────────────────────────────────────────────────────────────────────────────

def import_expenses(client: Client, category_map: dict[str, str], year: int):
    key = f"expense_{year}"
    if key not in NOTION_DB:
        print(f"[SKIP] expense_{year} のDBが設定されていません")
        return
    print(f"\n[2/3] {year}年 経費をインポート中...")
    pages = fetch_all_pages(client, NOTION_DB[key])
    count = 0
    skipped = 0
    for page in pages:
        props = page["properties"]
        name   = _text(props, "名目")
        amount = _number(props, "金額")
        date   = _date(props, "日付")

        if not date:
            skipped += 1
            continue

        # カテゴリのリレーション先IDを取得
        cat_relations = props.get("カテゴリ", {}).get("relation", [])
        category_id = None
        if cat_relations:
            notion_cat_id = cat_relations[0]["id"]
            category_id = category_map.get(notion_cat_id)

        insert_expense(
            name=name or "（名目なし）",
            amount=amount,
            date=date,
            category_id=category_id,
            payment_method=_select(props, "支払い方法"),
            payee=_text(props, "支払先"),
            memo=_text(props, "メモ"),
            is_recurring=_checkbox(props, "定期"),
            notion_id=page["id"],
        )
        count += 1

    print(f"   → {count} 件インポート完了（{skipped} 件スキップ＝日付なし）")


# ─────────────────────────────────────────────────────────────────────────────
# 売上のインポート
# ─────────────────────────────────────────────────────────────────────────────

def import_revenue(client: Client, year: int):
    key = f"revenue_{year}"
    if key not in NOTION_DB:
        print(f"[SKIP] revenue_{year} のDBが設定されていません")
        return
    print(f"\n[3/3] {year}年 売上をインポート中...")
    pages = fetch_all_pages(client, NOTION_DB[key])
    count = 0
    skipped = 0
    for page in pages:
        props = page["properties"]
        name   = _text(props, "名前")
        amount = _number(props, "金額")
        date   = _date(props, "日付")

        if not date:
            skipped += 1
            continue

        insert_revenue(
            name=name or "（名前なし）",
            amount=amount,
            date=date,
            student_name=_text(props, "生徒名"),
            memo=_text(props, "メモ"),
            notion_id=page["id"],
        )
        count += 1

    print(f"   → {count} 件インポート完了（{skipped} 件スキップ＝日付なし）")


# ─────────────────────────────────────────────────────────────────────────────
# メインエントリーポイント
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("=" * 50)
    print("  Notion → SQLite インポート開始")
    print("=" * 50)

    # DBを初期化
    init_db()

    client = get_client()

    # カテゴリを先にインポート
    category_map = import_categories(client)

    # 2025年・2026年を処理
    for year in [2025, 2026]:
        import_expenses(client, category_map, year)
        import_revenue(client, year)

    print("\n" + "=" * 50)
    print("  インポート完了！")
    print("=" * 50)


if __name__ == "__main__":
    run()
