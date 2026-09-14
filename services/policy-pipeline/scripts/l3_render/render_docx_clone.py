"""用上期终稿 docx 作模板,克隆其样式/字体/sectPr/文头分隔线,只把正文换成 final.md。

产出与上期公文排版一致(仿宋_GB2312 16pt 正文/黑体标题/方正小标宋简体橙文头/行距560/首行缩进2字)。
**不用 docx-js 从零建**:公文版式的细节(文头橙线、sectPr、样式 id)从零复现代价极高且极易走样。

模块级不读 sys.argv——MA8 组稿要程序调用 render();CLI 入口在 main()。
"""
import re, sys, os, shutil, tempfile, zipfile

def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# —— 段落模板(pPr + run rPr,均取自4月真实运行属性)——
def p_title(t):
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="aff1"/><w:tblW w:w="0" w:type="auto"/>'
            '<w:tblBorders><w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
            '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/></w:tblBorders>'
            '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
            '<w:tblGrid><w:gridCol w:w="8856"/></w:tblGrid>'
            '<w:tr><w:tc><w:tcPr><w:tcW w:w="8856" w:type="dxa"/>'
            '<w:tcBorders><w:bottom w:val="single" w:sz="24" w:space="0" w:color="FF7733"/></w:tcBorders></w:tcPr>'
            '<w:p><w:pPr><w:pStyle w:val="1"/><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="方正小标宋简体" w:eastAsia="方正小标宋简体" w:hAnsi="方正小标宋简体"/>'
            '<w:color w:val="FF7733"/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')

def p_h2(t):  # 一、二、三、附录 : 黑体16pt
    return ('<w:p><w:pPr><w:pStyle w:val="21"/><w:spacing w:line="560" w:lineRule="exact"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="黑体" w:eastAsia="黑体" w:hAnsi="黑体"/><w:b w:val="0"/><w:bCs w:val="0"/>'
            '<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>')

def p_h3(t):  # (一)(二)/国家级 : 仿宋14pt
    return ('<w:p><w:pPr><w:pStyle w:val="31"/><w:spacing w:line="560" w:lineRule="exact"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:eastAsia="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/>'
            '<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="28"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>')

def p_h4(t):  # 【政策信息】 : 仿宋16pt
    return ('<w:p><w:pPr><w:pStyle w:val="4"/><w:spacing w:line="560" w:lineRule="exact"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:eastAsia="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/><w:i w:val="0"/><w:iCs w:val="0"/>'
            '<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>')

def p_bullet(t):  # 业务条目/决策建议 : 仿宋16pt 缩进
    return ('<w:p><w:pPr><w:pStyle w:val="a0"/><w:spacing w:line="560" w:lineRule="exact"/><w:ind w:left="283"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:eastAsia="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/>'
            '<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>')

def p_body(t):  # 正文 : 仿宋16pt 首行缩进2字
    return ('<w:p><w:pPr><w:spacing w:line="560" w:lineRule="exact"/><w:ind w:firstLineChars="200" w:firstLine="640"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:eastAsia="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/>'
            '<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p>')

def cell(t, w, bold=False):
    b = '<w:b/>' if bold else ''
    return ('<w:tc><w:tcPr>'
            f'<w:tcW w:w="{w}" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>'
            '<w:p><w:pPr><w:spacing w:after="0" w:line="300" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
            '<w:r><w:rPr><w:rFonts w:ascii="仿宋_GB2312" w:eastAsia="仿宋_GB2312" w:hAnsi="仿宋_GB2312"/>'
            f'<w:color w:val="000000" w:themeColor="text1"/><w:sz w:val="21"/>{b}</w:rPr>'
            f'<w:t xml:space="preserve">{esc(t)}</w:t></w:r></w:p></w:tc>')

def table(rows):
    ncol = len(rows[0])
    widths = {4: [1101, 1417, 3686, 3685], 5: [950, 1150, 2750, 2350, 2689]}.get(
        ncol, [9889 // ncol] * ncol)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    trs = []
    for ri, r in enumerate(rows):
        cells = "".join(cell(c, widths[ci], bold=(ri == 0)) for ci, c in enumerate(r))
        trs.append(f"<w:tr>{cells}</w:tr>")
    return ('<w:tbl><w:tblPr><w:tblStyle w:val="-11"/><w:tblW w:w="9889" w:type="dxa"/>'
            '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
            f'<w:tblGrid>{grid}</w:tblGrid>{"".join(trs)}</w:tbl>')

BLOCK_BUILDERS = {"title": p_title, "h2": p_h2, "h3": p_h3,
                  "h4": p_h4, "bullet": p_bullet, "body": p_body}


def is_table_row(s):
    return " | " in s


def classify_line(s, is_first=False):
    """把一行 markdown 归到公文版式的段落类型。表格行由调用方先行拦截。"""
    s = s.strip()
    if is_first:
        return "title"
    if re.match(r"^[一二三四五六七八九十]+、", s) or s.startswith("附录"):
        return "h2"
    if re.match(r"^[\(（][一二三四五六七八九十]+[\)）]", s):
        return "h3"
    if re.match(r"^【.+】", s):
        return "h4"
    if re.match(r"^(加油业务|充电业务|电力业务)", s):
        return "bullet"
    return "body"


def md_to_xml(md_text):
    """final.md → document.xml 的 body 内容片段。"""
    lines = md_text.split("\n")
    first = next(i for i, l in enumerate(lines) if l.strip())
    out, i = [], 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "":
            i += 1
            continue
        if is_table_row(s):
            block = []
            while i < len(lines) and lines[i].strip() and is_table_row(lines[i].strip()):
                block.append([c.strip() for c in lines[i].strip().split(" | ")])
                i += 1
            out.append(table(block))
            continue
        out.append(BLOCK_BUILDERS[classify_line(s, is_first=(i == first))](s))
        i += 1
    return "".join(out)


def render(template_dir, md_path, out_path):
    """克隆 template_dir(已解包的上期 docx)的版式,正文换成 md_path,写出 out_path。

    构建目录走 tempfile:同月重跑与 MA7 返修会并发调用,写死路径会互相覆盖。
    """
    content = md_to_xml(open(md_path, encoding="utf-8").read())

    # —— 文本手术:保留模板 document.xml 的根命名空间 + sectPr ——
    doc = open(os.path.join(template_dir, "word/document.xml"), encoding="utf-8").read()
    prefix = doc[: doc.index("<w:body>") + len("<w:body>")]
    suffix = doc[doc.index("<w:sectPr"):]   # <w:sectPr ...>…</w:sectPr></w:body></w:document>
    new_doc = prefix + content + suffix

    build = tempfile.mkdtemp(prefix="l3_docx_")
    try:
        shutil.rmtree(build)                 # copytree 要求目标不存在
        shutil.copytree(template_dir, build)
        open(os.path.join(build, "word/document.xml"), "w", encoding="utf-8").write(new_doc)
        if os.path.exists(out_path):
            os.remove(out_path)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            order = ["[Content_Types].xml"]  # 必须是包内第一个条目
            for root, _, files in os.walk(build):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), build).replace(os.sep, "/")
                    if rel not in order:
                        order.append(rel)
            for rel in order:
                full = os.path.join(build, rel)
                if os.path.exists(full):
                    zf.write(full, rel)
    finally:
        shutil.rmtree(build, ignore_errors=True)
    return {"bytes": os.path.getsize(out_path),
            "tables": content.count("<w:tbl>"), "paras": content.count("<w:p>")}


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 3:
        print("用法: render_docx_clone.py <上期docx解包目录> <final.md> <输出.docx>", file=sys.stderr)
        return 2
    st = render(a[0], a[1], a[2])
    print(f"wrote {a[2]} {st['bytes']} bytes; {st['tables']} tables, {st['paras']} paras")
    return 0


if __name__ == "__main__":
    sys.exit(main())
