"""喂给 MA2 的正文摘录。

**文头在开头、落款在结尾**,而 MA2 判国家/地方与真实发文日全靠这两处。只截"正文前 N 字"
会把落款截掉,模型就只能退回去信 frontmatter——那正是这条产线要修的病。所以头尾都取。
"""
from scripts.l3_render.pack_lib import ELISION, body_of  # noqa: F401  (转出给 MA2 用)
from scripts.l3_render import pack_lib as pl


def excerpt(body, head_chars=1500, tail_chars=600):
    """MA2 的摘录预算。规则本身在 pack_lib——装包的 RAW 段用同一条,不许走散。

    先清页面 chrome 再截:2100 字符的判定窗口里,最脏的文件有七成是 URL,
    等于让 MA2 拿几百字判一篇。
    """
    return pl.excerpt(pl.strip_web_chrome(body), head_chars, tail_chars)
