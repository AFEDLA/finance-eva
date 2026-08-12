"""
Modul Text-to-Speech menggunakan ElevenLabs API (full pengganti edge-tts, R&D V2).

Kenapa pindah dari edge-tts ke ElevenLabs:
- Kualitas suara ElevenLabs (model eleven_multilingual_v2 / eleven_flash_v2_5)
  jauh lebih natural dan ekspresif dibanding Microsoft Neural TTS, terutama
  untuk intonasi percakapan (bukan sekadar pembacaan teks datar).
- ElevenLabs mendukung Bahasa Indonesia secara resmi di model multilingual-nya.

Bagaimana lip-sync presisi tetap dipertahankan:
- edge-tts dulu memberi word-level timing langsung lewat event WordBoundary.
- ElevenLabs tidak punya event per-kata, tapi endpoint .../with-timestamps
  memberi CHARACTER-level timing (offset + durasi per karakter, presisi dari
  audio asli, bukan estimasi). Modul ini menyusun ulang timing per-kata dari
  timing per-karakter tsb (lihat _words_from_character_alignment), sehingga
  pipeline viseme (head.speakAudio() di TalkingHead.js) tidak berubah sama sekali.

Konfigurasi (di .env):
  ELEVENLABS_API_KEY   -> wajib, dari elevenlabs.io -> Developer -> API Key
  ELEVENLABS_VOICE_ID  -> wajib, voice_id suara "Admin Ola"
  ELEVENLABS_MODEL_ID  -> opsional, default eleven_multilingual_v2
                          (ganti ke eleven_flash_v2_5 kalau mau respons lebih
                          cepat / hemat kuota free tier, lihat README_ELEVENLABS.md)
"""

import asyncio
import base64
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("hola.tts")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

# Voice default: dikonfigurasi lewat .env (ELEVENLABS_VOICE_ID), bukan hardcode,
# supaya gampang ganti voice tanpa ubah kode (mis. saat coba-coba kandidat suara).
DEFAULT_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")
DEFAULT_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# Batas wajar 1 kalimat TTS supaya tidak terlalu panjang dan responsif.
MAX_TTS_CHARS = 2000

# ============================================================
# GRAPHEME-TO-VISEME UNTUK BAHASA INDONESIA
#
# Setelah timing per-karakter dari ElevenLabs disusun ulang jadi timing PER
# KATA (lihat _words_from_character_alignment), kita tetap tidak punya data
# viseme eksplisit per fonem. Tanpa itu, head.speakAudio() di TalkingHead.js
# hanya menggerakkan mulut secara generik berdasarkan durasi kata (buka selama
# durasi kata, tutup di antaranya) — inilah sebab lip sync terlihat "buka-tutup
# doang" meskipun timing kata sudah presisi.
#
# Bahasa Indonesia adalah bahasa fonetis yang sangat konsisten (ejaan ~ lafal,
# mirip kasus Finnish di dokumentasi TalkingHead), sehingga direct mapping
# grapheme->viseme bisa memberi akurasi tinggi tanpa perlu dictionary fonem.
#
# 15 viseme Oculus yang didukung TalkingHead: viseme_sil, viseme_PP, viseme_FF,
# viseme_TH, viseme_DD, viseme_kk, viseme_CH, viseme_SS, viseme_nn, viseme_RR,
# viseme_aa, viseme_E, viseme_I, viseme_O, viseme_U
# ============================================================

_VOWEL_VISEME = {
    "a": "aa", "i": "I", "u": "U", "e": "E", "o": "O",
}

_CONSONANT_VISEME = {
    "b": "PP", "p": "PP", "m": "PP",
    "f": "FF", "v": "FF",
    "s": "SS", "z": "SS", "x": "SS",
    "d": "DD", "t": "DD",
    "n": "nn", "l": "nn",
    "k": "kk", "g": "kk", "q": "kk", "h": "kk",
    "r": "RR",
    "c": "CH", "j": "CH",
    "w": "U", "y": "I",
}

# Bobot durasi relatif per viseme (vokal lebih lama dari konsonan, natural
# untuk pengucapan Bahasa Indonesia yang silabis terbuka konsonan-vokal).
_VISEME_WEIGHT = {
    "aa": 1.3, "O": 1.2, "U": 1.1, "E": 1.1, "I": 1.0,
    "PP": 0.7, "FF": 0.7, "TH": 0.7, "DD": 0.7, "kk": 0.7,
    "CH": 0.8, "SS": 0.7, "nn": 0.7, "RR": 0.8,
}


def _word_to_viseme_sequence(word: str) -> list[str]:
    """Pecah satu kata jadi urutan viseme berdasarkan huruf-huruf signifikan.
    Konsonan ganda/berdekatan dan huruf tak dikenal disaring supaya urutan
    viseme tidak terlalu padat (over-animated)."""
    sequence = []
    prev_viseme = None
    for ch in word.lower():
        viseme = _VOWEL_VISEME.get(ch) or _CONSONANT_VISEME.get(ch)
        if viseme is None:
            continue
        # Lewati kalau viseme sama persis dengan sebelumnya (mis. "ss" dobel)
        if viseme == prev_viseme:
            continue
        sequence.append(viseme)
        prev_viseme = viseme
    return sequence or ["aa"]  # fallback: kata tanpa huruf dikenali tetap "bicara"


def _generate_visemes_for_words(
    words: list[str], wtimes: list[int], wdurations: list[int]
) -> tuple[list[str], list[int], list[int]]:
    """Untuk setiap kata, distribusikan urutan viseme-nya proporsional di dalam
    window waktu [wtimes[i], wtimes[i]+wdurations[i]] yang sudah presisi dari
    edge-tts. Hasilnya: array visemes/vtimes/vdurations siap pakai head.speakAudio().
    """
    visemes: list[str] = []
    vtimes: list[int] = []
    vdurations: list[int] = []

    for word, wtime, wduration in zip(words, wtimes, wdurations):
        clean_word = re.sub(r"[^a-zA-Z]", "", word)
        seq = _word_to_viseme_sequence(clean_word)
        if not seq or wduration <= 0:
            continue

        total_weight = sum(_VISEME_WEIGHT.get(v, 0.8) for v in seq)
        cursor = wtime
        for v in seq:
            weight = _VISEME_WEIGHT.get(v, 0.8)
            dur = max(40, int(wduration * (weight / total_weight)))
            visemes.append(v)
            vtimes.append(cursor)
            vdurations.append(dur)
            cursor += dur

    return visemes, vtimes, vdurations


def _words_from_character_alignment(
    characters: list[str], starts: list[float], ends: list[float]
) -> tuple[list[str], list[int], list[int]]:
    """Susun ulang timing per-kata dari timing per-karakter yang dikembalikan
    ElevenLabs (alignment.characters / character_start_times_seconds /
    character_end_times_seconds). Kata dipisah berdasarkan whitespace, sama
    seperti cara edge-tts membagi WordBoundary, supaya pipeline viseme di
    bawah (_generate_visemes_for_words) tidak perlu berubah."""
    words: list[str] = []
    wtimes: list[int] = []
    wdurations: list[int] = []

    current_chars: list[str] = []
    current_start: float | None = None
    current_end: float = 0.0

    for ch, start, end in zip(characters, starts, ends):
        if ch.isspace():
            if current_chars:
                words.append("".join(current_chars))
                wtimes.append(int(current_start * 1000))
                wdurations.append(max(1, int((current_end - current_start) * 1000)))
                current_chars = []
                current_start = None
            continue
        if current_start is None:
            current_start = start
        current_chars.append(ch)
        current_end = end

    if current_chars:
        words.append("".join(current_chars))
        wtimes.append(int(current_start * 1000))
        wdurations.append(max(1, int((current_end - current_start) * 1000)))

    return words, wtimes, wdurations


def _rate_to_speed(rate: str) -> float:
    """Konversi format rate ala edge-tts ('+20%' / '-15%', yang dikirim apa
    adanya oleh main.py lewat _rate_to_edge_format) jadi parameter `speed`
    ElevenLabs. ElevenLabs membatasi speed 0.7 - 1.2 (1.0 = normal); di luar
    itu kualitas audio bisa menurun, jadi di-clamp."""
    try:
        pct = int(str(rate).replace("%", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        pct = 0
    speed = 1.0 + (pct / 100)
    return max(0.7, min(1.2, speed))


@dataclass
class TTSResult:
    audio_base64: str
    words: list[str] = field(default_factory=list)
    wtimes: list[int] = field(default_factory=list)      # ms, start time tiap kata
    wdurations: list[int] = field(default_factory=list)  # ms, durasi tiap kata
    visemes: list[str] = field(default_factory=list)     # Oculus viseme ID per fonem
    vtimes: list[int] = field(default_factory=list)      # ms, start time tiap viseme
    vdurations: list[int] = field(default_factory=list)  # ms, durasi tiap viseme
    emojis: list[dict] = field(default_factory=list)     # [{emoji, position(0-1)}], untuk trigger ekspresi
    mime_type: str = "audio/mpeg"


def _normalize_numbers(text: str) -> str:
    """
    Konversi angka dan format numerik ke bentuk yang natural diucapkan
    dalam Bahasa Indonesia, supaya ElevenLabs tidak membaca digit per digit.

    Urutan penerapan penting — dari yang paling spesifik ke paling umum.
    """
    import re

    # 1. Mata uang Rupiah — Rp 135.701.500 → "seratus tiga puluh lima juta..."
    #    Dikonversi ke terbilang supaya natural, tapi karena terbilang kompleks
    #    kita pakai format "X rupiah" yang sudah cukup natural untuk TTS.
    def _rupiah(m):
        raw = m.group(2).replace(".", "").replace(",", "")
        try:
            n = int(raw)
            return _terbilang(n) + " rupiah"
        except:
            return m.group(0)
    text = re.sub(r'(Rp\.?\s*)([\d.,]+)', _rupiah, text, flags=re.IGNORECASE)

    # 2. Persentase — 85% → "delapan puluh lima persen"
    def _persen(m):
        try:
            return _terbilang(int(m.group(1))) + " persen"
        except:
            return m.group(0)
    text = re.sub(r'(\d+)%', _persen, text)

    # 3. Tanggal — 2026-06-22 → "22 Juni 2026"
    BULAN = ['','Januari','Februari','Maret','April','Mei','Juni',
             'Juli','Agustus','September','Oktober','November','Desember']
    def _tanggal_iso(m):
        try:
            y,mo,d = int(m.group(1)),int(m.group(2)),int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{d} {BULAN[mo]} {y}"
        except: pass
        return m.group(0)
    text = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b', _tanggal_iso, text)

    # 4. Waktu — 13:20 → "pukul tiga belas dua puluh"
    def _waktu(m):
        try:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                jam_str = _terbilang(h)
                mnt_str = "tepat" if mn == 0 else _terbilang(mn)
                return f"pukul {jam_str}" + ("" if mn == 0 else f" {mnt_str}")
        except: pass
        return m.group(0)
    text = re.sub(r'\b(\d{1,2}):(\d{2})\b', _waktu, text)

    # 5. Angka dengan pemisah ribuan (titik) — 13.455.000 → terbilang
    def _angka_titik(m):
        raw = m.group(0).replace(".", "")
        try:
            return _terbilang(int(raw))
        except:
            return m.group(0)
    text = re.sub(r'\b\d{1,3}(?:\.\d{3})+\b', _angka_titik, text)

    # 6. Angka biasa sisa — konversi ke terbilang kalau <= 999 miliar
    def _angka_biasa(m):
        try:
            n = int(m.group(0))
            if n <= 999_000_000_000:
                return _terbilang(n)
        except: pass
        return m.group(0)
    text = re.sub(r'\b\d+\b', _angka_biasa, text)

    return text


def _terbilang(n: int) -> str:
    """Konversi integer ke kata Bahasa Indonesia. Mendukung hingga ratusan miliar."""
    if n < 0:
        return "minus " + _terbilang(-n)
    if n == 0:
        return "nol"

    satuan = ["", "satu", "dua", "tiga", "empat", "lima",
              "enam", "tujuh", "delapan", "sembilan", "sepuluh",
              "sebelas", "dua belas", "tiga belas", "empat belas",
              "lima belas", "enam belas", "tujuh belas", "delapan belas",
              "sembilan belas"]

    def _ratusan(x: int) -> str:
        if x == 0: return ""
        if x < 20: return satuan[x]
        if x < 100:
            puluhan = x // 10
            sisa    = x % 10
            return ["", "", "dua puluh", "tiga puluh", "empat puluh",
                    "lima puluh", "enam puluh", "tujuh puluh",
                    "delapan puluh", "sembilan puluh"][puluhan] \
                   + (" " + satuan[sisa] if sisa else "")
        ratus = x // 100
        sisa  = x % 100
        prefix = "seratus" if ratus == 1 else satuan[ratus] + " ratus"
        return prefix + (" " + _ratusan(sisa) if sisa else "")

    parts = []
    if n >= 1_000_000_000:
        parts.append(_ratusan(n // 1_000_000_000) + " miliar")
        n %= 1_000_000_000
    if n >= 1_000_000:
        bagian = n // 1_000_000
        parts.append(("satu" if bagian == 1 else _ratusan(bagian)) + " juta")
        n %= 1_000_000
    if n >= 1_000:
        bagian = n // 1_000
        parts.append(("seribu" if bagian == 1 else _ratusan(bagian) + " ribu"))
        n %= 1_000
    if n > 0:
        parts.append(_ratusan(n))

    return " ".join(parts)


def _clean_text_for_tts(text: str) -> str:
    """Bersihkan markdown, normalisasi angka, dan simbol sebelum dikirim ke TTS."""
    import re
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text)        # **bold**
    cleaned = re.sub(r"[*_`#]", "", cleaned)               # markdown sisa
    cleaned = re.sub(r"^[-•]\s*", "", cleaned, flags=re.M) # bullet list
    cleaned = re.sub(r"\n+", " ", cleaned)                 # newline → spasi
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _normalize_numbers(cleaned)                  # angka → terbilang
    cleaned = re.sub(r"\s+", " ", cleaned).strip()        # rapikan spasi sisa
    return cleaned[:MAX_TTS_CHARS]


# Rentang Unicode emoji umum (emoticons, symbols & pictographs, transport,
# supplemental symbols, dingbats). edge-tts akan membaca nama emoji ini
# secara literal kalau tidak disaring sebelum dikirim ke TTS — emoji harus
# diekstrak dan dipakai sebagai trigger ekspresi wajah, bukan diucapkan.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-c
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-a
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F1E6-\U0001F1FF"  # flags
    "]+",
    flags=re.UNICODE,
)


def _extract_emojis(text: str) -> tuple[str, list[dict]]:
    """Hapus emoji dari teks (supaya tidak dibacakan literal oleh TTS) dan
    kembalikan daftar emoji beserta posisi relatifnya (0.0-1.0, berdasarkan
    posisi karakter dalam teks asli) supaya frontend bisa memicu ekspresi
    wajah pada saat yang tepat selama avatar bicara."""
    text_len = max(1, len(text))
    emojis_with_pos = []
    for match in _EMOJI_PATTERN.finditer(text):
        for ch in match.group():
            emojis_with_pos.append({
                "emoji": ch,
                "position": round(match.start() / text_len, 4),
            })
    clean_text = _EMOJI_PATTERN.sub("", text)
    # Rapikan spasi ganda/sisa yang muncul setelah emoji dihapus.
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text, emojis_with_pos


async def _synthesize_edge_tts(
    text: str,
    voice: str,
    rate: str = "+0%",
) -> TTSResult:
    """
    Generate audio + word timing dari teks menggunakan edge-tts (Microsoft Azure Neural TTS, gratis).
    Voice format: "edge:id-ID-GadisNeural" → strip prefix "edge:" sebelum dikirim ke edge-tts.
    Word timing dari edge-tts via event WordBoundary (presisi, langsung per kata).
    """
    import edge_tts
    import io

    # Strip prefix "edge:"
    edge_voice = voice.removeprefix("edge:")

    words: list[str] = []
    wtimes: list[int] = []
    wdurations: list[int] = []
    audio_chunks: list[bytes] = []

    communicate = edge_tts.Communicate(text, edge_voice, rate=rate, boundary="WordBoundary")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append(chunk["text"])
            # edge-tts memberi offset & duration dalam satuan 100-nanosecond ticks
            # konversi ke milliseconds: ticks / 10_000
            wtimes.append(chunk["offset"] // 10_000)
            wdurations.append(chunk["duration"] // 10_000)

    audio_bytes = b"".join(audio_chunks)
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    visemes, vtimes, vdurations = _generate_visemes_for_words(words, wtimes, wdurations)

    return TTSResult(
        audio_base64=audio_b64,
        words=words,
        wtimes=wtimes,
        wdurations=wdurations,
        visemes=visemes,
        vtimes=vtimes,
        vdurations=vdurations,
        emojis=[],  # emoji sudah diekstrak sebelum masuk sini
        mime_type="audio/mpeg",
    )


async def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> TTSResult:
    """
    Generate audio + word timing dari teks.
    Routing otomatis berdasarkan prefix voice:
      - "edge:<voice>"  → edge-tts (Microsoft Azure Neural, gratis)
      - lainnya         → ElevenLabs (production)

    Parameter `pitch` dipertahankan untuk kompatibilitas dengan main.py.
    """
    text_no_emoji, emojis = _extract_emojis(text)
    clean_text = _clean_text_for_tts(text_no_emoji)
    if not clean_text:
        return TTSResult(audio_base64="", emojis=emojis)

    # ── EDGE TTS ──────────────────────────────────────────────────────────────
    if voice and voice.startswith("edge:"):
        result = await _synthesize_edge_tts(clean_text, voice=voice, rate=rate)
        result.emojis = emojis  # inject emojis dari teks asli
        return result

    # ── ELEVENLABS ────────────────────────────────────────────────────────────
    if not ELEVENLABS_API_KEY:
        raise RuntimeError(
            "ELEVENLABS_API_KEY belum di-set di .env. "
            "Ambil API key di elevenlabs.io -> Developer -> API Key."
        )
    if not voice:
        raise RuntimeError(
            "Voice ID ElevenLabs belum di-set (ELEVENLABS_VOICE_ID di .env, "
            "atau parameter voice saat memanggil synthesize())."
        )

    payload = {
        "text": clean_text,
        "model_id": DEFAULT_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
            "speed": _rate_to_speed(rate),
        },
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    url = ELEVENLABS_API_URL.format(voice_id=voice)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"[TTS] ElevenLabs gagal ({e.response.status_code}): {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"[TTS] ElevenLabs gagal: {e}")
        raise

    audio_b64 = data.get("audio_base64", "")
    alignment = data.get("alignment") or {}
    characters = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    words, wtimes, wdurations = _words_from_character_alignment(characters, starts, ends)
    visemes, vtimes, vdurations = _generate_visemes_for_words(words, wtimes, wdurations)

    return TTSResult(
        audio_base64=audio_b64,
        words=words,
        wtimes=wtimes,
        wdurations=wdurations,
        visemes=visemes,
        vtimes=vtimes,
        vdurations=vdurations,
        emojis=emojis,
    )


EDGE_FALLBACK_VOICE = "edge:id-ID-GadisNeural"

async def synthesize_safe(text: str, voice: str = DEFAULT_VOICE, rate: str = "+0%") -> TTSResult | None:
    """
    Wrapper aman: coba ElevenLabs dulu, kalau gagal (API key kosong/habis/error)
    otomatis fallback ke edge-tts supaya avatar tetap bisa bicara.
    Kalau voice sudah "edge:..." langsung pakai edge-tts, tidak coba ElevenLabs.
    """
    try:
        return await synthesize(text, voice=voice, rate=rate)
    except Exception as e:
        # Kalau bukan edge-tts, coba fallback ke edge-tts
        if not (voice and voice.startswith("edge:")):
            logger.warning(f"[TTS] ElevenLabs gagal, fallback ke edge-tts: {e}")
            try:
                text_no_emoji, emojis = _extract_emojis(text)
                clean_text = _clean_text_for_tts(text_no_emoji)
                result = await _synthesize_edge_tts(clean_text, voice=EDGE_FALLBACK_VOICE, rate=rate)
                result.emojis = emojis
                return result
            except Exception as e2:
                logger.warning(f"[TTS] edge-tts fallback juga gagal: {e2}")
        else:
            logger.warning(f"[TTS] edge-tts gagal: {e}")
        return None


if __name__ == "__main__":
    # Quick manual test: python -m api.tts
    # Pastikan ELEVENLABS_API_KEY dan ELEVENLABS_VOICE_ID sudah di-set di .env.
    async def _main():
        if not ELEVENLABS_API_KEY or not DEFAULT_VOICE:
            print("ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID belum di-set di .env")
            return
        result = await synthesize("Halo! Saya Admin Ola, siap membantu administrasi Holomoc Indonesia.")
        print(f"Audio bytes (base64 len): {len(result.audio_base64)}")
        print(f"Words: {result.words}")
        print(f"Times: {result.wtimes}")
        print(f"Durations: {result.wdurations}")

    asyncio.run(_main())
