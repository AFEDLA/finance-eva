---
name: skill-conventions
description: "Standar dan konvensi pembuatan skill di Holomoc Indonesia. Mencakup aturan frontmatter, struktur direktori, instruksi langkah-demi-langkah, MCP Integration Patterns, dan Agent Iteration & Evaluation Guidance. Gunakan saat akan membuat skill baru, mengupdate skill yang sudah ada, atau mengecek kepatuhan skill terhadap standar Holomoc."
metadata:
  version: 1.0.0
  category: holomoc
---

# Holomoc Skill Conventions

Panduan ini mendefinisikan standar pembuatan dan pemeliharaan skill di Holomoc. Setiap skill WAJIB mengikuti konvensi berikut.

---

## 1. Struktur Direktori & File

```
skills/holomoc/<skill-name>/
  ├── SKILL.md              # WAJIB — file utama (case-sensitive)
  ├── references/            # Opsional — dokumentasi detail
  │   ├── <topic>.md
  │   └── ...
  ├── scripts/               # Opsional — kode eksekusi (Python/Bash)
  │   └── <name>.py
  └── assets/                # Opsional — template/aset desain
```

### Aturan Ketat
- ✅ Nama folder: `kebab-case` (tanpa spasi, huruf kapital, garis bawah)
- ✅ File utama: `SKILL.md` (case-sensitive, huruf besar di S dan M)
- ❌ DILARANG: `README.md` di dalam folder skill
- ❌ DILARANG: nama skill mengandung kata "claude" atau "anthropic"
- ✅ Absolute paths: jangan gunakan `~` — gunakan `/home/ubuntu/...`
- ✅ Folder referensi: gunakan `references/` untuk dokumentasi panjang agar SKILL.md tetap ringan

---

## 2. Konfigurasi YAML Frontmatter

Frontmatter WAJIB di bagian PALING ATAS file `SKILL.md`:

```yaml
---
name: <kebab-case-nama>        # WAJIB — harus sama dengan nama folder
description: >                  # WAJIB — maks 1024 karakter
  "Apa fungsi skill dan kapan digunakan.
   Sertakan trigger phrases spesifik:
   'katakan ini', 'bilang itu', dll."
metadata:
  version: X.Y.Z               # WAJIB — gunakan semver
  category: <kategori>          # WAJIB — contoh: document-automation, finance
---
```

### Aturan
- `name`: kebab-case, identik dengan nama folder. ❌ Jangan pakai "claude" atau "anthropic"
- `description`: WAJIB mencakup fungsi skill DAN trigger phrases. ❌ DILARANG tag XML `<` atau `>` di frontmatter
- Batas panjang description: **1024 karakter maksimal**

---

## 3. Isi SKILL.md — Desain Instruksi Utama

### Format
- Instruksi dalam Markdown di bawah frontmatter
- WAJIB format **langkah-demi-langkah** (Step 1, Step 2, Step 3, ...)
- Spesifik dan berorientasi pada tindakan

### Jika dokumentasi panjang
- Pindahkan detail ke `references/<topic>.md`
- Cukup tautkan satu baris di SKILL.md: "Lihat detail di `references/<topic>.md`"

### Komponen yang WAJIB ada di setiap skill

#### a. MCP Integration Patterns
```markdown
## MCP Integration Patterns

### Sequential Orchestration
Workflow <Nama> memiliki N langkah berurutan yang WAJIB diikuti:
**Step 1** → **Step 2** → **Step 3**.
Jika salah satu step gagal, jangan lanjut ke step berikutnya.

### Multi-MCP (Cross-Skill Coordination)
Kolaborasi dengan skill lain:
- **skill-a → skill-b**: Kapan harus arahkan ke skill lain
- **skill-a → skill-c**: Kapan harus panggil script dari skill lain

### Iterative Refinement
- Jika <kondisi gagal>: lakukan <tindakan>.
- Jika <kondisi lain>: lakukan <tindakan lain>.
```

#### b. Agent Iteration & Evaluation Guidance
```markdown
## Agent Iteration & Evaluation Guidance

### Trigger Phrase Testing
Skill ini akan terpanggil saat user menggunakan kata/frasa:
- ✅ "trigger phrase 1"
- ✅ "trigger phrase 2"

Jika skill terlalu sering aktif di luar konteks (overtriggering), persempit deskripsi.

### Failure Recovery
- **<Error A>**: <Solusi>
- **<Error B>**: <Solusi>

### Precondition Verification
Sebelum menjalankan workflow, WAJIB verifikasi:
1. ✅ <Prasyarat 1>
2. ✅ <Prasyarat 2>
```

#### c. Troubleshooting Section
```markdown
## Troubleshooting
**Error:** <deskripsi error>
**Cause:** <penyebab>
**Solution:** <solusi>
```

#### d. Response Format Rules (khusus chat/WhatsApp)
```markdown
# RESPONSE FORMAT RULES (WAJIB)
Setiap kali merespon user di chat, GUNAKAN FORMAT LIST (bullet/numbered).
- ✅ Tampilkan data sebagai numbered list atau bullet list
- ✅ Gunakan emoji untuk memperjelas (📋, 👤, 💰, dll)
- ❌ JANGAN gunakan format tabel markdown
- ❌ JANGAN buat tabel visual
```

---

## 4. Integrasi Model Context Protocol (MCP)

### Sequential Pattern
- Definisikan urutan langkah, dependensi antar tahap
- Instruksi rollback jika gagal

### Multi-MCP Pattern
- Koordinasikan alur kerja lintas layanan
- Pisahkan tindakan ke fase yang jelas
- Validasi transfer data antar MCP

### Iterative Pattern
- Bangun loop penyempurnaan
- Cek ulang via skrip evaluasi
- Iterasi sampai memenuhi standar kualitas

---

## 5. Script Eksternal untuk Validasi

Untuk langkah kritis, instruksikan EKSEKUSI script eksternal — jangan hanya mengandalkan pemahaman bahasa model.

Contoh dari skill yang sudah ada:
- `scripts/add_arsip.py` — menambah entry index arsip
- `scripts/add_finance.py` — menambah entry cashbon/reimburse
- `scripts/add_mom.py` — validasi MoM, simpan file, update index
- `scripts/search_arsip.py` — pencarian di index arsip
- `scripts/generate_excel.py` — generate Excel
- `scripts/generate_png.py` — generate PNG image

---

## 6. Contoh SKILL.md Lengkap

Lihat skill yang sudah ada untuk contoh implementasi:
- `arsip-document` v3.0.0 — contoh skill arsip dengan MCP + Iteration
- `finance` v3.0.0 — contoh skill keuangan dengan auth check + MCP
- `holomoc-email` v2.0.0 — contoh skill komunikasi dengan numbered steps

---

## Referensi Terkait

File di `references/` masing-masing skill berisi detail spesifik:
- `finance/references/auth-rules.md` — aturan otorisasi
- `finance/references/cashbon-workflow.md` — workflow kasbon
- `finance/references/reimburse-workflow.md` — workflow reimburse
- `arsip-document/references/json-schema.md` — schema index JSON
- `mom/references/mom-template.md` — template MoM
- `mom/references/indexing-schema.md` — schema indexing MoM
- `holomoc-email/references/configuration.md` — konfigurasi email
- `holomoc-email/references/message-composition.md` — format MML
- `holomoc-email/references/gmail-locale-folders.md` — folder Gmail
