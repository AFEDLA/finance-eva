# Reimburse Workflow & Indexing Schema

## Aturan Pemrosesan Reimburse:
1. Semua level akses (Management, Lead, General Staff) bisa mengajukan reimburse, masing-masing dengan limit tertentu (lihat auth-rules.md).
2. **Kenali pola input cepat (compressed single-line):** User Indonesia sering memberi semua detail dalam satu kalimat pendek seperti `Hajid reimburse kopi 50rb` atau `Fikri reimburse bensin 100rb`. Pola: `[nama] reimburse [keperluan] [jumlah]`. Jika user sudah memberikan nama, keperluan, DAN jumlah dalam satu pesan, langsung ke langkah konfirmasi — JANGAN tanya ulang.
3. Jika data tidak lengkap, WAJIB tanyakan dulu sebelum memproses:
   - **Siapa?** → Nama orang yang mengajukan reimburse
   - **Untuk apa?** → Keperluan/biaya yang direimburse
   - **Berapa?** → Jumlah nominal yang diajukan (dalam Rupiah)
   - **Ada bukti?** → Upload foto/scan bukti pembayaran jika ada

   ⚠️ **PENTING — Cek gambar receipt dulu sebelum bertanya:**
   Jika user mengirim foto struk/receipt bersama teks reimburse, JANGAN langsung tanya nominal. Gunakan `vision_analyze` pada gambar untuk mengekstrak jumlah total dari struk secara otomatis. Jumlah biasanya terlihat jelas di receipt (contoh: "Rp 128.000" atau "128.000"). Ini menghemat waktu karena user tidak perlu mengetik ulang nominal yang sudah ada di bukti.
3. Setelah semua data terkumpul, simpan file bukti (jika ada) ke folder arsip dan buat JSON indexing.

## Alur Konfirmasi (Clarification Flow)

Jika user hanya bilang "reimburse" tanpa detail lengkap, balas dengan:

> Baik, saya bantu catatkan reimburse. Mohon info:
> 1. Siapa yang mengajukan? (nama)
> 2. Untuk keperluan apa?
> 3. Berapa jumlahnya?
> 4. Ada bukti pembayaran? (jika ada, silakan dikirim)

Setelah user menjawab, rangkum dan minta konfirmasi:

> Konfirmasi reimburse:
> - Nama: [nama]
> - Keperluan: [tujuan]
> - Jumlah: Rp [jumlah]
> - Bukti: [ada/tidak]
> Simpan?

Jika user konfirmasi (ya/ok/oke/sip/betul/betull/bener/udah/lanjut/simpan), baru proses ke indexing.
Jika user menolak (gajadi/batal/koreksi/nggak), tanyakan revisi atau batalkan.

## Target JSON Schema (Reimburse)

```json
{
  "id": "reimburse_YYYYMMDD_NNN",
  "timestamp_archived": "YYYY-MM-DD HH:mm:ss",
  "sender": "sender_number_or_identifier",
  "category": "reimburse",
  "person_name": "Nama orang yang mengajukan reimburse",
  "amount": 0,
  "currency": "IDR",
  "description": "Keperluan/biaya yang direimburse",
  "file_absolute_path": null
}
```

Jika ada file bukti yang diupload, simpan ke:
`/home/ubuntu/holomoc-file-finance/YYYY/MM/DD/`
dan isi `file_absolute_path` dengan path lengkap file tersebut.

## Index Update Rules

Finance memiliki index file sendiri: `/home/ubuntu/holomoc-file-finance/finance-index.json`
*(CRITICAL: Jangan pernah menggunakan tilde `~`. Selalu gunakan absolute path ini).*

Lihat `references/finance-index-schema.md` untuk detail struktur index, field, dan contoh entry lengkap.

Untuk entry reimburse, gunakan skema entry dengan `category: "reimburse"` dan format id `reimburse_YYYYMMDD_NNN`.

## Koreksi / Update Entry yang Sudah Ada

User sering meminta koreksi setelah entry tersimpan, misalnya:
- "nomor 2 update bukan 40rb tapi 100rb" — perubahan amount
- "koreksi, galon 3 biji" — perubahan description
- "reimburse 001 ganti jadi 200rb" — perubahan amount

**Handle dengan Step 6 di SKILL.md utama.** Gunakan script `scripts/update_finance.py` untuk update programmatik.

**PENTING:** "koreksi" di konteks update BUKAN berarti tolak/batal. Ini adalah permintaan perubahan data entry yang sudah ada, bukan pembatalan transaksi. Bedakan dengan "gajadi" / "batal" yang berarti batalkan seluruh pengajuan.
