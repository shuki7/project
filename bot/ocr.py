"""
レシート画像をClaude APIで解析し、構造化データとして返す。
インドネシア語・英語・日本語に対応。
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from config import ANTHROPIC_API_KEY

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """あなたはレシート解析の専門家です。
レシート画像を分析し、以下のJSON形式で情報を抽出してください。
通貨はインドネシアルピア（IDR）を基本とします。

返すJSONの形式:
{
  "name": "店名または支払い名目（文字列）",
  "amount": 金額（数値、IDR。他通貨の場合はIDRに換算せずそのまま記載し currency_note で補足）,
  "date": "YYYY-MM-DD（レシートの日付。不明な場合はnull）",
  "payee": "支払先（店名など）",
  "category_hint": "推定カテゴリ（食費/交通費/光熱費/通信費/給料/備品/その他 から最も近いもの）",
  "payment_method": "支払い方法（CASH/TRANSFER/DEBIT/不明 から選択）",
  "memo": "補足情報（商品名の一覧など）",
  "currency_note": "IDR以外の通貨が使われている場合のみ記載",
  "confidence": "high/medium/low（読み取りの確信度）"
}

JSONのみ返してください。説明文は不要です。"""


def parse_receipt(image_path: str | Path) -> dict:
    """
    レシート画像を解析して構造化データを返す。

    Returns:
        dict: {name, amount, date, payee, category_hint,
               payment_method, memo, currency_note, confidence}
              解析失敗時は {"error": "メッセージ"} を返す。
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return {"error": f"ファイルが見つかりません: {image_path}"}

    # 画像をbase64エンコード
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    suffix = image_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "このレシートを解析してください。",
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text.strip()
        # JSONブロックが含まれる場合に対応
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失敗: {e}", "raw": raw}
    except Exception as e:
        return {"error": str(e)}


def parse_receipt_from_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Telegramから受け取ったバイト列を直接解析する。"""
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": "このレシートを解析してください。"},
                    ],
                }
            ],
        )

        raw = response.content[0].text.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失敗: {e}"}
    except Exception as e:
        return {"error": str(e)}


def classify_category(name: str, payee: str, hint: str, existing_categories: list[str]) -> str:
    """
    支出名・支払先・ヒントから最適なカテゴリを選択する。
    existing_categories に一致するものを返す。一致しない場合はhintをそのまま返す。
    """
    if not existing_categories:
        return hint or "その他"

    # 完全一致・部分一致をまず試みる
    for cat in existing_categories:
        if cat == hint:
            return cat

    # Claudeに選択させる
    try:
        client = _get_client()
        cats_str = "\n".join(f"- {c}" for c in existing_categories)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"以下のカテゴリ一覧から、最も適切な1つを選んでください。\n\n"
                        f"カテゴリ一覧:\n{cats_str}\n\n"
                        f"支出名: {name}\n"
                        f"支払先: {payee}\n"
                        f"ヒント: {hint}\n\n"
                        f"カテゴリ名のみ返してください。"
                    ),
                }
            ],
        )
        selected = response.content[0].text.strip()
        # 返答がリストに含まれているか確認
        for cat in existing_categories:
            if cat in selected or selected in cat:
                return cat
        return hint or "その他"
    except Exception:
        return hint or "その他"
