"""
収支レポートデータを生成する。
Telegram表示用テキストとPDF用データ構造の両方を提供。
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import fmt_idr, COMPANY_NAME
from core.database import (
    get_expenses,
    get_revenue,
    sum_expenses,
    sum_revenue,
    sum_expenses_by_category,
    monthly_summary,
)

MONTH_NAMES = [
    "", "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]


def build_monthly_report_text(year: int, month: int) -> str:
    """Telegram表示用の月次収支レポートテキストを生成する。"""
    inc = sum_revenue(year, month)
    exp = sum_expenses(year, month)
    profit = inc - exp
    sign = "+" if profit >= 0 else ""

    by_cat = sum_expenses_by_category(year, month)

    lines = [
        f"*{year}年{MONTH_NAMES[month]} 収支レポート*",
        f"_{COMPANY_NAME}_",
        "─" * 22,
        f"収入合計: `{fmt_idr(inc)}`",
        f"支出合計: `{fmt_idr(exp)}`",
        f"損  益: `{sign}{fmt_idr(profit)}`",
        "",
    ]

    if by_cat:
        lines.append("*支出カテゴリ別内訳*")
        for row in by_cat:
            cat = row["category"] or "未分類"
            lines.append(f"  {cat}: `{fmt_idr(row['total'])}`")

    # 売上上位5件
    revenues = get_revenue(year, month)
    if revenues:
        lines.append("")
        lines.append("*収入明細（上位5件）*")
        for r in revenues[:5]:
            lines.append(f"  {r['date']}: {r['name']} `{fmt_idr(r['amount'])}`")

    return "\n".join(lines)


def build_annual_report_data(year: int) -> dict:
    """
    年次レポート用のデータ構造を返す。
    PDF生成やObsidianのMarkdown生成に使用。
    """
    summary = monthly_summary(year)
    total_revenue = sum(m["revenue"] for m in summary)
    total_expenses = sum(m["expenses"] for m in summary)
    total_profit = total_revenue - total_expenses

    by_cat = sum_expenses_by_category(year)

    return {
        "year": year,
        "company": COMPANY_NAME,
        "generated_at": datetime.now().isoformat(),
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "total_profit": total_profit,
        "monthly": summary,
        "expenses_by_category": by_cat,
    }


def build_monthly_report_data(year: int, month: int) -> dict:
    """月次レポート用のデータ構造を返す。"""
    inc = sum_revenue(year, month)
    exp = sum_expenses(year, month)
    by_cat = sum_expenses_by_category(year, month)

    expenses = get_expenses(year, month)
    revenues = get_revenue(year, month)

    return {
        "year": year,
        "month": month,
        "month_name": MONTH_NAMES[month],
        "company": COMPANY_NAME,
        "generated_at": datetime.now().isoformat(),
        "total_revenue": inc,
        "total_expenses": exp,
        "profit": inc - exp,
        "expenses_by_category": by_cat,
        "expenses": expenses,
        "revenues": revenues,
    }
