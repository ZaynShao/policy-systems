#!/usr/bin/env python3
"""按 assessment/裁定-2026-09-15-r2.json 落地(新增五行业首轮):条目 effects(本轮全为现状,无改动)、方向确认、stops 登记。
用法: python3 tools/apply_ruling_2026-09-15-r2.py   然后对五份跑 temp_calc --write 与 validate。
"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = '2026-09-15'; RND = '2026-09-15-r2'
R = json.load(open(os.path.join(ROOT, 'assessment', f'裁定-{RND}.json'), encoding='utf-8'))
ITEMS = json.load(open(os.path.join(ROOT, 'tools', f'ruling_items_{RND}.json'), encoding='utf-8'))['items']
choices, notes, moot = R['choices'], R.get('notes', {}), set(R.get('moot', []))
NEW = ['water', 'telecom', 'logistics', 'storage_vpp', 'computing']

def setnote(n, text):
    n['note'] = ((n.get('note') or '') + ('\n' if n.get('note') else '') + text)

effects = {}
for it in ITEMS:
    key = choices.get(it['id'])
    if not key or it['id'] in moot: continue
    opt = next((o for o in it.get('options', []) if o['key'] == key), None)
    if opt and opt.get('effects'):
        for ref, eff in opt['effects'].items():
            effects[ref] = (eff, it['id'], opt['label'])

stats = {'effects': 0, 'dir': 0}
for ind_id in NEW:
    p = os.path.join(ROOT, 'industries', f'{ind_id}.json')
    d = json.load(open(p, encoding='utf-8'))
    nodes = {n['id']: n for n in d['timeline']}
    for ref, (eff, iid, label) in effects.items():
        a, nid = ref.split(':')
        if a != ind_id or nid not in nodes: continue
        n = nodes[nid]
        if isinstance(eff, dict):
            for k, v in eff.items():
                old = n.get(k); n[k] = v
                setnote(n, f'{DAY} 用户裁定 {iid}({label}):{k} {old}→{v}')
        else:
            old = n['push']; n['push'] = eff
            setnote(n, f'{DAY} 用户裁定 {iid}({label}):push {old}→{eff}')
        stats['effects'] += 1
    if R.get('directions_confirmed', {}).get(ind_id):
        dr = d['direction']
        if not dr.get('confirmed'):
            dr['confirmed'] = True
            dr['note'] = (dr.get('note') or '') + f'(用户 {DAY} 裁定台确认)'
            stats['dir'] += 1
    log = d['meta'].setdefault('stops', [])
    log.append(f'{DAY} 用户裁定台(assessment/裁定-{RND}.json):本行业各项均选“维持现状/建议项”,无节点改动;产业方向已确认')
    for it in ITEMS:
        if it.get('group') != ind_id: continue
        key = choices.get(it['id']); 
        if not key: continue
        lab = next((o['label'] for o in it.get('options', []) if o['key'] == key), key)
        log.append(f'{DAY} 用户裁定 {it["id"]}「{it["title"]}」:{key} {lab}' + (f';备注:{notes[it["id"]]}' if notes.get(it['id'], '').strip() else ''))
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(ind_id, 'written')
print(stats)
