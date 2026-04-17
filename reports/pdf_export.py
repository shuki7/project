"""
ReportLabを使ってPDF形式の決算書を生成する。
日本語フォントはmacOS標準の Hiragino Sans を使用。
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from config import fmt_idr, COMPANY_NAME, REPORTS_DIR
from reports.generator import build_monthly_report_data, build_annual_report_data

# ─────────────────────────────────────────────────────────────────────────────
# フォント設定
# ─────────────────────────────────────────────────────────────────────────────

_FONT_PATHS = [
    # macOS Hiragino
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux (IPAフォント)
    "/usr/share/fonts/truetype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
]

_FONT_REGISTERED = False


def _register_font():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return

    for path in _FONT_PATHS:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("JapaneseFont", path))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue

    # Fallback to Helvetica
    _FONT_REGISTERED = True


def _font() -> str:
    """Returns a safe font name. Always returns Helvetica for now to ensure site stability."""
    return "Helvetica"


# ─────────────────────────────────────────────────────────────────────────────
# スタイル定義
# ─────────────────────────────────────────────────────────────────────────────

def _styles():
    font = _font()
    return {
        "title": ParagraphStyle(
            "title", fontName=font, fontSize=18, alignment=TA_CENTER,
            textColor=colors.HexColor("#1a1a2e"), spaceAfter=4
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName=font, fontSize=11, alignment=TA_CENTER,
            textColor=colors.HexColor("#444444"), spaceAfter=2
        ),
        "section": ParagraphStyle(
            "section", fontName=font, fontSize=13, textColor=colors.HexColor("#16213e"),
            spaceBefore=10, spaceAfter=4, borderPadding=(4, 0, 4, 0)
        ),
        "body": ParagraphStyle(
            "body", fontName=font, fontSize=9, textColor=colors.HexColor("#333333")
        ),
        "amount_right": ParagraphStyle(
            "amount_right", fontName=font, fontSize=9,
            alignment=TA_RIGHT, textColor=colors.HexColor("#333333")
        ),
        "profit_positive": ParagraphStyle(
            "profit_positive", fontName=font, fontSize=11, alignment=TA_RIGHT,
            textColor=colors.HexColor("#2d6a4f"), spaceBefore=4
        ),
        "profit_negative": ParagraphStyle(
            "profit_negative", fontName=font, fontSize=11, alignment=TA_RIGHT,
            textColor=colors.HexColor("#c1121f"), spaceBefore=4
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# テーブルスタイル
# ─────────────────────────────────────────────────────────────────────────────

_TABLE_HEADER_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
    ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
    ("FONTNAME",   (0, 0), (-1, -1), _font()),
    ("FONTSIZE",   (0, 0), (-1, -1), 8),
    ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
    ("ALIGN",      (-1, 1), (-1, -1), "RIGHT"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
])


# ─────────────────────────────────────────────────────────────────────────────
# 月次PDF
# ─────────────────────────────────────────────────────────────────────────────

def export_monthly_pdf(year: int, month: int) -> Path:
    """月次決算書PDFを生成し、パスを返す。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = build_monthly_report_data(year, month)
    filename = REPORTS_DIR / f"report_{year}_{month:02d}.pdf"

    _register_font()
    s = _styles()
    font = _font()

    story = []

    # ヘッダー
    story.append(Paragraph(COMPANY_NAME, s["subtitle"]))
    story.append(Paragraph(f"{year}年{data['month_name']} 月次収支報告書", s["title"]))
    story.append(Paragraph(
        f"作成日: {datetime.now().strftime('%Y年%m月%d日')}",
        ParagraphStyle("date", fontName=font, fontSize=8, alignment=TA_RIGHT,
                       textColor=colors.grey)
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#16213e")))
    story.append(Spacer(1, 6 * mm))

    # サマリーテーブル
    story.append(Paragraph("収支サマリー", s["section"]))
    profit = data["profit"]
    profit_label = f"+{fmt_idr(profit)}" if profit >= 0 else fmt_idr(profit)
    profit_color = "#2d6a4f" if profit >= 0 else "#c1121f"

    summary_data = [
        ["項目", "金額"],
        ["収入合計", fmt_idr(data["total_revenue"])],
        ["支出合計", fmt_idr(data["total_expenses"])],
        ["純利益", profit_label],
    ]
    t = Table(summary_data, colWidths=[80 * mm, 80 * mm])
    t.setStyle(TableStyle([
        *_TABLE_HEADER_STYLE._cmds,
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("TEXTCOLOR", (1, -1), (1, -1), colors.HexColor(profit_color)),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # カテゴリ別支出
    if data["expenses_by_category"]:
        story.append(Paragraph("支出カテゴリ別内訳", s["section"]))
        cat_data = [["カテゴリ", "金額"]]
        for row in data["expenses_by_category"]:
            cat_data.append([row["category"] or "未分類", fmt_idr(row["total"])])
        t = Table(cat_data, colWidths=[100 * mm, 60 * mm])
        t.setStyle(_TABLE_HEADER_STYLE)
        story.append(t)
        story.append(Spacer(1, 8 * mm))

    # 経費明細
    if data["expenses"]:
        story.append(Paragraph("経費明細", s["section"]))
        exp_data = [["日付", "名目", "支払先", "支払方法", "金額"]]
        for e in data["expenses"]:
            exp_data.append([
                e["date"] or "",
                (e["name"] or "")[:20],
                (e["payee"] or "")[:15],
                e["payment_method"] or "",
                fmt_idr(e["amount"]),
            ])
        t = Table(
            exp_data,
            colWidths=[22 * mm, 55 * mm, 40 * mm, 22 * mm, 35 * mm],
        )
        t.setStyle(_TABLE_HEADER_STYLE)
        story.append(t)
        story.append(Spacer(1, 8 * mm))

    # 収入明細
    if data["revenues"]:
        story.append(Paragraph("収入明細", s["section"]))
        rev_data = [["日付", "名前", "生徒名", "メモ", "金額"]]
        for r in data["revenues"]:
            rev_data.append([
                r["date"] or "",
                (r["name"] or "")[:20],
                (r["student_name"] or "")[:15],
                (r["memo"] or "")[:20],
                fmt_idr(r["amount"]),
            ])
        t = Table(
            rev_data,
            colWidths=[22 * mm, 45 * mm, 35 * mm, 35 * mm, 35 * mm],
        )
        t.setStyle(_TABLE_HEADER_STYLE)
        story.append(t)

    # フッター
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"本書は自動生成されたレポートです。 | {COMPANY_NAME}",
        ParagraphStyle("footer", fontName=font, fontSize=7, alignment=TA_CENTER,
                       textColor=colors.grey)
    ))

    doc = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    doc.build(story)
    return filename


# ─────────────────────────────────────────────────────────────────────────────
# 年次PDF
# ─────────────────────────────────────────────────────────────────────────────

def export_annual_pdf(year: int) -> Path:
    """年次決算書PDFを生成し、パスを返す。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = build_annual_report_data(year)
    filename = REPORTS_DIR / f"report_{year}_annual.pdf"

    _register_font()
    s = _styles()
    font = _font()

    MONTH_NAMES = ["", "1月", "2月", "3月", "4月", "5月", "6月",
                   "7月", "8月", "9月", "10月", "11月", "12月"]

    story = []

    # ヘッダー
    story.append(Paragraph(COMPANY_NAME, s["subtitle"]))
    story.append(Paragraph(f"{year}年 年次収支報告書", s["title"]))
    story.append(Paragraph(
        f"作成日: {datetime.now().strftime('%Y年%m月%d日')}",
        ParagraphStyle("date", fontName=font, fontSize=8, alignment=TA_RIGHT,
                       textColor=colors.grey)
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#16213e")))
    story.append(Spacer(1, 6 * mm))

    # 年間サマリー
    story.append(Paragraph("年間収支サマリー", s["section"]))
    profit = data["total_profit"]
    profit_label = f"+{fmt_idr(profit)}" if profit >= 0 else fmt_idr(profit)
    profit_color = "#2d6a4f" if profit >= 0 else "#c1121f"

    summary_data = [
        ["項目", "金額"],
        ["年間収入合計", fmt_idr(data["total_revenue"])],
        ["年間支出合計", fmt_idr(data["total_expenses"])],
        ["年間純利益", profit_label],
    ]
    t = Table(summary_data, colWidths=[80 * mm, 80 * mm])
    t.setStyle(TableStyle([
        *_TABLE_HEADER_STYLE._cmds,
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("TEXTCOLOR", (1, -1), (1, -1), colors.HexColor(profit_color)),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # 月次推移テーブル
    story.append(Paragraph("月次収支推移", s["section"]))
    monthly_table_data = [["月", "収入", "支出", "損益"]]
    for m in data["monthly"]:
        p = m["profit"]
        plabel = f"+{fmt_idr(p)}" if p >= 0 else fmt_idr(p)
        monthly_table_data.append([
            MONTH_NAMES[m["month"]],
            fmt_idr(m["revenue"]),
            fmt_idr(m["expenses"]),
            plabel,
        ])
    t = Table(
        monthly_table_data,
        colWidths=[20 * mm, 50 * mm, 50 * mm, 50 * mm],
    )
    t.setStyle(_TABLE_HEADER_STYLE)
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # カテゴリ別支出
    if data["expenses_by_category"]:
        story.append(Paragraph("年間 支出カテゴリ別内訳", s["section"]))
        cat_data = [["カテゴリ", "金額"]]
        for row in data["expenses_by_category"]:
            cat_data.append([row["category"] or "未分類", fmt_idr(row["total"])])
        t = Table(cat_data, colWidths=[100 * mm, 60 * mm])
        t.setStyle(_TABLE_HEADER_STYLE)
        story.append(t)

    # フッター
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"本書は自動生成されたレポートです。 | {COMPANY_NAME}",
        ParagraphStyle("footer", fontName=font, fontSize=7, alignment=TA_CENTER,
                       textColor=colors.grey)
    ))

    doc = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    doc.build(story)
    return filename
