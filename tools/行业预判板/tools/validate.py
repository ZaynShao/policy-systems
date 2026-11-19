#!/usr/bin/env python3
"""行业 JSON 校验:schema + 一致性规则(D1–D4、决策①)。
用法: python3 tools/validate.py industries/<id>.json [...]
退出码 1 = 有 ERROR。WARN 不阻塞但要在 F门.md 里说明。
"""
import json, sys, os, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = json.load(open(os.path.join(HERE, '..', 'schema', 'industry.schema.json'), encoding='utf-8'))
sys.path.insert(0, HERE)
from temp_calc import compute_full, stance_for

def d(s):
    return datetime.date.fromisoformat(s)

def check(path):
    errs, warns = [], []
    ind = json.load(open(path, encoding='utf-8'))
    try:
        import jsonschema
        for e in sorted(jsonschema.Draft7Validator(SCHEMA).iter_errors(ind), key=lambda e: list(e.path)):
            errs.append(f"schema: {'/'.join(map(str, e.path))}: {e.message[:160]}")
    except ImportError:
        warns.append('jsonschema 未安装,跳过 schema 校验')
    t0 = d(ind['t0']); win_from = t0 - datetime.timedelta(days=365)
    nodes = {n['id']: n for n in ind['timeline']}
    if len(nodes) != len(ind['timeline']): errs.append('timeline id 重复')
    # 节点基本
    for n in ind['timeline']:
        nd = d(n['date'])
        if n.get('pending'):
            continue
        if not n.get('url', '').startswith('http'): errs.append(f"{n['id']}: url 缺失")
        if not n.get('fetched_at'): errs.append(f"{n['id']}: fetched_at 缺失")
        if not n.get('excerpt', '').strip(): errs.append(f"{n['id']}: excerpt 为空")
        if n.get('tier') == 'S5': errs.append(f"{n['id']}: S5 不得进链")
        if (nd > t0) != bool(n.get('after_t0')): errs.append(f"{n['id']}: after_t0 与日期不符(T0={t0})")
        if n.get('out_of_window'):
            if n['role'] != 'fact' or n['tier'] != 'S1': errs.append(f"{n['id']}: 锚点必须 role=fact tier=S1")
            if nd >= win_from: warns.append(f"{n['id']}: 标了 out_of_window 但日期在窗内")
        elif nd < win_from and nd <= t0:
            errs.append(f"{n['id']}: 日期在观察窗外({win_from}前)又未标 out_of_window")
        if n['role'] == 'context':
            rel = n.get('relation') or {}
            if rel.get('to_fact_id') not in nodes or nodes.get(rel.get('to_fact_id'), {}).get('role') != 'fact':
                errs.append(f"{n['id']}: context 节点必须挂到一个 fact 节点(relation.to_fact_id)")
            if not rel.get('effect'): errs.append(f"{n['id']}: relation.effect 缺失")
        if n['role'] == 'fact' and not n.get('stage') and not n.get('after_t0'):
            warns.append(f"{n['id']}: fact 节点缺 stage")
    # D12: push_weight 只允许 1 / 0.5,且只用于 up
    for n in ind['timeline']:
        if 'push_weight' in n and (n['push_weight'] not in (1, 0.5, 1.0) or (n['push_weight'] == 0.5 and n['push'] != 'up')):
            errs.append(f"{n['id']}: push_weight 只能是 1 或 0.5,且 0.5 只用于 up(软规则)")
    # D1: 窗内 S1 fact ≥3 且 ≥1 国家/省
    s1 = [n for n in ind['timeline'] if n['role'] == 'fact' and n['tier'] == 'S1' and not n.get('after_t0')
          and not n.get('out_of_window') and not n.get('pending') and win_from <= d(n['date']) <= t0]
    if len(s1) < 3: errs.append(f"停点1: 窗内 S1 政策事实仅 {len(s1)} 条(<3)")
    if not any(n.get('issuer_level') in ('国家', '省') for n in s1): errs.append('停点1: 窗内 S1 事实无国家/省级件')
    # D2: temp_calc
    rows, temp, st, up, dn, basis = compute_full(ind)
    # D14 weight_class 合法性
    for n in ind['timeline']:
        wc = n.get('weight_class')
        if wc is None: continue
        if wc not in ('core', 'decisive'): errs.append(f"{n['id']}: weight_class 只能是 core/decisive")
        if n['role'] != 'fact' or n['push'] == '0': errs.append(f"{n['id']}: weight_class 节点必须是有方向的 fact")
        if wc == 'decisive':
            dt = n.get('decisive_temp')
            if not isinstance(dt, int) or abs(dt) < 60 or abs(dt) > 100: errs.append(f"{n['id']}: decisive_temp 须为整数且 60≤|值|≤100")
            elif (dt < 0) != (n['push'] == 'up'): errs.append(f"{n['id']}: decisive_temp 符号与 push 方向不符")
    tb = (ind.get('meta') or {}).get('temp_basis') or {'mode': 'mean'}  # 缺省按均值(旧文件未写 temp_basis)
    if tb != basis: errs.append(f"meta.temp_basis {tb} ≠ 规则值 {basis}")
    if 'override' in (ind.get('meta') or {}) or 'temp_model' in ind: errs.append('D14 已改为 weight_class 机制,不接受 override/temp_model')
    exp = {r['node_id']: r['contribution'] for r in rows}
    got = {r['node_id']: r['contribution'] for r in ind.get('temp_calc', [])}
    for k, v in exp.items():
        if k not in got: errs.append(f"temp_calc 缺节点 {k}")
        elif abs(got[k] - v) > 0.02: errs.append(f"temp_calc {k} 贡献 {got[k]} ≠ 规则值 {v}")
    for k in got:
        if k not in exp: errs.append(f"temp_calc 多出节点 {k}(T0后/锚点/pending 不计)")
    if ind.get('temp') != temp: errs.append(f"temp {ind.get('temp')} ≠ 规则值 {temp}")
    if ind.get('stance') != st: errs.append(f"stance {ind.get('stance')} ≠ 规则值 {st}")
    # 卡片
    br = ind['process']['base_rate']
    missing = bool(br.get('missing')) or br.get('n', 0) < 5
    if br.get('n', 0) < 5 and not br.get('missing'): errs.append('base_rate n<5 必须 missing=true')
    if not missing and len(br.get('samples', [])) < br['n']: errs.append('base_rate samples 数少于 n')
    for smp in br.get('samples', []):
        if not smp.get('url', '').startswith('http'): errs.append(f"基率样本 {smp.get('title')} 无 URL")
    for c in ind['cards']:
        keys = [h['key'] for h in c['hypotheses']]
        if sorted(keys) != ['H0', 'H1', 'H2']: errs.append(f"{c['id']}: 假设组必须 H1/H2/H0 各一")
        ps = [h.get('p') for h in c['hypotheses']]
        if any(p is None for p in ps): errs.append(f"{c['id']}: 决策①要求每个假设填 p")
        elif abs(sum(ps) - 1) > 0.011: errs.append(f"{c['id']}: p 之和 {sum(ps):.2f} ≠ 1")
        for fid in c['basis_fact_ids']:
            n = nodes.get(fid)
            if not n: errs.append(f"{c['id']}: basis {fid} 不存在")
            elif n['role'] != 'fact' or n.get('after_t0') or n.get('out_of_window') or n.get('pending'):
                errs.append(f"{c['id']}: basis {fid} 必须是 T0 前、窗内的 fact 节点")
        if missing and c['level'] in ('较大可能', '高度可能'): errs.append(f"{c['id']}: 基率缺失,档位不得高于「可能」")
        wf, wt, vd = d(c['window']['from']), d(c['window']['to']), d(c['verify_date'])
        if wf < t0: warns.append(f"{c['id']}: window.from 早于 T0")
        if not (wt < vd <= wt + datetime.timedelta(days=15)): errs.append(f"{c['id']}: verify_date 须在 window.to 之后 15 天内")
        imp = c.get('impact') or {}
        if not all(imp.get(k) for k in ('strategy', 'gr', 'compliance')): warns.append(f"{c['id']}: impact 三维不全")
    # D8: direction 产业方向
    dr = ind.get('direction')
    if not dr: errs.append('D8: 缺 direction(产业方向)')
    else:
        if dr.get('stance') not in ('支持', '中性', '限制'): errs.append('D8: direction.stance 必须是 支持/中性/限制')
        if not dr.get('basis_fact_ids'): errs.append('D8: direction.basis_fact_ids 为空')
        for fid in dr.get('basis_fact_ids', []):
            n = nodes.get(fid)
            if not n: errs.append(f"D8: direction 依据 {fid} 不存在")
            elif n['role'] != 'fact' or n['tier'] != 'S1' or n.get('issuer_level') != '国家' or n.get('after_t0') or n.get('pending'):
                errs.append(f"D8: direction 依据 {fid} 必须是 T0 前的 S1 国家级 fact(可为锚点)")
        if not dr.get('note'): warns.append('D8: direction.note 为空')
        if not dr.get('confirmed'): warns.append('D8: direction 为草拟、未经用户确认')
    # 算子
    names = [o['name'] for o in ind['process']['operators']]
    if len(set(names)) != 4: errs.append('operators 必须四个且不重复')
    for o in ind['process']['operators']:
        if o['status'] in ('SUPPORTED', 'COUNTER') and not o.get('fact_ids'): errs.append(f"算子 {o['name']} {o['status']} 但 fact_ids 为空")
        for fid in o.get('fact_ids', []):
            if fid not in nodes: errs.append(f"算子 {o['name']} 引用不存在的节点 {fid}")
    # 其它
    if ind['next']['source_node_id'] not in nodes: errs.append('next.source_node_id 不存在')
    if ind['process']['kind'] == 'service_run' and not ind['process'].get('run', {}).get('run_id'): errs.append('service_run 必须有 run.run_id')
    admitted = sum(1 for n in ind['timeline'] if not n.get('pending'))
    if ind['process']['retrieval'].get('admitted') != admitted: warns.append(f"retrieval.admitted={ind['process']['retrieval'].get('admitted')} 与时间链节点数 {admitted} 不一致")
    for k in ('stance_rule', 's1_admission_rule', 'anchor_rule', 'direction_rule'):
        if not ind['meta'].get(k): warns.append(f"meta.{k} 缺失")
    return errs, warns

if __name__ == '__main__':
    bad = 0
    for p in sys.argv[1:]:
        errs, warns = check(p)
        print(f"== {p}: {len(errs)} ERROR, {len(warns)} WARN")
        for e in errs: print('  ERROR', e)
        for w in warns: print('  WARN ', w)
        bad += bool(errs)
    sys.exit(1 if bad else 0)
