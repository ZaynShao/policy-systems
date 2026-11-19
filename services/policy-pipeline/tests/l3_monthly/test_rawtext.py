"""喂给 MA2 的正文摘录。

关键约束:**文头在开头、落款在结尾**,而 MA2 判国家/地方与真实发文日全靠这两处。
只截"正文前 N 字"会把落款截掉,模型就只能退回去信 frontmatter——那正是要修的病。
所以摘录必须头尾都取。
"""
from scripts.l3_monthly import rawtext as R

MD = (
    "---\nid: P_A\ntitle: 甲\ndate: '2026-07-01'\n---\n"
    "## 政策原文\n"
    "国家发展改革委 国家能源局\n"
    + "中间正文" * 400 + "\n"
    "国家发展改革委\n2026年7月23日\n"
)


def test_body_of_strips_frontmatter():
    b = R.body_of(MD)
    assert not b.startswith("---") and "国家发展改革委" in b


def test_excerpt_keeps_head_and_tail():
    ex = R.excerpt(R.body_of(MD), head_chars=200, tail_chars=120)
    assert "国家发展改革委 国家能源局" in ex, "文头(发文机关)必须在"
    assert "2026年7月23日" in ex, "落款日期必须在——只取前 N 字会把它截掉"


def test_excerpt_marks_elision():
    ex = R.excerpt(R.body_of(MD), head_chars=200, tail_chars=120)
    assert "略" in ex or "…" in ex, "中间省略要标出来,免得模型把两段读成连续正文"


def test_excerpt_returns_whole_body_when_short():
    short = "很短的正文"
    assert R.excerpt(short, head_chars=200, tail_chars=120) == short


def test_excerpt_never_exceeds_budget():
    ex = R.excerpt(R.body_of(MD), head_chars=200, tail_chars=120)
    assert len(ex) <= 200 + 120 + 20


def test_excerpt_strips_chrome_before_budgeting():
    """判定窗口只有 2100 字符,最脏的文件七成是 URL——不先清就是拿几百字判一篇。"""
    body = "![](http://a.gov.cn/1.jpg)" * 200 + "第一条 本办法适用于充电设施。" + "尾" * 50
    ex = R.excerpt(body, head_chars=200, tail_chars=100)
    assert "http" not in ex
    assert "第一条 本办法适用于充电设施。" in ex
