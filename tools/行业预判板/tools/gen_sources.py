#!/usr/bin/env python3
"""从 industries/<id>.json 生成 sources/<id>/<node_id>.md（原文摘录 + 抓取记录）。用法: python3 tools/gen_sources.py healthcare"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ind_id = sys.argv[1]
root = os.path.join(HERE, '..')
d = json.load(open(os.path.join(root, 'industries', f'{ind_id}.json'), encoding='utf-8'))
out = os.path.join(root, 'sources', ind_id)
os.makedirs(out, exist_ok=True)
n_written = 0
for n in d['timeline']:
    if n.get('pending'):
        continue
    fm = {
        'node_id': n['id'], 'url': n['url'], 'fetched_at': n['fetched_at'],
        'http_status': n.get('http_status', ''), 'fetch_tool': n.get('fetch_tool', ''),
        'title': n['title'], 'issuer': n.get('issuer', ''), 'issuer_level': n['issuer_level'],
        'docno': n.get('docno', ''), 'date': n['date'], 'issued_on': n.get('issued_on', ''),
        'tier': n['tier'], 'role': n['role'], 'kind': n['kind'], 'push': n['push'],
        'out_of_window': n.get('out_of_window', False), 'after_t0': n['after_t0'],
    }
    lines = ['---']
    for k, v in fm.items():
        if isinstance(v, bool):
            v = 'true' if v else 'false'
        v = str(v).replace('"', '\\"')
        lines.append(f'{k}: "{v}"')
    lines += ['---', '', f"# {n['title']}", '', '## 抓取记录',
              f"- URL：{n['url']}",
              f"- 抓取日：{n['fetched_at']}，方式：{n.get('fetch_tool','')}，HTTP：{n.get('http_status','')}",
              f"- 机关：{n.get('issuer','')}（{n['issuer_level']}）；文号：{n.get('docno','') or '无'}；公开日：{n['date']}；成文日：{n.get('issued_on','') or '未核到'}",
              f"- 级别：{n['tier']}；角色：{n['role']}；推力：{n['push']}" + ('；锚点（窗外，不计 3 条/温度/信号）' if n.get('out_of_window') else '')]
    if n.get('relation'):
        lines.append(f"- 挂接：{n['relation']['to_fact_id']}（{n['relation']['effect']}）")
    lines += ['', '## 原文摘录（不改字，省略号为跳接）', '', '> ' + n['excerpt'].replace('\n', '\n> '), '',
              '## 在推理中的作用', '', n.get('use', ''), '']
    open(os.path.join(out, f"{n['id']}.md"), 'w', encoding='utf-8').write('\n'.join(lines))
    n_written += 1
print(f'written {n_written} files to sources/{ind_id}/')
