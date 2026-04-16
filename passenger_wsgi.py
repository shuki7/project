"""
cPanel "Setup Python App" (Passenger) エントリーポイント。

cPanelの設定:
  Application root:    public_html/shuki.link
  Application URL:     https://shuki.link
  Application startup file: passenger_wsgi.py
  Application Entry point:  application
"""

import sys
import os
from pathlib import Path

# LiteSpeed/Passenger環境でUTF-8エンコーディングを強制
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# プロジェクトルートをパスに追加
_here = Path(__file__).parent
sys.path.insert(0, str(_here))

# 仮想環境が有効な場合はsite-packagesをパスに追加
# （cPanel Python Appが自動設定する場合は不要）
_venv = _here / "venv"
if _venv.exists():
    import site
    site.addsitedir(str(_venv / "lib" /
                        f"python{sys.version_info.major}.{sys.version_info.minor}" /
                        "site-packages"))

from app import application  # noqa: E402  Flask WSGIアプリをエクスポート
