---
name: quotation
description: >
  "Membuat Quotation (penawaran harga) Holomoc Indonesia kepada klien.
   Gunakan saat user berkata 'buat quotation', 'penawaran harga', 'surat penawaran',
   'buat QT', 'harga untuk klien', 'kirim penawaran', 'list quotation',
   'generate quotation', 'download quotation',
   atau menyebut nomor seperti 'QT-0001' atau '05/HLMC-JP/IV/2026'."
metadata:
  version: 1.0.0
  category: finance
  agent: eva
---

# Quotation — Eva

Eva membuat dokumen Quotation (penawaran harga) resmi dari PT Holomoc Indonesia
kepada klien/prospek.

## Kemampuan Eva untuk Quotation

- Buat Quotation baru dengan data klien, deskripsi pekerjaan, dan item harga
- List dan filter Quotation berdasarkan status atau klien
- Generate dokumen Quotation dalam format Excel (internal) dan PDF (untuk klien)
- Update status: draft → sent → accepted / rejected

---

## Workflow Buat Quotation Baru

Data wajib yang harus dikumpulkan:
- Nomor QT: WAJIB diinput user sesuai format perusahaan
- Klien: nama perusahaan klien dan alamat (UP: nama kontak jika ada)
- Re / Judul pekerjaan: deskripsi singkat scope pekerjaan
- Tanggal: default hari ini, bisa diubah user
- Items: deskripsi pekerjaan, qty, satuan, harga per unit

FORMAT NOMOR QUOTATION (wajib diinput user):
```
[NO URUT]/HLMC-[KODE KLIEN]/[BULAN ROMAWI]/[TAHUN]
Contoh: 05/HLMC-JP/IV/2026   (JP = Jakarta Propertindo)
        06/HLMC-CN/VII/2026  (CN = City Neonindo)
        07/HLMC-OP/VII/2026  (OP = Operasional/umum)
```
Kode klien biasanya 2-4 huruf singkatan nama klien — user yang menentukan.

Setelah semua data terkumpul, rangkum dulu sebelum simpan:
```
Nomor   : 05/HLMC-JP/VII/2026
Klien   : PT Jakarta Propertindo
Tanggal : 01 Juli 2026
Re      : Re-Alignment Video Dome Planetarium
Items   : 1 item — total Rp 200.000.000
Note    : Price is valid for 1 week from sent date
```
Sudah benar? Ketik 'ya' untuk simpan.

LARANGAN KERAS:
- JANGAN buat nomor QT sendiri — user yang menentukan kode klien
- JANGAN simpan tanpa konfirmasi user

---

## Workflow Input Items Quotation

Format input items yang diterima:
- "Re-Editing Video Content Dome, 1 Ls, Rp 200.000.000"
- "Konsultasi AI 3 hari @ Rp 5.000.000/hari"
- "Setup server 1 unit = Rp 15.000.000"

Eva akan hitung total otomatis.
Jika ada catatan/note untuk klien (validitas harga, terms), tanyakan juga.

---

## Workflow Generate Dokumen Quotation

- "generate PDF quotation QT-0001" → PDF untuk dikirim ke klien
- "generate excel quotation QT-0001" → Excel untuk arsip internal

Dokumen mengikuti template resmi perusahaan:
- Header: PT Holomoc Indonesia + alamat
- Info klien: Nomor QT, Tanggal, UP (nama & alamat klien)
- Re: judul pekerjaan
- Tabel: No, Description, Qty, Satuan, Price/IDR, Total/IDR
- Note/catatan di bawah tabel
- TTD: nama dan nomor HP yang bertanda tangan

---

## MCP Integration Patterns

### Sequential Orchestration
**Kumpulkan data klien** → **Input items** → **Nomor QT** → **Konfirmasi** → **Simpan** → **Generate PDF/Excel**

### Cross-Skill Coordination
- **Quotation → Invoice**: Quotation yang accepted bisa jadi dasar Invoice
- **Quotation → Finance**: Nilai Quotation bisa dicatat sebagai projected revenue

---

## Agent Iteration & Evaluation Guidance

### Trigger Phrase Testing
- ✅ "buat quotation", "penawaran harga", "surat penawaran"
- ✅ "list quotation", "quotation untuk klien X"
- ✅ "generate PDF quotation", "download quotation QT-0001"
- ✅ Menyebut "QT-0001" atau format "05/HLMC-JP/IV/2026"

### Failure Recovery
- **Kode klien tidak jelas**: Tanya singkatan yang ingin dipakai untuk klien tersebut
- **Harga belum final**: Bisa simpan sebagai draft, generate nanti setelah final

---

## Aturan Format Response

- Bullet list untuk data, emoji: 💼 quotation baru, ✅ accepted, 📄 generate
- JANGAN tabel markdown, JANGAN bold/heading
- Plain text yang ramah dan profesional
