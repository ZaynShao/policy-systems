#!/usr/bin/env python3
"""把 build/ 的行业预判板导出到 safety-platform 的 portal/industry-board/(iframe 挂载用)。
用法: python3 tools/export_portal.py /path/to/safety-platform/portal [--src snapshots/T0-2026-09-14/industries]
做的事:先 build_data(含 validate),再把 build/index.html 包成完整 HTML 文档、给 data.js 加版本参数,复制 data.js,写 README。
"""
import os, sys, re, json, shutil, subprocess, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
if len(sys.argv) < 2:
    print(__doc__); sys.exit(2)
portal = sys.argv[1]; out = os.path.join(portal, 'industry-board')
extra = sys.argv[2:]  # 例如 --src snapshots/T0-2026-09-14/industries
r = subprocess.run([sys.executable, os.path.join(HERE, 'build_data.py')] + extra, capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1])
if r.returncode != 0:
    sys.exit(1)
src = open(os.path.join(ROOT, 'build', 'index.html'), encoding='utf-8').read()
meta = json.loads(re.search(r'window\.BOARD_META=(\{.*?\});\n', open(os.path.join(ROOT, 'build', 'data.js'), encoding='utf-8').read()).group(1))
ver = meta['built_at'].replace('-', '').replace(' ', '').replace(':', '')
head, body = src.split('</style>', 1)
head = head.replace('<meta charset="utf-8">\n', '')
html = ('<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n' + head + '</style>\n</head>\n<body>'
        + body.replace('<script src="data.js"></script>', '<script src="./data.js?v=%s"></script>' % ver)
        + '\n</body>\n</html>\n')
assert '<script src="./data.js?v=' in html
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(html)
shutil.copyfile(os.path.join(ROOT, 'build', 'data.js'), os.path.join(out, 'data.js'))
open(os.path.join(out, 'README.md'), 'w', encoding='utf-8').write(
    '# 行业预判板(生成物,不要手改)\n\n'
    '- 来源:policy pipeline 仓 `state/行业预判板/`(`build/index.html` + `build/data.js`,由 `tools/export_portal.py` 导出)。\n'
    '- 事实来源:`state/行业预判板/industries/<id>.json`(24 个行业,schema v1.2,导出前必过 `tools/validate.py`)。\n'
    '- 挂载方式:`portal/policy-predict.html` 侧栏「行业预判板」视图用同源 iframe 加载本目录 `index.html`;页面在 iframe 内自动隐藏自带的平台页签条。\n'
    '- 刷新数据:在 policy pipeline 仓执行 `python3 state/行业预判板/tools/export_portal.py <safety-platform>/portal`,提交生成的两个文件。\n'
    '- 本次导出:%s;T0 = 2026-09-14;`data.js` 带 `?v=` 版本参数以绕过 5 分钟静态缓存。\n' % meta['built_at'])
print('exported to', out, '(index.html %d KB, data.js %d KB, v=%s)' % (os.path.getsize(os.path.join(out,'index.html'))//1024, os.path.getsize(os.path.join(out,'data.js'))//1024, ver))
