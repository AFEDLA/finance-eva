"""
budget_core.py
Conversational handler untuk modul Budget & Expense EVA
Integrasi ke core.py via BudgetHandler class
"""

import re
from datetime import datetime
from typing import Optional

# Import dari storage.manager (single source of truth)
try:
    from storage.manager import (
        get_ops_categories, add_ops_category, find_ops_category,
        create_budget_project, create_budget_operational,
        override_monthly_budget, update_budget, close_budget, delete_budget,
        get_budget_by_id, find_budget_by_name, list_budgets,
        create_expense_link, delete_expense_link,
        get_links_by_budget, get_links_by_doc,
        compute_budget_summary, get_all_budget_summaries,
        detect_near_limit_budgets, get_ops_summary_by_month,
    )
except ImportError as _e:
    raise ImportError(f"budget_core: gagal import dari storage.manager — {_e}")

# ── Fetch amount dari dokumen di storage ─────────────────────
def _fetch_doc_amount(doc_id: str) -> Optional[float]:
    """
    Ambil total amount dari dokumen yang sudah ada di storage.
    Support: PR, PO, QT, RMB, CAS, INV
    Return None kalau tidak ditemukan.
    """
    try:
        from storage.manager import (
            get_pr_by_id, get_po_by_id, get_qt_by_id,
            get_finance, get_inv_by_id,
        )
        prefix = doc_id.split("-")[0].upper()

        if prefix == "PR":
            doc = get_pr_by_id(doc_id)
            if doc:
                items = doc.get("items", [])
                total = sum(int(x.get("jumlah", 0)) for x in items)
                return float(total) if total else float(doc.get("total", 0))

        elif prefix == "PO":
            doc = get_po_by_id(doc_id)
            if doc:
                items = doc.get("items", [])
                total = sum(int(x.get("jumlah", 0)) for x in items)
                return float(total) if total else float(doc.get("total", 0))

        elif prefix == "QT":
            doc = get_qt_by_id(doc_id)
            if doc:
                return float(doc.get("total", 0))

        elif prefix in ("RMB", "CAS"):
            all_fin = get_finance()
            doc = next((x for x in all_fin if x.get("id", "").upper() == doc_id.upper()), None)
            if doc:
                return float(doc.get("jumlah", 0))

        elif prefix == "INV":
            doc = get_inv_by_id(doc_id)
            if doc:
                items = doc.get("items", [])
                total = sum(int(x.get("total", x.get("jumlah", 0))) for x in items)
                return float(total) if total else float(doc.get("total", 0))

    except Exception:
        pass
    return None

# ── Format currency ──────────────────────────────────────────
def _fmt(amount: float) -> str:
    """Format angka jadi Rp x.xxx.xxx"""
    return f"Rp {amount:,.0f}".replace(",", ".")

def _pct_bar(pct: float, width: int = 20) -> str:
    """Buat progress bar ASCII."""
    filled = int(width * min(pct, 100) / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.1f}%"

def _alert_emoji(alert: Optional[str]) -> str:
    if alert == "OVER_BUDGET": return "🔴"
    if alert == "NEAR_LIMIT":  return "🟡"
    return "🟢"

def _month_name(month: int) -> str:
    names = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
             "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
    return names[month] if 1 <= month <= 12 else str(month)

# ── Parse amount (Rp 500jt, 1.2M, 500000000) ─────────────────
def _parse_amount(text: str) -> Optional[float]:
    text = text.lower().replace("rp", "").replace(" ", "").replace(",", ".")
    multipliers = {
        "miliar": 1_000_000_000, "milyar": 1_000_000_000,
        "m":      1_000_000_000,   # M = miliar (bukan mega)
        "jt":     1_000_000, "juta": 1_000_000,
        "rb":     1_000, "ribu": 1_000, "k": 1_000,
    }
    for suffix, mult in multipliers.items():
        if text.endswith(suffix):
            try:
                return float(text[:-len(suffix)]) * mult
            except ValueError:
                pass
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return None

# ── Parse year & month ────────────────────────────────────────
def _parse_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d{2})\b", text)
    return int(m.group(1)) if m else None

def _parse_month(text: str) -> Optional[int]:
    months = {
        "januari": 1, "jan": 1, "februari": 2, "feb": 2,
        "maret": 3, "mar": 3, "april": 4, "apr": 4,
        "mei": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7,
        "agustus": 8, "agu": 8, "agst": 8, "september": 9, "sep": 9,
        "oktober": 10, "okt": 10, "november": 11, "nov": 11,
        "desember": 12, "des": 12,
    }
    text_lower = text.lower()
    for name, num in months.items():
        if name in text_lower:
            return num
    m = re.search(r"\bbulan\s+(\d{1,2})\b", text_lower)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 12:
            return val
    return None

# ── Parse date range (Jan–Jun 2025 / 2025-01-01) ─────────────
def _parse_date(text: str) -> Optional[str]:
    """Extract YYYY-MM-DD dari teks."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "mei": "05", "jun": "06", "jul": "07", "agu": "08", "agst": "08",
        "sep": "09", "okt": "10", "nov": "11", "des": "12",
    }
    for abbr, num in month_map.items():
        pattern = rf"\b{abbr}[a-z]*\b.*?\b(20\d{{2}})\b"
        m = re.search(pattern, text.lower())
        if m:
            return f"{m.group(1)}-{num}-01"
    return None

# ══════════════════════════════════════════════════════════════
# BUDGET HANDLER CLASS
# ══════════════════════════════════════════════════════════════

class BudgetHandler:
    """
    Multi-step conversational handler untuk Budget & Expense.
    Dipanggil dari core.py saat intent budget terdeteksi.
    """

    def __init__(self, agent=None):
        # agent parameter diterima tapi tidak dipakai — untuk kompatibilitas
        self.sessions = {}   # session_id → collect state

    # ── Session helpers ───────────────────────────────────────

    def _get_session(self, session_id: str) -> dict:
        return self.sessions.get(session_id, {})

    def _set_session(self, session_id: str, data: dict):
        self.sessions[session_id] = data

    def _clear_session(self, session_id: str):
        self.sessions.pop(session_id, None)

    def has_active_session(self, session_id: str) -> bool:
        return session_id in self.sessions

    # ── Main entry point ──────────────────────────────────────

    def handle(self, intent: str, message: str, session_id: str) -> str:
        """Route intent ke handler yang sesuai."""

        # Jika ada sesi aktif, lanjutkan collect flow
        if self.has_active_session(session_id):
            return self._continue_collect(message, session_id)

        # Route berdasarkan intent
        routes = {
            "add_budget_project":     self._start_add_project,
            "add_budget_ops":         self._start_add_ops,
            "override_budget_month":  self._handle_override,
            "edit_budget":            self._handle_edit,
            "close_budget":           self._handle_close,
            "delete_budget":          self._handle_delete,
            "link_expense":           self._start_link_expense,
            "unlink_expense":         self._handle_unlink,
            "check_budget":           self._handle_check,
            "list_budgets":           self._handle_list,
            "check_ops_monthly":      self._handle_ops_monthly,
            "budget_alert":           self._handle_alert,
            "list_ops_categories":    self._handle_list_cats,
            "add_ops_category":       self._handle_add_cat,
        }

        handler = routes.get(intent)
        if handler:
            return handler(message, session_id)
        return self._handle_check(message, session_id)

    # ══════════════════════════════════════════════════════════
    # FLOW: Buat Budget Proyek
    # ══════════════════════════════════════════════════════════

    def _start_add_project(self, message: str, session_id: str) -> str:
        """Mulai collect data budget proyek."""
        amount = _parse_amount(message)
        name   = self._extract_project_name(message)

        # Jika semua data lengkap, langsung konfirmasi
        if name and amount:
            return self._confirm_create_project(name, amount, session_id)

        # Simpan apa yang sudah ada, tanya sisanya
        self._set_session(session_id, {
            "flow":   "add_budget_project",
            "step":   "name" if not name else "amount",
            "name":   name,
            "amount": amount,
        })

        if not name:
            return (
                "📋 Buat budget proyek baru.\n\n"
                "Nama proyeknya apa? (contoh: Migrasi Cloud, Website Revamp, Padel VR Simulator)"
            )
        if not amount:
            return f"💰 Total budget untuk proyek **{name}**? (contoh: Rp500jt, 1.2M, 3M)"

    def _confirm_create_project(self, name, amount, session_id) -> str:
        """Konfirmasi sebelum simpan."""
        self._set_session(session_id, {
            "flow":   "add_budget_project",
            "step":   "confirm",
            "name":   name,
            "amount": amount,
        })
        return (
            f"📋 Konfirmasi budget proyek baru:\n\n"
            f"• **Nama Proyek:** {name}\n"
            f"• **Total Budget:** {_fmt(amount)}\n"
            f"• **Periode:** Tidak ada batas — tutup manual saat proyek selesai\n\n"
            f"Simpan? (ya/tidak)"
        )

    # ══════════════════════════════════════════════════════════
    # FLOW: Buat Budget Operasional
    # ══════════════════════════════════════════════════════════

    def _start_add_ops(self, message: str, session_id: str) -> str:
        """Mulai collect data budget operasional tahunan."""
        cats = get_ops_categories()
        cat_list = ", ".join(c["code"] for c in cats)

        amount = _parse_amount(message)
        year   = _parse_year(message) or datetime.now().year

        # Cari kategori di pesan
        cat = self._extract_ops_category(message)

        if cat and amount:
            return self._confirm_create_ops(cat, amount, year, session_id)

        self._set_session(session_id, {
            "flow":   "add_budget_ops",
            "step":   "category" if not cat else "amount",
            "cat":    cat,
            "amount": amount,
            "year":   year,
        })

        if not cat:
            return (
                f"📊 Buat budget operasional tahunan.\n\n"
                f"Kategori yang tersedia:\n"
                + "\n".join(f"• **{c['code']}** — {c['name']}" for c in cats)
                + f"\n\nKategori mana yang ingin diset?"
            )
        if not amount:
            return (
                f"📊 Budget operasional **{cat['name']}** tahun **{year}**.\n\n"
                f"Total budget setahun berapa? (akan dibagi otomatis per bulan)"
            )

    def _confirm_create_ops(self, cat, amount, year, session_id) -> str:
        monthly = round(amount / 12, 0)
        self._set_session(session_id, {
            "flow":   "add_budget_ops",
            "step":   "confirm",
            "cat":    cat,
            "amount": amount,
            "year":   year,
        })
        return (
            f"📊 Konfirmasi budget operasional:\n\n"
            f"• **Kategori:** {cat['name']}\n"
            f"• **Tahun:** {year}\n"
            f"• **Total Tahunan:** {_fmt(amount)}\n"
            f"• **Per Bulan (rata):** {_fmt(monthly)}\n\n"
            f"Simpan? (ya/tidak)"
        )

    # ══════════════════════════════════════════════════════════
    # FLOW: Link Expense ke Budget
    # ══════════════════════════════════════════════════════════

    def _process_multi_link(self, doc_ids: list, budget: dict, session_id: str) -> str:
        """
        Proses link multiple dokumen ke satu budget sekaligus.
        Kalau hanya satu doc → flow konfirmasi normal.
        Kalau banyak → konfirmasi batch.
        """
        if len(doc_ids) == 1:
            return self._resolve_and_confirm_link(doc_ids[0], budget, session_id)

        # Fetch amount semua dokumen
        items = []
        total = 0.0
        for doc_id in doc_ids:
            amount = _fetch_doc_amount(doc_id)
            exp_type = self._doc_to_expense_type(doc_id)
            items.append({
                "doc_id":       doc_id,
                "amount":       amount or 0,
                "expense_type": exp_type,
                "found":        amount is not None and amount > 0,
            })
            total += amount or 0

        # Simpan ke session untuk konfirmasi batch
        self._set_session(session_id, {
            "flow":   "link_expense",
            "step":   "confirm_multi",
            "budget": budget,
            "items":  items,
        })

        # Render konfirmasi batch
        lines = [f"🔗 Konfirmasi link **{len(doc_ids)} dokumen** ke **{budget['name']}**:\n"]
        for it in items:
            amt_str = _fmt(it["amount"]) if it["found"] else "⚠ tidak ditemukan di storage"
            tipe    = "Committed" if it["expense_type"] == "committed" else "Actual"
            lines.append(f"• **{it['doc_id']}** — {amt_str} ({tipe})")

        lines.append(f"\n**Total: {_fmt(total)}**")
        lines.append("\nSimpan semua? (ya/tidak)")
        return "\n".join(lines)

    def _resolve_and_confirm_link(self, doc_id: str, budget: dict, session_id: str) -> str:
        """
        Auto-fetch amount dari dokumen, langsung ke konfirmasi.
        Kalau amount tidak ditemukan di storage, baru tanya user.
        """
        expense_type = self._doc_to_expense_type(doc_id)
        amount = _fetch_doc_amount(doc_id)

        if amount and amount > 0:
            # Amount ditemukan di storage → langsung konfirmasi
            return self._confirm_link(doc_id, budget, amount, expense_type, session_id)
        else:
            # Amount tidak ditemukan → tanya user
            self._set_session(session_id, {
                "flow":         "link_expense",
                "step":         "amount",
                "doc_id":       doc_id,
                "budget":       budget,
                "expense_type": expense_type,
            })
            return (
                f"🔗 Link **{doc_id}** → **{budget['name']}**.\n\n"
                f"Dokumen tidak ditemukan di storage atau amount kosong.\n"
                f"Masukkan amount manual: (contoh: Rp25jt)"
            )

    def _start_link_expense(self, message: str, session_id: str) -> str:
        """Link dokumen ke budget — support multiple doc IDs sekaligus."""
        doc_ids = self._extract_doc_ids(message)
        budget  = self._extract_budget_from_message(message)

        # Resolve budget jika ambiguous
        if isinstance(budget, list):
            budget = budget[0] if len(budget) == 1 else None

        # Tidak ada doc_id → tanya
        if not doc_ids:
            self._set_session(session_id, {
                "flow":   "link_expense",
                "step":   "doc_id",
                "budget": budget,
            })
            return "🔗 Link dokumen ke budget.\n\nID dokumen yang ingin di-link? (contoh: PO-0042, RMB-0015)\nBisa sekaligus beberapa: CAS-0001, CAS-0003"

        # Tidak ada budget → tanya
        if not budget:
            self._set_session(session_id, {
                "flow":    "link_expense",
                "step":    "budget",
                "doc_ids": doc_ids,
            })
            docs_str = ", ".join(f"**{d}**" for d in doc_ids)
            return f"🔗 Link {docs_str} ke budget mana?"

        # Keduanya ada → proses semua doc_ids
        return self._process_multi_link(doc_ids, budget, session_id)

    def _confirm_link(self, doc_id, budget, amount, expense_type, session_id) -> str:
        self._set_session(session_id, {
            "flow":         "link_expense",
            "step":         "confirm",
            "doc_id":       doc_id,
            "budget":       budget,
            "amount":       amount,
            "expense_type": expense_type,
        })
        type_label = "Committed (belum keluar)" if expense_type == "committed" else "Actual (sudah keluar)"
        # Cek apakah amount dari storage atau manual
        storage_amount = _fetch_doc_amount(doc_id)
        amount_note = " _(dari dokumen)_" if storage_amount and abs(storage_amount - amount) < 1 else ""
        return (
            f"🔗 Konfirmasi link expense:\n\n"
            f"• **Dokumen:** {doc_id}\n"
            f"• **Budget:** {budget['name']}\n"
            f"• **Amount:** {_fmt(amount)}{amount_note}\n"
            f"• **Tipe:** {type_label}\n\n"
            f"Simpan? (ya/tidak)"
        )

    # ══════════════════════════════════════════════════════════
    # CONTINUE COLLECT (session router)
    # ══════════════════════════════════════════════════════════

    def _continue_collect(self, message: str, session_id: str) -> str:
        sess  = self._get_session(session_id)
        flow  = sess.get("flow")
        step  = sess.get("step")
        msg_l = message.lower().strip()

        # Cancel
        if msg_l in ("batal", "cancel", "tidak", "stop"):
            self._clear_session(session_id)
            return "❌ Dibatalkan."

        # ── delete_budget ──
        if flow == "delete_budget":
            if step == "confirm":
                if msg_l in ("ya", "yes", "y", "ok", "oke", "hapus"):
                    result = delete_budget(sess["budget_id"])
                    self._clear_session(session_id)
                    if "error" in result:
                        return f"❌ {result['error']}"
                    return (
                        f"🗑️ Budget **{sess['name']}** ({sess['budget_id']}) "
                        f"berhasil dihapus permanen."
                    )
                self._clear_session(session_id)
                return "❌ Dibatalkan. Budget tidak dihapus."
        if flow == "add_budget_project":
            if step == "name":
                sess["name"] = message.strip()
                sess["step"] = "amount"
                self._set_session(session_id, sess)
                return f"💰 Total budget untuk proyek **{sess['name']}**? (contoh: Rp500jt)"

            if step == "amount":
                amount = _parse_amount(message)
                if not amount:
                    return "❓ Format tidak dikenali. Coba: Rp500jt, 1.2M, atau 500000000"
                sess["amount"] = amount
                return self._confirm_create_project(sess["name"], sess["amount"], session_id)

            if step == "confirm":
                if msg_l in ("ya", "yes", "y", "ok", "oke", "simpan"):
                    now   = datetime.now()
                    start = now.strftime("%Y-%m-%d")
                    result = create_budget_project(
                        name=sess["name"],
                        total_budget=sess["amount"],
                        period_start=start,
                        period_end=None,
                    )
                    self._clear_session(session_id)
                    if "error" in result:
                        return f"❌ {result['error']}"
                    return (
                        f"✅ Budget proyek berhasil dibuat!\n\n"
                        f"• **ID:** {result['budget_id']}\n"
                        f"• **Proyek:** {result['name']}\n"
                        f"• **Total Budget:** {_fmt(result['total_budget'])}\n"
                        f"• **Mulai:** {result['period_start']}\n"
                        f"• **Selesai:** Tidak ada batas — tutup manual saat proyek selesai\n\n"
                        f"Mulai link dokumen ke budget ini dengan:\n"
                        f"`link [ID dokumen] ke {result['name']}`"
                    )
                self._clear_session(session_id)
                return "❌ Dibatalkan."

        # ── add_budget_ops ──
        if flow == "add_budget_ops":
            if step == "category":
                cat = find_ops_category(message)
                if not cat:
                    cats = get_ops_categories()
                    return (
                        f"❓ Kategori tidak ditemukan. Pilihan:\n"
                        + "\n".join(f"• **{c['code']}** — {c['name']}" for c in cats)
                    )
                sess["cat"]  = cat
                sess["step"] = "amount"
                self._set_session(session_id, sess)
                return f"💰 Total budget **{cat['name']}** tahun **{sess['year']}** berapa?"

            if step == "amount":
                amount = _parse_amount(message)
                if not amount:
                    return "❓ Format tidak dikenali. Coba: Rp60jt, 60000000"
                sess["amount"] = amount
                return self._confirm_create_ops(sess["cat"], amount, sess["year"], session_id)

            if step == "confirm":
                if msg_l in ("ya", "yes", "y", "ok", "oke", "simpan"):
                    result = create_budget_operational(
                        ops_category_code=sess["cat"]["code"],
                        yearly_total=sess["amount"],
                        year=sess["year"],
                    )
                    self._clear_session(session_id)
                    if "error" in result:
                        return f"❌ {result['error']}"
                    monthly = round(sess["amount"] / 12, 0)
                    return (
                        f"✅ Budget operasional berhasil dibuat!\n\n"
                        f"• **ID:** {result['budget_id']}\n"
                        f"• **Kategori:** {result['name']}\n"
                        f"• **Total Tahunan:** {_fmt(result['yearly_total'])}\n"
                        f"• **Per Bulan (rata):** {_fmt(monthly)}\n\n"
                        f"💡 Untuk override bulan tertentu:\n"
                        f"`override budget {result['budget_id']} Desember jadi Rp8jt`"
                    )
                self._clear_session(session_id)
                return "❌ Dibatalkan."

        # ── link_expense ──
        if flow == "link_expense":
            if step == "doc_id":
                doc_ids = self._extract_doc_ids(message)
                if not doc_ids:
                    doc_ids = [message.strip().upper()]
                existing_budget = sess.get("budget")
                if existing_budget and isinstance(existing_budget, dict):
                    self._set_session(session_id, sess)
                    return self._process_multi_link(doc_ids, existing_budget, session_id)
                else:
                    sess["doc_ids"] = doc_ids
                    sess["step"]    = "budget"
                    self._set_session(session_id, sess)
                    docs_str = ", ".join(f"**{d}**" for d in doc_ids)
                    return f"🔗 {docs_str} akan di-link ke budget mana?"

            if step == "budget":
                budget = self._extract_budget_from_message(message)
                if not budget:
                    return "❓ Budget tidak ditemukan. Coba ketik nama proyek atau ID budget (BUD-xxxx)."
                if isinstance(budget, list) and len(budget) > 1:
                    sess["step"]    = "resolve_budget"
                    sess["options"] = budget
                    self._set_session(session_id, sess)
                    opts = "\n".join(f"{i+1}. {b['name']} ({b['budget_id']})" for i, b in enumerate(budget))
                    return f"🔗 Ditemukan beberapa budget:\n\n{opts}\n\nPilih nomor:"
                b = budget if isinstance(budget, dict) else budget[0]
                sess["budget"] = b
                self._set_session(session_id, sess)
                doc_ids = sess.get("doc_ids") or ([sess["doc_id"]] if sess.get("doc_id") else [])
                return self._process_multi_link(doc_ids, b, session_id)

            if step == "resolve_budget":
                try:
                    idx = int(message.strip()) - 1
                    b   = sess["options"][idx]
                    sess["budget"] = b
                    self._set_session(session_id, sess)
                    doc_ids = sess.get("doc_ids") or ([sess["doc_id"]] if sess.get("doc_id") else [])
                    return self._process_multi_link(doc_ids, b, session_id)
                except (ValueError, IndexError):
                    return "❓ Pilih nomor yang valid."

            if step == "confirm_multi":
                if msg_l in ("ya", "yes", "y", "ok", "oke", "simpan"):
                    items  = sess.get("items", [])
                    budget = sess["budget"]
                    success, failed = [], []
                    for it in items:
                        if not it["found"] or it["amount"] == 0:
                            failed.append(f"{it['doc_id']} (amount tidak ditemukan)")
                            continue
                        result = create_expense_link(
                            budget_id=budget["budget_id"],
                            doc_type=it["doc_id"].split("-")[0],
                            doc_id=it["doc_id"],
                            amount=it["amount"],
                            expense_type=it["expense_type"],
                        )
                        if "error" in result:
                            failed.append(f"{it['doc_id']} ({result['error']})")
                        else:
                            success.append(it["doc_id"])
                    self._clear_session(session_id)
                    lines = []
                    if success:
                        lines.append(f"✅ **{len(success)} dokumen berhasil di-link ke {budget['name']}:**")
                        for d in success:
                            lines.append(f"• {d}")
                    if failed:
                        lines.append(f"\n⚠ **{len(failed)} gagal:**")
                        for f in failed:
                            lines.append(f"• {f}")
                    # Update summary
                    if success:
                        summary = compute_budget_summary(budget["budget_id"])
                        if "error" not in summary:
                            lines.append(
                                f"\n📊 **Update {summary['budget_name']}:**\n"
                                f"{_pct_bar(summary['pct_used'])}\n"
                                f"Terpakai: {_fmt(summary['total_used'])} / {_fmt(summary['total_budget'])}\n"
                                f"Sisa: {_fmt(summary['remaining'])}"
                            )
                            if summary["alert"]:
                                lines.append(f"\n{_alert_emoji(summary['alert'])} Budget sudah {summary['pct_used']:.1f}%!")
                    return "\n".join(lines)
                self._clear_session(session_id)
                return "❌ Dibatalkan."

            if step == "amount":
                amount = _parse_amount(message)
                if not amount:
                    return "❓ Format tidak dikenali. Coba: Rp25jt atau 25000000"
                sess["amount"] = amount
                return self._confirm_link(
                    sess["doc_id"], sess["budget"], amount, sess["expense_type"], session_id
                )

            if step == "confirm":
                if msg_l in ("ya", "yes", "y", "ok", "oke", "simpan"):
                    result = create_expense_link(
                        budget_id=sess["budget"]["budget_id"],
                        doc_type=sess["doc_id"].split("-")[0],
                        doc_id=sess["doc_id"],
                        amount=sess["amount"],
                        expense_type=sess["expense_type"],
                    )
                    self._clear_session(session_id)
                    if "error" in result:
                        return f"❌ {result['error']}"

                    # Show updated summary
                    summary = compute_budget_summary(result["budget_id"])
                    return (
                        f"✅ Link berhasil!\n\n"
                        f"• **{result['doc_id']}** → **{result['budget_name']}**\n"
                        f"• **Amount:** {_fmt(result['amount'])}\n"
                        f"• **Tipe:** {'Committed' if result['expense_type'] == 'committed' else 'Actual'}\n\n"
                        f"📊 **Update budget {summary['budget_name']}:**\n"
                        f"{_pct_bar(summary['pct_used'])}\n"
                        f"Terpakai: {_fmt(summary['total_used'])} / {_fmt(summary['total_budget'])}\n"
                        f"Sisa: {_fmt(summary['remaining'])}"
                        + (f"\n\n{_alert_emoji(summary['alert'])} **Peringatan: budget sudah {summary['pct_used']:.1f}%!**" if summary["alert"] else "")
                    )
                self._clear_session(session_id)
                return "❌ Dibatalkan."

        self._clear_session(session_id)
        return "❓ Sesi tidak dikenali. Silakan mulai ulang."

    # ══════════════════════════════════════════════════════════
    # HANDLERS (non-collect)
    # ══════════════════════════════════════════════════════════

    def _handle_check(self, message: str, session_id: str) -> str:
        """Cek sisa budget — by name atau ID."""
        # By budget_id
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        if bid_match:
            b = get_budget_by_id(bid_match.group(0))
            if b and b.get("status") == "closed":
                return f"ℹ️ Budget **{b['name']}** ({bid_match.group(0)}) sudah ditutup."
            return self._render_summary(bid_match.group(0), message)

        # By name — hanya active
        name_query = self._extract_budget_name_query(message)
        if name_query:
            results = find_budget_by_name(name_query, status="active")
            if not results:
                return f"❓ Budget aktif dengan nama '{name_query}' tidak ditemukan."
            if len(results) > 1:
                opts = "\n".join(f"• {b['name']} ({b['budget_id']})" for b in results)
                return f"🔍 Ditemukan beberapa budget:\n\n{opts}\n\nSebutkan ID atau nama lebih spesifik."
            return self._render_summary(results[0]["budget_id"], message)

        return "❓ Sebutkan nama proyek atau ID budget yang ingin dicek."

    def _render_summary(self, budget_id: str, message: str) -> str:
        """Render summary satu budget."""
        month = _parse_month(message)
        summary = compute_budget_summary(budget_id, month=month)
        if "error" in summary:
            return f"❌ {summary['error']}"

        s = summary
        lines = [
            f"📊 **{s['budget_name']}** ({s['budget_id']})",
            f"Periode: {s['period_label']}",
            f"",
            f"{_pct_bar(s['pct_used'])}",
            f"",
        ]

        # Tampilkan info tahunan vs bulanan untuk operasional
        if s["type"] == "operational" and s.get("yearly_total"):
            monthly_avg = round(s["yearly_total"] / 12, 0)
            lines += [
                f"• **Total Tahunan:** {_fmt(s['yearly_total'])}",
                f"• **Budget per Bulan (rata):** {_fmt(monthly_avg)}",
                f"• **Committed (PR/PO):** {_fmt(s['committed'])}",
                f"• **Actual (RMB/CAS/INV):** {_fmt(s['actual'])}",
                f"• **Total Terpakai:** {_fmt(s['total_used'])}",
                f"• **Sisa Tahunan:** {_fmt(s['remaining'])}",
            ]
        else:
            lines += [
                f"• **Total Budget:** {_fmt(s['total_budget'])}",
                f"• **Committed (PR/PO):** {_fmt(s['committed'])}",
                f"• **Actual (RMB/CAS/INV):** {_fmt(s['actual'])}",
                f"• **Total Terpakai:** {_fmt(s['total_used'])}",
                f"• **Sisa Budget:** {_fmt(s['remaining'])}",
            ]

        if s["alert"] == "OVER_BUDGET":
            lines.append(f"\n🔴 **OVER BUDGET! Melebihi {_fmt(abs(s['remaining']))}**")
        elif s["alert"] == "NEAR_LIMIT":
            lines.append(f"\n🟡 **Peringatan: Budget sudah {s['pct_used']:.1f}% terpakai**")

        if s["links"]:
            lines.append(f"\n**Dokumen yang di-link ({s['links_count']}):**")
            for lnk in s["links"][-5:]:
                tipe = "Committed" if lnk["expense_type"] == "committed" else "Actual"
                lines.append(f"• {lnk['doc_id']} — {_fmt(lnk['amount'])} ({tipe})")
            if s["links_count"] > 5:
                lines.append(f"  _...dan {s['links_count']-5} dokumen lainnya_")

        return "\n".join(lines)

    def _handle_list(self, message: str, session_id: str) -> str:
        """List budget. Support: aktif saja, closed saja, semua, atau filter by nama."""
        msg_l = message.lower()

        # Deteksi mode
        show_closed = bool(re.search(r'\b(closed|ditutup|history|arsip|lama|sudah\s+ditutup)\b', msg_l))
        show_all    = bool(re.search(r'\b(semua|all)\b', msg_l)) and show_closed

        # Deteksi nama filter — hanya kategori ops yang dikenal atau nama proyek eksplisit
        KNOWN_CATEGORIES = ["atk", "transport", "akomodasi", "utilitas", "entertainment", "maintenance"]
        name_filter = None

        # Cek kategori ops yang dikenal
        for kw in KNOWN_CATEGORIES:
            if re.search(rf'\b{kw}\b', msg_l):
                name_filter = kw
                break

        # Cek nama proyek eksplisit — hanya jika ada kata "proyek" sebelumnya
        if not name_filter:
            m = re.search(r'\bproyek\s+([a-zA-Z0-9\s]{3,30}?)(?:\s+(?:yang|closed|ditutup|history)|$)', msg_l)
            if m:
                candidate = m.group(1).strip()
                name_filter = candidate

        def _filter(budgets):
            if not name_filter:
                return budgets
            return [b for b in budgets if name_filter.lower() in b.get("name", "").lower()]

        # Mode: history/closed spesifik (tanpa show_all)
        if show_closed and not show_all:
            budgets_closed = _filter(list_budgets(status="closed"))
            if not budgets_closed:
                q = f" '{name_filter.upper()}'" if name_filter else ""
                return f"📁 Tidak ada budget{q} yang sudah ditutup."
            label = f" — {name_filter.upper()}" if name_filter else ""
            lines = [f"📁 **Budget Ditutup{label} ({len(budgets_closed)}):**"]
            for b in budgets_closed:
                s = compute_budget_summary(b["budget_id"])
                pct  = f"{s['pct_used']:.1f}%" if "error" not in s else "—"
                used = _fmt(s['total_used']) if "error" not in s else "—"
                lines.append(
                    f"🔒 **{b['name']}** ({b['budget_id']})\n"
                    f"   Terpakai: {used} ({pct}) · {b.get('period_start','')[:7]}"
                )
            return "\n".join(lines)

        # Mode: semua (aktif + closed)
        if show_all:
            budgets_active = _filter(list_budgets(status="active"))
            budgets_closed = _filter(list_budgets(status="closed"))
            lines = []
            if budgets_active:
                lines.append(f"📋 **Budget Aktif ({len(budgets_active)}):**")
                for b in budgets_active:
                    s = compute_budget_summary(b["budget_id"])
                    if "error" not in s:
                        lines.append(f"{_alert_emoji(s['alert'])} {b['name']} ({b['budget_id']}) — sisa {_fmt(s['remaining'])}")
            if budgets_closed:
                lines.append(f"\n📁 **Budget Ditutup ({len(budgets_closed)}):**")
                for b in budgets_closed:
                    s = compute_budget_summary(b["budget_id"])
                    pct = f"{s['pct_used']:.1f}%" if "error" not in s else "—"
                    lines.append(f"🔒 {b['name']} ({b['budget_id']}) — terpakai {pct}")
            if not lines:
                return "📋 Belum ada budget sama sekali."
            return "\n".join(lines)

        # Mode: default — hanya aktif
        summaries = get_all_budget_summaries(status="active")
        filtered  = [s for s in summaries if not name_filter or name_filter.lower() in s['budget_name'].lower()]
        if not filtered:
            q = f" '{name_filter.upper()}'" if name_filter else ""
            return f"📋 Tidak ada budget aktif{q}."
        label = f" — {name_filter.upper()}" if name_filter else ""
        lines = [f"📋 **Budget Aktif{label} ({len(filtered)}):**\n"]
        for s in filtered:
            lines.append(
                f"{_alert_emoji(s['alert'])} **{s['budget_name']}** ({s['budget_id']})\n"
                f"   {_pct_bar(s['pct_used'], width=15)} {_fmt(s['remaining'])} tersisa"
            )
        return "\n".join(lines)

    def _handle_alert(self, message: str, session_id: str) -> str:
        """Deteksi budget yang hampir habis atau over budget."""
        near = detect_near_limit_budgets(threshold=80.0)
        if not near:
            return "✅ Semua budget dalam kondisi aman (di bawah 80%)."

        lines = [f"⚠️ **Budget yang perlu diperhatikan:**\n"]
        for s in near:
            emoji = _alert_emoji(s["alert"])
            status = "OVER BUDGET" if s["alert"] == "OVER_BUDGET" else f"{s['pct_used']:.1f}% terpakai"
            lines.append(
                f"{emoji} **{s['budget_name']}** — {status}\n"
                f"   Sisa: {_fmt(s['remaining'])} dari {_fmt(s['total_budget'])}"
            )
        return "\n".join(lines)

    def _handle_ops_monthly(self, message: str, session_id: str) -> str:
        """Cek ringkasan budget operasional per bulan."""
        month = _parse_month(message) or datetime.now().month
        year  = _parse_year(message) or datetime.now().year
        summaries = get_ops_summary_by_month(year, month)

        if not summaries:
            return f"📊 Belum ada budget operasional untuk {_month_name(month)} {year}."

        lines = [f"📊 **Budget Operasional — {_month_name(month)} {year}**\n"]
        for s in summaries:
            emoji = _alert_emoji(s["alert"])
            lines.append(
                f"{emoji} **{s['budget_name']}**\n"
                f"   {_pct_bar(s['pct_used'], width=15)}\n"
                f"   {_fmt(s['total_used'])} / {_fmt(s['total_budget'])} — sisa {_fmt(s['remaining'])}"
            )
        return "\n".join(lines)

    def _handle_override(self, message: str, session_id: str) -> str:
        """Override budget bulan tertentu."""
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        month     = _parse_month(message)
        amount    = _parse_amount(message)

        if not bid_match:
            return "❓ Sebutkan ID budget yang ingin di-override. (contoh: BUD-0002)"
        if not month:
            return "❓ Sebutkan bulan yang ingin di-override. (contoh: Desember)"
        if not amount:
            return "❓ Sebutkan jumlah baru. (contoh: Rp8jt)"

        result = override_monthly_budget(bid_match.group(0), month, amount)
        if "error" in result:
            return f"❌ {result['error']}"

        monthly = result["monthly_slots"][str(month)]["amount"]
        return (
            f"✅ Override berhasil!\n\n"
            f"• **Budget:** {result['name']}\n"
            f"• **{_month_name(month)}:** {_fmt(monthly)} (override)\n"
            f"• **Bulan lain:** disesuaikan otomatis\n"
            f"• **Total tahunan:** tetap {_fmt(result['yearly_total'])}"
        )

    def _handle_close(self, message: str, session_id: str) -> str:
        """Tutup budget — allow meski ada expense links, dengan konfirmasi."""
        session = self._get_session(session_id)

        # ── Step: konfirmasi close budget yang punya links ─────────────────────
        if session.get("flow") == "close_budget" and session.get("step") == "confirm":
            budget_id   = session["budget_id"]
            budget_name = session["budget_name"]
            links_count = session["links_count"]
            msg_l       = message.lower().strip()

            if any(w in msg_l for w in ["ya", "yes", "iya", "ok", "lanjut", "tutup", "konfirmasi", "benar"]):
                self._clear_session(session_id)
                result = close_budget(budget_id)
                if "error" in result:
                    return f"❌ {result['error']}"
                return (
                    f"✅ Budget **{budget_name}** ({budget_id}) berhasil ditutup.\n\n"
                    f"📎 {links_count} expense link tetap tersimpan untuk keperluan audit."
                )
            else:
                self._clear_session(session_id)
                return f"↩️ Penutupan budget **{budget_name}** dibatalkan."

        # ── Identifikasi budget ────────────────────────────────────────────────
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        if not bid_match:
            name_query = self._extract_budget_name_query(message)
            if name_query:
                results = find_budget_by_name(name_query)
                if len(results) == 1:
                    budget_id = results[0]["budget_id"]
                elif len(results) > 1:
                    opts = "\n".join(f"• {b['name']} ({b['budget_id']})" for b in results)
                    return f"🔍 Ditemukan beberapa budget:\n\n{opts}\n\nSebutkan ID yang ingin ditutup."
                else:
                    return "❓ Budget tidak ditemukan. Sebutkan ID atau nama yang lebih spesifik."
            else:
                return "❓ Sebutkan ID budget (BUD-xxxx) atau nama budget yang ingin ditutup."
        else:
            budget_id = bid_match.group(0)

        budget = get_budget_by_id(budget_id)
        if not budget:
            return f"❌ Budget '{budget_id}' tidak ditemukan."

        if budget.get("status") == "closed":
            return f"ℹ️ Budget **{budget['name']}** ({budget_id}) sudah ditutup sebelumnya."

        # ── Cek expense links ──────────────────────────────────────────────────
        links = get_links_by_budget(budget_id)
        if links:
            # Ada links — minta konfirmasi dulu
            self._set_session(session_id, {
                "flow":        "close_budget",
                "step":        "confirm",
                "budget_id":   budget_id,
                "budget_name": budget["name"],
                "links_count": len(links),
            })
            return (
                f"⚠️ Budget **{budget['name']}** ({budget_id}) masih memiliki "
                f"**{len(links)} expense link** yang terhubung.\n\n"
                f"Data expense link akan tetap tersimpan untuk keperluan audit. "
                f"Yakin ingin menutup budget ini? (ya/tidak)"
            )

        # ── Tidak ada links — langsung close ──────────────────────────────────
        result = close_budget(budget_id)
        if "error" in result:
            return f"❌ {result['error']}"
        return f"✅ Budget **{result['name']}** ({budget_id}) berhasil ditutup."

    def _handle_delete(self, message: str, session_id: str) -> str:
        """Hapus budget — hanya jika closed dan tidak ada expense links."""
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        if not bid_match:
            # Cari by name di closed budgets
            name_query = self._extract_budget_name_query(message)
            if name_query:
                results = find_budget_by_name(name_query, status="closed")
                if not results:
                    # Coba cari di active juga untuk kasih pesan yang tepat
                    active = find_budget_by_name(name_query, status="active")
                    if active:
                        return f"❌ Budget **{active[0]['name']}** masih aktif. Tutup dulu sebelum dihapus."
                    return f"❓ Budget '{name_query}' tidak ditemukan."
                if len(results) > 1:
                    opts = "\n".join(f"• {b['name']} ({b['budget_id']})" for b in results)
                    return f"🔍 Ditemukan beberapa budget:\n\n{opts}\n\nSebutkan ID yang ingin dihapus."
                budget_id = results[0]["budget_id"]
            else:
                return "❓ Sebutkan ID budget (BUD-xxxx) atau nama budget yang ingin dihapus."
        else:
            budget_id = bid_match.group(0)

        budget = get_budget_by_id(budget_id)
        if not budget:
            return f"❌ Budget '{budget_id}' tidak ditemukan."

        # Tampilkan konfirmasi sebelum hapus
        links = get_links_by_budget(budget_id)
        if links:
            return (
                f"❌ **{budget['name']}** tidak bisa dihapus.\n\n"
                f"Masih ada **{len(links)} expense link** yang terhubung. "
                f"Budget ini sebaiknya dibiarkan sebagai arsip."
            )
        if budget.get("status") != "closed":
            return (
                f"❌ **{budget['name']}** masih aktif.\n\n"
                f"Tutup dulu dengan: `tutup budget {budget_id}`"
            )

        # Konfirmasi hapus
        self._set_session(session_id, {
            "flow":      "delete_budget",
            "step":      "confirm",
            "budget_id": budget_id,
            "name":      budget["name"],
        })
        return (
            f"⚠️ Konfirmasi hapus budget:\n\n"
            f"• **ID:** {budget_id}\n"
            f"• **Nama:** {budget['name']}\n"
            f"• **Status:** Closed\n"
            f"• **Expense Links:** 0\n\n"
            f"Data ini akan **dihapus permanen** dan tidak bisa dikembalikan.\n"
            f"Yakin? (ya/tidak)"
        )

    def _handle_edit(self, message: str, session_id: str) -> str:
        """Edit budget — nama atau total."""
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        if not bid_match:
            return "❓ Sebutkan ID budget yang ingin diubah. (contoh: BUD-0001)"

        updates = {}
        amount = _parse_amount(message)
        if amount:
            updates["total_budget"] = amount

        if not updates:
            return "❓ Apa yang ingin diubah? (contoh: revisi total budget BUD-0001 jadi Rp600jt)"

        result = update_budget(bid_match.group(0), updates)
        if "error" in result:
            return f"❌ {result['error']}"
        return (
            f"✅ Budget **{result['name']}** berhasil diupdate.\n"
            f"• **Total Budget:** {_fmt(result['total_budget'])}"
        )

    def _handle_unlink(self, message: str, session_id: str) -> str:
        """Hapus expense link."""
        lnk_match = re.search(r"\bLNK-\d{4}\b", message.upper())
        if lnk_match:
            result = delete_expense_link(lnk_match.group(0))
            if "error" in result:
                return f"❌ {result['error']}"
            lnk = result["link"]
            return (
                f"✅ Link **{lnk['link_id']}** berhasil dihapus.\n"
                f"• **{lnk['doc_id']}** tidak lagi terhubung ke **{lnk['budget_name']}**"
            )

        # Cari by doc_id
        doc_id = self._extract_doc_id(message)
        if doc_id:
            links = get_links_by_doc(doc_id)
            if not links:
                return f"❓ Dokumen '{doc_id}' tidak memiliki link ke budget manapun."
            if len(links) == 1:
                result = delete_expense_link(links[0]["link_id"])
                lnk = result["link"]
                return f"✅ Link **{doc_id}** → **{lnk['budget_name']}** berhasil dihapus."
            opts = "\n".join(f"• {l['link_id']} → {l['budget_name']} ({_fmt(l['amount'])})" for l in links)
            return f"🔍 **{doc_id}** memiliki beberapa link:\n\n{opts}\n\nSebutkan ID link (LNK-xxxx) yang ingin dihapus."

        return "❓ Sebutkan ID link (LNK-xxxx) atau ID dokumen yang ingin di-unlink."

    def _handle_list_cats(self, message: str, session_id: str) -> str:
        """List semua kategori operasional."""
        cats = get_ops_categories()
        lines = ["📂 **Kategori Operasional:**\n"]
        for c in cats:
            lines.append(f"• **{c['code']}** — {c['name']}")
        return "\n".join(lines)

    def _handle_add_cat(self, message: str, session_id: str) -> str:
        """Tambah kategori operasional baru."""
        # Extract nama kategori (setelah kata "tambah kategori")
        m = re.search(r"(?:tambah|tambahkan)\s+kategori\s+(.+)", message, re.IGNORECASE)
        if not m:
            return "❓ Format: `tambah kategori [nama kategori]`"
        name = m.group(1).strip()
        code = re.sub(r"[^A-Z0-9]", "_", name.upper())[:20]
        result = add_ops_category(code, name)
        if "error" in result:
            return f"❌ {result['error']}"
        return f"✅ Kategori **{result['name']}** (kode: {result['code']}) berhasil ditambahkan."

    # ══════════════════════════════════════════════════════════
    # HELPER EXTRACTORS
    # ══════════════════════════════════════════════════════════

    def _extract_project_name(self, message: str) -> Optional[str]:
        """Extract nama proyek dari pesan. Return None jika nama tidak spesifik."""
        # Kata-kata yang BUKAN nama proyek
        GENERIC_WORDS = {
            "baru", "proyek", "project", "budget", "anggaran",
            "buat", "tambah", "create", "add", "bikin", "mulai",
            "ini", "itu", "lain", "lainnya", "semua", "semua",
        }

        patterns = [
            # "buat budget proyek [nama]" atau "buat budget [nama]"
            r"(?:buat|tambah|set|create|add|bikin)\s+budget\s+(?:proyek\s+|project\s+)?(.+?)(?:\s+(?:rp|senilai|\d)|\s+jan|\s+feb|\s+mar|\s+apr|\s+mei|\s+jun|\s+jul|\s+agu|\s+sep|\s+okt|\s+nov|\s+des|$)",
            # "budget untuk proyek [nama]"
            r"budget\s+(?:untuk\s+)?(?:proyek|project)\s+(.+?)(?:\s+(?:rp|\d)|$)",
        ]
        for p in patterns:
            m = re.search(p, message, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # Buang tanda baca trailing
                name = re.sub(r'[.,;:!?]+$', '', name).strip()
                # Tolak kalau nama adalah kata generik atau terlalu pendek
                if name.lower() not in GENERIC_WORDS and len(name) > 2:
                    return name
        return None

    def _extract_ops_category(self, message: str) -> Optional[dict]:
        """Cari kategori ops di pesan."""
        cats = get_ops_categories()
        msg_lower = message.lower()
        for c in cats:
            if c["code"].lower() in msg_lower or c["name"].lower().split()[0] in msg_lower:
                return c
        return None

    def _extract_date_range(self, message: str) -> dict:
        """Extract start & end date dari pesan."""
        month_map = {
            "jan": ("01", "31"), "feb": ("02", "28"), "mar": ("03", "31"),
            "apr": ("04", "30"), "mei": ("05", "31"), "jun": ("06", "30"),
            "jul": ("07", "31"), "agu": ("08", "31"), "agst": ("08", "31"),
            "sep": ("09", "30"), "okt": ("10", "31"), "nov": ("11", "30"),
            "des": ("12", "31"),
        }
        year = _parse_year(message) or datetime.now().year
        found = []
        msg_l = message.lower()
        for abbr, (num, last) in month_map.items():
            if abbr in msg_l:
                found.append((msg_l.index(abbr), f"{year}-{num}-01", f"{year}-{num}-{last}"))
        found.sort()
        if len(found) >= 2:
            return {"start": found[0][1], "end": found[-1][2]}
        if len(found) == 1:
            return {"start": found[0][1], "end": None}
        return {"start": None, "end": None}

    def _extract_doc_id(self, message: str) -> Optional[str]:
        """Extract satu ID dokumen dari pesan (ambil yang pertama)."""
        m = re.search(r"\b(PR|PO|QT|RMB|CAS|INV)-\d{4}\b", message.upper())
        return m.group(0) if m else None

    def _extract_doc_ids(self, message: str) -> list:
        """Extract SEMUA ID dokumen dari pesan (support multi-link)."""
        matches = re.findall(r"\b((?:PR|PO|QT|RMB|CAS|INV)-\d{4})\b", message.upper())
        # Deduplicate sambil pertahankan urutan
        seen = set()
        result = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                result.append(m)
        return result

    def _extract_budget_from_message(self, message: str):
        """
        Cari budget yang disebutkan di pesan.
        Return: dict (satu), list (ambiguous), None (tidak ditemukan)
        Hanya cari budget dengan status active.
        """
        # By ID — cek status juga
        bid_match = re.search(r"\bBUD-\d{4}\b", message.upper())
        if bid_match:
            b = get_budget_by_id(bid_match.group(0))
            if b and b.get("status") == "active":
                return b
            elif b and b.get("status") == "closed":
                return {"error": f"Budget {bid_match.group(0)} sudah ditutup."}
            return None

        # By name — hanya active
        m = re.search(r"(?:ke|budget)\s+(.+?)(?:\s*$|\s*,)", message, re.IGNORECASE)
        if m:
            query = m.group(1).strip()
            results = find_budget_by_name(query, status="active")
            if len(results) == 1:
                return results[0]
            if len(results) > 1:
                return results
        return None

    def _extract_budget_name_query(self, message: str) -> Optional[str]:
        """Extract nama budget dari query cek/check."""
        patterns = [
            r"(?:cek|lihat|tampilkan|sisa)\s+budget\s+(.+?)(?:\s+berapa|\s+ini|\s*$)",
            r"budget\s+(.+?)\s+(?:berapa|sisa|terpakai)",
            r"(?:proyek|project)\s+(.+?)(?:\s+budget|\s*$)",
        ]
        for p in patterns:
            m = re.search(p, message, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _doc_to_expense_type(self, doc_id: str) -> str:
        """Tentukan expense_type berdasarkan prefix dokumen."""
        committed_prefixes = ("PR", "PO", "QT")
        actual_prefixes    = ("RMB", "CAS", "INV")
        prefix = doc_id.split("-")[0].upper()
        if prefix in committed_prefixes:
            return "committed"
        if prefix in actual_prefixes:
            return "actual"
        return "actual"   # default
