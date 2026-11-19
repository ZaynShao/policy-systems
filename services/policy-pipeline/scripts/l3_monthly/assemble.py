"""MA8 组稿:content(monthly.v2) → final.md → docx,并写 last_run.json。

`final.md` 不是随便的 markdown,它是**渲染器的输入契约**:
`render_docx_clone.classify_line` 靠行首形状决定这一行排成文头、小节、条目还是正文。
组稿这一步的活就是把结构化的 content 摆成那个形状——摆错了不会报错,
只会排出一份版式塌掉的公文。故测试全部拿渲染器自己的分类器验。

渲染器里业务线名是写死的(`加油业务|充电业务|电力业务`)。那份代码对已交付终稿
做过逐字节校验,不动它;改为加一条测试:画像里的业务线若有一条渲染器不认,
测试就红——让走散变响,而不是让速判静静掉回正文。
"""
import datetime
import json
import os

from scripts.l3_monthly import quick_table
from scripts.l3_render import render_docx_clone

CN_DIGITS = "〇一二三四五六七八九"
LABELS = (("info", "【政策信息】"), ("reading", "【政策解读】"),
          ("focus", "【重点关注内容】"))
CAVEAT_NOTE = ("说明:本期部分内容由 AI 生成,下列段落可能不够符合要求,敬请谅解:")


def _cn(n):
    """1→一,10→十,11→十一,20→二十。详情条数有配额,到二十足够。"""
    if n < 10:
        return CN_DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + CN_DIGITS[n - 10]
    return CN_DIGITS[n // 10] + "十" + (CN_DIGITS[n % 10] if n % 10 else "")


def _month_title(month):
    """D 门要求文头用官文字距式,否则整期一开头就是一条 MAJOR。"""
    year, mon = (month or "").split("-")[:2]
    return f"能 源 政 策 月 刊 · {year} 年 {int(mon)} 月"


def build_final_md(content, profile=None):
    """把 content 摆成渲染器认得的行形状。空段整节不出,不留空标题。"""
    lines = [_month_title(content.get("month", ""))]
    idx = 0

    overview = str(content.get("overview") or "").strip()
    takes = content.get("businessTakes") or []
    if overview or takes:
        idx += 1
        lines += ["", f"{_cn(idx)}、概述"]
        if overview:
            lines.append(overview)
        for take in takes:
            lines.append(f"{take.get('business','')}业务:{take.get('text','')}")

    rows = content.get("quickTable") or []
    if rows:
        idx += 1
        lines += ["", f"{_cn(idx)}、政策速览", quick_table.render_table(rows)]

    details = content.get("details") or []
    if details:
        idx += 1
        lines += ["", f"{_cn(idx)}、政策详情"]
        for i, det in enumerate(details, 1):
            lines += ["", f"({_cn(i)}){det.get('title','')}"]
            for key, label in LABELS:
                text = str(det.get(key) or "").strip()
                if text:
                    lines += [label, text]
            advice = det.get("advice") or []
            if advice:
                lines.append("【决策建议】")
                for a in advice:
                    lines.append(f"{a.get('business','')}业务"
                                 f"[{a.get('tag','')}]:{a.get('text','')}")

    roundup = str(content.get("localRoundup") or "").strip()
    if roundup:
        idx += 1
        lines += ["", f"{_cn(idx)}、地方政策综述", roundup]

    appendix = str(content.get("appendix") or "").strip()
    if appendix:
        lines += ["", "附录:国家级讲话与会议信号", appendix]

    uncovered = str(content.get("uncovered") or "").strip()
    if uncovered:
        lines += ["", "附录:已知未覆盖", uncovered]

    caveats = content.get("caveats") or []
    if caveats:
        # 只列位置不带原文引证:引证里可能带机器 token,而这一行在两道门之后才拼上
        where = "、".join(dict.fromkeys(str(c.get("location") or "") for c in caveats))
        lines += ["", CAVEAT_NOTE + where + "。"]
    return "\n".join(lines)


def write_outputs(content, profile, out_dir, template_dir=None, docx_name=None):
    """落 final.md(+ docx)与 last_run.json。返回各产物路径。

    没给模板就不出 docx——公文版式靠克隆上期成品,凭空生成必然走样,
    宁可只交 markdown 让人看见缺了什么。
    """
    os.makedirs(out_dir, exist_ok=True)
    md = build_final_md(content, profile)
    md_path = os.path.join(out_dir, "final.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    docx_path = None
    if template_dir:
        docx_path = os.path.join(
            out_dir, docx_name or f"能源政策月刊-{content.get('month','')}.docx")
        render_docx_clone.render(template_dir, md_path, docx_path)

    prov = content.get("provenance") or {}
    caveats = content.get("caveats") or []
    last_run = {
        "month": content.get("month", ""),
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat(timespec="seconds"),
        "profile_id": (profile or {}).get("profile_id", ""),
        "profile_effective_from": str((profile or {}).get("effective_from", "")),
        "writer_model": prov.get("writerModel", ""),
        "audit_rounds": prov.get("auditRounds", 0),
        "counts": {
            "details": len(content.get("details") or []),
            "quick_table": len(content.get("quickTable") or []),
            "business_takes": len(content.get("businessTakes") or []),
            "caveats": len(caveats),
        },
        "caveat_locations": [c.get("location") for c in caveats],
        "outputs": {"final_md": md_path, "docx": docx_path},
    }
    lr_path = os.path.join(out_dir, "last_run.json")
    with open(lr_path, "w", encoding="utf-8") as f:
        json.dump(last_run, f, ensure_ascii=False, indent=2)
    return {"final_md": md_path, "docx": docx_path, "last_run": lr_path}
