"""
agent/invoice_core.py — Eva Invoice Handler
============================================
Dipanggil dari agent/core.py di _execute_intent() setelah intent diklasifikasi.
Pola mengikuti quotation_core.py:
  - add_inv        : buat invoice baru (multi-step collect → confirm → save)
  - list_inv       : list / filter / detail invoice
  - update_inv     : edit field invoice
  - delete_inv     : hapus invoice
  - generate_inv   : generate PDF / Excel invoice
  - mark_paid      : ubah status ke paid
  - mark_issued    : ubah status ke issued (dari draft)

Storage: self.sm (storage.manager)
Session pending: self.session_manager (SessionManager)
"""

import re
import time
from datetime import datetime

# ─── INTENT SYSTEM SNIPPET (tambahkan ke INTENT_SYSTEM di core.py) ───────────
# Salin blok di bawah ke dalam string INTENT_SYSTEM di agent/core.py,
# di bawah baris terakhir contoh QT.
INTENT_SYSTEM_ADDON = r"""
INV     : add_inv(klien_nama,klien_alamat,nomor,tanggal,project_name,items,
                  ttd_nama,ttd_jabatan,bank_nama,bank_rekening,bank_cabang,bank_atas_nama,
                  quotation_id),
           list_inv(status,klien,id),
           update_inv(id,updates),
           delete_inv(id),
           generate_inv(id,format),
           mark_paid(id),
           mark_issued(id)

CONTOH INV:
user: "buat invoice" atau "buat faktur" atau "buat INV"
→ {"intent":"add_inv","params":{}}

user: "buat invoice untuk PT City Neonindo"
→ {"intent":"add_inv","params":{"klien_nama":"PT City Neonindo"}}

user: "buat invoice dari QT-0001"
→ {"intent":"add_inv","params":{"quotation_id":"QT-0001"}}

user: "list invoice" atau "tampilkan semua invoice"
→ {"intent":"list_inv","params":{}}

user: "invoice yang belum dibayar"
→ {"intent":"list_inv","params":{"status":"issued"}}

user: "tampilkan INV-0001" atau "detail INV-0001"
→ {"intent":"list_inv","params":{"id":"INV-0001"}}

user: "generate PDF INV-0001" atau "download invoice INV-0001"
→ {"intent":"generate_inv","params":{"id":"INV-0001","format":"pdf"}}

user: "generate excel INV-0001"
→ {"intent":"generate_inv","params":{"id":"INV-0001","format":"excel"}}

user: "INV-0001 sudah dibayar" atau "mark paid INV-0001"
→ {"intent":"mark_paid","params":{"id":"INV-0001"}}

user: "issue INV-0001" atau "kirim invoice INV-0001"
→ {"intent":"mark_issued","params":{"id":"INV-0001"}}

user: "hapus INV-0001"
→ {"intent":"delete_inv","params":{"id":"INV-0001"}}

user: "edit project INV-0001 jadi Padel VR Simulator"
→ {"intent":"update_inv","params":{"id":"INV-0001","updates":{"project_name":"Padel VR Simulator"}}}
"""

# ─── INTENT ALIASES (tambahkan ke INTENT_ALIASES di core.py) ─────────────────
INTENT_ALIASES_ADDON = {
    "add_invoice":        "add_inv",
    "create_inv":         "add_inv",
    "buat_invoice":       "add_inv",
    "new_inv":            "add_inv",
    "create_invoice":     "add_inv",
    "list_invoice":       "list_inv",
    "view_inv":           "list_inv",
    "detail_inv":         "list_inv",
    "show_inv":           "list_inv",
    "generate_invoice":   "generate_inv",
    "download_inv":       "generate_inv",
    "download_invoice":   "generate_inv",
    "paid_inv":           "mark_paid",
    "invoice_paid":       "mark_paid",
    "bayar_inv":          "mark_paid",
    "lunas_inv":          "mark_paid",
    "issue_inv":          "mark_issued",
    "issued_inv":         "mark_issued",
    "send_inv":           "mark_issued",
    "kirim_invoice":      "mark_issued",
    "hapus_inv":          "delete_inv",
    "delete_invoice":     "delete_inv",
    "update_invoice":     "update_inv",
    "edit_inv":           "update_inv",
    "edit_invoice":       "update_inv",
}

# ─── SAFETY NET KEYWORDS ──────────────────────────────────────────────────────
INV_PATTERN = r'\bINV\b|\binvoice\b|\bfaktur\b|\bINV-\d+\b'

# ─── COLLECT STEPS ────────────────────────────────────────────────────────────
_COLLECT_STEPS = [
    "klien_nama",
    "klien_alamat",
    "nomor",
    "project_name",
    "items",
]
_FIELD_LABELS = {
    "klien_nama":   "nama klien/perusahaan",
    "klien_alamat": "alamat klien (bisa multi-baris)",
    "nomor":        "nomor Invoice (contoh: INV/004/HLMC/PVR/I/2026)",
    "project_name": "nama project/pekerjaan",
    "items":        "daftar item (nama, qty, satuan, harga satuan, total)",
}

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _fmt_rp(n) -> str:
    try:
        return f"Rp {int(n):,.0f}".replace(",", ".")
    except:
        return "Rp 0"

def _terbilang(n: int) -> str:
    """Konversi angka ke teks terbilang Bahasa Indonesia (sederhana)."""
    if n == 0:
        return "Nol Rupiah"
    satuan = ["", "Satu", "Dua", "Tiga", "Empat", "Lima",
              "Enam", "Tujuh", "Delapan", "Sembilan", "Sepuluh",
              "Sebelas", "Dua Belas", "Tiga Belas", "Empat Belas",
              "Lima Belas", "Enam Belas", "Tujuh Belas", "Delapan Belas", "Sembilan Belas"]
    def _tiga(x):
        if x == 0: return ""
        if x < 20: return satuan[x]
        if x < 100:
            return satuan[x // 10] + " Puluh" + ("" if x % 10 == 0 else " " + satuan[x % 10])
        ratus = "Seratus" if x // 100 == 1 else satuan[x // 100] + " Ratus"
        sisa = x % 100
        return ratus + ("" if sisa == 0 else " " + _tiga(sisa))
    hasil = ""
    if n >= 1_000_000_000:
        hasil += _tiga(n // 1_000_000_000) + " Miliar "
        n %= 1_000_000_000
    if n >= 1_000_000:
        hasil += _tiga(n // 1_000_000) + " Juta "
        n %= 1_000_000
    if n >= 1_000:
        rb = n // 1_000
        hasil += ("Seribu " if rb == 1 else _tiga(rb) + " Ribu ")
        n %= 1_000
    if n > 0:
        hasil += _tiga(n)
    return hasil.strip() + " Rupiah"

def _parse_items(raw: list) -> list:
    """Pastikan setiap item punya field standar."""
    result = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        qty     = int(it.get("qty", 1))
        satuan  = it.get("satuan", "Ls")
        harga   = int(it.get("harga_per_unit", it.get("harga", it.get("satuan_rp", 0))))
        total   = int(it.get("total", it.get("jumlah", qty * harga)))
        # Kalau harga 0 tapi total ada, hitung per unit
        if harga == 0 and total > 0 and qty > 0:
            harga = total // qty
        result.append({
            "nama":         it.get("nama", it.get("deskripsi", "")),
            "qty":          qty,
            "satuan":       satuan,
            "satuan_rp":    harga,
            "total":        total if total else qty * harga,
        })
    return result

def _total_items(items: list) -> int:
    return sum(int(x.get("total", x.get("jumlah", 0))) for x in items)

def _item_preview(items: list) -> str:
    lines = []
    for i, x in enumerate(items, 1):
        lines.append(
            f"  {i}. {x.get('nama','')} — "
            f"{x.get('qty',1)} {x.get('satuan','Ls')} × "
            f"{_fmt_rp(x.get('satuan_rp',0))} = "
            f"{_fmt_rp(x.get('total',0))}"
        )
    return "\n".join(lines)

def _next_missing(pending: dict):
    for step in _COLLECT_STEPS:
        if step == "items":
            if not pending.get("items"):
                return "items"
        elif not pending.get(step):
            return step
    return None

def _confirm_summary(p: dict) -> str:
    items   = p.get("items", [])
    total   = _total_items(items)
    tanggal = p.get("tanggal", datetime.now().strftime("%d %B %Y"))
    qt_ref  = f"\n  Dari QT : {p['quotation_id']}" if p.get("quotation_id") else ""
    return (
        f"🧾 Rangkuman Invoice sebelum disimpan:\n"
        f"  Nomor   : {p.get('nomor','')}\n"
        f"  Klien   : {p.get('klien_nama','')}\n"
        f"  Alamat  : {p.get('klien_alamat','')}\n"
        f"  Tanggal : {tanggal}\n"
        f"  Project : {p.get('project_name','')}\n"
        f"  Items   : {len(items)} item — total {_fmt_rp(total)}\n"
        + (_item_preview(items) + "\n" if items else "")
        + qt_ref
        + f"\n\nSudah benar? Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
    )


# ─── ITEM TEXT PARSER ─────────────────────────────────────────────────────────

def _parse_items_from_text(text: str) -> list:
    """
    Parse item invoice dari teks bebas user.
    Mendukung format yang sama dengan quotation_core.
    """
    items = []

    # Pre-normalisasi: pecah numbered list inline
    text = re.sub(
        r'(?:(?<=\d{3})[.]\s+|(?<=juta)[.]\s+|(?<=juta)\s+|(?<=ribu)[.]\s+|(?<=ribu)\s+|(?<=jt)[.]\s+|(?<=jt)\s+)'
        r'(?=\d{1,2}[.)]\s*[A-Za-z]|\d{1,2}\s+[A-Z])',
        '\n', text, flags=re.I
    )

    lines = [l.strip() for l in re.split(r'\n|;', text) if l.strip()]
    lines = [re.sub(r'^\d+[.)]+\s*', '', l).strip() for l in lines if l.strip()]
    lines = [re.sub(r'^\d{1,2}\s+', '', l).strip() for l in lines if l.strip()]

    def _to_rp(s: str) -> int:
        s = s.strip()
        m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(juta|jt)\b', s, re.I)
        if m: return int(float(m.group(1).replace(',', '.')) * 1_000_000)
        m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(ribu|rb)\b', s, re.I)
        if m: return int(float(m.group(1).replace(',', '.')) * 1_000)
        m = re.search(r'Rp\s*([\d.,]+)', s, re.I)
        if m:
            try: return int(m.group(1).replace('.','').replace(',',''))
            except: pass
        m = re.search(r'\b(\d[\d.]{3,})\b', s)
        if m:
            try: return int(m.group(1).replace('.',''))
            except: pass
        return 0

    def _clean(s: str) -> str:
        s = re.sub(r'Rp\s*[\d.,]+', '', s, flags=re.I)
        s = re.sub(r'[\d]+(?:[.,]\d+)?\s*(?:juta|jt|ribu|rb)\b', '', s, flags=re.I)
        s = re.sub(r'\b\d+\s*(?:unit|pcs|buah|ls|set|box|hari|sesi|jam|bh|lbr|day|days)\b', '', s, flags=re.I)
        s = re.sub(r'\b(?:harga|per|dengan|dan|total|subtotal)\b', '', s, flags=re.I)
        s = re.sub(r'[@=,/]', ' ', s)
        return re.sub(r'\s+', ' ', s).strip().rstrip('- ') or "Item"

    # Daftar satuan yang diakui sebagai penanda qty (tidak termasuk nama produk)
    _SATUAN_RE = re.compile(
        r'^(unit|pcs|buah|ls|set|box|hari|sesi|jam|bh|lbr|day|days|lot|paket|pak|' 
        r'meter|m2|m3|kg|ton|liter|lembar|helai|roll|batang|keping|titik|' 
        r'lokasi|slot|lisensi|license|item|pasang|biji)$', re.I
    )

    for raw in lines:
        if not raw: continue
        line = re.sub(r'\b(dengan harga|seharga|senilai|sebesar)\b', ' ', raw, flags=re.I)
        line = re.sub(r'\s+', ' ', line).strip()

        # ── Parse qty: hapus token dimensi NxM dulu, lalu cari N <satuan_valid> ──
        # Token dimensi: "17x5", "3x4", "2.5×10meter" — bukan qty
        # Setelah dihapus, "1 unit" atau "3 unit" akan ditemukan dengan benar.
        # Satuan harus ada dalam whitelist — "Lumens", "Inch" tidak ada → skip.
        line_for_qty = re.sub(
            r'\b\d+(?:[.,]\d+)?[xX×]\d+(?:[.,]\d+)?\s*(?:m|cm|mm|meter)?\b',
            ' ', line
        )
        line_for_qty = re.sub(r'\s+', ' ', line_for_qty).strip()

        qty_raw, sat_raw = 1, "Ls"
        for m in re.finditer(r'(?<!\d)(\d+)\s+([a-zA-Z]\w*)', line_for_qty):
            if _SATUAN_RE.match(m.group(2)):
                qty_raw = int(m.group(1))
                sat_raw = m.group(2).title()
                break

        per_before = re.search(
            r'([\d]+(?:[.,]\d+)?\s*(?:juta|jt|ribu|rb|000)|Rp\s*[\d.,]+)\s+per\s+\w+', line, re.I)
        per_match  = re.search(r'\bper\s+\w+\s+(.*)', line, re.I)
        at_match   = re.search(r'[@]\s*(.*)', line)

        harga_per = 0
        harga_total_line = _to_rp(line)

        if at_match:
            harga_per = _to_rp(at_match.group(1))
        elif per_before:
            harga_per = _to_rp(per_before.group(1))
        elif per_match:
            harga_per = _to_rp(per_match.group(1))
        elif qty_raw > 1 and harga_total_line:
            harga_per = int(harga_total_line / qty_raw)
        elif harga_total_line:
            harga_per = harga_total_line

        if not harga_per:
            continue

        jumlah = harga_per * qty_raw

        if per_match:
            desc_raw = line[:per_match.start()].strip()
        elif at_match:
            desc_raw = line[:at_match.start()].strip()
        else:
            desc_raw = line
        desc = _clean(desc_raw)

        items.append({
            "nama":      desc,
            "qty":       qty_raw,
            "satuan":    sat_raw,
            "satuan_rp": harga_per,
            "total":     jumlah,
        })

    return items


# ─── MAIN HANDLER ─────────────────────────────────────────────────────────────

class InvoiceHandler:
    """
    Dipanggil dari Agent._execute_intent(). Butuh akses ke:
      self.sm              — storage manager
      self.session_manager — session / pending confirm manager
    """

    def __init__(self, agent):
        self.sm     = agent.sm
        self.sess   = agent.session_manager
        self._agent = agent

    # ── ADD INV ──────────────────────────────────────────────────────────────
    def handle_add_inv(self, session_id: str, params: dict):
        """
        Multi-step collect → confirm → save.
        Jika quotation_id disertakan, prefill data dari QT yang ada.
        """
        qt_id = params.get("quotation_id", "").strip().upper()
        qt_data = None

        # Coba prefill dari quotation jika ada
        if qt_id:
            all_qt = self.sm.get_qt()
            qt_data = next(
                (x for x in all_qt if x.get("id","").upper() == qt_id
                 or x.get("nomor","").upper() == qt_id),
                None
            )

        # Mapping items QT → format Invoice
        prefill_items = []
        if qt_data:
            for it in qt_data.get("items", []):
                prefill_items.append({
                    "nama":      it.get("deskripsi", it.get("nama", "")),
                    "qty":       it.get("qty", 1),
                    "satuan":    it.get("satuan", "Ls"),
                    "satuan_rp": it.get("harga_per_unit", 0),
                    "total":     it.get("jumlah", 0),
                })

        p = {
            "action":          "add_inv_collect",
            "klien_nama":      params.get("klien_nama", qt_data.get("klien_nama","") if qt_data else "").strip(),
            "klien_alamat":    params.get("klien_alamat", qt_data.get("klien_alamat","") if qt_data else "").strip(),
            "nomor":           params.get("nomor", "").strip(),
            "tanggal":         params.get("tanggal", datetime.now().strftime("%d %B %Y")),
            "project_name":    params.get("project_name", qt_data.get("re","") if qt_data else "").strip(),
            "items":           _parse_items(params.get("items", prefill_items)),
            "ttd_nama":        params.get("ttd_nama", "").strip(),
            "ttd_jabatan":     params.get("ttd_jabatan", "Finance").strip(),
            "bank_nama":       params.get("bank_nama", "").strip(),
            "bank_rekening":   params.get("bank_rekening", "").strip(),
            "bank_cabang":     params.get("bank_cabang", "").strip(),
            "bank_atas_nama":  params.get("bank_atas_nama", "").strip(),
            "quotation_id":    qt_id or None,
            "_created_at":     time.time(),
        }

        first_missing = _next_missing(p)
        if first_missing:
            self.sess.set_pending_confirm(session_id, p)
            prefix = ""
            if qt_data:
                prefix = (
                    f"📎 Data dari {qt_id} berhasil di-prefill!\n"
                    f"  Klien   : {p['klien_nama'] or '(belum ada)'}\n"
                    f"  Project : {p['project_name'] or '(belum ada)'}\n"
                    f"  Items   : {len(p['items'])} item\n\n"
                )
            return {
                "action": "add_inv", "status": "butuh_data",
                "reply_hint": (
                    f"{prefix}🧾 Siap buat Invoice baru!\n"
                    f"Mulai dari {_FIELD_LABELS[first_missing]} 🙏"
                )
            }, False

        # Semua data lengkap → confirm
        p["action"] = "add_inv_confirm"
        self.sess.set_pending_confirm(session_id, p)
        return {
            "action": "add_inv", "status": "butuh_konfirmasi",
            "reply_hint": _confirm_summary(p)
        }, False

    def handle_add_inv_collect(self, session_id: str, message: str, pending: dict):
        """Dipanggil dari _handle_confirm() saat action == 'add_inv_collect'."""
        msg_up = message.strip().upper()

        if self._is_escape(message, pending):
            self.sess.clear_pending_confirm(session_id)
            return None

        _in_note_phase = pending.get("_asked_optional") and not pending.get("_optional_answered")
        if not _in_note_phase and any(k in msg_up for k in ["BATAL", "CANCEL"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Pembuatan Invoice dibatalkan. 😊",
                    "skill_used": "invoice", "generated_file": None}

        waiting = _next_missing(pending)

        if waiting == "klien_nama":
            pending["klien_nama"] = message.strip().title()

        elif waiting == "klien_alamat":
            pending["klien_alamat"] = message.strip()

        elif waiting == "nomor":
            pending["nomor"] = message.strip()

        elif waiting == "project_name":
            pending["project_name"] = message.strip()

        elif waiting == "items":
            new_items = _parse_items_from_text(message)
            if new_items:
                pending["items"] = (pending.get("items") or []) + new_items
                total = _total_items(pending["items"])
                pending["_waiting_more_items"] = True
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        f"✅ {len(new_items)} item ditambahkan. "
                        f"Total sejauh ini: {_fmt_rp(total)}\n\n"
                        f"Masih ada item lagi? Kalau tidak, ketik 'selesai' atau 'lanjut' 🙏"
                    ),
                    "skill_used": "invoice", "generated_file": None
                }
            else:
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        "Maaf, format item belum terbaca. Coba format seperti:\n"
                        "\"HUD VR 512 GB, 3 Day, Rp 2.000.000\"\n"
                        "atau \"Camera 2 unit @ Rp 500.000\" 🙏"
                    ),
                    "skill_used": "invoice", "generated_file": None
                }

        # Handle "selesai" setelah input items
        if pending.get("_waiting_more_items"):
            if any(k in msg_up for k in ["SELESAI", "LANJUT", "DONE", "CUKUP", "SUDAH", "OK", "OKE"]):
                pending.pop("_waiting_more_items", None)
                pending["_asked_optional"] = True
                pending["_created_at"] = time.time()
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        "Siap! Terakhir, apakah ada info rekening bank untuk pembayaran?\n"
                        "(Contoh: \"BCA 274-1477086 Cabang KCU Kalimalang a/n Chandra Kirana\")\n"
                        "Kalau tidak, ketik 'skip' 🙏"
                    ),
                    "skill_used": "invoice", "generated_file": None
                }
            pending["_created_at"] = time.time()
            self.sess.set_pending_confirm(session_id, pending)
            total_str = _fmt_rp(_total_items(pending.get("items", [])))
            return {
                "reply": (
                    f"✅ Item ditambahkan. Total sejauh ini: {total_str}\n\n"
                    "Masih ada item lagi? Kalau tidak, ketik 'selesai' 🙏"
                ),
                "skill_used": "invoice", "generated_file": None
            }

        pending["_created_at"] = time.time()
        next_field = _next_missing(pending)

        if next_field:
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": f"Selanjutnya, {_FIELD_LABELS[next_field]} 🙏",
                "skill_used": "invoice", "generated_file": None
            }

        # Semua field wajib lengkap → tanya info bank (opsional)
        if not pending.get("_asked_optional"):
            pending["_asked_optional"] = True
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": (
                    "Siap! Terakhir, apakah ada info rekening bank untuk pembayaran?\n"
                    "(Contoh: \"BCA 274-1477086 Cabang KCU Kalimalang a/n Chandra Kirana\")\n"
                    "Kalau tidak, ketik 'skip' 🙏"
                ),
                "skill_used": "invoice", "generated_file": None
            }

        # Terima jawaban bank info
        if pending.get("_asked_optional") and not pending.get("_optional_answered"):
            pending["_optional_answered"] = True
            if not any(k in msg_up for k in ["TIDAK", "SKIP", "GAK", "NONE", "NO", "LANJUT"]):
                # Parse bank info dari teks bebas
                _parse_bank_info(message.strip(), pending)
            pending["action"] = "add_inv_confirm"
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": _confirm_summary(pending),
                "skill_used": "invoice", "generated_file": None
            }

        # Fallback
        pending["action"] = "add_inv_confirm"
        self.sess.set_pending_confirm(session_id, pending)
        return {
            "reply": _confirm_summary(pending),
            "skill_used": "invoice", "generated_file": None
        }

    def handle_add_inv_confirm(self, session_id: str, message: str, pending: dict):
        """Dipanggil dari _handle_confirm() saat action == 'add_inv_confirm'."""
        msg_up = message.strip().upper()

        if any(k in msg_up for k in ["BATAL", "CANCEL", "TIDAK", "GAK", "NO"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Pembuatan Invoice dibatalkan. 😊",
                    "skill_used": "invoice", "generated_file": None}

        if not any(k in msg_up for k in ["YA", "IYA", "YES", "OKE", "OK", "SETUJU", "YAP", "SIP", "BETUL", "BENAR"]):
            return {"reply": "Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏",
                    "skill_used": "invoice", "generated_file": None}

        # Simpan
        inv_data = {
            "klien_nama":     pending.get("klien_nama", ""),
            "klien_alamat":   pending.get("klien_alamat", ""),
            "nomor":          pending.get("nomor", ""),
            "tanggal":        pending.get("tanggal", datetime.now().strftime("%d %B %Y")),
            "project_name":   pending.get("project_name", ""),
            "items":          pending.get("items", []),
            "ttd_nama":       pending.get("ttd_nama", ""),
            "ttd_jabatan":    pending.get("ttd_jabatan", "Finance"),
            "bank_nama":      pending.get("bank_nama", ""),
            "bank_rekening":  pending.get("bank_rekening", ""),
            "bank_cabang":    pending.get("bank_cabang", ""),
            "bank_atas_nama": pending.get("bank_atas_nama", ""),
            "quotation_id":   pending.get("quotation_id"),
            "status":         "draft",
        }

        result = self.sm.add_inv(inv_data)
        self.sess.clear_pending_confirm(session_id)

        if not result:
            return {"reply": "❌ Gagal menyimpan Invoice. Coba lagi ya 🙏",
                    "skill_used": "invoice", "generated_file": None}

        inv_id = result.get("id", "")
        total  = _total_items(inv_data["items"])
        return {
            "reply": (
                f"✅ Invoice berhasil disimpan!\n"
                f"  ID       : {inv_id}\n"
                f"  Nomor    : {inv_data['nomor']}\n"
                f"  Klien    : {inv_data['klien_nama']}\n"
                f"  Project  : {inv_data['project_name']}\n"
                f"  Total    : {_fmt_rp(total)}\n"
                f"  Status   : Draft\n\n"
                f"Mau generate PDF sekarang? Ketik 'generate PDF {inv_id}' 📄"
            ),
            "skill_used": "invoice", "generated_file": None
        }

    # ── LIST INV ─────────────────────────────────────────────────────────────
    def handle_list_inv(self, session_id: str, params: dict):
        inv_id        = params.get("id", "").strip().upper()
        status_filter = params.get("status", "").lower()
        klien_filter  = params.get("klien", "").lower()

        all_inv = self.sm.get_inv()

        if inv_id:
            found = next(
                (x for x in all_inv if x.get("id","").upper() == inv_id
                 or x.get("nomor","").upper() == inv_id),
                None
            )
            if not found:
                return {"action": "list_inv", "data": [], "total": 0,
                        "reply_hint": f"Invoice {inv_id} tidak ditemukan 🙏"}, False
            items = found.get("items", [])
            total = _total_items(items)
            qt_ref = f"\n  Dari QT  : {found['quotation_id']}" if found.get("quotation_id") else ""
            return {
                "action": "list_inv", "data": [found], "total": 1,
                "reply_hint": (
                    f"🧾 {found.get('id','')} — {found.get('nomor','')}\n"
                    f"  Status   : {found.get('status','').title()}\n"
                    f"  Klien    : {found.get('klien_nama','')}\n"
                    f"  Tanggal  : {found.get('tanggal','')}\n"
                    f"  Project  : {found.get('project_name','')}\n"
                    f"  Items    : {len(items)} item\n"
                    + _item_preview(items) + "\n"
                    + f"  Total    : {_fmt_rp(total)}\n"
                    + qt_ref
                )
            }, False

        data = all_inv
        if status_filter: data = [x for x in data if status_filter in x.get("status","").lower()]
        if klien_filter:  data = [x for x in data if klien_filter  in x.get("klien_nama","").lower()]

        if not data:
            label = ""
            if status_filter: label += f" status '{status_filter}'"
            if klien_filter:  label += f" klien '{klien_filter}'"
            return {"action": "list_inv", "data": [], "total": 0,
                    "reply_hint": f"Belum ada Invoice{label} 📋"}, False

        lines = []
        for x in data:
            total = _total_items(x.get("items", []))
            lines.append(
                f"- {x.get('id','')} | {x.get('nomor','')} | "
                f"{x.get('klien_nama','')} | {x.get('status','').title()} | "
                f"{_fmt_rp(total)}"
            )
        return {
            "action": "list_inv", "data": data, "total": len(data),
            "reply_hint": f"📋 {len(data)} Invoice ditemukan:\n" + "\n".join(lines)
        }, False

    # ── UPDATE INV ────────────────────────────────────────────────────────────
    def handle_update_inv(self, session_id: str, params: dict, message: str = ""):
        inv_id  = params.get("id", "").strip().upper()
        updates = params.get("updates", {})

        if not inv_id:
            return {"action": "update_inv", "status": "butuh_id",
                    "reply_hint": "ID Invoice mana yang mau diubah? (contoh: INV-0001) 🙏"}, False

        found = self._find_inv(inv_id)
        if not found:
            return {"action": "update_inv", "status": "tidak_ditemukan",
                    "reply_hint": f"Invoice {inv_id} tidak ditemukan 🙏"}, False

        # Normalize field aliases
        _inv_field_aliases = {
            "nama_klien":     "klien_nama",
            "klien":          "klien_nama",
            "klien_nama":     "klien_nama",
            "alamat_klien":   "klien_alamat",
            "alamat":         "klien_alamat",
            "klien_alamat":   "klien_alamat",
            "project":        "project_name",
            "proyek":         "project_name",
            "project_name":   "project_name",
            "tanggal":        "tanggal",
            "nomor":          "nomor",
            "ttd_nama":       "ttd_nama",
            "nama_ttd":       "ttd_nama",
            "ttd_jabatan":    "ttd_jabatan",
            "jabatan_ttd":    "ttd_jabatan",
            "bank_nama":      "bank_nama",
            "bank":           "bank_nama",
            "rekening":       "bank_rekening",
            "bank_rekening":  "bank_rekening",
            "cabang":         "bank_cabang",
            "bank_cabang":    "bank_cabang",
            "atas_nama":      "bank_atas_nama",
            "bank_atas_nama": "bank_atas_nama",
        }
        updates = {_inv_field_aliases.get(k, k): v for k, v in updates.items()}
        updates.pop("status", None)  # status via mark_paid / mark_issued

        result = self.sm.update_inv(found["id"], updates)
        if not result:
            return {"action": "update_inv", "status": "gagal",
                    "reply_hint": f"❌ Gagal update Invoice {inv_id} 🙏"}, False

        field_lines = "\n".join(f"  • {k}: {v}" for k, v in updates.items())
        return {
            "action": "update_inv", "status": "ok",
            "reply_hint": (
                f"✅ Invoice {found['id']} berhasil diperbarui!\n"
                f"Perubahan:\n{field_lines}\n\n"
                f"Mau generate ulang dokumen? Ketik 'generate PDF {found['id']}' 📄"
            )
        }, False

    # ── DELETE INV ────────────────────────────────────────────────────────────
    def handle_delete_inv(self, session_id: str, params: dict):
        inv_id = params.get("id", "").strip().upper()

        if not inv_id:
            return {"action": "delete_inv", "status": "butuh_id",
                    "reply_hint": "ID Invoice mana yang mau dihapus? (contoh: INV-0001) 🙏"}, False

        found = self._find_inv(inv_id)
        if not found:
            return {"action": "delete_inv", "status": "tidak_ditemukan",
                    "reply_hint": f"Invoice {inv_id} tidak ditemukan 🙏"}, False

        self.sess.set_pending_confirm(session_id, {
            "action":      "delete_inv_confirm",
            "id":          found["id"],
            "detail":      found,
            "_created_at": time.time(),
        })
        return {
            "action": "delete_inv", "status": "butuh_konfirmasi",
            "reply_hint": (
                f"⚠️ Konfirmasi hapus {found['id']}?\n"
                f"  Nomor  : {found.get('nomor','')}\n"
                f"  Klien  : {found.get('klien_nama','')}\n"
                f"  Status : {found.get('status','').title()}\n\n"
                f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
            )
        }, False

    def handle_delete_inv_confirm(self, session_id: str, message: str, pending: dict):
        msg_up = message.strip().upper()
        if any(k in msg_up for k in ["BATAL", "CANCEL", "TIDAK", "GAK", "NO"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Penghapusan dibatalkan. 😊",
                    "skill_used": "invoice", "generated_file": None}
        if not any(k in msg_up for k in ["YA", "IYA", "YES", "OKE", "OK", "SETUJU", "YAP", "SIP"]):
            return {"reply": "Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏",
                    "skill_used": "invoice", "generated_file": None}

        inv_id = pending.get("id", "")
        result = self.sm.delete_inv(inv_id)
        self.sess.clear_pending_confirm(session_id)

        if not result:
            return {"reply": f"❌ Gagal hapus Invoice {inv_id} 🙏",
                    "skill_used": "invoice", "generated_file": None}
        return {"reply": f"✅ Invoice {inv_id} berhasil dihapus. 😊",
                "skill_used": "invoice", "generated_file": None}

    # ── MARK PAID / ISSUED ────────────────────────────────────────────────────
    def handle_mark_paid(self, session_id: str, params: dict):
        return self._change_status(session_id, params, "paid")

    def handle_mark_issued(self, session_id: str, params: dict):
        return self._change_status(session_id, params, "issued")

    def _change_status(self, session_id: str, params: dict, new_status: str):
        inv_id = params.get("id", "").strip().upper()
        if not inv_id:
            label = {"paid": "dilunasi", "issued": "dikirim"}.get(new_status, "diupdate")
            return {"action": f"inv_status_{new_status}", "status": "butuh_id",
                    "reply_hint": f"ID Invoice mana yang mau di{label}? 🙏"}, False

        found = self._find_inv(inv_id)
        if not found:
            return {"action": f"inv_status_{new_status}", "status": "tidak_ditemukan",
                    "reply_hint": f"Invoice {inv_id} tidak ditemukan 🙏"}, False

        cur_status = found.get("status", "")
        # Validasi transisi status
        if new_status == "issued" and cur_status == "paid":
            return {"action": f"inv_status_{new_status}", "status": "gagal",
                    "reply_hint": f"⚠️ Invoice {inv_id} sudah berstatus Paid — tidak bisa kembali ke Issued 🙏"}, False
        if new_status == "paid" and cur_status not in ("issued", "draft", "overdue"):
            return {"action": f"inv_status_{new_status}", "status": "gagal",
                    "reply_hint": f"⚠️ Invoice {inv_id} sudah berstatus {cur_status.title()} 🙏"}, False

        updates = {"status": new_status}
        if new_status == "paid":
            updates["paid_at"] = datetime.now().isoformat()
        elif new_status == "issued":
            updates["issued_at"] = datetime.now().isoformat()

        result = self.sm.update_inv(found["id"], updates)
        if not result:
            return {"action": f"inv_status_{new_status}", "status": "gagal",
                    "reply_hint": f"❌ Gagal update status Invoice {inv_id} 🙏"}, False

        total = _total_items(found.get("items", []))

        # ── Sinkronisasi ke Laporan Keuangan ──────────────────────────────────
        if new_status == "paid":
            # Gunakan result (data setelah update) agar paid_at sudah terisi
            inv_data = result if isinstance(result, dict) else found
            # Pastikan paid_at ada
            if not inv_data.get("paid_at"):
                inv_data = dict(inv_data)
                inv_data["paid_at"] = datetime.now().isoformat()
            print(f"[InvoiceCore] mark_paid: sync to finance, inv_id={inv_data.get('id')}, total={_total_items(inv_data.get('items',[]))}")
            try:
                from storage.manager import add_invoice_to_finance
                fin_entry = add_invoice_to_finance(inv_data)
                print(f"[InvoiceCore] add_invoice_to_finance result: {fin_entry}")
                fin_note = f"\n  📒 Masuk laporan keuangan sebagai pemasukan" if fin_entry else "\n  ℹ️ Sudah ada di laporan keuangan"
            except Exception as _e:
                print(f"[InvoiceCore] add_invoice_to_finance ERROR: {_e}")
                fin_note = f"\n  ⚠️ Gagal sync laporan: {_e}"
        elif new_status == "issued" and cur_status == "paid":
            try:
                from storage.manager import remove_invoice_from_finance
                removed = remove_invoice_from_finance(found["id"])
                print(f"[InvoiceCore] remove_invoice_from_finance: {found['id']} removed={removed}")
                fin_note = "\n  📒 Dihapus dari laporan keuangan" if removed else ""
            except Exception as _e:
                print(f"[InvoiceCore] remove_invoice_from_finance ERROR: {_e}")
                fin_note = ""
        else:
            fin_note = ""

        if new_status == "paid":
            emoji, label = "✅", "lunas/dibayar"
            suffix = f"Terima kasih! Ada yang bisa dibantu lagi? 😊{fin_note}"
        else:
            emoji, label = "📤", "diterbitkan/dikirim"
            suffix = f"Invoice sudah berstatus Issued. Ketik 'mark paid {found['id']}' jika sudah dibayar.{fin_note}"
        return {
            "action": f"inv_status_{new_status}", "status": "ok",
            "reply_hint": (
                f"{emoji} Invoice {found['id']} berhasil {label}!\n"
                f"  Nomor  : {found.get('nomor','')}\n"
                f"  Klien  : {found.get('klien_nama','')}\n"
                f"  Total  : {_fmt_rp(total)}\n\n"
                f"{suffix}"
            )
        }, False

    # ── GENERATE ──────────────────────────────────────────────────────────────
    def handle_generate_inv(self, session_id: str, params: dict, generator_module):
        inv_id = params.get("id", "").strip().upper()
        fmt    = params.get("format", "pdf").lower()

        if not inv_id:
            return {"action": "generate_inv", "status": "butuh_id",
                    "reply_hint": "ID Invoice mana yang mau digenerate? (contoh: INV-0001) 🙏"}, False

        found = self._find_inv(inv_id)
        if not found:
            return {"action": "generate_inv", "status": "tidak_ditemukan",
                    "reply_hint": f"Invoice {inv_id} tidak ditemukan 🙏"}, False

        try:
            if fmt == "excel":
                path = generator_module.generate_inv_excel(found)
            else:
                path = generator_module.generate_inv_pdf(found)
            fmt_label = "Excel" if fmt == "excel" else "PDF"
            return {
                "action": "generate_inv", "status": "ok",
                "reply_hint": f"🧾 Dokumen Invoice {fmt_label} {found['id']} sudah siap, silakan klik link unduh di bawah.",
                "generated_file": path
            }, False
        except Exception as e:
            return {"action": "generate_inv", "status": "gagal",
                    "reply_hint": f"❌ Gagal generate dokumen: {e} 🙏"}, False

    # ── UTILS ─────────────────────────────────────────────────────────────────
    def _find_inv(self, inv_id: str):
        all_inv = self.sm.get_inv()
        return next(
            (x for x in all_inv
             if x.get("id","").upper() == inv_id
             or x.get("nomor","").upper() == inv_id),
            None
        )

    @staticmethod
    def _is_escape(message: str, pending: dict = None) -> bool:
        if pending and pending.get("_asked_optional") and not pending.get("_optional_answered"):
            return False
        escape_kw = [
            "GENERATE", "BUATKAN", "LAPORAN", "HAPUS", "LIHAT", "TAMPILKAN",
            "APPROVE", "REJECT", "EDIT", "LIST", "CEK", "SALDO", "PR", "PO",
            "KASBON", "REIMBURSE", "PURCHASE", "EXPORT", "PDF", "EXCEL",
        ]
        msg_up    = message.strip().upper()
        msg_words = msg_up.split()
        return any(k in msg_words or msg_up.startswith(k) for k in escape_kw)


# ─── HELPER: PARSE BANK INFO ─────────────────────────────────────────────────

def _parse_bank_info(text: str, pending: dict):
    """
    Parse info bank dari teks bebas dan isi ke pending.
    Contoh: "BCA 274-1477086 Cabang KCU Kalimalang a/n Chandra Kirana"
    """
    # Bank name
    bank_names = ["BCA", "BNI", "BRI", "MANDIRI", "CIMB", "DANAMON",
                  "PERMATA", "BTN", "OCBC", "NISP", "PANIN", "MEGA"]
    for bname in bank_names:
        if bname.lower() in text.lower():
            pending["bank_nama"] = bname
            break

    # Rekening number
    m_rek = re.search(r'\b(\d[\d\-]{5,20})\b', text)
    if m_rek:
        pending["bank_rekening"] = m_rek.group(1)

    # Cabang
    m_cab = re.search(r'(?:cabang|cab)[:\s]+([^\n,]+?)(?:\s+a/n|\s+atas\s+nama|$)', text, re.I)
    if m_cab:
        pending["bank_cabang"] = m_cab.group(1).strip()

    # Atas nama
    m_an = re.search(r'(?:a/n|atas nama)[:\s]+([^\n,]+)', text, re.I)
    if m_an:
        pending["bank_atas_nama"] = m_an.group(1).strip()


# ─── STORAGE MANAGER METHODS YANG DIBUTUHKAN ─────────────────────────────────
# Tambahkan ke storage/manager.py:
#
# def _next_inv_id() -> str: ...
# def add_inv(data: dict) -> dict: ...
# def get_inv(status: str = "") -> list: ...
# def get_inv_by_id(inv_id: str) -> dict | None: ...
# def update_inv(inv_id: str, updates: dict) -> dict | None: ...
# def delete_inv(inv_id: str) -> bool: ...
#
# Schema invoice di storage:
# {
#   "id":             "INV-0001",
#   "nomor":          "INV/004/HLMC/PVR/I/2026",
#   "klien_nama":     "PT City Neonindo Indah Murni",
#   "klien_alamat":   "Jl. Pangeran Tubagus Angke...",
#   "tanggal":        "22 January 2026",
#   "project_name":   "Padel VR Simulator 19-21 Januari 2026",
#   "items": [
#     {"nama": "HUD VR 512 GB", "qty": 3, "satuan": "Day",
#      "satuan_rp": 0, "total": 2000000}
#   ],
#   "total":          2000000,
#   "ttd_nama":       "Nadia Noviana",
#   "ttd_jabatan":    "Finance",
#   "bank_nama":      "BCA",
#   "bank_rekening":  "274-1477086",
#   "bank_cabang":    "KCU Kalimalang",
#   "bank_atas_nama": "Chandra Kirana",
#   "quotation_id":   null,   # opsional, link ke QT
#   "status":         "draft", # draft | issued | paid | overdue
#   "issued_at":      null,
#   "paid_at":        null,
#   "created_at":     "2026-07-20T...",
#   "updated_at":     "2026-07-20T...",
# }
