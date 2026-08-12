"""
Client Hermes Agent API — pengganti Ollama lokal saat Admin Ola dijalankan
di VPS dengan Hermes Agent (OpenAI-compatible endpoint via ai.hajid.dev).

Kenapa modul terpisah, bukan ubah langsung _call_ollama di core.py:
- agent/core.py tetap bisa dipakai di semua mode (PC lokal Ollama, Gemini,
  atau Hermes) hanya dengan mengganti satu env var (LLM_PROVIDER),
  tanpa menyentuh logic skill-routing yang sudah stabil.
- Rollback mudah: kalau Hermes bermasalah, tinggal ganti LLM_PROVIDER=ollama
  di .env dan restart — tanpa redeploy kode.

Format input/output SAMA dengan gemini_client.call_gemini dan _call_ollama:
- Input : system_prompt (str), messages (list OpenAI-style), use_vision (bool)
- Output: string reply biasa

Konfigurasi via .env:
  LLM_PROVIDER=hermes
  LLM_BASE_URL=http://localhost:9119/v1   (tanya Hajid port Hermes API-nya)
  LLM_API_KEY=                            (kosongkan kalau Hermes tidak pakai auth)
  LLM_MODEL=deepseek-v4-flash             (nama model yang valid di ai.hajid.dev)
  LLM_TIMEOUT=60                          (detik, opsional)
"""

import logging
import os
import re

import httpx

logger = logging.getLogger("hola.hermes")


def _cfg():
    """Baca config fresh dari env setiap call — tidak di-cache di module level."""
    return {
        "base_url": os.getenv("LLM_BASE_URL", "http://localhost:9119/v1").rstrip("/"),
        "api_key":  os.getenv("LLM_API_KEY", ""),
        "model":    os.getenv("LLM_MODEL", "deepseek-v4-flash"),
        "timeout":  float(os.getenv("LLM_TIMEOUT", "60")),
    }


def _convert_messages(system_prompt: str, messages: list) -> list:
    """
    Konversi messages OpenAI-style ke format /v1/chat/completions.
    Vision content (list of image_url + text) dipertahankan as-is karena
    sudah dalam format OpenAI — Hermes/DeepSeek yang support vision akan
    menerimanya langsung.
    """
    result = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        result.append({"role": msg["role"], "content": msg["content"]})
    return result


async def call_hermes(system_prompt: str, messages: list, use_vision: bool = False) -> str:
    """
    Panggil Hermes Agent via OpenAI-compatible /v1/chat/completions endpoint.
    Signature kompatibel dengan _call_ollama dan call_gemini supaya core.py
    tidak perlu diubah strukturnya.

    use_vision diteruskan apa adanya — model yang dipakai tetap satu
    (tidak ada vision model terpisah seperti llava di Ollama), karena
    DeepSeek dan model modern lain sudah multimodal native.
    """
    cfg = _cfg()

    if not cfg["base_url"]:
        raise RuntimeError(
            "LLM_BASE_URL belum di-set. Tambahkan di .env: LLM_BASE_URL=http://localhost:9119/v1"
        )

    all_messages = _convert_messages(system_prompt, messages)

    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload = {
        "model":       cfg["model"],
        "messages":    all_messages,
        "temperature": 0.7,
        "max_tokens":  2048,
        "stream":      False,
    }

    try:
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
            response = await client.post(
                f"{cfg['base_url']}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        reply = data["choices"][0]["message"]["content"].strip()

        # Deteksi karakter CJK nyasar (sama seperti Ollama guard di core.py)
        if re.search(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', reply):
            logger.warning(
                f"[Hermes] ⚠️ Karakter non-Indonesia terdeteksi di reply: {reply[-150:]!r}"
            )

        return reply

    except httpx.HTTPStatusError as e:
        logger.error(f"[Hermes] HTTP error {e.response.status_code}: {e.response.text[:500]}")
        raise
    except Exception as e:
        logger.error(f"[Hermes] Gagal panggil API: {e}")
        raise


async def health_check() -> dict:
    """Probe apakah Hermes endpoint bisa dijangkau."""
    cfg = _cfg()
    try:
        headers = {}
        if cfg["api_key"]:
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{cfg['base_url']}/models", headers=headers)
        return {"status": "ok", "url": cfg["base_url"], "http_code": resp.status_code}
    except Exception as e:
        return {"status": "error", "url": cfg["base_url"], "detail": str(e)}
