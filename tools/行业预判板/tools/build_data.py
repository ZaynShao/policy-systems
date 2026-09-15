#!/usr/bin/env python3
"""把 industries/*.json 打包成 build/data.js(window.INDUSTRY_DATA),供 build/index.html 读取。
选 data.js 而不是 fetch JSON 的理由:file:// 直接打开与 Artifact 发布都不需要 fetch/CORS;industries/*.json 仍是唯一事实来源,本文件只是派生物。
用法: python3 tools/build_data.py [--src <industries 目录>] [--allow-mixed-t0]
     先跑 validate,任一行业有 ERROR 则拒绝打包;各行业 t0 不一致(有组在跑下一轮)也拒绝打包,除非 --allow-mixed-t0。
"""
import json, glob, os, sys, datetime, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
ORDER = ['ridehail','freight','two_wheel','fuel','charging','power','autonomous','delivery','tourism','generation',
         'space','embodied','low_altitude','healthcare','elderly','ai','ecommerce','industry','overseas',
         'water','telecom','logistics','storage_vpp','computing']  # 2026-09-15 新增五行业(S8)
SRC = os.path.join(ROOT, 'industries')
if '--src' in sys.argv:
    SRC = sys.argv[sys.argv.index('--src') + 1]
    if not os.path.isabs(SRC): SRC = os.path.join(ROOT, SRC)
paths = {os.path.basename(p)[:-5]: p for p in glob.glob(os.path.join(SRC, '*.json'))}
r = subprocess.run([sys.executable, os.path.join(HERE, 'validate.py')] + [paths[i] for i in ORDER if i in paths], capture_output=True, text=True)
print(r.stdout.strip())
if r.returncode != 0:
    print('validate 有 ERROR,拒绝打包'); sys.exit(1)
data, missing = [], []
for i in ORDER:
    if i in paths:
        data.append(json.load(open(paths[i], encoding='utf-8')))
    else:
        missing.append(i)
t0s = sorted({d['t0'] for d in data})
if len(t0s) > 1 and '--allow-mixed-t0' not in sys.argv:
    print('拒绝打包:各行业 JSON 的 t0 不一致', t0s, '——有组在跑下一轮增量调研;首轮发布请用 --src snapshots/T0-<日期>/industries'); sys.exit(1)
meta = {'built_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'order': ORDER, 'missing': missing,
        'validated': True, 'source': os.path.relpath(SRC, os.path.dirname(ROOT)), 'schema': 'v1.1', 'temp_rule': 'D2+D7+D11+D12+D14'}
os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
out = os.path.join(ROOT, 'build', 'data.js')
with open(out, 'w', encoding='utf-8') as f:
    f.write('/* 由 tools/build_data.py 生成,不要手改;事实以 industries/<id>.json 为准 */\n')
    f.write('window.BOARD_META=' + json.dumps(meta, ensure_ascii=False) + ';\n')
    f.write('window.INDUSTRY_DATA=' + json.dumps(data, ensure_ascii=False) + ';\n')
print('written', out, os.path.getsize(out)//1024, 'KB;', len(data), 'industries; missing:', missing)
