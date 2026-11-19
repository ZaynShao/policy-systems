#!/usr/bin/env python3
"""独立版补的:把链路看板(src/)和演示数据(data/)打成一个双击就能打开的 HTML。只用 Python 标准库。

    python3 dashboard/build.py [输出文件]

默认输出 dashboard/dist/政策分析pipeline-独立版.html(dist/ 不进仓库)。页面不联网、不引外部脚本和字体;
演示数据放在页面里的 <script type="application/json">,换数据先跑 export_data.py 再跑本脚本。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
DATA = HERE / "data"
DEFAULT_OUT = HERE / "dist" / "政策分析pipeline-独立版.html"
MAX_BYTES = 25 * 1024 * 1024


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_data() -> dict:
    data = {name: json.loads(read(DATA / f"{name}.json")) for name in ("overview", "audit", "policies")}
    dates = {data[name]["as_of"] for name in data}
    if len(dates) != 1:
        raise SystemExit(f"data/ 里三份数据的截至日不一致:{sorted(dates)},请重新跑 export_data.py")
    return data


def fill(template: str, marker: str, content: str) -> str:
    """把占位处换成内容。用切分而不是 replace,内容里碰巧有占位字样也不会被二次替换。"""
    head, sep, tail = template.partition(marker)
    if not sep or marker in tail:
        raise SystemExit(f"页面骨架里的占位 {marker} 应该恰好出现一次")
    return head + content + tail


def build(out: Path) -> tuple[Path, int, dict]:
    data = load_data()
    css = read(SRC / "style.css")
    js = read(SRC / "app.js")
    # 内联进页面时不能提前闭合标签:JS 里的 "</script" 写成 "<\/script",JSON 里的 "<" 一律写成 <
    css = re.sub(r"</(style)", r"<\\/\1", css, flags=re.I)
    js = re.sub(r"</(script)", r"<\\/\1", js, flags=re.I)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = read(SRC / "page.html")
    html = fill(html, "/*__STYLE__*/", css)
    html = fill(html, "/*__SCRIPT__*/", js)
    html = fill(html, "/*__DATA__*/", payload)
    size = len(html.encode("utf-8"))
    if size > MAX_BYTES:
        raise SystemExit(f"页面 {size / 1024 / 1024:.1f} MB,超过 25 MB 上限,请减少内嵌数据")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out, size, data


def main(argv: list[str]) -> int:
    out = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_OUT
    out, size, data = build(out)
    print(f"已写入 {out}({size / 1024 / 1024:.1f} MB):数据截至 {data['overview']['as_of']},"
          f"政策库条目 {len(data['policies']['items'])} 条,守恒巡检① {len(data['audit']['derivation'])} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
