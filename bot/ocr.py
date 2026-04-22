"""
レシート画像を Google Gemini Flash API で解析し、構造化データとして返す。
インドネシア語・英語・日本語に対応。

compress_image() もここで提供し、Telegram・Web 両方から利用する。
"""

import io
import json
import sys
from pathlib import Path
from typing import Union

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import GEMINI_API_KEY

_model = None


def _get_model():
    global _model
    if _model is None:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel("gemini-1.5-flash")
    return _model


RECEIPT_PROMPT = """このレシート・領収書の画像を解析して、以下のJSON形式で情報を抽出してください。
通貨はインドネシアルピア（IDR）を基本とします。

{
  "name": "店名または支払い名目（文字列）",
  "amount": 金額（数値、IDR。他通貨の場合はそのまま記載し currency_note で補足）,
  "date": "YYYY-MM-DD（レシートの日付。不明な場合はnull）",
  "payee": "支払先（店名など）",
  "category_hint": "推定カテゴリ（食費/交通費/光熱費/通信費/給料/備品/その他 から最も近いもの）",
  "payment_method": "支払い方法（CASH/TRANSFER/DEBIT/不明 から選択）",
  "memo": "補足情報（商品名の一覧など）",
  "currency_note": "IDR以外の通貨が使われている場合のみ記載",
  "confidence": "high/medium/low（読み取りの確信度）"
}

JSONのみ返してください。説明文もマークダウンのコードブロックも不要です。"""


# ─────────────────────────────────────────────────────────────────────────────
# 画像圧縮
# ─────────────────────────────────────────────────────────────────────────────

def compress_image(image_bytes: bytes,
                   max_px: int = 1600,
                   quality: int = 83) -> bytes:
    """
    画質を保ちながらファイルサイズを圧縮する。

    - 長辺を max_px 以下にリサイズ（それ以下なら変更なし）
    - EXIF の回転情報を反映
    - RGBA/P モードを RGB に変換
    - JPEG quality=83 で再エンコード（原画の 20〜40% 程度になる）
    - 圧縮後のほうが大きい場合はオリジナルを返す
    """
    if not _PIL_AVAILABLE:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # EXIF 回転補正（274 = Orientation タグ）
        try:
            exif = img._getexif()
            if exif:
                orientation = exif.get(274)
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        img.thumbnail((max_px, max_px), Image.LANCZOS)

        buf = io.BytesIO()
        # WebP形式で保存（method=6 は圧縮効率最大設定）
        img.save(buf, format="WEBP", quality=quality, method=6)
        compressed = buf.getvalue()
        return compressed if len(compressed) < len(image_bytes) else image_bytes

    except Exception:
        return image_bytes


# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

def parse_receipt_from_bytes(image_bytes: bytes,
                              media_type: str = "image/jpeg") -> dict:
    """バイト列のレシート画像を Gemini Flash で解析する。"""
    try:
        model = _get_model()
        if not _PIL_AVAILABLE:
            return {"error": "Pillow未インストール。pip install Pillow"}
        img = Image.open(io.BytesIO(image_bytes))
        response = model.generate_content([RECEIPT_PROMPT, img])
        raw = response.text.strip()

        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失敗: {e}"}
    except Exception as e:
        return {"error": str(e)}


def parse_receipt(image_path: Union[str, Path]) -> dict:
    """ファイルパスからレシートを解析する。"""
    image_path = Path(image_path)
    if not image_path.exists():
        return {"error": f"ファイルが見つかりません: {image_path}"}
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    suffix = image_path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
    }
    return parse_receipt_from_bytes(image_bytes, media_map.get(suffix, "image/jpeg"))


# ─────────────────────────────────────────────────────────────────────────────
# カテゴリ分類
# ─────────────────────────────────────────────────────────────────────────────

def classify_category(name: str, payee: str, hint: str,
                       existing_categories: list) -> str:
    """支出名・支払先・ヒントから既存カテゴリの中で最適なものを返す。"""
    if not existing_categories:
        return hint or "その他"

    # 完全一致
    for cat in existing_categories:
        if cat == hint:
            return cat

    try:
        model = _get_model()
        cats_str = "\n".join(f"- {c}" for c in existing_categories)
        prompt = (
            f"以下のカテゴリ一覧から最も適切な1つを選んでください。\n\n"
            f"カテゴリ一覧:\n{cats_str}\n\n"
            f"支出名: {name}\n支払先: {payee}\nヒント: {hint}\n\n"
            f"カテゴリ名のみ返してください。"
        )
        response = model.generate_content(prompt)
        selected = response.text.strip()
        for cat in existing_categories:
            if cat in selected or selected in cat:
                return cat
        return hint or "その他"
    except Exception:
        return hint or "その他"
