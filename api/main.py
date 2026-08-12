"""
api/main.py — Holomoc Agent Base
==================================
File ini SHARED dan tidak perlu diubah per agent.
Kustomisasi agent dilakukan via config.json dan agent/core.py.
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sys, os, json, base64, mimetypes
from pathlib import Path

_API_DIR               = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT_FOR_IMPORT = os.path.dirname(_API_DIR)
for _p in (_API_DIR, _PROJECT_ROOT_FOR_IMPORT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT_FOR_IMPORT, ".env"))

# Baca config.json untuk info agent
_CONFIG_PATH = os.path.join(_PROJECT_ROOT_FOR_IMPORT, "config.json")
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _AGENT_CONFIG = json.load(f)
except Exception:
    _AGENT_CONFIG = {}

AGENT_NAME    = _AGENT_CONFIG.get("agent_name",    "Agent")
AGENT_TAGLINE = _AGENT_CONFIG.get("agent_tagline", "Holomoc AI Assistant")

from agent.core import Agent
import tts as tts_module

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
WEB_DIR      = os.path.join(PROJECT_ROOT, "web")

app   = FastAPI(title=f"{AGENT_NAME} — {AGENT_TAGLINE}")
agent = Agent()

# Migrate data lama — hitung ulang field total PR yang belum ada
try:
    from storage.manager import migrate_pr_totals
    _migrated = migrate_pr_totals()
    if _migrated > 0:
        print(f"[Startup] migrate_pr_totals: {_migrated} PR diupdate")
except Exception as _e:
    print(f"[Startup] migrate_pr_totals skip: {_e}")


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStaticFiles(directory=WEB_DIR), name="static")

TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() == "true"


class ChatRequest(BaseModel):
    session_id   : str
    message      : str
    voice_enabled: bool      = True
    voice        : str | None = None
    rate         : float | None = None


class ChatResponse(BaseModel):
    reply          : str
    skill_used     : str | None = None
    audio_base64   : str | None = None
    words          : list[str] | None = None
    wtimes         : list[int] | None = None
    wdurations     : list[int] | None = None
    visemes        : list[str] | None = None
    vtimes         : list[int] | None = None
    vdurations     : list[int] | None = None
    emojis         : list[dict] | None = None
    download_url   : str | None = None
    download_filename: str | None = None
    image_base64   : str | None = None
    image_mime_type: str | None = None


def _rate_to_edge_format(rate: float | None) -> str:
    if rate is None:
        return "+0%"
    pct = round((rate - 1.0) * 100)
    return f"{'+' if pct >= 0 else ''}{pct}%"


async def _attach_tts(response: dict, text: str, voice_enabled: bool,
                      voice: str | None = None, rate: float | None = None) -> dict:
    if not (TTS_ENABLED and voice_enabled and text.strip()):
        return response
    effective_voice = voice or os.getenv("ELEVENLABS_VOICE_ID", "") or tts_module.DEFAULT_VOICE
    result = await tts_module.synthesize_safe(text, voice=effective_voice, rate=_rate_to_edge_format(rate))
    if result and result.audio_base64:
        response.update({
            "audio_base64": result.audio_base64,
            "words":        result.words,
            "wtimes":       result.wtimes,
            "wdurations":   result.wdurations,
            "visemes":      result.visemes,
            "vtimes":       result.vtimes,
            "vdurations":   result.vdurations,
            "emojis":       result.emojis,
        })
    return response


@app.get("/")
def root():
    return FileResponse(os.path.join(WEB_DIR, "eva_finance.html"))

@app.get("/skills")
def list_skills():
    return {"skills": agent.list_skills()}

@app.get("/config")
def get_config():
    return {
        "agent_name":    AGENT_NAME,
        "agent_tagline": AGENT_TAGLINE,
        "voice_id":      os.getenv("ELEVENLABS_VOICE_ID", ""),
        "model_id":      os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        "tts_enabled":   TTS_ENABLED,
    }

@app.get("/voices")
def get_voices():
    """
    Return daftar voice yang tersedia, dikelompokkan per provider.
    Frontend pakai ini untuk populate dropdown voice.
    Format voice_id:
      - ElevenLabs: "<elevenlabs_voice_id>" (langsung, tanpa prefix)
      - Edge TTS  : "edge:<voice_name>"
    """
    elevenlabs_key   = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice = os.getenv("ELEVENLABS_VOICE_ID", "")

    groups = []

    # ── ElevenLabs ─────────────────────────────────────────────────────────
    if elevenlabs_key and elevenlabs_voice:
        groups.append({
            "group": "ElevenLabs",
            "voices": [
                {"label": "Eva (ElevenLabs)", "value": elevenlabs_voice, "provider": "elevenlabs"},
            ]
        })

    # ── Edge TTS (Microsoft Azure Neural, gratis) ───────────────────────────
    groups.append({
        "group": "Edge TTS — Bahasa Indonesia",
        "voices": [
            {"label": "Gadis — Perempuan (id-ID)", "value": "edge:id-ID-GadisNeural",  "provider": "edge"},
            {"label": "Ardi — Laki-laki (id-ID)",  "value": "edge:id-ID-ArdiNeural",   "provider": "edge"},
        ]
    })
    groups.append({
        "group": "Edge TTS — English",
        "voices": [
            {"label": "Jenny — Female (en-US)",  "value": "edge:en-US-JennyNeural",   "provider": "edge"},
            {"label": "Guy — Male (en-US)",      "value": "edge:en-US-GuyNeural",     "provider": "edge"},
            {"label": "Aria — Female (en-US)",   "value": "edge:en-US-AriaNeural",    "provider": "edge"},
            {"label": "Sonia — Female (en-GB)",  "value": "edge:en-GB-SoniaNeural",   "provider": "edge"},
        ]
    })

    # Default voice: ElevenLabs kalau ada, atau Gadis edge-tts
    default_voice = elevenlabs_voice if (elevenlabs_key and elevenlabs_voice) else "edge:id-ID-GadisNeural"

    return {"groups": groups, "default_voice": default_voice}

@app.get("/debug/tts")
def debug_tts():
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")
    api_key  = os.getenv("ELEVENLABS_API_KEY", "")
    return {
        "tts_enabled":    TTS_ENABLED,
        "voice_id_env":   voice_id,
        "api_key_set":    bool(api_key),
        "api_key_prefix": api_key[:8] + "..." if api_key else "(kosong)",
        "model_id":       os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
    }

@app.get("/storage/summary")
def storage_summary():
    try:
        from storage.manager import get_storage_summary
        return get_storage_summary()
    except Exception as e:
        return {"error": str(e)}

@app.get("/storage/list/{category}")
def list_storage(category: str):
    try:
        from storage.manager import get_finance, get_pr, load_index
        if category == "finance":
            return {"data": get_finance()}
        elif category == "pr":
            # Selalu hitung ulang total dari items agar UI selalu sinkron
            data = get_pr()
            for item in data:
                items = item.get("items", [])
                item["total"] = sum(int(x.get("jumlah", 0)) for x in items)
            return {"data": data}
        elif category == "po":
            from storage.manager import get_po
            return {"data": get_po()}
        else:
            return {"data": load_index(category)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/storage/download/{category}/{file_name}")
def download_file(category: str, file_name: str):
    try:
        from storage.manager import get_file_path
        file_path = get_file_path(file_name, category)
        if not file_path or not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File '{file_name}' tidak ditemukan")
        mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return FileResponse(str(file_path), media_type=mime, filename=file_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/storage/download-export/{file_name}")
def download_export(file_name: str):
    export_dir = Path(os.getenv("STORAGE_DIR", str(Path.home() / "Documents" / "holomoc-file"))) / "exports"
    file_path  = export_dir / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File tidak ditemukan: {file_name}")
    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(str(file_path), media_type=mime, filename=file_name)

@app.get("/greeting", response_model=ChatResponse)
async def greeting(voice: str | None = None, rate: float | None = None):
    text     = _AGENT_CONFIG.get("greeting_message", f"Halo! Saya {AGENT_NAME}, siap membantu Anda!")
    response = {"reply": text, "skill_used": None}
    response = await _attach_tts(response, text, voice_enabled=True, voice=voice, rate=rate)
    return ChatResponse(**response)

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        result   = await agent.chat(req.session_id, req.message)
        response = {"reply": result["reply"], "skill_used": result.get("skill_used")}
        if result.get("generated_file"):
            _gf    = result["generated_file"]
            _fname = Path(_gf).name if _gf else ""
            response["download_url"]       = f"/storage/download-export/{_fname}"
            response["download_filename"]  = _fname
        if result.get("image_base64"):
            response["image_base64"]      = result["image_base64"]
            response["image_mime_type"]   = result.get("image_mime_type", "image/jpeg")
        response = await _attach_tts(response, result["reply"], req.voice_enabled, req.voice, req.rate)
        return ChatResponse(**response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat-with-file", response_model=ChatResponse)
async def chat_with_file(
    session_id   : str        = Form(...),
    message      : str        = Form(...),
    file         : UploadFile = File(...),
    voice_enabled: bool       = Form(True),
):
    try:
        file_bytes = await file.read()
        mime_type  = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

        IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if mime_type in IMAGE_TYPES:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(file_bytes))
                if img.width > 1024 or img.height > 1024:
                    img.thumbnail((1024, 1024), Image.LANCZOS)
                output = io.BytesIO()
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(output, format="JPEG", quality=85, optimize=True)
                file_bytes = output.getvalue()
                mime_type  = "image/jpeg"
            except Exception as e:
                print(f"[API] Image compress failed: {e}")

        file_b64 = base64.b64encode(file_bytes).decode("utf-8")
        result   = await agent.chat_with_file(
            session_id=session_id, message=message,
            file_b64=file_b64, file_name=file.filename,
            mime_type=mime_type, file_size=len(file_bytes),
        )
        response = {"reply": result["reply"], "skill_used": result.get("skill_used")}
        response = await _attach_tts(response, result["reply"], voice_enabled)
        return ChatResponse(**response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PO: update items langsung dari modal frontend ──────────────────────────────
@app.put("/storage/po/{po_id}/items")
async def api_update_po_items(po_id: str, payload: dict):
    try:
        from storage.manager import update_po
        po_id  = po_id.upper()
        items  = payload.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="items tidak boleh kosong")
        result = update_po(po_id, {"items": items})
        if not result:
            raise HTTPException(status_code=404, detail=f"PO {po_id} tidak ditemukan")
        return {"status": "ok", "po": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PO: update field-level (vendor, nomor, proyek, catatan, dll) ───────────────
@app.put("/storage/po/{po_id}/detail")
async def api_update_po_detail(po_id: str, payload: dict):
    try:
        from storage.manager import update_po
        po_id         = po_id.upper()
        allowed_fields = {"nomor","vendor_nama","vendor_alamat","vendor_attn","proyek","ref","catatan"}
        updates        = {k: v for k, v in payload.items() if k in allowed_fields and v != ""}
        if not updates:
            raise HTTPException(status_code=400, detail="Tidak ada field valid untuk diupdate")
        result = update_po(po_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"PO {po_id} tidak ditemukan")
        return {"status": "ok", "po": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PR: update items ──────────────────────────────────────────────────────────
@app.put("/storage/pr/{pr_id}/items")
async def api_update_pr_items(pr_id: str, payload: dict):
    try:
        from storage.manager import update_pr
        pr_id = pr_id.upper()
        items = payload.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="items tidak boleh kosong")
        result = update_pr(pr_id, {"items": items})
        if not result:
            raise HTTPException(status_code=404, detail=f"PR {pr_id} tidak ditemukan")
        return {"status": "ok", "pr": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PR: update field-level (pemohon, proyek, keperluan, nomor, vendor, catatan)
@app.put("/storage/pr/{pr_id}/detail")
async def api_update_pr_detail(pr_id: str, payload: dict):
    try:
        from storage.manager import update_pr
        pr_id = pr_id.upper()
        allowed_fields = {"pemohon", "proyek", "keperluan", "nomor", "vendor", "catatan"}
        updates = {k: v for k, v in payload.items() if k in allowed_fields and v != ""}
        if not updates:
            raise HTTPException(status_code=400, detail="Tidak ada field valid untuk diupdate")
        result = update_pr(pr_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"PR {pr_id} tidak ditemukan")
        return {"status": "ok", "pr": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── QT: update items ──────────────────────────────────────────────────────────
@app.put("/storage/qt/{qt_id}/items")
async def api_update_qt_items(qt_id: str, payload: dict):
    try:
        from storage.manager import update_qt
        qt_id = qt_id.upper()
        items = payload.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="items tidak boleh kosong")
        result = update_qt(qt_id, {"items": items})
        if not result:
            raise HTTPException(status_code=404, detail=f"QT {qt_id} tidak ditemukan")
        return {"status": "ok", "qt": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── QT: update field-level (klien, nomor, re, note, ttd_nama, ttd_hp, tanggal)
@app.put("/storage/qt/{qt_id}/detail")
async def api_update_qt_detail(qt_id: str, payload: dict):
    try:
        from storage.manager import update_qt
        qt_id = qt_id.upper()
        allowed_fields = {"klien_nama", "klien_alamat", "klien_up", "nomor", "tanggal",
                          "re", "note", "ttd_nama", "ttd_hp"}
        updates = {k: v for k, v in payload.items() if k in allowed_fields and v != ""}
        if not updates:
            raise HTTPException(status_code=400, detail="Tidak ada field valid untuk diupdate")
        result = update_qt(qt_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"QT {qt_id} tidak ditemukan")
        return {"status": "ok", "qt": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: update items ─────────────────────────────────────────────────────────
@app.put("/storage/inv/{inv_id}/items")
async def api_update_inv_items(inv_id: str, payload: dict):
    try:
        from storage.manager import update_inv
        inv_id = inv_id.upper()
        items  = payload.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="items tidak boleh kosong")
        result = update_inv(inv_id, {"items": items})
        if not result:
            raise HTTPException(status_code=404, detail=f"INV {inv_id} tidak ditemukan")
        return {"status": "ok", "inv": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: update field-level ───────────────────────────────────────────────────
@app.put("/storage/inv/{inv_id}/detail")
async def api_update_inv_detail(inv_id: str, payload: dict):
    try:
        from storage.manager import update_inv
        inv_id = inv_id.upper()
        allowed_fields = {
            "klien_nama", "klien_alamat", "nomor", "tanggal",
            "project_name", "ttd_nama", "ttd_jabatan",
            "bank_nama", "bank_rekening", "bank_cabang", "bank_atas_nama",
        }
        updates = {k: v for k, v in payload.items() if k in allowed_fields and v != ""}
        if not updates:
            raise HTTPException(status_code=400, detail="Tidak ada field valid untuk diupdate")
        result = update_inv(inv_id, updates)
        if not result:
            raise HTTPException(status_code=404, detail=f"INV {inv_id} tidak ditemukan")
        return {"status": "ok", "inv": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: update status (issued / paid / overdue / draft) ──────────────────────
@app.put("/storage/inv/{inv_id}/status")
async def api_update_inv_status(inv_id: str, payload: dict):
    try:
        from storage.manager import update_inv, get_inv, add_invoice_to_finance, remove_invoice_from_finance
        from datetime import datetime as _dt
        inv_id     = inv_id.upper()
        new_status = payload.get("status", "")
        if new_status not in ("issued", "paid", "overdue", "draft"):
            raise HTTPException(status_code=400,
                detail="status harus 'draft', 'issued', 'paid', atau 'overdue'")
        all_inv = get_inv()
        target  = next((x for x in all_inv if x.get("id") == inv_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"{inv_id} tidak ditemukan")
        prev_status = target.get("status", "")
        updates = {"status": new_status}
        if new_status == "paid":
            updates["paid_at"]   = _dt.now().isoformat()
        elif new_status == "issued":
            updates["issued_at"] = _dt.now().isoformat()
        result = update_inv(inv_id, updates)
        if not result:
            raise HTTPException(status_code=500, detail="Gagal update status")

        # ── Sinkronisasi ke Laporan Keuangan ──────────────────────────────────
        if new_status == "paid":
            # Masukkan ke finance sebagai pemasukan
            inv_data = dict(result)
            inv_data["paid_at"] = updates["paid_at"]
            try:
                fin_entry = add_invoice_to_finance(inv_data)
                print(f"[Main] INV {inv_id} paid → finance sync: {fin_entry is not None}")
            except Exception as _fe:
                print(f"[Main] INV {inv_id} finance sync error: {_fe}")
        elif prev_status == "paid" and new_status != "paid":
            # Status berubah dari paid → hapus dari laporan keuangan
            try:
                removed = remove_invoice_from_finance(inv_id)
                print(f"[Main] INV {inv_id} unpaid → remove from finance: {removed}")
            except Exception as _fe:
                print(f"[Main] INV {inv_id} finance remove error: {_fe}")

        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: list semua atau filter ───────────────────────────────────────────────
@app.get("/storage/list/inv")
async def api_get_inv(status: str = "", klien: str = ""):
    try:
        from storage.manager import get_inv
        data = get_inv()
        if status:
            data = [x for x in data if status.lower() in x.get("status","").lower()]
        if klien:
            data = [x for x in data if klien.lower() in x.get("klien_nama","").lower()]
        return {"status": "ok", "data": data, "total": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: get by ID ────────────────────────────────────────────────────────────
@app.get("/storage/inv/{inv_id}")
async def api_get_inv_by_id(inv_id: str):
    try:
        from storage.manager import get_inv_by_id
        result = get_inv_by_id(inv_id.upper())
        if not result:
            raise HTTPException(status_code=404, detail=f"INV {inv_id} tidak ditemukan")
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: delete ───────────────────────────────────────────────────────────────
@app.delete("/storage/inv/{inv_id}")
async def api_delete_inv(inv_id: str):
    try:
        from storage.manager import delete_inv
        ok = delete_inv(inv_id.upper())
        if not ok:
            raise HTTPException(status_code=404, detail=f"{inv_id} tidak ditemukan")
        return {"status": "ok", "deleted": inv_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: generate PDF ─────────────────────────────────────────────────────────
@app.get("/storage/inv/{inv_id}/generate/pdf")
async def api_generate_inv_pdf(inv_id: str):
    try:
        from storage.manager import get_inv_by_id
        from agent.invoice_generator import generate_inv_pdf
        inv = get_inv_by_id(inv_id.upper())
        if not inv:
            raise HTTPException(status_code=404, detail=f"INV {inv_id} tidak ditemukan")
        path  = generate_inv_pdf(inv)
        fname = Path(path).name
        return FileResponse(path, media_type="application/pdf", filename=fname)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── INV: generate Excel ───────────────────────────────────────────────────────
@app.get("/storage/inv/{inv_id}/generate/excel")
async def api_generate_inv_excel(inv_id: str):
    try:
        from storage.manager import get_inv_by_id
        from agent.invoice_generator import generate_inv_excel
        inv = get_inv_by_id(inv_id.upper())
        if not inv:
            raise HTTPException(status_code=404, detail=f"INV {inv_id} tidak ditemukan")
        path  = generate_inv_excel(inv)
        fname = Path(path).name
        mime  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(path, media_type=mime, filename=fname)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





# ── Export laporan langsung via API (bypass EVA chat) ─────────────────────────
@app.get("/storage/export/excel")
async def export_excel(bulan: int = 0, tahun: int = 0, jenis: str = "", status: str = ""):
    try:
        from storage.manager import get_finance, get_finance_config
        from storage.generator import generate_excel_finance
        data = get_finance()
        if jenis:
            data = [x for x in data if jenis.lower() in x.get("jenis", "").lower()]
        if status:
            data = [x for x in data if status.lower() in x.get("status", "").lower()]
        if bulan:
            bstr = f"-{str(bulan).zfill(2)}-"
            data = [x for x in data if bstr in x.get("created_at", "")]
        if tahun:
            data = [x for x in data if str(tahun) in x.get("created_at", "")]
        saldo_awal = get_finance_config().get("saldo_awal", 0)
        path = generate_excel_finance(data, saldo_awal=saldo_awal)
        fname = Path(path).name
        mime  = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(path, media_type=mime, filename=fname)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/storage/export/pdf")
async def export_pdf(bulan: int = 0, tahun: int = 0, jenis: str = "", status: str = ""):
    try:
        from storage.manager import get_finance, get_finance_config
        from storage.generator import generate_pdf_finance
        data = get_finance()
        if jenis:
            data = [x for x in data if jenis.lower() in x.get("jenis", "").lower()]
        if status:
            data = [x for x in data if status.lower() in x.get("status", "").lower()]
        if bulan:
            bstr = f"-{str(bulan).zfill(2)}-"
            data = [x for x in data if bstr in x.get("created_at", "")]
        if tahun:
            data = [x for x in data if str(tahun) in x.get("created_at", "")]
        saldo_awal = get_finance_config().get("saldo_awal", 0)
        path = generate_pdf_finance(data, saldo_awal=saldo_awal)
        fname = Path(path).name
        return FileResponse(path, media_type="application/pdf", filename=fname)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Finance: approve/reject langsung via API ───────────────────────────────────
@app.put("/storage/finance/{fin_id}/status")
async def api_update_finance_status(fin_id: str, payload: dict):
    try:
        from storage.manager import update_finance, get_finance
        fin_id = fin_id.upper()
        new_status = payload.get("status", "")
        if new_status not in ("approved", "rejected"):
            raise HTTPException(status_code=400, detail="status harus 'approved' atau 'rejected'")
        all_fin = get_finance()
        target  = next((x for x in all_fin if x.get("id") == fin_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"{fin_id} tidak ditemukan")
        updates = {"status": new_status}
        if new_status == "approved":
            updates["approved_by"] = "Finance"
        result = update_finance(fin_id, updates)
        if not result:
            raise HTTPException(status_code=500, detail="Gagal update status")
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Finance: edit detail ───────────────────────────────────────────────────────
@app.put("/storage/finance/{fin_id}/detail")
async def api_update_finance_detail(fin_id: str, payload: dict):
    try:
        from storage.manager import update_finance, get_finance
        fin_id  = fin_id.upper()
        allowed = {"nama", "jumlah", "keperluan", "project", "tanggal"}
        updates = {k: v for k, v in payload.items() if k in allowed and v is not None}
        if "jumlah" in updates:
            try: updates["jumlah"] = int(str(updates["jumlah"]).replace(".", "").replace(",", ""))
            except: updates.pop("jumlah")
        if not updates:
            raise HTTPException(status_code=400, detail="Tidak ada field valid untuk diupdate")
        all_fin = get_finance()
        if not next((x for x in all_fin if x.get("id") == fin_id), None):
            raise HTTPException(status_code=404, detail=f"{fin_id} tidak ditemukan")
        result = update_finance(fin_id, updates)
        if not result:
            raise HTTPException(status_code=500, detail="Gagal update detail")
        return {"status": "ok", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Finance: delete ────────────────────────────────────────────────────────────
@app.delete("/storage/finance/{fin_id}")
async def api_delete_finance(fin_id: str):
    try:
        from storage.manager import delete_finance
        ok = delete_finance(fin_id.upper())
        if not ok:
            raise HTTPException(status_code=404, detail=f"{fin_id} tidak ditemukan")
        return {"status": "ok", "deleted": fin_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════════════════════════════
# BUDGET & EXPENSE endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/budgets")
async def api_list_budgets(status: str = "active", type: str = ""):
    """List semua budget dengan summary."""
    try:
        from storage.manager import list_budgets, compute_budget_summary
        budgets = list_budgets(status=status, budget_type=type or None)
        summaries = []
        for b in budgets:
            s = compute_budget_summary(b["budget_id"])
            if "error" not in s:
                summaries.append(s)
        return {"budgets": summaries, "total": len(summaries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/budgets/alerts")
async def api_budget_alerts(threshold: float = 80.0):
    """Budget yang hampir habis atau over budget."""
    try:
        from storage.manager import detect_near_limit_budgets
        alerts = detect_near_limit_budgets(threshold=threshold)
        return {"alerts": alerts, "total": len(alerts)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/budgets/ops/monthly")
async def api_ops_monthly(year: int = 0, month: int = 0):
    """Ringkasan budget ops per bulan."""
    try:
        from storage.manager import get_ops_summary_by_month
        from datetime import datetime as _dt
        y = year  or _dt.now().year
        m = month or _dt.now().month
        summaries = get_ops_summary_by_month(y, m)
        return {"year": y, "month": m, "summaries": summaries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/budgets/{budget_id}")
async def api_get_budget(budget_id: str, month: int = 0):
    """Detail satu budget + summary."""
    try:
        from storage.manager import compute_budget_summary
        summary = compute_budget_summary(budget_id.upper(), month=month or None)
        if "error" in summary:
            raise HTTPException(status_code=404, detail=summary["error"])
        return summary
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ops-categories")
async def api_ops_categories():
    """List semua kategori operasional."""
    try:
        from storage.manager import get_ops_categories
        return {"categories": get_ops_categories()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/expense-links/{budget_id}")
async def api_expense_links(budget_id: str):
    """List expense links untuk satu budget."""
    try:
        from storage.manager import get_links_by_budget
        links = get_links_by_budget(budget_id.upper())
        return {"budget_id": budget_id, "links": links, "total": len(links)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/expense-links/doc/{doc_id}")
async def api_links_by_doc(doc_id: str):
    """List expense links untuk satu dokumen."""
    try:
        from storage.manager import get_links_by_doc
        links = get_links_by_doc(doc_id.upper())
        return {"doc_id": doc_id, "links": links, "total": len(links)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/budgets/{budget_id}/close")
async def api_close_budget(budget_id: str):
    """Tutup budget — bypass LLM, langsung ke storage."""
    try:
        from storage.manager import close_budget, get_budget_by_id, get_links_by_budget
        bid = budget_id.upper()
        budget = get_budget_by_id(bid)
        if not budget:
            raise HTTPException(status_code=404, detail=f"Budget '{bid}' tidak ditemukan.")
        if budget.get("status") == "closed":
            raise HTTPException(status_code=400, detail=f"Budget '{bid}' sudah ditutup.")
        result = close_budget(bid)
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        links = get_links_by_budget(bid)
        return {
            "success":     True,
            "budget_id":   bid,
            "name":        result.get("name"),
            "status":      "closed",
            "links_count": len(links),
            "message":     f"Budget '{result.get('name')}' berhasil ditutup. {len(links)} expense link tetap tersimpan untuk audit.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    agent.clear_session(session_id)
    return {"message": "Session cleared"}


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS DASHBOARD endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/analytics/summary")
async def analytics_summary(bulan: int = 0, tahun: int = 0):
    """
    Endpoint utama Visual Analytics Dashboard.
    Aggregate semua data dari storage dan kembalikan dalam satu response.
    Query params (optional): bulan (1-12), tahun (YYYY)
    """
    try:
        from storage.manager import (
            load_index, get_finance, get_finance_config,
            list_budgets, compute_budget_summary, get_all_budget_summaries,
            get_links_by_budget
        )
        from datetime import datetime as _dt
        import calendar

        now   = _dt.now()
        tahun = tahun or now.year
        bulan = bulan or now.month

        # ── Helper ────────────────────────────────────────────────────────────
        def _month_prefix(y, m):
            return f"{y}-{m:02d}"

        def _in_period(iso_str, y, m):
            """True kalau iso_str (created_at) masuk bulan/tahun yang dipilih."""
            try:
                return iso_str[:7] == _month_prefix(y, m)
            except Exception:
                return False

        def _to_int(v):
            try:
                return int(v)
            except Exception:
                return 0

        # ── 1. Finance (Reimburse + Kasbon) ───────────────────────────────────
        all_finance    = get_finance()
        finance_period = [x for x in all_finance if _in_period(x.get("created_at", ""), tahun, bulan)]

        rmb_all    = [x for x in all_finance    if x.get("jenis") == "reimburse"]
        cas_all    = [x for x in all_finance    if x.get("jenis") == "kasbon"]
        rmb_period = [x for x in finance_period if x.get("jenis") == "reimburse"]
        cas_period = [x for x in finance_period if x.get("jenis") == "kasbon"]

        total_rmb_period   = sum(_to_int(x.get("jumlah", 0)) for x in rmb_period if x.get("status") == "approved")
        total_cas_outstanding = sum(_to_int(x.get("jumlah", 0)) for x in cas_all if x.get("status") not in ("approved", "rejected"))
        cas_outstanding_count = len([x for x in cas_all if x.get("status") not in ("approved", "rejected")])

        # ── 2. PR ─────────────────────────────────────────────────────────────
        all_pr         = load_index("pr")
        pr_pending     = [x for x in all_pr if x.get("status") == "pending"]
        pr_approved    = [x for x in all_pr if x.get("status") == "approved"]
        pr_period      = [x for x in all_pr if _in_period(x.get("created_at", ""), tahun, bulan)]

        # ── 3. PO ─────────────────────────────────────────────────────────────
        all_po         = load_index("po")
        po_period      = [x for x in all_po if _in_period(x.get("created_at", ""), tahun, bulan)]
        total_po_period = sum(_to_int(x.get("total", 0)) for x in po_period)
        po_pending     = [x for x in all_po if x.get("status") == "pending"]

        # ── 4. Invoice ────────────────────────────────────────────────────────
        all_inv        = load_index("inv")
        inv_period     = [x for x in all_inv if _in_period(x.get("created_at", ""), tahun, bulan)]
        inv_unpaid     = [x for x in all_inv if x.get("status") in ("draft", "issued")]
        inv_paid_period = [x for x in inv_period if x.get("status") == "paid"]
        total_inv_paid_period = sum(_to_int(x.get("total", 0)) for x in inv_paid_period)

        # ── 5. Budget summary ─────────────────────────────────────────────────
        budget_summaries   = get_all_budget_summaries(status="active")
        total_budget_active = sum(s.get("total_budget", 0) for s in budget_summaries)
        total_budget_used   = sum(s.get("total_used",   0) for s in budget_summaries)
        budget_pct_overall  = round((total_budget_used / total_budget_active * 100), 1) if total_budget_active > 0 else 0
        budget_alerts       = [s for s in budget_summaries if s.get("alert") in ("OVER_BUDGET", "NEAR_LIMIT")]

        # ── 6. Tren 6 bulan terakhir (pengeluaran approved) ───────────────────
        trend_months = []
        for delta in range(5, -1, -1):
            # Hitung bulan mundur dari bulan yang dipilih
            target_month = bulan - delta
            target_year  = tahun
            while target_month <= 0:
                target_month += 12
                target_year  -= 1
            label = f"{calendar.month_abbr[target_month]} {str(target_year)[-2:]}"
            # Pengeluaran = reimburse approved + kasbon approved (sudah lunas)
            rmb_m = sum(
                _to_int(x.get("jumlah", 0)) for x in rmb_all
                if _in_period(x.get("created_at", ""), target_year, target_month)
                and x.get("status") == "approved"
            )
            cas_m = sum(
                _to_int(x.get("jumlah", 0)) for x in cas_all
                if _in_period(x.get("created_at", ""), target_year, target_month)
                and x.get("status") == "approved"
            )
            po_m = sum(
                _to_int(x.get("total", 0)) for x in all_po
                if _in_period(x.get("created_at", ""), target_year, target_month)
                and x.get("status") == "approved"
            )
            trend_months.append({
                "label":   label,
                "year":    target_year,
                "month":   target_month,
                "reimburse": rmb_m,
                "kasbon":    cas_m,
                "po":        po_m,
                "total":     rmb_m + cas_m + po_m,
            })

        # ── 7. Expense by category (dari expense_links) ───────────────────────
        # Fetch semua budget (active + closed) untuk lookup nama yang benar
        all_budgets_raw   = list_budgets(status=None)   # semua status
        active_budget_ids = {s["budget_id"] for s in budget_summaries}

        # Build lookup dict: budget_id → nama bersih
        def _clean_budget_name(b):
            name = b.get("name") or b.get("budget_name") or b.get("budget_id", "")
            # Hilangkan prefix "Budget Ops " dan suffix tahun supaya lebih singkat
            name = name.replace("Budget Ops ", "").replace("Budget Ops", "")
            return name.strip() or b.get("budget_id", "Lainnya")

        # Deteksi nama yang duplikat di antara closed budgets
        # supaya bisa tambahkan budget ID sebagai disambiguator
        closed_budgets_raw = [b for b in all_budgets_raw if b.get("status") == "closed"]
        closed_name_counts = {}
        for b in closed_budgets_raw:
            n = _clean_budget_name(b)
            closed_name_counts[n] = closed_name_counts.get(n, 0) + 1

        budget_lookup = {}
        for b in all_budgets_raw:
            bid    = b.get("budget_id", "")
            status = b.get("status", "active")
            name   = _clean_budget_name(b)
            # Kalau closed dan namanya duplikat → tambahkan budget ID
            if status == "closed" and closed_name_counts.get(name, 0) > 1:
                label = f"{name} ({bid})"
            else:
                label = name
            budget_lookup[bid] = {
                "name":   label,
                "status": status,
                "type":   b.get("type", "project"),
            }

        all_links    = load_index("expense_links")
        cat_map_active = {}
        cat_map_closed = {}

        for lnk in all_links:
            # Filter by tahun saja (bukan bulan) — donut menampilkan akumulasi tahunan
            linked_at = lnk.get("linked_at", "")
            if not linked_at or not linked_at.startswith(str(tahun)):
                continue
            bid    = lnk.get("budget_id", "")
            amount = lnk.get("amount", 0)
            info   = budget_lookup.get(bid, {"name": bid, "status": "active", "type": "project"})
            label  = info["name"] or bid

            if info["status"] == "closed":
                cat_map_closed[label] = cat_map_closed.get(label, 0) + amount
            else:
                cat_map_active[label] = cat_map_active.get(label, 0) + amount

        expense_by_category_active = [
            {"label": k, "amount": round(v)}
            for k, v in sorted(cat_map_active.items(), key=lambda x: -x[1])
        ]
        expense_by_category_closed = [
            {"label": k, "amount": round(v)}
            for k, v in sorted(cat_map_closed.items(), key=lambda x: -x[1])
        ]
        # Backward compat — gabungan untuk field lama
        expense_by_category = expense_by_category_active + expense_by_category_closed

        # ── 8. Outstanding items (tabel) ───────────────────────────────────────
        outstanding_items = []
        for x in cas_all:
            if x.get("status") not in ("approved", "rejected"):
                outstanding_items.append({
                    "type":   "Kasbon",
                    "id":     x.get("id"),
                    "nama":   x.get("nama"),
                    "jumlah": _to_int(x.get("jumlah", 0)),
                    "status": x.get("status"),
                    "tanggal": x.get("tanggal", x.get("created_at", "")[:10]),
                })
        for x in pr_pending:
            outstanding_items.append({
                "type":   "PR",
                "id":     x.get("id"),
                "nama":   x.get("pemohon"),
                "jumlah": _to_int(x.get("total", 0)),
                "status": "pending",
                "tanggal": x.get("tanggal", x.get("created_at", "")[:10]),
            })
        for x in inv_unpaid:
            outstanding_items.append({
                "type":   "Invoice",
                "id":     x.get("id"),
                "nama":   x.get("klien_nama"),
                "jumlah": _to_int(x.get("total", 0)),
                "status": x.get("status"),
                "tanggal": x.get("created_at", "")[:10],
            })

        # ── 9. Budget vs Actual per project ───────────────────────────────────
        budget_vs_actual = []
        for s in budget_summaries:
            budget_vs_actual.append({
                "budget_id":    s["budget_id"],
                "name":         s["budget_name"],
                "type":         s["type"],
                "total_budget": s["total_budget"],
                "total_used":   s["total_used"],
                "remaining":    s["remaining"],
                "pct_used":     s["pct_used"],
                "alert":        s.get("alert"),
            })

        # ── Compose response ───────────────────────────────────────────────────
        return {
            "period": {
                "bulan": bulan,
                "tahun": tahun,
                "label": f"{calendar.month_name[bulan]} {tahun}",
            },
            "kpi": {
                "total_reimburse_approved":  total_rmb_period,
                "total_kasbon_outstanding":  total_cas_outstanding,
                "kasbon_outstanding_count":  cas_outstanding_count,
                "total_po_period":           total_po_period,
                "total_inv_paid_period":     total_inv_paid_period,
                "inv_unpaid_count":          len(inv_unpaid),
                "budget_pct_overall":        budget_pct_overall,
                "budget_total_active":       round(total_budget_active),
                "budget_total_used":         round(total_budget_used),
                "budget_alert_count":        len(budget_alerts),
                "pr_pending_count":          len(pr_pending),
                "po_pending_count":          len(po_pending),
            },
            "trend_6_bulan":                trend_months,
            "expense_by_category":          expense_by_category,
            "expense_by_category_active":   expense_by_category_active,
            "expense_by_category_closed":   expense_by_category_closed,
            "budget_vs_actual":             budget_vs_actual,
            "outstanding_items":   outstanding_items,
            "raw_counts": {
                "finance": len(all_finance),
                "pr":      len(all_pr),
                "po":      len(all_po),
                "qt":      len(load_index("qt")),
                "inv":     len(all_inv),
                "budget":  len(list_budgets()),
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
