"""
cPanel Python App (Passenger WSGI) エントリーポイント。
Telegramのwebhookリクエストを受け取りボット処理を実行する。

cPanel の "Setup Python App" でこのファイルを指定する:
    Application startup file: app.py
    Application Entry point: application
"""

import os
import sys
import json
import logging
from pathlib import Path

from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application

# ボットのハンドラーを登録するモジュール
from bot.webhook_handlers import register_handlers
from config import TELEGRAM_TOKEN
from core.database import init_db
from web_app import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Flask & Telegram Application の初期化 ────────────────────────────────────

flask_app = Flask(__name__)
flask_app.secret_key = os.getenv("SECRET_KEY", "keiri-secret-2026")
flask_app.config['TEMPLATES_AUTO_RELOAD'] = True  # テンプレート変更を即反映
flask_app.register_blueprint(web)
init_db()

ptb_app = None
if TELEGRAM_TOKEN:
    try:
        ptb_app = Application.builder().token(TELEGRAM_TOKEN).build()
        register_handlers(ptb_app)
        logger.info("Telegram Bot 初期化完了")
    except Exception as e:
        logger.warning(f"Telegram初期化スキップ: {e}")

# cPanel Passenger が要求する WSGI callable
application = flask_app


# ── Webhook エンドポイント ────────────────────────────────────────────────────

@flask_app.route("/keiri/telegram_webhook", methods=["POST"])
def telegram_webhook():
    """Telegramからのupdateを受け取る（LiteSpeedプロキシ経由）。
    Webhook URL: https://shuki.link/keiri/telegram_webhook
    """
    if not ptb_app:
        return Response("telegram not configured", status=503)
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, ptb_app.bot)

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(ptb_app.initialize())
            loop.run_until_complete(ptb_app.process_update(update))
        finally:
            loop.close()

        return Response("ok", status=200)
    except Exception as e:
        logger.error(f"Webhook処理エラー: {e}")
        return Response("error", status=500)


@flask_app.route("/keiri/health", methods=["GET"])
def health():
    """死活監視用。"""
    return Response("ok", status=200)


# ── ローカル開発用（直接実行時） ──────────────────────────────────────────────

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=8000, debug=True)
