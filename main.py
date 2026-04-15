"""
家計簿アプリ — メインエントリーポイント

使い方:
    python main.py bot       # Telegramボット起動
    python main.py import    # Notionからデータをインポート
    python main.py report    # 今月のレポートをターミナルに表示
    python main.py pdf       # 今月のPDFを生成
    python main.py pdf 2026  # 2026年の年次PDFを生成
    python main.py obsidian  # Obsidianノートを再生成
    python main.py sync      # Google Driveに同期
"""

import sys
from datetime import datetime


def cmd_bot():
    from bot.telegram_bot import main
    main()


def cmd_import():
    from migration.notion_import import run
    run()


def cmd_report(args):
    from core.database import init_db
    from reports.generator import build_monthly_report_text

    init_db()
    now = datetime.now()
    year, month = now.year, now.month

    if args:
        try:
            parts = args[0].split("-")
            year = int(parts[0])
            if len(parts) > 1:
                month = int(parts[1])
        except (ValueError, IndexError):
            print("形式が違います。例: python main.py report 2026-03")
            return

    # Markdownの装飾を外してプレーンテキストに
    text = build_monthly_report_text(year, month)
    text = text.replace("*", "").replace("`", "").replace("_", "")
    print(text)


def cmd_pdf(args):
    from core.database import init_db
    from reports.pdf_export import export_monthly_pdf, export_annual_pdf

    init_db()
    now = datetime.now()
    year, month = now.year, now.month

    if args:
        try:
            parts = args[0].split("-")
            year = int(parts[0])
            if len(parts) == 1:
                # 年次
                path = export_annual_pdf(year)
                print(f"年次PDFを生成しました: {path}")
                return
            else:
                month = int(parts[1])
        except (ValueError, IndexError):
            print("形式が違います。例: python main.py pdf 2026-03 または python main.py pdf 2026")
            return

    path = export_monthly_pdf(year, month)
    print(f"月次PDFを生成しました: {path}")


def cmd_obsidian(args):
    from core.database import init_db
    from obsidian.md_writer import write_all_notes

    init_db()
    now = datetime.now()
    year, month = now.year, now.month

    if args:
        try:
            parts = args[0].split("-")
            year = int(parts[0])
            if len(parts) > 1:
                month = int(parts[1])
        except (ValueError, IndexError):
            pass

    write_all_notes(year, month)


def cmd_sync():
    from sync.gdrive import sync_to_drive
    sync_to_drive()


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return

    command = args[0]
    rest = args[1:]

    commands = {
        "bot":      lambda: cmd_bot(),
        "import":   lambda: cmd_import(),
        "report":   lambda: cmd_report(rest),
        "pdf":      lambda: cmd_pdf(rest),
        "obsidian": lambda: cmd_obsidian(rest),
        "sync":     lambda: cmd_sync(),
    }

    if command not in commands:
        print(f"不明なコマンド: {command}")
        print(__doc__)
        return

    commands[command]()


if __name__ == "__main__":
    main()
