"""
Storage Manager — simpan data ke folder lokal Windows
Semua data disimpan di: Documents/holomoc-file/
"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(os.getenv("STORAGE_DIR", str(Path.home() / "Documents" / "holomoc-file")))

def get_index_path(category: str) -> Path:
    index_dir = BASE_DIR / category
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir / "index.json"

def load_index(category: str) -> list:
    path = get_index_path(category)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            return []
    return []

def save_index(category: str, data: list):
    path = get_index_path(category)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── ARSIP ────────────────────────────────────────────────────────────────────

def add_arsip(judul: str, kategori: str, deskripsi: str = "", file_name: str = "") -> dict:
    index = load_index("arsip")
    entry = {
        "id": f"ARSIP-{len(index)+1:04d}",
        "judul": judul,
        "kategori": kategori,
        "deskripsi": deskripsi,
        "file": file_name,
        "tanggal": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat()
    }
    index.append(entry)
    save_index("arsip", index)
    return entry

def search_arsip(keyword: str = "", kategori: str = "", tanggal_dari: str = "", tanggal_sampai: str = "") -> list:
    index = load_index("arsip")
    results = []
    for item in index:
        # Match keyword — cek judul, deskripsi, dan nama file
        match_keyword = not keyword or (
            keyword.lower() in item.get("judul","").lower() or
            keyword.lower() in item.get("deskripsi","").lower() or
            keyword.lower() in item.get("file","").lower()
        )
        # Match kategori
        match_kategori = not kategori or kategori.lower() in item.get("kategori","").lower()
        # Match tanggal
        tgl = item.get("tanggal","")
        match_dari = not tanggal_dari or tgl >= tanggal_dari
        match_sampai = not tanggal_sampai or tgl <= tanggal_sampai

        if match_keyword and match_kategori and match_dari and match_sampai:
            results.append(item)
    return results

def update_arsip(arsip_id: str, updates: dict) -> dict | None:
    index = load_index("arsip")
    for i, item in enumerate(index):
        if item.get("id") == arsip_id:
            index[i].update(updates)
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("arsip", index)
            return index[i]
    return None

def delete_arsip(arsip_id: str) -> bool:
    index = load_index("arsip")
    new_index = [x for x in index if x.get("id") != arsip_id]
    if len(new_index) < len(index):
        save_index("arsip", new_index)
        return True
    return False

# ─── FINANCE ──────────────────────────────────────────────────────────────────

def _next_finance_id(jenis: str) -> str:
    """Generate ID baru: RMB-xxxx untuk reimburse, CAS-xxxx untuk kasbon.
    Data lama FIN-xxxx tetap valid (backward compatible)."""
    import re as _re
    index = load_index("finance")
    prefix = "RMB" if jenis.lower() == "reimburse" else "CAS"
    nums = []
    for x in index:
        m = _re.match(rf'{prefix}-(\d+)', x.get("id", ""))
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"{prefix}-{next_num:04d}"

def add_finance(jenis: str, nama: str, jumlah: int, keperluan: str, file_name: str = "", project: str = "Operasional") -> dict:
    index = load_index("finance")
    entry = {
        "id": _next_finance_id(jenis),
        "jenis": jenis,
        "nama": nama,
        "jumlah": jumlah,
        "keperluan": keperluan,
        "project": project or "Operasional",
        "file": file_name,
        "status": "pending",
        "tanggal": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat()
    }
    index.append(entry)
    save_index("finance", index)
    return entry

def get_finance(bulan: int = None, tahun: int = None) -> list:
    index = load_index("finance")
    if not bulan and not tahun:
        return index
    results = []
    for item in index:
        try:
            tgl = datetime.fromisoformat(item.get("created_at", datetime.now().isoformat()))
            if (not bulan or tgl.month == bulan) and (not tahun or tgl.year == tahun):
                results.append(item)
        except:
            results.append(item)
    return results

def update_finance(fin_id: str, updates: dict) -> dict | None:
    index = load_index("finance")
    for i, item in enumerate(index):
        if item.get("id") == fin_id:
            index[i].update(updates)
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("finance", index)
            return index[i]
    return None

def delete_finance(fin_id: str) -> bool:
    index = load_index("finance")
    new_index = [x for x in index if x.get("id") != fin_id]
    if len(new_index) < len(index):
        save_index("finance", new_index)
        return True
    return False

# ─── FINANCE CONFIG (Saldo Awal Kas) ──────────────────────────────────────────

def get_finance_config_path() -> Path:
    config_dir = BASE_DIR / "finance"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"

def get_finance_config() -> dict:
    path = get_finance_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except:
            return {"saldo_awal": 0}
    return {"saldo_awal": 0}

def set_saldo_awal(jumlah: int) -> dict:
    config = get_finance_config()
    config["saldo_awal"] = jumlah
    config["updated_at"] = datetime.now().isoformat()
    path = get_finance_config_path()
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config

# ─── MOM ──────────────────────────────────────────────────────────────────────

def add_mom(judul: str, peserta: list, topik: str, keputusan: list, action_items: list) -> dict:
    index = load_index("mom")
    entry = {
        "id": f"MOM-{len(index)+1:04d}",
        "judul": judul,
        "peserta": peserta,
        "topik": topik,
        "keputusan": keputusan,
        "action_items": action_items,
        "tanggal": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat()
    }
    index.append(entry)
    save_index("mom", index)
    return entry

def get_mom_list() -> list:
    return load_index("mom")

def update_mom(mom_id: str, updates: dict) -> dict | None:
    index = load_index("mom")
    for i, item in enumerate(index):
        if item.get("id") == mom_id:
            index[i].update(updates)
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("mom", index)
            return index[i]
    return None

def delete_mom(mom_id: str) -> bool:
    index = load_index("mom")
    new_index = [x for x in index if x.get("id") != mom_id]
    if len(new_index) < len(index):
        save_index("mom", new_index)
        return True
    return False

# ─── JADWAL ───────────────────────────────────────────────────────────────────

def add_jadwal(judul: str, tanggal: str, waktu: str, peserta: list, lokasi: str = "") -> dict:
    index = load_index("jadwal")
    entry = {
        "id": f"RAPAT-{len(index)+1:04d}",
        "judul": judul,
        "tanggal": tanggal,
        "waktu": waktu,
        "peserta": peserta,
        "lokasi": lokasi,
        "created_at": datetime.now().isoformat()
    }
    index.append(entry)
    save_index("jadwal", index)
    return entry

def get_jadwal_hari_ini() -> list:
    index = load_index("jadwal")
    today = datetime.now().strftime("%Y-%m-%d")
    return [x for x in index if x.get("tanggal") == today]

def get_all_jadwal() -> list:
    return load_index("jadwal")

def update_jadwal(jadwal_id: str, updates: dict) -> dict | None:
    index = load_index("jadwal")
    for i, item in enumerate(index):
        if item.get("id") == jadwal_id:
            index[i].update(updates)
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("jadwal", index)
            return index[i]
    return None

def delete_jadwal(jadwal_id: str) -> bool:
    index = load_index("jadwal")
    new_index = [x for x in index if x.get("id") != jadwal_id]
    if len(new_index) < len(index):
        save_index("jadwal", new_index)
        return True
    return False

# ─── FILE STORAGE ─────────────────────────────────────────────────────────────

def save_file(file_bytes: bytes, file_name: str, category: str = "arsip") -> str:
    """Simpan file ke storage dan return path relatif."""
    today = datetime.now()
    file_dir = BASE_DIR / category / "files" / str(today.year) / f"{today.month:02d}"
    file_dir.mkdir(parents=True, exist_ok=True)
    file_path = file_dir / file_name
    # Hindari overwrite
    counter = 1
    while file_path.exists():
        stem = Path(file_name).stem
        suffix = Path(file_name).suffix
        file_path = file_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    file_path.write_bytes(file_bytes)
    return str(file_path)

def get_file_path(file_name: str, category: str = "arsip") -> Path | None:
    """Cari file di storage dengan beberapa strategi fallback."""
    search_dir = BASE_DIR / category

    # Strategi 1: exact match via rglob
    for f in search_dir.rglob(file_name):
        if f.is_file():
            return f

    # Strategi 2: case-insensitive match (Windows kadang case-sensitive via rglob)
    file_name_lower = file_name.lower()
    for f in search_dir.rglob("*"):
        if f.is_file() and f.name.lower() == file_name_lower:
            return f

    # Strategi 3: stem match — cari file dengan nama dasar sama, abaikan suffix counter
    # mis. "doc.pdf" cocok dengan "doc_1.pdf" kalau "doc.pdf" tidak ada
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix
    for f in search_dir.rglob(f"*{suffix}"):
        if f.is_file() and (f.stem == stem or f.stem.startswith(stem + "_")):
            return f

    return None

# ─── DELETE ALL ──────────────────────────────────────────────────────────────

def delete_all_arsip() -> int:
    index = load_index("arsip")
    count = len(index)
    save_index("arsip", [])
    return count

def delete_all_finance() -> int:
    index = load_index("finance")
    count = len(index)
    save_index("finance", [])
    return count

def delete_all_mom() -> int:
    index = load_index("mom")
    count = len(index)
    save_index("mom", [])
    return count

def delete_all_jadwal() -> int:
    index = load_index("jadwal")
    count = len(index)
    save_index("jadwal", [])
    return count

def delete_all_pr() -> int:
    index = load_index("pr")
    count = len(index)
    save_index("pr", [])
    return count

def delete_all_data() -> dict:
    return {
        "arsip": delete_all_arsip(),
        "finance": delete_all_finance(),
        "mom": delete_all_mom(),
        "jadwal": delete_all_jadwal(),
        "pr": delete_all_pr(),
    }

# ─── PURCHASE REQUEST ────────────────────────────────────────────────────────

def add_pr(
    nomor: str,
    pemohon: str,
    proyek: str,
    keperluan: str,
    items: list,
    tanggal_permohonan: str = "",
    vendor: str = "",
    catatan: str = "",
) -> dict:
    index = load_index("pr")
    total = sum(int(x.get("jumlah", 0)) for x in items)
    entry = {
        "id": f"PR-{len(index)+1:04d}",
        "nomor": nomor,
        "pemohon": pemohon,
        "proyek": proyek,
        "keperluan": keperluan,
        "items": items,
        "total": total,
        "vendor": vendor,
        "catatan": catatan,
        "status": "pending",
        "approved_by": "",
        "tanggal_permohonan": tanggal_permohonan or datetime.now().strftime("%d %B %Y"),
        "tanggal": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat()
    }
    index.append(entry)
    save_index("pr", index)
    return entry

def get_pr(status: str = "", pemohon: str = "", proyek: str = "") -> list:
    index = load_index("pr")
    results = []
    for item in index:
        match_status  = not status  or status.lower()  == item.get("status", "").lower()
        match_pemohon = not pemohon or pemohon.lower() in item.get("pemohon", "").lower()
        match_proyek  = not proyek  or proyek.lower()  in item.get("proyek", "").lower()
        if match_status and match_pemohon and match_proyek:
            results.append(item)
    return results

def get_pr_by_id(pr_id: str) -> dict | None:
    index = load_index("pr")
    return next((x for x in index if x.get("id") == pr_id or x.get("nomor") == pr_id), None)

def update_pr(pr_id: str, updates: dict) -> dict | None:
    index = load_index("pr")
    for i, item in enumerate(index):
        if item.get("id") == pr_id:
            index[i].update(updates)
            # Selalu hitung ulang total dari items agar sinkron dengan UI
            current_items = index[i].get("items", [])
            index[i]["total"] = sum(int(x.get("jumlah", 0)) for x in current_items)
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("pr", index)
            return index[i]
    return None

def migrate_pr_totals() -> int:
    """Hitung ulang field total untuk semua PR yang sudah ada di storage.
    Dipanggil sekali saat startup untuk fix data lama yang tidak punya field total.
    Return jumlah PR yang diupdate."""
    index = load_index("pr")
    updated = 0
    for i, item in enumerate(index):
        items = item.get("items", [])
        correct_total = sum(int(x.get("jumlah", 0)) for x in items)
        if item.get("total") != correct_total:
            index[i]["total"] = correct_total
            updated += 1
    if updated > 0:
        save_index("pr", index)
    return updated

def delete_pr(pr_id: str) -> bool:
    index = load_index("pr")
    new_index = [x for x in index if x.get("id") != pr_id]
    if len(new_index) < len(index):
        save_index("pr", new_index)
        return True
    return False


# ─── PURCHASE ORDER ───────────────────────────────────────────────────────────

def _next_po_id() -> str:
    index = load_index("po")
    if not index:
        return "PO-0001"
    nums = []
    for x in index:
        import re as _re
        m = _re.match(r'PO-(\d+)', x.get("id", ""))
        if m:
            nums.append(int(m.group(1)))
    return f"PO-{(max(nums) + 1):04d}" if nums else "PO-0001"

def add_po(
    nomor: str,
    vendor_nama: str,
    vendor_alamat: str = "",
    vendor_attn: str = "",
    proyek: str = "",
    ref: str = "",
    items: list | None = None,
    pr_id: str = "",
    catatan: str = "",
) -> dict:
    """Simpan PO baru ke storage. Return dict PO yang disimpan."""
    index  = load_index("po")
    po_id  = _next_po_id()
    total  = sum(int(x.get("jumlah", 0)) for x in (items or []))
    now    = datetime.now()
    record = {
        "id":            po_id,
        "nomor":         nomor,
        "vendor_nama":   vendor_nama,
        "vendor_alamat": vendor_alamat,
        "vendor_attn":   vendor_attn,
        "proyek":        proyek,
        "ref":           ref,
        "items":         items or [],
        "total":         total,
        "status":        "pending",
        "pr_id":         pr_id,
        "catatan":       catatan,
        "tanggal":       now.strftime("%d %B %Y"),
        "created_at":    now.isoformat(),
        "updated_at":    now.isoformat(),
    }
    index.append(record)
    save_index("po", index)
    return record

def get_po(status: str = "") -> list:
    """Ambil semua PO, opsional filter by status."""
    index = load_index("po")
    if status:
        index = [x for x in index if x.get("status", "").lower() == status.lower()]
    return index

def get_po_by_id(po_id: str) -> dict | None:
    """Cari PO by ID (PO-0001) atau nomor dokumen (PO/VII/2026/OPR/001)."""
    index = load_index("po")
    po_id_up = po_id.upper()
    # Cari by ID dulu
    found = next((x for x in index if x.get("id", "").upper() == po_id_up), None)
    if found:
        return found
    # Fallback: cari by nomor dokumen
    return next((x for x in index if x.get("nomor", "").upper() == po_id_up), None)

def update_po(po_id: str, updates: dict) -> dict | None:
    """Update field PO. Recalculate total kalau items diupdate."""
    index = load_index("po")
    for i, item in enumerate(index):
        if item.get("id") == po_id:
            index[i].update(updates)
            if "items" in updates:
                index[i]["total"] = sum(int(x.get("jumlah", 0)) for x in updates["items"])
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("po", index)
            return index[i]
    return None

def delete_po(po_id: str) -> bool:
    index = load_index("po")
    new_index = [x for x in index if x.get("id") != po_id]
    if len(new_index) < len(index):
        save_index("po", new_index)
        return True
    return False

# ─── QUOTATION ────────────────────────────────────────────────────────────────

def _next_qt_id() -> str:
    import re as _re
    index = load_index("qt")
    nums = []
    for x in (index or []):
        m = _re.match(r'QT-(\d+)', str(x.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"QT-{next_num:04d}"

def add_qt(data: dict) -> dict:
    """Simpan Quotation baru ke storage. Return dict QT yang disimpan (dengan id)."""
    index  = load_index("qt")
    qt_id  = _next_qt_id()
    now    = datetime.now()
    items  = data.get("items", [])
    total  = sum(int(x.get("jumlah", 0)) for x in items)
    record = {
        "id":           qt_id,
        "nomor":        data.get("nomor", ""),
        "klien_nama":   data.get("klien_nama", ""),
        "klien_alamat": data.get("klien_alamat", ""),
        "klien_up":     data.get("klien_up", ""),
        "tanggal":      data.get("tanggal", now.strftime("%d %B %Y")),
        "re":           data.get("re", ""),
        "items":        items,
        "total":        total,
        "note":         data.get("note", ""),
        "ttd_nama":     data.get("ttd_nama", ""),
        "ttd_hp":       data.get("ttd_hp", ""),
        "status":       "draft",
        "quotation_id": None,
        "created_at":   now.isoformat(),
        "updated_at":   now.isoformat(),
    }
    index.append(record)
    save_index("qt", index)
    return record

def get_qt(status: str = "") -> list:
    """Ambil semua Quotation, opsional filter by status."""
    index = load_index("qt")
    if status:
        index = [x for x in index if x.get("status", "").lower() == status.lower()]
    return index

def get_qt_by_id(qt_id: str) -> dict | None:
    """Cari QT by ID (QT-0001) atau nomor dokumen (05/HLMC-JP/VII/2026)."""
    index    = load_index("qt")
    qt_id_up = qt_id.upper()
    found    = next((x for x in index if x.get("id", "").upper() == qt_id_up), None)
    if found:
        return found
    return next((x for x in index if x.get("nomor", "").upper() == qt_id_up), None)

def update_qt(qt_id: str, updates: dict) -> dict | None:
    """Update field QT. Recalculate total kalau items diupdate."""
    index = load_index("qt")
    for i, item in enumerate(index):
        if item.get("id") == qt_id:
            index[i].update(updates)
            if "items" in updates:
                index[i]["total"] = sum(int(x.get("jumlah", 0)) for x in updates["items"])
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("qt", index)
            return index[i]
    return None

def delete_qt(qt_id: str) -> bool:
    index     = load_index("qt")
    new_index = [x for x in index if x.get("id") != qt_id]
    if len(new_index) < len(index):
        save_index("qt", new_index)
        return True
    return False

def delete_all_qt() -> int:
    index = load_index("qt")
    count = len(index)
    save_index("qt", [])
    return count

# ─── INVOICE ─────────────────────────────────────────────────────────────────

def _next_inv_id() -> str:
    import re as _re
    index = load_index("inv")
    nums = []
    for x in (index or []):
        m = _re.match(r'INV-(\d+)', str(x.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"INV-{next_num:04d}"

def add_inv(data: dict) -> dict:
    """Simpan Invoice baru ke storage. Return dict INV yang disimpan (dengan id)."""
    index  = load_index("inv")
    inv_id = _next_inv_id()
    now    = datetime.now()
    items  = data.get("items", [])
    total  = sum(int(x.get("total", x.get("jumlah", 0))) for x in items)
    record = {
        "id":             inv_id,
        "nomor":          data.get("nomor", ""),
        "klien_nama":     data.get("klien_nama", ""),
        "klien_alamat":   data.get("klien_alamat", ""),
        "tanggal":        data.get("tanggal", now.strftime("%d %B %Y")),
        "project_name":   data.get("project_name", ""),
        "items":          items,
        "total":          total,
        "ttd_nama":       data.get("ttd_nama", ""),
        "ttd_jabatan":    data.get("ttd_jabatan", "Finance"),
        "bank_nama":      data.get("bank_nama", ""),
        "bank_rekening":  data.get("bank_rekening", ""),
        "bank_cabang":    data.get("bank_cabang", ""),
        "bank_atas_nama": data.get("bank_atas_nama", ""),
        "quotation_id":   data.get("quotation_id"),
        "status":         "draft",
        "issued_at":      None,
        "paid_at":        None,
        "created_at":     now.isoformat(),
        "updated_at":     now.isoformat(),
    }
    index.append(record)
    save_index("inv", index)
    return record

def get_inv(status: str = "") -> list:
    """Ambil semua Invoice, opsional filter by status."""
    index = load_index("inv")
    if status:
        index = [x for x in index if x.get("status", "").lower() == status.lower()]
    return index

def get_inv_by_id(inv_id: str) -> dict | None:
    """Cari Invoice by ID (INV-0001) atau nomor dokumen."""
    index     = load_index("inv")
    inv_id_up = inv_id.upper()
    found     = next((x for x in index if x.get("id", "").upper() == inv_id_up), None)
    if found:
        return found
    return next((x for x in index if x.get("nomor", "").upper() == inv_id_up), None)

def update_inv(inv_id: str, updates: dict) -> dict | None:
    """Update field Invoice. Recalculate total kalau items diupdate."""
    index = load_index("inv")
    for i, item in enumerate(index):
        if item.get("id") == inv_id:
            index[i].update(updates)
            if "items" in updates:
                index[i]["total"] = sum(
                    int(x.get("total", x.get("jumlah", 0))) for x in updates["items"]
                )
            index[i]["updated_at"] = datetime.now().isoformat()
            save_index("inv", index)
            return index[i]
    return None

def delete_inv(inv_id: str) -> bool:
    index     = load_index("inv")
    new_index = [x for x in index if x.get("id") != inv_id]
    if len(new_index) < len(index):
        save_index("inv", new_index)
        # Hapus juga entry finance yang terhubung (jika ada)
        remove_invoice_from_finance(inv_id)
        return True
    return False

def add_invoice_to_finance(inv: dict) -> dict | None:
    """
    Masukkan Invoice yang sudah paid ke laporan keuangan (finance storage).
    Dipanggil saat mark_paid.
    Return entry finance yang dibuat, atau None kalau sudah ada.
    """
    inv_id = inv.get("id", "")
    # Cek duplikat — jangan masukkan dua kali
    existing = load_index("finance")
    if any(x.get("inv_ref") == inv_id for x in existing):
        return None

    # Hitung total dari items
    items = inv.get("items", [])
    total = sum(int(x.get("jumlah", x.get("total", 0))) for x in items)
    if not total:
        total = inv.get("total", 0)

    paid_at = inv.get("paid_at", datetime.now().isoformat())
    tanggal = paid_at[:10] if paid_at else datetime.now().strftime("%Y-%m-%d")

    entry = {
        "id":         f"INV-REF-{inv_id}",
        "jenis":      "invoice",
        "inv_ref":    inv_id,
        "nama":       inv.get("klien_nama", "-"),
        "jumlah":     int(total),
        "keperluan":  f"Invoice {inv.get('nomor', inv_id)} — {inv.get('project_name', inv.get('re', '-'))}",
        "project":    inv.get("project_name", "Invoice"),
        "file":       "",
        "status":     "approved",
        "tanggal":    tanggal,
        "created_at": paid_at or datetime.now().isoformat(),
        "approved_by": "Invoice Paid",
    }
    existing.append(entry)
    save_index("finance", existing)
    return entry

def remove_invoice_from_finance(inv_id: str) -> bool:
    """
    Hapus entry finance yang berasal dari Invoice (saat unpaid atau delete).
    Return True kalau ada yang dihapus.
    """
    finance = load_index("finance")
    new_finance = [x for x in finance if x.get("inv_ref") != inv_id]
    if len(new_finance) < len(finance):
        save_index("finance", new_finance)
        return True
    return False



# ─── SUMMARY ──────────────────────────────────────────────────────────────────

def get_storage_summary() -> dict:
    return {
        "arsip":   len(load_index("arsip")),
        "finance": len(load_index("finance")),
        "mom":     len(load_index("mom")),
        "jadwal":  len(load_index("jadwal")),
        "pr":      len(load_index("pr")),
        "po":      len(load_index("po")),
        "qt":      len(load_index("qt")),
        "inv":     len(load_index("inv")),
        "storage_path": str(BASE_DIR)
    }


# ─── BUDGET & EXPENSE ─────────────────────────────────────────────────────────

DEFAULT_OPS_CATEGORIES = [
    {"code": "ATK",           "name": "ATK & Perlengkapan Kantor"},
    {"code": "TRANSPORT",     "name": "Transport & Perjalanan"},
    {"code": "AKOMODASI",     "name": "Akomodasi"},
    {"code": "UTILITAS",      "name": "Utilitas (Listrik/Air/Internet)"},
    {"code": "ENTERTAINMENT", "name": "Entertainment & Representasi"},
    {"code": "MAINTENANCE",   "name": "Maintenance & Pemeliharaan"},
]

def _next_bud_id() -> str:
    import re as _re
    index = load_index("budget")
    nums = []
    for x in (index or []):
        m = _re.match(r'BUD-(\d+)', str(x.get("budget_id", "")))
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"BUD-{next_num:04d}"

def _next_lnk_id() -> str:
    import re as _re
    index = load_index("expense_links")
    nums = []
    for x in (index or []):
        m = _re.match(r'LNK-(\d+)', str(x.get("link_id", "")))
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    return f"LNK-{next_num:04d}"

# ── Ops Categories ────────────────────────────────────────────────────────────

def get_ops_categories() -> list:
    cats = load_index("ops_categories")
    if not cats:
        save_index("ops_categories", DEFAULT_OPS_CATEGORIES)
        return DEFAULT_OPS_CATEGORIES
    return cats

def add_ops_category(code: str, name: str) -> dict:
    cats = get_ops_categories()
    code = code.upper().replace(" ", "_")
    if any(c["code"] == code for c in cats):
        return {"error": f"Kategori '{code}' sudah ada."}
    cat = {"code": code, "name": name}
    cats.append(cat)
    save_index("ops_categories", cats)
    return cat

def find_ops_category(query: str):
    cats = get_ops_categories()
    q = query.upper().strip()
    for c in cats:
        if c["code"] == q:
            return c
    q_lower = query.lower()
    for c in cats:
        if q_lower in c["name"].lower() or q_lower in c["code"].lower():
            return c
    return None

# ── Budgets ───────────────────────────────────────────────────────────────────

def create_budget_project(name: str, total_budget: float, period_start: str,
                           period_end: str = None, notes: str = "", created_by: str = "finance") -> dict:
    budgets = load_index("budget")
    budget_id = _next_bud_id()
    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "budget_id": budget_id, "type": "project", "name": name,
        "ops_category": None, "total_budget": float(total_budget),
        "period_start": period_start, "period_end": period_end,
        "is_recurring": False, "yearly_total": None, "year": None,
        "monthly_slots": {}, "status": "active",
        "created_by": created_by, "created_at": now, "updated_at": now, "notes": notes,
    }
    budgets.append(record)
    save_index("budget", budgets)
    return record

def create_budget_operational(ops_category_code: str, yearly_total: float, year: int,
                               monthly_override: dict = None, notes: str = "",
                               created_by: str = "finance") -> dict:
    budgets = load_index("budget")
    for b in budgets:
        if (b["type"] == "operational" and b.get("ops_category") == ops_category_code
                and b.get("year") == year and b["status"] != "closed"):
            return {"error": f"Budget ops '{ops_category_code}' tahun {year} sudah ada (ID: {b['budget_id']})."}
    budget_id = _next_bud_id()
    now = datetime.now().isoformat(timespec="seconds")
    monthly_override = monthly_override or {}
    override_total = sum(monthly_override.values())
    non_override = [m for m in range(1, 13) if m not in monthly_override]
    adjusted = round((yearly_total - override_total) / len(non_override), 2) if non_override else 0
    monthly_slots = {}
    for month in range(1, 13):
        if month in monthly_override:
            monthly_slots[str(month)] = {"amount": float(monthly_override[month]), "override": True}
        else:
            monthly_slots[str(month)] = {"amount": float(adjusted), "override": False}
    record = {
        "budget_id": budget_id, "type": "operational",
        "name": f"Budget Ops {ops_category_code} {year}",
        "ops_category": ops_category_code, "year": year,
        "total_budget": float(yearly_total), "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31", "is_recurring": True,
        "yearly_total": float(yearly_total), "monthly_slots": monthly_slots,
        "base_monthly": round(yearly_total / 12, 2), "status": "active",
        "created_by": created_by, "created_at": now, "updated_at": now, "notes": notes,
    }
    budgets.append(record)
    save_index("budget", budgets)
    return record

def override_monthly_budget(budget_id: str, month: int, new_amount: float) -> dict:
    budgets = load_index("budget")
    for b in budgets:
        if b["budget_id"] == budget_id:
            if b["type"] != "operational":
                return {"error": "Override bulanan hanya untuk budget operasional."}
            if b["status"] == "closed":
                return {"error": "Budget sudah closed."}
            slots = b["monthly_slots"]
            slots[str(month)]["amount"] = float(new_amount)
            slots[str(month)]["override"] = True
            override_total = sum(s["amount"] for s in slots.values() if s["override"])
            non_override = [k for k, s in slots.items() if not s["override"]]
            if non_override:
                adjusted = round((b["yearly_total"] - override_total) / len(non_override), 2)
                for k in non_override:
                    slots[k]["amount"] = adjusted
            b["monthly_slots"] = slots
            b["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_index("budget", budgets)
            return b
    return {"error": f"Budget '{budget_id}' tidak ditemukan."}

def update_budget(budget_id: str, updates: dict) -> dict:
    budgets = load_index("budget")
    allowed = {"name", "total_budget", "notes", "status", "period_start", "period_end"}
    for b in budgets:
        if b["budget_id"] == budget_id:
            if b["status"] == "closed" and updates.get("status") != "active":
                return {"error": "Budget sudah closed."}
            for k, v in updates.items():
                if k in allowed:
                    b[k] = v
            b["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_index("budget", budgets)
            return b
    return {"error": f"Budget '{budget_id}' tidak ditemukan."}

def close_budget(budget_id: str) -> dict:
    return update_budget(budget_id, {"status": "closed"})

def delete_budget(budget_id: str) -> dict:
    """
    Hapus budget secara permanen.
    Syarat: status = closed DAN tidak ada expense links.
    """
    budget = get_budget_by_id(budget_id)
    if not budget:
        return {"error": f"Budget '{budget_id}' tidak ditemukan."}
    if budget["status"] != "closed":
        return {"error": f"Budget harus ditutup dulu sebelum bisa dihapus. Gunakan 'tutup budget {budget_id}' terlebih dahulu."}
    links = get_links_by_budget(budget_id)
    if links:
        return {"error": f"Budget tidak bisa dihapus karena masih memiliki {len(links)} expense link. Hapus semua link terlebih dahulu atau biarkan sebagai arsip."}
    budgets = load_index("budget")
    budgets = [b for b in budgets if b["budget_id"] != budget_id]
    save_index("budget", budgets)
    return {"deleted": True, "budget": budget}

def get_budget_by_id(budget_id: str):
    budgets = load_index("budget")
    for b in budgets:
        if b["budget_id"] == budget_id:
            return b
    return None

def find_budget_by_name(query: str, budget_type: str = None, status: str = "active") -> list:
    budgets = load_index("budget")
    q = query.lower().strip()
    results = []
    for b in budgets:
        if budget_type and b["type"] != budget_type:
            continue
        # Filter by status — default hanya active, pass None untuk semua
        if status and b.get("status") != status:
            continue
        if q in b["name"].lower():
            results.append(b)
    return results

def list_budgets(status: str = None, budget_type: str = None) -> list:
    budgets = load_index("budget")
    if status:
        budgets = [b for b in budgets if b["status"] == status]
    if budget_type:
        budgets = [b for b in budgets if b["type"] == budget_type]
    return budgets

# ── Expense Links ─────────────────────────────────────────────────────────────

def create_expense_link(budget_id: str, doc_type: str, doc_id: str, amount: float,
                         expense_type: str, notes: str = "", linked_by: str = "finance") -> dict:
    budget = get_budget_by_id(budget_id)
    if not budget:
        return {"error": f"Budget '{budget_id}' tidak ditemukan."}
    if budget["status"] == "closed":
        return {"error": f"Budget '{budget['name']}' sudah closed."}
    links = load_index("expense_links")
    for lnk in links:
        if lnk["doc_id"] == doc_id and lnk["budget_id"] == budget_id:
            return {"error": f"Dokumen '{doc_id}' sudah di-link ke budget ini."}
    link_id = _next_lnk_id()
    record = {
        "link_id": link_id, "budget_id": budget_id, "budget_name": budget["name"],
        "doc_type": doc_type.upper(), "doc_id": doc_id, "amount": float(amount),
        "expense_type": expense_type,
        "linked_at": datetime.now().isoformat(timespec="seconds"),
        "linked_by": linked_by, "notes": notes,
    }
    links.append(record)
    save_index("expense_links", links)
    return record

def delete_expense_link(link_id: str) -> dict:
    links = load_index("expense_links")
    for i, lnk in enumerate(links):
        if lnk["link_id"] == link_id:
            removed = links.pop(i)
            save_index("expense_links", links)
            return {"deleted": True, "link": removed}
    return {"error": f"Link '{link_id}' tidak ditemukan."}

def get_links_by_budget(budget_id: str) -> list:
    return [l for l in load_index("expense_links") if l["budget_id"] == budget_id]

def get_links_by_doc(doc_id: str) -> list:
    return [l for l in load_index("expense_links") if l["doc_id"] == doc_id]

# ── Budget Engine ─────────────────────────────────────────────────────────────

def compute_budget_summary(budget_id: str, month: int = None) -> dict:
    budget = get_budget_by_id(budget_id)
    if not budget:
        return {"error": f"Budget '{budget_id}' tidak ditemukan."}
    links = get_links_by_budget(budget_id)
    if budget["type"] == "operational" and month:
        # Mode: satu bulan spesifik
        year = budget.get("year", datetime.now().year)
        month_prefix = f"{year}-{month:02d}"
        links = [l for l in links if l["linked_at"][:7] == month_prefix]
        total_budget = budget["monthly_slots"].get(str(month), {}).get("amount", 0)
        period_label = f"Bulan {month}/{year}"
    elif budget["type"] == "operational":
        # Mode: overview tahunan — tampilkan yearly_total sebagai acuan
        year = budget.get("year", datetime.now().year)
        total_budget = budget.get("yearly_total", budget["total_budget"])
        period_label = f"YTD {year} (s/d bulan {datetime.now().month})"
    else:
        total_budget = budget["total_budget"]
        period_label = f"{budget['period_start']} s/d {budget['period_end']}"
    committed  = sum(l["amount"] for l in links if l["expense_type"] == "committed")
    actual     = sum(l["amount"] for l in links if l["expense_type"] == "actual")
    total_used = committed + actual
    remaining  = total_budget - total_used
    pct_used   = round((total_used / total_budget * 100), 1) if total_budget > 0 else 0
    alert = None
    if pct_used >= 100: alert = "OVER_BUDGET"
    elif pct_used >= 80: alert = "NEAR_LIMIT"
    return {
        "budget_id": budget_id, "budget_name": budget["name"],
        "type": budget["type"], "period_label": period_label,
        "total_budget": total_budget,
        "yearly_total": budget.get("yearly_total"),
        "committed": committed, "actual": actual,
        "total_used": total_used, "remaining": remaining,
        "pct_used": pct_used, "alert": alert,
        "links_count": len(links), "links": links,
    }

def get_all_budget_summaries(status: str = "active") -> list:
    budgets = list_budgets(status=status)
    summaries = []
    for b in budgets:
        s = compute_budget_summary(b["budget_id"])
        if "error" not in s:
            summaries.append(s)
    priority = {"OVER_BUDGET": 0, "NEAR_LIMIT": 1, None: 2}
    summaries.sort(key=lambda x: priority.get(x["alert"], 2))
    return summaries

def detect_near_limit_budgets(threshold: float = 80.0) -> list:
    return [s for s in get_all_budget_summaries() if s["pct_used"] >= threshold]

def get_ops_summary_by_month(year: int, month: int) -> list:
    budgets = list_budgets(status="active", budget_type="operational")
    result = []
    for b in budgets:
        if b.get("year") == year:
            s = compute_budget_summary(b["budget_id"], month=month)
            if "error" not in s:
                result.append(s)
    return result

# ── Storage summary update ────────────────────────────────────────────────────

def get_storage_summary_with_budget() -> dict:
    base = get_storage_summary()
    base["budget"] = len(load_index("budget"))
    base["expense_links"] = len(load_index("expense_links"))
    return base
