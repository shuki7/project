import sys
import os
from pathlib import Path

# ── LiteSpeed/Passenger環境でUTF-8エンコーディングを強制 ──
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# プロジェクトルートをパスに追加
_here = Path(__file__).parent
sys.path.insert(0, str(_here))

# ── キャッシュをクリアして強制リロード ──
# サーバーが古いコードを掴んだまま離さない場合があるため、明示的にモジュールキャッシュを削除
for m in list(sys.modules.keys()):
    if any(p in m for p in ["app", "bot", "core", "reports", "sync", "web_app", "translations"]):
        del sys.modules[m]

from app import application as _flask_app  # noqa: E402

def application(environ, start_response):
    """/keiri プレフィックスをWSGIに伝えてurl_for()が正しいURLを生成するようにする。"""
    environ["SCRIPT_NAME"] = "/keiri"
    return _flask_app(environ, start_response)
