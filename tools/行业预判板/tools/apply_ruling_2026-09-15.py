#!/usr/bin/env python3
"""按 assessment/裁定-2026-09-15.json 批量改写 industries/*.json(S0 执行,一次性脚本)。
G1=b → D10:温度只计监管动作,促进类 dn 节点归 0(KEEP 列表除外);其余按条目 effects;方向确认;stops/gaps 登记。
之后需: for f in industries/*.json: python3 tools/temp_calc.py $f --write; python3 tools/validate.py industries/*.json
"""
import json, glob, os, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, 'assessment', '裁定-2026-09-15.json'), encoding='utf-8'))
ITEMS = {it['id']: it for it in json.load(open(os.path.join(ROOT, 'tools', 'ruling_items_2026-09-15.json'), encoding='utf-8'))['items']}
choices, notes, moot = R['choices'], R['notes'], set(R.get('moot', []))
DAY = '2026-09-15'
assert choices.get('G1') == 'b' and choices.get('G2') == 'a'

D10 = ('D10(2026-09-15 用户裁定 G1=b):温度只计监管动作。dn(放宽)只计放开或降低准入门槛、发放许可/准入资质、简化审批备案、取消或放松既有义务与限制、'
       '开放此前受限的空域/道路/场景、降低检查频次;规划/意见/行动方案/指导意见、补贴与税费优惠、资金与项目、试点与培育、设施资源开放、消费促进、目标上调等促进类文件记 0,'
       '其内容只进产业方向(direction),不进温度。分母仍按 D7 含 push=0 节点(用户裁定 G2=a)。')
# D10 下仍算“放宽”的节点(逐条复判,理由写进 note)
KEEP = {
    'autonomous:F3': '工信部许可两款 L3 车型:发放准入资质',
    'autonomous:F8': '深圳条例修正:全域开放与商业化运营试点入法,放开既有限制',
    'freight:F8': '从业年龄 60→63:放松既有限制',
    'generation:F13': '多用户绿电直连:放开此前不允许的模式',
    'healthcare:F3': '涉企行政检查频次上限:降低检查频次',
}
# 条目 effects(裁定选项自带)
effects = {}
for iid, key in choices.items():
    it = ITEMS.get(iid)
    if not it or iid in moot: continue
    opt = next((o for o in it.get('options', []) if o['key'] == key), None)
    if opt and opt.get('effects'):
        for ref, eff in opt['effects'].items():
            effects[ref] = (eff, iid, opt['label'])

inds = {}
for f in sorted(glob.glob(os.path.join(ROOT, 'industries', '*.json'))):
    inds[os.path.basename(f)[:-5]] = (f, json.load(open(f, encoding='utf-8')))

def setnote(n, text):
    n['note'] = ((n.get('note') or '') + ('\n' if n.get('note') else '') + text)

stats = {'dn_to_0': 0, 'kept': 0, 'effects': 0}
for ind, (f, d) in inds.items():
    t0 = datetime.date.fromisoformat(d['t0'])
    log = []
    # 1) D10 sweep
    for n in d['timeline']:
        ref = f'{ind}:{n["id"]}'
        if n['push'] != 'dn': continue
        if ref in KEEP:
            setnote(n, f'{DAY} D10 复判:仍记 dn({KEEP[ref]})'); stats['kept'] += 1; continue
        n['push'] = '0'; stats['dn_to_0'] += 1
        setnote(n, f'{DAY} 用户裁定 G1=b(D10):促进类文件不进温度,push dn→0;内容只进产业方向')
    # 2) effects
    for ref, (eff, iid, label) in effects.items():
        i2, nid = ref.split(':')
        if i2 != ind: continue
        n = next(x for x in d['timeline'] if x['id'] == nid)
        if isinstance(eff, dict):
            for k, v in eff.items():
                old = n.get(k); n[k] = v
                setnote(n, f'{DAY} 用户裁定 {iid}({label}):{k} {old}→{v}')
        else:
            old = n['push']; n['push'] = eff
            setnote(n, f'{DAY} 用户裁定 {iid}({label}):push {old}→{eff}')
        stats['effects'] += 1
        log.append(f'{DAY} 用户裁定 {iid}:{nid} {label}')
    # 3) direction 确认
    dr = d.get('direction') or {}
    if R['directions_confirmed'].get(ind) and not dr.get('confirmed'):
        dr['confirmed'] = True
        dr['note'] = (dr.get('note') or '') + f'(用户 {DAY} 裁定台确认)'
    # 4) meta
    m = d['meta']
    m['stance_rule'] = m['stance_rule'] + ';' + D10
    log.insert(0, f'{DAY} 用户裁定台(assessment/裁定-{DAY}.json):G1=b 促进类文件不进温度(D10),G2=a 分母维持 D7;本行业 dn→0 节点见各节点 note')
    for iid in [k for k in choices if k in ITEMS and ITEMS[k]['group'] == ind and k not in moot]:
        it = ITEMS[iid]; key = choices[iid]
        lab = next((o['label'] for o in it['options'] if o['key'] == key), key)
        if not it.get('options') or not any(o.get('effects') for o in it['options']) or it['kind'] in ('confirm', 'scope', 'text'):
            log.append(f'{DAY} 用户裁定 {iid}「{it["title"]}」:{key} {lab}' + (f';备注:{notes[iid]}' if notes.get(iid, '').strip() else ''))
    for iid in [k for k in moot if ITEMS[k]['group'] == ind]:
        log.append(f'{DAY} {iid}「{ITEMS[iid]["title"]}」随 G1=b 归 0,不再单议')
    m['stops'] = m.get('stops', []) + log
    gaps = {'EC-1': 'ecommerce', 'OV-2': 'overseas', 'TW-2': 'two_wheel'}
    for iid, g in gaps.items():
        if g == ind and choices.get(iid) == 'a':
            m['gaps'] = m.get('gaps', []) + [f'{DAY} 用户裁定 {iid}:本轮不补,下轮补——{ITEMS[iid]["title"]}']
    # 5) CH-2
    if ind == 'charging' and choices.get('CH-2') == 'b':
        c = next(x for x in d['cards'] if x['id'] == 'CHG-002')
        old = c['impact']['business']; c['impact']['business'] = notes['CH-2'].strip()
        m['stops'].append(f'{DAY} 用户裁定 CH-2:CHG-002 impact.business 改为「{notes["CH-2"].strip()}」;原文:{old}')
    json.dump(d, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(stats)
