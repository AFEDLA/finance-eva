"""
Client Gemini Flash API — pengganti Ollama lokal saat Admin Ola dijalankan
di VPS (bukan PC kantor dengan GPU lokal).

Kenapa modul terpisah, bukan ubah langsung _call_ollama di core.py:
- agent/core.py tetap bisa dipakai di kedua mode (PC lokal dengan Ollama,
  atau VPS dengan Gemini) hanya dengan mengganti satu env var (LLM_PROVIDER),
  tanpa menyentuh logic skill-routing/intent-classification yang sudah stabil.
- Memudahkan rollback: kalau Gemini API bermasalah, tinggal ganti env var
  balik ke "ollama" tanpa redeploy kode.

Format yang dipertahankan SAMA dengan _call_ollama agar caller (core.py)
tidak perlu tahu provider mana yang dipakai:
- Input: system_prompt (str), messages (list of {"role", "content"}),
  use_vision (bool, diabaikan di Gemini karena semua model Gemini Flash
  sudah multimodal native, tidak perlu vision model terpisah seperti llava).
- Output: string reply biasa.

Format messages yang didukung (sama seperti yang sudah dipakai core.py
untuk Ollama, konvensi OpenAI-style):
- content berupa string biasa -> teks
- content berupa list of dict dengan {"type": "image_url", "image_url": {"url": "data:mime;base64,..."}}
  dan {"type": "text", "text": "..."} -> dikonversi ke Gemini inline_data + text part
"""

import base64
import logging
import os
import re

import httpx

logger = logging.getLogger("hola.gemini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _openai_content_to_gemini_parts(content) -> list[dict]:
    """Konversi content message (string atau list OpenAI-style) ke list of
    Gemini 'parts'. Mendukung campuran teks dan gambar base64."""
    if isinstance(content, str):
        return [{"text": content}]

    parts = []
    for item in content:
        if item.get("type") == "text":
            parts.append({"text": item["text"]})
        elif item.get("type") == "image_url":
            url = item["image_url"]["url"]
            # Format: data:image/jpeg;base64,<data>
            match = re.match(r"^data:([^;]+);base64,(.+)$", url)
            if match:
                mime_type, b64data = match.group(1), match.group(2)
                parts.append({
                    "inline_data": {"mime_type": mime_type, "data": b64data}
                })
    return parts or [{"text": ""}]


def _messages_to_gemini_contents(messages: list) -> list[dict]:
    """Konversi list messages OpenAI-style ke format 'contents' Gemini.
    Gemini hanya kenal role 'user' dan 'model' (bukan 'assistant')."""
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        parts = _openai_content_to_gemini_parts(msg["content"])
        contents.append({"role": role, "parts": parts})
    return contents


async def call_gemini(system_prompt: str, messages: list, use_vision: bool = False) -> str:
    """
    Panggil Gemini Flash API. Signature kompatibel dengan Agent._call_ollama
    supaya bisa langsung dipakai sebagai pengganti tanpa mengubah caller.

    use_vision diabaikan secara fungsional (Gemini Flash sudah multimodal
    native untuk semua request), parameter ini dipertahankan hanya supaya
    signature tetap identik dan core.py tidak perlu diubah strukturnya.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY belum di-set. Tambahkan di .env: GEMINI_API_KEY=AIza..."
        )

    contents = _messages_to_gemini_contents(messages)
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"temperature": 0.7},
    }

    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                # Bisa terjadi kalau diblokir safety filter Gemini.
                finish_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
                logger.warning(f"[Gemini] Tidak ada candidate, kemungkinan diblokir: {finish_reason}")
                return "Maaf, saya tidak bisa merespons permintaan itu. Bisa dicoba dengan kalimat lain?"
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
    except httpx.HTTPStatusError as e:
        logger.error(f"[Gemini] HTTP error {e.response.status_code}: {e.response.text[:500]}")
        raise
    except Exception as e:
        logger.error(f"[Gemini] Gagal panggil API: {e}")
        raise
