# Cashbon Workflow & Indexing Schema

## Aturan Pemrosesan Cashbon:
1. Tolak jika pengirim adalah `General Staff`.
2. **Kenali pola input cepat (compressed single-line):** User Indonesia sering memberi semua detail dalam satu kalimat pendek seperti `Fikri casbon rumah 1 miliar` atau `Hajid casbon motor 10jt`. Pola: `[nama] casbon [keperluan] [jumlah]`. Jika user sudah memberikan nama, keperluan, DAN jumlah dalam satu pesan, langsung ke langkah konfirmasi — JANGAN tanya ulang.
3. Jika data tidak lengkap, WAJIB tanyakan dulu sebelum memproses:
   - **Siapa?** → Nama orang yang mengajukan kasbon
   - **Untuk apa?** → Tujuan/keperluan dana
   - **Berapa?** → Jumlah nominal yang diajukan (dalam Rupiah)
4. Setelah semua data terkumpul, buat JSON indexing dan konfirmasi ke user.

## Alur Konfirmasi (Clarification Flow)

Jika user hanya bilang "cashbon" tanpa detail lengkap, balas dengan:

> Baik, saya bantu catatkan cashbon. Mohon info:
> 1. Siapa yang kasbon? (nama)
> 2. Untuk keperluan apa?
> 3. Berapa jumlahnya?

Setelah user menjawab, rangkum dan minta konfirmasi:

> Konfirmasi cashbon:
> - Nama: [nama]
> - Keperluan: [tujuan]
> - Jumlah: Rp [jumlah]
> Simpan?

Jika user konfirmasi (ya/ok/oke/sip/betul/betull/bener/udah/lanjut/simpan), baru proses ke indexing.
Jika user menolak (gajadi/batal/koreksi/nggak), tanyakan revisi atau batalkan.

> **Tip:** User sering menjawab "betull" (typo dari "betul") — ini adalah konfirmasi positif yang valid.

## Target JSON Schema (Cashbon)

```json
{
  "id": "cashbon_YYYYMMDD_NNN",
  "timestamp_archived": "YYYY-MM-DD HH:mm:ss",
  "sender": "sender_number_or_identifier",
  "category": "cashbon",
  "person_name": "Nama orang yang kasbon",
  "amount": 0,
  "currency": "IDR",
  "description": "Tujuan/keperluan dana",
  "file_absolute_path": null
}
```

## Index Update Rules

Finance memiliki index file sendiri: `/home/ubuntu/holomoc-file-finance/finance-index.json`
*(CRITICAL: Jangan pernah menggunakan tilde `~`. Selalu gunakan absolute path ini).*

Lihat `references/finance-index-schema.md` untuk detail struktur index, field, dan contoh entry lengkap.

Untuk entry cashbon, gunakan skema entry dengan `category: "cashbon"` dan format id `cashbon_YYYYMMDD_NNN`.

## Koreksi / Update Entry yang Sudah Ada

Sama seperti reimburse, user bisa minta koreksi cashbon yang sudah tersimpan. Lihat `references/reimburse-workflow.md` → "Koreksi / Update Entry yang Sudah Ada" untuk detail.
Gunakan Step 6 di SKILL.md utama dan script `scripts/update_finance.py`.
