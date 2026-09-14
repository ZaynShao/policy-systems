"""L3 迁入 monorepo 后必须成立的三件事。

这三条不是风格洁癖,是 PM3(cron 每月自动跑)的前置条件:
① 导入方式必须与仓内一致,否则容器里跑不起来;
② 渲染器必须能被程序调用且并发安全,否则同月重跑/返修会互相踩;
③ slate 必须能被结构校验,否则 MA3 出的坏 slate 要到 MA4 装包才炸。
"""
import importlib
import sys

import pytest


# ── ① build_month_pack 的导入方式 ──────────────────────────────
def test_build_month_pack_imports_without_syspath_hack():
    """不得靠 sys.path.insert 自举:容器内工作目录不是 scripts/ 的父目录。"""
    before = list(sys.path)
    importlib.import_module("scripts.l3_render.build_month_pack")
    assert sys.path == before, "模块导入时改了 sys.path(应改用 scripts.* 绝对导入)"


# ── ② render_docx_clone 可程序调用 + 并发安全 ──────────────────
def test_render_docx_clone_importable_without_argv():
    """模块级不得读 sys.argv:一 import 就崩的模块没法被 MA8 调用。"""
    importlib.import_module("scripts.l3_render.render_docx_clone")


def test_render_docx_clone_exposes_render_function():
    m = importlib.import_module("scripts.l3_render.render_docx_clone")
    assert hasattr(m, "render"), "需暴露 render(template_dir, md_path, out_path)"


def test_render_docx_clone_has_no_hardcoded_build_dir():
    """构建目录写死 /tmp/jun_build 会让并发/重跑互相覆盖。"""
    import inspect
    m = importlib.import_module("scripts.l3_render.render_docx_clone")
    src = inspect.getsource(m)
    assert "/tmp/jun_build" not in src, "构建目录仍写死,应改用 tempfile"


@pytest.mark.parametrize("line,kind", [
    ("能源政策月刊", "title"),
    ("一、概述", "h2"),
    ("附录:本月战略基调", "h2"),
    ("(一)国家级", "h3"),
    ("（二）地方", "h3"),
    ("【政策信息】", "h4"),
    ("充电业务:建议跟进", "bullet"),
    ("本月共收录政策 12 件。", "body"),
])
def test_classify_line_covers_all_block_kinds(line, kind):
    """版式分类是纯逻辑,必须可单测——它决定公文排版对不对。"""
    m = importlib.import_module("scripts.l3_render.render_docx_clone")
    assert m.classify_line(line, is_first=(kind == "title")) == kind


# ── ③ slate 结构校验 ───────────────────────────────────────────
def _slate(**over):
    base = {
        "month": "2026-07",
        "narrative": "本月定调",
        "sections": {
            "national_detail": [
                {"policy_id": "P_A", "title_hint": "甲", "score": "5分",
                 "rank": 1, "why": "旗舰", "dq": ""}
            ],
            "local_detail": [], "roundup": [], "appendix": [],
        },
    }
    base.update(over)
    return base


def test_validate_slate_accepts_wellformed():
    from scripts.l3_render import slate_schema as ss
    assert ss.validate_slate(_slate()) == []


def test_validate_slate_rejects_bad_month():
    from scripts.l3_render import slate_schema as ss
    errs = ss.validate_slate(_slate(month="2026/07"))
    assert any("month" in e for e in errs)


def test_validate_slate_rejects_unknown_section():
    from scripts.l3_render import slate_schema as ss
    s = _slate()
    s["sections"]["technology"] = []
    errs = ss.validate_slate(s)
    assert any("technology" in e for e in errs)


def test_validate_slate_rejects_item_missing_policy_id():
    from scripts.l3_render import slate_schema as ss
    s = _slate()
    del s["sections"]["national_detail"][0]["policy_id"]
    errs = ss.validate_slate(s)
    assert any("policy_id" in e for e in errs)


def test_validate_slate_rejects_duplicate_policy_id_across_sections():
    """同一篇同时进详情与速览 = 选目重复计数,MA1 去重没做干净的信号。"""
    from scripts.l3_render import slate_schema as ss
    s = _slate()
    s["sections"]["roundup"] = [
        {"policy_id": "P_A", "title_hint": "甲", "score": "3分",
         "rank": 1, "why": "重复", "dq": ""}
    ]
    errs = ss.validate_slate(s)
    assert any("P_A" in e for e in errs)
