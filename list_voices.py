"""
Script bantu: list voice ElevenLabs yang KE-AKSES lewat API di free tier.

Voice dari Voice Library (kategori "community") tidak bisa dipakai lewat API
di free tier (error 402 payment_required), meskipun sudah di-"Add to my voices"
dari dashboard. Yang bisa dipakai: kategori "premade" (bawaan tiap akun) atau
"cloned" (hasil Instant Voice Cloning milik sendiri).

Cara pakai:
  1. pip install httpx python-dotenv --break-system-packages   (kalau belum ada)
  2. Jalankan dari folder yang ada file .env -nya (root holomoc-bot V2):
     python list_voices.py
  3. Script otomatis baca ELEVENLABS_API_KEY dari .env di folder yang sama.
"""

import os
from pathlib import Path
import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    print("[!] python-dotenv belum terinstall, .env tidak otomatis kebaca.")
    print("    Install dengan: pip install python-dotenv --break-system-packages")

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


def main():
    if not API_KEY:
        print(
            "[!] ELEVENLABS_API_KEY kosong. Pastikan:\n"
            "    1. File .env ada di folder yang sama dengan list_voices.py, DAN\n"
            "    2. Baris ELEVENLABS_API_KEY=... sudah diisi key asli (bukan placeholder)"
        )
        return

    resp = httpx.get(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": API_KEY},
        timeout=30.0,
    )
    if resp.status_code == 401:
        print(f"[!] 401 Unauthorized -- API key ditolak ElevenLabs. Key yang dipakai (terpotong): {API_KEY[:6]}...{API_KEY[-4:] if len(API_KEY) > 10 else ''}")
        print("    Cek lagi key-nya di elevenlabs.io -> Developer -> API Keys, mungkin ada typo/spasi tersisa.")
        return
    resp.raise_for_status()
    voices = resp.json().get("voices", [])

    usable = [v for v in voices if v.get("category") in ("premade", "cloned")]
    blocked = [v for v in voices if v.get("category") not in ("premade", "cloned")]

    print(f"\n=== BISA DIPAKAI di free tier ({len(usable)}) ===")
    for v in usable:
        labels = v.get("labels", {}) or {}
        print(f"  {v['voice_id']}  |  {v['name']}  |  kategori={v.get('category')}  |  {labels}")

    print(f"\n=== TIDAK BISA via API di free tier ({len(blocked)}) ===")
    for v in blocked:
        print(f"  {v['voice_id']}  |  {v['name']}  |  kategori={v.get('category')}")

    if not usable:
        print(
            "\nTidak ada voice 'premade' di akun ini. Opsi:\n"
            "  1. Pakai Instant Voice Cloning (rekam suara sendiri/orang lain "
            "yang punya izin) -> voice hasil clone otomatis usable via API.\n"
            "  2. Upgrade ke paid plan (Creator tier ke atas) untuk akses "
            "Voice Library via API."
        )


if __name__ == "__main__":
    main()
