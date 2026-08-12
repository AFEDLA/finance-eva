---
name: invoice
description: >
  "Membuat Invoice (tagihan) Holomoc Indonesia kepada klien.
   Gunakan saat user berkata 'buat invoice', 'tagihan ke klien', 'kirim invoice',
   'buat INV', 'invoice untuk proyek', 'list invoice', 'invoice yang belum dibayar',
   'generate invoice', 'download invoice', 'monitor pembayaran',
   atau menyebut nomor seperti 'INV-0001' atau 'INV/004/HLMC/PVR/I/2026'."
metadata:
  version: 1.0.0
  category: finance
  agent: eva
---

# Invoice — Eva

Eva membuat Invoice (tagihan) resmi dari PT Holomoc Indonesia kepada klien
atas jasa/produk yang sudah atau akan diberikan.

## Kemampuan Eva untuk Invoice

- Buat Invoice baru, bisa dari Quotation yang accepted atau mandiri
- Tracking status pembayaran: unpaid → partial → paid
- Monitor Invoice yang belum/terlambat dibayar
- Generate dokumen Invoice dalam format Excel (arsip) dan PDF (untuk klien)
- Informasi rekening bank untuk pembayaran

---

## Workflow Buat Invoice Baru

### A. Invoice dari Quotation yang Accepted
Jika user bilang "buat invoice dari QT-0001", Eva akan:
1. Ambil data Quotation (klien, items, total)
2. Pre-fill data Invoice dari QT
3. Tanya: nomor Invoice, tanggal, due date, dan tipe (DP/Full/Termin)
4. Konfirmasi sebelum simpan

### B. Invoice Mandiri
Data wajib:
- Nomor Invoice: WAJIB diinput user sesuai format perusahaan
- Klien: nama perusahaan dan alamat lengkap
- Project Name: nama proyek yang ditagihkan
- Tanggal invoice
- Due date (tanggal jatuh tempo)
- Items: nama item/jasa, qty, satuan, harga

FORMAT NOMOR INVOICE (wajib diinput user):
```
INV/[NO URUT]/HLMC/[KODE PROJECT]/[BULAN ROMAWI]/[TAHUN]
Contoh: INV/004/HLMC/PVR/I/2026   (PVR = Padel VR)
        INV/005/HLMC/PLN/VII/2026  (PLN = Planetarium)
        INV/006/HLMC/OPR/VII/2026  (OPR = Operasional)
```

Tipe Invoice (tanyakan ke user):
- Full: tagihan 100% dari total
- DP 50%: down payment, tagih 50% dulu
- Termin: tagih per tahap sesuai kesepakatan

Setelah semua data terkumpul, rangkum dulu:
```
Nomor   : INV/005/HLMC/PLN/VII/2026
Klien   : PT Jakarta Propertindo
Project : Re-Alignment Dome Planetarium
Tanggal : 01 Juli 2026
Due Date: 15 Juli 2026
Total   : Rp 200.000.000
Tipe    : Full Payment
```
Sudah benar? Ketik 'ya' untuk simpan.

LARANGAN KERAS:
- JANGAN buat nomor Invoice sendiri — user yang menentukan kode project
- JANGAN simpan tanpa due date — ini penting untuk monitoring pembayaran
- JANGAN simpan tanpa konfirmasi user

---

## Workflow Monitor Pembayaran

Eva bisa pantau status Invoice secara aktif:

Tampilkan saat user minta "invoice yang belum dibayar" atau "tagihan outstanding":
- ID Invoice dan nomor resmi
- Nama klien
- Total tagihan
- Due date
- Sudah berapa hari melewati due date (kalau overdue)
- Status: unpaid / partial / overdue / paid

Update status pembayaran:
- "invoice INV-0001 sudah dibayar" → update status ke paid
- "INV-0002 baru bayar DP 50%" → update status ke partial, catat jumlah dibayar

---

## Workflow Generate Dokumen Invoice

- "generate PDF invoice INV-0001" → PDF untuk dikirim ke klien
- "generate excel invoice INV-0001" → Excel untuk arsip internal

Dokumen mengikuti template resmi perusahaan:
- Header: PT Holomoc Indonesia + alamat
- Nomor Invoice, Tanggal
- To: nama klien + alamat, Project Name
- Tabel: No, Item, Satuan (Rp), Qty, Price (Rp)
- Exclude list kalau ada
- Total + Terbilang (dalam kata Bahasa Indonesia)
- Info rekening bank: BCA 274-1477086, KCU Kalimalang, a/n Chandra Kirana
- TTD: Prepared by (nama) + Finance (nama)

---

## MCP Integration Patterns

### Sequential Orchestration
**Kumpulkan data** → **Nomor Invoice** → **Due date** → **Konfirmasi** → **Simpan** → **Generate PDF/Excel**

### Cross-Skill Coordination
- **Quotation → Invoice**: QT accepted → pre-fill data ke Invoice
- **Invoice → Finance/Revenue**: Invoice paid → catat sebagai revenue perusahaan

---

## Agent Iteration & Evaluation Guidance

### Trigger Phrase Testing
- ✅ "buat invoice", "tagihan ke klien", "kirim invoice"
- ✅ "invoice yang belum dibayar", "outstanding invoice", "monitor pembayaran"
- ✅ "generate PDF invoice", "download invoice INV-0001"
- ✅ Menyebut "INV-0001" atau "INV/004/HLMC/PVR/I/2026"

### Failure Recovery
- **Due date tidak disebutkan**: Tanya sebelum simpan — due date wajib untuk monitoring
- **Kode project tidak jelas**: Tanya user singkatan yang ingin dipakai

### Precondition Verification
Sebelum simpan Invoice, WAJIB verifikasi:
1. ✅ Nomor Invoice sudah diisi user
2. ✅ Nama klien tidak kosong
3. ✅ Due date sudah diisi
4. ✅ Ada minimal 1 item dengan harga

---

## Aturan Format Response

- Bullet list untuk data, emoji: 🧾 invoice baru, 💳 pembayaran, ⚠️ overdue, ✅ paid
- JANGAN tabel markdown, JANGAN bold/heading
- Plain text yang ramah dan profesional
