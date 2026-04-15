"""
TelegramのWebhookを設定・確認・削除するスクリプト。

使い方（サーバー上のSSHで実行）:
    python setup_webhook.py set    https://yourdomain.com
    python setup_webhook.py check
    python setup_webhook.py delete
"""

import sys
import requests

from config import TELEGRAM_TOKEN

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def set_webhook(domain: str):
    url = f"{BASE_URL}/setWebhook"
    webhook_url = f"{domain}/webhook/{TELEGRAM_TOKEN}"
    resp = requests.post(url, json={"url": webhook_url})
    data = resp.json()
    if data.get("ok"):
        print(f"Webhook設定完了: {webhook_url}")
    else:
        print(f"エラー: {data}")


def check_webhook():
    resp = requests.get(f"{BASE_URL}/getWebhookInfo")
    data = resp.json()
    info = data.get("result", {})
    print(f"URL: {info.get('url', '未設定')}")
    print(f"保留中の更新数: {info.get('pending_update_count', 0)}")
    if info.get("last_error_message"):
        print(f"最後のエラー: {info['last_error_message']}")


def delete_webhook():
    resp = requests.post(f"{BASE_URL}/deleteWebhook")
    data = resp.json()
    if data.get("ok"):
        print("Webhook削除完了（Pollingモードに戻す場合に使用）")
    else:
        print(f"エラー: {data}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "set":
        if len(args) < 2:
            print("ドメインを指定してください。例: python setup_webhook.py set https://yourdomain.com")
            sys.exit(1)
        set_webhook(args[1].rstrip("/"))
    elif cmd == "check":
        check_webhook()
    elif cmd == "delete":
        delete_webhook()
    else:
        print(f"不明なコマンド: {cmd}")
