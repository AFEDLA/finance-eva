"""
Generator — buat file Excel dan PDF dari data storage
"""
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(os.getenv("STORAGE_DIR", str(Path.home() / "Documents" / "holomoc-file")))
EXPORT_DIR = BASE_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

COMPANY_NAME = "Holomoc Indonesia"

# ─── EXCEL ────────────────────────────────────────────────────────────────────

def generate_excel_finance(data: list, title: str = "Laporan Keuangan", saldo_awal: int = 0) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan Keuangan"

    # ── Styles ──────────────────────────────────────────────────────────────────
    HDR_FILL  = PatternFill("solid", fgColor="16A34A")
    HDR_FONT  = Font(bold=True, color="FFFFFF", size=10)
    TTL_FONT  = Font(bold=True, size=14, color="1E2235")
    ALT_FILL  = PatternFill("solid", fgColor="F0FDF4")
    INV_FILL  = PatternFill("solid", fgColor="EFF6FF")   # biru muda = invoice/pemasukan
    TOT_FILL  = PatternFill("solid", fgColor="DCFCE7")
    NET_FILL  = PatternFill("solid", fgColor="BBDEFB")   # biru = net
    RED_FILL  = PatternFill("solid", fgColor="FEE2E2")   # merah = net negatif
    center    = Alignment(horizontal="center", vertical="center")
    right     = Alignment(horizontal="right",  vertical="center")
    thin      = Border(
        left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),  bottom=Side(style="thin", color="CCCCCC"),
    )

    # ── Header perusahaan ────────────────────────────────────────────────────────
    ws.merge_cells("A1:F1")
    ws["A1"] = COMPANY_NAME
    ws["A1"].font = Font(bold=True, size=16, color="16A34A")
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = title.upper()
    ws["A2"].font = TTL_FONT
    ws["A2"].alignment = center

    ws.merge_cells("A3:F3")
    ws["A3"] = f"Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}"
    ws["A3"].font = Font(italic=True, color="888888", size=9)
    ws["A3"].alignment = center

    ws.row_dimensions[4].height = 6

    # ── Header kolom (tanpa Saldo) ───────────────────────────────────────────────
    COLS = ["No", "Tanggal", "Uraian", "Pemasukan (Rp)", "Pengeluaran (Rp)", "Project"]
    for col, h in enumerate(COLS, 1):
        cell = ws.cell(row=5, column=col, value=h)
        cell.font      = HDR_FONT
        cell.fill      = HDR_FILL
        cell.alignment = center
        cell.border    = thin

    # ── Data rows ────────────────────────────────────────────────────────────────
    row = 6
    sorted_data       = sorted(data, key=lambda x: x.get("tanggal", x.get("created_at", "")))
    total_pemasukan   = 0
    total_pengeluaran = 0

    for i, item in enumerate(sorted_data):
        jumlah       = int(item.get("jumlah", 0))
        jenis        = item.get("jenis", "").lower()
        is_pemasukan = (jenis == "invoice")

        if is_pemasukan:
            total_pemasukan   += jumlah
            col_masuk  = jumlah
            col_keluar = ""
        else:
            total_pengeluaran += jumlah
            col_masuk  = ""
            col_keluar = jumlah

        jenis_label = item.get("jenis", "").title()
        # Untuk invoice, keperluan sudah berisi nomor invoice — cukup tampilkan nama klien + project
        if jenis == "invoice":
            inv_ref = item.get("inv_ref", "")
            project = item.get("project", "")
            uraian  = f"Invoice — {item.get('nama', '')} | {project}"
            if inv_ref:
                uraian += f" ({inv_ref})"
        else:
            uraian = f"{jenis_label} — {item.get('nama', '')} ({item.get('keperluan', '')})"
        status = item.get("status", "pending")
        if status not in ("approved", "paid"):
            uraian += f" [{status.upper()}]"

        row_fill = INV_FILL if is_pemasukan else (ALT_FILL if i % 2 == 0 else PatternFill())
        # Untuk invoice: kolom project tampilkan ID invoice (project sudah ada di uraian)
        # Untuk RMB/CAS: potong project name jika terlalu panjang
        if is_pemasukan:
            project_name = item.get("inv_ref", "")
        else:
            project_name = item.get("project", "Operasional")
            if len(project_name) > 25:
                project_name = project_name[:23] + "…"
        values = [i + 1, item.get("tanggal", ""), uraian, col_masuk, col_keluar, project_name]

        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border    = thin
            cell.fill      = row_fill
            cell.alignment = Alignment(vertical="center", wrap_text=(col in (3, 6)))
            if col in (4, 5):
                cell.number_format = '#,##0;(#,##0);"-"'
                cell.alignment     = right
        row += 1

    # ── Total row ────────────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:C{row}")
    ws[f"A{row}"] = "TOTAL"
    ws[f"A{row}"].font      = Font(bold=True)
    ws[f"A{row}"].alignment = right
    ws[f"A{row}"].border    = thin
    ws[f"B{row}"].border    = thin
    ws[f"C{row}"].border    = thin

    ws[f"D{row}"] = total_pemasukan
    ws[f"D{row}"].font         = Font(bold=True)
    ws[f"D{row}"].number_format = '#,##0'
    ws[f"D{row}"].alignment    = right
    ws[f"D{row}"].fill         = TOT_FILL
    ws[f"D{row}"].border       = thin

    ws[f"E{row}"] = total_pengeluaran
    ws[f"E{row}"].font         = Font(bold=True)
    ws[f"E{row}"].number_format = '#,##0'
    ws[f"E{row}"].alignment    = right
    ws[f"E{row}"].fill         = TOT_FILL
    ws[f"E{row}"].border       = thin

    ws[f"F{row}"].border = thin
    ws[f"F{row}"].fill   = TOT_FILL
    row += 1

    # ── Net row (Pemasukan − Pengeluaran) ────────────────────────────────────────
    net      = total_pemasukan - total_pengeluaran
    net_fill = NET_FILL if net >= 0 else RED_FILL
    net_clr  = "1D4ED8" if net >= 0 else "DC2626"

    ws.merge_cells(f"A{row}:C{row}")
    ws[f"A{row}"] = "NET (Pemasukan − Pengeluaran)"
    ws[f"A{row}"].font      = Font(bold=True, color=net_clr)
    ws[f"A{row}"].alignment = right
    ws[f"A{row}"].border    = thin
    ws[f"B{row}"].border    = thin
    ws[f"C{row}"].border    = thin

    ws.merge_cells(f"D{row}:E{row}")
    ws[f"D{row}"] = net
    ws[f"D{row}"].font          = Font(bold=True, color=net_clr)
    ws[f"D{row}"].number_format = '+#,##0;-#,##0;"-"'
    ws[f"D{row}"].alignment     = right
    ws[f"D{row}"].fill          = net_fill
    ws[f"D{row}"].border        = thin
    ws[f"E{row}"].border        = thin
    ws[f"E{row}"].fill          = net_fill
    ws[f"F{row}"].border        = thin
    ws[f"F{row}"].fill          = net_fill

    # ── Column widths ─────────────────────────────────────────────────────────────
    for i, w in enumerate([5, 12, 40, 18, 18, 22], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    fname = f"finance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path  = EXPORT_DIR / fname
    wb.save(str(path))
    return str(path)

def generate_excel_arsip(data: list) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Arsip Dokumen"

    header_fill = PatternFill("solid", fgColor="16A34A")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
                  top=Side(style="thin", color="CCCCCC"), bottom=Side(style="thin", color="CCCCCC"))
    alt_fill = PatternFill("solid", fgColor="F0FDF4")

    ws.merge_cells("A1:F1")
    ws["A1"] = f"{COMPANY_NAME} — Arsip Dokumen"
    ws["A1"].font = Font(bold=True, size=14, color="16A34A")
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}"
    ws["A2"].font = Font(italic=True, color="888888", size=9)
    ws["A2"].alignment = center

    ws.row_dimensions[3].height = 8

    headers = ["No", "ID", "Judul", "Kategori", "Deskripsi", "Tanggal"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin

    for i, item in enumerate(data):
        row = i + 5
        fill = alt_fill if i % 2 == 0 else PatternFill()
        values = [i+1, item.get("id",""), item.get("judul",""), item.get("kategori",""), item.get("deskripsi",""), item.get("tanggal","")]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if fill.fgColor.rgb != "00000000": cell.fill = fill

    for i, w in enumerate([5, 12, 30, 14, 35, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    fname = f"arsip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = EXPORT_DIR / fname
    wb.save(str(path))
    return str(path)

def generate_excel_mom(data: list) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Minutes of Meeting"

    header_fill = PatternFill("solid", fgColor="16A34A")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
                  top=Side(style="thin", color="CCCCCC"), bottom=Side(style="thin", color="CCCCCC"))

    ws.merge_cells("A1:F1")
    ws["A1"] = f"{COMPANY_NAME} — Minutes of Meeting"
    ws["A1"].font = Font(bold=True, size=14, color="16A34A")
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}"
    ws["A2"].font = Font(italic=True, color="888888", size=9)
    ws["A2"].alignment = center

    ws.row_dimensions[3].height = 8

    headers = ["No", "ID", "Judul Rapat", "Peserta", "Topik", "Keputusan", "Tanggal"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin

    for i, item in enumerate(data):
        row = i + 5
        fill = PatternFill("solid", fgColor="F0FDF4") if i % 2 == 0 else PatternFill()
        peserta = ", ".join(item.get("peserta", []))
        keputusan = "\n".join(item.get("keputusan", []))
        values = [i+1, item.get("id",""), item.get("judul",""), peserta, item.get("topik",""), keputusan, item.get("tanggal","")]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if fill.fgColor.rgb != "00000000": cell.fill = fill

    for i, w in enumerate([5, 12, 25, 20, 25, 35, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    fname = f"mom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = EXPORT_DIR / fname
    wb.save(str(path))
    return str(path)

def generate_excel_jadwal(data: list) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Jadwal Rapat"

    header_fill = PatternFill("solid", fgColor="16A34A")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
                  top=Side(style="thin", color="CCCCCC"), bottom=Side(style="thin", color="CCCCCC"))

    ws.merge_cells("A1:F1")
    ws["A1"] = f"{COMPANY_NAME} — Jadwal Rapat"
    ws["A1"].font = Font(bold=True, size=14, color="16A34A")
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}"
    ws["A2"].font = Font(italic=True, color="888888", size=9)
    ws["A2"].alignment = center
    ws.row_dimensions[3].height = 8

    headers = ["No", "ID", "Judul Rapat", "Tanggal", "Waktu", "Peserta", "Lokasi"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin

    for i, item in enumerate(data):
        row = i + 5
        fill = PatternFill("solid", fgColor="F0FDF4") if i % 2 == 0 else PatternFill()
        peserta = ", ".join(item.get("peserta", []))
        values = [i+1, item.get("id",""), item.get("judul",""), item.get("tanggal",""), item.get("waktu",""), peserta, item.get("lokasi","")]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = thin
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if fill.fgColor.rgb != "00000000": cell.fill = fill

    for i, w in enumerate([5, 12, 28, 12, 10, 25, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    fname = f"jadwal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = EXPORT_DIR / fname
    wb.save(str(path))
    return str(path)

# ─── PDF ──────────────────────────────────────────────────────────────────────

def generate_pdf_finance(data: list, title: str = "Laporan Keuangan", saldo_awal: int = 0) -> str:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    fname = f"finance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path  = EXPORT_DIR / fname

    doc = SimpleDocTemplate(
        str(path), pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    styles = getSampleStyleSheet()
    story  = []

    # ── Header ──────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"<font color='#16A34A'><b>{COMPANY_NAME}</b></font>",
        ParagraphStyle('co', fontSize=18, spaceAfter=4)
    ))
    story.append(Paragraph(
        f"<b>{title.upper()}</b>",
        ParagraphStyle('sub', fontSize=13, spaceAfter=2)
    ))
    story.append(Paragraph(
        f"<font color='grey' size='8'>Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}</font>",
        styles['Normal']
    ))
    story.append(Spacer(1, 0.5*cm))

    # ── Data ────────────────────────────────────────────────────────────────────
    sorted_data       = sorted(data, key=lambda x: x.get("tanggal", x.get("created_at", "")))
    total_pemasukan   = 0
    total_pengeluaran = 0

    # Style untuk wrap text di kolom uraian
    from reportlab.platypus import Paragraph as _Para
    from reportlab.lib.styles import ParagraphStyle as _PS
    cell_style = _PS('cell', fontSize=8, leading=10, wordWrap='LTR')

    # Header row (tanpa Saldo)
    headers    = ["No", "Tanggal", "Uraian", "Pemasukan (Rp)", "Pengeluaran (Rp)", "Project"]
    table_data = [headers]
    row_styles = []  # index baris untuk pewarnaan invoice

    for i, item in enumerate(sorted_data):
        jumlah       = int(item.get("jumlah", 0))
        jenis        = item.get("jenis", "").lower()
        is_pemasukan = (jenis == "invoice")

        if is_pemasukan:
            total_pemasukan   += jumlah
            col_masuk  = f"Rp {jumlah:,.0f}"
            col_keluar = ""
        else:
            total_pengeluaran += jumlah
            col_masuk  = ""
            col_keluar = f"Rp {jumlah:,.0f}"

        # Uraian — ringkas dan bersih
        if is_pemasukan:
            inv_ref  = item.get("inv_ref", "")
            nama     = item.get("nama", "")
            project  = item.get("project", "")
            # Format: "Invoice | Nama Klien | Nama Project" — tanpa truncation, biarkan wrap
            parts    = ["Invoice", nama]
            if project and project != nama:
                parts.append(project)
            uraian_txt = " | ".join(p for p in parts if p)
            if inv_ref:
                uraian_txt += f"\n{inv_ref}"
        else:
            keperluan  = item.get("keperluan", "")[:50]
            nama       = item.get("nama", "")
            jenis_lbl  = item.get("jenis", "").title()
            uraian_txt = f"{jenis_lbl} — {nama}\n{keperluan}"

        status = item.get("status", "pending")
        if status not in ("approved", "paid"):
            uraian_txt += f" [{status.upper()}]"

        # Wrap text dengan Paragraph agar tidak berantakan
        uraian_para = _Para(uraian_txt.replace("\n", "<br/>"), cell_style)

        # Kolom project: invoice = ID inv, RMB/CAS = nama project
        if is_pemasukan:
            project_col = item.get("inv_ref", "")
        else:
            p = item.get("project", "Operasional")
            project_col = p[:18] + "…" if len(p) > 18 else p

        table_data.append([
            str(i + 1),
            item.get("tanggal", ""),
            uraian_para,
            col_masuk,
            col_keluar,
            project_col,
        ])
        if is_pemasukan:
            row_styles.append(i + 1)

    # Total row
    net     = total_pemasukan - total_pengeluaran
    net_str = f"+Rp {net:,.0f}" if net >= 0 else f"-Rp {abs(net):,.0f}"
    table_data.append([
        "", "", "TOTAL",
        f"Rp {total_pemasukan:,.0f}",
        f"Rp {total_pengeluaran:,.0f}",
        "",
    ])
    # Net row
    table_data.append([
        "", "", f"NET (Pemasukan − Pengeluaran)",
        net_str, "", "",
    ])

    # ── Table style ─────────────────────────────────────────────────────────────
    n_data   = len(sorted_data)
    tot_idx  = n_data + 1   # index baris TOTAL
    net_idx  = n_data + 2   # index baris NET
    net_clr  = colors.HexColor('#1D4ED8') if net >= 0 else colors.HexColor('#DC2626')
    net_bg   = colors.HexColor('#DBEAFE') if net >= 0 else colors.HexColor('#FEE2E2')

    style_cmds = [
        # Header
        ('BACKGROUND',  (0, 0), (-1, 0),       colors.HexColor('#16A34A')),
        ('TEXTCOLOR',   (0, 0), (-1, 0),       colors.white),
        ('FONTNAME',    (0, 0), (-1, 0),       'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, 0),       9),
        # Semua data
        ('FONTSIZE',    (0, 1), (-1, -1),      8),
        ('GRID',        (0, 0), (-1, -1),      0.4, colors.HexColor('#CCCCCC')),
        ('PADDING',     (0, 0), (-1, -1),      4),
        # Alignment
        ('ALIGN',       (0, 0), (-1, -1),      'CENTER'),
        ('ALIGN',       (2, 1), (2, -1),       'LEFT'),   # Uraian
        ('ALIGN',       (3, 1), (4, tot_idx),  'RIGHT'),  # Nominal
        ('VALIGN',      (0, 0), (-1, -1),      'TOP'),    # Top align agar wrap rapi
        # Zebra
        ('ROWBACKGROUNDS', (0, 1), (-1, tot_idx - 1),
         [colors.HexColor('#F0FDF4'), colors.white]),
        # Total row
        ('BACKGROUND',  (0, tot_idx), (-1, tot_idx), colors.HexColor('#DCFCE7')),
        ('FONTNAME',    (0, tot_idx), (-1, tot_idx), 'Helvetica-Bold'),
        ('ALIGN',       (2, tot_idx), (2, tot_idx),  'RIGHT'),
        # Net row
        ('BACKGROUND',  (0, net_idx), (-1, net_idx), net_bg),
        ('FONTNAME',    (0, net_idx), (-1, net_idx), 'Helvetica-Bold'),
        ('TEXTCOLOR',   (0, net_idx), (-1, net_idx), net_clr),
        ('ALIGN',       (2, net_idx), (4, net_idx),  'RIGHT'),
        ('SPAN',        (3, net_idx), (4, net_idx)),  # merge kolom nominal net
    ]

    # Warna biru untuk baris invoice (pemasukan)
    for row_i in row_styles:
        style_cmds.append(('BACKGROUND', (0, row_i), (-1, row_i), colors.HexColor('#EFF6FF')))

    col_widths = [1*cm, 2.5*cm, 9.5*cm, 3.2*cm, 3.2*cm, 3.1*cm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    story.append(t)
    doc.build(story)
    return str(path)

def generate_pdf_mom(data: list) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    fname = f"mom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = EXPORT_DIR / fname

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2.5*cm, rightMargin=2.5*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<font color='#16A34A'><b>{COMPANY_NAME}</b></font>",
                            ParagraphStyle('co', fontSize=16, spaceAfter=2)))
    story.append(Paragraph("<b>Minutes of Meeting</b>",
                            ParagraphStyle('title', fontSize=13, spaceAfter=2)))
    story.append(Paragraph(f"<font color='grey' size='8'>Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}</font>",
                            styles['Normal']))
    story.append(Spacer(1, 0.4*cm))

    label_style = ParagraphStyle('label', fontSize=9, textColor=colors.HexColor('#16A34A'), fontName='Helvetica-Bold')
    value_style = ParagraphStyle('value', fontSize=10, spaceAfter=6)

    for item in data:
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#16A34A')))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(item.get("id",""), label_style))
        story.append(Paragraph(f"<b>{item.get('judul','')}</b>", ParagraphStyle('h', fontSize=12, spaceAfter=4)))
        story.append(Paragraph("TANGGAL", label_style))
        story.append(Paragraph(item.get("tanggal",""), value_style))
        story.append(Paragraph("PESERTA", label_style))
        story.append(Paragraph(", ".join(item.get("peserta",[])), value_style))
        story.append(Paragraph("TOPIK", label_style))
        story.append(Paragraph(item.get("topik",""), value_style))
        if item.get("keputusan"):
            story.append(Paragraph("KEPUTUSAN", label_style))
            for k in item.get("keputusan",[]):
                story.append(Paragraph(f"• {k}", value_style))
        if item.get("action_items"):
            story.append(Paragraph("ACTION ITEMS", label_style))
            for a in item.get("action_items",[]):
                story.append(Paragraph(f"• {a}", value_style))
        story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    return str(path)

def generate_pdf_arsip(data: list) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    fname = f"arsip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = EXPORT_DIR / fname

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<font color='#16A34A'><b>{COMPANY_NAME}</b></font>", ParagraphStyle('title', fontSize=18, spaceAfter=4)))
    story.append(Paragraph("<b>List Arsip Dokumen</b>", ParagraphStyle('sub', fontSize=13, spaceAfter=2)))
    story.append(Paragraph(f"<font color='grey' size='8'>Digenerate: {datetime.now().strftime('%d %B %Y, %H:%M')}</font>", styles['Normal']))
    story.append(Spacer(1, 0.5*cm))

    headers = ["No", "ID", "Judul", "Kategori", "Deskripsi", "Tanggal"]
    table_data = [headers]
    for i, item in enumerate(data):
        table_data.append([
            str(i+1), item.get("id",""), item.get("judul","")[:35],
            item.get("kategori",""), item.get("deskripsi","")[:30], item.get("tanggal","")
        ])

    col_widths = [1*cm, 2.5*cm, 5*cm, 2.5*cm, 4.5*cm, 2.5*cm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#16A34A')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (2,1), (2,-1), 'LEFT'),
        ('ALIGN', (4,1), (4,-1), 'LEFT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F0FDF4'), colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC')),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t)
    doc.build(story)
    return str(path)

# ─── PURCHASE REQUEST ─────────────────────────────────────────────────────────

COMPANY_ADDRESS = "Jl. Duren Sawit Indah No.K1 no 10, Kec. Duren Sawit, Jakarta Timur, 13440"

def _pr_total(items: list) -> int:
    return sum(int(x.get("jumlah", 0)) for x in items)

def generate_pr_pdf(pr: dict) -> str:
    """Generate PR sebagai PDF — layout identik template PR Holomoc.
    Header: logo kiri kecil (5.28cm) + alamat perusahaan teks kanan.
    """
    from reportlab.lib.pagesizes import letter as LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (Table, TableStyle, Paragraph, Spacer,
                                    BaseDocTemplate, PageTemplate, Frame, Image as RLImage)
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    import zipfile as _zf

    items   = pr.get("items", [])
    total   = _pr_total(items)
    tanggal = pr.get("tanggal_permohonan", datetime.now().strftime("%d %B %Y"))

    fname = f"PR_{pr.get('id','PR')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path  = EXPORT_DIR / fname

    # ── Logo dari PR template (pola sama seperti PO dari PO template) ──
    LOGO_PR = Path(__file__).parent / "pr_logo.jpg"
    TPL_PR  = Path(__file__).parent / "Purchase_Request_Template.docx"
    if not LOGO_PR.exists() and TPL_PR.exists():
        with _zf.ZipFile(str(TPL_PR)) as _z:
            try:
                LOGO_PR.write_bytes(_z.read("word/media/image1.jpg"))
            except Exception:
                pass

    # ── Page: Letter 21.59x27.94cm, margin 1.7cm (ikuti template) ──
    PAGE_W  = 21.59 * cm
    PAGE_H  = 27.94 * cm
    L_MAR   = 1.7 * cm
    R_MAR   = 1.7 * cm
    B_MAR   = 1.5 * cm

    # Header tinggi: logo 0.68cm + padding 0.3cm atas + 0.3cm bawah = 1.28cm
    HEADER_H = 1.4 * cm
    T_MAR    = HEADER_H + 0.4 * cm  # konten mulai di bawah header

    BLACK = colors.black
    GREY  = colors.HexColor("#666666")
    DARK  = colors.HexColor("#1E2235")

    def draw_header(canvas, doc):
        """Header: logo kiri kecil + alamat perusahaan kanan (persis seperti template)."""
        canvas.saveState()
        y_top = PAGE_H - 0.3 * cm  # 0.3cm dari atas halaman

        # Logo kiri: 5.28cm lebar x 0.68cm tinggi (ukuran asli di template)
        logo_w = 5.28 * cm
        logo_h = 0.68 * cm
        if LOGO_PR.exists():
            canvas.drawImage(str(LOGO_PR),
                             L_MAR, y_top - logo_h,
                             width=logo_w, height=logo_h,
                             preserveAspectRatio=True, mask='auto')
        else:
            canvas.setFont("Helvetica-Bold", 12)
            canvas.setFillColor(DARK)
            canvas.drawString(L_MAR, y_top - 0.5*cm, "HOLOMOC")

        # Alamat perusahaan kanan (3 baris)
        txt_x   = L_MAR + logo_w + 0.3 * cm
        txt_w   = PAGE_W - txt_x - R_MAR
        txt_y   = y_top - 0.25 * cm
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(DARK)
        canvas.drawRightString(PAGE_W - R_MAR, txt_y,              "PT HOLOMOC INDONESIA,")
        canvas.drawRightString(PAGE_W - R_MAR, txt_y - 0.30*cm,   "Jl. Duren Sawit Indah Blok K1/10, Duren Sawit, Jakarta Timur – 13440, INDONESIA")
        canvas.drawRightString(PAGE_W - R_MAR, txt_y - 0.60*cm,   "P. 081345678910")

        # Garis bawah header tipis
        canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
        canvas.setLineWidth(0.3)
        canvas.line(L_MAR, y_top - HEADER_H, PAGE_W - R_MAR, y_top - HEADER_H)

        canvas.restoreState()

    frame = Frame(L_MAR, B_MAR,
                  PAGE_W - L_MAR - R_MAR,
                  PAGE_H - T_MAR - B_MAR,
                  id='normal', leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    tpl = PageTemplate(id='main', frames=[frame], onPage=draw_header)
    doc = BaseDocTemplate(str(path), pagesize=(PAGE_W, PAGE_H),
                          leftMargin=L_MAR, rightMargin=R_MAR,
                          topMargin=T_MAR, bottomMargin=B_MAR)
    doc.addPageTemplates([tpl])

    story = []
    s11  = ParagraphStyle("s11",  fontSize=11, fontName="Helvetica")
    s11b = ParagraphStyle("s11b", fontSize=11, fontName="Helvetica-Bold")

    # ── Judul ──
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(
        "<b>PURCHASE REQUEST</b>",
        ParagraphStyle("judul", fontSize=22, fontName="Helvetica-Bold",
                       alignment=TA_CENTER, spaceAfter=10)
    ))
    story.append(Spacer(1, 0.3*cm))

    # ── Tabel Info (2 kolom, berkotak) ──
    info_data = [
        [Paragraph(f"<b>Pemohon             : </b>{pr.get('pemohon','')}", s11),
         Paragraph("<b>PR # :</b>",                  s11b)],
        [Paragraph("",                               s11),
         Paragraph(pr.get("nomor",""),               s11b)],
        [Paragraph(f"<b>Proyek / Client      : </b>{pr.get('proyek','')}", s11),
         Paragraph("",                               s11)],
        [Paragraph("",                               s11),
         Paragraph("<b>TANGGAL PERMOHONAN :</b>",    s11b)],
        [Paragraph(f"<b>Keperluan            : </b>{pr.get('keperluan','')}", s11),
         Paragraph(tanggal,                          s11b)],
    ]
    info_t = Table(info_data, colWidths=[9.0*cm, 8.2*cm])
    info_t.setStyle(TableStyle([
        ("BOX",           (0,0), (-1,-1), 0.5, BLACK),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
    ]))
    story.append(info_t)
    story.append(Spacer(1, 0.3*cm))

    # ── Tabel Items (No | Item | Harga Perkiraan | Qty | Jumlah) ──
    # Semua sel pakai Paragraph agar teks panjang bisa word-wrap
    s_item = ParagraphStyle("si", fontSize=10, fontName="Helvetica", leading=13)
    s_num  = ParagraphStyle("sn", fontSize=10, fontName="Helvetica", leading=13, alignment=1)  # CENTER
    s_hdr  = ParagraphStyle("sh", fontSize=10, fontName="Helvetica-Bold", leading=13)
    s_hdr_c= ParagraphStyle("shc",fontSize=10, fontName="Helvetica-Bold", leading=13, alignment=1)

    tbl_data = [[
        Paragraph("No",              s_hdr_c),
        Paragraph("Item",            s_hdr),
        Paragraph("Harga Perkiraan", s_hdr_c),
        Paragraph("Qty",             s_hdr_c),
        Paragraph("Jumlah",          s_hdr_c),
    ]]
    for i, item in enumerate(items):
        harga  = int(item.get("harga_perkiraan", 0))
        qty    = int(item.get("qty", 1))
        sat    = item.get("satuan", "Pcs")
        jumlah = int(item.get("jumlah", harga * qty))
        tbl_data.append([
            Paragraph(str(i + 1),              s_num),
            Paragraph(item.get("nama", ""),    s_item),
            Paragraph(f"{harga:,}",            s_num),
            Paragraph(f"( {qty} {sat} )",      s_num),
            Paragraph(f"{jumlah:,}",           s_num),
        ])

    s_sub  = ParagraphStyle("ss", fontSize=10, fontName="Helvetica-Bold", leading=13, alignment=1)
    tbl_data.append([
        Paragraph("", s_item),
        Paragraph("", s_item),
        Paragraph("", s_item),
        Paragraph("Sub Total", s_sub),
        Paragraph(f"{total:,}", s_sub),
    ])

    col_w = [1.0*cm, 7.8*cm, 3.2*cm, 2.7*cm, 3.0*cm]
    t = Table(tbl_data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        # Border penuh semua sel — termasuk baris Sub Total
        ("BOX",           (0,0),  (-1,-1), 0.5, BLACK),
        ("INNERGRID",     (0,0),  (-1,-1), 0.5, BLACK),
        ("FONTSIZE",      (0,0),  (-1,-1), 10),
        ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 4),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    # ── Terbilang ──
    story.append(Paragraph(
        f"   Terbilang : {_terbilang(total)} Rupiah,--",
        ParagraphStyle("terb", fontSize=11, fontName="Times-Roman", spaceAfter=4)
    ))

    if pr.get("catatan"):
        story.append(Paragraph(
            f"   Catatan : {pr['catatan']}",
            ParagraphStyle("note", fontSize=10)
        ))

    story.append(Spacer(1, 0.8*cm))

    # ── TTD kanan bawah ──
    story.append(Paragraph(
        "Hormat kami",
        ParagraphStyle("hk", fontSize=11, fontName="Times-Roman", alignment=TA_RIGHT)
    ))
    story.append(Spacer(1, 2.2*cm))
    story.append(Paragraph(
        f"<b>{pr.get('pemohon','_______________')}</b>",
        ParagraphStyle("ttd", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    ))
    story.append(Paragraph(
        "[NAMA PEMOHON]",
        ParagraphStyle("ttd2", fontSize=9, textColor=GREY, alignment=TA_RIGHT)
    ))

    doc.build(story)
    return str(path)


def generate_pr_docx(pr: dict) -> str:
    """Generate PR sebagai .docx — layout identik template PR Holomoc.
    Header page: logo kiri kecil (5.28cm) + alamat perusahaan teks kanan.
    Logo diambil dari Purchase_Request_Template.docx (pola sama seperti PO).
    """
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor, Emu
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import zipfile as _zf

    def _no_border(cell):
        tc = cell._tc; tcPr = tc.get_or_add_tcPr()
        b = OxmlElement("w:tcBorders")
        for s in ["top","left","bottom","right"]:
            el = OxmlElement(f"w:{s}"); el.set(qn("w:val"), "none"); b.append(el)
        tcPr.append(b)

    def _single_border(cell, color="000000", sz="4"):
        tc = cell._tc; tcPr = tc.get_or_add_tcPr()
        b = OxmlElement("w:tcBorders")
        for s in ["top","left","bottom","right"]:
            el = OxmlElement(f"w:{s}")
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), sz); el.set(qn("w:color"), color)
            b.append(el)
        tcPr.append(b)

    def _tbl_borders(tbl, color="000000", sz="4"):
        tbl_el = tbl._tbl
        tblPr  = tbl_el.find(qn("w:tblPr"))
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr"); tbl_el.insert(0, tblPr)
        tb = OxmlElement("w:tblBorders")
        for s in ["top","left","bottom","right","insideH","insideV"]:
            el = OxmlElement(f"w:{s}")
            el.set(qn("w:val"), "single"); el.set(qn("w:sz"), sz); el.set(qn("w:color"), color)
            tb.append(el)
        tblPr.append(tb)

    items   = pr.get("items", [])
    total   = _pr_total(items)
    tanggal = pr.get("tanggal_permohonan", datetime.now().strftime("%d %B %Y"))

    fname = f"PR_{pr.get('id','PR')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    path  = EXPORT_DIR / fname

    # ── Logo dari PR template (pola sama seperti PO) ──
    LOGO_PR = Path(__file__).parent / "pr_logo.jpg"
    TPL_PR  = Path(__file__).parent / "Purchase_Request_Template.docx"
    if not LOGO_PR.exists() and TPL_PR.exists():
        with _zf.ZipFile(str(TPL_PR)) as _z:
            try:
                LOGO_PR.write_bytes(_z.read("word/media/image1.jpg"))
            except Exception:
                pass

    doc = Document()

    # ── Page setup: Letter 21.59x27.94cm, margin 1.7cm (ikuti template) ──
    for section in doc.sections:
        section.page_width    = Cm(21.59)
        section.page_height   = Cm(27.94)
        section.left_margin   = Cm(1.7)
        section.right_margin  = Cm(1.7)
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.header_distance = Cm(0.63)  # 720 twip dari template

    # ── Header page: tabel 2 kolom (logo kiri + alamat kanan) ──
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    for p in header.paragraphs:
        p.clear()

    # Buat tabel header 1 baris 2 kolom
    hdr_tbl = header.add_table(rows=1, cols=2, width=Cm(18.19))
    # Hapus border tabel header
    hdr_tbl_el = hdr_tbl._tbl
    hdr_tblPr  = hdr_tbl_el.find(qn("w:tblPr"))
    if hdr_tblPr is None:
        hdr_tblPr = OxmlElement("w:tblPr"); hdr_tbl_el.insert(0, hdr_tblPr)
    hdr_tb = OxmlElement("w:tblBorders")
    for s in ["top","left","bottom","right","insideH","insideV"]:
        el = OxmlElement(f"w:{s}"); el.set(qn("w:val"), "none"); hdr_tb.append(el)
    hdr_tblPr.append(hdr_tb)

    # Kolom kiri: logo 5.28cm
    hdr_left  = hdr_tbl.rows[0].cells[0]
    hdr_right = hdr_tbl.rows[0].cells[1]
    hdr_left.width  = Cm(5.5)
    hdr_right.width = Cm(12.69)
    _no_border(hdr_left); _no_border(hdr_right)

    p_logo = hdr_left.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if LOGO_PR.exists():
        # Logo asli di template: 5.28cm x 0.68cm
        p_logo.add_run().add_picture(str(LOGO_PR), width=Cm(5.28))
    else:
        r = p_logo.add_run("HOLOMOC")
        r.bold = True; r.font.size = Pt(16); r.font.name = "Calibri"
        r.font.color.rgb = RGBColor(0x1E, 0x6A, 0xA5)

    # Kolom kanan: alamat 3 baris rata kanan
    p_addr = hdr_right.paragraphs[0]
    p_addr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    def _addr_run(para, text, first=False, sz=8):
        p = para if first else para._element.getparent()
        r = para.add_run(text)
        r.font.size = Pt(sz); r.font.name = "Calibri"
        r.font.color.rgb = RGBColor(0x1E, 0x22, 0x35)
        return r
    _addr_run(p_addr, "PT HOLOMOC INDONESIA,", first=True, sz=8)
    p_addr2 = hdr_right.add_paragraph()
    p_addr2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _addr_run(p_addr2, "Jl. Duren Sawit Indah Blok K1/10, Duren Sawit, Jakarta Timur – 13440, INDONESIA", sz=7)
    p_addr3 = hdr_right.add_paragraph()
    p_addr3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _addr_run(p_addr3, "P. 081345678910", sz=8)

    # ── Judul PURCHASE REQUEST ──
    doc.add_paragraph()
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_title = p_title.add_run("PURCHASE REQUEST")
    r_title.bold = True; r_title.font.size = Pt(26); r_title.font.name = "Calibri"
    doc.add_paragraph()

    # ── Tabel Info (2 kolom berkotak) ──
    tbl_info = doc.add_table(rows=1, cols=2)
    tbl_info.alignment = WD_TABLE_ALIGNMENT.LEFT
    _tbl_borders(tbl_info)

    ci_l = tbl_info.rows[0].cells[0]
    ci_r = tbl_info.rows[0].cells[1]
    ci_l.width = Cm(10.0); ci_r.width = Cm(8.19)

    def _il(cell, bold_label, value, first=False, sz=11):
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        if bold_label:
            rl = p.add_run(bold_label); rl.bold = True
            rl.font.size = Pt(sz); rl.font.name = "Calibri"
        if value:
            rv = p.add_run(value)
            rv.font.size = Pt(sz); rv.font.name = "Calibri"

    _il(ci_l, "Pemohon             : ", pr.get("pemohon",""),   first=True)
    _il(ci_l, "",                        "")
    _il(ci_l, "Proyek / Client      : ", pr.get("proyek",""))
    _il(ci_l, "",                        "")
    _il(ci_l, "Keperluan            : ", pr.get("keperluan",""))

    _il(ci_r, "PR # :",              "",                  first=True)
    _il(ci_r, pr.get("nomor",""),    "")
    _il(ci_r, "",                    "")
    _il(ci_r, "TANGGAL PERMOHONAN :", "")
    _il(ci_r, tanggal,               "")

    doc.add_paragraph()

    # ── Tabel Items: No | Item | Harga Perkiraan | Qty | Jumlah ──
    col_w   = [Cm(1.0), Cm(7.5), Cm(3.3), Cm(3.0), Cm(3.0)]
    headers = ["No ", "Item ", " Harga Perkiraan ", "Qty ", " Jumlah "]

    tbl_items = doc.add_table(rows=1 + len(items) + 1, cols=5)
    tbl_items.alignment = WD_TABLE_ALIGNMENT.LEFT
    _tbl_borders(tbl_items)

    for c, (h, w) in enumerate(zip(headers, col_w)):
        cell = tbl_items.rows[0].cells[c]; cell.width = w
        p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(h); r.bold = True; r.font.size = Pt(11); r.font.name = "Cambria"

    for i, item in enumerate(items):
        harga  = int(item.get("harga_perkiraan", 0))
        qty    = int(item.get("qty", 1))
        sat    = item.get("satuan", "Pcs")
        jumlah = int(item.get("jumlah", harga * qty))
        row    = tbl_items.rows[i + 1]
        vals   = [str(i+1), item.get("nama",""), f"{harga:,}", f"( {qty} {sat} )", f"{jumlah:,}"]
        aligns = [WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT,
                  WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER,
                  WD_ALIGN_PARAGRAPH.CENTER]
        for c, (v, a, w) in enumerate(zip(vals, aligns, col_w)):
            cell = row.cells[c]; cell.width = w
            p = cell.paragraphs[0]; p.alignment = a
            p.add_run(v).font.size = Pt(11)

    # Sub Total row: semua kolom berkotak (border penuh semua sisi)
    sub_row = tbl_items.rows[-1]
    for c in range(5):
        sub_row.cells[c].width = col_w[c]
        sub_row.cells[c].paragraphs[0].clear()
        _single_border(sub_row.cells[c])  # border penuh semua kolom

    p3 = sub_row.cells[3].paragraphs[0]; p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r3 = p3.add_run("Sub Total"); r3.bold = True; r3.font.size = Pt(11); r3.font.name = "Cambria"
    p4 = sub_row.cells[4].paragraphs[0]; p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r4 = p4.add_run(f"{total:,}"); r4.bold = True; r4.font.size = Pt(11); r4.font.name = "Cambria"

    doc.add_paragraph()

    # ── Terbilang ──
    p_terb = doc.add_paragraph()
    r_terb = p_terb.add_run(f"Terbilang : {_terbilang(total)} Rupiah,--")
    r_terb.font.size = Pt(12); r_terb.font.name = "Times New Roman"

    if pr.get("catatan"):
        p_cat = doc.add_paragraph()
        p_cat.add_run(f"Catatan : {pr['catatan']}").font.size = Pt(10)

    doc.add_paragraph()
    doc.add_paragraph()

    # ── TTD ──
    p_hk = doc.add_paragraph()
    r_hk = p_hk.add_run("      Hormat kami")
    r_hk.font.size = Pt(11); r_hk.font.name = "Times New Roman"

    for _ in range(5):
        doc.add_paragraph()

    p_nama = doc.add_paragraph()
    r_nama = p_nama.add_run(f"       {pr.get('pemohon','_______________').upper()} [NAMA PEMOHON]")
    r_nama.bold = True; r_nama.font.size = Pt(11); r_nama.font.name = "Times New Roman"

    doc.save(str(path))
    return str(path)



# ─── PURCHASE ORDER ───────────────────────────────────────────────────────────

TEMPLATE_PO_PATH = Path(__file__).parent / "PO_Template_AI.docx"

def _terbilang(n: int) -> str:
    """Konversi angka ke kata bahasa Indonesia (untuk field Terbilang di PO)."""
    satuan = ["", "satu", "dua", "tiga", "empat", "lima",
              "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]

    def _bilang(x):
        if x < 12:   return satuan[x]
        if x < 20:   return _bilang(x - 10) + " belas"
        if x < 100:  return _bilang(x // 10) + " puluh" + (" " + _bilang(x % 10) if x % 10 else "")
        if x < 200:  return "seratus" + (" " + _bilang(x % 100) if x % 100 else "")
        return _bilang(x // 100) + " ratus" + (" " + _bilang(x % 100) if x % 100 else "")

    def _rek(x):
        if x == 0:          return ""
        if x < 1000:        return _bilang(x)
        if x < 2000:        return "seribu" + (" " + _rek(x % 1000) if x % 1000 else "")
        if x < 1_000_000:   return _rek(x // 1000) + " ribu" + (" " + _rek(x % 1000) if x % 1000 else "")
        if x < 1_000_000_000: return _rek(x // 1_000_000) + " juta" + (" " + _rek(x % 1_000_000) if x % 1_000_000 else "")
        return _rek(x // 1_000_000_000) + " miliar" + (" " + _rek(x % 1_000_000_000) if x % 1_000_000_000 else "")

    if n == 0: return "Nol"
    hasil = _rek(abs(n))
    hasil = " ".join(w.capitalize() for w in hasil.split())
    return ("Minus " if n < 0 else "") + hasil

def generate_po_docx(po: dict) -> str:
    """Generate dokumen PO Word (.docx) — build from scratch, logo di-embed langsung.
    Tidak bergantung file template eksternal sehingga selalu berhasil.
    """
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io, re as _re, base64

    # ── Logo Holomoc (embedded sebagai base64 agar tidak bergantung file eksternal) ──
    # Dicopy dari PO_Template_AI.docx saat setup. Kalau template ada di disk, pakai itu.
    LOGO_PATH = TEMPLATE_PO_PATH.parent / "po_logo.jpeg"
    # Fallback: coba dari template langsung
    if not LOGO_PATH.exists():
        _tpl = TEMPLATE_PO_PATH
        if _tpl.exists():
            import zipfile
            with zipfile.ZipFile(str(_tpl)) as _z:
                try:
                    _img = _z.read("word/media/image1.jpeg")
                    LOGO_PATH.write_bytes(_img)
                except Exception:
                    pass

    def _set_cell_shading(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tcPr.append(shd)

    def _set_cell_borders(cell, color="CCCCCC", sz="4"):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        borders = OxmlElement("w:tcBorders")
        for side in ["top", "left", "bottom", "right"]:
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), sz)
            el.set(qn("w:color"), color)
            borders.append(el)
        tcPr.append(borders)

    def _para(cell, text, bold=False, size=10, align=WD_ALIGN_PARAGRAPH.LEFT, color=None):
        p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
        p.alignment = align
        run = p.add_run(str(text))
        run.bold = bold
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        return run

    items   = po.get("items", [])
    total   = sum(int(x.get("jumlah", 0)) for x in items)
    tanggal = po.get("tanggal", datetime.now().strftime("%d %B %Y"))

    doc = Document()

    # ── Page setup ──
    for section in doc.sections:
        section.page_width    = Cm(21.0)
        section.page_height   = Cm(29.7)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(1.5)
        section.top_margin    = Cm(2.3)
        section.bottom_margin = Cm(1.5)

    # ── Header: Logo + Judul ──
    tbl_header = doc.add_table(rows=1, cols=2)
    tbl_header.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Col kiri: logo
    cell_logo = tbl_header.rows[0].cells[0]
    cell_logo.width = Cm(6)
    p_logo = cell_logo.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if LOGO_PATH.exists():
        run_logo = p_logo.add_run()
        run_logo.add_picture(str(LOGO_PATH), width=Cm(5.5))
    else:
        run_l = p_logo.add_run("PT HOLOMOC INDONESIA")
        run_l.bold = True; run_l.font.size = Pt(14)

    # Col kanan: judul + info perusahaan
    cell_title = tbl_header.rows[0].cells[1]
    cell_title.width = Cm(11)
    p_t = cell_title.paragraphs[0]
    p_t.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run_t = p_t.add_run("PURCHASE ORDER")
    run_t.bold = True; run_t.font.size = Pt(16)
    p_addr = cell_title.add_paragraph()
    p_addr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run_addr = p_addr.add_run("Jl. Duren Sawit Indah Blok K1/10, Duren Sawit, Jakarta Timur 13440")
    run_addr.font.size = Pt(8)
    run_addr.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    p_ph = cell_title.add_paragraph()
    p_ph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run_ph = p_ph.add_run("P. 0812-85232001")
    run_ph.font.size = Pt(8)
    run_ph.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # Hapus border header table
    for row in tbl_header.rows:
        for cell in row.cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for side in ["top","left","bottom","right"]:
                el = OxmlElement(f"w:{side}"); el.set(qn("w:val"),"none")
                borders.append(el)
            tcPr.append(borders)

    doc.add_paragraph()  # spacer

    # ── Tabel Vendor & PO Info ──
    tbl_info = doc.add_table(rows=1, cols=2)
    ci_left  = tbl_info.rows[0].cells[0]
    ci_right = tbl_info.rows[0].cells[1]
    ci_left.width  = Cm(9.5)
    ci_right.width = Cm(7.5)

    # Kiri: vendor info
    def _add_info_line(cell, label, value, first=False):
        p = cell.paragraphs[0] if first and cell.paragraphs else cell.add_paragraph()
        rl = p.add_run(label); rl.bold = True; rl.font.size = Pt(10)
        rv = p.add_run(str(value)); rv.font.size = Pt(10)

    _add_info_line(ci_left, "To            :  ", po.get("vendor_nama",""),  first=True)
    _add_info_line(ci_left, "Alamat   :  ",      po.get("vendor_alamat",""))
    _add_info_line(ci_left, "Attn         :  ",  po.get("vendor_attn","-"))

    # Kanan: PO details
    _add_info_line(ci_right, "PO #  :  ", po.get("nomor",""),  first=True)
    _add_info_line(ci_right, "Date   :  ", tanggal)
    _add_info_line(ci_right, "REF # :  ", po.get("ref","-"))

    for row in tbl_info.rows:
        for cell in row.cells:
            tc = cell._tc
            tcPr = tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for side in ["top","left","bottom","right"]:
                el = OxmlElement(f"w:{side}"); el.set(qn("w:val"),"none")
                borders.append(el)
            tcPr.append(borders)

    doc.add_paragraph()

    # ── Tabel Item ──
    # Kolom: No | Item | Harga Satuan | Qty | Jumlah
    col_w = [Cm(0.95), Cm(8.21), Cm(3.34), Cm(3.23), Cm(3.06)]
    HDR_COLOR = "1E2235"
    ALT_COLOR  = "F5F5F5"

    tbl_items = doc.add_table(rows=1 + len(items) + 1, cols=5)

    # Header row
    headers = ["No", "Item / Nama Barang", "Harga Satuan", "Qty", "Jumlah"]
    for c, (h, w) in enumerate(zip(headers, col_w)):
        cell = tbl_items.rows[0].cells[c]
        cell.width = w
        _set_cell_shading(cell, HDR_COLOR)
        _set_cell_borders(cell, color="FFFFFF", sz="2")
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(h)
        run.bold = True; run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    # Data rows
    for i, item in enumerate(items):
        harga  = int(item.get("harga_perkiraan", item.get("harga_satuan", 0)))
        qty    = int(item.get("qty", 1))
        sat    = item.get("satuan", "Pcs")
        jumlah = int(item.get("jumlah", harga * qty))
        row    = tbl_items.rows[i + 1]
        bg     = ALT_COLOR if i % 2 == 0 else "FFFFFF"
        vals   = [str(i+1), item.get("nama",""), f"{harga:,}", f"( {qty} {sat} )", f"{jumlah:,}"]
        aligns = [WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.LEFT,
                  WD_ALIGN_PARAGRAPH.RIGHT,  WD_ALIGN_PARAGRAPH.CENTER,
                  WD_ALIGN_PARAGRAPH.RIGHT]
        for c, (v, a, w) in enumerate(zip(vals, aligns, col_w)):
            cell = row.cells[c]
            cell.width = w
            _set_cell_shading(cell, bg)
            _set_cell_borders(cell)
            p = cell.paragraphs[0]; p.alignment = a
            run = p.add_run(v); run.font.size = Pt(9)

    # Sub Total row
    sub_row = tbl_items.rows[-1]
    for c in range(5):
        cell = sub_row.cells[c]
        cell.width = col_w[c]
        _set_cell_shading(cell, "E8E8E8")
        _set_cell_borders(cell)
        cell.paragraphs[0].clear()
    p3 = sub_row.cells[3].paragraphs[0]
    p3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r3 = p3.add_run("Sub Total"); r3.bold = True; r3.font.size = Pt(9)
    p4 = sub_row.cells[4].paragraphs[0]
    p4.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r4 = p4.add_run(f"Rp {total:,}"); r4.bold = True; r4.font.size = Pt(9)

    doc.add_paragraph()

    # ── Terbilang ──
    p_terb = doc.add_paragraph()
    run_terb = p_terb.add_run(f"Terbilang : {_terbilang(total)} Rupiah,-- ")
    run_terb.italic = True; run_terb.font.size = Pt(9)

    doc.add_paragraph()

    # ── TTD ──
    p_salam = doc.add_paragraph()
    p_salam.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_salam.add_run("Hormat kami,").font.size = Pt(10)

    for _ in range(4):
        p_sp = doc.add_paragraph()
        p_sp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_sp.add_run("").font.size = Pt(10)

    p_name = doc.add_paragraph()
    p_name.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run_name = p_name.add_run("Finance")
    run_name.bold = True; run_name.underline = True; run_name.font.size = Pt(10)

    p_dept = doc.add_paragraph()
    p_dept.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_dept.add_run("PT Holomoc Indonesia").font.size = Pt(9)

    fname = f"PO_{po.get('id','PO')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    path  = EXPORT_DIR / fname
    doc.save(str(path))
    return str(path)

def generate_po_pdf(po: dict) -> str:
    """Generate PO sebagai PDF dengan logo Holomoc di header — layout identik dengan Word."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable, Image)
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

    items   = po.get("items", [])
    total   = sum(int(x.get("jumlah", 0)) for x in items)
    tanggal = po.get("tanggal", datetime.now().strftime("%d %B %Y"))

    fname = f"PO_{po.get('id', 'PO')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path  = EXPORT_DIR / fname

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=2.5*cm, rightMargin=1.5*cm,
        topMargin=2.3*cm, bottomMargin=1.5*cm
    )
    styles = getSampleStyleSheet()
    story  = []

    # ── Header: Logo kiri + Judul & Alamat kanan ──
    LOGO_PATH = TEMPLATE_PO_PATH.parent / "po_logo.jpeg"
    # Fallback: ekstrak dari template kalau logo belum ada
    if not LOGO_PATH.exists() and TEMPLATE_PO_PATH.exists():
        import zipfile
        with zipfile.ZipFile(str(TEMPLATE_PO_PATH)) as _z:
            try:
                LOGO_PATH.write_bytes(_z.read("word/media/image1.jpeg"))
            except Exception:
                pass

    DARK = colors.HexColor("#1E2235")
    GREY = colors.HexColor("#666666")

    s_company = ParagraphStyle("co",   fontSize=13, textColor=DARK,  fontName="Helvetica-Bold", alignment=TA_RIGHT)
    s_addr    = ParagraphStyle("addr", fontSize=8,  textColor=GREY,  alignment=TA_RIGHT, spaceAfter=1)
    s_phone   = ParagraphStyle("ph",   fontSize=8,  textColor=GREY,  alignment=TA_RIGHT)
    s_po_title= ParagraphStyle("pot",  fontSize=14, textColor=DARK,  fontName="Helvetica-Bold", alignment=TA_RIGHT, spaceBefore=4)

    right_col = [
        Paragraph("PT HOLOMOC INDONESIA", s_company),
        Paragraph("Jl. Duren Sawit Indah Blok K1/10, Duren Sawit, Jakarta Timur 13440", s_addr),
        Paragraph("P. 0812-85232001", s_phone),
        Paragraph("PURCHASE ORDER", s_po_title),
    ]

    if LOGO_PATH.exists():
        logo_img = Image(str(LOGO_PATH), width=5.5*cm, height=5.5*cm * (17485/17485)**0.5)
        # Hitung tinggi proporsional
        from PIL import Image as PILImage
        with PILImage.open(str(LOGO_PATH)) as pil:
            w_px, h_px = pil.size
        logo_h = 5.5*cm * h_px / w_px
        logo_img = Image(str(LOGO_PATH), width=5.5*cm, height=logo_h)
        left_col = [logo_img]
    else:
        left_col = [Paragraph("<b>PT HOLOMOC INDONESIA</b>",
                               ParagraphStyle("fb", fontSize=12, fontName="Helvetica-Bold"))]

    header_data = [[left_col, right_col]]
    header_tbl = Table(header_data, colWidths=[7*cm, 10*cm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN",    (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",     (0,0), (0,0),   "LEFT"),
        ("ALIGN",     (1,0), (1,0),   "RIGHT"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width="100%", thickness=1.5, color=DARK, spaceAfter=6))

    # ── Info vendor & PO# (2 kolom) ──
    s9  = ParagraphStyle("s9",  fontSize=9)
    s9b = ParagraphStyle("s9b", fontSize=9, fontName="Helvetica-Bold")

    def _info_row(label, value):
        return [Paragraph(f"<b>{label}</b> {value}", s9), ""]

    info_data = [
        [Paragraph(f"<b>To            :</b>  {po.get('vendor_nama','')}", s9),
         Paragraph(f"<b>PO #  :</b>  {po.get('nomor','')}", s9)],
        [Paragraph(f"<b>Alamat   :</b>  {po.get('vendor_alamat','')}", s9),
         Paragraph(f"<b>Date   :</b>  {tanggal}", s9)],
        [Paragraph(f"<b>Attn       :</b>  {po.get('vendor_attn','-')}", s9),
         Paragraph(f"<b>REF #  :</b>  {po.get('ref','-')}", s9)],
        [Paragraph(f"<b>Proyek   :</b>  {po.get('proyek','')}", s9),
         Paragraph("", s9)],
    ]
    info_t = Table(info_data, colWidths=[9.5*cm, 7.5*cm])
    info_t.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
    ]))
    story.append(info_t)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"), spaceAfter=4))

    # ── Tabel Item ──
    tbl_data = [["No", "Item / Nama Barang", "Harga Satuan", "Qty", "Jumlah"]]
    for i, item in enumerate(items):
        harga  = int(item.get("harga_perkiraan", item.get("harga_satuan", 0)))
        qty    = int(item.get("qty", 1))
        sat    = item.get("satuan", "Pcs")
        jumlah = int(item.get("jumlah", harga * qty))
        tbl_data.append([
            str(i + 1),
            item.get("nama", ""),
            f"{harga:,}",
            f"( {qty} {sat} )",
            f"{jumlah:,}",
        ])
    tbl_data.append(["", "", "", "Sub Total", f"Rp {total:,}"])

    col_w = [0.95*cm, 8.21*cm, 3.34*cm, 3.23*cm, 3.06*cm]
    t = Table(tbl_data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  DARK),
        ("TEXTCOLOR",     (0,0),  (-1,0),  colors.white),
        ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),  (-1,0),  8),
        ("ALIGN",         (0,0),  (-1,0),  "CENTER"),
        ("ALIGN",         (2,1),  (2,-1),  "RIGHT"),
        ("ALIGN",         (4,1),  (4,-1),  "RIGHT"),
        ("ALIGN",         (3,-1), (3,-1),  "RIGHT"),
        ("ALIGN",         (0,1),  (0,-1),  "CENTER"),
        ("ROWBACKGROUNDS",(0,1),  (-1,-2), [colors.HexColor("#F5F5F5"), colors.white]),
        ("FONTNAME",      (0,-1), (-1,-1), "Helvetica-Bold"),
        ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#E8E8E8")),
        ("GRID",          (0,0),  (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
        ("FONTSIZE",      (0,1),  (-1,-1), 8),
        ("VALIGN",        (0,0),  (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),  (-1,-1), 4),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3*cm))

    # ── Terbilang ──
    story.append(Paragraph(
        f"<i>Terbilang : {_terbilang(total)} Rupiah,--</i>",
        ParagraphStyle("terb", fontSize=8, spaceAfter=6)
    ))

    if po.get("catatan"):
        story.append(Paragraph(
            f"<b>Catatan:</b> {po['catatan']}",
            ParagraphStyle("note", fontSize=8, spaceAfter=8)
        ))

    # ── TTD ──
    story.append(Spacer(1, 1*cm))
    ttd_data = [
        ["", Paragraph("Hormat kami,", ParagraphStyle("hk", fontSize=9, alignment=TA_CENTER))],
        ["", Spacer(1, 2*cm)],
        ["", Paragraph("<b><u>Finance</u></b>",
                        ParagraphStyle("fn", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER))],
        ["", Paragraph("PT Holomoc Indonesia",
                        ParagraphStyle("co2", fontSize=8, textColor=GREY, alignment=TA_CENTER))],
    ]
    ttd_t = Table(ttd_data, colWidths=[10*cm, 7*cm])
    ttd_t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(ttd_t)

    doc.build(story)
    return str(path)

