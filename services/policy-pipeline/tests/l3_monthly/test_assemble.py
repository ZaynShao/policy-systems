"""MA8 组稿:content(v2) → final.md → docx,并写 last_run.json。

final.md 不是随便的 markdown——它是**渲染器的输入契约**:
`render_docx_clone.classify_line` 靠行首形状决定这一行排成标题、小节、条目还是正文。
所以这里的测试都拿渲染器自己的分类器验,而不是看字符串长得像不像。
"""
import json
import os
import zipfile

import pytest

from scripts.l3_monthly import assemble
from scripts.l3_render import render_docx_clone as rdc


PROFILE = {"schema_version": 1, "status": "active", "profile_id": "t2026",
           "effective_from": "2026-08-31",
           "businesses": [{"id": "fuel", "zh": "加油"}, {"id": "charging", "zh": "充电"},
                          {"id": "power", "zh": "电力"}]}


def _content(**over):
    base = {
        "schema": "monthly.v2", "month": "2026-07", "narrative": "本月定调",
        "overview": "本月政策密度抬升。",
        "businessTakes": [{"business": "充电", "text": "备案口径要摸清。"}],
        "quickTable": [{"no": "01", "level": "国家级", "score": "5分",
                        "title": "甲文件", "issuer": "国家发展改革委",
                        "date": "2026-07-23", "doc_no": "发改能源〔2026〕1号"}],
        "details": [{"no": "01", "policyId": "P_A", "title": "甲文件",
                     "info": "发文机关:国家发展改革委。", "reading": "改了备案口径。",
                     "focus": "第三条要求年底前完成。",
                     "advice": [{"business": "充电", "tag": "B 研究/跟进",
                                 "text": "先摸清备案口径。"}]}],
        "localRoundup": "江苏等省本月集中调整。",
        "appendix": "国务院专题学习释放信号。",
        "caveats": [],
    }
    base.update(over)
    return base


def _kinds(md):
    """按渲染器自己的规则给每一行归类。"""
    lines = [l for l in md.split("\n") if l.strip()]
    first = md.split("\n").index(lines[0])
    out = []
    for i, line in enumerate(lines):
        if rdc.is_table_row(line):
            out.append((line, "table"))
        else:
            out.append((line, rdc.classify_line(line, is_first=(i == 0))))
    return out


# ── ① 渲染契约 ─────────────────────────────────────────────────
def test_title_uses_the_spaced_official_head():
    """D 门 D-HEAD:文头须用官文字距式,否则整期一开头就是一条 MAJOR。"""
    md = assemble.build_final_md(_content(), PROFILE)
    head = md.split("\n")[0]
    assert "能 源 政 策 月 刊" in head
    from scripts.l3_monthly import gates
    assert not [v for v in gates.check_style(md) if v["rule"] == "D-HEAD"]


def test_section_headings_classify_as_h2():
    kinds = dict(_kinds(assemble.build_final_md(_content(), PROFILE)))
    for line, kind in kinds.items():
        if line.startswith(("一、", "二、", "三、", "四、", "附录")):
            assert kind == "h2", f"{line!r} 应排成小节标题"


def test_detail_title_classifies_as_h3_and_labels_as_h4():
    kinds = _kinds(assemble.build_final_md(_content(), PROFILE))
    assert any(k == "h3" and "甲文件" in l for l, k in kinds)
    for label in ("【政策信息】", "【政策解读】", "【重点关注内容】", "【决策建议】"):
        assert any(k == "h4" and l.strip() == label for l, k in kinds)


def test_quick_table_rows_are_table_rows():
    kinds = _kinds(assemble.build_final_md(_content(), PROFILE))
    rows = [l for l, k in kinds if k == "table"]
    assert len(rows) == 2, "表头 + 一行"
    assert "发改能源〔2026〕1号" in rows[1]


def test_business_lines_classify_as_bullet():
    """速判与决策建议都要排成缩进条目,不能掉回正文首行缩进。"""
    kinds = _kinds(assemble.build_final_md(_content(), PROFILE))
    bullets = [l for l, k in kinds if k == "bullet"]
    assert any(l.startswith("充电业务") and "备案口径要摸清" in l for l in bullets)
    assert any(l.startswith("充电业务") and "B 研究/跟进" in l for l in bullets)


def test_every_profile_business_is_recognised_by_the_renderer():
    """渲染器的条目判定里写死了业务线名。口径一改而它没改,速判就会静静掉回正文。

    这条不改渲染器(它对已交付终稿逐字节校验过),只让走散变响。
    """
    for biz in PROFILE["businesses"]:
        line = f"{biz['zh']}业务:某条建议。"
        assert rdc.classify_line(line) == "bullet", (
            f"渲染器不认「{biz['zh']}业务」——画像与 render_docx_clone.classify_line 已走散")


# ── ② 空段不留空标题 ───────────────────────────────────────────
def test_empty_sections_are_omitted():
    md = assemble.build_final_md(_content(localRoundup="", appendix="",
                                          quickTable=[]), PROFILE)
    assert "地方政策综述" not in md and "附录" not in md and "政策速览" not in md


# ── ③ 容错提示随稿走 ───────────────────────────────────────────
def test_caveat_note_appears_only_when_there_are_caveats():
    clean = assemble.build_final_md(_content(), PROFILE)
    assert "敬请谅解" not in clean
    dirty = assemble.build_final_md(
        _content(caveats=[{"gate": "F", "location": "details[01].reading",
                           "note": "某数字未能回指原文"}]), PROFILE)
    assert "敬请谅解" in dirty and "details[01].reading" in dirty


# ── ④ 落盘 ─────────────────────────────────────────────────────
def _fake_template(tmp_path):
    d = tmp_path / "tpl"
    os.makedirs(str(d / "word"))
    (d / "[Content_Types].xml").write_text("<Types/>", encoding="utf-8")
    (d / "word" / "document.xml").write_text(
        '<w:document xmlns:w="x"><w:body><w:p/><w:sectPr/></w:body></w:document>',
        encoding="utf-8")
    return str(d)


def test_write_outputs_without_template_still_produces_md_and_last_run(tmp_path):
    out = str(tmp_path / "o")
    res = assemble.write_outputs(_content(), PROFILE, out)
    assert os.path.exists(os.path.join(out, "final.md"))
    assert res["docx"] is None
    lr = json.load(open(os.path.join(out, "last_run.json"), encoding="utf-8"))
    assert lr["month"] == "2026-07" and lr["profile_id"] == "t2026"
    assert lr["counts"]["details"] == 1 and lr["counts"]["caveats"] == 0


def test_write_outputs_renders_docx_when_template_given(tmp_path):
    out = str(tmp_path / "o")
    res = assemble.write_outputs(_content(), PROFILE, out,
                                 template_dir=_fake_template(tmp_path))
    assert res["docx"] and os.path.exists(res["docx"])
    with zipfile.ZipFile(res["docx"]) as z:
        assert z.namelist()[0] == "[Content_Types].xml"
        assert "能 源 政 策 月 刊" in z.read("word/document.xml").decode("utf-8")


def test_last_run_records_provenance_for_traceability(tmp_path):
    c = _content(provenance={"writerModel": "deepseek-v4-pro", "auditRounds": 2})
    res = assemble.write_outputs(c, PROFILE, str(tmp_path / "o"))
    lr = json.load(open(res["last_run"], encoding="utf-8"))
    assert lr["writer_model"] == "deepseek-v4-pro" and lr["audit_rounds"] == 2
