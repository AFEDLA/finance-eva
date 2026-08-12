"""
agent/core.py — Eva, Holomoc AI Finance Assistant
===================================================
Fork dari holomoc-agent-base, dikustomisasi untuk domain finance.
"""

import os
import re
import json
import base64
import mimetypes
import httpx
from pathlib import Path
from datetime import datetime
from .skill_loader import SkillLoader
from .session import SessionManager
from . import gemini_client
from . import hermes_client
from . import groq_client

# ─── CONFIG ───────────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH  = os.path.join(_PROJECT_ROOT, "config.json")
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        AGENT_CONFIG = json.load(f)
except Exception:
    AGENT_CONFIG = {}

AGENT_ID   = AGENT_CONFIG.get("agent_id",   "eva")
AGENT_NAME = AGENT_CONFIG.get("agent_name", "Eva")

# ─── LLM PROVIDER ─────────────────────────────────────────────────────────────
LLM_PROVIDER         = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_URL           = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL         = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_VISION_MODEL  = os.getenv("OLLAMA_VISION_MODEL", "llava:7b")
OLLAMA_RECEIPT_MODEL = os.getenv("OLLAMA_RECEIPT_MODEL", "qwen2.5vl:7b")

# ─── SKILLS DIR ───────────────────────────────────────────────────────────────
_default_skills_dir = os.path.join(_PROJECT_ROOT, "skills")
SKILLS_DIR = os.getenv("SKILLS_DIR", _default_skills_dir)
if not os.path.isabs(SKILLS_DIR):
    SKILLS_DIR = os.path.join(_PROJECT_ROOT, SKILLS_DIR)

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# ─── INTENT SYSTEM ────────────────────────────────────────────────────────────
INTENT_SYSTEM = """Kamu adalah classifier intent untuk Eva, Finance Assistant Holomoc Indonesia.
Analisa pesan user dan return HANYA JSON ini (tidak ada teks lain, tidak ada penjelasan):

{"intent": "<intent_code>", "params": {}}

INTENT CODES:
BACA    : list_finance, search_finance(keyword,jenis,status,nama), finance_summary, dashboard_keuangan
TAMBAH  : add_reimburse(nama,jumlah,keperluan,tanggal,project), add_kasbon(nama,jumlah,keperluan,tanggal,project)
APPROVAL: approve_finance(id), reject_finance(id)
EDIT    : update_finance(id,updates)
HAPUS   : delete_finance(id)
LAPORAN : generate_excel(jenis,bulan,tahun,status), generate_pdf(jenis,bulan,tahun,status)
SALDO   : set_saldo_awal(jumlah), cek_saldo()
PR      : add_pr(pemohon,proyek,keperluan,nomor,items,vendor,catatan), list_pr(status,pemohon,proyek), approve_pr(id), reject_pr(id), generate_pr(id,format), delete_pr(id), delete_all_pr, update_pr(id,updates), edit_pr_items(id,action,nama_item,qty,satuan,jumlah)
PO      : add_po(vendor_nama,vendor_alamat,vendor_attn,nomor,proyek,ref,items,pr_id,catatan), list_po(status), detail_po(id), approve_po(id), reject_po(id), generate_po(id,format), delete_po(id)
LAIN    : general_chat

PENTING: Selalu return intent code yang valid. Jangan return "LAIN" — gunakan "general_chat" untuk pesan yang tidak sesuai intent lain.

ATURAN EKSTRAK PARAMS:
- jumlah: angka integer, "Rp 75.000" → 75000, "75rb" → 75000, "1jt" → 1000000
- jenis: "reimburse" atau "kasbon"
- status: "pending", "approved", "rejected"
- bulan: integer 1-12, "Juni" → 6, "bulan ini" → bulan sekarang
- tahun: integer, "tahun ini" → tahun sekarang
- nama: string nama orang
- project: nama project kalau disebutkan eksplisit (mis. "Planetarium", "Kelapa Gading", "Padel"). Kalau TIDAK disebutkan, kosongkan string ("") — JANGAN mengisi sendiri

CONTOH:
user: "tampilkan semua reimburse"
→ {"intent":"list_finance","params":{"jenis":"reimburse"}}

user: "reimburse makan siang Rp 75.000 atas nama Fikri"
→ {"intent":"add_reimburse","params":{"nama":"Fikri","jumlah":75000,"keperluan":"makan siang"}}

user: "kasbon transport atas nama Defa 200rb"
→ {"intent":"add_kasbon","params":{"nama":"Defa","jumlah":200000,"keperluan":"transport"}}

user: "reimburse gojek meeting ke jakpro Rp 25.000 atas nama Fikri untuk project Planetarium"
→ {"intent":"add_reimburse","params":{"nama":"Fikri","jumlah":25000,"keperluan":"gojek meeting ke jakpro","project":"Planetarium"}}

user: "set saldo awal kas reimburse Rp 5.000.000"
→ {"intent":"set_saldo_awal","params":{"jumlah":5000000}}

user: "saldo kas sekarang 10jt"
→ {"intent":"set_saldo_awal","params":{"jumlah":10000000}}

user: "berapa sisa saldo kas kita?"
→ {"intent":"cek_saldo","params":{}}



user: "edit data reimburse dengan id FIN-0001 ubah nama menjadi Devon"
→ {"intent":"update_finance","params":{"id":"FIN-0001","updates":{"nama":"Devon"}}}

user: "edit data reimburse dengan id RMB-0002 ubah keperluan jadi Makan siang bersama EPSON"
→ {"intent":"update_finance","params":{"id":"RMB-0002","updates":{"keperluan":"Makan siang bersama EPSON"}}}

user: "edit data kasbon dengan id CAS-0001 ubah nama menjadi Budi"
→ {"intent":"update_finance","params":{"id":"CAS-0001","updates":{"nama":"Budi"}}}

user: "edit RMB-0001 ubah jumlah jadi 500rb"
→ {"intent":"update_finance","params":{"id":"RMB-0001","updates":{"jumlah":500000}}}

user: "edit data cashbon atas nama Jagger ubah nama menjadi Yeager"
→ {"intent":"update_finance","params":{"id":"","updates":{"nama":"Yeager"}}}

user: "edit data cashbon dengan id FIN-0002 ubah nama menjadi Yeager"
→ {"intent":"update_finance","params":{"id":"FIN-0002","updates":{"nama":"Yeager"}}}

user: "edit nama menjadi Rio"
→ {"intent":"update_finance","params":{"id":"","updates":{"nama":"Rio"}}}

user: "ganti nama jadi Rio"
→ {"intent":"update_finance","params":{"id":"","updates":{"nama":"Rio"}}}



user: "edit jumlah menjadi 800rb"
→ {"intent":"update_finance","params":{"id":"","updates":{"jumlah":800000}}}

user: "edit nama menjadi Rio"
→ {"intent":"update_finance","params":{"id":"","updates":{"nama":"Rio"}}}

user: "ganti nama jadi Rio"
→ {"intent":"update_finance","params":{"id":"","updates":{"nama":"Rio"}}}

user: "ganti nama reimburse FIN-0002 jadi Budi"
→ {"intent":"update_finance","params":{"id":"FIN-0002","updates":{"nama":"Budi"}}}

user: "ubah keperluan FIN-0003 jadi transport"
→ {"intent":"update_finance","params":{"id":"FIN-0003","updates":{"keperluan":"transport"}}}

user: "edit keperluan kasbon menjadi beli material"
→ {"intent":"update_finance","params":{"id":"","updates":{"keperluan":"beli material"}}}

user: "sisa kas reimburse masih berapa"
→ {"intent":"cek_saldo","params":{}}

user: "approve FIN-0001"
→ {"intent":"approve_finance","params":{"id":"FIN-0001"}}

user: "approve RMB-0001"
→ {"intent":"approve_finance","params":{"id":"RMB-0001"}}

user: "approve CAS-0002"
→ {"intent":"approve_finance","params":{"id":"CAS-0002"}}

user: "approve status reimburse atas nama Defa"
→ {"intent":"approve_finance","params":{"id":"","nama":"Defa","jenis":"reimburse"}}

user: "approve reimburse Fikri"
→ {"intent":"approve_finance","params":{"id":"","nama":"Fikri","jenis":"reimburse"}}

user: "setujui kasbon atas nama Nizam"
→ {"intent":"approve_finance","params":{"id":"","nama":"Nizam","jenis":"kasbon"}}

user: "tolak reimburse FIN-0002"
→ {"intent":"reject_finance","params":{"id":"FIN-0002"}}

user: "tolak kasbon atas nama Fikri"
→ {"intent":"reject_finance","params":{"id":"","nama":"Fikri","jenis":"kasbon"}}

user: "reject reimburse Defa"
→ {"intent":"reject_finance","params":{"id":"","nama":"Defa","jenis":"reimburse"}}

user: "laporan keuangan bulan Juni 2026"
→ {"intent":"generate_excel","params":{"bulan":6,"tahun":2026}}

user: "laporan reimburse yang sudah approved bulan ini"
→ {"intent":"generate_excel","params":{"jenis":"reimburse","status":"approved","bulan":0,"tahun":0}}

user: "dashboard keuangan bulan ini"
→ {"intent":"dashboard_keuangan","params":{}}

user: "cari reimburse atas nama Nizam"
→ {"intent":"search_finance","params":{"nama":"Nizam","jenis":"reimburse"}}

user: "cek status FIN-0001" atau "tampilkan detail FIN-0001" atau "cek FIN-0001"
→ {"intent":"search_finance","params":{"id":"FIN-0001"}}

user: "cek status pengajuan reimburse ID FIN-0001 atas nama Devon dan tampilkan detailnya"
→ {"intent":"search_finance","params":{"id":"FIN-0001","nama":"Devon","jenis":"reimburse"}}

user: "cek status pengajuan kasbon ID FIN-0002 atas nama Yeager dan tampilkan detailnya"
→ {"intent":"search_finance","params":{"id":"FIN-0002","nama":"Yeager","jenis":"kasbon"}}

user: "yang masih pending"
→ {"intent":"list_finance","params":{"status":"pending"}}

TYPO HANDLING:
- "casbon", "kasbon" → kasbon
- "remburse", "reemburse" → reimburse

ATURAN KRITIS — PR EDIT:
- "edit/ubah/ganti [field] PR" → update_pr (field: pemohon, proyek, keperluan, nomor)
- "hapus item [nama] dari PR" atau "tambah item [nama] ke PR" → edit_pr_items
- JANGAN return edit_pr_items untuk ubah pemohon/proyek/keperluan/nomor — itu update_pr
- id bisa berupa PR-XXXX atau nomor dokumen lengkap PR/xxx/yyy/...
- Untuk tampilkan/lihat/detail PR → selalu gunakan list_pr, JANGAN view_pr atau detail_pr
- Field pemohon di PR adalah "pemohon", BUKAN "nama" — selalu gunakan key "pemohon"

CONTOH PR:
user: "buat purchase request untuk pembelian GPU, pemohon Rahmad, proyek AI Finance"
→ {"intent":"add_pr","params":{"pemohon":"Rahmad","proyek":"AI Finance","keperluan":"pembelian GPU","items":[]}}

user: "tampilkan semua PR" atau "list purchase request"
→ {"intent":"list_pr","params":{}}

user: "PR yang pending"
→ {"intent":"list_pr","params":{"status":"pending"}}

user: "tampilkan detail PR-0002"
→ {"intent":"list_pr","params":{"id":"PR-0002"}}

user: "tampilkan detail purchase request PR-0002 dengan nomor PR/Hardware/003/VII/2026"
→ {"intent":"list_pr","params":{"id":"PR-0002"}}

user: "lihat PR atas nama Aldefa"
→ {"intent":"list_pr","params":{"pemohon":"Aldefa"}}

user: "approve PR-0001" atau "setujui PR-0001"
→ {"intent":"approve_pr","params":{"id":"PR-0001"}}

user: "approved status pr dengan nomor pr : PR/Hardware/003/VII/2026"
→ {"intent":"approve_pr","params":{"id":"PR/Hardware/003/VII/2026"}}

user: "setujui PR/Hardware/003/VII/2026"
→ {"intent":"approve_pr","params":{"id":"PR/Hardware/003/VII/2026"}}

user: "tolak PR-0001" atau "reject PR-0001"
→ {"intent":"reject_pr","params":{"id":"PR-0001"}}

user: "reject PR/Hardware/003/VII/2026"
→ {"intent":"reject_pr","params":{"id":"PR/Hardware/003/VII/2026"}}

user: "generate PDF PR-0001" atau "buat dokumen PR-0001"
→ {"intent":"generate_pr","params":{"id":"PR-0001","format":"pdf"}}

user: "download word PR-0001" atau "buat docx PR-0001" atau "generate word PR-0001" atau "tolong generate word PR dengan ID PR-0001" atau "generate PR dalam format word"
→ {"intent":"generate_pr","params":{"id":"PR-0001","format":"docx"}}

user: "PR-0001" (saat konteks sedang generate dokumen)
→ {"intent":"generate_pr","params":{"id":"PR-0001","format":"pdf"}}

user: "buat PO dari PR-0003" atau "buat purchase order dari PR yang approved"
→ {"intent":"add_po","params":{"pr_id":"PR-0003"}}

user: "buat PO untuk PT Sinar Elektronika, nomor PO/VII/2026/OPR/001"
→ {"intent":"add_po","params":{"vendor_nama":"PT Sinar Elektronika","nomor":"PO/VII/2026/OPR/001"}}

user: "list PO" atau "tampilkan semua purchase order"
→ {"intent":"list_po","params":{"status":""}}

user: "tampilkan PO-0001" atau "detail PO-0001"
→ {"intent":"detail_po","params":{"id":"PO-0001"}}

user: "approve PO-0001" atau "setujui PO-0001"
→ {"intent":"approve_po","params":{"id":"PO-0001"}}

user: "reject PO-0001" atau "tolak PO-0001"
→ {"intent":"reject_po","params":{"id":"PO-0001"}}

user: "generate PO-0001" atau "download PO-0001" atau "buat dokumen PO-0001" atau "buat word PO-0001"
→ {"intent":"generate_po","params":{"id":"PO-0001","format":"docx"}}

user: "generate PDF PO-0001" atau "cetak PDF PO-0001"
→ {"intent":"generate_po","params":{"id":"PO-0001","format":"pdf"}}

user: "generate word PO-0001" atau "buat docx PO-0001"
→ {"intent":"generate_po","params":{"id":"PO-0001","format":"docx"}}

user: "hapus PO-0001" atau "delete PO-0001"
→ {"intent":"delete_po","params":{"id":"PO-0001"}}

user: "hapus PR-0001"
→ {"intent":"delete_pr","params":{"id":"PR-0001"}}

user: "hapus semua PR" atau "hapus semua data PR" atau "clear all PR"
→ {"intent":"delete_all_pr","params":{}}

QT      : add_qt(klien_nama,klien_alamat,klien_up,nomor,tanggal,re,items,note,ttd_nama,ttd_hp), list_qt(status,klien,id), update_qt(id,updates), delete_qt(id), generate_qt(id,format), approve_qt(id), reject_qt(id)

CONTOH QT:
user: "buat quotation" atau "surat penawaran" atau "buat QT" atau "penawaran harga"
→ {"intent":"add_qt","params":{}}

user: "buat quotation untuk PT Jakarta Propertindo"
→ {"intent":"add_qt","params":{"klien_nama":"PT Jakarta Propertindo"}}

user: "list quotation" atau "tampilkan semua QT"
→ {"intent":"list_qt","params":{}}

user: "QT yang accepted" atau "quotation yang diterima"
→ {"intent":"list_qt","params":{"status":"accepted"}}

user: "tampilkan QT-0001" atau "detail QT-0001"
→ {"intent":"list_qt","params":{"id":"QT-0001"}}

user: "tampilkan quotation 05/HLMC-JP/IV/2026"
→ {"intent":"list_qt","params":{"id":"05/HLMC-JP/IV/2026"}}

user: "generate PDF QT-0001" atau "download quotation QT-0001"
→ {"intent":"generate_qt","params":{"id":"QT-0001","format":"pdf"}}

user: "generate excel QT-0001" atau "download excel QT-0001"
→ {"intent":"generate_qt","params":{"id":"QT-0001","format":"excel"}}

user: "accepted QT-0001" atau "quotation diterima QT-0001" atau "setujui QT-0001"
→ {"intent":"approve_qt","params":{"id":"QT-0001"}}

user: "reject QT-0001" atau "tolak quotation QT-0001"
→ {"intent":"reject_qt","params":{"id":"QT-0001"}}

user: "hapus QT-0001" atau "delete QT-0001"
→ {"intent":"delete_qt","params":{"id":"QT-0001"}}

user: "edit re QT-0001 jadi Re-Alignment Video Dome"
→ {"intent":"update_qt","params":{"id":"QT-0001","updates":{"re":"Re-Alignment Video Dome"}}}

user: "ubah alamat klien QT-0001 jadi Jl. Sudirman No.1 Jakarta"
→ {"intent":"update_qt","params":{"id":"QT-0001","updates":{"klien_alamat":"Jl. Sudirman No.1 Jakarta"}}}

user: "ubah nama klien QT-0002 jadi PT Maju Jaya"
→ {"intent":"update_qt","params":{"id":"QT-0002","updates":{"klien_nama":"PT Maju Jaya"}}}

user: "ubah note QT-0001 jadi Price is valid for 2 weeks"
→ {"intent":"update_qt","params":{"id":"QT-0001","updates":{"note":"Price is valid for 2 weeks"}}}

user: "edit quotation QT-0004 ubah item nomor 2 jadi 3 unit"
→ {"intent":"update_qt","params":{"id":"QT-0004","updates":{}}}

user: "QT-0002 item nomor 1 ubah qty jadi 5"
→ {"intent":"update_qt","params":{"id":"QT-0002","updates":{}}}

INV     : add_inv(klien_nama,klien_alamat,nomor,tanggal,project_name,items,ttd_nama,ttd_jabatan,bank_nama,bank_rekening,bank_cabang,bank_atas_nama,quotation_id), list_inv(status,klien,id), update_inv(id,updates), delete_inv(id), generate_inv(id,format), mark_paid(id), mark_issued(id)

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

user: "generate PDF INV-0001"
→ {"intent":"generate_inv","params":{"id":"INV-0001","format":"pdf"}}

user: "generate excel INV-0001"
→ {"intent":"generate_inv","params":{"id":"INV-0001","format":"excel"}}

user: "INV-0001 sudah dibayar" atau "mark paid INV-0001"
→ {"intent":"mark_paid","params":{"id":"INV-0001"}}

user: "issue INV-0001" atau "terbitkan invoice INV-0001"
→ {"intent":"mark_issued","params":{"id":"INV-0001"}}

user: "hapus INV-0001"
→ {"intent":"delete_inv","params":{"id":"INV-0001"}}

user: "edit project INV-0001 jadi Padel VR Simulator"
→ {"intent":"update_inv","params":{"id":"INV-0001","updates":{"project_name":"Padel VR Simulator"}}}

user: "bagaimana format PR?" atau "cara buat PR" atau "contoh purchase request" atau "format purchase request"
→ {"intent":"add_pr","params":{}}

user: "saya mau buat PR" atau "tolong buatkan PR" atau "bantu buat purchase request"
→ {"intent":"add_pr","params":{}}

user: "edit pr PR-0001 ganti pemohon jadi Budi"
→ {"intent":"update_pr","params":{"id":"PR-0001","updates":{"pemohon":"Budi"}}}

user: "edit data pr dengan nomor PR/Hardware/003/VII/2026 ubah nama pemohon menjadi Eren Yeager"
→ {"intent":"update_pr","params":{"id":"PR/Hardware/003/VII/2026","updates":{"pemohon":"Eren Yeager"}}}

user: "edit data pr dengan id PR-0003 ubah nama menjadi Eren Yeager"
→ {"intent":"update_pr","params":{"id":"PR-0003","updates":{"pemohon":"Eren Yeager"}}}

user: "ubah proyek pr PR-0002 menjadi Sphere Jakarta"
→ {"intent":"update_pr","params":{"id":"PR-0002","updates":{"proyek":"Sphere Jakarta"}}}

user: "ganti proyek PR/Hardware/003/VII/2026 jadi Sphere Jakarta"
→ {"intent":"update_pr","params":{"id":"PR/Hardware/003/VII/2026","updates":{"proyek":"Sphere Jakarta"}}}

user: "ubah keperluan PR-0001 jadi Pembelian ATK"
→ {"intent":"update_pr","params":{"id":"PR-0001","updates":{"keperluan":"Pembelian ATK"}}}

user: "edit nomor PR-0002 menjadi PR/Hardware/005/VII/2026"
→ {"intent":"update_pr","params":{"id":"PR-0002","updates":{"nomor":"PR/Hardware/005/VII/2026"}}}

user: "hapus item High end PC dari PR-0002"
→ {"intent":"edit_pr_items","params":{"id":"PR-0002","action":"hapus","nama_item":"High end PC"}}

user: "edit pr PR-0002 hapus item High end PC"
→ {"intent":"edit_pr_items","params":{"id":"PR-0002","action":"hapus","nama_item":"High end PC"}}

user: "edit data pr dengan id PR-0002 hapus High end PC x5 Unit = Rp 175,000,000"
→ {"intent":"edit_pr_items","params":{"id":"PR-0002","action":"hapus","nama_item":"High end PC"}}

user: "hapus item RPLidar dari PR-0001"
→ {"intent":"edit_pr_items","params":{"id":"PR-0001","action":"hapus","nama_item":"RPLidar"}}

user: "tambah item ke PR-0002: Monitor x2 Unit harga Rp 5000000"
→ {"intent":"edit_pr_items","params":{"id":"PR-0002","action":"tambah","nama_item":"Monitor","qty":2,"satuan":"Unit","harga_per_unit":5000000,"jumlah":10000000}}

user: "edit pr dengan nomor PR/Hardware/003/VII/2026 tambah item baru Brightsign Media Player Controller 5 unit dengan harga per unit 23 juta"
→ {"intent":"edit_pr_items","params":{"id":"PR/Hardware/003/VII/2026","action":"tambah","nama_item":"Brightsign Media Player Controller","qty":5,"satuan":"Unit","harga_per_unit":23000000,"jumlah":115000000}}

HANYA return JSON. Tidak ada teks lain."""


class Agent:
    def __init__(self):
        self.skill_loader    = SkillLoader(SKILLS_DIR)
        self.session_manager = SessionManager()
        self.skills          = self.skill_loader.load_all()
        self._pending_file_bytes = None
        print(f"[{AGENT_NAME}] Loaded skills : {list(self.skills.keys())}")
        print(f"[{AGENT_NAME}] Agent ID       : {AGENT_ID}")
        print(f"[{AGENT_NAME}] LLM Provider   : {LLM_PROVIDER}")
        self._init_storage()

    def _init_storage(self):
        try:
            import sys
            sys.path.insert(0, _PROJECT_ROOT)
            import storage.manager as sm
            self.sm = sm
            print(f"[{AGENT_NAME}] ✅ Storage: {sm.get_storage_summary()['storage_path']}")
        except Exception as e:
            print(f"[{AGENT_NAME}] ⚠️ Storage error: {e}")
            self.sm = None

        # Quotation handler & generator
        try:
            from skills.quotation.quotation_core import QuotationHandler
            from skills.quotation import quotation_generator as _qt_gen
            self._qt_handler = QuotationHandler(self)
            self._qt_gen     = _qt_gen
            print(f"[{AGENT_NAME}] ✅ Quotation handler loaded")
        except Exception as e:
            print(f"[{AGENT_NAME}] ⚠️ Quotation handler error: {e}")
            self._qt_handler = None
            self._qt_gen     = None

        # Invoice handler & generator
        try:
            from agent.invoice_core import InvoiceHandler
            self._inv_handler = InvoiceHandler(self)
            print(f"[{AGENT_NAME}] ✅ Invoice handler loaded")
        except Exception as e:
            print(f"[{AGENT_NAME}] ⚠️ Invoice handler error: {e}")
            self._inv_handler = None

        # Budget & Expense handler
        try:
            from agent.budget_core import BudgetHandler
            # Coba inisialisasi dengan agent (kompatibel versi lama)
            # Jika gagal, coba tanpa argument
            try:
                self._bud_handler = BudgetHandler(self)
            except TypeError:
                self._bud_handler = BudgetHandler()
            print(f"[{AGENT_NAME}] ✅ Budget handler loaded")
        except Exception as e:
            print(f"[{AGENT_NAME}] ⚠️ Budget handler error: {e}")
            self._bud_handler = None


    def list_skills(self):
        return list(self.skills.keys())

    def clear_session(self, session_id: str):
        self.session_manager.clear(session_id)

    async def chat(self, session_id: str, message: str) -> dict:
        # ── EARLY INTERCEPT: Detail Finance (RMB/CAS/FIN) ────────────────────
        # Kalau pesan mengandung ID finance + kata cek/detail/status,
        # langsung ambil dari storage dan return — BYPASS LLM sepenuhnya.
        # Ini fix permanen untuk halusinasi EVA saat menampilkan data finance.
        if self.sm:
            _early_id_m = re.search(r'\b((?:RMB|CAS|FIN)-\d+)\b', message, re.IGNORECASE)
            _early_cek  = re.search(r'\b(cek|tampilkan|detail|status|lihat|info|show|check|display)\b', message, re.IGNORECASE)
            _no_pr_po   = not re.search(r'\b(PR-|PO-|QT-)\d+\b', message, re.IGNORECASE)
            if _early_id_m and _early_cek and _no_pr_po:
                _eid = _early_id_m.group(1).upper()
                _all = self.sm.get_finance()
                _target = next((x for x in _all if x.get("id","").upper() == _eid), None)
                if _target:
                    _st      = _target.get("status", "pending")
                    _st_icon = "✅" if _st == "approved" else "❌" if _st == "rejected" else "🕒"
                    _jenis   = _target.get("jenis", "").title()
                    _reply   = (
                        f"📋 Detail {_jenis} {_eid}:\n"
                        f"- Nama      : {_target.get('nama', '-')}\n"
                        f"- Keperluan : {_target.get('keperluan', '-') or '-'}\n"
                        f"- Jumlah    : Rp {int(_target.get('jumlah', 0)):,}\n"
                        f"- Tanggal   : {_target.get('tanggal', '-')}\n"
                        f"- Project   : {_target.get('project', '-') or '-'}\n"
                        f"- Status    : {_st_icon} {_st.title()}\n"
                        + (f"- Approved oleh: {_target.get('approved_by')}\n" if _target.get("approved_by") else "")
                        + "\nAda yang bisa saya bantu lagi? 😊"
                    )
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", _reply)
                    print(f"[{AGENT_NAME}] EARLY INTERCEPT finance detail: {_eid} status={_st}")
                    return {"reply": _reply, "skill_used": "finance", "generated_file": None}
                else:
                    # Data tidak ditemukan — return eksplisit agar LLM tidak halusinasi
                    # dari history percakapan yang masih menyebut ID ini
                    _reply = f"❌ Data **{_eid}** tidak ditemukan di sistem. Data mungkin sudah dihapus atau ID tidak valid."
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", _reply)
                    print(f"[{AGENT_NAME}] EARLY INTERCEPT finance: {_eid} NOT FOUND")
                    return {"reply": _reply, "skill_used": "finance", "generated_file": None}
        if self.sm:
            _inv_id_m = re.search(r'\b(INV-\d{4})\b', message, re.IGNORECASE)
            _inv_cek  = re.search(r'\b(cek|tampilkan|detail|status|lihat|info|show|check|berapa|invoice|faktur)\b', message, re.IGNORECASE)
            if _inv_id_m and _inv_cek:
                _iid = _inv_id_m.group(1).upper()
                try:
                    _inv_target = self.sm.get_inv_by_id(_iid)
                    if _inv_target:
                        _items = _inv_target.get("items", [])
                        _total = sum(int(x.get("total", x.get("jumlah", 0))) for x in _items)
                        _st    = _inv_target.get("status", "draft")
                        _qt_ref = f"\nDari QT  : {_inv_target['quotation_id']}" if _inv_target.get("quotation_id") else ""
                        _inv_reply = (
                            f"🧾 {_inv_target['id']} — {_inv_target.get('nomor','')}"
                            f"\nStatus   : {_st.title()}"
                            f"\nKlien    : {_inv_target.get('klien_nama','')}"
                            f"\nTanggal  : {_inv_target.get('tanggal','')}"
                            f"\nProject  : {_inv_target.get('project_name','')}"
                            f"\nItems    : {len(_items)} item"
                            f"\nTotal    : Rp {_total:,}"
                            + _qt_ref
                        )
                        self.session_manager.add_message(session_id, "user", message)
                        self.session_manager.add_message(session_id, "assistant", _inv_reply)
                        print(f"[{AGENT_NAME}] EARLY INTERCEPT invoice detail: {_iid} status={_st}")
                        return {"reply": _inv_reply, "skill_used": "invoice", "generated_file": None}
                except Exception:
                    pass  # fallback ke LLM normal

        # Cek pending konfirmasi (max 15 menit)
        # Timeout sengaja diperpanjang ke 15 menit karena PR flow multi-step
        # bisa butuh waktu (user perlu menyiapkan daftar items, nomor dokumen, dll).
        pending = self.session_manager.get_pending_confirm(session_id)
        if pending:
            import time
            if time.time() - pending.get("_created_at", 0) > 900:
                self.session_manager.clear_pending_confirm(session_id)
                self._pending_file_bytes = None
                pending = None
            # batch_edit_confirm tidak lagi digunakan (direct execute)
            # clear jika ada stale dari versi sebelumnya
            elif pending.get("action") == "batch_edit_confirm":
                print(f"[{AGENT_NAME}] Clear stale batch_edit_confirm pending")
                self.session_manager.clear_pending_confirm(session_id)
                pending = None

        if pending:
            # Cek apakah pesan adalah jawaban konfirmasi atau perintah baru
            # Kalau perintah baru (ada intent PR/finance), clear pending dulu
            _msg_up = message.upper().strip()
            _is_confirm_answer = bool(re.search(
                r'(?:^|\s)(ya|iya|yes|oke|ok|setuju|yap|sip|betul|benar|batal|cancel|tidak|gak|no|tidak\s+jadi)(?:\s|$)',
                message, re.IGNORECASE
            )) and len(message.strip().split()) <= 5  # jawaban konfirmasi biasanya pendek

            _is_new_command = bool(re.search(
                r'\b(tampilkan|edit|ubah|hapus|tambah|generate|buat|list|detail|approve|reject)\b',
                message, re.IGNORECASE
            )) and not _is_confirm_answer

            # Jangan clear pending untuk multi-step collect flows (QT, PR, PO)
            _multi_step_actions = {
                "add_qt_collect", "add_qt_confirm", "delete_qt_confirm",
                "add_pr_collect", "add_po_collect",
                "add_inv_collect", "add_inv_confirm", "delete_inv_confirm",
                # Budget multi-step flows
                "add_budget_project", "add_budget_ops", "link_expense", "delete_budget",
            }
            _is_multi_step = pending.get("action", "") in _multi_step_actions

            if _is_new_command and not _is_multi_step:
                print(f"[{AGENT_NAME}] Clear stale pending ({pending.get('action','')}) — new command detected")
                self.session_manager.clear_pending_confirm(session_id)
                pending = None

        if pending:
            result = await self._handle_confirm(session_id, message, pending)
            if result is not None:
                return result

        # Classify intent
        intent_data = await self._classify_intent(message)
        intent = intent_data.get("intent", "general_chat")
        # Normalize intent yang tidak valid → general_chat
        if intent.upper() in ("LAIN", "OTHER", "NONE", "NULL", ""):
            intent = "general_chat"
        params = intent_data.get("params", {})

        # Safety net: approve/reject jangan jadi delete atau search
        approve_keywords = r"\b(approve|setujui|acc|tolak|reject)\b"
        if re.search(approve_keywords, message, re.IGNORECASE) and            intent in ("delete_finance", "search_finance", "list_finance", "general_chat"):
            is_approve = bool(re.search(r"\b(approve|setujui|acc)\b", message, re.IGNORECASE))
            # Cek apakah ada PR ID → harusnya approve/reject PR, bukan finance
            pr_id_in_msg = re.search(r"\bPR[-/]\d+\b", message, re.IGNORECASE)
            if pr_id_in_msg:
                intent = "approve_pr" if is_approve else "reject_pr"
                params = {"id": pr_id_in_msg.group(0).upper()}
                print(f"[{AGENT_NAME}] Safety net approve PR: {intent} id={params['id']}")
            else:
                intent = "approve_finance" if is_approve else "reject_finance"
            # Coba ekstrak nama dari pesan
            nama_match = re.search(r"(?:atas nama|nama)\s+([A-Za-z]+)", message, re.IGNORECASE)
            nama = nama_match.group(1) if nama_match else params.get("nama", "")
            jenis_match = re.search(r"\b(reimburse|kasbon|cashbon)\b", message, re.IGNORECASE)
            jenis = jenis_match.group(1).lower() if jenis_match else ""
            # Ekstrak FIN/RMB/CAS ID dari pesan kalau ada
            fin_id_match = re.search(r'\b((?:FIN|RMB|CAS)-\d+)\b', message, re.IGNORECASE)
            fin_id_from_msg = fin_id_match.group(1).upper() if fin_id_match else params.get("id", "")
            params = {"id": fin_id_from_msg, "nama": nama, "jenis": jenis}
            print(f"[{AGENT_NAME}] Safety net approve: {intent} nama={nama}")

        print(f"[{AGENT_NAME}] Intent: {intent} | Params: {params}")

        # Normalize intent alias yang LLM kadang return
        INTENT_ALIASES = {
            "view_pr": "list_pr",
            "detail_pr": "list_pr",
            "show_pr": "list_pr",
            "get_pr": "list_pr",
            "view_finance": "list_finance",
            "detail_finance": "list_finance",
            # Alias approve/reject — LLM kadang return varian berbeda
            "approve_purchase_request": "approve_pr",
            # PO aliases
            "buat_po":         "add_po",
            "create_po":       "add_po",
            "tambah_po":       "add_po",
            "edit_po_items":   "batch_edit_po_items",
            "update_po_items": "batch_edit_po_items",
            "edit_po":         "batch_edit_po_items",
            "ubah_po_items":   "batch_edit_po_items",
            "list_purchase_order": "list_po",
            "view_po":         "detail_po",
            "show_po":         "detail_po",
            "get_po":          "detail_po",
            "approve_purchase_order": "approve_po",
            "reject_purchase_order":  "reject_po",
            "generate_purchase_order": "generate_po",
            "download_po":       "generate_po",
            "hapus_po":          "delete_po",
            # LLM kadang return varian intent PO yang tidak standard
            "create_po_from_pr": "add_po",
            "create_po":         "add_po",
            "make_po":           "add_po",
            "new_po":            "add_po",
            "po_from_pr":        "add_po",
            "generate_po_doc":   "generate_po",
            "po_detail":         "detail_po",
            "view_po":           "detail_po",
            "reject_purchase_request":  "reject_pr",
            "pr_approve":               "approve_pr",
            "pr_reject":                "reject_pr",
            # Finance edit aliases — LLM sering return varian ini alih-alih update_finance
            "update_reimburse":         "update_finance",
            "edit_reimburse":           "update_finance",
            "ubah_reimburse":           "update_finance",
            "update_kasbon":            "update_finance",
            "edit_kasbon":              "update_finance",
            "ubah_kasbon":              "update_finance",
            "edit_finance":             "update_finance",
            "ubah_finance":             "update_finance",
            # Finance delete aliases
            "hapus_finance":            "delete_finance",
            "hapus_reimburse":          "delete_finance",
            "hapus_kasbon":             "delete_finance",
            "delete_reimburse":         "delete_finance",
            "delete_kasbon":            "delete_finance",
            "remove_finance":           "delete_finance",
            "remove_reimburse":         "delete_finance",
            # Quotation aliases
            "add_quotation":            "add_qt",
            "create_qt":                "add_qt",
            "buat_qt":                  "add_qt",
            "new_qt":                   "add_qt",
            "list_quotation":           "list_qt",
            "view_qt":                  "list_qt",
            "detail_qt":                "list_qt",
            "show_qt":                  "list_qt",
            "generate_quotation":       "generate_qt",
            "download_qt":              "generate_qt",
            "accept_qt":                "approve_qt",
            "accepted_qt":              "approve_qt",
            "rejected_qt":              "reject_qt",
            "hapus_qt":                 "delete_qt",
            "update_quotation":         "update_qt",
            "edit_qt":                  "update_qt",
            # Invoice aliases
            "add_invoice":              "add_inv",
            "create_inv":               "add_inv",
            "buat_invoice":             "add_inv",
            "new_inv":                  "add_inv",
            "create_invoice":           "add_inv",
            "create_inv_from_quote":    "add_inv",
            "create_inv_from_qt":       "add_inv",
            "create_invoice_from_qt":   "add_inv",
            "add_inv_from_qt":          "add_inv",
            "invoice_from_quotation":   "add_inv",
            "inv_from_qt":              "add_inv",
            "buat_inv_dari_qt":         "add_inv",
            "list_invoice":             "list_inv",
            "view_inv":                 "list_inv",
            "detail_inv":               "list_inv",
            "show_inv":                 "list_inv",
            "generate_invoice":         "generate_inv",
            "download_inv":             "generate_inv",
            "download_invoice":         "generate_inv",
            "paid_inv":                 "mark_paid",
            "invoice_paid":             "mark_paid",
            "bayar_inv":                "mark_paid",
            "lunas_inv":                "mark_paid",
            "issue_inv":                "mark_issued",
            "issued_inv":               "mark_issued",
            "send_inv":                 "mark_issued",
            "kirim_invoice":            "mark_issued",
            "hapus_inv":                "delete_inv",
            "delete_invoice":           "delete_inv",
            "update_invoice":           "update_inv",
            "edit_inv":                 "update_inv",
            "edit_invoice":             "update_inv",
            # Budget aliases
            "buat_budget_proyek":       "add_budget_project",
            "tambah_budget_proyek":     "add_budget_project",
            "create_budget_project":    "add_budget_project",
            "buat_budget_ops":          "add_budget_ops",
            "tambah_budget_ops":        "add_budget_ops",
            "set_budget_ops":           "add_budget_ops",
            "buat_budget_operasional":  "add_budget_ops",
            "override_budget":          "override_budget_month",
            "ubah_budget_bulan":        "override_budget_month",
            "edit_budget":              "edit_budget_amount",
            "update_budget":            "edit_budget_amount",
            "tutup_budget":             "close_budget",
            "close_budget_project":     "close_budget",
            "link_dokumen":             "link_expense",
            "link_po":                  "link_expense",
            "link_pr":                  "link_expense",
            "link_rmb":                 "link_expense",
            "link_cas":                 "link_expense",
            "link_inv":                 "link_expense",
            "assign_budget":            "link_expense",
            "hapus_link":               "unlink_expense",
            "remove_link":              "unlink_expense",
            "cek_budget":               "check_budget",
            "lihat_budget":             "check_budget",
            "sisa_budget":              "check_budget",
            "daftar_budget":            "list_budgets",
            "semua_budget":             "list_budgets",
            "budget_aktif":             "list_budgets",
            "history_budget":           "list_budgets",
            "budget_history":           "list_budgets",
            "budget_closed":            "list_budgets",
            "budget_arsip":             "list_budgets",
            "budget_ditutup":           "list_budgets",
            "hapus_budget":             "delete_budget",
            "delete_budget_project":    "delete_budget",
            "hapus_anggaran":           "delete_budget",
            "expense_kantor":           "check_ops_monthly",
            "ops_bulan":                "check_ops_monthly",
            "ringkasan_ops":            "check_ops_monthly",
            "budget_hampir_habis":      "budget_alert",
            "over_budget":              "budget_alert",
            "alert_budget":             "budget_alert",
            "kategori_ops":             "list_ops_categories",
            "tambah_kategori":          "add_ops_category",
        }
        if intent in INTENT_ALIASES:
            print(f"[{AGENT_NAME}] Alias normalize: {intent} → {INTENT_ALIASES[intent]}")
            intent = INTENT_ALIASES[intent]

        # Normalisasi param INV: LLM kadang return quote_id/qt_id alih-alih quotation_id
        if intent == "add_inv":
            for _alias_key in ("quote_id", "qt_id", "quotation", "from_qt", "from_quotation"):
                if params.get(_alias_key) and not params.get("quotation_id"):
                    params["quotation_id"] = params.pop(_alias_key)
                    print(f"[{AGENT_NAME}] Param normalize: {_alias_key} → quotation_id={params['quotation_id']}")
                    break

        # ── Safety net PO: batch edit/hapus/tambah item PO ──────────────────
        # Mirror dari safety net PR batch edit. Dijalankan SEBELUM safety net PO umum.
        _ubah_item_po_kw = (
            r'\b(ubah|edit|ganti|update|hapus|remove|delete|tambah|add)\b.*\bitem\b'
            r'|\bitem\b.*\b(ubah|edit|ganti|update|hapus|remove|delete|tambah|add)\b'
            r'|\b(ubah|edit|ganti|update)\b.*\bnomor\s+\d+\b'
            r'|\b(hapus|remove|delete)\b.*\bnomor\s+\d+\b'
        )
        if re.search(_ubah_item_po_kw, message, re.IGNORECASE):
            # Cari PO ID: dari pesan dulu, fallback ke history
            _m_po_msg = re.search(r'\b(PO-\d+)\b', message, re.IGNORECASE)
            _po_id_edit = _m_po_msg.group(1).upper() if _m_po_msg else ""
            if not _po_id_edit:
                _hist_po = " ".join(h.get("content","") for h in self.session_manager.get_history(session_id)[-10:])
                _m_po_hist = re.search(r'\b(PO-\d+)\b', _hist_po, re.IGNORECASE)
                _po_id_edit = _m_po_hist.group(1).upper() if _m_po_hist else ""
                # Hanya gunakan history PO ID — jangan fallback ke PR/QT ID
                if not _po_id_edit:
                    _po_id_edit = ""

            if _po_id_edit:
                def _parse_po_multi_idx(msg):
                    # Strip ID dokumen dulu agar angkanya tidak ter-parse sebagai index
                    _msg_po_idx = re.sub(r'\b(?:PR|PO|QT|RMB|CAS|FIN)-\d+\b', '', msg, flags=re.I)
                    idxs = []
                    for m in re.finditer(r'(?:nomor|item)\s+(\d+)', _msg_po_idx, re.I):
                        v = int(m.group(1))
                        if v not in idxs: idxs.append(v)
                    last_m = None
                    for m in re.finditer(r'(?:nomor|item)\s+(\d+)', _msg_po_idx, re.I):
                        last_m = m
                    if last_m:
                        rest = _msg_po_idx[last_m.end():]
                        for x in re.findall(r'(?:[,/]|\bdan\b)\s*(?:nomor\s+)?(\d+)', rest, re.I):
                            v = int(x)
                            if v not in idxs: idxs.append(v)
                    if not idxs:
                        m = re.search(r'(?:item\s+)?(?:nomor\s+)?(\d+)\b', _msg_po_idx, re.I)
                        if m: idxs.append(int(m.group(1)))
                    return sorted(set(idxs))

                def _parse_po_harga(msg):
                    m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', msg, re.I)
                    if m:
                        angka = float(m.group(1).replace(',','.'))
                        mul   = m.group(2).lower()
                        return int(angka*1_000_000) if mul in ('juta','jt') else int(angka*1_000)
                    m = re.search(r'Rp\s*([\d.,]+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    m = re.search(r'(?:harga|menjadi|jadi|=|:)\s*(?:Rp\s*)?([\d]{1,3}(?:[.,]\d{3})+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    return 0

                _is_po_hapus  = bool(re.search(r'\b(hapus|remove|delete)\b', message, re.I))
                _is_po_tambah = bool(re.search(r'\b(tambah(?:kan)?|add)\s+item\b', message, re.I))
                _po_action    = "hapus" if _is_po_hapus else "tambah" if _is_po_tambah else "ubah"

                _po_indices   = _parse_po_multi_idx(message)
                _po_harga     = _parse_po_harga(message)
                _m_po_qty     = re.search(r'(?:sebanyak\s+)?(?:menjadi|jadi|qty)\s+(\d+)\s*(?:unit|pcs|buah)?|(?:(\d+))\s+unit\b', message, re.I)
                _po_qty       = int(_m_po_qty.group(1) or _m_po_qty.group(2)) if _m_po_qty else 0

                # Untuk tambah: parse nama item dari pesan
                _po_nama_baru = ""
                if _po_action == "tambah":
                    _msg_po_n = re.sub(r'(?:item\s+baru)\s*:\s*', 'item baru ', message, flags=re.I)
                    _msg_po_n = re.sub(r'\bsebanyak\b', '', _msg_po_n, flags=re.I)
                    _msg_po_n = re.sub(r'\btambahkan\b', 'tambah', _msg_po_n, flags=re.I)
                    _m_po_nama = re.search(
                        r'\b(?:tambah|add)\s+item\s+(?:baru\s+)?([A-Za-z][A-Za-z0-9\s/,.()\'\"-]{2,80}?)'
                        r'(?:\s+\d+\s*(?:unit|pcs|buah)|\s+(?:dengan|harga|@)|\s*$)',
                        _msg_po_n, re.I
                    )
                    _po_nama_baru = _m_po_nama.group(1).strip() if _m_po_nama else ""
                    if not _po_nama_baru:
                        _m_po_fb = re.search(r'(?:item\s+baru\s*[:]?\s*)([A-Za-z][\w\s/,.()-]{2,60}?)\s+\d+\s*(?:unit|pcs|buah)', _msg_po_n, re.I)
                        _po_nama_baru = _m_po_fb.group(1).strip() if _m_po_fb else ""

                if len(_po_indices) > 1 and _po_action in ("ubah", "hapus"):
                    intent = "batch_edit_po_items"
                    params = {
                        "id":      _po_id_edit,
                        "action":  _po_action,
                        "indices": _po_indices,
                        "qty":     _po_qty,
                        "harga_per_unit": _po_harga,
                    }
                    print(f"[{AGENT_NAME}] Safety net PO batch_{_po_action}: po={_po_id_edit} idx={_po_indices} qty={_po_qty} harga={_po_harga}")
                elif _po_indices or _po_harga or _po_qty or _po_nama_baru:
                    _single_po_idx = _po_indices[0] if _po_indices else 0
                    intent = "batch_edit_po_items"
                    params = {
                        "id":      _po_id_edit,
                        "action":  _po_action,
                        "indices": [_single_po_idx] if _single_po_idx else [],
                        "qty":     _po_qty,
                        "harga_per_unit": _po_harga,
                        "nama_item": _po_nama_baru,
                    }
                    print(f"[{AGENT_NAME}] Safety net PO single_{_po_action}: po={_po_id_edit} idx={_single_po_idx} qty={_po_qty} harga={_po_harga} nama={_po_nama_baru}")

        # ── Safety net PO — intercept pesan yang mengandung PO/purchase order ──
        # Diperlukan karena LLM lokal sering salah route ke finance/general_chat
        _po_kw      = r'\bPO\b|\bpurchase.order\b|\bPO-\d+\b|\bPO/[A-Z0-9]'
        _po_id_m    = re.search(r'\b(PO-\d+)\b', message, re.IGNORECASE)
        _po_nomor_m = re.search(r'\b(PO/[A-Z0-9/]+)\b', message, re.IGNORECASE)
        _has_po     = bool(re.search(_po_kw, message, re.IGNORECASE))
        # Juga detect "dari PR-XXXX" atau "from PR" tanpa kata PO (intent add_po via PR)
        _dari_pr_m  = re.search(r'\b(?:dari|from|berdasarkan)\s+(PR-\d+)\b', message, re.IGNORECASE)
        _buat_po_kw = r'\\b(buat(?:kan)?|buatin|tambah|create|add|pesan|order\\s+(?:ke|untuk)|bikin(?:kan)?|tolong\\s+buat)\\b'
        _is_buat_po = bool(re.search(_buat_po_kw, message, re.IGNORECASE)) and _has_po

        if (_has_po or _is_buat_po) and intent not in (
            "add_po","list_po","detail_po","approve_po","reject_po","generate_po","delete_po",
            "batch_edit_po_items",
        ):
            _po_id_val = (_po_id_m.group(1).upper() if _po_id_m else
                          _po_nomor_m.group(1).upper() if _po_nomor_m else "")
            _msg_low = message.lower()

            # ── Generate (cek dulu sebelum buat, karena "generate" bukan "buat") ──
            if re.search(r'\b(generate|download|cetak|pdf|word|docx)\b', _msg_low) and _po_id_val:
                _fmt = "pdf" if "pdf" in _msg_low else "docx"
                intent = "generate_po"; params = {"id": _po_id_val, "format": _fmt}
                print(f"[{AGENT_NAME}] Safety net PO: generate_po id={_po_id_val} fmt={_fmt}")

            # ── List (tanpa PO-ID dan bukan perintah buat/hapus) ──
            elif re.search(r'\b(list|tampilkan|semua|daftar|lihat)\b', _msg_low) and not _po_id_val                     and not re.search(_buat_po_kw, _msg_low, re.IGNORECASE)                     and not re.search(r'\b(hapus|delete)\b', _msg_low):
                intent = "list_po"; params = {"status": ""}
                print(f"[{AGENT_NAME}] Safety net PO: list_po")

            # ── Buat PO baru (termasuk "buatkan", "bikinkan", dst) ──
            elif re.search(_buat_po_kw, _msg_low, re.IGNORECASE) or _is_buat_po:
                _pr_src_m = re.search(r'\b(PR-\d+)\b', message, re.IGNORECASE)
                _po_params = {"pr_id": _pr_src_m.group(1).upper()} if _pr_src_m else {}
                intent = "add_po"; params = _po_params
                print(f"[{AGENT_NAME}] Safety net PO: add_po params={params}")

            # ── Hapus ──
            elif re.search(r'\b(hapus|delete|remove|buang)\b', _msg_low) and _po_id_val:
                intent = "delete_po"; params = {"id": _po_id_val}
                print(f"[{AGENT_NAME}] Safety net PO: delete_po id={_po_id_val}")

            # ── Approve / Reject ──
            elif re.search(r'\b(approve|setujui|acc)\b', _msg_low):
                intent = "approve_po"; params = {"id": _po_id_val}
                print(f"[{AGENT_NAME}] Safety net PO: approve_po id={_po_id_val}")
            elif re.search(r'\b(reject|tolak|ditolak)\b', _msg_low):
                intent = "reject_po"; params = {"id": _po_id_val}
                print(f"[{AGENT_NAME}] Safety net PO: reject_po id={_po_id_val}")

            # ── Detail / View ──
            elif re.search(r'\b(detail|tampilkan|lihat|show|cek)\b', _msg_low) and _po_id_val:
                intent = "detail_po"; params = {"id": _po_id_val}
                print(f"[{AGENT_NAME}] Safety net PO: detail_po id={_po_id_val}")

            # ── Edit field PO (vendor, nomor, proyek, catatan) ──
            elif re.search(r'\b(ubah|edit|ganti|update|perbarui)\b', _msg_low) and _po_id_val and not re.search(r'\bitem\b', _msg_low):
                _po_upd_kw = {
                    "vendor": "vendor_nama", "nomor": "nomor",
                    "proyek": "proyek", "catatan": "catatan",
                    "alamat": "vendor_alamat", "attn": "vendor_attn",
                }
                _po_updates = {}
                for _fk, _fv in _po_upd_kw.items():
                    m_fk = re.search(rf'(?:{_fk})\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$|,)', message, re.I)
                    if m_fk: _po_updates[_fv] = m_fk.group(1).strip()
                intent = "update_po"
                params = {"id": _po_id_val, "updates": _po_updates}
                print(f"[{AGENT_NAME}] Safety net PO: update_po id={_po_id_val} updates={_po_updates}")

            # ── Fallback: ada PO-ID tapi intent salah ke finance ──
            elif _po_id_val and intent in ("general_chat", "add_reimburse", "add_kasbon",
                                            "list_finance", "search_finance", "approve_finance",
                                            "reject_finance", "generate_excel", "generate_pdf"):
                intent = "detail_po"; params = {"id": _po_id_val}
                print(f"[{AGENT_NAME}] Safety net PO: fallback detail_po id={_po_id_val}")

        # ── Safety net PR — intercept generate PR yang misroute ─────────────────
        # Diperlukan karena LLM lokal sering salah route:
        #   "generate word PR-0001" → add_pr (karena kata "buat"/"pr" terdeteksi)
        #   "generate pdf PR-0005"  → finance/general_chat
        _pr_id_m_sn    = re.search(r'\b(PR-\d+)\b', message, re.IGNORECASE)
        _pr_id_val_sn  = _pr_id_m_sn.group(1).upper() if _pr_id_m_sn else ""
        _msg_low_pr_sn = message.lower()
        _has_generate_kw = bool(re.search(
            r'\b(generate|download|cetak|unduh|buat\s+(?:pdf|word|docx)|pdf|word|docx)\b',
            _msg_low_pr_sn
        ))

        if _pr_id_val_sn and _has_generate_kw and intent not in ("generate_pr",):
            _fmt_pr_sn = "docx" if re.search(r'\b(word|docx)\b', _msg_low_pr_sn) else "pdf"
            intent = "generate_pr"
            params = {"id": _pr_id_val_sn, "format": _fmt_pr_sn}
            print(f"[{AGENT_NAME}] Safety net PR: generate_pr id={_pr_id_val_sn} fmt={_fmt_pr_sn}")

        # Hard override: add_pr tapi params mengandung format pdf/docx → harusnya generate_pr
        # LLM kadang return add_pr untuk perintah "generate word PR-0001"
        if intent == "add_pr" and _pr_id_val_sn and _has_generate_kw:
            _fmt_pr_ov = "docx" if re.search(r'\b(word|docx)\b', _msg_low_pr_sn) else "pdf"
            intent = "generate_pr"
            params = {"id": _pr_id_val_sn, "format": _fmt_pr_ov}
            print(f"[{AGENT_NAME}] Override: add_pr → generate_pr id={_pr_id_val_sn} fmt={_fmt_pr_ov}")

        # ── Safety net QT — intercept pesan yang mengandung QT/quotation ──────────
        _qt_kw     = r'\bQT\b|\bquotation\b|\bpenawaran\s+harga\b|\bsurat\s+penawaran\b|\bQT-\d+\b'
        _qt_id_m   = re.search(r'\b(QT-\d+)\b', message, re.IGNORECASE)
        # Coba juga deteksi nomor format "XX/HLMC-XX/..."
        _qt_nom_m  = re.search(r'(\d+/HLMC-[\w]+/[IVX]+/\d+)', message, re.IGNORECASE) if not _qt_id_m else None
        _qt_id_val = _qt_id_m.group(1).upper() if _qt_id_m else (_qt_nom_m.group(1) if _qt_nom_m else "")
        _has_qt    = bool(re.search(_qt_kw, message, re.IGNORECASE)) or bool(_qt_nom_m)
        _msg_low_qt = message.lower()
        # Guard: jangan intercept kalau pesan jelas tentang invoice/faktur
        _is_inv_context = bool(re.search(r'(invoice|faktur|INV)', message, re.IGNORECASE))

        if _has_qt and not _is_inv_context and intent not in (
            "add_qt","list_qt","update_qt","delete_qt","generate_qt","approve_qt","reject_qt",
        ):
            if re.search(r'\b(generate|download|cetak|pdf|excel|xlsx)\b', _msg_low_qt) and _qt_id_val:
                _fmt_qt = "excel" if re.search(r'\b(excel|xlsx)\b', _msg_low_qt) else "pdf"
                intent = "generate_qt"; params = {"id": _qt_id_val, "format": _fmt_qt}
                print(f"[{AGENT_NAME}] Safety net QT: generate_qt id={_qt_id_val} fmt={_fmt_qt}")
            elif re.search(r'\b(list|tampilkan|semua|daftar|lihat|detail|cek|info)\b', _msg_low_qt) and not _qt_id_val:
                intent = "list_qt"; params = {}
                print(f"[{AGENT_NAME}] Safety net QT: list_qt")
            elif re.search(r'\b(list|tampilkan|semua|daftar|lihat|detail|cek|info)\b', _msg_low_qt) and _qt_id_val:
                intent = "list_qt"; params = {"id": _qt_id_val}
                print(f"[{AGENT_NAME}] Safety net QT: list_qt id={_qt_id_val}")
            elif re.search(r'\b(tambah(?:kan)?|add)\s+item\b', _msg_low_qt) and _qt_id_val:
                # Tambah item ke quotation yang sudah ada
                _msg_qt_n = re.sub(r'(?:item\s+baru)\s*:\s*', 'item baru ', message, flags=re.I)
                _msg_qt_n = re.sub(r'\bsebanyak\b', '', _msg_qt_n, flags=re.I)
                _msg_qt_n = re.sub(r'\btambahkan\b', 'tambah', _msg_qt_n, flags=re.I)
                _m_qt_nama = re.search(
                    r'\b(?:tambah|add)\s+item\s+(?:baru\s+)?([A-Za-z][A-Za-z0-9\s/,.()\'\"-]{2,80}?)'
                    r'(?:\s+\d+\s*(?:unit|pcs|buah)|\s+(?:dengan|harga|@)|\s*$)',
                    _msg_qt_n, re.I
                )
                _qt_nama_baru = _m_qt_nama.group(1).strip() if _m_qt_nama else ""
                if not _qt_nama_baru:
                    _m_qt_fb = re.search(r'(?:item\s+baru\s*[:]?\s*)([A-Za-z][\w\s/,.()-]{2,60}?)\s+\d+\s*(?:unit|pcs|buah)', _msg_qt_n, re.I)
                    _qt_nama_baru = _m_qt_fb.group(1).strip() if _m_qt_fb else ""
                _m_qt_qty = re.search(r'(?:sebanyak\s+)?(\d+)\s*(?:unit|pcs|buah)', message, re.I)
                _m_qt_hrg = re.search(r'(\d+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', message, re.I)
                _qt_qty = int(_m_qt_qty.group(1)) if _m_qt_qty else 1
                _qt_harga = 0
                if _m_qt_hrg:
                    _v = float(_m_qt_hrg.group(1).replace(',','.')); _mul = _m_qt_hrg.group(2).lower()
                    _qt_harga = int(_v*1_000_000) if _mul in ('juta','jt') else int(_v*1_000)
                intent = "update_qt"
                params = {"id": _qt_id_val, "updates": {}, "_tambah_item": True,
                          "_nama": _qt_nama_baru, "_qty": _qt_qty, "_harga": _qt_harga}
                print(f"[{AGENT_NAME}] Safety net QT: tambah_item id={_qt_id_val} nama='{_qt_nama_baru}' qty={_qt_qty} harga={_qt_harga}")
            elif re.search(r'\b(hapus|delete|remove)\b', _msg_low_qt) and re.search(r'\bitem\b', _msg_low_qt) and _qt_id_val:
                # Hapus item dari quotation by index
                _msg_qt_idx = re.sub(r'\b(?:PR|PO|QT|RMB|CAS|FIN)-\d+\b', '', message, flags=re.I)
                _m_qt_idx = re.search(r'(?:nomor|item)\s+(\d+)', _msg_qt_idx, re.I)
                _qt_del_idx = int(_m_qt_idx.group(1)) if _m_qt_idx else 0
                intent = "update_qt"
                params = {"id": _qt_id_val, "updates": {}, "_hapus_item": True, "_idx": _qt_del_idx}
                print(f"[{AGENT_NAME}] Safety net QT: hapus_item id={_qt_id_val} idx={_qt_del_idx}")
            elif re.search(r'\b(edit|ubah|ganti|update)\b', _msg_low_qt) and re.search(r'\bitem\b', _msg_low_qt) and _qt_id_val:
                # Edit item quotation — pass ke update_qt dengan message
                intent = "update_qt"
                params = {"id": _qt_id_val, "updates": {}}
                print(f"[{AGENT_NAME}] Safety net QT: edit_item id={_qt_id_val}")
            elif re.search(r'\b(buat|tambah|create|add|bikin)\b', _msg_low_qt) and not _qt_id_val:
                intent = "add_qt"; params = {}
                print(f"[{AGENT_NAME}] Safety net QT: add_qt")
            elif re.search(r'\b(hapus|delete|remove)\b', _msg_low_qt) and _qt_id_val:
                intent = "delete_qt"; params = {"id": _qt_id_val}
                print(f"[{AGENT_NAME}] Safety net QT: delete_qt id={_qt_id_val}")
            elif re.search(r'\b(accept|diterima|setujui|acc)\b', _msg_low_qt):
                intent = "approve_qt"; params = {"id": _qt_id_val}
                print(f"[{AGENT_NAME}] Safety net QT: approve_qt id={_qt_id_val}")
            elif re.search(r'\b(reject|tolak|ditolak)\b', _msg_low_qt):
                intent = "reject_qt"; params = {"id": _qt_id_val}
                print(f"[{AGENT_NAME}] Safety net QT: reject_qt id={_qt_id_val}")
            elif _qt_id_val:
                # Fallback: ada QT ID di pesan → tampilkan detail
                intent = "list_qt"; params = {"id": _qt_id_val}
                print(f"[{AGENT_NAME}] Safety net QT: fallback list_qt id={_qt_id_val}")

        # ── Safety net INV — intercept pesan yang mengandung INV/invoice ─────────────
        _inv_kw    = r'\bINV\b|\binvoice\b|\bfaktur\b|\bINV-\d+\b'
        _inv_id_sn = re.search(r'\b(INV-\d+)\b', message, re.IGNORECASE)
        _inv_id_val= _inv_id_sn.group(1).upper() if _inv_id_sn else ""
        _has_inv   = bool(re.search(_inv_kw, message, re.IGNORECASE))
        _msg_low_inv = message.lower()

        if _has_inv and intent not in (
            "add_inv","list_inv","update_inv","delete_inv",
            "generate_inv","mark_paid","mark_issued",
        ):
            if re.search(r'\b(generate|download|cetak|pdf|excel|xlsx)\b', _msg_low_inv) and _inv_id_val:
                _fmt_inv = "excel" if re.search(r'\b(excel|xlsx)\b', _msg_low_inv) else "pdf"
                intent = "generate_inv"; params = {"id": _inv_id_val, "format": _fmt_inv}
                print(f"[{AGENT_NAME}] Safety net INV: generate_inv id={_inv_id_val} fmt={_fmt_inv}")
            elif re.search(r'\b(list|tampilkan|semua|daftar|lihat)\b', _msg_low_inv) and not _inv_id_val:
                intent = "list_inv"; params = {}
                print(f"[{AGENT_NAME}] Safety net INV: list_inv")
            elif re.search(r'\b(list|tampilkan|detail|lihat|cek|info)\b', _msg_low_inv) and _inv_id_val:
                intent = "list_inv"; params = {"id": _inv_id_val}
                print(f"[{AGENT_NAME}] Safety net INV: list_inv id={_inv_id_val}")
            elif re.search(r'\b(paid|dibayar|lunas|bayar)\b', _msg_low_inv) and _inv_id_val:
                intent = "mark_paid"; params = {"id": _inv_id_val}
                print(f"[{AGENT_NAME}] Safety net INV: mark_paid id={_inv_id_val}")
            elif re.search(r'\b(issue|issued|terbitkan|kirim)\b', _msg_low_inv) and _inv_id_val:
                intent = "mark_issued"; params = {"id": _inv_id_val}
                print(f"[{AGENT_NAME}] Safety net INV: mark_issued id={_inv_id_val}")
            elif re.search(r'\b(buat|tambah|create|add|bikin|faktur baru)\b', _msg_low_inv) and not _inv_id_val:
                intent = "add_inv"
                # Preserve quotation_id dari params LLM kalau ada, normalisasi key alias
                _qt_ref_m = re.search(r'\b(QT-\d+)\b', message, re.IGNORECASE)
                _qt_ref_val = _qt_ref_m.group(1).upper() if _qt_ref_m else ""
                _existing_qt_id = (params.get("quotation_id") or params.get("quote_id") or
                                   params.get("qt_id") or params.get("from_qt") or _qt_ref_val)
                params = {"quotation_id": _existing_qt_id} if _existing_qt_id else {}
                print(f"[{AGENT_NAME}] Safety net INV: add_inv quotation_id={_existing_qt_id or 'none'}")
            elif re.search(r'\b(hapus|delete|remove)\b', _msg_low_inv) and _inv_id_val:
                intent = "delete_inv"; params = {"id": _inv_id_val}
                print(f"[{AGENT_NAME}] Safety net INV: delete_inv id={_inv_id_val}")
            elif _inv_id_val:
                intent = "list_inv"; params = {"id": _inv_id_val}
                print(f"[{AGENT_NAME}] Safety net INV: fallback list_inv id={_inv_id_val}")

        # ── Safety net BUDGET — intercept pesan yang mengandung keyword budget ──
        _bud_kw = r'\b(budget|anggaran)\b'
        _bud_id_m = re.search(r'\b(BUD-\d{4})\b', message, re.IGNORECASE)
        _lnk_id_m = re.search(r'\b(LNK-\d{4})\b', message, re.IGNORECASE)
        _has_bud  = bool(re.search(_bud_kw, message, re.IGNORECASE))
        _msg_low_bud = message.lower()
        BUDGET_INTENTS_SET = {
            "add_budget_project", "add_budget_ops", "override_budget_month",
            "edit_budget_amount", "close_budget", "delete_budget", "link_expense", "unlink_expense",
            "check_budget", "list_budgets", "check_ops_monthly",
            "budget_alert", "list_ops_categories", "add_ops_category",
        }
        # Intent yang harus di-override jika ada BUD-ID di pesan
        _bad_budget_intents = {
            "add_pr", "add_po", "add_qt", "add_inv",
            "add_reimburse", "add_kasbon", "general_chat",
        }

        # ── Intercept: LLM salah klasifikasi "tutup" sebagai delete_budget ──────
        # Harus dicek SEBELUM blok safety net utama karena delete_budget ada di BUDGET_INTENTS_SET
        if intent == "delete_budget" and (_has_bud or _bud_id_m) and \
           re.search(r'\b(tutup|close|nonaktifkan|selesai)\b', _msg_low_bud) and \
           not re.search(r'\b(hapus|delete|remove)\b', _msg_low_bud):
            intent = "close_budget"
            print(f"[{AGENT_NAME}] Intercept: delete_budget → close_budget (kata tutup/close)")

        if (_has_bud or _bud_id_m or _lnk_id_m) and \
           (intent not in BUDGET_INTENTS_SET or (_bud_id_m and intent in _bad_budget_intents)):
            # Hapus budget — cek dulu sebelum link/unlink
            if re.search(r'\b(hapus|delete|remove)\b', _msg_low_bud) and \
               (re.search(r'\b(budget|anggaran)\b', _msg_low_bud) or _bud_id_m) and \
               not re.search(r'\b(link|expense|dokumen)\b', _msg_low_bud):
                intent = "delete_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: delete_budget")
            # Link expense — prioritas tinggi jika ada kata link
            elif re.search(r'\b(link|hubungkan|assign|masukkan)\b', _msg_low_bud):
                intent = "link_expense"
                print(f"[{AGENT_NAME}] Safety net BUD: link_expense")
            # Hapus budget
            elif re.search(r'\b(hapus|delete|remove)\b', _msg_low_bud) and \
                 not re.search(r'\b(link|expense)\b', _msg_low_bud):
                intent = "delete_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: delete_budget")
            # Expense/detail links dengan BUD-ID
            elif _bud_id_m and re.search(r'\b(expense|apa\s+saja|links?|detail|lihat\s+link)\b', _msg_low_bud):
                intent = "check_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: check_budget (expense/links)")
            # Buat budget proyek
            elif re.search(r'\b(buat|tambah|create|add|bikin|new|mulai|set)\b', _msg_low_bud) and \
                 re.search(r'\bproyek\b|\bproject\b', _msg_low_bud):
                intent = "add_budget_project"
                print(f"[{AGENT_NAME}] Safety net BUD: add_budget_project")
            # Buat budget operasional
            elif re.search(r'\b(buat|tambah|create|add|set|bikin)\b', _msg_low_bud) and \
                 re.search(r'\b(ops|operasional|kantor|rutin)\b', _msg_low_bud):
                intent = "add_budget_ops"
                print(f"[{AGENT_NAME}] Safety net BUD: add_budget_ops")
            # Override bulan
            elif re.search(r'\b(override|ubah|ganti|revisi)\b', _msg_low_bud) and \
                 re.search(r'\bbulan\b', _msg_low_bud):
                intent = "override_budget_month"
                print(f"[{AGENT_NAME}] Safety net BUD: override_budget_month")
            # Tutup budget
            elif re.search(r'\b(tutup|close|nonaktifkan|selesai)\b', _msg_low_bud):
                intent = "close_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: close_budget")
            # Unlink
            elif re.search(r'\b(hapus\s+link|unlink|lepas\s+link)\b', _msg_low_bud) or _lnk_id_m:
                intent = "unlink_expense"
                print(f"[{AGENT_NAME}] Safety net BUD: unlink_expense")
            # Alert
            elif re.search(r'\b(hampir\s+habis|mau\s+habis|over|melebihi|peringatan|alert)\b', _msg_low_bud):
                intent = "budget_alert"
                print(f"[{AGENT_NAME}] Safety net BUD: budget_alert")
            # List semua — termasuk history/closed
            elif re.search(r'\b(daftar|list|semua|tampilkan\s+semua|aktif|history|closed|ditutup|arsip|lama)\b', _msg_low_bud) and not _bud_id_m:
                intent = "list_budgets"
                print(f"[{AGENT_NAME}] Safety net BUD: list_budgets")
            # Ops monthly
            elif re.search(r'\b(expense|pengeluaran)\b', _msg_low_bud) and \
                 re.search(r'\b(kantor|ops|operasional|bulan)\b', _msg_low_bud):
                intent = "check_ops_monthly"
                print(f"[{AGENT_NAME}] Safety net BUD: check_ops_monthly")
            # Fallback: BUD-ID ada tapi intent salah → cek budget
            elif _bud_id_m and intent in _bad_budget_intents:
                intent = "check_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: check_budget (BUD-ID override)")
            # Cek budget (keyword)
            elif re.search(r'\b(cek|sisa|berapa|tampilkan|detail|lihat)\b', _msg_low_bud):
                intent = "check_budget"
                print(f"[{AGENT_NAME}] Safety net BUD: check_budget")

        # Hard override: add_po tapi params.id = PO-XXXX → harusnya generate_po
        # LLM kadang return add_po {'id': 'PO-0001'} untuk perintah "generate PO-0001"
        if intent == "add_po":
            _po_id_check = params.get("id", "")
            if _po_id_check and re.match(r'^PO-\d+$', str(_po_id_check).strip().upper()):
                _msg_low_g = message.lower()
                _fmt_g = "pdf" if "pdf" in _msg_low_g else "docx"
                intent = "generate_po"
                params = {"id": str(_po_id_check).strip().upper(), "format": _fmt_g}
                print(f"[{AGENT_NAME}] Override: add_po(id=PO-*) → generate_po id={params['id']}")

        # Hard override: update_pr_status → approve_pr / reject_pr
        # LLM kadang return intent update_pr_status dengan params {id, status}
        if intent == "update_pr_status":
            _status_val = str(params.get("status", "")).lower()
            if _status_val in ("approved", "approve"):
                intent = "approve_pr"
            elif _status_val in ("rejected", "reject"):
                intent = "reject_pr"
            else:
                intent = "approve_pr"  # fallback ke approve kalau tidak jelas
            print(f"[{AGENT_NAME}] Alias normalize: update_pr_status({_status_val}) → {intent}")

        # Hard override: field "nama" di update_pr/update_finance → map ke field yang benar
        # LLM sering pakai "nama" generik padahal schema PR pakai "pemohon"
        if intent == "update_pr":
            updates = params.get("updates", {})
            if isinstance(updates, dict) and "nama" in updates:
                updates["pemohon"] = updates.pop("nama")
                params["updates"] = updates
                print(f"[{AGENT_NAME}] Field fix: nama→pemohon in update_pr")


        # [batch_edit_pr_items handler dipindah ke _execute_intent]
        # Hard override: edit_pr_items — normalisasi action dan handle id kosong
        if intent == "edit_pr_items":
            # Normalize action non-standard dari LLM
            op_raw = params.get("action", "").lower()
            ACTION_NORM = {
                "ubah_qty": "ubah", "update_qty": "ubah", "change_qty": "ubah",
                "ubah_harga": "ubah", "update_price": "ubah", "edit_item": "ubah",
                "ganti": "ubah", "update": "ubah", "edit": "ubah",
                "remove": "hapus", "delete": "hapus",
                "add": "tambah",
            }
            if op_raw in ACTION_NORM:
                params["action"] = ACTION_NORM[op_raw]
                print(f"[{AGENT_NAME}] Normalize action: {op_raw} → {params['action']}")

            # Handle id kosong — cari dari history
            if not params.get("id"):
                _hist2 = " ".join(h.get("content","") for h in self.session_manager.get_history(session_id)[-10:])
                m_ph2  = re.search(r'\b(PR-\d+)\b', _hist2, re.IGNORECASE)
                if m_ph2:
                    params["id"] = m_ph2.group(1).upper()
                    print(f"[{AGENT_NAME}] Recovered PR ID from history: {params['id']}")

            # Handle nama_item berupa list dari LLM (kadang LLM return list)
            nama_item = params.get("nama_item", "")
            if isinstance(nama_item, list):
                # Konversi list ke batch — trigger batch handler
                qty_raw = params.get("qty", 0)
                indices_raw = []
                for ni in nama_item:
                    m_i = re.search(r'(\d+)', str(ni))
                    if m_i: indices_raw.append(int(m_i.group(1)))
                if indices_raw and len(indices_raw) > 1:
                    qty_val = qty_raw[0] if isinstance(qty_raw, list) and qty_raw else (qty_raw if isinstance(qty_raw, int) else 0)
                    intent = "batch_edit_pr_items"
                    params = {
                        "id":      params.get("id", ""),
                        "action":  params.get("action", "ubah"),
                        "indices": indices_raw,
                        "qty":     qty_val,
                        "harga_per_unit": 0,
                    }
                    print(f"[{AGENT_NAME}] LLM list→batch: idx={indices_raw} qty={qty_val}")

            op = params.get("action", "").lower()
            if intent == "edit_pr_items" and op not in ("hapus", "tambah", "remove", "delete", "add", "ubah", "edit", "ganti", "update"):
                pr_id_raw = params.get("id", "")
                updates = {}
                field_map = {
                    "pemohon": "pemohon", "nama pemohon": "pemohon", "nama": "pemohon",
                    "proyek": "proyek", "project": "proyek", "client": "proyek",
                    "keperluan": "keperluan", "keterangan": "keperluan",
                    "nomor": "nomor",
                }
                raw_field = params.get("nama_item", "").lower()
                raw_value = params.get("nilai_baru", "") or params.get("value", "")
                mapped = field_map.get(raw_field)
                if mapped and raw_value:
                    updates[mapped] = raw_value.strip().title() if mapped == "pemohon" else raw_value.strip()
                if not updates:
                    m_p = re.search(r'(?:nama\s+pemohon|pemohon|nama)\s*(?:menjadi|jadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,)', message, re.I)
                    m_r = re.search(r'(?:proyek|project|client)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    m_k = re.search(r'(?:keperluan|keterangan)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    m_n = re.search(r'(?:nomor)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    if m_p: updates["pemohon"]  = m_p.group(1).strip().title()
                    if m_r: updates["proyek"]   = m_r.group(1).strip()
                    if m_k: updates["keperluan"]= m_k.group(1).strip()
                    if m_n: updates["nomor"]    = m_n.group(1).strip()
                intent = "update_pr"
                params = {"id": pr_id_raw, "updates": updates}
                print(f"[{AGENT_NAME}] Hard override edit_pr_items→update_pr: id={pr_id_raw} updates={updates}")
        edit_kw = r"\b(edit|ubah|ganti|update|perbarui|koreksi)\b"
        pr_pattern = r"\b(PR-\d+|PR/|purchase.request)\b"

        # ── Safety net: batch edit/hapus/tambah items ──────────────────────
        # Aktif untuk SEMUA intent. Cari PR ID dari pesan atau history.
        ubah_item_kw_check = (
            r'\b(ubah|edit|ganti|update|hapus|remove|delete|tambah|add)\b.*\bitem\b'   # ada "item"
            r'|\bitem\b.*\b(ubah|edit|ganti|update|hapus|remove|delete|tambah|add)\b'   # "item" duluan
            r'|\b(ubah|edit|ganti|update)\b.*\bnomor\s+\d+\b'                          # "ubah/edit nomor X"
            r'|\b(hapus|remove|delete)\b.*\bnomor\s+\d+\b'                             # "hapus nomor X"
            r'|\bjumlah\s+unit\b.*\bnomor\b'                                            # "jumlah unit... nomor"
        )
        # Guard: skip safety net PR items jika pesan jelas tentang QT, PO, atau dokumen lain
        _non_pr_pattern = r'\b(QT-\d+|CAS-\d+|RMB-\d+|PO-\d+|BUD-\d+|LNK-\d+|quotation|kasbon|reimburse)\b'
        _is_non_pr_msg  = bool(re.search(_non_pr_pattern, message, re.IGNORECASE))

        if re.search(ubah_item_kw_check, message, re.IGNORECASE) and not _is_non_pr_msg:
            # Cari PR ID: dari pesan dulu, fallback ke history
            m_pr_msg = re.search(r'\b(PR-\d+)\b', message, re.IGNORECASE)
            _pr_id = m_pr_msg.group(1).upper() if m_pr_msg else ""
            if not _pr_id:
                _hist = " ".join(h.get("content","") for h in self.session_manager.get_history(session_id)[-10:])
                m_ph  = re.search(r'\b(PR-\d+)\b', _hist, re.IGNORECASE)
                _pr_id = m_ph.group(1).upper() if m_ph else ""

            if _pr_id:
                # ── Parse multiple indices ───────────────────────────────────
                def _parse_multi_idx(msg):
                    # Strip ID dokumen dulu agar angkanya tidak ter-parse sebagai index
                    _msg_idx = re.sub(r'\b(?:PR|PO|QT|RMB|CAS|FIN)-\d+\b', '', msg, flags=re.I)
                    idxs = []
                    for m in re.finditer(r'(?:nomor|item)\s+(\d+)', _msg_idx, re.I):
                        v = int(m.group(1))
                        if v not in idxs: idxs.append(v)
                    last_m = None
                    for m in re.finditer(r'(?:nomor|item)\s+(\d+)', _msg_idx, re.I):
                        last_m = m
                    if last_m:
                        rest = _msg_idx[last_m.end():]
                        for x in re.findall(r'(?:[,/]|\bdan\b)\s*(?:nomor\s+)?(\d+)', rest, re.I):
                            v = int(x)
                            if v not in idxs: idxs.append(v)
                    if not idxs:
                        m = re.search(r'(?:item\s+)?(?:nomor\s+)?(\d+)\b', _msg_idx, re.I)
                        if m: idxs.append(int(m.group(1)))
                    return sorted(set(idxs))

                # ── Parse harga ──────────────────────────────────────────────
                def _parse_harga_robust(msg):
                    m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', msg, re.I)
                    if m:
                        angka = float(m.group(1).replace(',','.'))
                        mul   = m.group(2).lower()
                        return int(angka*1_000_000) if mul in ('juta','jt') else int(angka*1_000)
                    m = re.search(r'Rp\s*([\d.,]+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    m = re.search(r'(?:harga|menjadi|jadi|=|:)\s*(?:Rp\s*)?([\d]{1,3}(?:[.,]\d{3})+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    return 0

                # ── Deteksi action ──────────────────────────────────────────
                is_hapus  = bool(re.search(r'\b(hapus|remove|delete)\b', message, re.I))
                is_tambah = bool(re.search(r'\b(tambah(?:kan)?|add)\s+item\b', message, re.I))
                is_ubah   = bool(re.search(r'\b(ubah|edit|ganti|update)\b', message, re.I))
                action    = "hapus" if is_hapus else "tambah" if is_tambah else "ubah"

                indices   = _parse_multi_idx(message)
                harga     = _parse_harga_robust(message)
                m_qty     = re.search(r'(?:menjadi|jadi|qty)\s+(\d+)\s*(?:unit|pcs|buah)?|(?:(\d+))\s+unit\b', message, re.I)
                qty       = int(m_qty.group(1) or m_qty.group(2)) if m_qty else 0

                # ── Batch (>1 item) atau single ─────────────────────────────
                if len(indices) > 1 and action in ("ubah", "hapus"):
                    # Batch operation — handle sekaligus
                    intent = "batch_edit_pr_items"
                    params = {
                        "id":      _pr_id,
                        "action":  action,
                        "indices": indices,   # list of 1-based index
                        "qty":     qty,
                        "harga_per_unit": harga,
                    }
                    print(f"[{AGENT_NAME}] Safety net batch_{action} (pr={_pr_id}): idx={indices} qty={qty} harga={harga}")
                elif len(indices) == 1 or (not indices and harga) or (not indices and qty):
                    # Single item operation
                    if action == "tambah":
                        # Normalisasi: strip ":" setelah "item baru" dan kata "sebanyak"
                        _msg_n1 = re.sub(r'(?:item\s+baru)\s*:\s*', 'item baru ', message, flags=re.I)
                        _msg_n1 = re.sub(r'\bsebanyak\b', '', _msg_n1, flags=re.I)
                        _msg_n1 = re.sub(r'\btambahkan\b', 'tambah', _msg_n1, flags=re.I)
                        # Ekstrak nama item dari pesan
                        m_nama_tambah = re.search(
                            r'\b(?:tambah|add)\s+item\s+(?:baru\s+)?([A-Za-z][A-Za-z0-9\s/,.()\'\"-]{2,80}?)'
                            r'(?:\s+\d+\s*(?:unit|pcs|buah)|\s+(?:dengan|harga|@)|\s*$)',
                            _msg_n1, re.IGNORECASE
                        )
                        nama_item = m_nama_tambah.group(1).strip() if m_nama_tambah else ""
                        # Fallback: ambil teks antara "item baru :?" dan angka qty
                        if not nama_item:
                            m_fb = re.search(r'(?:item\s+baru\s*[:]?\s*)([A-Za-z][\w\s/,.()-]{2,60}?)\s+\d+\s*(?:unit|pcs|buah)', _msg_n1, re.I)
                            nama_item = m_fb.group(1).strip() if m_fb else f"__idx_{indices[0]}__" if indices else ""
                    else:
                        nama_item = f"__idx_{indices[0]}__" if indices else ""
                    ubah_params = {"id": _pr_id, "action": action, "nama_item": nama_item}
                    if harga: ubah_params["harga_per_unit"] = harga
                    if qty:   ubah_params["qty"] = qty
                    if ubah_params.get("nama_item") or harga or qty:
                        intent = "edit_pr_items"
                        params = ubah_params
                        print(f"[{AGENT_NAME}] Safety net {action}_item (pr={_pr_id}): {params}")

        if intent == "general_chat" and re.search(edit_kw, message, re.IGNORECASE):
            is_pr_msg = bool(re.search(pr_pattern, message, re.IGNORECASE))
            is_fin_msg = bool(re.search(r"\b(reimburse|kasbon|cashbon|FIN-\d+|RMB-\d+|CAS-\d+)\b", message, re.IGNORECASE))
            if is_fin_msg and not is_pr_msg:
                intent = "update_finance"
                m_id   = re.search(r'\b((?:FIN|RMB|CAS)-\d+)\b', message, re.IGNORECASE)
                fin_id_raw = m_id.group(1).upper() if m_id else ""
                m_nama = re.search(r'(?:nama)\s*(?:menjadi|jadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,)', message, re.I)
                m_jml  = re.search(r'(?:jumlah|nominal|total)\s*(?:menjadi|jadi)\s*(?:Rp\s*)?([\d.,]+(?:\s*(?:jt|juta|rb|ribu))?)', message, re.I)
                m_kep  = re.search(r'(?:keperluan|keterangan)\s*(?:menjadi|jadi)\s*(.+?)(?:\s*$)', message, re.I)
                updates = {}
                if m_nama: updates["nama"] = m_nama.group(1).strip().title()
                if m_jml:
                    raw = m_jml.group(1).strip()
                    ms = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', raw, re.I)
                    if ms:
                        v = float(ms.group(1).replace(',','.')); mul = ms.group(2).lower()
                        updates["jumlah"] = int(v*1_000_000) if mul in ('jt','juta') else int(v*1_000)
                    else:
                        c = re.sub(r'[^0-9]','',raw); updates["jumlah"] = int(c) if c else 0
                if m_kep: updates["keperluan"] = m_kep.group(1).strip()
                params = {"id": fin_id_raw, "updates": updates}
                print(f"[{AGENT_NAME}] Safety net update_finance: id={fin_id_raw} updates={updates}")

            # Safety net untuk PR edit
            # Skip jika intent sudah di-set oleh safety net batch/item di atas
            if is_pr_msg and re.search(edit_kw, message, re.IGNORECASE) and intent not in ("batch_edit_pr_items", "edit_pr_items"):
                # Ekstrak ID — support PR-XXXX dan PR/xxx/yyy/...
                m_pr_id_short = re.search(r'\b(PR-\d+)\b', message, re.IGNORECASE)
                m_pr_nomor    = re.search(r'(PR/[^\s,]+)', message, re.IGNORECASE)
                pr_id_raw = (m_pr_id_short.group(1).upper() if m_pr_id_short
                             else m_pr_nomor.group(1) if m_pr_nomor else "")

                # edit_pr_items HANYA kalau ada keyword hapus/tambah ITEM secara eksplisit
                hapus_item_kw  = r'\b(hapus|remove|delete)\s+(?:item\s+)?(?:nomor\s+\d+\b|(?!(?:PR[-/]|data\b|semua\b)))'
                tambah_item_kw = r'\b(tambah(?:kan)?|add)\s+item\b'
                ubah_item_kw   = r'\b(ubah|edit|ganti|update)\s+item\s+(?:nomor\s+)?\d+\b|\b(ubah|edit|ganti|update)\s+item\s+[A-Za-z]'
                is_items_op = (
                    bool(re.search(hapus_item_kw, message, re.IGNORECASE)) or
                    bool(re.search(tambah_item_kw, message, re.IGNORECASE)) or
                    bool(re.search(ubah_item_kw,  message, re.IGNORECASE))
                )

                if is_items_op and intent != "edit_pr_items":
                    # Cek apakah by index ("hapus item nomor 4", "hapus item 4", "hapus nomor 4")
                    m_idx = re.search(
                        r'(?:hapus|remove|delete)\s+(?:item\s+)?(?:nomor\s+)?(\d+)\b'
                        r'|(?:hapus|remove|delete)\s+(?:item\s+)?nomor\s+(\d+)\b'
                        r'|item\s+nomor\s+(\d+)\b'
                        r'|nomor\s+(\d+)\b',
                        message, re.IGNORECASE
                    )
                    m_item = re.search(
                        r'(?:hapus|remove|delete)\s*(?:item\s*)?["\']?([A-Za-z][A-Za-z0-9\s]{2,40}?)(?:\s*x\d|\s*=|\s*Rp|\s*dari|\s*$)',
                        message, re.IGNORECASE
                    )
                    nama_item = m_item.group(1).strip() if m_item else ""
                    # Jangan ekstrak "nomor 4" / angka sebagai nama_item
                    if re.match(r'^(?:nomor\s+)?\d+$', nama_item, re.I):
                        nama_item = ""
                    # Jangan ekstrak "nomor" saja tanpa angka
                    if re.match(r'^nomor\s*$', nama_item, re.I):
                        nama_item = ""

                    # Ambil angka dari group manapun yang match
                    idx_val = None
                    if m_idx:
                        for g in m_idx.groups():
                            if g is not None:
                                idx_val = int(g)
                                break

                    # Jika action tambah: parse nama item dari pesan
                    is_tambah_op = bool(re.search(tambah_item_kw, message, re.IGNORECASE))
                    if is_tambah_op:
                        # Normalisasi: strip ":" setelah "item baru" dan kata "sebanyak"
                        _msg_n2 = re.sub(r'(?:item\s+baru)\s*:\s*', 'item baru ', message, flags=re.I)
                        _msg_n2 = re.sub(r'\bsebanyak\b', '', _msg_n2, flags=re.I)
                        _msg_n2 = re.sub(r'\btambahkan\b', 'tambah', _msg_n2, flags=re.I)
                        m_nama_t = re.search(
                            r'\b(?:tambah|add)\s+item\s+(?:baru\s+)?([A-Za-z][A-Za-z0-9\s/,.()\'\"-]{2,80}?)'
                            r'(?:\s+\d+\s*(?:unit|pcs|buah)|\s+(?:dengan|harga|@)|\s*$)',
                            _msg_n2, re.IGNORECASE
                        )
                        nama_baru = m_nama_t.group(1).strip() if m_nama_t else ""
                        if not nama_baru:
                            m_fb2 = re.search(r'(?:item\s+baru\s*[:]?\s*)([A-Za-z][\w\s/,.()-]{2,60}?)\s+\d+\s*(?:unit|pcs|buah)', _msg_n2, re.I)
                            nama_baru = m_fb2.group(1).strip() if m_fb2 else ""
                        m_qty_t  = re.search(r'(?:sebanyak\s+)?(\d+)\s*(?:unit|pcs|buah)', message, re.I)
                        m_hrg_t  = re.search(r'(\d+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', message, re.I)
                        qty_t    = int(m_qty_t.group(1)) if m_qty_t else 1
                        harga_t  = 0
                        if m_hrg_t:
                            v = float(m_hrg_t.group(1).replace(',','.')); mul = m_hrg_t.group(2).lower()
                            harga_t = int(v*1_000_000) if mul in ('juta','jt') else int(v*1_000)
                        if nama_baru:
                            intent = "edit_pr_items"
                            params = {"id": pr_id_raw, "action": "tambah", "nama_item": nama_baru,
                                      "qty": qty_t, "satuan": "Unit", "harga_per_unit": harga_t,
                                      "jumlah": harga_t * qty_t}
                            print(f"[{AGENT_NAME}] Safety net tambah_item: id={pr_id_raw} nama='{nama_baru}' qty={qty_t} harga={harga_t}")
                        else:
                            intent = "update_pr"
                            params = {"id": pr_id_raw, "updates": {}}
                    elif idx_val is not None:
                        intent = "edit_pr_items"
                        params = {"id": pr_id_raw, "action": "hapus", "nama_item": f"__idx_{idx_val}__"}
                        print(f"[{AGENT_NAME}] Safety net edit_pr_items by index {idx_val}: id={pr_id_raw}")
                    elif nama_item:
                        intent = "edit_pr_items"
                        params = {"id": pr_id_raw, "action": "hapus", "nama_item": nama_item}
                        print(f"[{AGENT_NAME}] Safety net edit_pr_items: id={pr_id_raw} hapus='{nama_item}'")
                    else:
                        intent = "update_pr"
                        params = {"id": pr_id_raw, "updates": {}}
                        print(f"[{AGENT_NAME}] Safety net update_pr (no item name): id={pr_id_raw}")
                else:
                    # Update field biasa (pemohon, proyek, keperluan)
                    if intent not in ("update_pr", "edit_pr_items"):
                        intent = "update_pr"
                    m_pemohon = re.search(r'(?:nama\s+pemohon|pemohon|nama)\s*(?:menjadi|jadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,)', message, re.I)
                    m_proyek  = re.search(r'(?:proyek|project|client)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    m_kep     = re.search(r'(?:keperluan|keterangan)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    updates = {}
                    if m_pemohon: updates["pemohon"] = m_pemohon.group(1).strip().title()
                    if m_proyek:  updates["proyek"]  = m_proyek.group(1).strip()
                    if m_kep:     updates["keperluan"] = m_kep.group(1).strip()
                    if intent == "update_pr":
                        params = {"id": pr_id_raw, "updates": updates}
                        print(f"[{AGENT_NAME}] Safety net update_pr: id={pr_id_raw} updates={updates}")

            # Safety net untuk tampilkan/detail PR
            elif is_pr_msg and intent == "general_chat":
                view_kw = r"\b(tampilkan|lihat|detail|cek|show|list|info)\b"
                if re.search(view_kw, message, re.IGNORECASE):
                    intent = "list_pr"
                    m_pr = re.search(r'\b(PR-\d+)\b', message, re.IGNORECASE)
                    params = {"id": m_pr.group(1).upper()} if m_pr else {}
                    print(f"[{AGENT_NAME}] Safety net list_pr: params={params}")
        # ── Safety net LAPORAN — intercept pesan yang minta generate laporan keuangan ──
        # LLM lokal sering gagal classify "buatkan laporan format pdf" → generate_pdf
        # Safety net ini memastikan intent generate_excel/generate_pdf tetap benar
        _laporan_kw = r'\b(laporan|report)\b'
        _excel_kw   = r'\b(excel|xlsx|spreadsheet)\b'
        _pdf_kw     = r'\b(pdf)\b'
        _fmt_kw     = r'\b(format|dalam|sebagai|buat|buatkan|generate|export|unduh|download)\b'
        _has_laporan = bool(re.search(_laporan_kw, message, re.IGNORECASE))
        _has_excel   = bool(re.search(_excel_kw,   message, re.IGNORECASE))
        _has_pdf     = bool(re.search(_pdf_kw,     message, re.IGNORECASE))
        _has_fmt_kw  = bool(re.search(_fmt_kw,     message, re.IGNORECASE))

        if _has_laporan and (_has_excel or _has_pdf) and intent not in ("generate_excel", "generate_pdf"):
            if _has_excel:
                intent = "generate_excel"
                params = {}
                print(f"[{AGENT_NAME}] Safety net LAPORAN: generate_excel")
            elif _has_pdf:
                intent = "generate_pdf"
                params = {}
                print(f"[{AGENT_NAME}] Safety net LAPORAN: generate_pdf")
            # Ekstrak filter bulan/tahun kalau ada
            _m_bulan = re.search(r'\b(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|bulan\s+ini|this\s+month)\b', message, re.IGNORECASE)
            _bulan_map = {"januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,"juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12}
            if _m_bulan:
                _bn = _m_bulan.group(1).lower()
                if "ini" in _bn or "this" in _bn:
                    params["bulan"] = int(datetime.now().strftime("%m"))
                    params["tahun"] = int(datetime.now().strftime("%Y"))
                elif _bn in _bulan_map:
                    params["bulan"] = _bulan_map[_bn]
            _m_tahun = re.search(r'\b(202[0-9])\b', message)
            if _m_tahun:
                params["tahun"] = int(_m_tahun.group(1))


        # ── Safety net FINANCE ID — kalau pesan mengandung FIN/RMB/CAS-xxxx ──
        # LLM lokal sering:
        # 1. Classify sebagai general_chat dan tidak eksekusi apapun
        # 2. Classify sebagai search_finance tapi tidak isi params id
        # Safety net ini memastikan ID selalu ada di params
        _fin_id_sn = re.search(r'\b((?:FIN|RMB|CAS)-\d+)\b', message, re.IGNORECASE)
        if _fin_id_sn and not re.search(r'\b(PR-|PO-|QT-)\d+\b', message, re.IGNORECASE):
            _fin_id_found = _fin_id_sn.group(1).upper()
            _cek_kw   = r'\b(cek|tampilkan|detail|status|lihat|info|show|check)\b'
            _hapus_kw = r'\b(hapus|delete|remove|buang)\b'
            _has_cek   = bool(re.search(_cek_kw,   message, re.IGNORECASE))
            _has_hapus = bool(re.search(_hapus_kw, message, re.IGNORECASE))
            # Case 0: hapus RMB/CAS → paksa ke delete_finance
            if _has_hapus and intent not in ("delete_finance", "delete_finance_confirmed"):
                intent = "delete_finance"
                params = {"id": _fin_id_found}
                print(f"[{AGENT_NAME}] Safety net FIN ID (case0): delete_finance id={_fin_id_found}")
            # Case 1: intent salah → perbaiki ke search_finance
            elif intent in ("general_chat", "list_finance") and _has_cek:
                intent = "search_finance"
                params = {"id": _fin_id_found}
                print(f"[{AGENT_NAME}] Safety net FIN ID (case1): search_finance id={_fin_id_found}")
            # Case 2: intent sudah search_finance tapi id kosong → isi id dari pesan
            elif intent == "search_finance" and not params.get("id"):
                params["id"] = _fin_id_found
                print(f"[{AGENT_NAME}] Safety net FIN ID (case2): inject id={_fin_id_found} ke params")


        storage_result = None
        needs_confirm  = False
        if intent != "general_chat" and self.sm:
            GUARDED_ACTIONS = {
                "add_pr_confirm", "add_finance_confirm",
                "delete_finance_confirmed",
                "delete_finance_wait_id", "update_pr_confirm",
                "edit_pr_items_confirm", "delete_pr_confirmed",
                "delete_all_pr_confirmed",
                "approve_reject_pr_confirm",
                "add_po_confirm", "add_po_collect",
                "approve_reject_po_confirm",
                "delete_po_confirm",
                # Quotation multi-step flows — jangan eksekusi intent lain saat collect
                "add_qt_collect", "add_qt_confirm", "delete_qt_confirm",
                # Budget multi-step flows
                "add_budget_project", "add_budget_ops", "link_expense", "delete_budget",
            }
            active_pending = self.session_manager.get_pending_confirm(session_id)
            # Read-only intents selalu dieksekusi meski ada pending aktif
            # Ini fix bug: "cek status FIN-0001" tetap jalan meski ada pending lain
            READ_ONLY_INTENTS = {
                "search_finance", "list_finance", "finance_summary",
                "dashboard_keuangan", "cek_saldo",
            }
            if active_pending and active_pending.get("action") in GUARDED_ACTIONS                     and intent not in READ_ONLY_INTENTS:
                print(f"[{AGENT_NAME}] GUARDED: skip _execute_intent, pending={active_pending.get('action')}")
                pass
            else:
                print(f"[{AGENT_NAME}] CALL _execute_intent: intent={intent} active_pending={active_pending.get('action') if active_pending else None}")
                storage_result, needs_confirm = self._execute_intent(intent, params, session_id, message)

        # Build response
        skill_name    = "finance"
        skill_content = self.skills.get(skill_name)
        if skill_content and len(skill_content) > 3000:
            skill_content = skill_content[:3000] + "\n\n[...dipotong...]"

        system_prompt = self._build_system_prompt(skill_content)
        history       = self.session_manager.get_history(session_id)
        messages      = [{"role": h["role"], "content": h["content"]} for h in history[-10:]]

        if storage_result:
            storage_json = json.dumps(storage_result, ensure_ascii=False, indent=2)

            # Kalau hasil search_finance/list_finance dengan data tunggal tapi tidak ada reply_hint
            # — buat reply_hint dari data supaya LLM tidak bebas menginterpretasi
            if not storage_result.get("reply_hint") and                storage_result.get("action") in ("search_finance", "list_finance") and                isinstance(storage_result.get("data"), dict):
                _d = storage_result["data"]
                _st = _d.get("status","pending")
                _st_icon = "✅" if _st=="approved" else "❌" if _st=="rejected" else "🕒"
                storage_result["reply_hint"] = (
                    f"📋 Detail {_d.get('jenis','').title()} {_d.get('id','')}:\n"
                    f"- Nama      : {_d.get('nama','-')}\n"
                    f"- Keperluan : {_d.get('keperluan','-') or '-'}\n"
                    f"- Jumlah    : Rp {int(_d.get('jumlah',0)):,}\n"
                    f"- Tanggal   : {_d.get('tanggal','-')}\n"
                    f"- Project   : {_d.get('project','-') or '-'}\n"
                    f"- Status    : {_st_icon} {_st.title()}\n"
                    + (f"- Approved oleh: {_d.get('approved_by','')}\n" if _d.get("approved_by") else "")
                )

            # Kalau ada reply_hint — bypass LLM, langsung pakai sebagai response
            if storage_result.get("reply_hint"):
                reply = storage_result["reply_hint"]
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                generated_file = storage_result.get("generated_file") or storage_result.get("file")
                return {"reply": reply, "skill_used": skill_name, "generated_file": generated_file}

            if needs_confirm:
                user_msg = f"{message}\n\n[PERLU KONFIRMASI]\n{storage_json}\n\nSampaikan ringkasan ke user dan minta konfirmasi dengan jelas. JANGAN kasih template kosong."
            else:
                user_msg = f"{message}\n\n[HASIL EKSEKUSI]\n{storage_json}\n\nSampaikan hasilnya ke user dengan ramah."
        else:
            user_msg = message

        messages.append({"role": "user", "content": user_msg})
        reply = await self._call_ollama(system_prompt, messages)

        self.session_manager.add_message(session_id, "user",      message)
        self.session_manager.add_message(session_id, "assistant", reply)

        generated_file = None
        if storage_result and isinstance(storage_result, dict) and \
           storage_result.get("status") == "berhasil":
            generated_file = storage_result.get("generated_file") or storage_result.get("file")

        return {"reply": reply, "skill_used": skill_name, "generated_file": generated_file}

    async def chat_with_file(self, session_id, message, file_b64, file_name, mime_type, file_size) -> dict:
        """Handle upload struk/bon/invoice — OCR via Groq, konfirmasi sebelum simpan."""
        # Clear pending aktif apapun — upload struk selalu mulai flow baru
        # Tapi simpan nama dan jenis kalau sudah ada dari flow sebelumnya
        carried_nama  = None
        carried_jenis = None
        existing_pending = self.session_manager.get_pending_confirm(session_id)
        if existing_pending:
            carried_nama  = existing_pending.get("nama") or existing_pending.get("pemohon")
            # Simpan jenis (kasbon/reimburse) dari flow yang sudah berjalan
            carried_jenis = existing_pending.get("jenis")
            self.session_manager.clear_pending_confirm(session_id)
            self._pending_file_bytes = None

        use_vision = mime_type in IMAGE_TYPES

        if use_vision:
            # Ekstrak data struk via Groq/Ollama
            extracted = await self._extract_receipt_data(file_b64, mime_type, message)

            if not extracted.get("_vision_ok", True):
                reply = (
                    "⚠️ Maaf, saya gagal membaca gambar struknya. Coba lagi sebentar, "
                    "atau input manual: 'tambah reimburse atas nama X, jumlah Rp ..., keperluan ...'"
                )
                self.session_manager.add_message(session_id, "user",      f"[Upload struk: {file_name}] {message}")
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "finance", "generated_file": None}

            # Simpan file bytes untuk dipakai saat konfirmasi
            self._pending_file_bytes = base64.b64decode(file_b64)

            nama       = self._extract_nama_from_message(message) or carried_nama
            keperluan  = self._extract_keperluan_from_message(message) or extracted["keperluan"]
            # Prioritas jenis: dari flow sebelumnya (kasbon/reimburse) > dari OCR struk
            # Ini fix bug: upload struk di tengah flow kasbon tidak lagi override ke reimburse
            jenis_final = carried_jenis or extracted["jenis"]
            import time as _time
            pending_data = {
                "action":    "add_finance_from_receipt",
                "nama":      nama,
                "nama_toko": extracted["nama_toko"],
                "jumlah":    extracted["jumlah"],
                "keperluan": keperluan,
                "tanggal":   extracted["tanggal"],
                "jenis":     jenis_final,
                "file_name": file_name,
                "_created_at": _time.time(),
            }
            self.session_manager.set_pending_confirm(session_id, pending_data)

            jumlah_fmt = f"Rp {extracted['jumlah']:,}"
            lines = ["📋 Saya sudah baca struknya, ini hasilnya:"]
            if nama:
                lines.append(f"- Atas nama: {nama}")
            lines.extend([
                f"- Toko/Merchant: {extracted['nama_toko']}",
                f"- Total: {jumlah_fmt}",
                f"- Keperluan: {keperluan}",
            ])
            if extracted["tanggal"]:
                lines.append(f"- Tanggal: {extracted['tanggal']}")
            if not nama:
                lines.append("\nIni atas nama siapa? Sebutkan juga reimburse atau kasbon, lalu konfirmasi 🙏")
            elif not jenis_final:
                lines.append("\nIni mau dicatat sebagai reimburse atau kasbon? 🙏")
            else:
                lines.append(f"- Jenis: {jenis_final.title()}")
                lines.append(
                    "\nKeperluan di atas diambil dari struk — kalau mau diganti ketik keperluan yang benar, "
                    "atau ketik 'ya' kalau sudah benar 🙏"
                )

            reply = "\n".join(lines)
            self.session_manager.add_message(session_id, "user",      f"[Upload struk: {file_name}] {message}")
            self.session_manager.add_message(session_id, "assistant", reply)
            return {"reply": reply, "skill_used": "finance", "generated_file": None}

        # Non-image file
        skill_content = self.skills.get("finance")
        system_prompt = self._build_system_prompt(skill_content)
        history       = self.session_manager.get_history(session_id)
        messages      = [{"role": h["role"], "content": h["content"]} for h in history[-8:]]
        messages.append({"role": "user", "content":
            f"[File: {file_name} | {file_size/1024:.1f} KB]\nInstruksi: {message or 'Analisa file ini'}"
        })
        reply = await self._call_ollama(system_prompt, messages)
        self.session_manager.add_message(session_id, "user",      f"[Upload: {file_name}] {message}")
        self.session_manager.add_message(session_id, "assistant", reply)
        return {"reply": reply, "skill_used": "finance", "generated_file": None}

    # ─── STORAGE EXECUTION ────────────────────────────────────────────────────

    def _execute_intent(self, intent: str, params: dict, session_id: str, message: str = "") -> tuple[dict | None, bool]:
        """Return (storage_result, needs_confirm)"""
        if not self.sm:
            return None, False
        import time as _time
        now = datetime.now()
        try:
            # ── Handler: Budget & Expense ─────────────────────────────────────
            BUDGET_INTENTS = {
                "add_budget_project", "add_budget_ops", "override_budget_month",
                "edit_budget_amount", "close_budget", "delete_budget", "link_expense", "unlink_expense",
                "check_budget", "list_budgets", "check_ops_monthly",
                "budget_alert", "list_ops_categories", "add_ops_category",
            }
            if intent in BUDGET_INTENTS and self._bud_handler:
                reply = self._bud_handler.handle(intent, message, session_id)
                # Jika budget handler masih punya sesi aktif → set pending_confirm
                # supaya _handle_confirm tahu ada multi-step flow yang berjalan
                import time as _bud_time
                if self._bud_handler.has_active_session(session_id):
                    self.session_manager.set_pending_confirm(session_id, {
                        "action": intent,
                        "_created_at": _bud_time.time(),
                    })
                return {"reply_hint": reply, "skill_used": "budget", "generated_file": None}, False

            # ── Handler: batch_edit_pr_items ─────────────────────────────────
            # Langsung eksekusi tanpa intermediate pending state untuk menghindari
            # konflik dengan GUARDED_ACTIONS dan LLM override
            if intent == "batch_edit_pr_items":
                pr_id   = params.get("id", "")
                action  = params.get("action", "ubah")
                indices = params.get("indices", [])
                qty     = params.get("qty", 0)
                harga   = params.get("harga_per_unit", 0)
                print(f"[{AGENT_NAME}] EXECUTE batch_{action}: pr={pr_id} idx={indices} qty={qty} harga={harga}")

                current_pr = self.sm.get_pr_by_id(pr_id)
                if not current_pr:
                    return {"reply_hint": f"❌ {pr_id} tidak ditemukan 🙏", "skill_used": "pr", "generated_file": None}, False

                current_items = list(current_pr.get("items", []))
                errors = []
                valid_indices = []

                for idx_1based in indices:
                    idx = idx_1based - 1
                    if 0 <= idx < len(current_items):
                        valid_indices.append(idx)
                    else:
                        errors.append(f"Nomor {idx_1based} tidak ada (total {len(current_items)} item)")

                if not valid_indices:
                    items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                    return {"reply_hint": (
                        f"❌ Nomor item tidak valid di {pr_id}.\n"
                        f"Items yang ada:\n{items_list} 🙏"
                    ), "skill_used": "pr", "generated_file": None}, False

                if action == "hapus":
                    removed = [current_items[i].get('nama','') for i in valid_indices]
                    new_items = [x for i, x in enumerate(current_items) if i not in valid_indices]
                    new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                    result = self.sm.update_pr(pr_id, {"items": new_items})
                    if not result:
                        return {"reply_hint": f"❌ Gagal menyimpan perubahan ke {pr_id} 🙏", "skill_used": "pr", "generated_file": None}, False
                    print(f"[{AGENT_NAME}] batch hapus OK: {removed}")
                    items_preview = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(new_items)
                    )
                    return {"reply_hint": (
                        f"✅ {len(valid_indices)} item berhasil dihapus dari {pr_id}!\n\n"
                        f"Items tersisa ({len(new_items)}):\n{items_preview}\n"
                        f"Total baru: Rp {new_total:,}\n\n"
                        + (f"⚠️ {'; '.join(errors)}\n\n" if errors else "")
                        + f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
                    ), "skill_used": "pr", "generated_file": None}, False

                elif action == "ubah":
                    if not qty and not harga:
                        item_names = [f"  {i+1}. {current_items[i].get('nama','')}" for i in valid_indices]
                        return {"reply_hint": (
                            f"Mau ubah apa dari {len(valid_indices)} item berikut di {pr_id}?\n"
                            + "\n".join(item_names) +
                            f"\n\nContoh:\n- 'qty jadi 3'\n- 'harga jadi 5jt' 🙏"
                        ), "skill_used": "pr", "generated_file": None}, False

                    new_items = list(current_items)
                    preview = []
                    for idx in valid_indices:
                        item = dict(current_items[idx])
                        old_qty   = item.get("qty", 1)
                        old_harga = item.get("harga_perkiraan", 0)
                        if qty:   item["qty"]             = qty
                        if harga: item["harga_perkiraan"] = harga
                        item["jumlah"] = item.get("harga_perkiraan", old_harga) * item.get("qty", old_qty)
                        new_items[idx] = item
                        line = f"  {idx+1}. {item.get('nama','')}:"
                        if qty:   line += f" qty {old_qty} → {qty}"
                        if harga: line += f" harga/unit Rp {old_harga:,} → Rp {harga:,}"
                        line += f" | total Rp {item['jumlah']:,}"
                        preview.append(line)

                    new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                    result = self.sm.update_pr(pr_id, {"items": new_items})
                    if not result:
                        return {"reply_hint": f"❌ Gagal menyimpan perubahan ke {pr_id} 🙏", "skill_used": "pr", "generated_file": None}, False
                    print(f"[{AGENT_NAME}] batch ubah OK: pr={pr_id} total=Rp{new_total:,}")
                    items_preview = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(new_items)
                    )
                    return {"reply_hint": (
                        f"✅ {len(valid_indices)} item berhasil diperbarui di {pr_id}!\n\n"
                        f"Perubahan:\n" + "\n".join(preview) + "\n\n"
                        + (f"⚠️ {'; '.join(errors)}\n\n" if errors else "")
                        + f"Items terbaru ({len(new_items)}):\n{items_preview}\n"
                        f"Total baru: Rp {new_total:,}\n\n"
                        f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
                    ), "skill_used": "pr", "generated_file": None}, False

                return {"reply_hint": f"❌ Action batch '{action}' tidak dikenal 🙏", "skill_used": "pr", "generated_file": None}, False


            # ── Handler: batch_edit_po_items ─────────────────────────────────
            # Mirror persis dari batch_edit_pr_items. Langsung eksekusi tanpa confirm.
            if intent == "batch_edit_po_items":
                po_id   = params.get("id", "")
                action  = params.get("action", "ubah")
                indices = params.get("indices", [])
                qty     = params.get("qty", 0)
                harga   = params.get("harga_per_unit", 0)
                print(f"[{AGENT_NAME}] EXECUTE batch_edit_po_{action}: po={po_id} idx={indices} qty={qty} harga={harga}")

                # Normalisasi action alias dari LLM
                ACTION_NORM_PO = {
                    "ubah_qty": "ubah", "update_qty": "ubah", "change_qty": "ubah",
                    "ubah_harga": "ubah", "update_price": "ubah", "edit_item": "ubah",
                    "ganti": "ubah", "update": "ubah", "edit": "ubah",
                    "remove": "hapus", "delete": "hapus",
                    "add": "tambah",
                }
                if action in ACTION_NORM_PO:
                    action = ACTION_NORM_PO[action]

                # Recover PO ID dari history kalau kosong
                if not po_id:
                    _hist_po2 = " ".join(h.get("content","") for h in self.session_manager.get_history(session_id)[-10:])
                    m_po2 = re.search(r'\b(PO-\d+)\b', _hist_po2, re.IGNORECASE)
                    if m_po2:
                        po_id = m_po2.group(1).upper()
                        print(f"[{AGENT_NAME}] Recovered PO ID from history: {po_id}")

                if not po_id:
                    return {"reply_hint": "❌ Sebutkan ID PO yang mau diedit (contoh: PO-0001) 🙏", "skill_used": "po", "generated_file": None}, False

                current_po = self.sm.get_po_by_id(po_id)
                if not current_po:
                    return {"reply_hint": f"❌ {po_id} tidak ditemukan 🙏", "skill_used": "po", "generated_file": None}, False

                current_items = list(current_po.get("items", []))
                errors = []
                valid_indices = []

                for idx_1based in indices:
                    idx = idx_1based - 1
                    if 0 <= idx < len(current_items):
                        valid_indices.append(idx)
                    else:
                        errors.append(f"Nomor {idx_1based} tidak ada (total {len(current_items)} item)")

                # ── HAPUS ──
                if action == "hapus":
                    if not valid_indices:
                        items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                        return {"reply_hint": (
                            f"❌ Nomor item tidak valid di {po_id}.\n"
                            f"Items yang ada:\n{items_list} 🙏"
                        ), "skill_used": "po", "generated_file": None}, False
                    removed = [current_items[i].get('nama','') for i in valid_indices]
                    new_items = [x for i, x in enumerate(current_items) if i not in valid_indices]
                    new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                    result = self.sm.update_po(po_id, {"items": new_items})
                    if not result:
                        return {"reply_hint": f"❌ Gagal menyimpan perubahan ke {po_id} 🙏", "skill_used": "po", "generated_file": None}, False
                    print(f"[{AGENT_NAME}] PO batch hapus OK: po={po_id} removed={removed}")
                    items_preview = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(new_items)
                    )
                    return {"reply_hint": (
                        f"✅ {len(valid_indices)} item berhasil dihapus dari {po_id}!\n"
                        f"Item dihapus: {', '.join(removed)}\n\n"
                        + (f"⚠️ {'; '.join(errors)}\n\n" if errors else "")
                        + (f"Items tersisa ({len(new_items)}):\n{items_preview}\n" if new_items else "⚠️ Tidak ada item tersisa.\n")
                        + f"Total baru: Rp {new_total:,}\n\n"
                        + f"Mau generate ulang dokumen? Ketik 'generate PDF {po_id}' 📄"
                    ), "skill_used": "po", "generated_file": None}, False

                # ── UBAH ──
                elif action == "ubah":
                    if not valid_indices:
                        items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                        return {"reply_hint": (
                            f"❌ Nomor item tidak valid di {po_id}.\n"
                            f"Items yang ada:\n{items_list} 🙏"
                        ), "skill_used": "po", "generated_file": None}, False
                    if not qty and not harga:
                        item_names = [f"  {i+1}. {current_items[i].get('nama','')}" for i in valid_indices]
                        return {"reply_hint": (
                            f"Mau ubah apa dari {len(valid_indices)} item berikut di {po_id}?\n"
                            + "\n".join(item_names)
                            + f"\n\nContoh:\n- 'qty jadi 3'\n- 'harga jadi 5jt' 🙏"
                        ), "skill_used": "po", "generated_file": None}, False

                    new_items = list(current_items)
                    preview = []
                    for idx in valid_indices:
                        item = dict(current_items[idx])
                        old_qty   = item.get("qty", 1)
                        old_harga = item.get("harga_perkiraan", 0)
                        if qty:   item["qty"]             = qty
                        if harga: item["harga_perkiraan"] = harga
                        item["jumlah"] = item.get("harga_perkiraan", old_harga) * item.get("qty", old_qty)
                        new_items[idx] = item
                        line = f"  {idx+1}. {item.get('nama','')}:"
                        if qty:   line += f" qty {old_qty} → {qty}"
                        if harga: line += f" harga/unit Rp {old_harga:,} → Rp {harga:,}"
                        line += f" | total Rp {item['jumlah']:,}"
                        preview.append(line)

                    new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                    result = self.sm.update_po(po_id, {"items": new_items})
                    if not result:
                        return {"reply_hint": f"❌ Gagal menyimpan perubahan ke {po_id} 🙏", "skill_used": "po", "generated_file": None}, False
                    print(f"[{AGENT_NAME}] PO batch ubah OK: po={po_id} total=Rp{new_total:,}")
                    items_preview = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(new_items)
                    )
                    return {"reply_hint": (
                        f"✅ {len(valid_indices)} item berhasil diperbarui di {po_id}!\n\n"
                        f"Perubahan:\n" + "\n".join(preview) + "\n\n"
                        + (f"⚠️ {'; '.join(errors)}\n\n" if errors else "")
                        + f"Items terbaru ({len(new_items)}):\n{items_preview}\n"
                        f"Total baru: Rp {new_total:,}\n\n"
                        f"Mau generate ulang dokumen? Ketik 'generate PDF {po_id}' 📄"
                    ), "skill_used": "po", "generated_file": None}, False

                # ── TAMBAH ──
                elif action == "tambah":
                    # Untuk tambah item, ekstrak dari params atau message
                    nama_baru  = params.get("nama_item", "").strip()
                    qty_baru   = qty or params.get("qty", 1)
                    satuan_baru = params.get("satuan", "Unit")
                    harga_baru = harga or params.get("harga_per_unit", 0)
                    jumlah_baru = harga_baru * qty_baru

                    if not nama_baru:
                        return {"reply_hint": (
                            f"Sebutkan nama item yang mau ditambahkan ke {po_id}\n"
                            f"Contoh: 'tambah item Monitor 2 unit Rp 5jt ke {po_id}' 🙏"
                        ), "skill_used": "po", "generated_file": None}, False

                    new_item = {
                        "nama":           nama_baru,
                        "qty":            qty_baru,
                        "satuan":         satuan_baru,
                        "harga_perkiraan": harga_baru,
                        "jumlah":         jumlah_baru,
                    }
                    new_items = current_items + [new_item]
                    new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                    result = self.sm.update_po(po_id, {"items": new_items})
                    if not result:
                        return {"reply_hint": f"❌ Gagal menambahkan item ke {po_id} 🙏", "skill_used": "po", "generated_file": None}, False
                    print(f"[{AGENT_NAME}] PO tambah item OK: po={po_id} item={nama_baru}")
                    items_preview = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(new_items)
                    )
                    return {"reply_hint": (
                        f"✅ Item baru berhasil ditambahkan ke {po_id}!\n\n"
                        f"Item baru: {nama_baru} x{qty_baru} {satuan_baru} = Rp {jumlah_baru:,}\n\n"
                        f"Items terbaru ({len(new_items)}):\n{items_preview}\n"
                        f"Total baru: Rp {new_total:,}\n\n"
                        f"Mau generate ulang dokumen? Ketik 'generate PDF {po_id}' 📄"
                    ), "skill_used": "po", "generated_file": None}, False

                return {"reply_hint": f"❌ Action '{action}' tidak dikenal untuk edit PO 🙏", "skill_used": "po", "generated_file": None}, False


            # ── READ ──────────────────────────────────────────────────────────
            if intent in ("list_finance", "search_finance"):
                all_fin = self.sm.get_finance()
                jenis   = params.get("jenis", "")
                status  = params.get("status", "")
                nama    = params.get("nama", "")
                keyword = params.get("keyword", "")
                bulan   = params.get("bulan", 0)
                tahun   = params.get("tahun", 0)
                fin_id_q = params.get("id", "").upper()

                # Cek apakah ada ID spesifik di params atau di pesan
                if not fin_id_q:
                    _m_fin_id = re.search(r'\b((?:FIN|RMB|CAS)-\d+)\b', message, re.IGNORECASE)
                    if _m_fin_id:
                        fin_id_q = _m_fin_id.group(1).upper()

                # Kalau ada ID spesifik — cari langsung dan return detail lengkap sebagai reply_hint
                # bypass LLM supaya semua field (keperluan, jumlah, dll) tampil akurat
                if fin_id_q:
                    target = next((x for x in all_fin if x.get("id","").upper() == fin_id_q), None)
                    if not target:
                        return {"action": intent, "status": "tidak_ditemukan",
                                "reply_hint": f"{fin_id_q} tidak ditemukan di data finance 🙏"}, False
                    st     = target.get("status","pending")
                    st_icon = "✅" if st=="approved" else "❌" if st=="rejected" else "🕒"
                    jenis_label = target.get("jenis","").title()
                    reply_hint = (
                        f"📋 Detail {jenis_label} {fin_id_q}:\n"
                        f"- Nama      : {target.get('nama','-')}\n"
                        f"- Keperluan : {target.get('keperluan','-') or '-'}\n"
                        f"- Jumlah    : Rp {int(target.get('jumlah',0)):,}\n"
                        f"- Tanggal   : {target.get('tanggal','-')}\n"
                        f"- Project   : {target.get('project','-') or '-'}\n"
                        f"- Status    : {st_icon} {st.title()}\n"
                        + (f"- Approved oleh: {target.get('approved_by','-')}\n" if target.get("approved_by") else "")
                    )
                    return {"action": intent, "status": "ok", "data": target,
                            "reply_hint": reply_hint}, False

                data = list(all_fin)
                if keyword: data = [x for x in data if keyword.lower() in str(x).lower()]
                if jenis:   data = [x for x in data if jenis.lower()   in x.get("jenis","").lower()]
                if status:  data = [x for x in data if status.lower()  in x.get("status","").lower()]
                if nama:    data = [x for x in data if nama.lower()    in x.get("nama","").lower()]
                if bulan:
                    bulan_str = f"-{str(bulan).zfill(2)}-"
                    data = [x for x in data if bulan_str in x.get("tanggal", x.get("created_at",""))]
                if tahun:
                    data = [x for x in data if str(tahun) in x.get("tanggal", x.get("created_at",""))]
                return {"action": intent, "data": data, "total": len(data)}, False

            if intent == "dashboard_keuangan":
                data         = self.sm.get_finance()
                bulan_ini    = now.strftime("%Y-%m")
                data_bulan   = [x for x in data if bulan_ini in x.get("created_at", "")]
                total_nilai  = sum(x.get("jumlah", 0) for x in data_bulan)
                pending_list = [x for x in data_bulan if x.get("status") == "pending"]
                approved_list= [x for x in data_bulan if x.get("status") == "approved"]
                rejected_list= [x for x in data_bulan if x.get("status") == "rejected"]
                reimburse    = [x for x in data_bulan if x.get("jenis")  == "reimburse"]
                kasbon       = [x for x in data_bulan if x.get("jenis")  == "kasbon"]
                # Top 3 pengaju
                from collections import Counter
                top_pengaju  = Counter(x.get("nama","") for x in data_bulan).most_common(3)
                return {
                    "action":          "dashboard_keuangan",
                    "periode":         bulan_ini,
                    "total_pengajuan": len(data_bulan),
                    "total_nilai":     total_nilai,
                    "pending":         len(pending_list),
                    "approved":        len(approved_list),
                    "rejected":        len(rejected_list),
                    "total_reimburse": len(reimburse),
                    "total_kasbon":    len(kasbon),
                    "top_pengaju":     [{"nama": n, "jumlah_pengajuan": c} for n, c in top_pengaju],
                }, False

            if intent == "finance_summary":
                data  = self.sm.get_finance()
                total = sum(x.get("jumlah", 0) for x in data)
                return {
                    "action": intent,
                    "total_data":  len(data),
                    "total_nilai": total,
                    "pending":     len([x for x in data if x.get("status") == "pending"]),
                    "approved":    len([x for x in data if x.get("status") == "approved"]),
                    "rejected":    len([x for x in data if x.get("status") == "rejected"]),
                }, False

            # ── TAMBAH ────────────────────────────────────────────────────────
            if intent in ("add_reimburse", "add_kasbon"):
                jenis  = "reimburse" if intent == "add_reimburse" else "kasbon"
                jumlah = params.get("jumlah", 0)
                if isinstance(jumlah, str):
                    jumlah = int(re.sub(r"[^0-9]", "", jumlah) or 0)
                nama      = params.get("nama", "").strip()
                keperluan = params.get("keperluan", "").strip()
                project   = params.get("project", "").strip() or "Operasional"
                tanggal   = params.get("tanggal", now.strftime("%Y-%m-%d"))

                # Kalau data wajib (nama / jumlah / keperluan) belum lengkap,
                # set pending dan tanya satu per satu — JANGAN langsung tampilkan
                # konfirmasi dengan data kosong. Pattern ini sama dengan PR collect_data.
                missing = []
                if not nama:     missing.append("nama")
                if not jumlah:   missing.append("jumlah")
                if not keperluan: missing.append("keperluan")

                pending_data = {
                    "action":    "add_finance_confirm",
                    "fin_step":  "collect" if missing else "confirm",
                    "jenis":     jenis,
                    "nama":      nama,
                    "jumlah":    jumlah,
                    "keperluan": keperluan,
                    "project":   project,
                    "tanggal":   tanggal,
                    "missing":   missing,
                    "_created_at": _time.time(),
                }
                self.session_manager.set_pending_confirm(session_id, pending_data)

                if missing:
                    pertanyaan = {
                        "nama":      f"Baik, mau ajukan {jenis}! 💰 Ini atas nama siapa?",
                        "jumlah":    "Berapa jumlahnya? (contoh: Rp 250.000 atau 250rb)",
                        "keperluan": "Keperluannya apa?",
                    }
                    reply_hint = pertanyaan.get(missing[0], f"Masih butuh: {missing[0]}. Bisa tolong isi?")
                else:
                    jumlah_fmt = f"Rp {jumlah:,}"
                    reply_hint = (
                        f"Baik, saya rangkum dulu sebelum disimpan:\n"
                        f"- Jenis     : {jenis.title()}\n"
                        f"- Nama      : {nama}\n"
                        f"- Jumlah    : {jumlah_fmt}\n"
                        f"- Keperluan : {keperluan}\n"
                        f"- Project   : {project}\n"
                        f"- Tanggal   : {tanggal}\n\n"
                        "Ada yang perlu diubah? Ketik koreksinya, atau ketik 'ya' untuk simpan 🙏"
                    )
                return {"action": "confirm_needed", "reply_hint": reply_hint}, True

            # ── APPROVAL ──────────────────────────────────────────────────────
            if intent in ("approve_finance", "reject_finance"):
                fin_id = params.get("id", "").upper()
                status = "approved" if intent == "approve_finance" else "rejected"

                # Resolve by nama kalau tidak ada ID
                # Support FIN-xxxx (lama), RMB-xxxx (reimburse), CAS-xxxx (kasbon)
                if not fin_id or not re.match(r'^(FIN|RMB|CAS)-\d+$', fin_id):
                    nama_cari = params.get("nama", "")
                    jenis_cari = params.get("jenis", "")
                    all_fin = self.sm.get_finance()

                    if nama_cari:
                        candidates = [x for x in all_fin
                                      if nama_cari.lower() in x.get("nama", "").lower()
                                      and x.get("status") == "pending"]
                        if jenis_cari:
                            by_jenis = [x for x in candidates
                                        if jenis_cari.lower() in x.get("jenis", "").lower()]
                            if by_jenis:
                                candidates = by_jenis
                        if len(candidates) == 1:
                            fin_id = candidates[0]["id"]
                            print(f"[{AGENT_NAME}] {intent}: resolved '{nama_cari}' → {fin_id}")
                        elif len(candidates) > 1:
                            return {"action": intent, "status": "ambigu",
                                    "pesan": f"Ditemukan {len(candidates)} pengajuan pending atas nama {nama_cari}. Sebutkan ID spesifik.",
                                    "data": [{"id": x["id"], "jenis": x.get("jenis",""),
                                              "jumlah": x.get("jumlah",0)} for x in candidates]}, False
                        else:
                            # Cek apakah ada data dengan nama yang sama tapi sudah approved/rejected
                            already_done = [x for x in all_fin
                                           if nama_cari.lower() in x.get("nama", "").lower()
                                           and x.get("status") in ("approved", "rejected")]
                            if already_done:
                                item = already_done[0]
                                label = "sudah disetujui" if item.get("status") == "approved" else "sudah ditolak"
                                return {"action": intent, "status": "gagal",
                                        "pesan": f"{item['jenis'].title()} {item['id']} atas nama {item.get('nama','')} tidak bisa diubah — {label}.",
                                        "current_status": item.get("status"),
                                        "data": item}, False
                            pending_list = [x for x in all_fin if x.get("status") == "pending"]
                            return {"action": intent, "status": "tidak_ditemukan",
                                    "pesan": f"Tidak ada pengajuan atas nama '{nama_cari}'.",
                                    "data_pending": [{"id": x["id"], "nama": x.get("nama",""),
                                                      "jenis": x.get("jenis","")}
                                                     for x in pending_list]}, False
                    else:
                        pending_list = [x for x in all_fin if x.get("status") == "pending"]
                        return {"action": intent, "status": "butuh_id",
                                "pesan": "Sebutkan nama atau ID pengajuan yang mau di-approve/reject",
                                "data_pending": [{"id": x["id"], "nama": x.get("nama",""),
                                                  "jenis": x.get("jenis",""),
                                                  "jumlah": x.get("jumlah",0)} for x in pending_list]}, False

                # Validasi — cek status saat ini sebelum update
                all_fin = all_fin if 'all_fin' in dir() else self.sm.get_finance()
                target = next((x for x in self.sm.get_finance() if x["id"] == fin_id), None)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "pesan": f"{fin_id} tidak ditemukan"}, False
                current_status = target.get("status", "pending")
                if current_status != "pending":
                    label = "sudah disetujui" if current_status == "approved" else "sudah ditolak"
                    return {"action": intent, "status": "gagal",
                            "pesan": f"{fin_id} tidak bisa diubah — statusnya {label}.",
                            "current_status": current_status}, False

                result = self.sm.update_finance(fin_id, {"status": status})
                return {"action": intent, "status": "berhasil" if result else "gagal",
                        "id": fin_id, "new_status": status, "data": result}, False

            # ── UPDATE ────────────────────────────────────────────────────────
            if intent == "update_finance":
                fin_id  = params.get("id", "").upper()
                updates = params.get("updates") or {}
                if not isinstance(updates, dict):
                    updates = {}

                # Strip semua field berbahaya yang bisa diinjeksi LLM
                for bad_key in ("status", "approved_by", "rejected_by", "created_at", "id"):
                    updates.pop(bad_key, None)

                # Buang field yang nilainya None/kosong dari LLM
                updates = {k: v for k, v in updates.items() if v is not None and v != ""}

                # ── Normalisasi jumlah ────────────────────────────────────────
                if "jumlah" in updates:
                    raw_j = str(updates["jumlah"])
                    jumlah_parsed = 0
                    m_short = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', raw_j, re.I)
                    if m_short:
                        v = float(m_short.group(1).replace(",", "."))
                        mul = m_short.group(2).lower()
                        jumlah_parsed = int(v * 1_000_000) if mul in ("jt", "juta") else int(v * 1_000)
                    else:
                        cleaned = re.sub(r'[^0-9]', '', raw_j)
                        try: jumlah_parsed = int(cleaned) if cleaned else 0
                        except: pass
                    if jumlah_parsed > 0:
                        updates["jumlah"] = jumlah_parsed
                    else:
                        updates.pop("jumlah", None)

                # Kalau updates jumlah masih kosong, coba parse dari raw message langsung
                if not updates.get("jumlah"):
                    m_raw = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', message, re.I)
                    if not m_raw:
                        m_raw2 = re.search(r'(?:jadi|menjadi|ganti|ubah)\s*(?:Rp\s*)?([\d.,]+)', message, re.I)
                        if m_raw2:
                            cleaned = m_raw2.group(1).replace('.','').replace(',','')
                            try:
                                val = int(cleaned)
                                if val > 0 and any(k in message.lower() for k in ['jumlah','nominal','total']):
                                    updates["jumlah"] = val
                            except: pass
                    elif m_raw:
                        v = float(m_raw.group(1).replace(',','.'))
                        mul = m_raw.group(2).lower()
                        val = int(v * 1_000_000) if mul in ('jt','juta') else int(v * 1_000)
                        if any(k in message.lower() for k in ['jumlah','nominal','total']):
                            updates["jumlah"] = val

                # Fallback: parse nama dari raw message kalau LLM tidak ekstrak
                if not updates.get("nama") and any(k in message.lower() for k in ['nama','name']):
                    m_nama = re.search(r'(?:nama|name)\s*(?:jadi|menjadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,|\bdan\b)', message, re.I)
                    if m_nama:
                        updates["nama"] = m_nama.group(1).strip().title()

                # Fallback: parse keperluan dari raw message
                if not updates.get("keperluan") and any(k in message.lower() for k in ['keperluan','keterangan']):
                    m_kep = re.search(r'(?:keperluan|keterangan)\s*(?:jadi|menjadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                    if m_kep:
                        updates["keperluan"] = m_kep.group(1).strip()

                # Kalau tidak ada ID → minta dulu via pending
                # Support prefix: FIN-xxxx (lama), RMB-xxxx (reimburse baru), CAS-xxxx (kasbon baru)
                _valid_id = fin_id and bool(re.match(r'^(FIN|RMB|CAS)-\d+$', fin_id))
                if not _valid_id:
                    import time as _time_upd
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":    "update_finance_confirm",
                        "updates":   updates,
                        "raw_message": params.get("_raw", ""),
                        "_created_at": _time_upd.time(),
                    })
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID finance yang mau diupdate ya (contoh: RMB-0001 untuk reimburse, CAS-0001 untuk kasbon) 🙏"}, False

                target = next((x for x in self.sm.get_finance() if x["id"] == fin_id), None)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"{fin_id} tidak ditemukan di data finance 🙏"}, False

                if not updates:
                    # Simpan pending dengan ID supaya user tinggal sebutkan field
                    import time as _time_upd
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":    "update_finance_confirm",
                        "fin_id":    fin_id,
                        "updates":   {},
                        "target":    target,
                        "_created_at": _time_upd.time(),
                    })
                    return {"action": intent, "status": "kosong",
                            "reply_hint": (
                                f"Mau update field apa dari {fin_id} "
                                f"({target.get('jenis','').title()} a.n. {target.get('nama','')})?\n"
                                f"Contoh:\n"
                                f"- 'ganti nama jadi Budi'\n"
                                f"- 'ubah keperluan jadi transport'\n"
                                f"- 'ubah jumlah jadi 300rb' 🙏"
                            )}, False

                # Ada ID dan updates — langsung eksekusi (bypass confirm, sama seperti UI card)
                result = self.sm.update_finance(fin_id, updates)
                if not result:
                    return {"action": intent, "status": "gagal",
                            "reply_hint": f"❌ Gagal mengupdate {fin_id}. Coba lagi ya 🙏"}, False
                field_list = []
                for k, v in updates.items():
                    if k == "jumlah":
                        field_list.append(f"{k} → Rp {v:,}" if isinstance(v, int) else f"{k} → {v}")
                    else:
                        field_list.append(f"{k} → {v}")
                return {"action": intent, "status": "berhasil",
                        "reply_hint": (
                            f"✅ {fin_id} berhasil diperbarui!\n"
                            f"Perubahan: {', '.join(field_list)}\n\n"
                            f"Data terbaru:\n"
                            f"- Nama      : {result.get('nama','')}\n"
                            f"- Keperluan : {result.get('keperluan','') or '-'}\n"
                            f"- Jumlah    : Rp {result.get('jumlah',0):,}\n"
                            f"- Status    : {result.get('status','')}\n\n"
                            f"Ada yang bisa saya bantu lagi? 😊"
                        )}, False

            # ── HAPUS ─────────────────────────────────────────────────────────
            if intent == "delete_finance":
                fin_id = params.get("id", "").upper()
                # Support semua prefix: FIN-, RMB-, CAS-
                _fin_id_match = re.match(r'^(FIN|RMB|CAS)-\d+$', fin_id)
                if not fin_id or not _fin_id_match:
                    import time as _time_del
                    nama_cari = params.get("nama", "")
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":     "delete_finance_wait_id",
                        "nama_cari":  nama_cari,
                        "_created_at": _time_del.time(),
                    })
                    hint = f" atas nama {nama_cari}" if nama_cari else ""
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": f"Sebutkan ID finance{hint} yang mau dihapus ya (contoh: RMB-0001, CAS-0002) 🙏"}, False
                fin_detail = next((x for x in self.sm.get_finance() if x["id"].upper() == fin_id), None)
                if not fin_detail:
                    return {"action": intent, "status": "gagal",
                            "reply_hint": f"❌ **{fin_id}** tidak ditemukan. Data mungkin sudah dihapus atau ID tidak valid."}, False
                self.session_manager.set_pending_confirm(session_id, {
                    "action": "delete_finance_confirmed", "id": fin_id,
                    "detail": fin_detail, "_created_at": _time.time(),
                })
                _jenis_label = fin_detail.get('jenis','Finance').title()
                return {"action": "confirm_needed", "target": fin_id, "detail": fin_detail,
                        "pesan": (
                            f"⚠️ Konfirmasi hapus {_jenis_label} **{fin_id}**:\n"
                            f"- Nama      : {fin_detail.get('nama','-')}\n"
                            f"- Keperluan : {fin_detail.get('keperluan','-')}\n"
                            f"- Nominal   : Rp {int(fin_detail.get('jumlah',0)):,}\n"
                            f"- Status    : {fin_detail.get('status','pending').title()}\n\n"
                            f"Data ini akan dihapus permanen. Ketik ya/tidak."
                        )}, True

            # ── SALDO ─────────────────────────────────────────────────────────
            if intent == "set_saldo_awal":
                return {"action": intent, "status": "dihapus",
                        "reply_hint": "ℹ️ Fitur saldo awal sudah dihapus. Laporan keuangan EVA sekarang hanya mencatat Pemasukan (Invoice paid) dan Pengeluaran (Reimburse/Kasbon) tanpa saldo berjalan."}, False

            if intent == "cek_saldo":
                data              = self.sm.get_finance()
                inv_data          = [x for x in data if x.get("jenis") == "invoice"]
                pengeluaran_data  = [x for x in data if x.get("jenis") != "invoice" and x.get("status") == "approved"]
                total_pemasukan   = sum(x.get("jumlah", 0) for x in inv_data)
                total_pengeluaran = sum(x.get("jumlah", 0) for x in pengeluaran_data)
                net               = total_pemasukan - total_pengeluaran
                return {
                    "action":             intent,
                    "total_pemasukan":    total_pemasukan,
                    "total_pengeluaran":  total_pengeluaran,
                    "net":                net,
                    "jumlah_transaksi":   len(data),
                }, False

            # ── PURCHASE REQUEST ───────────────────────────────────────────────
            if intent == "add_pr":
                pemohon  = params.get("pemohon", "")
                proyek   = params.get("proyek", "")
                keperluan= params.get("keperluan", "")
                nomor    = params.get("nomor", "")
                items    = params.get("items", [])
                vendor   = params.get("vendor", "")
                catatan  = params.get("catatan", "")

                # Validasi field wajib
                missing = []
                if not pemohon:   missing.append("nama pemohon")
                if not proyek:    missing.append("proyek/client")
                if not keperluan: missing.append("keperluan")

                if missing:
                    # Set pending confirm dengan data yang sudah ada
                    # supaya jawaban user berikutnya masuk ke state machine
                    pending_data = {
                        "action": "add_pr_confirm",
                        "pr_step": "collect_data",  # step khusus untuk kumpulkan data dasar
                        "pemohon": pemohon,
                        "proyek": proyek,
                        "keperluan": keperluan,
                        "items": items,
                        "nomor": nomor,
                        "vendor": vendor,
                        "catatan": catatan,
                        "missing": missing,
                        "_created_at": _time.time(),
                    }
                    self.session_manager.set_pending_confirm(session_id, pending_data)
                    pertanyaan = {
                        "nama pemohon": "Baik, saya bantu buat PR-nya! 📋 Siapa nama pemohonnya?",
                        "proyek/client": f"Oke! PR untuk pemohon {pemohon}. Ini untuk proyek atau client apa?",
                        "keperluan": f"Baik! Keperluannya apa? (contoh: Pembelian hardware, Pembelian ATK)",
                    }
                    first_missing = missing[0]
                    reply_hint = pertanyaan.get(first_missing,
                        f"Masih butuh informasi: {first_missing}. Bisa tolong lengkapi?")
                    return {"action": intent, "status": "butuh_info",
                            "reply_hint": reply_hint}, True

                # Kalau items kosong, simpan pending dulu dan tanya items
                if not items:
                    pending_data = {
                        "action": "add_pr_confirm",
                        "pr_step": "items",
                        "pemohon": pemohon,
                        "proyek": proyek,
                        "keperluan": keperluan,
                        "nomor": nomor,
                        "items": [],
                        "vendor": vendor,
                        "catatan": catatan,
                        "_created_at": _time.time(),
                    }
                    self.session_manager.set_pending_confirm(session_id, pending_data)
                    return {
                        "action": "pr_butuh_items",
                        "pesan": (
                            f"Baik! Data PR hampir lengkap. Sekarang, barang/jasa apa yang perlu dibeli?\n\n"
                            f"Contoh format input:\n"
                            f"- GPU RTX 4090 x1 harga Rp 16.000.000\n"
                            f"- RAM DDR5 64GB x2 @ Rp 3.500.000\n\n"
                            f"Atau ketik 'skip' kalau mau simpan tanpa items dulu."
                        )
                    }, True

                # Kalau nomor belum diisi, minta user input
                if not nomor:
                    pending_data = {
                        "action": "add_pr_confirm",
                        "pr_step": "nomor",
                        "pemohon": pemohon,
                        "proyek": proyek,
                        "keperluan": keperluan,
                        "items": items,
                        "vendor": vendor,
                        "catatan": catatan,
                        "_created_at": _time.time(),
                    }
                    self.session_manager.set_pending_confirm(session_id, pending_data)
                    return {
                        "action": "pr_butuh_nomor",
                        "pesan": (
                            f"Baik! Satu hal lagi — nomor PR-nya berapa?\n"
                            f"Contoh format: PR/Hardware/001/VII/2026\n\n"
                            f"(Format: PR/[JENIS BARANG]/[NO URUT]/[BULAN ROMAWI]/[TAHUN])"
                        )
                    }, True

                # Semua data lengkap — langsung ke final confirm
                pending_data = {
                    "action": "add_pr_confirm",
                    "pr_step": "final",
                    "pemohon": pemohon,
                    "proyek": proyek,
                    "keperluan": keperluan,
                    "nomor": nomor,
                    "items": items,
                    "vendor": vendor,
                    "catatan": catatan,
                    "_created_at": _time.time(),
                }
                self.session_manager.set_pending_confirm(session_id, pending_data)
                items_preview = ""
                if items:
                    items_preview = "\n" + "\n".join(
                        f"  - {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','Pcs')} = Rp {int(x.get('jumlah',0)):,}"
                        for x in items
                    )
                total = sum(int(x.get("jumlah", 0)) for x in items)
                return {
                    "action": "confirm_needed",
                    "reply_hint": (
                        f"Baik, saya rangkum PR sebelum disimpan:\n"
                        f"- Nomor    : {nomor}\n"
                        f"- Pemohon  : {pemohon}\n"
                        f"- Proyek   : {proyek}\n"
                        f"- Keperluan: {keperluan}\n"
                        f"- Vendor   : {vendor or '-'}\n"
                        f"- Items    : {len(items)} item{items_preview}\n"
                        + (f"- Total    : Rp {total:,}\n" if total else "")
                        + "\nAda yang perlu diubah? Atau ketik 'ya' untuk simpan 🙏"
                    )
                }, True

            if intent == "list_pr":
                status  = params.get("status", "")
                pemohon = params.get("pemohon", "")
                proyek  = params.get("proyek", "")
                pr_id   = params.get("id", "").upper()

                # Kalau ada ID spesifik — tampilkan detail satu PR
                if pr_id:
                    target = self.sm.get_pr_by_id(pr_id)
                    if not target:
                        return {"action": intent, "data": [], "total": 0,
                                "reply_hint": f"{pr_id} tidak ditemukan 📋"}, False
                    items = target.get("items", [])
                    total = sum(int(x.get("jumlah", 0)) for x in items)
                    items_str = "\n".join(
                        f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                        for i, x in enumerate(items)
                    ) if items else "   (tidak ada items)"
                    emoji = {"pending":"🕒","approved":"✅","rejected":"❌"}.get(target.get("status","pending"),"🕒")
                    reply = (
                        f"Detail {pr_id}:\n"
                        f"- Nomor    : {target.get('nomor','')}\n"
                        f"- Pemohon  : {target.get('pemohon','')}\n"
                        f"- Proyek   : {target.get('proyek','')}\n"
                        f"- Keperluan: {target.get('keperluan','')}\n"
                        f"- Status   : {emoji} {target.get('status','pending')}\n"
                        f"- Items ({len(items)}):\n{items_str}\n"
                        + (f"- Total    : Rp {total:,}\n" if total else "")
                        + f"\nMau generate dokumen? Ketik 'generate PDF {pr_id}' 📄"
                    )
                    return {"action": intent, "data": [target], "total": 1, "reply_hint": reply}, False

                data = self.sm.get_pr(status=status, pemohon=pemohon, proyek=proyek)

                # reply_hint di sini WAJIB — list_pr TIDAK generate file apapun,
                # jadi tidak boleh ada link download. Kalau dilempar ke LLM lewat
                # [HASIL EKSEKUSI], LLM cenderung ikut pola "dokumen sudah siap,
                # klik link unduh" dari system prompt padahal belum ada file yang
                # dibuat — itu sumber halusinasi link palsu.
                if not data:
                    filter_desc = []
                    if status:  filter_desc.append(f"status {status}")
                    if pemohon: filter_desc.append(f"pemohon {pemohon}")
                    if proyek:  filter_desc.append(f"proyek {proyek}")
                    ket = f" ({', '.join(filter_desc)})" if filter_desc else ""
                    return {"action": intent, "data": [], "total": 0,
                            "reply_hint": f"Belum ada data PR{ket} 📋"}, False

                status_emoji = {"pending": "🕒", "approved": "✅", "rejected": "❌"}
                baris = []
                for x in data:
                    emoji = status_emoji.get(x.get("status", "pending"), "🕒")
                    baris.append(
                        f"{emoji} {x.get('id','')} — {x.get('nomor','') or '(belum ada nomor)'}\n"
                        f"   Pemohon: {x.get('pemohon','-')} | Proyek: {x.get('proyek','-')} "
                        f"| Status: {x.get('status','pending')}"
                    )
                reply = (
                    f"Ini daftar PR yang ada ({len(data)}):\n\n"
                    + "\n".join(baris)
                    + "\n\nKalau mau lihat dokumennya, bilang \"generate PR-xxxx\" ya, nanti saya buatkan file-nya 🙏"
                )
                return {"action": intent, "data": data, "total": len(data),
                        "reply_hint": reply}, False

            if intent in ("approve_pr", "reject_pr"):
                pr_id      = params.get("id", "").strip().upper()
                new_status = "approved" if intent == "approve_pr" else "rejected"

                # Resolve: bisa PR-XXXX, nomor dokumen (PR/xxx), atau nama pemohon
                if not pr_id or not pr_id.startswith("PR-"):
                    # Coba lookup by nomor dokumen dulu (PR/Hardware/003/VII/2026)
                    raw_id = params.get("id", "").strip()
                    if raw_id.upper().startswith("PR/"):
                        all_pr = self.sm.get_pr()
                        found = next((x for x in all_pr if x.get("nomor","").lower() == raw_id.lower()), None)
                        if found:
                            pr_id = found["id"]
                        else:
                            return {"action": intent, "status": "tidak_ditemukan",
                                    "reply_hint": f"PR dengan nomor '{raw_id}' tidak ditemukan. Cek nomor dokumennya ya 🙏"}, False

                    # Fallback: coba resolve by nama pemohon
                    if not pr_id or not pr_id.startswith("PR-"):
                        pemohon_cari = params.get("pemohon", "")
                        if pemohon_cari:
                            candidates = [x for x in self.sm.get_pr(status="pending")
                                          if pemohon_cari.lower() in x.get("pemohon","").lower()]
                            if len(candidates) == 1:
                                pr_id = candidates[0]["id"]
                            elif len(candidates) > 1:
                                opts = "\n".join(f"  - {x['id']} | {x.get('nomor','')} | {x.get('pemohon','')}" for x in candidates)
                                return {"action": intent, "status": "ambigu",
                                        "reply_hint": f"Ada {len(candidates)} PR pending dari '{pemohon_cari}':\n{opts}\n\nSebutkan ID atau nomor PR yang spesifik 🙏"}, False
                            else:
                                return {"action": intent, "status": "tidak_ditemukan",
                                        "reply_hint": f"Tidak ada PR pending dari '{pemohon_cari}' 🙏"}, False
                        else:
                            return {"action": intent, "status": "butuh_id",
                                    "reply_hint": "Sebutkan ID atau nomor PR yang mau di-approve/reject (contoh: PR-0001 atau PR/Hardware/001/VII/2026) 🙏"}, False

                target = self.sm.get_pr_by_id(pr_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"{pr_id} tidak ditemukan 🙏"}, False
                if target.get("status") != "pending":
                    label = "sudah disetujui" if target.get("status") == "approved" else "sudah ditolak"
                    return {"action": intent, "status": "gagal",
                            "reply_hint": f"{pr_id} ({target.get('nomor','')}) tidak bisa diubah — {label} 🙏"}, False

                # Simpan pending confirm — jangan langsung eksekusi
                # Ini mencegah LLM generate konfirmasi sendiri tanpa state tersimpan
                import time as _t_apr
                action_word = "menyetujui" if new_status == "approved" else "menolak"
                emoji_word  = "✅" if new_status == "approved" else "❌"
                self.session_manager.set_pending_confirm(session_id, {
                    "action":      "approve_reject_pr_confirm",
                    "pr_id":       pr_id,
                    "new_status":  new_status,
                    "target":      target,
                    "_created_at": _t_apr.time(),
                })
                return {
                    "action": intent, "status": "butuh_konfirmasi",
                    "reply_hint": (
                        f"{emoji_word} Konfirmasi: {action_word} PR {pr_id}?\n"
                        f"  Nomor   : {target.get('nomor', '-')}\n"
                        f"  Pemohon : {target.get('pemohon', '-')}\n"
                        f"  Proyek  : {target.get('proyek', '-')}\n"
                        f"  Total   : Rp {int(target.get('total', 0)):,}\n\n"
                        f"Ketik 'ya' untuk konfirmasi atau 'batal' untuk batalkan 🙏"
                    )
                }, False

            if intent == "generate_pr":
                from storage.generator import generate_pr_pdf, generate_pr_docx
                pr_id  = params.get("id", "")
                fmt    = params.get("format", "pdf").lower()

                if not pr_id:
                    return {"action": intent, "status": "butuh_id",
                            "pesan": "Sebutkan ID PR yang mau digenerate (mis. PR-0001)"}, False

                # Support lookup by ID (PR-0001) atau nomor dokumen (PR/Hardware/001/VII/2026)
                pr = self.sm.get_pr_by_id(pr_id.upper()) or self.sm.get_pr_by_id(pr_id)
                if not pr:
                    # Coba cari by nomor dokumen (case-insensitive)
                    all_pr = self.sm.get_pr()
                    pr = next((x for x in all_pr if x.get("nomor","").lower() == pr_id.lower()), None)

                if not pr:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"PR dengan ID atau nomor '{pr_id}' tidak ditemukan. Cek lagi ya — gunakan ID seperti PR-0001 atau nomor dokumen lengkap 🙏"}, False

                if fmt == "docx":
                    path = generate_pr_docx(pr)
                else:
                    path = generate_pr_pdf(pr)

                fname = Path(path).name
                fmt_label = "PDF" if fmt == "pdf" else "Word (.docx)"
                return {"action": intent, "status": "berhasil", "file": fname,
                        "format": fmt, "pr_id": pr.get("id",""),
                        "reply_hint": (
                            f"✅ Dokumen {fmt_label} untuk {pr.get('id','')} sudah siap!\n"
                            f"Nomor: {pr.get('nomor','')}\n"
                            f"Silakan klik link unduh di bawah 📄"
                        )}, False

            if intent == "update_pr":
                pr_id   = params.get("id", "").strip()
                updates = params.get("updates") or {}
                if not isinstance(updates, dict): updates = {}
                updates = {k: v for k, v in updates.items() if v is not None and v != ""}

                # Resolve ID — support PR-XXXX dan nomor dokumen PR/xxx/...
                resolved_id = ""
                if pr_id.upper().startswith("PR-"):
                    resolved_id = pr_id.upper()
                elif pr_id.upper().startswith("PR/"):
                    all_pr = self.sm.get_pr()
                    found  = next((x for x in all_pr if x.get("nomor","").lower() == pr_id.lower()), None)
                    if found:
                        resolved_id = found["id"]
                    else:
                        return {"action": intent, "status": "tidak_ditemukan",
                                "reply_hint": f"PR dengan nomor '{pr_id}' tidak ditemukan 🙏"}, False

                # Kalau tidak ada ID sama sekali → minta dulu via pending
                if not resolved_id:
                    import time as _time_upd
                    self.session_manager.set_pending_confirm(session_id, {
                        "action": "update_pr_confirm", "updates": updates, "_created_at": _time_upd.time()
                    })
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID PR yang mau diupdate ya (contoh: PR-0001) 🙏"}, False
                target = self.sm.get_pr_by_id(resolved_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"{resolved_id} tidak ditemukan 🙏"}, False
                if not updates:
                    import time as _time_upd
                    self.session_manager.set_pending_confirm(session_id, {
                        "action": "update_pr_confirm", "pr_id": resolved_id, "updates": {}, "target": target,
                        "_created_at": _time_upd.time()
                    })
                    return {"action": intent, "status": "kosong",
                            "reply_hint": (
                                f"Mau update field apa dari {resolved_id} ({target.get('pemohon','')})?\n"
                                f"Contoh:\n- 'ganti pemohon jadi Budi'\n- 'ubah proyek jadi Sphere Jakarta'\n- 'ubah keperluan jadi Pembelian ATK' 🙏"
                            )}, False
                import time as _time_upd
                lines = []
                for k, v in updates.items():
                    lines.append(f"  {k}: {target.get(k,'-')} → {v}")
                self.session_manager.set_pending_confirm(session_id, {
                    "action": "update_pr_confirm", "pr_id": resolved_id, "updates": updates, "target": target,
                    "_created_at": _time_upd.time()
                })
                return {"action": "confirm_needed",
                        "reply_hint": (
                            f"Konfirmasi update {resolved_id} (a.n. {target.get('pemohon','')}):\n"
                            + "\n".join(lines) +
                            f"\n\nKetik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                        )}, True

            if intent == "edit_pr_items":
                pr_id_raw = params.get("id", "").strip()
                op        = params.get("action", "hapus").lower()
                nama_item = params.get("nama_item", "").strip()

                # Resolve nomor dokumen → PR-XXXX
                if pr_id_raw.upper().startswith("PR/"):
                    all_pr = self.sm.get_pr()
                    found  = next((x for x in all_pr if x.get("nomor","").lower() == pr_id_raw.lower()), None)
                    pr_id  = found["id"] if found else ""
                else:
                    pr_id = pr_id_raw.upper()

                if not pr_id:
                    import time as _t
                    self.session_manager.set_pending_confirm(session_id, {
                        "action": "edit_pr_items_confirm", "op": op,
                        "nama_item": nama_item, "_created_at": _t.time()
                    })
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID PR yang mau diedit itemnya (contoh: PR-0001) 🙏"}, False

                target = self.sm.get_pr_by_id(pr_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"{pr_id} tidak ditemukan 🙏"}, False

                current_items = target.get("items", [])

                if op == "hapus":
                    if not nama_item:
                        import time as _t
                        self.session_manager.set_pending_confirm(session_id, {
                            "action": "edit_pr_items_confirm", "op": "hapus",
                            "pr_id": pr_id, "nama_item": "", "fase": "butuh_nama_item",
                            "_created_at": _t.time()
                        })
                        items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                        return {"action": intent, "status": "butuh_item",
                                "reply_hint": f"Item mana yang mau dihapus dari {pr_id}?\n{items_list}\n\nSebutkan nama atau nomor urut item 🙏"}, False

                    # Resolve by index jika nama_item adalah __idx_N__
                    m_idx_token = re.match(r'^__idx_(\d+)__$', nama_item)
                    if m_idx_token:
                        idx = int(m_idx_token.group(1)) - 1
                        if 0 <= idx < len(current_items):
                            matched       = [current_items[idx]]
                            matched_indices = [idx]
                        else:
                            return {"action": intent, "status": "tidak_ditemukan",
                                    "reply_hint": f"Nomor item {idx+1} tidak ada (total {len(current_items)} item) 🙏"}, False
                    else:
                        matched         = [x for x in current_items if nama_item.lower() in x.get("nama","").lower()]
                        matched_indices = [i for i, x in enumerate(current_items) if nama_item.lower() in x.get("nama","").lower()]

                    if not matched:
                        items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                        return {"action": intent, "status": "tidak_ditemukan",
                                "reply_hint": (
                                    f"Item '{nama_item}' tidak ditemukan di {pr_id}.\n"
                                    f"Items yang ada:\n{items_list}\n\n"
                                    f"Sebutkan nama atau nomor urut item 🙏"
                                )}, False

                    if len(matched) > 1:
                        # Tampilkan dengan nomor urut asli supaya user bisa hapus by index
                        opts = "\n".join(f"  {matched_indices[i]+1}. {x.get('nama','')}" for i, x in enumerate(matched))
                        return {"action": intent, "status": "ambigu",
                                "reply_hint": (
                                    f"Ditemukan {len(matched)} item dengan nama '{nama_item}':\n{opts}\n\n"
                                    f"Sebutkan nomor urut item yang mau dihapus (contoh: 'hapus item nomor {matched_indices[0]+1}') 🙏"
                                )}, False

                    item_to_del  = matched[0]
                    item_idx_del = matched_indices[0]
                    total_lama   = sum(int(x.get("jumlah", 0)) for x in current_items)
                    total_baru   = total_lama - int(item_to_del.get("jumlah", 0))

                    import time as _t
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":     "edit_pr_items_confirm",
                        "op":         "hapus",
                        "pr_id":      pr_id,
                        "item":       item_to_del,
                        "item_index": item_idx_del,
                        "nama_item":  item_to_del.get("nama", ""),
                        "target":     target,
                        "total_baru": total_baru,
                        "fase":       "confirm",
                        "_created_at": _t.time(),
                    })
                    return {"action": "confirm_needed",
                            "reply_hint": (
                                f"Konfirmasi hapus item dari {pr_id}:\n"
                                f"- Item      : {item_to_del.get('nama','')} "
                                f"x{item_to_del.get('qty',1)} {item_to_del.get('satuan','')}\n"
                                f"- Harga     : Rp {int(item_to_del.get('jumlah',0)):,}\n"
                                f"- Total baru: Rp {total_baru:,} (dari Rp {total_lama:,})\n\n"
                                f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                            )}, True

                elif op in ("ubah", "edit", "update", "ganti"):
                    # Edit field item (nama, qty, harga) by nama atau nomor urut
                    if not nama_item:
                        import time as _t
                        self.session_manager.set_pending_confirm(session_id, {
                            "action": "edit_pr_items_confirm", "op": "ubah",
                            "pr_id": pr_id, "nama_item": "", "fase": "butuh_nama_item",
                            "_created_at": _t.time()
                        })
                        items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                        return {"action": intent, "status": "butuh_item",
                                "reply_hint": f"Item mana yang mau diubah dari {pr_id}?\n{items_list}\n\nSebutkan nama atau nomor urut item 🙏"}, False

                    # Resolve by index jika nama_item adalah __idx_N__
                    m_idx_token = re.match(r'^__idx_(\d+)__$', nama_item)
                    if m_idx_token:
                        idx = int(m_idx_token.group(1)) - 1
                        if 0 <= idx < len(current_items):
                            item_target     = current_items[idx]
                            item_target_idx = idx
                        else:
                            return {"action": intent, "status": "tidak_ditemukan",
                                    "reply_hint": f"Nomor item {idx+1} tidak ada (total {len(current_items)} item) 🙏"}, False
                    else:
                        matched         = [x for x in current_items if nama_item.lower() in x.get("nama","").lower()]
                        matched_indices = [i for i, x in enumerate(current_items) if nama_item.lower() in x.get("nama","").lower()]
                        if not matched:
                            items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                            return {"action": intent, "status": "tidak_ditemukan",
                                    "reply_hint": (
                                        f"Item '{nama_item}' tidak ditemukan di {pr_id}.\n"
                                        f"Items yang ada:\n{items_list}\n\n"
                                        f"Sebutkan nama atau nomor urut item 🙏"
                                    )}, False
                        if len(matched) > 1:
                            opts = "\n".join(f"  {matched_indices[i]+1}. {x.get('nama','')}" for i, x in enumerate(matched))
                            return {"action": intent, "status": "ambigu",
                                    "reply_hint": (
                                        f"Ditemukan {len(matched)} item dengan nama '{nama_item}':\n{opts}\n\n"
                                        f"Sebutkan nomor urut item yang mau diubah 🙏"
                                    )}, False
                        item_target     = matched[0]
                        item_target_idx = matched_indices[0]

                    # Ambil field yang mau diubah dari params
                    # PENTING: params["jumlah"] dari LLM untuk konteks ubah item
                    # selalu dianggap sebagai harga_per_unit (bukan total),
                    # karena user berkata "harga jadi 5jt" bukan "total jadi 5jt".
                    # Total (jumlah) akan dihitung ulang: harga_per_unit × qty.
                    updates_item = {}
                    if params.get("qty"):        updates_item["qty"]             = int(params["qty"])
                    if params.get("satuan"):     updates_item["satuan"]          = params["satuan"]
                    if params.get("nama_baru"):  updates_item["nama"]            = params["nama_baru"]
                    # harga_per_unit bisa datang dari key "harga_per_unit" atau "jumlah" (LLM sering pakai jumlah)
                    harga_raw = params.get("harga_per_unit") or params.get("jumlah")
                    if harga_raw:
                        updates_item["harga_perkiraan"] = int(harga_raw)

                    # Fallback: parse harga dari raw message kalau LLM tidak extract dengan benar
                    # "harga jadi 5jt", "ubah harga 23 juta", "harga per unit 5.000.000"
                    if not updates_item.get("harga_perkiraan"):
                        import re as _re
                        m_h = _re.search(
                            r'(?:harga(?:\s+per\s+unit)?|price)\s*(?:jadi|menjadi|=|:)?\s*Rp?\s*([\d.,]+)\s*(jt|juta|rb|ribu)?',
                            message, _re.I
                        )
                        if m_h:
                            angka = float(m_h.group(1).replace('.','').replace(',','.'))
                            mul   = (m_h.group(2) or "").lower()
                            harga = int(angka * 1_000_000) if mul in ('jt','juta') else \
                                    int(angka * 1_000)     if mul in ('rb','ribu') else int(angka)
                            updates_item["harga_perkiraan"] = harga

                    # Kalau tidak ada field updates dari params, minta user sebutkan
                    if not updates_item:
                        import time as _t
                        self.session_manager.set_pending_confirm(session_id, {
                            "action":     "edit_pr_items_confirm",
                            "op":         "ubah",
                            "pr_id":      pr_id,
                            "item":       item_target,
                            "item_index": item_target_idx,
                            "nama_item":  item_target.get("nama", ""),
                            "target":     target,
                            "fase":       "butuh_field_ubah",
                            "_created_at": _t.time(),
                        })
                        return {"action": intent, "status": "butuh_field",
                                "reply_hint": (
                                    f"Mau ubah apa dari item '{item_target.get('nama','')}' di {pr_id}?\n"
                                    f"Contoh:\n"
                                    f"- 'ubah qty jadi 3'\n"
                                    f"- 'ubah harga jadi 5jt'\n"
                                    f"- 'ubah nama jadi Monitor Gaming' 🙏"
                                )}, False

                    # Hitung jumlah baru kalau qty/harga berubah
                    new_item = dict(item_target)
                    new_item.update(updates_item)
                    if "qty" in updates_item or "harga_perkiraan" in updates_item:
                        new_item["jumlah"] = new_item.get("harga_perkiraan", 0) * new_item.get("qty", 1)

                    total_lama = sum(int(x.get("jumlah", 0)) for x in current_items)
                    total_baru = total_lama - int(item_target.get("jumlah", 0)) + int(new_item.get("jumlah", 0))

                    # Preview perubahan — tampilkan harga per unit dan total item
                    lines_preview = []
                    old_qty = item_target.get("qty", 1)
                    for k, v in updates_item.items():
                        old_val = item_target.get(k, "-")
                        if k == "harga_perkiraan":
                            lines_preview.append(f"  harga/unit: Rp {int(old_val):,} → Rp {int(v):,}")
                        elif k == "qty":
                            lines_preview.append(f"  qty: {old_val} → {v}")
                        elif k == "nama":
                            lines_preview.append(f"  nama: {old_val} → {v}")
                        elif k == "satuan":
                            lines_preview.append(f"  satuan: {old_val} → {v}")
                        else:
                            lines_preview.append(f"  {k}: {old_val} → {v}")
                    # Selalu tampilkan perubahan total item
                    old_total = int(item_target.get("jumlah", 0))
                    new_total_item = int(new_item.get("jumlah", 0))
                    if new_total_item != old_total:
                        lines_preview.append(f"  total item: Rp {old_total:,} → Rp {new_total_item:,}")

                    import time as _t
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":       "edit_pr_items_confirm",
                        "op":           "ubah",
                        "pr_id":        pr_id,
                        "item":         item_target,
                        "item_index":   item_target_idx,
                        "new_item":     new_item,
                        "nama_item":    item_target.get("nama", ""),
                        "target":       target,
                        "total_baru":   total_baru,
                        "fase":         "confirm",
                        "_created_at":  _t.time(),
                    })
                    return {"action": "confirm_needed",
                            "reply_hint": (
                                f"Konfirmasi ubah item di {pr_id}:\n"
                                f"Item: {item_target.get('nama','')}\n"
                                + "\n".join(lines_preview) +
                                f"\nTotal baru PR: Rp {total_baru:,}\n\n"
                                f"Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                            )}, True

                elif op == "tambah":
                    qty    = int(params.get("qty", 1)) or 1
                    satuan = params.get("satuan", "Unit")
                    nama   = params.get("nama_item", "").strip()

                    # Ambil harga — LLM bisa pass jumlah (total) atau harga_per_unit
                    harga_per_unit = int(params.get("harga_per_unit", 0) or params.get("harga", 0))
                    jumlah_total   = int(params.get("jumlah", 0))

                    # Fallback: parse "harga per unit Rp X" atau "X juta" dari raw message
                    if not harga_per_unit and not jumlah_total:
                        m_hpu = re.search(
                            r'(?:harga\s+per\s+unit|harga\s+satuan|@)\s*Rp?\s*([\d.,]+)\s*(juta|ribu|rb|jt)?',
                            message, re.I
                        )
                        if m_hpu:
                            angka = float(m_hpu.group(1).replace('.','').replace(',','.'))
                            mult  = {"juta":1_000_000,"jt":1_000_000,"ribu":1_000,"rb":1_000}.get(
                                (m_hpu.group(2) or "").lower(), 1)
                            harga_per_unit = int(angka * mult)

                    # Kalau hanya total yang ada, hitung per unit
                    if jumlah_total and not harga_per_unit:
                        harga_per_unit = jumlah_total // qty
                    # Kalau hanya per unit yang ada, hitung total
                    if harga_per_unit and not jumlah_total:
                        jumlah_total = harga_per_unit * qty

                    new_item = {
                        "nama":            nama,
                        "qty":             qty,
                        "satuan":          satuan,
                        "harga_perkiraan": harga_per_unit,
                        "jumlah":          jumlah_total,
                        "spesifikasi":     params.get("spesifikasi", ""),
                    }
                    if not new_item["nama"] or not new_item["jumlah"]:
                        return {"action": intent, "status": "butuh_info",
                                "reply_hint": (
                                    f"Untuk tambah item ke {pr_id}, sebutkan nama, jumlah unit, dan harga per unit.\n"
                                    f"Contoh: 'tambah item Monitor x2 Unit harga per unit Rp 5.000.000' 🙏"
                                )}, False

                    total_lama = sum(int(x.get("jumlah", 0)) for x in current_items)
                    total_baru = total_lama + jumlah_total
                    import time as _t
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":    "edit_pr_items_confirm",
                        "op":        "tambah",
                        "pr_id":     pr_id,
                        "item":      new_item,
                        "target":    target,
                        "total_baru": total_baru,
                        "_created_at": _t.time(),
                    })
                    return {"action": "confirm_needed",
                            "reply_hint": (
                                f"Konfirmasi tambah item ke {pr_id}:\n"
                                f"- Item          : {nama} x{qty} {satuan}\n"
                                f"- Harga per unit: Rp {harga_per_unit:,}\n"
                                f"- Total item    : Rp {jumlah_total:,}\n"
                                f"- Total baru PR : Rp {total_baru:,}\n\n"
                                f"Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                            )}, True

                return {"action": intent, "status": "tidak_dikenal",
                        "reply_hint": "Operasi tidak dikenal. Gunakan 'hapus' atau 'tambah' item 🙏"}, False

            if intent == "delete_pr":
                pr_id = params.get("id", "").upper()
                if not pr_id:
                    return {"action": intent, "status": "butuh_id",
                            "pesan": "Sebutkan ID PR yang mau dihapus (mis. PR-0001)"}, False
                target = self.sm.get_pr_by_id(pr_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "pesan": f"{pr_id} tidak ditemukan"}, False
                # Minta konfirmasi dulu sebelum hapus
                import time as _t
                self.session_manager.set_pending_confirm(session_id, {
                    "action": "delete_pr_confirmed", "id": pr_id,
                    "detail": target, "_created_at": _t.time(),
                })
                total = sum(int(x.get("jumlah", 0)) for x in target.get("items", []))
                return {"action": "confirm_needed",
                        "reply_hint": (
                            f"⚠️ Konfirmasi hapus {pr_id}:\n"
                            f"- Nomor   : {target.get('nomor','')}\n"
                            f"- Pemohon : {target.get('pemohon','')}\n"
                            f"- Proyek  : {target.get('proyek','')}\n"
                            + (f"- Total   : Rp {total:,}\n" if total else "")
                            + f"\nKetik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                        )}, True

            if intent == "delete_all_pr":
                all_pr = self.sm.get_pr()
                count = len(all_pr)
                if count == 0:
                    return {"action": intent, "status": "kosong",
                            "pesan": "Tidak ada data PR yang perlu dihapus."}, False
                # Minta konfirmasi dulu
                pending_data = {
                    "action": "delete_all_pr_confirmed",
                    "count": count,
                    "_created_at": _time.time(),
                }
                self.session_manager.set_pending_confirm(session_id, pending_data)
                preview = "\n".join(
                    f"- {x.get('id','')} | {x.get('nomor','')} | {x.get('pemohon','')} | {x.get('status','')}"
                    for x in all_pr[:5]
                )
                if count > 5:
                    preview += f"\n... dan {count-5} PR lainnya"
                return {
                    "action": "confirm_needed",
                    "reply_hint": (
                        f"⚠️ Kamu yakin mau hapus SEMUA {count} data PR?\n\n"
                        f"{preview}\n\n"
                        "Ketik 'ya' untuk konfirmasi hapus semua, atau 'batal' untuk batalkan."
                    )
                }, True

            # ── PURCHASE ORDER ────────────────────────────────────────────
            # ── Handler: update_po (field-level: vendor, nomor, proyek, catatan) ──
            if intent == "update_po":
                po_id   = params.get("id", "").strip().upper()
                updates = params.get("updates", {})

                # Recover PO ID dari history kalau kosong
                if not po_id:
                    _hist_upo = " ".join(h.get("content","") for h in self.session_manager.get_history(session_id)[-10:])
                    m_upo = re.search(r'\b(PO-\d+)\b', _hist_upo, re.IGNORECASE)
                    if m_upo:
                        po_id = m_upo.group(1).upper()

                if not po_id:
                    return {"reply_hint": "❌ Sebutkan ID PO yang mau diedit (contoh: PO-0001) 🙏", "skill_used": "po", "generated_file": None}, False

                current_po = self.sm.get_po_by_id(po_id)
                if not current_po:
                    return {"reply_hint": f"❌ PO {po_id} tidak ditemukan 🙏", "skill_used": "po", "generated_file": None}, False

                # Kalau updates kosong, coba parse dari message
                if not updates:
                    _field_map_po = {
                        "vendor": "vendor_nama", "vendor_nama": "vendor_nama", "nama vendor": "vendor_nama",
                        "nomor": "nomor", "nomor po": "nomor",
                        "proyek": "proyek", "project": "proyek",
                        "catatan": "catatan", "keterangan": "catatan", "note": "catatan",
                        "alamat vendor": "vendor_alamat", "vendor_alamat": "vendor_alamat",
                        "attn": "vendor_attn", "attention": "vendor_attn",
                    }
                    _msg_u = message
                    for _raw_f, _mapped_f in _field_map_po.items():
                        m_f = re.search(
                            rf'(?:{re.escape(_raw_f)})\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$|,)',
                            _msg_u, re.I
                        )
                        if m_f:
                            updates[_mapped_f] = m_f.group(1).strip()

                if not updates:
                    return {"reply_hint": (
                        f"Apa yang mau diubah dari {po_id}?\n\n"
                        f"Field yang bisa diedit:\n"
                        f"  • vendor_nama (nama vendor)\n"
                        f"  • nomor (nomor PO)\n"
                        f"  • proyek\n"
                        f"  • catatan\n\n"
                        f"Contoh: 'ubah vendor {po_id} menjadi PT Sinar Jaya' 🙏"
                    ), "skill_used": "po", "generated_file": None}, False

                result = self.sm.update_po(po_id, updates)
                if not result:
                    return {"reply_hint": f"❌ Gagal update {po_id} 🙏", "skill_used": "po", "generated_file": None}, False

                changed = "\n".join(f"  • {k}: {v}" for k, v in updates.items())
                print(f"[{AGENT_NAME}] update_po OK: po={po_id} updates={updates}")
                return {"reply_hint": (
                    f"✅ {po_id} berhasil diperbarui!\n\n"
                    f"Perubahan:\n{changed}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {po_id}' 📄"
                ), "skill_used": "po", "generated_file": None}, False

            if intent == "add_po":
                # Kumpulkan data PO dari params
                vendor_nama   = params.get("vendor_nama", "").strip()
                vendor_alamat = params.get("vendor_alamat", "").strip()
                vendor_attn   = params.get("vendor_attn", "").strip()
                nomor         = params.get("nomor", "").strip()
                proyek        = params.get("proyek", "").strip()
                ref           = params.get("ref", "").strip()
                items         = params.get("items", [])
                pr_id_src     = params.get("pr_id", "").strip().upper()
                catatan       = params.get("catatan", "").strip()

                # Fallback: kalau pr_id kosong tapi ada 'id' yang bentuknya PR-XXXX
                if not pr_id_src:
                    _raw_id = params.get("id", "").strip().upper()
                    if _raw_id.startswith("PR-"):
                        pr_id_src = _raw_id

                # Jika dari PR → pre-fill data dari PR
                if pr_id_src:
                    src_pr = self.sm.get_pr_by_id(pr_id_src)
                    if not src_pr:
                        return {"action": intent, "status": "tidak_ditemukan",
                                "reply_hint": f"PR {pr_id_src} tidak ditemukan 🙏"}, False
                    if src_pr.get("status") != "approved":
                        return {"action": intent, "status": "gagal",
                                "reply_hint": f"PR {pr_id_src} belum di-approve — PO hanya bisa dibuat dari PR yang sudah disetujui 🙏"}, False
                    if not proyek:    proyek        = src_pr.get("proyek", "")
                    if not items:     items         = src_pr.get("items", [])
                    if not vendor_nama: vendor_nama = src_pr.get("vendor", "")

                # Validasi data wajib
                missing = []
                if not vendor_nama:   missing.append("nama vendor")
                if not nomor:         missing.append("nomor PO (contoh: PO/VII/2026/OPR/001)")
                # items hanya wajib kalau BUKAN dari PR (kalau dari PR, sudah diambil di atas)
                if not items and not pr_id_src:
                    missing.append("daftar item/barang")

                if missing:
                    import time as _t_po

                    # Tentukan step pertama yang perlu ditanyakan
                    if not vendor_nama:
                        waiting_for = "vendor_nama"
                        if pr_id_src and items:
                            # Konteks: dari PR, items sudah ada — hanya tanya vendor dulu
                            item_count = len(items)
                            total_pr = sum(int(x.get("jumlah", 0)) for x in items)
                            hint = (
                                f"🛒 Buat PO dari {pr_id_src} ({src_pr.get('nomor','')})\n"
                                f"  Proyek : {proyek}\n"
                                f"  Items  : {item_count} item — Total Rp {total_pr:,}\n\n"
                                f"Masukkan nama vendor/supplier 🙏"
                            )
                        else:
                            hint = (
                                f"🛒 Siap buat PO baru! Data yang masih kurang:\n"
                                + "\n".join(f"  • {m}" for m in missing)
                                + "\n\nMulai dari nama vendor/supplier 🙏"
                            )
                    elif not nomor:
                        waiting_for = "nomor"
                        hint = (
                            f"✅ Vendor: {vendor_nama}\n\n"
                            f"Sekarang masukkan nomor PO\n"
                            f"Contoh: PO/VII/2026/OPR/001 🙏"
                        )
                    else:
                        waiting_for = "items"
                        hint = "Masukkan daftar item/barang yang akan dipesan 🙏"

                    self.session_manager.set_pending_confirm(session_id, {
                        "action":        "add_po_collect",
                        "vendor_nama":   vendor_nama,
                        "vendor_alamat": vendor_alamat,
                        "vendor_attn":   vendor_attn,
                        "nomor":         nomor,
                        "proyek":        proyek,
                        "ref":           ref,
                        "items":         items,
                        "pr_id":         pr_id_src,
                        "catatan":       catatan,
                        "missing":       missing,
                        "waiting_for":   waiting_for,
                        "_created_at":   _t_po.time(),
                    })
                    return {
                        "action": intent, "status": "butuh_data",
                        "reply_hint": hint
                    }, False

                # Semua data sudah ada → minta konfirmasi
                total = sum(int(x.get("jumlah", 0)) for x in items)
                item_preview = "\n".join(
                    f"  {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(items)
                )
                import time as _t_po2
                self.session_manager.set_pending_confirm(session_id, {
                    "action":        "add_po_confirm",
                    "vendor_nama":   vendor_nama,
                    "vendor_alamat": vendor_alamat,
                    "vendor_attn":   vendor_attn,
                    "nomor":         nomor,
                    "proyek":        proyek,
                    "ref":           ref,
                    "items":         items,
                    "pr_id":         pr_id_src,
                    "catatan":       catatan,
                    "_created_at":   _t_po2.time(),
                })
                return {
                    "action": intent, "status": "butuh_konfirmasi",
                    "reply_hint": (
                        f"🛒 Rangkuman PO sebelum disimpan:\n"
                        f"  Nomor PO : {nomor}\n"
                        f"  Vendor   : {vendor_nama}\n"
                        f"  Alamat   : {vendor_alamat or '-'}\n"
                        f"  Attn     : {vendor_attn or '-'}\n"
                        f"  REF#     : {ref or '-'}\n"
                        f"  Proyek   : {proyek or '-'}\n"
                        f"  Items ({len(items)}):\n{item_preview}\n"
                        f"  Total    : Rp {total:,}\n\n"
                        f"Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                    )
                }, False

            if intent == "list_po":
                status_filter = params.get("status", "").lower()
                data = self.sm.get_po(status=status_filter)
                if not data:
                    label = f" dengan status '{status_filter}'" if status_filter else ""
                    return {"action": intent, "data": [], "total": 0,
                            "reply_hint": f"Belum ada data PO{label} 📋"}, False
                items_preview = []
                for po in data:
                    st = po.get("status", "pending")
                    em = {"pending": "🕒", "approved": "✅", "rejected": "❌"}.get(st, "🕒")
                    items_preview.append(
                        f"  {em} {po.get('id','')} | {po.get('nomor','')}\n"
                        f"     Vendor: {po.get('vendor_nama','')} | Total: Rp {int(po.get('total',0)):,}"
                    )
                return {
                    "action": intent, "data": data, "total": len(data),
                    "reply_hint": (
                        f"📋 Daftar Purchase Order ({len(data)} PO):\n\n"
                        + "\n\n".join(items_preview)
                    )
                }, False

            if intent == "detail_po":
                po_id = params.get("id", "").strip().upper()
                if not po_id:
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID PO yang mau dilihat (contoh: PO-0001) 🙏"}, False
                po = self.sm.get_po_by_id(po_id)
                if not po:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"PO '{po_id}' tidak ditemukan 🙏"}, False
                st = po.get("status", "pending")
                em = {"pending": "🕒", "approved": "✅", "rejected": "❌"}.get(st, "🕒")
                items = po.get("items", [])
                item_lines = "\n".join(
                    f"  {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(items)
                )
                return {
                    "action": intent, "data": po,
                    "reply_hint": (
                        f"Detail {po.get('id','')}:\n"
                        f"  Nomor    : {po.get('nomor','')}\n"
                        f"  Vendor   : {po.get('vendor_nama','')}\n"
                        f"  Alamat   : {po.get('vendor_alamat','-')}\n"
                        f"  Attn     : {po.get('vendor_attn','-')}\n"
                        f"  REF#     : {po.get('ref','-')}\n"
                        f"  Proyek   : {po.get('proyek','-')}\n"
                        f"  Status   : {em} {st}\n"
                        f"  Tanggal  : {po.get('tanggal','')}\n"
                        f"  Items ({len(items)}):\n{item_lines}\n"
                        f"  Total    : Rp {int(po.get('total',0)):,}\n\n"
                        f"Mau generate dokumen? Ketik 'generate PO {po.get('id','')}' 📄"
                    )
                }, False

            if intent in ("approve_po", "reject_po"):
                po_id      = params.get("id", "").strip().upper()
                new_status = "approved" if intent == "approve_po" else "rejected"
                if not po_id or not po_id.startswith("PO-"):
                    all_po = self.sm.get_po(status="pending")
                    vendor_cari = params.get("vendor", "")
                    if vendor_cari:
                        candidates = [x for x in all_po if vendor_cari.lower() in x.get("vendor_nama","").lower()]
                        if len(candidates) == 1:
                            po_id = candidates[0]["id"]
                        else:
                            return {"action": intent, "status": "butuh_id",
                                    "reply_hint": "Sebutkan ID PO yang mau di-approve/reject (contoh: PO-0001) 🙏"}, False
                    else:
                        return {"action": intent, "status": "butuh_id",
                                "reply_hint": "Sebutkan ID PO yang mau di-approve/reject (contoh: PO-0001) 🙏"}, False
                target = self.sm.get_po_by_id(po_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"PO {po_id} tidak ditemukan 🙏"}, False
                if target.get("status") != "pending":
                    label = "sudah disetujui" if target.get("status") == "approved" else "sudah ditolak"
                    return {"action": intent, "status": "gagal",
                            "reply_hint": f"PO {po_id} tidak bisa diubah — {label} 🙏"}, False
                import time as _t_apo
                em = "✅" if new_status == "approved" else "❌"
                action_word = "menyetujui" if new_status == "approved" else "menolak"
                self.session_manager.set_pending_confirm(session_id, {
                    "action":     "approve_reject_po_confirm",
                    "po_id":      po_id,
                    "new_status": new_status,
                    "target":     target,
                    "_created_at": _t_apo.time(),
                })
                return {
                    "action": intent, "status": "butuh_konfirmasi",
                    "reply_hint": (
                        f"{em} Konfirmasi: {action_word} PO {po_id}?\n"
                        f"  Nomor  : {target.get('nomor','-')}\n"
                        f"  Vendor : {target.get('vendor_nama','-')}\n"
                        f"  Total  : Rp {int(target.get('total',0)):,}\n\n"
                        f"Ketik 'ya' untuk konfirmasi atau 'batal' untuk batalkan 🙏"
                    )
                }, False

            if intent == "generate_po":
                from storage.generator import generate_po_pdf, generate_po_docx
                po_id = params.get("id", "").strip().upper()
                fmt   = params.get("format", "docx").lower()
                if not po_id:
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID PO yang mau digenerate (contoh: PO-0001) 🙏"}, False
                po = self.sm.get_po_by_id(po_id)
                if not po:
                    all_po = self.sm.get_po()
                    po = next((x for x in all_po if x.get("nomor","").upper() == po_id), None)
                if not po:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"PO '{po_id}' tidak ditemukan 🙏"}, False
                if fmt in ("pdf",):
                    path = generate_po_pdf(po)
                else:
                    path = generate_po_docx(po)
                fname = Path(path).name
                return {
                    "action": intent, "status": "berhasil",
                    "generated_file": fname,
                    "reply_hint": (
                        f"✅ Dokumen {'PDF' if fmt == 'pdf' else 'Word (.docx)'} untuk {po_id} sudah siap!\n"
                        f"Nomor : {po.get('nomor','')}\n"
                        f"Vendor: {po.get('vendor_nama','')}\n"
                        f"Total : Rp {int(po.get('total',0)):,}\n\n"
                        f"Silakan klik tombol unduh di bawah 📄"
                    )
                }, False


            if intent == "delete_po":
                po_id = params.get("id", "").strip().upper()
                if not po_id:
                    return {"action": intent, "status": "butuh_id",
                            "reply_hint": "Sebutkan ID PO yang mau dihapus (contoh: PO-0001) 🙏"}, False
                target = self.sm.get_po_by_id(po_id)
                if not target:
                    return {"action": intent, "status": "tidak_ditemukan",
                            "reply_hint": f"PO {po_id} tidak ditemukan 🙏"}, False
                # Minta konfirmasi sebelum hapus
                import time as _t_del_po
                self.session_manager.set_pending_confirm(session_id, {
                    "action":     "delete_po_confirm",
                    "po_id":      po_id,
                    "target":     target,
                    "_created_at": _t_del_po.time(),
                })
                return {
                    "action": intent, "status": "butuh_konfirmasi",
                    "reply_hint": (
                        f"⚠️ Konfirmasi hapus PO {po_id}?\n"
                        f"  Nomor  : {target.get('nomor','-')}\n"
                        f"  Vendor : {target.get('vendor_nama','-')}\n"
                        f"  Total  : Rp {int(target.get('total',0)):,}\n\n"
                        f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                    )
                }, False

            # ── QUOTATION ─────────────────────────────────────────────────────
            if self._qt_handler and intent in (
                "add_qt","list_qt","update_qt","delete_qt",
                "approve_qt","reject_qt","generate_qt"
            ):
                try:
                    if intent == "add_qt":
                        return self._qt_handler.handle_add_qt(session_id, params)
                    if intent == "list_qt":
                        return self._qt_handler.handle_list_qt(session_id, params)
                    if intent == "update_qt":
                        return self._qt_handler.handle_update_qt(session_id, params, message)
                    if intent == "delete_qt":
                        return self._qt_handler.handle_delete_qt(session_id, params)
                    if intent == "approve_qt":
                        return self._qt_handler.handle_approve_qt(session_id, params)
                    if intent == "reject_qt":
                        return self._qt_handler.handle_reject_qt(session_id, params)
                    if intent == "generate_qt":
                        result, needs_confirm = self._qt_handler.handle_generate_qt(
                            session_id, params, self._qt_gen
                        )
                        gen_file = result.pop("generated_file", None)
                        if gen_file:
                            result["generated_file"] = Path(gen_file).name
                        return result, needs_confirm
                except Exception as _qt_err:
                    import traceback as _tb
                    print(f"[{AGENT_NAME}] ❌ QT handler error ({intent}): {_qt_err}")
                    _tb.print_exc()
                    return {"reply_hint": f"❌ Terjadi error di modul Quotation: {_qt_err}\nMohon coba lagi atau hubungi admin. 🙏", "skill_used": "quotation", "generated_file": None}, False

            # ── INVOICE ──────────────────────────────────────────────────────
            if self._inv_handler and intent in (
                "add_inv","list_inv","update_inv","delete_inv",
                "generate_inv","mark_paid","mark_issued"
            ):
                try:
                    if intent == "add_inv":
                        return self._inv_handler.handle_add_inv(session_id, params)
                    if intent == "list_inv":
                        return self._inv_handler.handle_list_inv(session_id, params)
                    if intent == "update_inv":
                        return self._inv_handler.handle_update_inv(session_id, params, message)
                    if intent == "delete_inv":
                        return self._inv_handler.handle_delete_inv(session_id, params)
                    if intent == "mark_paid":
                        return self._inv_handler.handle_mark_paid(session_id, params)
                    if intent == "mark_issued":
                        return self._inv_handler.handle_mark_issued(session_id, params)
                    if intent == "generate_inv":
                        import importlib, sys as _sys
                        # Coba import dengan berbagai path
                        _inv_gen = None
                        for _mod_name in ("agent.invoice_generator", "invoice_generator"):
                            try:
                                _inv_gen = importlib.import_module(_mod_name)
                                break
                            except ImportError:
                                pass
                        if _inv_gen is None:
                            # Fallback: load langsung dari file
                            import importlib.util as _ilu
                            _gen_candidates = [
                                os.path.join(_PROJECT_ROOT, "agent", "invoice_generator.py"),
                                os.path.join(os.path.dirname(__file__), "invoice_generator.py"),
                            ]
                            for _gc in _gen_candidates:
                                if os.path.exists(_gc):
                                    _spec = _ilu.spec_from_file_location("invoice_generator", _gc)
                                    _inv_gen = _ilu.module_from_spec(_spec)
                                    _spec.loader.exec_module(_inv_gen)
                                    break
                        if _inv_gen is None:
                            return {"reply_hint": "❌ Invoice generator tidak ditemukan. Pastikan invoice_generator.py ada di folder agent/ 🙏", "skill_used": "invoice", "generated_file": None}, False
                        result, needs_confirm = self._inv_handler.handle_generate_inv(
                            session_id, params, _inv_gen
                        )
                        gen_file = result.pop("generated_file", None)
                        if gen_file:
                            result["generated_file"] = Path(gen_file).name
                        return result, needs_confirm
                except Exception as _inv_err:
                    import traceback as _tb
                    print(f"[{AGENT_NAME}] ❌ INV handler error ({intent}): {_inv_err}")
                    _tb.print_exc()
                    return {"reply_hint": f"❌ Terjadi error di modul Invoice: {_inv_err}\nMohon coba lagi atau hubungi admin. 🙏", "skill_used": "invoice", "generated_file": None}, False

            # ── GENERATE ──────────────────────────────────────────────────────
            if intent in ("generate_excel", "generate_pdf"):
                from storage.generator import generate_excel_finance, generate_pdf_finance
                data   = self.sm.get_finance()
                jenis  = params.get("jenis", "")
                status = params.get("status", "")
                bulan  = params.get("bulan", 0)
                tahun  = params.get("tahun", 0)

                # Kalau tidak ada bulan — tanya dulu sebelum generate
                if not bulan:
                    fmt = "excel" if intent == "generate_excel" else "pdf"
                    self.session_manager.set_pending_confirm(session_id, {
                        "action":  "ask_export_bulan",
                        "fmt":     fmt,
                        "jenis":   jenis,
                        "status":  status,
                        "tahun":   tahun or int(datetime.now().strftime("%Y")),
                    })
                    now = datetime.now()
                    return {
                        "action": "ask_export_bulan",
                        "reply_hint": (
                            f"📅 Laporan keuangan format **{fmt.upper()}** — bulan mana yang ingin di-export?\n\n"
                            f"Contoh: *Juli*, *Juni 2026*, atau *bulan ini*"
                        )
                    }, True

                # Apply filters
                if jenis:  data = [x for x in data if jenis.lower()  in x.get("jenis",  "").lower()]
                if status: data = [x for x in data if status.lower() in x.get("status", "").lower()]
                if bulan:
                    bulan_str = f"-{str(bulan).zfill(2)}-"
                    data = [x for x in data if bulan_str in x.get("created_at", "")]
                if tahun:
                    data = [x for x in data if str(tahun) in x.get("created_at", "")]

                # Hitung breakdown termasuk invoice
                inv_entries = [x for x in data if x.get("jenis") == "invoice"]
                non_inv     = [x for x in data if x.get("jenis") != "invoice"]

                if intent == "generate_excel":
                    path = generate_excel_finance(data)
                else:
                    path = generate_pdf_finance(data)

                fname = Path(path).name
                fmt_label = "Excel" if intent == "generate_excel" else "PDF"
                filter_desc = []
                if jenis:  filter_desc.append(jenis)
                if status: filter_desc.append(status)
                if bulan:  filter_desc.append(f"bulan {bulan}")
                if tahun:  filter_desc.append(str(tahun))
                scope = f" ({', '.join(filter_desc)})" if filter_desc else " (semua data)"

                inv_note = f"\n  📄 Invoice paid: {len(inv_entries)} transaksi (Rp {sum(x.get('jumlah',0) for x in inv_entries):,.0f})" if inv_entries else ""

                return {"action": intent, "status": "berhasil", "file": fname,
                        "total_data": len(data),
                        "reply_hint": (
                            f"✅ Laporan keuangan {fmt_label}{scope} sudah siap!\n"
                            f"Total data: {len(data)} transaksi"
                            f"{inv_note}\n\n"
                            f"Silakan klik tombol unduh di bawah untuk download file 📥"
                        ),
                        "filters": {"jenis": jenis, "status": status, "bulan": bulan, "tahun": tahun}
                        }, False

        except Exception as e:
            import traceback
            print(f"[{AGENT_NAME}] Execute intent error: {e}")
            traceback.print_exc()
            return {"action": intent, "status": "error", "pesan": str(e)}, False

        return None, False

    async def _handle_confirm(self, session_id: str, message: str, pending: dict) -> dict | None:
        """Handle konfirmasi ya/tidak dari user."""
        import time as _time  # diperlukan untuk refresh _created_at di PR step transitions
        action = pending.get("action", "")
        msg_up = message.upper().strip()

        # ── Handler: Budget multi-step flows ─────────────────────────────────
        BUDGET_FLOWS = {"add_budget_project", "add_budget_ops", "link_expense", "delete_budget"}
        if action in BUDGET_FLOWS and self._bud_handler and self._bud_handler.has_active_session(session_id):
            reply = self._bud_handler._continue_collect(message, session_id)
            self.session_manager.add_message(session_id, "user", message)
            self.session_manager.add_message(session_id, "assistant", reply)
            # Clear pending setelah budget handler selesai (jika sesi sudah tidak ada)
            if not self._bud_handler.has_active_session(session_id):
                self.session_manager.clear_pending_confirm(session_id)
            return {"reply": reply, "skill_used": "budget", "generated_file": None}

        # ── Handler: ask_export_bulan — tanya bulan untuk export laporan ─────
        if action == "ask_export_bulan":
            _bulan_map = {
                "januari":1,"februari":2,"maret":3,"april":4,"mei":5,"juni":6,
                "juli":7,"agustus":8,"september":9,"oktober":10,"november":11,"desember":12
            }
            msg_l  = message.lower().strip()
            bulan  = 0
            tahun  = pending.get("tahun", int(datetime.now().strftime("%Y")))
            fmt    = pending.get("fmt", "excel")
            jenis  = pending.get("jenis", "")
            status = pending.get("status", "")

            # Parse bulan dari jawaban user
            if "ini" in msg_l or "this" in msg_l or "sekarang" in msg_l:
                bulan = int(datetime.now().strftime("%m"))
                tahun = int(datetime.now().strftime("%Y"))
            else:
                for nama, num in _bulan_map.items():
                    if nama in msg_l:
                        bulan = num
                        break
                _m_tahun = re.search(r'\b(202[0-9])\b', message)
                if _m_tahun:
                    tahun = int(_m_tahun.group(1))

            if not bulan:
                return {"reply": (
                    "❓ Bulan tidak dikenali. Coba sebutkan nama bulan, contoh:\n"
                    "*Juli*, *Juni 2026*, atau *bulan ini*"
                ), "skill_used": "finance", "generated_file": None}

            # Bulan sudah dapat — generate langsung
            self.session_manager.clear_pending_confirm(session_id)
            from storage.generator import generate_excel_finance, generate_pdf_finance
            from pathlib import Path as _Path
            data = self.sm.get_finance()
            if jenis:  data = [x for x in data if jenis.lower() in x.get("jenis","").lower()]
            if status: data = [x for x in data if status.lower() in x.get("status","").lower()]
            bulan_str = f"-{str(bulan).zfill(2)}-"
            data = [x for x in data if bulan_str in x.get("created_at","") and str(tahun) in x.get("created_at","")]
            path = generate_excel_finance(data) if fmt == "excel" else generate_pdf_finance(data)
            fname = _Path(path).name
            fmt_label = "Excel" if fmt == "excel" else "PDF"
            _bulan_names = {1:"Januari",2:"Februari",3:"Maret",4:"April",5:"Mei",6:"Juni",
                            7:"Juli",8:"Agustus",9:"September",10:"Oktober",11:"November",12:"Desember"}
            inv_entries = [x for x in data if x.get("jenis") == "invoice"]
            inv_note = f"\n  📄 Invoice paid: {len(inv_entries)} transaksi" if inv_entries else ""
            reply_hint = (
                f"✅ Laporan keuangan {fmt_label} **{_bulan_names.get(bulan,'')} {tahun}** sudah siap!\n"
                f"Total data: {len(data)} transaksi{inv_note}\n\n"
                f"Silakan klik tombol unduh di bawah 📥"
            )
            return {
                "action": f"generate_{fmt}", "status": "berhasil", "file": fname,
                "total_data": len(data),
                "reply_hint": reply_hint,
                "filters": {"jenis": jenis, "status": status, "bulan": bulan, "tahun": tahun},
                "skill_used": "finance", "generated_file": fname
            }

        # ── Handler: add_po_confirm ──────────────────────────────────────────
        if action in ("add_po_confirm", "add_po_collect"):
            is_batal = bool(re.search(r'\b(BATAL|CANCEL|TIDAK|GAK|NO)\b', msg_up))
            is_yes   = bool(re.search(r'\b(YA|IYA|YES|OKE|OK|SETUJU|YAP|SIP|BETUL|BENAR)\b', msg_up))

            vendor_nama   = pending.get("vendor_nama", "")
            vendor_alamat = pending.get("vendor_alamat", "")
            vendor_attn   = pending.get("vendor_attn", "")
            nomor         = pending.get("nomor", "")
            proyek        = pending.get("proyek", "")
            ref           = pending.get("ref", "")
            items         = pending.get("items", [])
            pr_id         = pending.get("pr_id", "")
            catatan       = pending.get("catatan", "")

            if is_batal:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Pembuatan PO dibatalkan. 😊", "skill_used": "po", "generated_file": None}

            # Kalau masih ada data yang kurang → step-by-step collection
            if action == "add_po_collect":
                import time as _t_poc
                msg_raw = message.strip()

                # Tentukan field mana yang sedang ditunggu (step saat ini)
                waiting_for = pending.get("waiting_for", "")

                # ── Step: tunggu nomor PO ──
                if waiting_for == "nomor" or (not nomor and not waiting_for):
                    m_nomor = re.search(r'(PO/[A-Za-z0-9]+/\d{4}/[A-Za-z0-9]+/\d+)', msg_raw, re.I)
                    if m_nomor:
                        nomor = m_nomor.group(1).upper()
                        pending["nomor"] = nomor
                        pending["waiting_for"] = "vendor_nama" if not vendor_nama else ""
                        pending["_created_at"] = _t_poc.time()
                        self.session_manager.set_pending_confirm(session_id, pending)
                        if not vendor_nama:
                            return {"reply": (
                                f"✅ Nomor PO: {nomor}\n\n"
                                f"Sekarang masukkan nama vendor/supplier 🙏"
                            ), "skill_used": "po", "generated_file": None}
                    else:
                        # Input tidak valid sebagai nomor PO — mungkin ini vendor nama?
                        if not vendor_nama and not re.search(r'^PO/', msg_raw, re.I):
                            vendor_nama = msg_raw.title()
                            pending["vendor_nama"] = vendor_nama
                            pending["waiting_for"] = "nomor"
                            pending["_created_at"] = _t_poc.time()
                            self.session_manager.set_pending_confirm(session_id, pending)
                            return {"reply": (
                                f"✅ Vendor: {vendor_nama}\n\n"
                                f"Sekarang masukkan nomor PO\n"
                                f"Contoh: PO/VII/2026/OPR/001 🙏"
                            ), "skill_used": "po", "generated_file": None}
                        pending["waiting_for"] = "nomor"
                        self.session_manager.set_pending_confirm(session_id, pending)
                        return {"reply": (
                            f"Format nomor PO tidak dikenali.\n"
                            f"Contoh: PO/VII/2026/OPR/001\n\n"
                            f"Masukkan nomor PO 🙏"
                        ), "skill_used": "po", "generated_file": None}

                # ── Step: tunggu vendor nama ──
                elif waiting_for == "vendor_nama" or (not vendor_nama and nomor):
                    vendor_nama = msg_raw.strip()
                    pending["vendor_nama"] = vendor_nama
                    pending["waiting_for"] = ""
                    pending["_created_at"] = _t_poc.time()
                    self.session_manager.set_pending_confirm(session_id, pending)

                # ── Step: tunggu items ──
                elif waiting_for == "items" or (vendor_nama and nomor and not items and not pr_id):
                    parsed_items = self._parse_pr_items(msg_raw)
                    if parsed_items:
                        items = parsed_items
                        pending["items"] = items
                        pending["waiting_for"] = ""
                        pending["_created_at"] = _t_poc.time()
                        self.session_manager.set_pending_confirm(session_id, pending)
                    else:
                        pending["waiting_for"] = "items"
                        pending["_created_at"] = _t_poc.time()
                        self.session_manager.set_pending_confirm(session_id, pending)
                        return {"reply": (
                            "Format item tidak terbaca. Coba format seperti ini:\n"
                            "1. Nama Item 1 unit harga per unit Rp 50.000.000\n"
                            "2. Nama Item 2 x2 unit harga per unit Rp 5.000.000 \U0001f64f"
                        ), "skill_used": "po", "generated_file": None}

                # Re-check missing setelah update
                # Items tidak wajib kalau ada pr_id (sudah diambil dari PR)
                missing = []
                if not nomor:        missing.append("nomor PO (contoh: PO/VII/2026/OPR/001)")
                if not vendor_nama:  missing.append("nama vendor/supplier")
                if not items and not pr_id:
                    missing.append("daftar item/barang")
                if missing:
                    next_field = missing[0]
                    next_waiting = "nomor" if "nomor" in next_field else ("vendor_nama" if "vendor" in next_field else "items")
                    pending["waiting_for"] = next_waiting
                    pending["_created_at"] = _t_poc.time()
                    self.session_manager.set_pending_confirm(session_id, pending)
                    # Reply yang lebih ramah sesuai konteks
                    if "nomor" in next_field:
                        reply_text = f"Masukkan nomor PO\nContoh: PO/VII/2026/OPR/001 🙏"
                    elif "vendor" in next_field:
                        reply_text = f"Masukkan nama vendor/supplier 🙏"
                    else:
                        reply_text = f"Masukkan daftar item/barang yang dipesan 🙏"
                    return {"reply": reply_text, "skill_used": "po", "generated_file": None}

                # Semua data sudah ada → tampilkan konfirmasi
                pending["action"] = "add_po_confirm"
                pending["vendor_nama"] = vendor_nama
                pending["nomor"] = nomor
                pending["_created_at"] = _t_poc.time()
                self.session_manager.set_pending_confirm(session_id, pending)
                total = sum(int(x.get("jumlah", 0)) for x in items)
                item_preview = "\n".join(
                    f"  {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(items)
                )
                return {"reply": (
                    f"🛒 Rangkuman PO sebelum disimpan:\n"
                    f"  Nomor PO : {nomor}\n"
                    f"  Vendor   : {vendor_nama}\n"
                    f"  Alamat   : {vendor_alamat or '-'}\n"
                    f"  Attn     : {vendor_attn or '-'}\n"
                    f"  REF#     : {ref or '-'}\n"
                    f"  Proyek   : {proyek or '-'}\n"
                    f"  Items ({len(items)}):\n{item_preview}\n"
                    f"  Total    : Rp {total:,}\n\n"
                    f"Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "po", "generated_file": None}

            if not is_yes:
                return {"reply": "Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏",
                        "skill_used": "po", "generated_file": None}

            # Simpan PO
            result = self.sm.add_po(
                nomor=nomor, vendor_nama=vendor_nama,
                vendor_alamat=vendor_alamat, vendor_attn=vendor_attn,
                proyek=proyek, ref=ref, items=items,
                pr_id=pr_id, catatan=catatan,
            )
            self.session_manager.clear_pending_confirm(session_id)
            total = int(result.get("total", 0))
            print(f"[{AGENT_NAME}] add_po: {result['id']} disimpan ✅")
            return {"reply": (
                f"✅ Purchase Order berhasil disimpan!\n"
                f"  ID     : {result['id']}\n"
                f"  Nomor  : {result['nomor']}\n"
                f"  Vendor : {result['vendor_nama']}\n"
                f"  Proyek : {result.get('proyek','-')}\n"
                f"  Status : Pending ⏳\n"
                f"  Total  : Rp {total:,}\n\n"
                f"Untuk generate dokumen Word, ketik 'generate PO {result['id']}' 📄"
            ), "skill_used": "po", "generated_file": None}

        # ── Handler: delete_po_confirm ───────────────────────────────────────
        if action == "delete_po_confirm":
            po_id  = pending.get("po_id", "")
            target = pending.get("target", {})
            is_batal = bool(re.search(r'\b(BATAL|CANCEL|TIDAK|GAK|NO)\b', msg_up))
            is_yes   = bool(re.search(r'\b(YA|IYA|YES|OKE|OK|SETUJU|YAP|SIP|BETUL|BENAR)\b', msg_up))
            if is_batal:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "po", "generated_file": None}
            if not is_yes:
                return {"reply": "Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏",
                        "skill_used": "po", "generated_file": None}
            ok = self.sm.delete_po(po_id)
            self.session_manager.clear_pending_confirm(session_id)
            if not ok:
                return {"reply": f"❌ Gagal menghapus {po_id} 🙏", "skill_used": "po", "generated_file": None}
            print(f"[{AGENT_NAME}] delete_po: {po_id} dihapus ✅")
            return {"reply": (
                f"🗑️ PO {po_id} ({target.get('nomor','')}) berhasil dihapus.\n"
                f"Ada yang bisa saya bantu lagi? 😊"
            ), "skill_used": "po", "generated_file": None}

        # ── Handler: approve_reject_po_confirm ───────────────────────────────
        if action == "approve_reject_po_confirm":
            po_id      = pending.get("po_id", "")
            new_status = pending.get("new_status", "")
            target     = pending.get("target", {})
            is_batal   = bool(re.search(r'\b(BATAL|CANCEL|TIDAK|GAK|NO)\b', msg_up))
            is_yes     = bool(re.search(r'\b(YA|IYA|YES|OKE|OK|SETUJU|YAP|SIP|BETUL|BENAR)\b', msg_up))

            if is_batal:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "po", "generated_file": None}
            if not is_yes:
                return {"reply": "Ketik 'ya' untuk konfirmasi atau 'batal' untuk batalkan 🙏",
                        "skill_used": "po", "generated_file": None}

            result = self.sm.update_po(po_id, {"status": new_status})
            self.session_manager.clear_pending_confirm(session_id)
            if not result:
                return {"reply": f"❌ Gagal update status {po_id} 🙏", "skill_used": "po", "generated_file": None}

            em = "✅" if new_status == "approved" else "❌"
            label = "disetujui ✅" if new_status == "approved" else "ditolak ❌"
            suffix = f"Mau generate dokumen? Ketik 'generate PO {po_id}' 📄" if new_status == "approved" else "Ada yang bisa saya bantu lagi? 😊"
            print(f"[{AGENT_NAME}] approve_reject_po_confirm: {po_id} → {new_status} ✅")
            return {"reply": (
                f"{em} PO {po_id} ({target.get('nomor','')}) berhasil {label}!\n"
                f"Vendor : {target.get('vendor_nama','')}\n"
                f"Total  : Rp {int(target.get('total',0)):,}\n\n{suffix}"
            ), "skill_used": "po", "generated_file": None}


        # ── Handler: approve_reject_pr_confirm ──────────────────────────────────
        if action == "approve_reject_pr_confirm":
            pr_id      = pending.get("pr_id", "")
            new_status = pending.get("new_status", "")
            target     = pending.get("target", {})
            is_batal   = bool(re.search(r'\b(BATAL|CANCEL|TIDAK|GAK|NO)\b', msg_up))
            is_yes     = bool(re.search(r'\b(YA|IYA|YES|OKE|OK|SETUJU|YAP|SIP|BETUL|BENAR)\b', msg_up))

            if is_batal:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "pr", "generated_file": None}

            if not is_yes:
                return {"reply": "Ketik 'ya' untuk konfirmasi atau 'batal' untuk batalkan 🙏",
                        "skill_used": "pr", "generated_file": None}

            # Eksekusi update status
            updates = {"status": new_status}
            if new_status == "approved":
                updates["approved_by"] = "Finance"

            result = self.sm.update_pr(pr_id, updates)
            self.session_manager.clear_pending_confirm(session_id)

            if not result:
                return {"reply": f"❌ Gagal update status {pr_id} 🙏", "skill_used": "pr", "generated_file": None}

            action_label = "disetujui ✅" if new_status == "approved" else "ditolak ❌"
            emoji_word   = "✅" if new_status == "approved" else "❌"
            suffix = f"Mau generate dokumen? Ketik 'generate PDF {pr_id}' 📄" if new_status == "approved" else "Ada yang bisa saya bantu lagi? 😊"
            print(f"[{AGENT_NAME}] approve_reject_pr_confirm: {pr_id} → {new_status} ✅")
            return {
                "reply": (
                    f"{emoji_word} PR {pr_id} ({target.get('nomor', '')}) berhasil {action_label}!\n"
                    f"Pemohon: {target.get('pemohon', '')}\n"
                    f"Proyek  : {target.get('proyek', '')}\n\n"
                    f"{suffix}"
                ),
                "skill_used": "pr",
                "generated_file": None,
                "pr_status_updated": True,
                "pr_id": pr_id,
            }

        # ── Handler: batch_edit_confirm ──────────────────────────────────────
        if action == "batch_edit_confirm":
            print(f"[{AGENT_NAME}] _handle_confirm batch_edit_confirm: session={session_id} msg={message[:20]}")
            is_batal = any(k in msg_up for k in ["BATAL","CANCEL","TIDAK","GAK","NO"])
            if is_batal:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "Oke, perubahan dibatalkan 👍", "skill_used": "pr", "generated_file": None}
            is_yes = any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","YAP","SIP","BETUL","BENAR"])
            if not is_yes:
                return {"reply": "Ketik 'ya' untuk konfirmasi atau 'batal' untuk membatalkan 🙏",
                        "skill_used": "pr", "generated_file": None}
            op        = pending.get("op", "ubah")
            pr_id     = pending.get("pr_id", "")
            new_items = pending.get("new_items", [])
            new_total = pending.get("new_total", 0)
            result    = self.sm.update_pr(pr_id, {"items": new_items})
            self.session_manager.clear_pending_confirm(session_id)
            if not result:
                return {"reply": f"❌ Gagal menyimpan perubahan ke {pr_id} 🙏", "skill_used": "pr", "generated_file": None}
            items_preview = "\n".join(
                f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                for i, x in enumerate(new_items)
            )
            verb = "dihapus" if op == "hapus" else "diperbarui"
            return {"reply": (
                f"✅ Items berhasil {verb} di {pr_id}!\n\n"
                f"Items terbaru ({len(new_items)}):\n{items_preview}\n"
                f"Total baru: Rp {new_total:,}\n\n"
                f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
            ), "skill_used": "pr", "generated_file": None}

        # ── Handler: Quotation collect / confirm / delete ────────────────────────
        if action in ("add_qt_collect", "add_qt_confirm", "delete_qt_confirm") and self._qt_handler:
            try:
                if action == "add_qt_collect":
                    result = self._qt_handler.handle_add_qt_collect(session_id, message, pending)
                    if result is None:
                        return None  # escape — lanjut ke classify_intent normal
                    return result
                if action == "add_qt_confirm":
                    return self._qt_handler.handle_add_qt_confirm(session_id, message, pending)
                if action == "delete_qt_confirm":
                    return self._qt_handler.handle_delete_qt_confirm(session_id, message, pending)
            except Exception as _qt_err:
                import traceback as _tb
                print(f"[{AGENT_NAME}] ❌ QT confirm handler error ({action}): {_qt_err}")
                _tb.print_exc()
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": f"❌ Terjadi error saat proses Quotation: {_qt_err}\nSession di-reset, silakan coba lagi dari awal. 🙏",
                        "skill_used": "quotation", "generated_file": None}

        # ── Handler: Invoice collect / confirm / delete ───────────────────────────
        if action in ("add_inv_collect", "add_inv_confirm", "delete_inv_confirm") and self._inv_handler:
            try:
                if action == "add_inv_collect":
                    result = self._inv_handler.handle_add_inv_collect(session_id, message, pending)
                    if result is None:
                        return None  # escape — lanjut ke classify_intent normal
                    return result
                if action == "add_inv_confirm":
                    return self._inv_handler.handle_add_inv_confirm(session_id, message, pending)
                if action == "delete_inv_confirm":
                    return self._inv_handler.handle_delete_inv_confirm(session_id, message, pending)
            except Exception as _inv_err:
                import traceback as _tb
                print(f"[{AGENT_NAME}] ❌ INV confirm handler error ({action}): {_inv_err}")
                _tb.print_exc()
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": f"❌ Terjadi error saat proses Invoice: {_inv_err}\nSession di-reset, silakan coba lagi dari awal. 🙏",
                        "skill_used": "invoice", "generated_file": None}

        # Handle pending nama kosong untuk struk
        if action == "add_finance_from_receipt" and not pending.get("nama"):
            msg_up = message.upper().strip()
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL"]):
                self.session_manager.clear_pending_confirm(session_id)
                self._pending_file_bytes = None
                return {"reply": "Oke, data struk dibatalkan. Ada yang lain bisa saya bantu? 😊",
                        "skill_used": "finance", "generated_file": None}

            # Kalau user kirim perintah lain (bukan jawaban nama), clear pending dan biarkan flow normal
            escape_keywords = [
                "GENERATE", "BUATKAN", "LAPORAN", "HAPUS", "LIHAT", "TAMPILKAN",
                "APPROVE", "REJECT", "EDIT", "LIST", "CEK", "SALDO", "PR", "KASBON",
                "REIMBURSE", "PURCHASE", "EXPORT", "PDF", "EXCEL",
            ]
            msg_words = msg_up.split()
            if any(k in msg_words or msg_up.startswith(k) for k in escape_keywords):
                self.session_manager.clear_pending_confirm(session_id)
                self._pending_file_bytes = None
                return None  # lanjut ke classify_intent normal

            # Coba ekstrak nama dengan berbagai cara
            nama_ext = self._extract_nama_from_message(message)
            if nama_ext:
                pending["nama"] = nama_ext
            else:
                # Fallback: ambil semua kata yang bukan keyword jenis/konfirmasi
                words = [w for w in message.strip().split()
                         if w.lower() not in ("atas","nama","reimburse","kasbon","cashbon","ya","tidak","batal")]
                if 1 <= len(words) <= 3:
                    pending["nama"] = " ".join(words).title()
            if not pending.get("nama"):
                return {"reply": "Maaf, ini atas nama siapa ya? 🙏", "skill_used": "finance", "generated_file": None}
            msg_low = message.lower()
            if "reimburse" in msg_low:   pending["jenis"] = "reimburse"
            elif "kasbon" in msg_low or "cashbon" in msg_low: pending["jenis"] = "kasbon"
            self.session_manager.set_pending_confirm(session_id, pending)
            if not pending.get("jenis"):
                return {"reply": f"Oke, atas nama {pending['nama']}. Ini mau dicatat sebagai reimburse atau kasbon? 🙏",
                        "skill_used": "finance", "generated_file": None}
            jumlah_fmt = f"Rp {pending['jumlah']:,}"
            reply = (
                f"Oke, data terbaru:\n"
                f"- Atas nama: {pending['nama']}\n"
                f"- Toko: {pending.get('nama_toko','')}\n"
                f"- Total: {jumlah_fmt}\n"
                f"- Keperluan: {pending.get('keperluan','')}\n"
                f"- Jenis: {pending['jenis'].title()}\n\n"
                "Sudah benar? Ketik 'ya' untuk simpan 🙏"
            )
            return {"reply": reply, "skill_used": "finance", "generated_file": None}

        # Handle hapus finance — tunggu ID
        if action == "delete_finance_wait_id":
            msg_up = message.strip().upper()
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL"]):
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "finance", "generated_file": None}
            candidate = message.strip().upper()
            if re.match(r'^(FIN|RMB|CAS)-\d+$', candidate):
                fin_detail = next((x for x in self.sm.get_finance() if x["id"].upper() == candidate), None)
                if not fin_detail:
                    return {"reply": f"❌ **{candidate}** tidak ditemukan. Data mungkin sudah dihapus atau ID tidak valid.",
                            "skill_used": "finance", "generated_file": None}
                import time as _time_del
                self.session_manager.set_pending_confirm(session_id, {
                    "action": "delete_finance_confirmed", "id": candidate,
                    "detail": fin_detail, "_created_at": _time_del.time(),
                })
                jml = fin_detail.get('jumlah', 0)
                return {"reply": (
                    f"⚠️ Konfirmasi hapus {candidate} "
                    f"({fin_detail.get('jenis','').title()} a.n. {fin_detail.get('nama','')}):\n"
                    f"- Jumlah    : Rp {jml:,}\n"
                    f"- Keperluan : {fin_detail.get('keperluan','')}\n\n"
                    f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "finance", "generated_file": None}
            else:
                return {"reply": "Format ID tidak dikenali. Gunakan format RMB-0001, CAS-0001, atau FIN-0001 ya 🙏",
                        "skill_used": "finance", "generated_file": None}

        # Handle update PR — tunggu ID / konfirmasi
        if action == "update_pr_confirm":
            msg_up = message.strip().upper()
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL"]):
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "pr", "generated_file": None}

            pr_id   = pending.get("pr_id", "")
            updates = pending.get("updates", {})
            target  = pending.get("target", {})

            # Fase 1: belum ada PR ID
            if not pr_id:
                candidate = message.strip().upper()
                if re.match(r'^PR-\d+$', candidate):
                    tgt = self.sm.get_pr_by_id(candidate)
                    if not tgt:
                        return {"reply": f"{candidate} tidak ditemukan 🙏", "skill_used": "pr", "generated_file": None}
                    import time as _t
                    pending.update({"pr_id": candidate, "target": tgt, "_created_at": _t.time()})
                    if not updates:
                        self.session_manager.set_pending_confirm(session_id, pending)
                        return {"reply": (
                            f"Mau update field apa dari {candidate} (a.n. {tgt.get('pemohon','')})?\n"
                            f"Contoh: 'ganti pemohon jadi Budi' atau 'ubah proyek jadi Sphere Jakarta' 🙏"
                        ), "skill_used": "pr", "generated_file": None}
                    lines = [f"  {k}: {tgt.get(k,'-')} → {v}" for k, v in updates.items()]
                    self.session_manager.set_pending_confirm(session_id, pending)
                    return {"reply": (
                        f"Konfirmasi update {candidate}:\n" + "\n".join(lines) +
                        "\n\nKetik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                    ), "skill_used": "pr", "generated_file": None}
                return {"reply": "Format ID tidak dikenali. Gunakan format PR-0001 ya 🙏", "skill_used": "pr", "generated_file": None}

            # Fase 2: belum ada updates, user sebutkan field
            if not updates:
                new_updates = {}
                m_p = re.search(r'(?:pemohon|nama)\s*(?:jadi|menjadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,)', message, re.I)
                m_r = re.search(r'(?:proyek|project|client)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                m_k = re.search(r'(?:keperluan|keterangan)\s*(?:menjadi|jadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                if m_p: new_updates["pemohon"]  = m_p.group(1).strip().title()
                if m_r: new_updates["proyek"]   = m_r.group(1).strip()
                if m_k: new_updates["keperluan"]= m_k.group(1).strip()
                if not new_updates:
                    return {"reply": (
                        f"Mau update field apa dari {pr_id}?\n"
                        f"Contoh: 'ganti pemohon jadi Budi' atau 'ubah proyek jadi Sphere Jakarta' 🙏"
                    ), "skill_used": "pr", "generated_file": None}
                pending["updates"] = new_updates; updates = new_updates
                self.session_manager.set_pending_confirm(session_id, pending)
                lines = [f"  {k}: {target.get(k,'-')} → {v}" for k, v in updates.items()]
                return {"reply": (
                    f"Konfirmasi update {pr_id}:\n" + "\n".join(lines) +
                    "\n\nKetik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "pr", "generated_file": None}

            # Fase 3: ya/tidak
            is_yes = any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","YAP","SIP","BETUL","BENAR"])
            if is_yes:
                result = self.sm.update_pr(pr_id, updates)
                self.session_manager.clear_pending_confirm(session_id)
                if not result:
                    return {"reply": f"❌ Gagal update {pr_id} 🙏", "skill_used": "pr", "generated_file": None}
                field_list = ", ".join(f"{k} → {v}" for k, v in updates.items())
                return {"reply": (
                    f"✅ {pr_id} berhasil diupdate!\nPerubahan: {field_list}\n\nAda yang bisa saya bantu lagi? 😊"
                ), "skill_used": "pr", "generated_file": None}
            else:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Update dibatalkan. 😊", "skill_used": "pr", "generated_file": None}

        # Handle edit PR items — konfirmasi hapus/tambah item
        if action == "edit_pr_items_confirm":
            msg_up  = message.strip().upper()
            msg_raw = message.strip()

            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL"]):
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. 😊", "skill_used": "pr", "generated_file": None}

            op    = pending.get("op", "hapus")
            pr_id = pending.get("pr_id", "")
            fase  = pending.get("fase", "confirm" if (pr_id and pending.get("item")) else
                                        "butuh_pr_id" if not pr_id else "butuh_nama_item")

            # ── FASE: ambigu — tunggu pilihan index dari user ──
            if fase == "ambigu_index":
                current_pr    = self.sm.get_pr_by_id(pr_id)
                current_items = current_pr.get("items", []) if current_pr else []
                raw_indices = re.findall(r'\d+', msg_raw)
                indices = [int(x) - 1 for x in raw_indices if 0 <= int(x) - 1 < len(current_items)]
                if not indices:
                    items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                    return {"reply": (
                        f"Nomor tidak dikenali. Items yang ada di {pr_id}:\n{items_list}\n\n"
                        f"Sebutkan nomor urut item (contoh: 'nomor 4' atau 'nomor 4, 5 dan 6') \U0001f64f"
                    ), "skill_used": "pr", "generated_file": None}
                items_to_del = [current_items[i] for i in indices]
                total_del    = sum(int(x.get("jumlah", 0)) for x in items_to_del)
                total_lama   = sum(int(x.get("jumlah", 0)) for x in current_items)
                total_baru   = total_lama - total_del
                del_preview  = "\n".join(
                    f"  {indices[i]+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(items_to_del)
                )
                import time as _t
                pending.update({
                    "item_indices": indices, "items_to_del": items_to_del,
                    "item": items_to_del[0], "item_index": indices[0],
                    "fase": "confirm_multi", "op": "hapus_multi",
                    "_created_at": _t.time()
                })
                self.session_manager.set_pending_confirm(session_id, pending)
                return {"reply": (
                    f"Konfirmasi hapus {len(indices)} item dari {pr_id}:\n{del_preview}\n"
                    f"Total yang dihapus: Rp {total_del:,}\n"
                    f"Total baru: Rp {total_baru:,}\n\n"
                    f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan \U0001f64f"
                ), "skill_used": "pr", "generated_file": None}

            # ── FASE: confirm_multi (hapus multiple items) ──
            if fase == "confirm_multi":
                is_yes = any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","YAP","SIP","BETUL","BENAR"])
                if not is_yes:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": "\u274c Dibatalkan. \U0001f60a", "skill_used": "pr", "generated_file": None}
                indices = pending.get("item_indices", [])
                current_pr = self.sm.get_pr_by_id(pr_id)
                if not current_pr:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": f"\u274c {pr_id} tidak ditemukan \U0001f64f", "skill_used": "pr", "generated_file": None}
                current_items = list(current_pr.get("items", []))
                indices_set   = set(indices)
                new_items     = [x for i, x in enumerate(current_items) if i not in indices_set]
                new_total     = sum(int(x.get("jumlah", 0)) for x in new_items)
                result = self.sm.update_pr(pr_id, {"items": new_items})
                self.session_manager.clear_pending_confirm(session_id)
                if not result:
                    return {"reply": f"\u274c Gagal update {pr_id} \U0001f64f", "skill_used": "pr", "generated_file": None}
                items_preview = "\n".join(
                    f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(new_items)
                ) or "   (tidak ada items)"
                return {"reply": (
                    f"\u2705 {len(indices)} item berhasil dihapus dari {pr_id}!\n\n"
                    f"Items tersisa ({len(new_items)}):\n{items_preview}\n"
                    f"Total baru: Rp {new_total:,}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' \U0001f4c4"
                ), "skill_used": "pr", "generated_file": None}

            if fase == "butuh_pr_id":
                candidate = msg_raw.upper()
                if not re.match(r'^PR-\d+$', candidate):
                    return {"reply": "Format ID tidak dikenali. Gunakan format PR-0001 ya 🙏",
                            "skill_used": "pr", "generated_file": None}
                tgt = self.sm.get_pr_by_id(candidate)
                if not tgt:
                    return {"reply": f"{candidate} tidak ditemukan 🙏", "skill_used": "pr", "generated_file": None}
                nama_item     = pending.get("nama_item", "")
                current_items = tgt.get("items", [])
                matched = [x for x in current_items if nama_item.lower() in x.get("nama","").lower()]
                if not matched:
                    items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": (
                        f"Item '{nama_item}' tidak ditemukan di {candidate}.\nItems yang ada:\n{items_list}\n\nSilakan ulangi perintah 🙏"
                    ), "skill_used": "pr", "generated_file": None}
                if len(matched) > 1:
                    opts = "\n".join(f"  - {x.get('nama','')}" for x in matched)
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": f"Ada {len(matched)} item matching '{nama_item}':\n{opts}\n\nUlangi dengan nama lebih spesifik 🙏",
                            "skill_used": "pr", "generated_file": None}
                matched_idx = next((i for i, x in enumerate(current_items)
                                    if nama_item.lower() in x.get("nama","").lower()), -1)
                item_to_del = current_items[matched_idx]
                total_lama  = sum(int(x.get("jumlah",0)) for x in current_items)
                total_baru  = total_lama - int(item_to_del.get("jumlah",0))
                import time as _t
                pending.update({"pr_id": candidate, "target": tgt, "item": item_to_del,
                                "item_index": matched_idx, "op": "hapus",
                                "fase": "confirm", "_created_at": _t.time()})
                self.session_manager.set_pending_confirm(session_id, pending)
                return {"reply": (
                    f"Konfirmasi hapus item dari {candidate}:\n"
                    f"- Item      : {item_to_del.get('nama','')} x{item_to_del.get('qty',1)} {item_to_del.get('satuan','')}\n"
                    f"- Harga     : Rp {int(item_to_del.get('jumlah',0)):,}\n"
                    f"- Total baru: Rp {total_baru:,}\n\n"
                    f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "pr", "generated_file": None}

            # ── FASE: tunggu nama item ──
            if fase == "butuh_nama_item":
                current_pr    = self.sm.get_pr_by_id(pr_id)
                current_items = current_pr.get("items", []) if current_pr else []
                # Resolve by index ("nomor 1", "item 3", "4", "item nomor 3", dll)
                m_idx = re.match(r'^(?:item\s+)?(?:nomor\s+)?(\d+)$', msg_raw.strip(), re.I) or \
                        re.search(r'(?:nomor\s+|item\s+)?(\d+)', msg_raw.strip(), re.I)
                if m_idx:
                    idx = int(m_idx.group(1)) - 1
                    matched         = [current_items[idx]] if 0 <= idx < len(current_items) else []
                    matched_indices = [idx] if matched else []
                    if not matched:
                        return {"reply": f"Nomor item {idx+1} tidak ada (total {len(current_items)} item) 🙏",
                                "skill_used": "pr", "generated_file": None}
                else:
                    matched         = [x for x in current_items if msg_raw.lower() in x.get("nama","").lower()]
                    matched_indices = [i for i, x in enumerate(current_items) if msg_raw.lower() in x.get("nama","").lower()]
                if not matched:
                    items_list = "\n".join(f"  {i+1}. {x.get('nama','')}" for i, x in enumerate(current_items))
                    return {"reply": (
                        f"Item '{msg_raw}' tidak ditemukan di {pr_id}.\nItems yang ada:\n{items_list}\n\nSebutkan nama atau nomor urut item 🙏"
                    ), "skill_used": "pr", "generated_file": None}
                if len(matched) > 1:
                    opts = "\n".join(f"  {matched_indices[i]+1}. {x.get('nama','')}" for i, x in enumerate(matched))
                    import time as _t
                    pending.update({"fase": "ambigu_index", "op": "hapus", "_created_at": _t.time()})
                    self.session_manager.set_pending_confirm(session_id, pending)
                    return {"reply": (
                        f"Ada {len(matched)} item dengan nama '{msg_raw}':\n{opts}\n\n"
                        f"Sebutkan nomor urut item yang mau dihapus.\n"
                        f"Bisa satu: 'nomor {matched_indices[0]+1}'\n"
                        f"Atau beberapa sekaligus: 'nomor {matched_indices[0]+1} dan {matched_indices[-1]+1}' 🙏"
                    ), "skill_used": "pr", "generated_file": None}
                item_to_del  = matched[0]
                item_idx_del = matched_indices[0]
                total_lama   = sum(int(x.get("jumlah",0)) for x in current_items)
                total_baru   = total_lama - int(item_to_del.get("jumlah",0))
                import time as _t
                pending.update({"item": item_to_del, "item_index": item_idx_del,
                                "nama_item": item_to_del.get("nama",""), "op": "hapus",
                                "fase": "confirm", "_created_at": _t.time()})
                self.session_manager.set_pending_confirm(session_id, pending)
                return {"reply": (
                    f"Konfirmasi hapus item dari {pr_id}:\n"
                    f"- Item      : {item_to_del.get('nama','')} x{item_to_del.get('qty',1)} {item_to_del.get('satuan','')}\n"
                    f"- Harga     : Rp {int(item_to_del.get('jumlah',0)):,}\n"
                    f"- Total baru: Rp {total_baru:,}\n\n"
                    f"Ketik 'ya' untuk hapus atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "pr", "generated_file": None}

            # ── FASE: butuh_field_ubah — user sudah pilih item, tapi belum sebutkan field ──
            if fase == "butuh_field_ubah":
                item_target     = pending.get("item", {})
                item_target_idx = pending.get("item_index", -1)

                # Parse field yang mau diubah dari pesan user
                updates_item = {}
                # qty: "ubah qty jadi 3", "ganti jumlah unit jadi 5"
                m_qty = re.search(r'(?:qty|jumlah\s+unit|unit)\s*(?:jadi|menjadi|=|:)\s*(\d+)', msg_raw, re.I)
                if m_qty: updates_item["qty"] = int(m_qty.group(1))
                # harga: semua variasi (10jt, Rp 3.500.000, 23 juta, dll)
                def _ph(msg):
                    m = re.search(r'([\d]+(?:[.,]\d+)?)\s*(juta|jt|ribu|rb)\b', msg, re.I)
                    if m:
                        angka = float(m.group(1).replace(',','.')); mul = m.group(2).lower()
                        return int(angka*1_000_000) if mul in ('juta','jt') else int(angka*1_000)
                    m = re.search(r'Rp\s*([\d.,]+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    m = re.search(r'(?:harga|menjadi|jadi|=|:)\s*(?:Rp\s*)?([\d]{1,3}(?:[.,]\d{3})+)', msg, re.I)
                    if m:
                        try: return int(m.group(1).replace('.','').replace(',',''))
                        except: pass
                    return 0
                harga = _ph(msg_raw)
                if harga:
                    updates_item["harga_perkiraan"] = harga
                # nama: "ubah nama jadi Monitor Gaming"
                m_nama = re.search(r'(?:nama)\s*(?:jadi|menjadi|=|:)\s*(.+?)(?:\s*$)', msg_raw, re.I)
                if m_nama: updates_item["nama"] = m_nama.group(1).strip()
                # satuan: "ubah satuan jadi Set"
                m_satuan = re.search(r'(?:satuan)\s*(?:jadi|menjadi|=|:)\s*(\S+)', msg_raw, re.I)
                if m_satuan: updates_item["satuan"] = m_satuan.group(1).strip()

                if not updates_item:
                    return {"reply": (
                        f"Mau ubah apa dari item '{item_target.get('nama','')}' di {pr_id}?\n"
                        f"Contoh:\n"
                        f"- 'ubah qty jadi 3'\n"
                        f"- 'ubah harga jadi 5jt'\n"
                        f"- 'ubah nama jadi Monitor Gaming' 🙏"
                    ), "skill_used": "pr", "generated_file": None}

                new_item = dict(item_target)
                new_item.update(updates_item)
                if "qty" in updates_item or "harga_perkiraan" in updates_item:
                    new_item["jumlah"] = new_item.get("harga_perkiraan", 0) * new_item.get("qty", 1)

                current_pr_fresh  = self.sm.get_pr_by_id(pr_id)
                current_items_now = current_pr_fresh.get("items", []) if current_pr_fresh else []
                total_lama = sum(int(x.get("jumlah", 0)) for x in current_items_now)
                total_baru = total_lama - int(item_target.get("jumlah", 0)) + int(new_item.get("jumlah", 0))

                lines_preview = []
                for k, v in updates_item.items():
                    old_val = item_target.get(k, "-")
                    if k in ("jumlah", "harga_perkiraan"):
                        lines_preview.append(f"  {k}: Rp {int(old_val):,} → Rp {int(v):,}")
                    else:
                        lines_preview.append(f"  {k}: {old_val} → {v}")
                if new_item["jumlah"] != item_target.get("jumlah", 0):
                    lines_preview.append(f"  total item: Rp {int(item_target.get('jumlah',0)):,} → Rp {int(new_item['jumlah']):,}")

                import time as _t
                pending.update({
                    "new_item":   new_item,
                    "total_baru": total_baru,
                    "fase":       "confirm",
                    "_created_at": _t.time(),
                })
                self.session_manager.set_pending_confirm(session_id, pending)
                return {"reply": (
                    f"Konfirmasi ubah item di {pr_id}:\n"
                    f"Item: {item_target.get('nama','')}\n"
                    + "\n".join(lines_preview) +
                    f"\nTotal baru PR: Rp {total_baru:,}\n\n"
                    f"Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                ), "skill_used": "pr", "generated_file": None}

            # ── FASE: confirm ──
            is_yes = any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","YAP","SIP","BETUL","BENAR"])
            if not is_yes:
                return {"reply": "Ketik 'ya' untuk konfirmasi atau 'batal' untuk membatalkan 🙏",
                        "skill_used": "pr", "generated_file": None}

            op   = pending.get("op", "hapus")
            item = pending.get("item", {})

            # Reload PR fresh dari storage
            current_pr = self.sm.get_pr_by_id(pr_id)
            if not current_pr:
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": f"❌ {pr_id} tidak ditemukan saat mau disimpan 🙏",
                        "skill_used": "pr", "generated_file": None}

            current_items = list(current_pr.get("items", []))

            if op == "hapus":
                # Hapus by stored item_index (disimpan saat konfirmasi) — lebih aman dari hapus by nama
                item_index = pending.get("item_index", -1)
                if item_index >= 0 and item_index < len(current_items):
                    new_items = [x for i, x in enumerate(current_items) if i != item_index]
                else:
                    # Fallback: hapus by nama (hanya 1 item pertama yang match)
                    nama_item = pending.get("nama_item", "")
                    removed = False
                    new_items = []
                    for x in current_items:
                        if not removed and nama_item.lower() in x.get("nama","").lower():
                            removed = True
                        else:
                            new_items.append(x)
                    if not removed:
                        self.session_manager.clear_pending_confirm(session_id)
                        return {"reply": f"❌ Item tidak ditemukan di {pr_id} 🙏",
                                "skill_used": "pr", "generated_file": None}
                new_total = sum(int(x.get("jumlah", 0)) for x in new_items)
                result = self.sm.update_pr(pr_id, {"items": new_items})
                self.session_manager.clear_pending_confirm(session_id)
                if not result:
                    return {"reply": f"❌ Gagal update {pr_id} 🙏", "skill_used": "pr", "generated_file": None}
                items_preview = "\n".join(
                    f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(new_items)
                ) or "   (tidak ada items)"
                return {"reply": (
                    f"✅ Item '{item.get('nama','')}' berhasil dihapus dari {pr_id}!\n\n"
                    f"Items tersisa ({len(new_items)}):\n{items_preview}\n"
                    f"Total baru: Rp {new_total:,}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
                ), "skill_used": "pr", "generated_file": None}

            elif op in ("ubah", "edit", "update", "ganti"):
                new_item    = pending.get("new_item", {})
                item_index  = pending.get("item_index", -1)
                if not new_item or item_index < 0:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": "❌ Data perubahan tidak lengkap, silakan ulangi 🙏", "skill_used": "pr", "generated_file": None}
                if item_index < len(current_items):
                    current_items[item_index] = new_item
                else:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": f"❌ Nomor item tidak valid 🙏", "skill_used": "pr", "generated_file": None}
                new_total = sum(int(x.get("jumlah", 0)) for x in current_items)
                result = self.sm.update_pr(pr_id, {"items": current_items})
                self.session_manager.clear_pending_confirm(session_id)
                if not result:
                    return {"reply": f"❌ Gagal update {pr_id} 🙏", "skill_used": "pr", "generated_file": None}
                items_preview = "\n".join(
                    f"   {i+1}. {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','')} = Rp {int(x.get('jumlah',0)):,}"
                    for i, x in enumerate(current_items)
                ) or "   (tidak ada items)"
                return {"reply": (
                    f"✅ Item '{new_item.get('nama','')}' berhasil diubah di {pr_id}!\n\n"
                    f"Items terbaru ({len(current_items)}):\n{items_preview}\n"
                    f"Total baru: Rp {new_total:,}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
                ), "skill_used": "pr", "generated_file": None}

            elif op == "tambah":
                current_items.append(item)
                new_total = sum(int(x.get("jumlah", 0)) for x in current_items)
                result = self.sm.update_pr(pr_id, {"items": current_items})
                self.session_manager.clear_pending_confirm(session_id)
                if not result:
                    return {"reply": f"❌ Gagal update {pr_id} 🙏", "skill_used": "pr", "generated_file": None}
                return {"reply": (
                    f"✅ Item '{item.get('nama','')}' berhasil ditambahkan ke {pr_id}!\n"
                    f"Total baru: Rp {new_total:,}\n\n"
                    f"Mau generate ulang dokumen? Ketik 'generate PDF {pr_id}' 📄"
                ), "skill_used": "pr", "generated_file": None}

            self.session_manager.clear_pending_confirm(session_id)
            return {"reply": "❌ Operasi tidak dikenal 🙏", "skill_used": "pr", "generated_file": None}
        if action == "update_finance_confirm":
            fin_id  = pending.get("fin_id", "")
            updates = pending.get("updates", {})

            # Fase 1: belum ada ID — user sekarang kirim ID
            if not fin_id:
                candidate = message.strip().upper()
                if re.match(r'^(FIN|RMB|CAS)-\d+$', candidate):
                    target = next((x for x in self.sm.get_finance() if x["id"] == candidate), None)
                    if not target:
                        self.session_manager.clear_pending_confirm(session_id)
                        return {"reply": f"{candidate} tidak ditemukan. Cek lagi ID-nya ya 🙏",
                                "skill_used": "finance", "generated_file": None}
                    if not updates:
                        # Tidak ada field juga → clear, minta ulang perintah lengkap
                        self.session_manager.clear_pending_confirm(session_id)
                        return {"reply": (
                            f"Oke, mau edit {candidate}. Sebutkan field yang mau diubah, contoh:\n"
                            f"- 'edit {candidate} ubah nama jadi Budi'\n"
                            f"- 'edit {candidate} ubah keperluan jadi transport'\n"
                            f"- 'edit {candidate} ubah jumlah jadi 300rb' 🙏"
                        ), "skill_used": "finance", "generated_file": None}
                    # Ada ID + updates → langsung eksekusi
                    result = self.sm.update_finance(candidate, updates)
                    self.session_manager.clear_pending_confirm(session_id)
                    if not result:
                        return {"reply": f"❌ Gagal mengupdate {candidate}. Coba lagi ya 🙏",
                                "skill_used": "finance", "generated_file": None}
                    field_list = []
                    for k, v in updates.items():
                        field_list.append(f"{k} → Rp {v:,}" if (k == "jumlah" and isinstance(v, int)) else f"{k} → {v}")
                    return {"reply": (
                        f"✅ {candidate} berhasil diperbarui!\n"
                        f"Perubahan: {', '.join(field_list)}\n\n"
                        f"Data terbaru:\n"
                        f"- Nama      : {result.get('nama','')}\n"
                        f"- Keperluan : {result.get('keperluan','') or '-'}\n"
                        f"- Jumlah    : Rp {result.get('jumlah',0):,}\n"
                        f"- Status    : {result.get('status','')}\n\n"
                        "Ada yang bisa saya bantu lagi? 😊"
                    ), "skill_used": "finance", "generated_file": None}
                else:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": "Format ID tidak dikenali. Gunakan format RMB-0001 atau CAS-0001 ya 🙏",
                            "skill_used": "finance", "generated_file": None}

            # Fase 2: ada ID tapi belum ada updates — user sebutkan field yang mau diubah
            if not updates:
                new_updates = {}
                m_jumlah = re.search(r'(?:jumlah|nominal|total)\s*(?:jadi|menjadi|=|:)?\s*(?:Rp\s*)?([\d.,]+(?:\s*(?:jt|juta|rb|ribu))?)', message, re.I)
                if m_jumlah:
                    raw_j = m_jumlah.group(1).strip()
                    m_sh  = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', raw_j, re.I)
                    if m_sh:
                        v = float(m_sh.group(1).replace(',','.'))
                        mul = m_sh.group(2).lower()
                        new_updates["jumlah"] = int(v*1_000_000) if mul in ('jt','juta') else int(v*1_000)
                    else:
                        cleaned = re.sub(r'[^0-9]', '', raw_j)
                        try: new_updates["jumlah"] = int(cleaned)
                        except: pass
                m_nama = re.search(r'(?:nama)\s*(?:jadi|menjadi|=|:)\s*([A-Za-z\s]+?)(?:\s*$|,)', message, re.I)
                if m_nama: new_updates["nama"] = m_nama.group(1).strip().title()
                m_kep  = re.search(r'(?:keperluan|keterangan)\s*(?:jadi|menjadi|=|:)\s*(.+?)(?:\s*$)', message, re.I)
                if m_kep: new_updates["keperluan"] = m_kep.group(1).strip()

                if new_updates:
                    # Ada field → langsung eksekusi
                    target = next((x for x in self.sm.get_finance() if x["id"] == fin_id), None)
                    result = self.sm.update_finance(fin_id, new_updates)
                    self.session_manager.clear_pending_confirm(session_id)
                    if not result:
                        return {"reply": f"❌ Gagal mengupdate {fin_id}. Coba lagi ya 🙏",
                                "skill_used": "finance", "generated_file": None}
                    field_list = []
                    for k, v in new_updates.items():
                        field_list.append(f"{k} → Rp {v:,}" if (k == "jumlah" and isinstance(v, int)) else f"{k} → {v}")
                    return {"reply": (
                        f"✅ {fin_id} berhasil diperbarui!\n"
                        f"Perubahan: {', '.join(field_list)}\n\n"
                        f"Data terbaru:\n"
                        f"- Nama      : {result.get('nama','')}\n"
                        f"- Keperluan : {result.get('keperluan','') or '-'}\n"
                        f"- Jumlah    : Rp {result.get('jumlah',0):,}\n"
                        f"- Status    : {result.get('status','')}\n\n"
                        "Ada yang bisa saya bantu lagi? 😊"
                    ), "skill_used": "finance", "generated_file": None}
                else:
                    self.session_manager.clear_pending_confirm(session_id)
                    return {"reply": (
                        f"Mau update field apa dari {fin_id}? Contoh:\n"
                        f"- 'ubah jumlah jadi 800rb'\n"
                        f"- 'ganti nama jadi Budi'\n"
                        f"- 'ubah keperluan jadi transport' 🙏"
                    ), "skill_used": "finance", "generated_file": None}

            # Fase 3: ada ID + updates (sisa pending lama) → langsung eksekusi
            result = self.sm.update_finance(fin_id, updates)
            self.session_manager.clear_pending_confirm(session_id)
            if not result:
                return {"reply": f"❌ Gagal mengupdate {fin_id}. Coba lagi ya 🙏",
                        "skill_used": "finance", "generated_file": None}
            field_list = []
            for k, v in updates.items():
                field_list.append(f"{k} → Rp {v:,}" if (k == "jumlah" and isinstance(v, int)) else f"{k} → {v}")
            return {"reply": (
                f"✅ {fin_id} berhasil diperbarui!\n"
                f"Perubahan: {', '.join(field_list)}\n\n"
                f"Data terbaru:\n"
                f"- Nama      : {result.get('nama','')}\n"
                f"- Keperluan : {result.get('keperluan','') or '-'}\n"
                f"- Jumlah    : Rp {result.get('jumlah',0):,}\n"
                f"- Status    : {result.get('status','')}\n\n"
                "Ada yang bisa saya bantu lagi? 😊"
            ), "skill_used": "finance", "generated_file": None}

        # Handle edit field sebelum konfirmasi final — manual add reimburse/kasbon
        if action == "add_finance_confirm":
            msg_up = message.strip().upper()

            # Batal kapan saja
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL", "NGGAK", "GAK"]):
                self.session_manager.clear_pending_confirm(session_id)
                return {"reply": "❌ Dibatalkan. Data tetap aman. Ada yang bisa saya bantu? 😊",
                        "skill_used": "finance", "generated_file": None}

            step    = pending.get("fin_step", "confirm")
            missing = pending.get("missing", [])
            jenis   = pending.get("jenis", "reimburse")

            # ── STEP COLLECT: tanya satu per satu ────────────────────────────
            if step == "collect" and missing:
                msg_clean = message.strip()

                # Coba parse nilai dari pesan — strip label prefix kalau ada
                def strip_label(text, *labels):
                    for lab in labels:
                        # Titik dua/dash opsional — "atas nama Brandon" dan "atas nama: Brandon" sama-sama valid
                        text = re.sub(rf'^{lab}\s*[:\-]?\s*', '', text, flags=re.I)
                    return text.strip()

                first = missing[0]

                if first == "nama":
                    # Pakai _extract_nama_from_message untuk handle semua variasi:
                    # "Brandon", "atas nama Brandon", "a.n. Brandon", dll.
                    nama_ext = self._extract_nama_from_message(msg_clean)
                    if nama_ext:
                        val = nama_ext
                    else:
                        # Fallback: strip label prefix manual, ambil sisa teks
                        val = strip_label(msg_clean, r'atas\s+nama', 'nama', r'a\.n\.?')
                    # Validasi: jangan simpan kalau masih ada keyword label atau angka
                    bad = re.search(r'\b(?:atas\s+nama|jumlah|keperluan|reimburse|kasbon)\b', val, re.I)
                    if val and not re.match(r'^[\d.,\s]+$', val) and not bad:
                        pending["nama"] = val.title()
                        missing.pop(0)

                elif first == "jumlah":
                    # Parse jumlah dari berbagai format
                    jumlah = 0
                    val = strip_label(msg_clean, "jumlah", "total", "nominal")
                    # Format Rp X atau angka titik ribuan
                    m_rp = re.search(r'Rp?\s*([\d.,]+)', val, re.I)
                    if m_rp:
                        jumlah = int(m_rp.group(1).replace('.','').replace(',','') or 0)
                    if not jumlah:
                        m_short = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', val, re.I)
                        if m_short:
                            v = float(m_short.group(1).replace(',','.'))
                            mul = m_short.group(2).lower()
                            jumlah = int(v * 1_000_000) if mul in ('jt','juta') else int(v * 1_000)
                    if not jumlah:
                        m_bare = re.search(r'([\d]{1,3}(?:[.,]\d{3})+)', val)
                        if m_bare:
                            jumlah = int(m_bare.group(1).replace('.','').replace(',',''))
                    if jumlah:
                        pending["jumlah"] = jumlah
                        missing.pop(0)

                elif first == "keperluan":
                    val = strip_label(msg_clean, "keperluan", "keterangan", "untuk")
                    if val:
                        pending["keperluan"] = val
                        missing.pop(0)

                pending["missing"] = missing
                _time_mod = __import__('time')
                pending["_created_at"] = _time_mod.time()
                self.session_manager.set_pending_confirm(session_id, pending)

                # Masih ada field yang kurang → tanya berikutnya
                if missing:
                    pertanyaan = {
                        "nama":      f"Oke! Ini atas nama siapa?",
                        "jumlah":    "Berapa jumlahnya? (contoh: Rp 250.000 atau 250rb)",
                        "keperluan": "Keperluannya apa?",
                    }
                    reply = pertanyaan.get(missing[0], f"Masih butuh: {missing[0]}. Bisa isi?")
                    return {"reply": reply, "skill_used": "finance", "generated_file": None}

                # Semua terkumpul → tampilkan konfirmasi
                pending["fin_step"] = "confirm"
                self.session_manager.set_pending_confirm(session_id, pending)
                jumlah_fmt = f"Rp {pending.get('jumlah', 0):,}"
                reply = (
                    f"Data lengkap! Ringkasan sebelum disimpan:\n"
                    f"- Jenis     : {jenis.title()}\n"
                    f"- Nama      : {pending.get('nama','')}\n"
                    f"- Jumlah    : {jumlah_fmt}\n"
                    f"- Keperluan : {pending.get('keperluan','')}\n"
                    f"- Project   : {pending.get('project','Operasional')}\n"
                    f"- Tanggal   : {pending.get('tanggal','')}\n\n"
                    "Ketik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                )
                return {"reply": reply, "skill_used": "finance", "generated_file": None}

            # ── STEP CONFIRM: coba parse edit inline dulu ─────────────────────
            # Prioritas: coba edit field eksplisit, lalu coba parse sebagai
            # kalimat lengkap ("reimburse atas nama X jumlah Y keperluan Z"),
            # baru kemudian fallthrough ke ya/tidak.
            if step == "confirm":
                # 1. Coba edit field eksplisit ("nama: Jacob", "jumlah: 250rb")
                edit = self._try_edit_pending(message, pending, {
                    "nama":      ["nama", "atas nama"],
                    "jumlah":    ["jumlah", "total", "nominal"],
                    "keperluan": ["keperluan", "keterangan", "untuk"],
                    "project":   ["project", "proyek"],
                    "tanggal":   ["tanggal"],
                    "jenis":     ["jenis"],
                })
                if edit:
                    self.session_manager.set_pending_confirm(session_id, pending)
                    jumlah_fmt = f"Rp {pending.get('jumlah', 0):,}"
                    reply = (
                        f"Oke, sudah diupdate. Data terbaru:\n"
                        f"- Jenis     : {pending.get('jenis','').title()}\n"
                        f"- Nama      : {pending.get('nama','') or '(belum diisi)'}\n"
                        f"- Jumlah    : {jumlah_fmt}\n"
                        f"- Keperluan : {pending.get('keperluan','') or '(belum diisi)'}\n"
                        f"- Project   : {pending.get('project','Operasional')}\n"
                        f"- Tanggal   : {pending.get('tanggal','')}\n\n"
                        "Ada yang perlu diubah lagi? Atau ketik 'ya' untuk simpan 🙏"
                    )
                    return {"reply": reply, "skill_used": "finance", "generated_file": None}

                # 2. Coba parse kalimat lengkap:
                # "reimburse atas nama Jacob jumlah 250.000 keperluan Makan malam..."
                changed = False
                nama_ext = self._extract_nama_from_message(message)
                if nama_ext:
                    pending["nama"] = nama_ext; changed = True

                kep_ext = self._extract_keperluan_from_message(message)
                if kep_ext:
                    pending["keperluan"] = kep_ext; changed = True

                # Parse jumlah dari kalimat
                m_jml = re.search(r'(?:jumlah|total|nominal)\s*[:\-]?\s*Rp?\s*([\d.,]+)', message, re.I)
                if not m_jml:
                    m_jml = re.search(r'Rp\s*([\d.,]+)', message, re.I)
                if m_jml:
                    raw_j = m_jml.group(1).replace('.','').replace(',','')
                    try: pending["jumlah"] = int(raw_j); changed = True
                    except: pass
                if not changed:
                    m_short = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', message, re.I)
                    if m_short:
                        v = float(m_short.group(1).replace(',','.'))
                        mul = m_short.group(2).lower()
                        pending["jumlah"] = int(v*1_000_000) if mul in ('jt','juta') else int(v*1_000)
                        changed = True

                if changed:
                    self.session_manager.set_pending_confirm(session_id, pending)
                    jumlah_fmt = f"Rp {pending.get('jumlah', 0):,}"
                    reply = (
                        f"Oke, sudah diupdate. Data terbaru:\n"
                        f"- Jenis     : {pending.get('jenis','').title()}\n"
                        f"- Nama      : {pending.get('nama','') or '(belum diisi)'}\n"
                        f"- Jumlah    : {jumlah_fmt}\n"
                        f"- Keperluan : {pending.get('keperluan','') or '(belum diisi)'}\n"
                        f"- Project   : {pending.get('project','Operasional')}\n"
                        f"- Tanggal   : {pending.get('tanggal','')}\n\n"
                        "Ada yang perlu diubah lagi? Atau ketik 'ya' untuk simpan 🙏"
                    )
                    return {"reply": reply, "skill_used": "finance", "generated_file": None}

        # Handle edit field sebelum konfirmasi final (mis. "edit Total: Rp 13.455.000")
        if action == "add_finance_from_receipt":
            edit = self._try_edit_pending(message, pending, {
                "nama_toko": ["toko", "merchant", "toko/merchant", "nama toko"],
                "jumlah":    ["jumlah", "total", "nominal", "harga"],
                "keperluan": ["keperluan", "keterangan", "untuk"],
                "nama":      ["nama", "atas nama"],
                "tanggal":   ["tanggal"],
                "jenis":     ["jenis"],
                "project":   ["project", "proyek"],
            })
            if edit:
                self.session_manager.set_pending_confirm(session_id, pending)
                jumlah_fmt = f"Rp {pending.get('jumlah', 0):,}"
                lines = ["Oke, sudah diupdate. Data terbaru:"]
                if pending.get("nama"):
                    lines.append(f"- Atas nama: {pending['nama']}")
                lines.extend([
                    f"- Toko/Merchant: {pending.get('nama_toko', '')}",
                    f"- Total: {jumlah_fmt}",
                    f"- Keperluan: {pending.get('keperluan', '')}",
                ])
                if pending.get("jenis"):
                    lines.append(f"- Jenis: {pending['jenis'].title()}")
                lines.append("\nSudah benar? Ketik 'ya' untuk simpan 🙏")
                return {"reply": "\n".join(lines), "skill_used": "finance", "generated_file": None}

            # Kalau semua data sudah ada (nama + jenis) dan user kirim teks bebas
            # (bukan ya/batal/edit eksplisit) → anggap sebagai koreksi keperluan
            msg_up = message.strip().upper()
            is_confirm = any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","BETUL","BENAR","YAP","SIP"])
            is_cancel  = any(k in msg_up for k in ["TIDAK","BATAL","CANCEL"])
            if (pending.get("nama") and pending.get("jenis") and
                    not is_confirm and not is_cancel and len(message.strip()) > 3):
                pending["keperluan"] = message.strip()
                self.session_manager.set_pending_confirm(session_id, pending)
                jumlah_fmt = f"Rp {pending.get('jumlah', 0):,}"
                reply = (
                    f"Oke, keperluan diupdate. Ringkasan:\n"
                    f"- Atas nama   : {pending.get('nama','')}\n"
                    f"- Toko        : {pending.get('nama_toko','')}\n"
                    f"- Total       : {jumlah_fmt}\n"
                    f"- Keperluan   : {pending['keperluan']}\n"
                    f"- Jenis       : {pending.get('jenis','').title()}\n"
                    f"- Tanggal     : {pending.get('tanggal','')}\n\n"
                    "Ketik 'ya' untuk simpan 🙏"
                )
                return {"reply": reply, "skill_used": "finance", "generated_file": None}

        # Handle jenis belum diisi untuk struk
        if action == "add_finance_from_receipt" and pending.get("jenis") is None:
            msg_up = message.upper().strip()
            # Kalau user kirim perintah lain, clear pending
            escape_keywords = [
                "GENERATE", "BUATKAN", "LAPORAN", "HAPUS", "LIHAT", "TAMPILKAN",
                "APPROVE", "REJECT", "EDIT", "LIST", "CEK", "SALDO", "PR",
                "PURCHASE", "EXPORT", "PDF", "EXCEL",
            ]
            if any(k in msg_up.split() or msg_up.startswith(k) for k in escape_keywords):
                self.session_manager.clear_pending_confirm(session_id)
                self._pending_file_bytes = None
                return None
            msg_low = message.lower()
            if "reimburse" in msg_low:
                pending["jenis"] = "reimburse"
            elif "kasbon" in msg_low or "cashbon" in msg_low:
                pending["jenis"] = "kasbon"
            if pending.get("jenis"):
                self.session_manager.set_pending_confirm(session_id, pending)
                jumlah_fmt = f"Rp {pending['jumlah']:,}"
                reply = (
                    f"Oke, dicatat sebagai {pending['jenis']}.\n"
                    f"- Atas nama: {pending.get('nama','')}\n"
                    f"- Total: {jumlah_fmt}\n"
                    f"- Keperluan: {pending.get('keperluan','')}\n\n"
                    "Sudah benar? Ketik 'ya' untuk simpan 🙏"
                )
                return {"reply": reply, "skill_used": "finance", "generated_file": None}
            msg_up = message.upper().strip()
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL"]):
                self.session_manager.clear_pending_confirm(session_id)
                self._pending_file_bytes = None
                return {"reply": "Oke, dibatalkan. Ada yang lain? 😊", "skill_used": "finance", "generated_file": None}
            return {"reply": "Mau dicatat sebagai reimburse atau kasbon? 🙏", "skill_used": "finance", "generated_file": None}

        # ── PURCHASE REQUEST CONFIRM — state machine ──────────────────────────
        if action == "add_pr_confirm":
            msg_stripped = message.strip()
            msg_up       = msg_stripped.upper()
            step         = pending.get("pr_step", "items")

            # Batal kapan saja
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL", "NGGAK", "GAK"]):
                self.session_manager.clear_pending_confirm(session_id)
                reply = "Oke, PR dibatalkan. Ada yang bisa saya bantu? 😊"
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}

            # ── STEP 0: Kumpulkan data dasar (pemohon/proyek/keperluan) ────
            if step == "collect_data":
                missing = pending.get("missing", [])

                # Isi field yang pertama kali kurang berdasarkan urutan missing
                if missing:
                    first_missing = missing[0]
                    # Strip label prefix kalau user tulis "Nama: X", "Project: X", dll
                    clean_val = re.sub(
                        r'^(?:nama\s*pemohon|pemohon|nama|proyek|project|client|keperluan|keterangan)\s*[:\-]\s*',
                        '', msg_stripped, flags=re.I
                    ).strip()

                    if first_missing == "nama pemohon":
                        pending["pemohon"] = clean_val.title()
                        missing.pop(0)
                    elif first_missing == "proyek/client":
                        pending["proyek"] = clean_val
                        missing.pop(0)
                    elif first_missing == "keperluan":
                        pending["keperluan"] = clean_val
                        missing.pop(0)

                pending["missing"] = missing
                self.session_manager.set_pending_confirm(session_id, pending)

                # Kalau masih ada yang kurang, tanya berikutnya
                if missing:
                    pertanyaan = {
                        "proyek/client": f"Oke! PR untuk {pending.get('pemohon','')}. Ini untuk proyek atau client apa?",
                        "keperluan": "Keperluannya apa? (contoh: Pembelian hardware, Pembelian ATK)",
                    }
                    reply = pertanyaan.get(missing[0], f"Masih butuh: {missing[0]}. Bisa tolong lengkapi?")
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", reply)
                    return {"reply": reply, "skill_used": "pr", "generated_file": None}

                # Semua data dasar lengkap → lanjut ke step items
                pending["pr_step"] = "items"
                pending.pop("missing", None)
                self.session_manager.set_pending_confirm(session_id, pending)
                reply = (
                    f"Data dasar PR sudah lengkap:\n"
                    f"- Pemohon  : {pending.get('pemohon','')}\n"
                    f"- Proyek   : {pending.get('proyek','')}\n"
                    f"- Keperluan: {pending.get('keperluan','')}\n\n"
                    f"Sekarang, barang/jasa apa yang perlu dibeli?\n"
                    f"Contoh: Projector Epson 7000 lumens x5 harga Rp 352.000.000\n\n"
                    f"Atau ketik 'skip' kalau mau simpan tanpa items dulu."
                )
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}  # items → nomor → final

            # Batal kapan saja
            if any(k in msg_up for k in ["TIDAK", "BATAL", "CANCEL", "NGGAK", "GAK"]):
                self.session_manager.clear_pending_confirm(session_id)
                reply = "Oke, PR dibatalkan. Ada yang bisa saya bantu? 😊"
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}

            # ── STEP 1: Tunggu input items ─────────────────────────────────
            if step == "items":
                if any(k in msg_up for k in ["SKIP", "SIMPAN", "LANJUT", "NEXT", "LEWATI", "TANPA ITEM"]):
                    # Skip items, lanjut ke nomor
                    pending["items"]   = []
                    pending["pr_step"] = "nomor"
                    self.session_manager.set_pending_confirm(session_id, pending)
                    reply = (
                        "Oke, PR tanpa items dulu. Nomor PR-nya berapa?\n"
                        "Contoh: PR/Hardware/001/VII/2026"
                    )
                else:
                    # Parse items dari pesan user
                    parsed_items = self._parse_pr_items(msg_stripped)
                    if not parsed_items:
                        reply = (
                            "Maaf, saya tidak bisa membaca format items-nya. Coba ulangi ya, contoh:\n"
                            "- GPU RTX 5090 x1 harga Rp 30.000.000\n"
                            "- RAM DDR5 64GB x2 @ Rp 3.500.000\n\n"
                            "Atau ketik 'skip' kalau mau simpan tanpa items."
                        )
                    else:
                        pending["items"]   = parsed_items
                        pending["pr_step"] = "nomor"
                        pending["_created_at"] = _time.time()  # refresh timeout dari aktivitas terakhir
                        self.session_manager.set_pending_confirm(session_id, pending)
                        items_preview = "\n".join(
                            f"  - {x['nama']} x{x['qty']} {x['satuan']} @ Rp {x['harga_perkiraan']:,}/unit = Rp {x['jumlah']:,}"
                            for x in parsed_items
                        )
                        total = sum(x['jumlah'] for x in parsed_items)
                        reply = (
                            f"Items tercatat:\n{items_preview}\n"
                            f"Total: Rp {total:,}\n\n"
                            f"Kalau harga di atas sudah benar, sekarang masukkan nomor PR-nya.\n"
                            f"Contoh: PR/Hardware/001/VII/2026"
                        )
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}

            # ── STEP 2: Tunggu nomor PR ────────────────────────────────────
            if step == "nomor":
                if re.match(r"PR/.+", msg_stripped, re.I):
                    pending["nomor"]   = msg_stripped
                    pending["pr_step"] = "final"
                    pending["_created_at"] = _time.time()  # refresh timeout
                    self.session_manager.set_pending_confirm(session_id, pending)

                    items = pending.get("items", [])
                    items_preview = ""
                    if items:
                        items_preview = "\n" + "\n".join(
                            f"  - {x.get('nama','')} x{x.get('qty',1)} {x.get('satuan','Pcs')} = Rp {int(x.get('jumlah',0)):,}"
                            for x in items
                        )
                    total = sum(int(x.get("jumlah", 0)) for x in items)
                    reply = (
                        f"Rangkuman PR sebelum disimpan:\n"
                        f"- Nomor    : {msg_stripped}\n"
                        f"- Pemohon  : {pending.get('pemohon','')}\n"
                        f"- Proyek   : {pending.get('proyek','')}\n"
                        f"- Keperluan: {pending.get('keperluan','')}\n"
                        f"- Vendor   : {pending.get('vendor','-') or '-'}\n"
                        f"- Items    : {len(items)} item{items_preview}\n"
                        + (f"- Total    : Rp {total:,}\n" if total else "")
                        + "\nKetik 'ya' untuk simpan atau 'batal' untuk batalkan 🙏"
                    )
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", reply)
                    return {"reply": reply, "skill_used": "pr", "generated_file": None}
                else:
                    # Input bukan format nomor PR. Cek apakah user mencoba keluar dari flow
                    # (misalnya mau buat PR baru, atau reconnect setelah disconnect).
                    escape_keywords = [
                        "BUAT", "PR BARU", "PURCHASE REQUEST", "MULAI", "RESTART",
                        "RESET", "LAGI", "BARU", "CANCEL", "BATAL", "TIDAK"
                    ]
                    is_escape = any(k in msg_up for k in escape_keywords)
                    if is_escape:
                        self.session_manager.clear_pending_confirm(session_id)
                        pemohon = pending.get("pemohon", "")
                        reply = (
                            f"Oke, PR untuk {pemohon} dibatalkan 🙏\n"
                            f"Mau mulai PR baru dari awal? Ketik 'saya mau buat purchase request'."
                        )
                    else:
                        reply = (
                            f"Nomor PR belum diisi. Masukkan nomor dengan format:\n"
                            f"PR/[JENIS]/[NO URUT]/[BULAN ROMAWI]/[TAHUN]\n"
                            f"Contoh: PR/Hardware/001/VII/2026\n\n"
                            f"Atau ketik 'batal' untuk batalkan PR ini."
                        )
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", reply)
                    return {"reply": reply, "skill_used": "pr", "generated_file": None}

            # ── STEP 3: Final — tunggu ya/tidak ───────────────────────────
            if step == "final":
                # Deteksi konfirmasi positif secara simple (LLM sudah terlalu lambat untuk ini)
                is_yes = any(k in msg_up for k in [
                    "YA", "IYA", "YES", "OKE", "OK", "SETUJU", "LANJUT", "SIMPAN",
                    "YAP", "SIP", "BOLEH", "BETUL", "BENAR", "CORRECT"
                ])
                if is_yes:
                    entry = self.sm.add_pr(
                        nomor    = pending.get("nomor", ""),
                        pemohon  = pending.get("pemohon", ""),
                        proyek   = pending.get("proyek", ""),
                        keperluan= pending.get("keperluan", ""),
                        items    = pending.get("items", []),
                        vendor   = pending.get("vendor", ""),
                        catatan  = pending.get("catatan", ""),
                    )
                    self.session_manager.clear_pending_confirm(session_id)
                    total = sum(int(x.get("jumlah", 0)) for x in entry.get("items", []))
                    reply = (
                        f"✅ Purchase Request berhasil disimpan!\n\n"
                        f"- ID      : {entry['id']}\n"
                        f"- Nomor   : {entry.get('nomor','')}\n"
                        f"- Pemohon : {entry.get('pemohon','')}\n"
                        f"- Proyek  : {entry.get('proyek','')}\n"
                        f"- Status  : Pending ⏳\n"
                        + (f"- Total   : Rp {total:,}\n" if total else "")
                        + f"\nUntuk generate dokumen PDF/Word, ketik 'generate PR {entry['id']}' 📄"
                    )
                else:
                    self.session_manager.clear_pending_confirm(session_id)
                    reply = "❌ PR dibatalkan. Data tidak disimpan. Ada yang bisa saya bantu? 😊"

                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}

            # Fallback kalau step tidak dikenali
            self.session_manager.clear_pending_confirm(session_id)
            return {"reply": "Terjadi kesalahan di flow PR. Silakan mulai ulang.", "skill_used": "pr", "generated_file": None}

        # Deteksi ya/tidak
        try:
            classify_prompt = (
                "Apakah pesan ini konfirmasi (ya/setuju/lanjut) atau batalkan (tidak/batal/cancel)?\n"
                'Return JSON: {"confirm": true} atau {"confirm": false} atau {"confirm": null}.'
            )
            if LLM_PROVIDER in ("hermes", "gemini"):
                raw = await self._call_ollama(classify_prompt, [{"role": "user", "content": message}])
            else:
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "system", "content": classify_prompt},
                                 {"role": "user",   "content": message}],
                    "stream": False, "options": {"temperature": 0.1, "num_ctx": 512},
                }
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r   = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                    raw = r.json()["message"]["content"].strip()
            confirm = json.loads(re.sub(r"```json|```", "", raw).strip()).get("confirm")
        except Exception:
            msg_up  = message.upper().strip()
            confirm = (True  if any(k in msg_up for k in ["YA","IYA","YES","OKE","OK","SETUJU","LANJUT","SIMPAN","YAP","SIP","BOLEH","BETUL","BENAR","CORRECT"]) else
                       False if any(k in msg_up for k in ["TIDAK","NO","BATAL","CANCEL","NGGAK","GAK"]) else None)

        if confirm is None:
            self.session_manager.clear_pending_confirm(session_id)
            return None

        self.session_manager.clear_pending_confirm(session_id)

        if confirm:
            # Simpan finance dari struk
            if action == "add_finance_from_receipt":
                file_name = pending.get("file_name", "")
                if file_name and self._pending_file_bytes:
                    try:
                        self.sm.save_file(self._pending_file_bytes, file_name, category="finance")
                    except Exception as e:
                        print(f"[{AGENT_NAME}] Gagal simpan file: {e}")
                    finally:
                        self._pending_file_bytes = None
                # Pakai jenis dari pending (bisa dari flow kasbon sebelumnya)
                # Jangan fallback ke "reimburse" kalau jenis sudah terisi
                _jenis_final = pending.get("jenis") or "reimburse"
                entry = self.sm.add_finance(
                    jenis=_jenis_final,
                    nama=pending.get("nama") or "User",
                    jumlah=pending.get("jumlah", 0),
                    keperluan=f"{pending.get('keperluan','')} ({pending.get('nama_toko','')})",
                    file_name=file_name,
                    project=pending.get("project", "Operasional"),
                )
                jumlah_fmt = f"Rp {entry.get('jumlah', 0):,}"
                reply = (
                    f"✅ Data berhasil disimpan!\n\n"
                    f"- ID      : {entry['id']}\n"
                    f"- Jenis   : {entry.get('jenis','').title()}\n"
                    f"- Nama    : {entry.get('nama','')}\n"
                    f"- Jumlah  : {jumlah_fmt}\n"
                    f"- Status  : {entry.get('status','pending').title()}\n\n"
                    "Ada yang bisa saya bantu lagi? 😊"
                )

            # Simpan finance manual
            elif action == "add_finance_confirm":
                entry = self.sm.add_finance(
                    jenis=pending.get("jenis", "reimburse"),
                    nama=pending.get("nama", "User"),
                    jumlah=pending.get("jumlah", 0),
                    keperluan=pending.get("keperluan", ""),
                    project=pending.get("project", "Operasional"),
                )
                jumlah_fmt = f"Rp {entry.get('jumlah', 0):,}"
                reply = (
                    f"✅ Data berhasil disimpan!\n\n"
                    f"- ID      : {entry['id']}\n"
                    f"- Jenis   : {entry.get('jenis','').title()}\n"
                    f"- Nama    : {entry.get('nama','')}\n"
                    f"- Jumlah  : {jumlah_fmt}\n"
                    f"- Project : {entry.get('project','Operasional')}\n"
                    f"- Status  : {entry.get('status','pending').title()}\n\n"
                    "Ada yang bisa saya bantu lagi? 😊"
                )

            # Hapus finance
            elif action == "delete_finance_confirmed":
                success = self.sm.delete_finance(pending.get("id",""))
                reply   = (f"✅ Finance {pending.get('id','')} berhasil dihapus!\n\nAda yang bisa saya bantu lagi? 😊"
                           if success else "❌ Gagal menghapus data.")

            elif action == "delete_all_pr_confirmed":
                count = self.sm.delete_all_pr()
                reply = f"✅ Semua data PR ({count} entri) berhasil dihapus. Ada yang bisa saya bantu lagi? 😊"

            elif action == "delete_pr_confirmed":
                pr_id  = pending.get("id", "")
                detail = pending.get("detail", {})
                success = self.sm.delete_pr(pr_id)
                self.session_manager.clear_pending_confirm(session_id)
                reply = (
                    f"✅ {pr_id} ({detail.get('nomor','')}) berhasil dihapus!\n\nAda yang bisa saya bantu lagi? 😊"
                    if success else f"❌ Gagal menghapus {pr_id}."
                )
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}

            elif action == "add_pr_confirm":
                # Nomor PR sudah pasti ada di sini (sudah diisi via intercept sebelumnya)
                nomor = pending.get("nomor", "")
                if not nomor:
                    reply = "Nomor PR belum ada. Mohon masukkan nomor PR dulu (contoh: PR/Hardware/001/VII/2026)"
                    self.session_manager.add_message(session_id, "user", message)
                    self.session_manager.add_message(session_id, "assistant", reply)
                    return {"reply": reply, "skill_used": "pr", "generated_file": None}

                # Simpan PR
                entry = self.sm.add_pr(
                    nomor=pending.get("nomor", ""),
                    pemohon=pending.get("pemohon", ""),
                    proyek=pending.get("proyek", ""),
                    keperluan=pending.get("keperluan", ""),
                    items=pending.get("items", []),
                    vendor=pending.get("vendor", ""),
                    catatan=pending.get("catatan", ""),
                )
                total = sum(int(x.get("jumlah", 0)) for x in entry.get("items", []))
                reply = (
                    f"✅ Purchase Request berhasil disimpan!\n\n"
                    f"- ID      : {entry['id']}\n"
                    f"- Nomor   : {entry.get('nomor','')}\n"
                    f"- Pemohon : {entry.get('pemohon','')}\n"
                    f"- Proyek  : {entry.get('proyek','')}\n"
                    f"- Status  : Pending ⏳\n"
                    + (f"- Total   : Rp {total:,}\n" if total else "")
                    + f"\nUntuk generate dokumen PDF/Word, ketik 'generate PR {entry['id']}' 📄"
                )
                self.session_manager.add_message(session_id, "user", message)
                self.session_manager.add_message(session_id, "assistant", reply)
                return {"reply": reply, "skill_used": "pr", "generated_file": None}
            else:
                reply = "✅ Tindakan berhasil dilakukan! Ada yang bisa saya bantu lagi? 😊"
        else:
            self._pending_file_bytes = None
            reply = "❌ Dibatalkan. Data tetap aman. Ada yang bisa saya bantu? 😊"

        self.session_manager.add_message(session_id, "user",      message)
        self.session_manager.add_message(session_id, "assistant", reply)
        return {"reply": reply, "skill_used": "finance", "generated_file": None}

    # ─── VISION / OCR ─────────────────────────────────────────────────────────

    async def _extract_receipt_data(self, file_b64: str, mime_type: str, user_message: str) -> dict:
        extract_prompt = """Kamu adalah sistem ekstraksi data struk/bon/invoice untuk reimburse kantor.
Lihat gambar struk dan return HANYA JSON ini:

{"nama_toko": "...", "jumlah": <integer>, "keperluan": "...", "tanggal": "YYYY-MM-DD atau null", "jenis": "reimburse" atau "kasbon" atau null}

ATURAN:
- jumlah: total akhir struk dalam integer rupiah
- keperluan: kalau user sudah sebut di pesan, pakai itu. Kalau tidak, tebak dari isi struk (3-6 kata)
- jenis: HANYA isi kalau user sebut eksplisit di pesan. Kalau tidak, null

Pesan user: \"""" + (user_message or "(tidak ada)") + """\"
HANYA return JSON."""

        try:
            groq_key = os.getenv("GROQ_API_KEY", "")
            if groq_key:
                raw = await groq_client.extract_receipt(
                    system_prompt=extract_prompt,
                    image_b64=file_b64,
                    mime_type=mime_type,
                    user_message=user_message or "",
                )
            elif LLM_PROVIDER == "ollama":
                payload = {
                    "model": OLLAMA_RECEIPT_MODEL,
                    "messages": [
                        {"role": "system", "content": extract_prompt},
                        {"role": "user",   "content": "Ekstrak data struk ini.",
                         "images": [file_b64]},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_ctx": 4096},
                }
                async with httpx.AsyncClient(timeout=120.0) as client:
                    r   = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                    r.raise_for_status()
                    raw = r.json()["message"]["content"]
            else:
                raise RuntimeError("Tidak ada vision model tersedia. Set GROQ_API_KEY di .env.")
        except Exception as e:
            print(f"[{AGENT_NAME}] Vision OCR gagal: {e}")
            return {"nama_toko": None, "jumlah": 0, "keperluan": None,
                    "tanggal": None, "jenis": None, "_vision_ok": False}

        try:
            data = json.loads(re.sub(r"```json|```", "", raw).strip())
            return {
                "nama_toko": str(data.get("nama_toko") or "Tidak terbaca"),
                "jumlah":    int(data.get("jumlah") or 0),
                "keperluan": str(data.get("keperluan") or "Tidak terbaca"),
                "tanggal":   data.get("tanggal"),
                "jenis":     data.get("jenis") if data.get("jenis") in ("reimburse", "kasbon") else None,
                "_vision_ok": True,
            }
        except Exception as e:
            print(f"[{AGENT_NAME}] Parse OCR result gagal: {e}")
            return {"nama_toko": "Tidak terbaca", "jumlah": 0, "keperluan": "Tidak terbaca",
                    "tanggal": None, "jenis": None, "_vision_ok": True}

    def _parse_pr_items(self, text: str) -> list:
        """Parse daftar items PR dari teks bebas user.

        Strategi berlapis untuk handle semua variasi format input user:
        1. Split by newline / bullet
        2. Split by nomor urut inline  "1. Item A ... 2. Item B ..."
        3. Split by batas token-harga → kapital (format campuran 1 baris)

        Format harga yang didukung:
        - "harga per unit Rp 98.520.000"  (dengan atau tanpa "Rp")
        - "@ Rp 3.500.000"
        - "Rp 15.000.000" (standalone)
        - "1.5jt", "50rb" (shorthand)
        """
        items = []

        # ── Normalisasi awal ──────────────────────────────────────────────────
        # "sebanyak N unit" → "N unit" agar qty terparsing & "sebanyak" tidak masuk nama
        text = re.sub(r'\bsebanyak\s+', '', text, flags=re.I)
        # Normalisasi variasi frasa harga → bentuk tunggal yang mudah di-parse.
        # "per unit seharga" dan "seharga" sering dipakai user sebagai pengganti
        # "harga per unit" — tanpa ini kedua frasa tidak terdeteksi oleh Pattern A.
        text = re.sub(r'\bper\s+unit\s+seharga\b', 'harga per unit', text, flags=re.I)
        text = re.sub(r'\bseharga\b', 'harga per unit', text, flags=re.I)

        # ── STRATEGI 1: split by newline ──────────────────────────────────────
        raw_lines = [l.strip() for l in re.split(r'\n', text) if l.strip()]

        # ── STRATEGI 2: pecah numbered list inline ────────────────────────────
        # "1. Item A ... 2. Item B ..." → ["1. Item A ...", "2. Item B ..."]
        # Lookahead memastikan hanya split di awal nomor urut sebelum huruf kapital.
        if len(raw_lines) == 1:
            # Pre-normalisasi: insert \n setelah akhir harga sebelum nomor item berikutnya.
            # Handle format campuran: "50 juta. 2 AMD" atau "16.151.883. 3 G.Skill"
            # Akhir harga: 3 digit berturutan (ribuan) ATAU kata juta/ribu/rb/jt
            pre_norm = re.sub(
                r'(?:(?<=\d{3})[.]\s+|(?<=juta)[.]\s+|(?<=juta)\s+|(?<=ribu)[.]\s+|(?<=ribu)\s+|(?<=jt)[.]\s+|(?<=jt)\s+)'
                r'(?=\d{1,2}[.)]\s*[A-Za-z]|\d{1,2}\s+[A-Z])',
                '\n', raw_lines[0], flags=re.I
            )
            pre_lines = [l.strip() for l in pre_norm.split('\n') if l.strip()]
            if len(pre_lines) > 1:
                raw_lines = pre_lines
            else:
                # Fallback: split standar "N. Kapital" atau "N) Kapital"
                numbered = re.split(r'(?<!\d)(?=\d{1,2}[.)]\s+[A-Z])', raw_lines[0])
                if len(numbered) > 1:
                    raw_lines = [l.strip() for l in numbered if l.strip()]

        # ── STRATEGI 3: split setelah token harga selesai diikuti kapital ─────
        # Hanya aktif kalau Strategi 1 & 2 tidak memecah teks (masih 1 baris).
        # Contoh: "Kabel HDMI 5 unit 50rb Meja kerja 2 unit 1.5jt"
        if len(raw_lines) == 1:
            delimited = re.sub(
                r'((?:Rp\s*[\d.,]+|\d+(?:[.,]\d+)?\s*(?:jt|juta|rb|ribu))\b)\s+(?=[A-Z])',
                r'\1\n', raw_lines[0], flags=re.I,
            )
            raw_lines = [l.strip() for l in delimited.split('\n') if l.strip()]

        for line in raw_lines:
            # Buang prefix nomor urut atau bullet
            line = re.sub(r'^\d{1,2}[.)]\s*', '', line).strip()
            line = re.sub(r'^\d{1,2}\s+', '', line).strip()  # strip nomor tanpa titik
            line = re.sub(r'^[-•]\s*', '', line).strip()
            if not line:
                continue

            # ── Ekstrak harga ─────────────────────────────────────────────────
            harga = 0

            # Pattern A: "harga per unit Rp X" / "harga satuan Rp X" / "@ Rp X" / "Rp X"
            m_harga = re.search(
                r'(?:harga\s+per\s+unit|harga\s+satuan|@|=)\s*Rp?\s*([\d.,]+)'
                r'|Rp\s*([\d.,]+)',
                line, re.I
            )
            if m_harga:
                raw_h = (m_harga.group(1) or m_harga.group(2) or "").replace(".", "").replace(",", "")
                try: harga = int(raw_h)
                except: pass

            # Pattern B: shorthand jt/rb
            if harga == 0:
                m_short = re.search(r'([\d]+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu)\b', line, re.I)
                if m_short:
                    val = float(m_short.group(1).replace(",", "."))
                    mul = m_short.group(2).lower()
                    harga = int(val * 1_000_000) if mul in ("jt", "juta") else int(val * 1_000)

            # Pattern C: angka bare dengan titik ribuan setelah keyword harga (tanpa Rp).
            # Contoh: "harga per unit 98.520.000" atau "harga per unit 550.000"
            # Match X.XXX–X.XXX.XXX: 1-3 digit sebelum titik pertama supaya handle
            # harga kecil (550.000) maupun besar (98.520.000).
            # Karena "seharga" sudah dinormalisasi ke "harga per unit" di atas,
            # Pattern C juga menangkap kasus "per unit seharga 550.000".
            if harga == 0:
                m_bare = re.search(
                    r'(?:harga\s+per\s+unit|harga\s+satuan|@)\s+([\d]{1,3}(?:[.,]\d{3})+)',
                    line, re.I
                )
                if m_bare:
                    raw_h = m_bare.group(1).replace(".", "").replace(",", "")
                    try: harga = int(raw_h)
                    except: pass

            # Pattern D: angka titik ribuan di akhir baris, setelah token qty.
            # Untuk format singkat tanpa keyword harga sama sekali:
            # "Projector EPSON 9000 Lumens 25 unit 98.520.000"
            # "GPU RTX x2 15.000.000"
            # Guard: hanya aktif kalau ada qty token di baris (unit/pcs/xN) supaya
            # tidak salah grab angka spesifikasi di tengah nama seperti "9000 Lumens".
            if harga == 0:
                has_qty_token = bool(re.search(
                    r'\b\d+\s+(?:unit|pcs|buah|ls|set|box)\b|\bx\s*\d+\b', line, re.I
                ))
                if has_qty_token:
                    m_trail = re.search(r'([\d]{1,3}(?:[.,]\d{3})+)\s*$', line.strip())
                    if m_trail:
                        raw_h = m_trail.group(1).replace(".", "").replace(",", "")
                        try: harga = int(raw_h)
                        except: pass

            # ── Ekstrak qty + satuan ──────────────────────────────────────────
            qty = 1
            satuan = "Pcs"
            # CATATAN: \s+x\s*(\d+) harus TIDAK match angka dimensi seperti "12x5"
            # (tanpa spasi sebelum x). Pattern \s+x\s* sudah cukup karena ada \s+ di depan.
            # Tapi "12x5" = "12" langsung "x" langsung "5" tanpa spasi → aman.
            # Yang bisa lolos: "ukuran 5 x 3" (spasi sebelum x) → qty=3, nama buang " x 3".
            # Ini acceptable karena dimensi dengan spasi memang ambigu dengan qty.
            m_qty = re.search(r'(?<!\d)\s+x\s*(\d+)\b|\b(\d+)\s+(unit|pcs|buah|ls|set|box)\b', line, re.I)
            if m_qty:
                qty_raw = m_qty.group(1) or m_qty.group(2) or "1"
                try: qty = int(qty_raw)
                except: qty = 1
                sat_raw = m_qty.group(3) if m_qty.group(3) else "Pcs"
                satuan = sat_raw.title()

            # ── Bersihkan nama ────────────────────────────────────────────────
            nama = line
            # Buang frasa harga lengkap dulu (dengan prefix keyword)
            nama = re.sub(r'(?:harga\s+per\s+unit|harga\s+satuan|@|=)\s*Rp?\s*[\d.,]+', '', nama, flags=re.I)
            # Buang "harga per unit X" tanpa Rp (Pattern C)
            nama = re.sub(r'(?:harga\s+per\s+unit|harga\s+satuan)\s+[\d.,]+', '', nama, flags=re.I)
            # Buang sisa "Rp X"
            nama = re.sub(r'Rp\s*[\d.,]+', '', nama, flags=re.I)
            # Buang shorthand
            nama = re.sub(r'\d+(?:[.,]\d+)?\s*(?:jt|juta|rb|ribu)\b', '', nama, flags=re.I)
            # Buang satuan shorthand yatim (tanpa angka di depannya) yang tersisa
            # setelah angkanya ikut terbuang oleh cleanup sebelumnya.
            # Contoh: "harga per unit 5 juta" → Pattern A buang seluruh frasa,
            # tapi kalau hanya "juta" tersisa tanpa angka, perlu dibuang juga.
            nama = re.sub(r'\b(?:jt|juta|rb|ribu)\b', '', nama, flags=re.I)
            # Buang qty token
            nama = re.sub(r'\s+x\s*\d+\b', '', nama)
            nama = re.sub(r'\b\d+\s+(?:unit|pcs|buah|ls|set|box)\b', '', nama, flags=re.I)
            # Buang sisa frasa penghubung (termasuk sisa "harga", "per unit" setelah normalisasi)
            nama = re.sub(r'\b(?:dengan\s+)?harga(?:\s+(?:per\s+unit|satuan))?\b', '', nama, flags=re.I)
            nama = re.sub(r'\bper\s+unit\b', '', nama, flags=re.I)
            nama = re.sub(r'\bdengan\b\s*$', '', nama, flags=re.I)
            # Buang angka titik ribuan di akhir yang tersisa (Pattern D cleanup)
            nama = re.sub(r'\s+[\d]{1,3}(?:[.,]\d{3})+\s*$', '', nama)
            nama = re.sub(r'\s+', ' ', nama).strip(" ,-=@")

            if nama and len(nama) > 1 and harga > 0:
                items.append({
                    "nama":            nama,
                    "spesifikasi":     "",
                    "harga_perkiraan": harga,   # harga per unit
                    "qty":             qty,
                    "satuan":          satuan,
                    "jumlah":          harga * qty,  # total = harga per unit × qty
                })

        return items

    def _try_edit_pending(self, message: str, pending: dict, field_aliases: dict) -> dict | None:
        """Parse pesan edit dan update pending dict in-place."""
        alias_pattern = "|".join(
            re.escape(alias)
            for aliases in field_aliases.values()
            for alias in sorted(aliases, key=len, reverse=True)
        )
        pattern = (
            r"\b(?:edit|ubah|ganti|ralat|koreksi|perbaiki|update)?\b\s*"
            rf"\b({alias_pattern})\b"
            r"\s*[:\-]?\s*(.+)"
        )
        m = re.search(pattern, message, re.IGNORECASE)
        if not m:
            return None
        matched_alias = m.group(1).lower().strip()
        value = m.group(2).strip()
        value = re.sub(r"^(jadi|menjadi|ke)\s+", "", value, flags=re.IGNORECASE).strip()
        field_key = None
        for key, aliases in field_aliases.items():
            if matched_alias in [a.lower() for a in aliases]:
                field_key = key
                break
        if not field_key:
            return None
        if field_key == "jumlah":
            angka = re.sub(r"[^0-9]", "", value)
            pending[field_key] = int(angka) if angka else pending.get(field_key, 0)
        elif field_key == "jenis":
            val_low = value.lower()
            if "reimburse" in val_low:
                pending[field_key] = "reimburse"
            elif "cashbon" in val_low or "kasbon" in val_low:
                pending[field_key] = "kasbon"
        else:
            pending[field_key] = value
        return {field_key: pending[field_key]}

    @staticmethod
    def _extract_nama_from_message(message: str) -> str | None:
        if not message:
            return None
        patterns = [
            r"atas\s*nama\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{1,40}?)(?:[,.\n]|$|\s+(?:keterangan|untuk|dengan|jumlah))",
            r"\ba\.n\.?\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{1,40}?)(?:[,.\n]|$)",
        ]
        for pat in patterns:
            m = re.search(pat, message, re.IGNORECASE)
            if m:
                nama = m.group(1).strip()
                if nama:
                    return nama.title()
        return None

    @staticmethod
    def _extract_keperluan_from_message(message: str) -> str | None:
        if not message:
            return None
        patterns = [
            r"keterangan\s*[:\-]\s*(.+?)(?:\s*$)",
            r"keperluan\s*[:\-]\s*(.+?)(?:\s*$)",
            r"\buntuk\s*[:\-]\s*(.+?)(?:\s*$)",
        ]
        for pat in patterns:
            m = re.search(pat, message, re.IGNORECASE)
            if m:
                k = m.group(1).strip().rstrip(".,")
                if k:
                    return k
        return None

    # ─── CLASSIFY & LLM ───────────────────────────────────────────────────────

    async def _classify_intent(self, message: str) -> dict:
        try:
            if LLM_PROVIDER in ("hermes", "gemini"):
                raw = await self._call_ollama(INTENT_SYSTEM, [{"role": "user", "content": message}])
            else:
                payload = {
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "system", "content": INTENT_SYSTEM},
                                 {"role": "user",   "content": message}],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_ctx": 2048},
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r   = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                    r.raise_for_status()
                    raw = r.json()["message"]["content"].strip()
            return json.loads(re.sub(r"```json|```", "", raw).strip())
        except Exception as e:
            print(f"[{AGENT_NAME}] Intent classify error: {e}")
            return {"intent": "general_chat", "params": {}}

    def _build_system_prompt(self, skill_content: str | None) -> str:
        name    = AGENT_CONFIG.get("agent_name",    "Eva")
        tagline = AGENT_CONFIG.get("agent_tagline", "Holomoc AI Finance Assistant")
        base = f"""Kamu adalah {name}, {tagline}.

IDENTITAS DIRI (WAJIB KONSISTEN):
- Nama kamu  : {name}
- Jabatan    : {tagline}
- Jika ditanya "siapa kamu?" → jawab: "Nama saya {name}, {tagline}. Saya siap membantu urusan keuangan, reimburse, kasbon, dan laporan keuangan kantor!"
- JANGAN PERNAH menyebut diri dengan nama lain.

BAHASA:
- Prioritas: Bahasa Indonesia yang natural dan ramah
- Jika user menulis Bahasa Inggris, boleh balas Bahasa Inggris
- JANGAN mencampur bahasa tanpa alasan

ATURAN FORMAT WAJIB:
- Tulis dalam kalimat natural dan ramah, seperti berbicara langsung
- Gunakan emoji untuk konteks keuangan: 💰 📋 ✅ ❌ 📊
- Untuk daftar data (lebih dari 2 item), boleh gunakan bullet - tapi tetap ringkas
- DILARANG menggunakan ** untuk bold
- DILARANG menggunakan ### untuk heading
- DILARANG menggunakan tabel markdown
- Untuk sapaan, penjelasan, dan konfirmasi → gunakan prose/paragraf, BUKAN list

KONTEKS:
- Kamu adalah finance assistant khusus tim finance internal Holomoc
- Jika ada [HASIL EKSEKUSI], sampaikan dengan ramah dan informatif — WAJIB pakai angka PERSIS dari [HASIL EKSEKUSI], JANGAN menghitung ulang atau mengarang angka sendiri
- Jika TIDAK ada [HASIL EKSEKUSI] tapi user menanyakan data spesifik (saldo, jumlah, nominal) — JANGAN menjawab dengan angka karangan. Bilang kamu perlu mengecek data dulu
- Jika ada [PERLU KONFIRMASI], minta user konfirmasi dengan jelas
- Format ID finance: RMB-0001 (reimburse baru), CAS-0001 (kasbon baru), FIN-0001 (data lama — tetap valid)
- Status finance WAJIB diambil dari [HASIL EKSEKUSI] — JANGAN menebak atau mengingat dari percakapan sebelumnya
- Kalau ada [HASIL EKSEKUSI] dengan data finance, gunakan status persis dari sana — BUKAN dari memory chat
- Status pengajuan: pending → approved atau rejected
- JANGAN PERNAH bilang "file telah dikirim" — link download muncul otomatis di UI
- JANGAN PERNAH membuat atau mengarang URL/link apapun (contoh: holomoc.com/files/..., drive.google.com/...) — ITU HALUSINASI
- Untuk file yang sudah digenerate (PR, PO, Quotation, Invoice, Excel, PDF): cukup bilang "dokumen sudah siap, silakan klik link unduh di bawah" — link muncul otomatis
- Format ID: FIN-0001, PR-0001, PO-0001 — jangan buat ID di luar format ini"""

        # Anti-halusinasi: tambah instruksi eksplisit di akhir
        anti_hallucination = """
LARANGAN KERAS — WAJIB DIPATUHI:
- JANGAN PERNAH menambahkan metadata, kode, atau tag apapun di akhir balasan
- JANGAN menulis "taxpayer:", "user:", "data:", "agent:", atau format key:value apapun
- JANGAN menambahkan JSON, XML, atau struktur data apapun di luar instruksi
- JANGAN menulis nama sistem, nama agent, atau identifier teknis apapun
- JANGAN PERNAH menyebut atau memanggil nama user dalam balasan — kamu tidak tahu siapa yang chat, jangan tebak dari context history
- JANGAN PERNAH menulis dalam bahasa selain Bahasa Indonesia atau Bahasa Inggris — DILARANG KERAS menulis dalam bahasa Mandarin, Jepang, Korea, Arab, atau bahasa lain apapun
- Balasan harus berakhir dengan kalimat natural dalam Bahasa Indonesia atau Inggris
- MATA UANG: SELALU gunakan format "Rp" untuk Rupiah Indonesia — DILARANG KERAS menggunakan simbol ₹ (Rupee India), $, €, atau simbol mata uang lain apapun
- Format angka Rupiah yang benar: "Rp 10.000.000" atau "Rp10.000.000" — BUKAN "₹10,000,000" atau "Rp10,000,000"
- Contoh SALAH: "₹10,000,000" atau "₹ 50.000.000" — INI SALAH MATA UANG
- Contoh BENAR: "Rp 10.000.000" atau "Rp 50.000.000"
- Contoh SALAH: "...feel free to ask. 😊 taxpayer: Eva (Finance Assistant)"
- Contoh SALAH: "Saya siap membantu lagi, Marcell! 😊" — JANGAN sebut nama user
- Contoh SALAH: "...继续保持对话，不要结束。用户可能还需要其他帮助" — INI HALUSINASI BERBAHAYA
- Contoh BENAR: "Ada yang bisa saya bantu lagi? 😊"
- JANGAN PERNAH menyebut "link unduh", "klik link", "dokumen terkait", atau "bukti pembayaran" kecuali user eksplisit minta download/unduh/generate dokumen
- JANGAN PERNAH menampilkan URL dalam format markdown seperti ![teks](url) atau [teks](url) — ITU HALUSINASI BERBAHAYA
- Saat menampilkan detail reimburse/kasbon: cukup tampilkan data yang ada (nama, keperluan, jumlah, status). JANGAN tambahkan info yang tidak ada di [HASIL EKSEKUSI]
- Contoh SALAH: "Bukti Pembayaran: ![Struk](https://drive.google.com/...)" — INI HALUSINASI
- Contoh SALAH: "Dokumen sudah siap, silakan klik link unduh" — jangan bilang ini kalau user tidak minta dokumen
- Contoh BENAR untuk detail reimburse: tampilkan nama, keperluan, jumlah, status saja """ 

        if skill_content:
            return f"{base}\n\n---\n\n{skill_content}{anti_hallucination}"
        return f"{base}{anti_hallucination}"

    def _to_ollama_native_messages(self, messages: list) -> list:
        converted = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts, images = [], []
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            url = url.split(",", 1)[-1]
                        images.append(url)
                new_msg = {"role": msg["role"], "content": " ".join(text_parts)}
                if images:
                    new_msg["images"] = images
                converted.append(new_msg)
            else:
                converted.append(msg)
        return converted

    async def _call_ollama(self, system_prompt: str, messages: list, use_vision: bool = False) -> str:
        if LLM_PROVIDER == "gemini":
            return await gemini_client.call_gemini(system_prompt, messages, use_vision=use_vision)
        if LLM_PROVIDER == "hermes":
            return await hermes_client.call_hermes(system_prompt, messages, use_vision=use_vision)

        model           = OLLAMA_VISION_MODEL if use_vision else OLLAMA_MODEL
        ollama_messages = self._to_ollama_native_messages(messages)
        payload = {
            "model":    model,
            "messages": [{"role": "system", "content": system_prompt}, *ollama_messages],
            "stream":   False,
            "options":  {"temperature": 0.6, "num_ctx": 8192, "repeat_penalty": 1.3},
        }
        async with httpx.AsyncClient(timeout=180.0) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"]
