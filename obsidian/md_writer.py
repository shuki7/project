"""
Obsidian用Markdownファイルを生成する。
Google Drive同期フォルダ内の Obsidian/ ディレクトリに書き出す。

生成されるファイル構造:
  Obsidian/
    _index.md                     ← ダッシュボード
    2026/
      2026-index.md               ← 年次サマリー
      2026-04/
        2026-04-index.md          ← 月次サマリー
        2026-04-15.md             ← 日次メモ（支出・収入一覧）
"""

import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import fmt_idr, OBSIDIAN_DIR, COMPANY_NAME
from core.database import (
    get_expenses,
    get_revenue,
    sum_expenses,
    sum_revenue,
    monthly_summary,
    sum_expenses_by_category,
)

MONTH_NAMES = ["", "1月", "2月", "3月", "4月", "5月", "6月",
               "7月", "8月", "9月", "10月", "11月", "12月"]


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# ダッシュボード（_index.md）
# ─────────────────────────────────────────────────────────────────────────────

def write_dashboard():
    now = datetime.now()
    year, month = now.year, now.month

    inc = sum_revenue(year, month)
    exp = sum_expenses(year, month)
    profit = inc - exp
    sign = "+" if profit >= 0 else ""

    annual_inc = sum_revenue(year)
    annual_exp = sum_expenses(year)
    annual_profit = annual_inc - annual_exp
    annual_sign = "+" if annual_profit >= 0 else ""

    lines = [
        f"# {COMPANY_NAME} 家計簿ダッシュボード",
        f"",
        f"> 最終更新: {now.strftime('%Y年%m月%d日 %H:%M')}",
        f"",
        f"## 今月の収支（{year}年{MONTH_NAMES[month]}）",
        f"",
        f"| 項目 | 金額 |",
        f"|------|------|",
        f"| 収入 | {fmt_idr(inc)} |",
        f"| 支出 | {fmt_idr(exp)} |",
        f"| 損益 | {sign}{fmt_idr(profit)} |",
        f"",
        f"## {year}年 年間累計",
        f"",
        f"| 項目 | 金額 |",
        f"|------|------|",
        f"| 収入 | {fmt_idr(annual_inc)} |",
        f"| 支出 | {fmt_idr(annual_exp)} |",
        f"| 損益 | {annual_sign}{fmt_idr(annual_profit)} |",
        f"",
        f"## 月次リンク",
        f"",
    ]

    for m in range(1, month + 1):
        lines.append(f"- [[{year}/{year}-{m:02d}/{year}-{m:02d}-index|{year}年{MONTH_NAMES[m]}]]")

    _write(OBSIDIAN_DIR / "_index.md", "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# 月次サマリー
# ─────────────────────────────────────────────────────────────────────────────

def write_monthly_index(year: int, month: int):
    inc = sum_revenue(year, month)
    exp = sum_expenses(year, month)
    profit = inc - exp
    sign = "+" if profit >= 0 else ""

    by_cat = sum_expenses_by_category(year, month)
    expenses = get_expenses(year, month)
    revenues = get_revenue(year, month)

    lines = [
        f"# {year}年{MONTH_NAMES[month]} 収支サマリー",
        f"",
        f"> [[../{year}-index|{year}年 年間サマリーへ]] | [[../../_index|ダッシュボードへ]]",
        f"",
        f"## 収支サマリー",
        f"",
        f"| 項目 | 金額 |",
        f"|------|------|",
        f"| 収入 | {fmt_idr(inc)} |",
        f"| 支出 | {fmt_idr(exp)} |",
        f"| 損益 | **{sign}{fmt_idr(profit)}** |",
        f"",
    ]

    if by_cat:
        lines += [
            "## 支出カテゴリ別",
            "",
            "| カテゴリ | 金額 |",
            "|----------|------|",
        ]
        for row in by_cat:
            lines.append(f"| {row['category'] or '未分類'} | {fmt_idr(row['total'])} |")
        lines.append("")

    if expenses:
        lines += [
            "## 経費一覧",
            "",
            "| 日付 | 名目 | カテゴリ | 金額 | 支払方法 |",
            "|------|------|----------|------|----------|",
        ]
        for e in expenses:
            lines.append(
                f"| {e['date']} | {e['name']} | {e.get('category_name') or ''} "
                f"| {fmt_idr(e['amount'])} | {e.get('payment_method') or ''} |"
            )
        lines.append("")

    if revenues:
        lines += [
            "## 収入一覧",
            "",
            "| 日付 | 名前 | 生徒名 | 金額 |",
            "|------|------|--------|------|",
        ]
        for r in revenues:
            lines.append(
                f"| {r['date']} | {r['name']} | {r.get('student_name') or ''} "
                f"| {fmt_idr(r['amount'])} |"
            )

    path = OBSIDIAN_DIR / f"{year}" / f"{year}-{month:02d}" / f"{year}-{month:02d}-index.md"
    _write(path, "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# 年次サマリー
# ─────────────────────────────────────────────────────────────────────────────

def write_annual_index(year: int):
    summary = monthly_summary(year)
    total_rev = sum(m["revenue"] for m in summary)
    total_exp = sum(m["expenses"] for m in summary)
    total_profit = total_rev - total_exp
    sign = "+" if total_profit >= 0 else ""

    lines = [
        f"# {year}年 年間収支サマリー — {COMPANY_NAME}",
        f"",
        f"> [[../_index|ダッシュボードへ]]",
        f"",
        f"## 年間合計",
        f"",
        f"| 項目 | 金額 |",
        f"|------|------|",
        f"| 年間収入 | {fmt_idr(total_rev)} |",
        f"| 年間支出 | {fmt_idr(total_exp)} |",
        f"| 年間損益 | **{sign}{fmt_idr(total_profit)}** |",
        f"",
        f"## 月次推移",
        f"",
        f"| 月 | 収入 | 支出 | 損益 |",
        f"|----|------|------|------|",
    ]

    for m in summary:
        p = m["profit"]
        plabel = f"+{fmt_idr(p)}" if p >= 0 else fmt_idr(p)
        mn = MONTH_NAMES[m["month"]]
        link = f"[[{year}-{m['month']:02d}/{year}-{m['month']:02d}-index|{mn}]]"
        lines.append(f"| {link} | {fmt_idr(m['revenue'])} | {fmt_idr(m['expenses'])} | {plabel} |")

    path = OBSIDIAN_DIR / f"{year}" / f"{year}-index.md"
    _write(path, "\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# 一括生成
# ─────────────────────────────────────────────────────────────────────────────

def write_all_notes(year: int = None, month: int = None):
    """ダッシュボード・年次・月次ノートを一括生成する。"""
    now = datetime.now()
    year = year or now.year
    month = month or now.month

    write_dashboard()
    write_annual_index(year)
    write_monthly_index(year, month)

    print(f"[Obsidian] ノート生成完了: {year}年{MONTH_NAMES[month]}")
