#!/usr/bin/env python3
"""独立版:把行业预判板打成一个 HTML 文件,双击就能打开,不用联网、不用起服务。

    python3 portal/industry-board/build-offline.py [输出文件]

默认输出 portal/industry-board/dist/行业预判板-独立版.html(dist/ 不进仓库)。只用 Python 标准库。
做的事(只改离线文件,不动本目录的 index.html、data.js):
- 把 data.js 内联进页面;
- 去掉外网字体(没网时本来也会退回系统字体);
- 默认按平台上的公开视图显示(原来门户 iframe 带 ?embed=1 时就是这样,加工过程用知识库口径),
  页面顶部说明条里可切到「完整工作记录」(网址后加 ?full=1,也就是原来单独打开时看到的全量视图);
- 隐藏页头下那排静态的平台页签(独立版没有那些页面)。
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "dist" / "行业预判板-独立版.html"
html = (HERE / "index.html").read_text(encoding="utf-8")
data = (HERE / "data.js").read_text(encoding="utf-8")
meta = json.loads(re.search(r"window\.BOARD_META=(\{.*?\});\n", data).group(1))
rows = json.loads(re.search(r"window\.INDUSTRY_DATA=(\[.*\]);\n", data, re.S).group(1))
t0 = sorted({r["t0"] for r in rows})

def sub_once(pattern, repl, text, what):
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        sys.exit(f"页面结构和预期不一样,找不到:{what}")
    return new

# 内联数据:数据里若出现 "</script" 要改写,免得提前结束 <script>
inline = data.replace("</script", "<\\/script")
html = sub_once(r'<script src="\./data\.js\?v=\d+"></script>', lambda m: "<script>\n" + inline + "</script>", html, "data.js 引用")
html = sub_once(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com/[^"]*">\n?', "", html, "外网字体")
html = sub_once(r"const PUBLIC = /\[\?&\]\(embed\|public\)=1/\.test\(location\.search\);",
                "const PUBLIC = !/[?&]full=1/.test(location.search);  /* 独立版离线页:默认公开视图,?full=1 看完整工作记录 */",
                html, "公开视图开关")
bar = (
    "<style>.policy-tab-bar{display:none}"
    ".ib-offline-bar{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:0 -20px 14px;padding:8px 20px;"
    "font-size:12.5px;color:#9A3412;background:#FFF7ED;border-bottom:1px solid #FDBA74}"
    ".ib-offline-bar b{font-weight:800}.ib-offline-bar a{color:#9A3412;margin-left:auto}</style>\n"
    '<div class="ib-offline-bar"><b>个人版·离线页</b>'
    f"<span>{len(rows)} 个行业,证据冻结 T0 = {'、'.join(t0)},{meta['built_at']} 打包;数据由 tools/行业预判板 构建,只读。</span>"
    '<a id="ibViewSwitch" href="?full=1">看完整工作记录</a></div>\n'
    "<script>(function(){var full=/[?&]full=1/.test(location.search),a=document.getElementById('ibViewSwitch');"
    "if(full){a.textContent='回到公开视图';a.href=location.pathname;}})();</script>\n"
)
html = sub_once(r'<div class="page">', lambda m: '<div class="page">\n' + bar, html, "页面容器")
assert "https://fonts.googleapis.com" not in html and 'src="./data.js' not in html
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"已写入 {out}({out.stat().st_size / 1024 / 1024:.1f} MB):{len(rows)} 个行业,T0 {'、'.join(t0)}")
