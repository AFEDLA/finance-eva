"""
skills/quotation/quotation_core.py — Eva Quotation Handler
===========================================================
Dipanggil dari agent/core.py di _execute_intent() setelah intent diklasifikasi.
Pola mengikuti PR/PO handler yang sudah ada:
  - add_qt        : buat quotation baru (multi-step collect → confirm → save)
  - list_qt       : list / filter / detail quotation
  - update_qt     : edit field quotation (status belum final, field header)
  - delete_qt     : hapus quotation
  - generate_qt   : generate PDF / Excel quotation
  - approve_qt    : alias — ubah status ke accepted
  - reject_qt     : alias — ubah status ke rejected

Storage: self.sm (storage.manager) — metode yang diperlukan ada di bawah.
Session pending: self.session_manager (SessionManager) — sama persis dengan PR/PO.
"""

import re
import time
from datetime import datetime

# ─── INTENT SYSTEM SNIPPET (tambahkan ke INTENT_SYSTEM di core.py) ──────────
# Salin blok di bawah ke dalam string INTENT_SYSTEM di agent/core.py,
# di bawah baris terakhir contoh PO.
INTENT_SYSTEM_ADDON = r"""
QT      : add_qt(klien_nama,klien_alamat,klien_up,nomor,tanggal,re,items,note,ttd_nama,ttd_hp),
           list_qt(status,klien,id),
           update_qt(id,updates),
           delete_qt(id),
           generate_qt(id,format),
           approve_qt(id),
           reject_qt(id)

CONTOH QT:
user: "buat quotation" atau "surat penawaran" atau "buat QT"
→ {"intent":"add_qt","params":{}}

user: "buat quotation untuk PT Jakarta Propertindo"
→ {"intent":"add_qt","params":{"klien_nama":"PT Jakarta Propertindo"}}

user: "list quotation" atau "tampilkan semua QT"
→ {"intent":"list_qt","params":{}}

user: "QT yang accepted"
→ {"intent":"list_qt","params":{"status":"accepted"}}

user: "tampilkan QT-0001" atau "detail QT-0001"
→ {"intent":"list_qt","params":{"id":"QT-0001"}}

user: "tampilkan quotation 05/HLMC-JP/IV/2026"
→ {"intent":"list_qt","params":{"id":"05/HLMC-JP/IV/2026"}}

user: "generate PDF QT-0001" atau "download quotation QT-0001"
→ {"intent":"generate_qt","params":{"id":"QT-0001","format":"pdf"}}

user: "generate excel QT-0001" atau "download excel QT-0001"
→ {"intent":"generate_qt","params":{"id":"QT-0001","format":"excel"}}

user: "accepted QT-0001" atau "quotation diterima QT-0001"
→ {"intent":"approve_qt","params":{"id":"QT-0001"}}

user: "reject QT-0001" atau "tolak quotation QT-0001"
→ {"intent":"reject_qt","params":{"id":"QT-0001"}}

user: "hapus QT-0001"
→ {"intent":"delete_qt","params":{"id":"QT-0001"}}

user: "edit re QT-0001 jadi Re-Alignment Video Dome"
→ {"intent":"update_qt","params":{"id":"QT-0001","updates":{"re":"Re-Alignment Video Dome"}}}

user: "ubah note QT-0001 jadi Price is valid for 2 weeks"
→ {"intent":"update_qt","params":{"id":"QT-0001","updates":{"note":"Price is valid for 2 weeks"}}}
"""

# ─── INTENT ALIASES (tambahkan ke INTENT_ALIASES di core.py) ─────────────────
INTENT_ALIASES_ADDON = {
    "add_quotation":      "add_qt",
    "create_qt":          "add_qt",
    "buat_qt":            "add_qt",
    "new_qt":             "add_qt",
    "list_quotation":     "list_qt",
    "view_qt":            "list_qt",
    "detail_qt":          "list_qt",
    "show_qt":            "list_qt",
    "generate_quotation": "generate_qt",
    "download_qt":        "generate_qt",
    "accept_qt":          "approve_qt",
    "accepted_qt":        "approve_qt",
    "rejected_qt":        "reject_qt",
    "hapus_qt":           "delete_qt",
    "delete_qt":          "delete_qt",
    "update_quotation":   "update_qt",
    "edit_qt":            "update_qt",
}

# ─── SAFETY NET KEYWORDS (untuk core.py _execute_intent) ─────────────────────
QT_PATTERN = r'\bQT\b|\bquotation\b|\bpenawaran\s+harga\b|\bsurat\s+penawaran\b|\bQT-\d+\b'

# ─── FIELD LABELS ─────────────────────────────────────────────────────────────
_COLLECT_STEPS = [
    "klien_nama",
    "klien_alamat",
    "nomor",
    "re",
    "items",
]
_FIELD_LABELS = {
    "klien_nama":   "nama klien/perusahaan",
    "klien_alamat": "alamat klien (dan UP/nama kontak jika ada)",
    "nomor":        "nomor Quotation (contoh: 05/HLMC-JP/VII/2026)",
    "re":           "judul/scope pekerjaan (Re: ...)",
    "items":        "daftar item (deskripsi, qty, satuan, harga per unit)",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _fmt_rp(n: int) -> str:
    return f"Rp {n:,.0f}".replace(",", ".")

def _parse_items(raw: list) -> list:
    """Pastikan setiap item punya field standar dan jumlah dihitung."""
    result = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        qty   = int(it.get("qty", 1))
        harga = int(it.get("harga_per_unit", it.get("harga", 0)))
        jml   = qty * harga
        result.append({
            "deskripsi":    it.get("deskripsi", it.get("nama", "")),
            "qty":          qty,
            "satuan":       it.get("satuan", "Ls"),
            "harga_per_unit": harga,
            "jumlah":       jml,
        })
    return result

def _total_items(items: list) -> int:
    return sum(int(x.get("jumlah", 0)) for x in items)

def _item_preview(items: list) -> str:
    lines = []
    for i, x in enumerate(items, 1):
        lines.append(
            f"  {i}. {x.get('deskripsi','')} — "
            f"{x.get('qty',1)} {x.get('satuan','Ls')} × "
            f"{_fmt_rp(x.get('harga_per_unit',0))} = "
            f"{_fmt_rp(x.get('jumlah',0))}"
        )
    return "\n".join(lines)

def _next_missing(pending: dict) -> str | None:
    """Return field pertama yang masih kosong."""
    for step in _COLLECT_STEPS:
        if step == "items":
            if not pending.get("items"):
                return "items"
        elif not pending.get(step):
            return step
    return None

def _confirm_summary(p: dict) -> str:
    items    = p.get("items", [])
    total    = _total_items(items)
    n_items  = len(items)
    tanggal  = p.get("tanggal", datetime.now().strftime("%d %B %Y"))
    klien_up = f" — UP: {p['klien_up']}" if p.get("klien_up") else ""
    return (
        f"💼 Rangkuman Quotation sebelum disimpan:\n"
        f"  Nomor   : {p.get('nomor','')}\n"
        f"  Klien   : {p.get('klien_nama','')}{klien_up}\n"
        f"  Alamat  : {p.get('klien_alamat','')}\n"
        f"  Tanggal : {tanggal}\n"
        f"  Re      : {p.get('re','')}\n"
        f"  Items   : {n_items} item — total {_fmt_rp(total)}\n"
        + (_item_preview(items) + "\n" if items else "")
        + (f"  Note    : {p['note']}\n" if p.get("note") else "")
        + f"\nSudah benar? Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
    )


# ─── MAIN HANDLER ─────────────────────────────────────────────────────────────

class QuotationHandler:
    """
    Dipanggil dari Agent._execute_intent(). Butuh akses ke:
      self.sm              — storage manager
      self.session_manager — session / pending confirm manager
    """

    def __init__(self, agent):
        self.sm      = agent.sm
        self.sess    = agent.session_manager
        self._agent  = agent

    # ── ADD QT ───────────────────────────────────────────────────────────────
    def handle_add_qt(self, session_id: str, params: dict):
        """
        Multi-step collect → confirm → save.
        Ikut pola add_po di core.py.
        """
        p = {
            "action":       "add_qt_collect",
            "klien_nama":   params.get("klien_nama",   "").strip(),
            "klien_alamat": params.get("klien_alamat", "").strip(),
            "klien_up":     params.get("klien_up",     "").strip(),
            "nomor":        params.get("nomor",        "").strip(),
            "tanggal":      params.get("tanggal",      datetime.now().strftime("%d %B %Y")),
            "re":           params.get("re",           "").strip(),
            "items":        _parse_items(params.get("items", [])),
            "note":         params.get("note",         "").strip(),
            "ttd_nama":     params.get("ttd_nama",     "").strip(),
            "ttd_hp":       params.get("ttd_hp",       "").strip(),
            "_created_at":  time.time(),
        }

        first_missing = _next_missing(p)
        if first_missing:
            self.sess.set_pending_confirm(session_id, p)
            return {
                "action": "add_qt", "status": "butuh_data",
                "reply_hint": (
                    f"💼 Siap buat Quotation baru!\n"
                    f"Mulai dari {_FIELD_LABELS[first_missing]} 🙏"
                )
            }, False

        # Semua data lengkap → confirm
        p["action"] = "add_qt_confirm"
        self.sess.set_pending_confirm(session_id, p)
        return {
            "action": "add_qt", "status": "butuh_konfirmasi",
            "reply_hint": _confirm_summary(p)
        }, False

    def handle_add_qt_collect(self, session_id: str, message: str, pending: dict):
        """
        Dipanggil dari _handle_confirm() saat action == 'add_qt_collect'.
        Terima jawaban user satu field, lanjut ke field berikutnya.
        """
        msg_up = message.strip().upper()

        # Escape — perintah baru
        if self._is_escape(message, pending):
            self.sess.clear_pending_confirm(session_id)
            return None  # lanjut ke classify_intent normal

        # Batal — hanya kalau belum di fase note (TIDAK di fase note = tidak ada note)
        _in_note_phase = pending.get("_asked_note") and not pending.get("_note_answered")
        if not _in_note_phase and any(k in msg_up for k in ["BATAL", "CANCEL"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Pembuatan Quotation dibatalkan. 😊",
                    "skill_used": "quotation", "generated_file": None}

        waiting = _next_missing(pending)

        if waiting == "klien_nama":
            pending["klien_nama"] = message.strip().title()

        elif waiting == "klien_alamat":
            # Cek apakah ada UP dalam pesan
            up_match = re.search(r'UP[:\s]+(.+?)(?:,|$)', message, re.IGNORECASE)
            if up_match:
                pending["klien_up"] = up_match.group(1).strip()
                pending["klien_alamat"] = re.sub(r'\bUP[:\s]+.+', '', message, flags=re.IGNORECASE).strip().rstrip(",")
            else:
                pending["klien_alamat"] = message.strip()

        elif waiting == "nomor":
            pending["nomor"] = message.strip()

        elif waiting == "re":
            re_val = message.strip()
            if re_val.lower().startswith("re:"):
                re_val = re_val[3:].strip()
            pending["re"] = re_val

        elif waiting == "items":
            new_items = _parse_items_from_text(message)
            if new_items:
                pending["items"] = (pending.get("items") or []) + new_items
                # Tanya apakah masih ada item lagi
                total = _total_items(pending["items"])
                pending["_waiting_more_items"] = True
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        f"✅ {len(new_items)} item ditambahkan. "
                        f"Total sejauh ini: {_fmt_rp(total)}\n\n"
                        f"Masih ada item lagi? Kalau tidak, ketik 'selesai' atau 'lanjut' 🙏"
                    ),
                    "skill_used": "quotation", "generated_file": None
                }
            else:
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        "Maaf, format item belum terbaca. Coba format seperti:\n"
                        "\"Re-Editing Video, 1 Ls, Rp 200.000.000\"\n"
                        "atau \"Konsultasi AI 3 hari @ Rp 5.000.000/hari\" 🙏"
                    ),
                    "skill_used": "quotation", "generated_file": None
                }

        # ── Handle "selesai"/"lanjut" setelah input items ──
        if pending.get("_waiting_more_items"):
            if any(k in msg_up for k in ["SELESAI", "LANJUT", "DONE", "CUKUP", "SUDAH", "OK", "OKE"]):
                pending.pop("_waiting_more_items", None)
                # Langsung tanya note setelah user bilang selesai
                pending["_asked_note"] = True
                pending["_created_at"] = time.time()
                self.sess.set_pending_confirm(session_id, pending)
                return {
                    "reply": (
                        "Ada catatan/note untuk klien? "
                        "(contoh: \"Price is valid for 1 week from sent date\")\n"
                        "Kalau tidak ada, ketik 'tidak' atau 'skip' 🙏"
                    ),
                    "skill_used": "quotation", "generated_file": None
                }
            # User masih ketik item baru — sudah dihandle di atas
            pending["_created_at"] = time.time()
            self.sess.set_pending_confirm(session_id, pending)
            total_str = _fmt_rp(_total_items(pending.get("items", [])))
            return {
                "reply": (
                    f"\u2705 Item ditambahkan. Total sejauh ini: {total_str}\n\n"
                    "Masih ada item lagi? Kalau tidak, ketik 'selesai' \U0001f64f"
                ),
                "skill_used": "quotation", "generated_file": None
            }

        pending["_created_at"] = time.time()
        next_field = _next_missing(pending)

        if next_field:
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": f"Selanjutnya, {_FIELD_LABELS[next_field]} 🙏",
                "skill_used": "quotation", "generated_file": None
            }

        # ── Semua field lengkap → tanya note ──
        if not pending.get("_asked_note"):
            pending["_asked_note"] = True
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": (
                    "Ada catatan/note untuk klien? "
                    "(contoh: \"Price is valid for 1 week from sent date\")\n"
                    "Kalau tidak ada, ketik 'tidak' atau 'skip' 🙏"
                ),
                "skill_used": "quotation", "generated_file": None
            }

        # ── Terima jawaban note → langsung tampilkan summary confirm ──
        if pending.get("_asked_note") and not pending.get("_note_answered"):
            pending["_note_answered"] = True
            if not any(k in msg_up for k in ["TIDAK", "SKIP", "GAK", "NONE", "NO", "LANJUT", "NEXT"]):
                pending["note"] = message.strip()
            pending["action"] = "add_qt_confirm"
            self.sess.set_pending_confirm(session_id, pending)
            return {
                "reply": _confirm_summary(pending),
                "skill_used": "quotation", "generated_file": None
            }

        # ── Fallback: sudah semua → confirm ──
        pending["action"] = "add_qt_confirm"
        self.sess.set_pending_confirm(session_id, pending)
        return {
            "reply": _confirm_summary(pending),
            "skill_used": "quotation", "generated_file": None
        }

    def handle_add_qt_confirm(self, session_id: str, message: str, pending: dict):
        """Dipanggil dari _handle_confirm() saat action == 'add_qt_confirm'."""
        msg_up = message.strip().upper()

        if any(k in msg_up for k in ["BATAL", "CANCEL", "TIDAK", "GAK", "NO"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Pembuatan Quotation dibatalkan. 😊",
                    "skill_used": "quotation", "generated_file": None}

        if not any(k in msg_up for k in ["YA", "IYA", "YES", "OKE", "OK", "SETUJU", "YAP", "SIP", "BETUL", "BENAR"]):
            return {"reply": "Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏",
                    "skill_used": "quotation", "generated_file": None}

        # Simpan
        qt_data = {
            "klien_nama":    pending.get("klien_nama", ""),
            "klien_alamat":  pending.get("klien_alamat", ""),
            "klien_up":      pending.get("klien_up", ""),
            "nomor":         pending.get("nomor", ""),
            "tanggal":       pending.get("tanggal", datetime.now().strftime("%d %B %Y")),
            "re":            pending.get("re", ""),
            "items":         pending.get("items", []),
            "note":          pending.get("note", ""),
            "ttd_nama":      pending.get("ttd_nama", ""),
            "ttd_hp":        pending.get("ttd_hp", ""),
            "status":        "draft",
            "quotation_id":  None,  # akan diisi oleh storage manager
        }

        result = self.sm.add_qt(qt_data)
        self.sess.clear_pending_confirm(session_id)

        if not result:
            return {"reply": "❌ Gagal menyimpan Quotation. Coba lagi ya 🙏",
                    "skill_used": "quotation", "generated_file": None}

        qt_id = result.get("id", "")
        total = _total_items(qt_data["items"])
        return {
            "reply": (
                f"✅ Quotation berhasil disimpan!\n"
                f"  ID       : {qt_id}\n"
                f"  Nomor    : {qt_data['nomor']}\n"
                f"  Klien    : {qt_data['klien_nama']}\n"
                f"  Re       : {qt_data['re']}\n"
                f"  Total    : {_fmt_rp(total)}\n"
                f"  Status   : Draft\n\n"
                f"Mau generate PDF sekarang? Ketik 'generate PDF {qt_id}' 📄"
            ),
            "skill_used": "quotation", "generated_file": None
        }

    # ── LIST QT ──────────────────────────────────────────────────────────────
    def handle_list_qt(self, session_id: str, params: dict):
        qt_id        = params.get("id", "").strip().upper()
        status_filter= params.get("status", "").lower()
        klien_filter = params.get("klien", "").lower()

        all_qt = self.sm.get_qt()

        # Detail by ID / nomor
        if qt_id:
            # Coba by ID dulu (QT-0001), lalu by nomor (05/HLMC-JP/...)
            found = next(
                (x for x in all_qt if x.get("id","").upper() == qt_id
                 or x.get("nomor","").upper() == qt_id),
                None
            )
            if not found:
                return {"action": "list_qt", "data": [], "total": 0,
                        "reply_hint": f"Quotation {qt_id} tidak ditemukan 🙏"}, False
            items      = found.get("items", [])
            total      = _total_items(items)
            klien_up   = f" — UP: {found['klien_up']}" if found.get("klien_up") else ""
            return {
                "action": "list_qt", "data": [found], "total": 1,
                "reply_hint": (
                    f"📄 {found.get('id','')} — {found.get('nomor','')}\n"
                    f"  Status  : {found.get('status','').title()}\n"
                    f"  Klien   : {found.get('klien_nama','')}{klien_up}\n"
                    f"  Tanggal : {found.get('tanggal','')}\n"
                    f"  Re      : {found.get('re','')}\n"
                    f"  Items   : {len(items)} item\n"
                    + _item_preview(items) + "\n"
                    f"  Total   : {_fmt_rp(total)}\n"
                    + (f"  Note    : {found['note']}\n" if found.get("note") else "")
                )
            }, False

        # Filter
        data = all_qt
        if status_filter: data = [x for x in data if status_filter in x.get("status","").lower()]
        if klien_filter:  data = [x for x in data if klien_filter  in x.get("klien_nama","").lower()]

        if not data:
            label = ""
            if status_filter: label += f" status '{status_filter}'"
            if klien_filter:  label += f" klien '{klien_filter}'"
            return {"action": "list_qt", "data": [], "total": 0,
                    "reply_hint": f"Belum ada Quotation{label} 📋"}, False

        lines = []
        for x in data:
            total = _total_items(x.get("items", []))
            lines.append(
                f"- {x.get('id','')} | {x.get('nomor','')} | "
                f"{x.get('klien_nama','')} | {x.get('status','').title()} | "
                f"{_fmt_rp(total)}"
            )
        return {
            "action": "list_qt", "data": data, "total": len(data),
            "reply_hint": f"📋 {len(data)} Quotation ditemukan:\n" + "\n".join(lines)
        }, False

    # ── UPDATE QT ─────────────────────────────────────────────────────────────
    def handle_update_qt(self, session_id: str, params: dict, message: str = ""):
        qt_id   = params.get("id", "").strip().upper()
        updates = params.get("updates", {})

        if not qt_id:
            return {"action": "update_qt", "status": "butuh_id",
                    "reply_hint": "ID Quotation mana yang mau diubah? (contoh: QT-0001) 🙏"}, False

        found = self._find_qt(qt_id)
        if not found:
            return {"action": "update_qt", "status": "tidak_ditemukan",
                    "reply_hint": f"Quotation {qt_id} tidak ditemukan 🙏"}, False

        # ── Intercept: hapus item by index via safety net flag ────────────────
        if params.get("_hapus_item"):
            idx_1based = params.get("_idx", 0)
            items = list(found.get("items", []))
            if not idx_1based or idx_1based < 1 or idx_1based > len(items):
                items_list = "\n".join(
                    f"  {i+1}. {x.get('deskripsi', x.get('nama',''))}"
                    for i, x in enumerate(items)
                )
                return {"action": "update_qt", "status": "gagal", "reply_hint": (
                    f"❌ Nomor item {idx_1based} tidak ada di {qt_id} (total {len(items)} item).\n"
                    f"Items yang ada:\n{items_list} 🙏"
                )}, False
            removed = items.pop(idx_1based - 1)
            result = self.sm.update_qt(found["id"], {"items": items})
            if not result:
                return {"action": "update_qt", "status": "gagal",
                        "reply_hint": f"❌ Gagal menghapus item dari {qt_id} 🙏"}, False
            new_total = sum(int(x.get("jumlah", 0)) for x in items)
            items_preview = "\n".join(
                f"   {i+1}. {x.get('deskripsi', x.get('nama',''))} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                for i, x in enumerate(items)
            )
            return {"action": "update_qt", "status": "ok", "reply_hint": (
                f"✅ Item nomor {idx_1based} ({removed.get('deskripsi', removed.get('nama',''))}) "
                f"berhasil dihapus dari {found['id']}!\n\n"
                + (f"Items tersisa ({len(items)}):\n{items_preview}\n" if items else "⚠️ Tidak ada item tersisa.\n")
                + f"Total baru: Rp {new_total:,}\n\n"
                f"Mau generate ulang dokumen? Ketik 'generate PDF {found['id']}' 📄"
            )}, False

        # ── Intercept: tambah item baru via safety net flag ────────────────
        if params.get("_tambah_item"):
            nama_baru = params.get("_nama", "").strip()
            qty_baru  = params.get("_qty", 1) or 1
            harga_baru = params.get("_harga", 0)
            if not nama_baru:
                return {"action": "update_qt", "status": "butuh_nama",
                        "reply_hint": (
                            f"Sebutkan nama item yang mau ditambahkan ke {qt_id}\n"
                            f"Contoh: 'tambah item Monitor 2 unit Rp 5jt ke {qt_id}' 🙏"
                        )}, False
            items = list(found.get("items", []))
            new_item = {
                "deskripsi":      nama_baru,
                "qty":            qty_baru,
                "satuan":         "Unit",
                "harga_per_unit": harga_baru,
                "jumlah":         harga_baru * qty_baru,
            }
            items.append(new_item)
            result = self.sm.update_qt(found["id"], {"items": items})
            if not result:
                return {"action": "update_qt", "status": "gagal",
                        "reply_hint": f"❌ Gagal menambahkan item ke {qt_id} 🙏"}, False
            new_total = sum(int(x.get("jumlah", 0)) for x in items)
            items_preview = "\n".join(
                f"   {i+1}. {x.get('deskripsi', x.get('nama',''))} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                for i, x in enumerate(items)
            )
            return {"action": "update_qt", "status": "ok", "reply_hint": (
                f"✅ Item baru berhasil ditambahkan ke {found['id']}!\n\n"
                f"Item baru: {nama_baru} x{qty_baru} Unit = Rp {harga_baru * qty_baru:,}\n\n"
                f"Items terbaru ({len(items)}):\n{items_preview}\n"
                f"Total baru: Rp {new_total:,}\n\n"
                f"Mau generate ulang dokumen? Ketik 'generate PDF {found['id']}' 📄"
            )}, False

        # ── Intercept: edit item by index via chat ─────────────────────────
        # Deteksi pola: "ubah item nomor X jadi N unit" atau "ubah qty item N"
        _item_edit = re.search(
            r'(?:item|nomor)\s+(\d+).*?(?:jadi|menjadi|qty|=)\s*(\d+)\s*(?:unit|pcs|buah)?'
            r'|(?:jadi|menjadi)\s*(\d+)\s*(?:unit|pcs|buah).*?(?:item|nomor)\s*(\d+)',
            message, re.I
        )
        if _item_edit or "items" in updates:
            items = list(found.get("items", []))
            changed = False
            if _item_edit:
                # Ambil index dan qty dari regex
                g = _item_edit.groups()
                idx_1based = int(g[0] or g[3] or 0)
                new_qty    = int(g[1] or g[2] or 0)
                # Parse juga harga jika ada
                m_harga = re.search(r'(\d+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', message, re.I)
                new_harga = 0
                if m_harga:
                    v = float(m_harga.group(1).replace(',','.'))
                    mul = m_harga.group(2).lower()
                    new_harga = int(v*1_000_000) if mul in ('juta','jt') else int(v*1_000)
                if 1 <= idx_1based <= len(items):
                    item = dict(items[idx_1based - 1])
                    old_qty   = item.get("qty", 1)
                    old_harga = item.get("harga_per_unit", 0)
                    if new_qty:   item["qty"]           = new_qty
                    if new_harga: item["harga_per_unit"]= new_harga
                    item["jumlah"] = item.get("harga_per_unit", old_harga) * item.get("qty", old_qty)
                    items[idx_1based - 1] = item
                    changed = True
                    updates = {"items": items}
                    field_lines = (
                        f"  • Item {idx_1based} ({item.get('deskripsi',item.get('nama',''))}):\n"
                        f"    qty: {old_qty} → {item['qty']}\n"
                        f"    total: Rp {item['jumlah']:,}"
                    )
            if not changed:
                # Fallback: items dipass langsung dari params
                updates.pop("status", None)
                result = self.sm.update_qt(found["id"], updates)
                if not result:
                    return {"action": "update_qt", "status": "gagal",
                            "reply_hint": f"❌ Gagal update Quotation {qt_id} 🙏"}, False
                return {"action": "update_qt", "status": "ok",
                        "reply_hint": f"✅ Quotation {found['id']} berhasil diperbarui! 📄"}, False

            result = self.sm.update_qt(found["id"], {"items": items})
            if not result:
                return {"action": "update_qt", "status": "gagal",
                        "reply_hint": f"❌ Gagal update items Quotation {qt_id} 🙏"}, False
            new_total = sum(int(x.get("jumlah", 0)) for x in items)
            return {
                "action": "update_qt", "status": "ok",
                "reply_hint": (
                    f"✅ Quotation {found['id']} berhasil diperbarui!\n"
                    f"{field_lines}\n"
                    f"Total baru: Rp {new_total:,}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {found['id']}' 📄"
                )
            }, False

        # ── Normalize field aliases dari LLM ──────────────────────────────
        # LLM kadang return nama field yang berbeda dari yang disimpan di storage
        _qt_field_aliases = {
            "alamat_klien":   "klien_alamat",
            "alamat":         "klien_alamat",
            "klien_alamat":   "klien_alamat",
            "nama_klien":     "klien_nama",
            "klien":          "klien_nama",
            "klien_nama":     "klien_nama",
            "up":             "klien_up",
            "kontak":         "klien_up",
            "klien_up":       "klien_up",
            "perihal":        "re",
            "judul":          "re",
            "re":             "re",
            "catatan":        "note",
            "keterangan":     "note",
            "note":           "note",
            "tanggal":        "tanggal",
            "nomor":          "nomor",
            "ttd_nama":       "ttd_nama",
            "nama_ttd":       "ttd_nama",
            "ttd_hp":         "ttd_hp",
            "hp_ttd":         "ttd_hp",
            "telepon":        "ttd_hp",
        }
        updates = {_qt_field_aliases.get(k, k): v for k, v in updates.items()}

        # ── Field-level update (re, note, klien, ttd, dll) ────────────────
        # Jangan izinkan update status via update_qt — gunakan approve/reject
        updates.pop("status", None)

        result = self.sm.update_qt(found["id"], updates)
        if not result:
            return {"action": "update_qt", "status": "gagal",
                    "reply_hint": f"❌ Gagal update Quotation {qt_id} 🙏"}, False

        field_lines = "\n".join(f"  • {k}: {v}" for k, v in updates.items())
        return {
            "action": "update_qt", "status": "ok",
            "reply_hint": (
                f"✅ Quotation {found['id']} berhasil diperbarui!\n"
                f"Perubahan:\n{field_lines}\n\n"
                f"Mau generate ulang dokumen? Ketik 'generate PDF {found['id']}' 📄"
            )
        }, False

    # ── DELETE QT ─────────────────────────────────────────────────────────────
    def handle_delete_qt(self, session_id: str, params: dict):
        qt_id = params.get("id", "").strip().upper()

        if not qt_id:
            return {"action": "delete_qt", "status": "butuh_id",
                    "reply_hint": "ID Quotation mana yang mau dihapus? (contoh: QT-0001) 🙏"}, False

        found = self._find_qt(qt_id)
        if not found:
            return {"action": "delete_qt", "status": "tidak_ditemukan",
                    "reply_hint": f"Quotation {qt_id} tidak ditemukan 🙏"}, False

        # Minta konfirmasi
        import time as _t
        self.sess.set_pending_confirm(session_id, {
            "action":      "delete_qt_confirm",
            "id":          found["id"],
            "detail":      found,
            "_created_at": _t.time(),
        })
        return {
            "action": "delete_qt", "status": "butuh_konfirmasi",
            "reply_hint": (
                f"⚠️ Konfirmasi hapus {found['id']}?\n"
                f"  Nomor : {found.get('nomor','')}\n"
                f"  Klien : {found.get('klien_nama','')}\n"
                f"  Status: {found.get('status','').title()}\n\n"
                f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
            )
        }, False

    def handle_delete_qt_confirm(self, session_id: str, message: str, pending: dict):
        msg_up = message.strip().upper()
        if any(k in msg_up for k in ["BATAL", "CANCEL", "TIDAK", "GAK", "NO"]):
            self.sess.clear_pending_confirm(session_id)
            return {"reply": "❌ Penghapusan dibatalkan. 😊",
                    "skill_used": "quotation", "generated_file": None}
        if not any(k in msg_up for k in ["YA", "IYA", "YES", "OKE", "OK", "SETUJU", "YAP", "SIP"]):
            return {"reply": "Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏",
                    "skill_used": "quotation", "generated_file": None}

        qt_id = pending.get("id", "")
        result = self.sm.delete_qt(qt_id)
        self.sess.clear_pending_confirm(session_id)

        if not result:
            return {"reply": f"❌ Gagal hapus Quotation {qt_id} 🙏",
                    "skill_used": "quotation", "generated_file": None}
        return {"reply": f"✅ Quotation {qt_id} berhasil dihapus. 😊",
                "skill_used": "quotation", "generated_file": None}

    # ── APPROVE / REJECT ──────────────────────────────────────────────────────
    def handle_approve_qt(self, session_id: str, params: dict):
        return self._change_status(session_id, params, "accepted")

    def handle_reject_qt(self, session_id: str, params: dict):
        return self._change_status(session_id, params, "rejected")

    def _change_status(self, session_id: str, params: dict, new_status: str):
        qt_id = params.get("id", "").strip().upper()
        if not qt_id:
            label = "diterima" if new_status == "accepted" else "ditolak"
            return {"action": f"qt_status_{new_status}", "status": "butuh_id",
                    "reply_hint": f"ID Quotation mana yang mau di{label}? 🙏"}, False

        found = self._find_qt(qt_id)
        if not found:
            return {"action": f"qt_status_{new_status}", "status": "tidak_ditemukan",
                    "reply_hint": f"Quotation {qt_id} tidak ditemukan 🙏"}, False

        if found.get("status") in ("accepted", "rejected"):
            return {"action": f"qt_status_{new_status}", "status": "gagal",
                    "reply_hint": f"⚠️ Quotation {qt_id} sudah berstatus {found['status'].title()} — tidak bisa diubah lagi 🙏"}, False

        result = self.sm.update_qt(found["id"], {"status": new_status})
        if not result:
            return {"action": f"qt_status_{new_status}", "status": "gagal",
                    "reply_hint": f"❌ Gagal update status Quotation {qt_id} 🙏"}, False

        emoji = "✅" if new_status == "accepted" else "❌"
        label = "diterima klien" if new_status == "accepted" else "ditolak"
        suffix = (
            f"Mau convert ke Invoice? Ketik 'buat invoice dari {found['id']}' 💼"
            if new_status == "accepted" else "Ada yang bisa saya bantu lagi? 😊"
        )
        return {
            "action": f"qt_status_{new_status}", "status": "ok",
            "reply_hint": (
                f"{emoji} Quotation {found['id']} ({found.get('nomor','')}) "
                f"berhasil {label}!\n"
                f"Klien  : {found.get('klien_nama','')}\n"
                f"Re     : {found.get('re','')}\n\n"
                f"{suffix}"
            )
        }, False

    # ── GENERATE ──────────────────────────────────────────────────────────────
    def handle_generate_qt(self, session_id: str, params: dict, generator_module):
        """
        generator_module: import dari skills/quotation/quotation_generator.py
        Mengembalikan (result_dict, needs_confirm).
        """
        qt_id  = params.get("id", "").strip().upper()
        fmt    = params.get("format", "pdf").lower()

        if not qt_id:
            return {"action": "generate_qt", "status": "butuh_id",
                    "reply_hint": "ID Quotation mana yang mau digenerate? (contoh: QT-0001) 🙏"}, False

        found = self._find_qt(qt_id)
        if not found:
            return {"action": "generate_qt", "status": "tidak_ditemukan",
                    "reply_hint": f"Quotation {qt_id} tidak ditemukan 🙏"}, False

        try:
            if fmt == "excel":
                path = generator_module.generate_qt_excel(found)
            else:
                path = generator_module.generate_qt_pdf(found)
            fmt_label = "Excel" if fmt == "excel" else "PDF"
            return {
                "action": "generate_qt", "status": "ok",
                "reply_hint": f"📄 Dokumen Quotation {fmt_label} {found['id']} sudah siap, silakan klik link unduh di bawah.",
                "generated_file": path
            }, False
        except Exception as e:
            return {"action": "generate_qt", "status": "gagal",
                    "reply_hint": f"❌ Gagal generate dokumen: {e} 🙏"}, False

    # ── UTILS ─────────────────────────────────────────────────────────────────
    def _find_qt(self, qt_id: str):
        all_qt = self.sm.get_qt()
        return next(
            (x for x in all_qt
             if x.get("id","").upper() == qt_id
             or x.get("nomor","").upper() == qt_id),
            None
        )

    @staticmethod
    def _is_escape(message: str, pending: dict = None) -> bool:
        # Kalau user sedang mengisi note, jangan escape — apapun isinya
        if pending and pending.get("_asked_note") and not pending.get("_note_answered"):
            return False
        escape_kw = [
            "GENERATE", "BUATKAN", "LAPORAN", "HAPUS", "LIHAT", "TAMPILKAN",
            "APPROVE", "REJECT", "EDIT", "LIST", "CEK", "SALDO", "PR", "PO",
            "KASBON", "REIMBURSE", "PURCHASE", "EXPORT", "PDF", "EXCEL",
        ]
        msg_up    = message.strip().upper()
        msg_words = msg_up.split()
        return any(k in msg_words or msg_up.startswith(k) for k in escape_kw)


# ─── ITEM TEXT PARSER ─────────────────────────────────────────────────────────

def _parse_items_from_text(text: str) -> list:
    """
    Parse item dari teks bebas user. Mendukung:
      "Re-Editing Video, 1 Ls, Rp 200.000.000"
      "Konsultasi AI 3 hari @ Rp 5.000.000/hari"   → qty=3, per=5jt, total=15jt
      "3 video dengan harga per video 3 juta"        → qty=3, per=3jt, total=9jt
      "3 video @ 3 juta"                             → qty=3, per=3jt, total=9jt
      "2 pcs RAM seharga 3,5 juta per pcs"           → qty=2, per=3.5jt, total=7jt
      "Workshop 5 sesi Rp 2.500.000" (total)         → qty=5, per=500rb, total=2.5jt
    """
    items = []

    # ── Pre-normalisasi: pecah numbered list inline ──────────────────────────
    # Handle format: "35 juta. 2. High End PC" atau "35 juta. 2 High End PC"
    # Akhir harga: 3 digit berturutan (ribuan) ATAU kata juta/ribu/rb/jt
    # Nomor item berikutnya: 1-2 digit diikuti titik+spasi+kapital atau spasi+kapital
    text = re.sub(
        r'(?:(?<=\d{3})[.]\s+|(?<=juta)[.]\s+|(?<=juta)\s+|(?<=ribu)[.]\s+|(?<=ribu)\s+|(?<=jt)[.]\s+|(?<=jt)\s+)'
        r'(?=\d{1,2}[.)]\s*[A-Za-z]|\d{1,2}\s+[A-Z])',
        '\n', text, flags=re.I
    )

    lines = [l.strip() for l in re.split(r'\n|;', text) if l.strip()]
    lines = [re.sub(r'^\d+[.)]+\s*', '', l).strip() for l in lines if l.strip()]
    lines = [re.sub(r'^\d{1,2}\s+', '', l).strip() for l in lines if l.strip()]  # strip nomor tanpa titik

    def _to_rp(s: str) -> int:
        s = s.strip()
        m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(juta|jt)\b', s, re.I)
        if m:
            return int(float(m.group(1).replace(',', '.')) * 1_000_000)
        m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(ribu|rb)\b', s, re.I)
        if m:
            return int(float(m.group(1).replace(',', '.')) * 1_000)
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
        # Strip pola qty+satuan: "1 unit", "2 pcs", "3 hari", dll
        s = re.sub(r'\b\d+\s*(?:unit|pcs|buah|ls|set|box|hari|sesi|jam|bh|lbr)\b', '', s, flags=re.I)
        # Strip kata filler yang tersisa setelah harga/qty dihapus
        s = re.sub(r'\b(?:harga|per|dengan|dan|total|subtotal)\b', '', s, flags=re.I)
        s = re.sub(r'[@=,/]', ' ', s)
        return re.sub(r'\s+', ' ', s).strip().rstrip('- ') or "Item"

    for raw in lines:
        if not raw: continue

        # Normalisasi: "x1" → qty, filler words
        line = re.sub(r'\s+x(\d+)\b', r' \1 unit', raw, flags=re.I)  # "GPU x1" → "GPU 1 unit"
        line = re.sub(r'\b(dengan harga|seharga|senilai|sebesar)\b', ' ', line, flags=re.I)
        line = re.sub(r'\s+', ' ', line).strip()

        # ── STEP 1: Cari semua angka rupiah di baris ──
        rupiah_matches = list(re.finditer(
            r'(?:Rp\s*)?([\d]+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b|Rp\s*([\d.,]+)',
            line, re.I
        ))

        # ── STEP 2: Cari qty eksplisit — PRIORITAS: angka yang diikuti satuan baku ──
        # Satuan baku harus diikuti kata non-nama-produk (spasi, koma, harga, end)
        SATUAN_BAKU = r'(?:unit|pcs|buah|ls|set|box|hari|sesi|jam|bh|lbr|lembar|paket|lot)'
        qty_match = None
        qty_raw   = 1
        sat_raw   = "Unit"

        # Cari pola "N satuan" — qty diikuti satuan baku (paling reliable)
        sat_match = re.search(
            rf'(?<![.\d])(\d+)\s+({SATUAN_BAKU})\b',
            line, re.I
        )
        if sat_match:
            qty_raw = int(sat_match.group(1))
            sat_raw = sat_match.group(2).title()
            qty_match = sat_match  # pakai sebagai anchor posisi
        else:
            # Fallback: cari angka yang diikuti kata NON-nama-produk
            # Nama produk biasanya mengandung: huruf kapital, angka, slash, dash
            # Qty biasanya diikuti kata biasa (unit, pcs, dll atau kata keperluan)
            # Heuristik: ambil angka TERAKHIR sebelum kata "harga/per/unit/@"
            # bukan angka pertama yang bisa dari nama produk
            harga_anchor = re.search(
                r'\b(\d+)\s+(?:unit|pcs|buah|ls|set|box|hari|sesi|jam|bh|lbr|lembar|paket|lot|'
                r'dengan\s+harga|per\s+unit|per\s+pcs|per\s+buah|@)',
                line, re.I
            )
            if harga_anchor:
                qty_raw = int(harga_anchor.group(1))
                sat_raw = "Unit"
                qty_match = harga_anchor
            else:
                # Last resort: angka pertama di baris yang bukan bagian dari nama/kode produk
                # Skip angka yang diikuti huruf kapital langsung (kemungkinan kode produk)
                for m in re.finditer(r'(?<![.\d/])(\d+)(?!\s*[A-Z]{2,}|\s*\d)', line):
                    candidate = int(m.group(1))
                    if candidate <= 999:  # qty masuk akal max 999
                        qty_raw = candidate
                        qty_match = m
                        sat_raw = "Unit"
                        break

        # ── STEP 3: Cari harga per unit ──
        per_before = re.search(
            r'([\d]+(?:[.,]\d+)?\s*(?:juta|jt|ribu|rb|000)|Rp\s*[\d.,]+)\s+per\s+\w+',
            line, re.I
        )
        per_match = re.search(r'\bper\s+\w+\s+(.*)', line, re.I)
        at_match  = re.search(r'[@]\s*(.*)', line)

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

        # ── STEP 4: Bersihkan deskripsi ──
        if qty_match:
            if per_match:
                desc_raw = line[:per_match.start()].strip()
            elif at_match:
                desc_raw = line[:at_match.start()].strip()
            else:
                desc_raw = line
            desc = _clean(desc_raw)
        else:
            desc = _clean(line)

        # Bersihkan juga kata "denga" (typo dari "dengan") dari deskripsi
        desc = re.sub(r'\bdenga\b', '', desc, flags=re.I).strip()
        desc = re.sub(r'\s+', ' ', desc).strip() or "Item"

        items.append({
            "deskripsi":      desc,
            "qty":            qty_raw,
            "satuan":         sat_raw,
            "harga_per_unit": harga_per,
            "jumlah":         jumlah,
        })

    return items

# ─── STORAGE MANAGER METHODS YANG DIBUTUHKAN ─────────────────────────────────
# Tambahkan ke storage/manager.py:
#
# def add_qt(data: dict) -> dict | None:
#     """Simpan quotation baru. Return dict dengan 'id' yang diassign."""
#     ...
#
# def get_qt(status: str = "") -> list:
#     """Return list semua quotation, filter by status kalau ada."""
#     ...
#
# def get_qt_by_id(qt_id: str) -> dict | None:
#     """Return satu quotation by ID atau nomor."""
#     ...
#
# def update_qt(qt_id: str, updates: dict) -> dict | None:
#     """Update field quotation. Return updated dict atau None kalau gagal."""
#     ...
#
# def delete_qt(qt_id: str) -> bool:
#     """Hapus quotation. Return True kalau berhasil."""
#     ...
#
# Schema quotation di storage:
# {
#   "id":           "QT-0001",          # auto-assign
#   "nomor":        "05/HLMC-JP/VII/2026",
#   "klien_nama":   "PT Jakarta Propertindo",
#   "klien_alamat": "...",
#   "klien_up":     "Budi Santoso",     # opsional
#   "tanggal":      "14 Juli 2026",
#   "re":           "Re-Alignment Video Dome",
#   "items":        [...],              # list dict item
#   "note":         "Price valid 1 week",
#   "ttd_nama":     "",                 # opsional
#   "ttd_hp":       "",                 # opsional
#   "status":       "draft",            # draft | sent | accepted | rejected
#   "quotation_id": null,               # selalu null untuk QT (bukan Invoice)
#   "created_at":   "2026-07-14T10:00:00",
# }
