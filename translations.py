"""
日本語 / インドネシア語 翻訳辞書。
テンプレートで {{ T.key }} または {{ T['key'] }} で呼び出す。
"""

MONTHS_JA = ["1月","2月","3月","4月","5月","6月",
              "7月","8月","9月","10月","11月","12月"]
MONTHS_ID = ["Jan","Feb","Mar","Apr","Mei","Jun",
              "Jul","Agu","Sep","Okt","Nov","Des"]
MONTHS_ID_FULL = ["Januari","Februari","Maret","April","Mei","Juni",
                  "Juli","Agustus","September","Oktober","November","Desember"]

TRANSLATIONS = {
    "ja": {
        # ナビ
        "nav_dashboard":   "ダッシュボード",
        "nav_expenses":    "経費",
        "nav_revenue":     "収入",
        "nav_categories":  "勘定科目",
        "nav_receipt":     "📷レシート",
        "nav_budget":      "予算",
        "nav_financial":   "決算書",
        "nav_logout":      "ログアウト",
        "nav_search_ph":   "検索...",
        "nav_search_btn":  "検索",

        # ダッシュボード見出し
        "dash_title":        "ダッシュボード",
        "this_month":        "{year}年{month}月",
        "annual":            "年間（{year}年）",

        # KPIカード
        "kpi_revenue":   "今月収入",
        "kpi_expenses":  "今月支出",
        "kpi_profit":    "今月損益",
        "kpi_prev":      "前月比",
        "kpi_ann_rev":   "年間収入",
        "kpi_ann_exp":   "年間支出",
        "kpi_ann_prf":   "年間損益",
        "kpi_tokutei":   "今月支払い",
        "kpi_job":       "今月支払い",

        # チャート
        "chart_monthly":   "{year}年 月次推移",
        "chart_cat":       "今月 支出内訳",
        "chart_ranking":   "今月 収入ランキング",
        "chart_budget":    "予算 vs 実績",
        "chart_recurring": "定期支出",
        "chart_budget_set":"設定",

        # ボタン
        "btn_add_expense":  "＋ 経費を追加",
        "btn_add_revenue":  "＋ 収入を追加",
        "btn_financial":    "📊 決算書",
        "btn_csv":          "⬇ CSV",
        "btn_receipt_ocr":  "レシートで自動記帳",
        "btn_receipt_sub":  "写真をアップロードするだけ — Gemini AI が金額・日付・カテゴリを自動入力",
        "btn_settle":       "✓ 精算済み",
        "btn_edit":         "編集",
        "btn_year_label":   "表示年度：",

        # タブ
        "tab_tatekae":    "立替え",
        "tab_recent":     "直近10件",
        "tab_month_exp":  "今月の支出",
        "tab_see_more":   "▼ もっと見る（{n}件）",
        "tab_no_tatekae": "立替え中の経費はありません",
        "tab_no_recent":  "データがありません",
        "tab_total":      "合計",
        "tab_tatekae_total": "未精算合計",
        "tab_no_revenue": "今月の収入データなし",
        "budget_not_set": "予算未設定 —",
        "budget_set_link": "設定する",
        "chart_rev_label": "収入",
        "chart_exp_label": "支出",
        "chart_prf_label": "損益",

        # 月ナビ
        "month_prev": "◀ 前月",
        "month_next": "翌月 ▶",
        "month_today": "今月",

        # テーブルヘッダ
        "th_date":     "日付",
        "th_name":     "名目",
        "th_category": "カテゴリ",
        "th_payee":    "支払先",
        "th_method":   "方法",
        "th_amount":   "金額",
        "th_action":   "",
        "months": MONTHS_JA,

        # 管理セクション
        "nav_tasks":       "タスク",
        "nav_contacts":    "取引先",
        "nav_info":        "重要情報",
        "nav_jobs":        "案件利益",
        "nav_mgmt":        "プロジェクト管理",
        "nav_accounting":  "経理",

        "task_title":      "タスク管理",
        "task_add":        "タスク追加",
        "task_todo":       "未完了",
        "task_done":       "完了",
        "task_archived":   "アーカイブ",
        "task_priority":   "優先度",
        "task_due":        "期限",

        "contact_title":   "取引先・顧客名簿",
        "contact_vendor":  "注文先(Vendor)",
        "contact_customer":"得意先(Customer)",
        "contact_add":     "連絡先追加",

        "job_title":       "案件別利益管理",
        "job_add":         "案件追加",
        "job_active":      "進行中",
        "job_closed":      "完了済み",
        "job_profit":      "粗利",
        "job_cost":        "仕入合計",
        "job_sales":       "販売合計",

        "info_title":      "プロジェクト重要情報",
        "info_bank":       "銀行口座・振込情報",
        "info_facility":   "施設・公共料金情報",
        "info_emergency":  "緊急連絡先",
        "info_updated":    "最終更新",
    },

    "id": {
        # ナビ
        "nav_dashboard":   "Dasbor",
        "nav_expenses":    "Pengeluaran",
        "nav_revenue":     "Pendapatan",
        "nav_categories":  "Kategori",
        "nav_receipt":     "📷 Kuitansi",
        "nav_budget":      "Anggaran",
        "nav_financial":   "Lap. Keuangan",
        "nav_logout":      "Keluar",
        "nav_search_ph":   "Cari...",
        "nav_search_btn":  "Cari",

        # ダッシュボード見出し
        "dash_title":      "Dasbor",
        "this_month":      "{month_name} {year}",
        "annual":          "Tahunan ({year})",

        # KPIカード
        "kpi_revenue":   "Pendapatan Bulan Ini",
        "kpi_expenses":  "Pengeluaran Bulan Ini",
        "kpi_profit":    "Laba Bulan Ini",
        "kpi_prev":      "vs. bulan lalu",
        "kpi_ann_rev":   "Pendapatan Tahunan",
        "kpi_ann_exp":   "Pengeluaran Tahunan",
        "kpi_ann_prf":   "Laba Tahunan",
        "kpi_tokutei":   "Bayar bulan ini",
        "kpi_job":       "Bayar bulan ini",

        # チャート
        "chart_monthly":   "Tren Bulanan {year}",
        "chart_cat":       "Rincian Pengeluaran Bulan Ini",
        "chart_ranking":   "Peringkat Pendapatan Bulan Ini",
        "chart_budget":    "Anggaran vs Realisasi",
        "chart_recurring": "Pengeluaran Rutin",
        "chart_budget_set":"Atur",

        # ボタン
        "btn_add_expense":  "＋ Tambah Pengeluaran",
        "btn_add_revenue":  "＋ Tambah Pendapatan",
        "btn_financial":    "📊 Lap. Keuangan",
        "btn_csv":          "⬇ CSV",
        "btn_receipt_ocr":  "Catat Otomatis dari Kuitansi",
        "btn_receipt_sub":  "Unggah foto saja — Gemini AI akan mengisi jumlah, tanggal & kategori",
        "btn_settle":       "✓ Lunas",
        "btn_edit":         "Edit",
        "btn_year_label":   "Tahun:",

        # タブ
        "tab_tatekae":    "Talangan",
        "tab_recent":     "10 Terakhir",
        "tab_month_exp":  "Pengeluaran Bulan Ini",
        "tab_see_more":   "▼ Lihat lebih ({n} item)",
        "tab_no_tatekae": "Tidak ada pengeluaran talangan",
        "tab_no_recent":  "Tidak ada data",
        "tab_total":      "Total",
        "tab_tatekae_total": "Total belum dilunasi",
        "tab_no_revenue": "Tidak ada data pendapatan bulan ini",
        "budget_not_set": "Anggaran belum diatur —",
        "budget_set_link": "Atur sekarang",
        "chart_rev_label": "Pendapatan",
        "chart_exp_label": "Pengeluaran",
        "chart_prf_label": "Laba",

        # 月ナビ
        "month_prev": "◀ Bulan Lalu",
        "month_next": "Bulan Depan ▶",
        "month_today": "Bulan Ini",

        # テーブルヘッダ
        "th_date":     "Tanggal",
        "th_name":     "Keterangan",
        "th_category": "Kategori",
        "th_payee":    "Dibayar ke",
        "th_method":   "Metode",
        "th_amount":   "Jumlah",
        "th_action":   "",

        "months": MONTHS_ID,

        # Manajemen
        "nav_tasks":       "Tugas",
        "nav_contacts":    "Kontak",
        "nav_info":        "Info Penting",
        "nav_jobs":        "Laba Proyek",
        "nav_mgmt":        "Manajemen Proyek",
        "nav_accounting":  "Akuntansi",

        "task_title":      "Manajemen Tugas",
        "task_add":        "Tambah Tugas",
        "task_todo":       "Belum Selesai",
        "task_done":       "Selesai",
        "task_archived":   "Arsip",
        "task_priority":   "Prioritas",
        "task_due":        "Tenggat",

        "contact_title":   "Buku Kontak/Pelanggan",
        "contact_vendor":  "Pemasok(Vendor)",
        "contact_customer":"Pelanggan(Customer)",
        "contact_add":     "Tambah Kontak",

        "job_title":       "Manajemen Laba per Proyek",
        "job_add":         "Tambah Proyek/Job",
        "job_active":      "Aktif",
        "job_closed":      "Selesai",
        "job_profit":      "Margin Laba",
        "job_cost":        "Total Modal",
        "job_sales":       "Total Penjualan",

        "info_title":      "Informasi Penting Proyek",
        "info_bank":       "Info Bank & Transfer",
        "info_facility":   "Info Fasilitas & Utilitas",
        "info_emergency":  "Kontak Darurat",
        "info_updated":    "Pembaruan Terakhir",
    },
}


def get_T(lang: str) -> dict:
    """言語コードに対応する翻訳辞書を返す。未対応言語は日本語にフォールバック。"""
    return TRANSLATIONS.get(lang, TRANSLATIONS["ja"])
