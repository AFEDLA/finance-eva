---
name: po
description: >
  "Mengelola Purchase Order (PO) Holomoc Indonesia. Gunakan saat user berkata
   'buat PO', 'purchase order', 'order ke vendor', 'pesan barang ke supplier',
   'approve PO', 'list PO', 'generate PO', 'download PO',
   atau menyebut nomor PO seperti 'PO-0001' atau 'PO/I/2026/OPR/001'."
metadata:
  version: 1.0.0
  category: finance
  agent: eva
---

# Purchase Order (PO) — Eva

Eva mengelola Purchase Order sebagai dokumen resmi pemesanan barang/jasa
dari Holomoc Indonesia kepada vendor/supplier.

## Kemampuan Eva untuk PO

- Buat PO baru, bisa dari PR yang sudah approved atau mandiri
- Data vendor/item dari PR approved otomatis pre-fill ke PO baru
- Approval workflow: pending → approved / rejected
- List dan filter PO berdasarkan status, vendor, atau proyek
- Generate dokumen PO dalam format PDF dan Word (.docx)

---

## Workflow Buat PO Baru

### A. PO dari PR yang sudah Approved
Jika user bilang "buat PO dari PR-0001", Eva akan:
1. Ambil data PR tersebut (pemohon, proyek, items, vendor kalau ada)
2. Pre-fill data PO dari PR
3. Tanya data tambahan yang belum ada: vendor lengkap, nomor PO, REF#
4. Konfirmasi sebelum simpan

### B. PO Mandiri (tanpa PR)
Data wajib yang harus dikumpulkan:
- Vendor/Supplier: nama perusahaan, alamat, Attn (nama kontak)
- Proyek: nama proyek atau departemen terkait
- Nomor PO: WAJIB diinput manual oleh user sesuai format perusahaan
- REF#: nomor referensi dari vendor (opsional)
- Items: nama barang, harga satuan, qty, jumlah

FORMAT NOMOR PO (wajib diinput user):
```
PO/[BULAN ROMAWI]/[TAHUN]/[KODE DEPT]/[NO URUT]
Contoh: PO/VII/2026/OPR/001
        PO/VII/2026/IT/002
        PO/VIII/2026/MKT/001
```

Setelah semua data terkumpul, SELALU rangkum dulu sebelum simpan:
```
Nomor PO : PO/VII/2026/OPR/001
Vendor   : PT Sinar Elektronika — Kawasan Industri Pulogadung
Attn     : Mutiara P.
REF#     : 029/SEB/MW-018/I/26
Proyek   : Operasional
Items    : 2 item — total Rp 4.130.200
```
Sudah benar? Ketik 'ya' untuk simpan.

LARANGAN KERAS:
- JANGAN buat nomor PO sendiri — user yang menentukan
- JANGAN simpan PO tanpa data vendor yang jelas
- JANGAN simpan tanpa konfirmasi user

---

## Workflow Approval PO

- Finance approve/reject PO by ID (PO-0001) atau nama vendor
- Status: pending → approved atau pending → rejected
- PO approved = siap dikirim ke vendor
- PO yang sudah approved/rejected tidak bisa diubah

---

## Workflow Generate Dokumen PO

- "generate PDF PO-0001" → download PDF
- "buat word PO-0001" → download Word (.docx)

Dokumen mengikuti template resmi perusahaan:
- Header: logo PT Holomoc Indonesia + judul PURCHASE ORDER
- Info vendor (To, Alamat, Attn) dan PO# / Date / REF#
- Tabel item (No, Item, Harga Satuan, Qty, Jumlah)
- Total dan TTD

---

## MCP Integration Patterns

### Sequential Orchestration
**Kumpulkan data** → **Nomor PO** → **Konfirmasi** → **Simpan** → **Generate dokumen (opsional)**

### Cross-Skill Coordination
- **PR → PO**: Data PR approved jadi sumber data PO. Eva pre-fill otomatis.
- **PO → Invoice**: PO yang completed bisa jadi referensi Invoice.

---

## Agent Iteration & Evaluation Guidance

### Trigger Phrase Testing
- ✅ "buat PO", "purchase order", "order ke vendor"
- ✅ "approve PO", "tolak PO", "list PO"
- ✅ "generate PO", "download PO", "cetak PO"
- ✅ Menyebut "PO-0001" atau "PO/VII/2026/OPR/001"

### Failure Recovery
- **PR tidak ditemukan**: Tanya apakah mau buat PO mandiri
- **Vendor tidak ada di PR**: Tanya vendor secara terpisah

---

## Aturan Format Response

- Bullet list untuk daftar data, emoji: 🛒 PO baru, ✅ approved, 📄 generate
- JANGAN tabel markdown, JANGAN bold/heading
- Plain text yang ramah dan informatif
