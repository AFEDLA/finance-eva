"""
Client Groq API — digunakan khusus untuk vision/OCR struk/bon.
Groq menyediakan model llama-4 vision yang gratis dengan limit 14.400 req/hari.

Kenapa modul terpisah:
- Groq hanya dipakai untuk vision struk, bukan chat biasa
- Chat tetap pakai Hermes/DeepSeek via LLM_BASE_URL
- Mudah diganti/dinonaktifkan tanpa menyentuh logic lain

Konfigurasi via .env:
  GROQ_API_KEY=gsk_xxxx         (dari console.groq.com)
  GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct  (default)

Format request: OpenAI-compatible — sama persis dengan hermes_client.py
"""

import logging
import os
import re

import httpx

logger = logging.getLogger("hola.groq")

GROQ_API_BASE = "https://api.groq.com/openai/v1"
GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "meta-llama/llama-4-scout-17b-16e-instruct"
)


async def extract_receipt(
    system_prompt: str,
    image_b64: str,
    mime_type: str,
    user_message: str = "",
) -> str:
    """
    Kirim gambar struk ke Groq untuk diekstrak datanya.
    Return string JSON mentah dari model — parsing dilakukan di caller.
    
    Raise RuntimeError kalau GROQ_API_KEY belum di-set.
    Raise httpx.HTTPStatusError kalau API error.
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY belum di-set. Tambahkan di .env: GROQ_API_KEY=gsk_..."
        )

    model = GROQ_VISION_MODEL

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_b64}"
                    }
                },
                {
                    "type": "text",
                    "text": user_message or "Ekstrak data struk ini sesuai instruksi system prompt."
                }
            ]
        }
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 512,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{GROQ_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    raw = data["choices"][0]["message"]["content"].strip()

    # Deteksi karakter CJK nyasar
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', raw):
        logger.warning(f"[Groq] Karakter non-Indonesia terdeteksi: {raw[-100:]!r}")

    logger.info(f"[Groq] Vision struk berhasil via {model}")
    return raw


async def health_check() -> dict:
    """Probe apakah Groq API bisa dijangkau."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "GROQ_API_KEY belum di-set"}
    try:
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GROQ_API_BASE}/models", headers=headers)
        return {"status": "ok", "http_code": resp.status_code}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
