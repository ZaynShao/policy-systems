#!/usr/bin/env python3
"""按 D2(+D7 均值化)规则从 timeline 算 temp_calc / temp / stance。D11:趋严为负、放宽为正。
用法: python3 tools/temp_calc.py industries/<id>.json          # 只打印
      python3 tools/temp_calc.py industries/<id>.json --write  # 写回 temp_calc/temp/stance
规则原文见 meta.stance_rule。只计 T0 前、非锚点(out_of_window)、非 pending 节点。
"""
import json, sys, datetime
TIER = {'S1': 1.0, 'S2': 0.8, 'S3': 0.5, 'S4': 0.5}
LEVEL = {'国家': 1.0, '省': 0.7, '市': 0.4}
SIGN = {'up': -1, 'dn': 1, '0': 0}  # D11(2026-09-15 用户裁定):收紧为负、放宽为正

def stance_for(temp, up, dn):
    if temp <= -30: return 'risk'      # 趋严:负值
    if temp >= 30: return 'support'    # 放宽:正值
    if up >= 25 and -dn >= 25: return 'mixed'
    return 'watch'

def recency(d, t0):
    days = (t0 - d).days
    if days < 0: return 0.0
    if days <= 90: return 1.0
    if days <= 180: return 0.7
    if days <= 365: return 0.4
    return 0.0

CORE_FULL = 100.0  # D14:核心内部信息按满额计入(不打级别/层级/时效折扣)

def compute_full(ind):
    t0 = datetime.date.fromisoformat(ind['t0'])
    rows, total, up, dn, decisive = [], 0.0, 0.0, 0.0, []
    for n in ind['timeline']:
        if n.get('after_t0') or n.get('out_of_window') or n.get('pending'):
            continue
        d = datetime.date.fromisoformat(n['date'])
        if d > t0:
            continue
        tw = TIER.get(n['tier'], 0.0)
        lw = LEVEL.get(n.get('issuer_level', ''), 0.0)
        rw = recency(d, t0)
        rf = 1.0 if n['role'] == 'fact' else 0.5
        pw = float(n.get('push_weight', 1))  # D12:软规则 0.5
        wc = n.get('weight_class')
        if wc in ('core', 'decisive'):  # D14(2026-09-15):核心内部信息 / 决定性事件 满额计入
            c = round(SIGN[n['push']] * CORE_FULL, 2)
        else:
            c = round(SIGN[n['push']] * 20 * tw * lw * rw * rf * pw, 2)
        row = {'node_id': n['id'], 'tier_weight': tw, 'level_weight': lw,
               'recency_weight': rw, 'role_factor': rf, 'push': n['push'], 'push_weight': pw, 'contribution': c}
        if wc: row['weight_class'] = wc
        if wc == 'decisive': decisive.append((abs(int(n['decisive_temp'])), int(n['decisive_temp']), n['id']))
        rows.append(row)
        total += c; up += max(c, 0); dn += min(c, 0)
    # D7 均值化;D12(2026-09-15 用户裁定 D):分母 = 有方向节点数 + 5(不被中性节点稀释,+5 防单条饱和)
    n_dir = len([r for r in rows if r['contribution'] != 0])
    mean_temp = max(-100, min(100, round(total / (n_dir + 5) * 8)))
    if decisive:  # D14:决定性事件有绝对权重,温度取其给定值(多条取绝对值最大者)
        _, dt, nid = max(decisive)
        temp = max(-100, min(100, dt))
        basis = {'mode': 'decisive', 'node_id': nid, 'mean_temp': mean_temp}
    else:
        temp = mean_temp
        basis = {'mode': 'mean'}
    return rows, temp, stance_for(temp, up, dn), up, dn, basis

def compute(ind):
    return compute_full(ind)[:5]

if __name__ == '__main__':
    path = sys.argv[1]
    ind = json.load(open(path, encoding='utf-8'))
    rows, temp, st, up, dn, basis = compute_full(ind)
    for r in rows:
        print(f"{r['node_id']:>5} push={r['push']} tier={r['tier_weight']} level={r['level_weight']} rec={r['recency_weight']} role={r['role_factor']}{' ['+r['weight_class']+']' if r.get('weight_class') else ''} -> {r['contribution']:+.2f}")
    print(f"temp={temp} stance={st} (支持分 {up:.1f} / 收紧分 {-dn:.1f}) basis={basis}")
    if '--write' in sys.argv:
        ind['temp_calc'], ind['temp'], ind['stance'] = rows, temp, st
        ind.setdefault('meta', {})['temp_basis'] = basis  # D14:mean 或 decisive
        for k in ('temp_model', 'stance_model'):
            ind.pop(k, None)
        ind['meta'].pop('override', None)
        json.dump(ind, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('written')
