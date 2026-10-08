"""按 5 月刊版式渲染 docx(替代缺失的 render_docx_clone.py)。

版式取自【2026年5月】滴滴能源政策月刊.docx:
封面 48pt 粗体刊名 + 英文名 + 年月 + 编制单位/发布日期
章节头用 1x2 表格:序号格橙底(FF6600)白字 + 标题格浅橙底(FFF3E0)深色字
正文 14pt(四号)、行距 1.5、首行缩进 2 字;标题 14pt 加粗
【前沿技术动态】及之后不渲染。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Cm

FONT = "Times New Roman Regular"
CJK = "宋体"   # 5 月刊基准用宋体;4 月公文模板才是仿宋_GB2312,勿混
ORANGE = "FF6600"
LIGHT = "FFF3E0"
GREY = RGBColor(0x88, 0x88, 0x88)
LABEL = RGBColor(0xAA, 0xAA, 0xAA)
HAIR = "E0E0E0"
DARK = RGBColor(0x1A, 0x1A, 0x2E)


def set_run(r, *, size=14, bold=False, color=None):
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = bold
    if color is not None:
        r.font.color.rgb = color
    rpr = r._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    rf.set(qn("w:eastAsia"), CJK)
    rf.set(qn("w:ascii"), FONT)
    rf.set(qn("w:hAnsi"), FONT)


def shade(cell, hexfill):
    tcpr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hexfill)
    tcpr.append(sh)


def set_tcw(cell, dxa):
    """按 dxa 精确设定单元格宽(章节头橙块宽度靠这个,不能只设 cell.width)。"""
    tcpr = cell._tc.get_or_add_tcPr()
    old = tcpr.find(qn("w:tcW"))
    if old is not None:
        tcpr.remove(old)
    w = OxmlElement("w:tcW")
    w.set(qn("w:w"), str(dxa))
    w.set(qn("w:type"), "dxa")
    tcpr.insert(0, w)


def para_shade(p, hexfill):
    ppr = p._p.get_or_add_pPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hexfill)
    ppr.append(sh)


def left_bar(p, *, sz=24, space=8, color=ORANGE):
    """段前橙色竖标(w:pBdr/w:left)。"""
    ppr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), str(sz))
    left.set(qn("w:space"), str(space))
    left.set(qn("w:color"), color)
    bdr.append(left)
    ppr.append(bdr)


def para(doc, text="", *, size=14, bold=False, indent=True, spacing=1.5,
         align=None, color=None, style=None):
    p = doc.add_paragraph(style=style)
    pf = p.paragraph_format
    pf.line_spacing = spacing
    pf.space_after = Pt(4)
    if indent:
        pf.first_line_indent = Cm(0.99)  # 2 字
    if align is not None:
        p.alignment = align
    if text:
        r = p.add_run(text)
        set_run(r, size=size, bold=bold, color=color)
    return p


def rich_para(doc, text, **kw):
    """处理 **粗体** 片段。"""
    p = para(doc, "", **kw)
    for seg in re.split(r"(\*\*[^*]+\*\*)", text):
        if not seg:
            continue
        b = seg.startswith("**") and seg.endswith("**")
        r = p.add_run(seg[2:-2] if b else seg)
        set_run(r, size=kw.get("size", 14), bold=b or kw.get("bold", False))
    return p


def chapter(doc, num, title):
    tb = doc.add_table(rows=1, cols=2)
    tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    tb.autofit = False
    # 5 月刊实测:总宽 9639dxa,橙块 800dxa,标题格 8839dxa
    tblpr = tb._tbl.tblPr
    old = tblpr.find(qn("w:tblW"))
    if old is not None:
        tblpr.remove(old)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), "9639")
    tw.set(qn("w:type"), "dxa")
    tblpr.append(tw)
    grid = tb._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for gc, w in zip(grid.findall(qn("w:gridCol")), ("800", "8839")):
            gc.set(qn("w:w"), w)
    c0, c1 = tb.rows[0].cells
    set_tcw(c0, 800)
    set_tcw(c1, 8839)
    shade(c0, ORANGE)
    shade(c1, LIGHT)
    for cell, txt, col in ((c0, num, RGBColor(0xFF, 0xFF, 0xFF)), (c1, title, DARK)):
        p = cell.paragraphs[0]
        p.paragraph_format.line_spacing = 1.2
        if cell is c0:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(txt)
        set_run(r, size=14, bold=True, color=col)
    doc.add_paragraph()


# 5 月刊实测列宽(dxa):4 列=国家级速览,5 列=地方速览
COLW = {4: (841, 1417, 3946, 3425), 5: (950, 1150, 2750, 2350, 2429)}


def md_table(doc, rows):
    tb = doc.add_table(rows=len(rows), cols=len(rows[0]))
    try:
        tb.style = "Light Grid Accent 1"
    except KeyError:
        tb.style = "Table Grid"
    widths = COLW.get(len(rows[0]))
    if widths:
        grid = tb._tbl.find(qn("w:tblGrid"))
        if grid is not None:
            for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
                gc.set(qn("w:w"), str(w))
        for row in tb.rows:
            for cell, w in zip(row.cells, widths):
                set_tcw(cell, w)
    tb.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = tb.rows[i].cells[j]
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.15
            r = p.add_run(val)
            set_run(r, size=10.5, bold=(i == 0))
            if i == 0:
                shade(cell, LIGHT)
            elif i % 2 == 0:
                shade(cell, "D3DFEE")   # 5 月刊的隔行底纹
    doc.add_paragraph()


def hairline(p, where):
    """封面信息块的上下细线(#E0E0E0)。"""
    ppr = p._p.get_or_add_pPr()
    bdr = ppr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        ppr.append(bdr)
    e = OxmlElement(f"w:{where}")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), "4")
    e.set(qn("w:space"), "6")
    e.set(qn("w:color"), HAIR)
    bdr.append(e)


def cover(doc, ym_cn, pub):
    for _ in range(8):
        doc.add_paragraph()
    for txt, sz, bold, col in (("能源政策月刊", 48, True, DARK),
                               ("Energy Policy Monthly", 20, False, RGBColor(0xFF, 0x66, 0x00)),
                               (ym_cn, 14, False, GREY)):
        para(doc, txt, size=sz, bold=bold, indent=False, color=col,
             align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.2)
    doc.add_paragraph()
    rows = (("编制单位", "滴滴能源安全生态中心"), ("发布日期", pub))
    for i, (label, val) in enumerate(rows):
        p = para(doc, "", size=12, indent=False, align=WD_ALIGN_PARAGRAPH.CENTER)
        r1 = p.add_run(label + "　")
        set_run(r1, size=12, color=LABEL)
        r2 = p.add_run(val)
        set_run(r2, size=12, color=RGBColor(0x33, 0x33, 0x33))
        if i == 0:
            hairline(p, "top")
        if i == len(rows) - 1:
            hairline(p, "bottom")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", type=Path, required=True, help="定稿 markdown")
    ap.add_argument("--out", type=Path, required=True, help="输出 .docx")
    ap.add_argument("--ym", required=True, help="封面年月,如 2026年7月")
    ap.add_argument("--pub", required=True, help="发布日期,如 2026年8月6日")
    a = ap.parse_args()
    md = a.md.read_text(encoding="utf-8")

    doc = docx.Document()
    sec = doc.sections[0]
    # 5 月刊实测:A4 + 四边各 2cm,正文宽正好 17cm=9639dxa,与章节头表宽严格对齐。
    # python-docx 默认 Letter,必须显式设 A4,否则表格溢出、橙块比例失真。
    sec.page_width = Cm(21)
    sec.page_height = Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2)
    sec.left_margin = sec.right_margin = Cm(2)
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(14)

    cover(doc, a.ym, a.pub)
    doc.add_page_break()

    lines = md.splitlines()
    i = 0
    tbuf = []
    while i < len(lines):
        ln = lines[i].rstrip()
        s = ln.strip()

        # 表格聚合
        if s.startswith("|"):
            tbuf.append(s)
            i += 1
            continue
        if tbuf:
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in tbuf
                    if not re.fullmatch(r"\|[\s|:-]+\|", r)]
            md_table(doc, rows)
            tbuf = []

        if not s:
            i += 1
            continue
        if s.startswith("# "):
            i += 1
            continue
        if s.startswith("## "):
            title = s[3:].strip()
            m = re.match(r"^([一二三四五六七八九十]+)、(.+)$", title)
            if m:
                chapter(doc, m.group(1), m.group(2))
            else:  # 附录
                chapter(doc, "附", title.replace("附录：", "").replace("附录", "").strip() or "附录")
            i += 1
            continue
        if s.startswith("### "):
            txt = s[4:].strip()
            if txt in ("国家级", "地方"):  # 速览表小标题,不套政策标题样式
                para(doc, txt, bold=True, indent=False)
                i += 1
                continue
            p = para(doc, "", bold=True, indent=False)
            pf = p.paragraph_format
            pf.space_before = Pt(10)
            pf.space_after = Pt(5)
            r = p.add_run(txt)
            set_run(r, size=14, bold=True, color=RGBColor(0xCC, 0x44, 0x00))
            para_shade(p, LIGHT)          # 整行浅橙底
            left_bar(p, sz=24, space=8)   # 段前橙色粗竖标
            i += 1
            continue
        if s.startswith("#### "):
            p = para(doc, "", bold=True, indent=False)
            pf = p.paragraph_format
            pf.space_before = Pt(8)
            pf.space_after = Pt(4)
            pf.left_indent = Cm(0.21)
            r = p.add_run(s[5:].strip())
            set_run(r, size=14, bold=True, color=DARK)
            left_bar(p, sz=16, space=6)   # 段前橙色细竖标
            i += 1
            continue
        if s.startswith("- "):
            rich_para(doc, s[2:], indent=False, style="List Bullet")
            i += 1
            continue
        if re.match(r"^\d+\. ", s):
            rich_para(doc, s, indent=True)
            i += 1
            continue
        rich_para(doc, s)
        i += 1

    if tbuf:
        rows = [[c.strip() for c in r.strip("|").split("|")] for r in tbuf
                if not re.fullmatch(r"\|[\s|:-]+\|", r)]
        md_table(doc, rows)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(a.out)
    print(f"已生成: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
