#!/usr/bin/env python3
"""行业预判板 · 裁定页面服务(本地,S0 用)。
用法: python3 tools/ruling_server.py [port]   默认 8766
读 tools/ruling_items_<日期>.json + industries/*.json,提供:
  GET  /               裁定页面(tools/ruling_page.html)
  GET  /api/state      条目、节点/卡片上下文、当前温度、已保存裁定
  POST /api/preview    按当前选择实时算 19 行业温度(D2+D7,可切分母口径)
  POST /api/save       写 assessment/裁定-<日期>.json 与 .md
不改 industries/*.json。
"""
import json, sys, os, glob, copy, datetime, re
from http.server import HTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUND = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('RULING_ROUND', '2026-09-15')
ITEMS_PATH = os.path.join(ROOT, 'tools', f'ruling_items_{ROUND}.json')
PAGE_PATH = os.path.join(ROOT, 'tools', 'ruling_page.html')
SAVE_JSON = os.path.join(ROOT, 'assessment', f'裁定-{ROUND}.json')
SAVE_MD = os.path.join(ROOT, 'assessment', f'裁定-{ROUND}.md')

TIER = {'S1': 1.0, 'S2': 0.8, 'S3': 0.5, 'S4': 0.5}
LEVEL = {'国家': 1.0, '省': 0.7, '市': 0.4}
SIGN = {'up': -1, 'dn': 1, '0': 0}
STANCE_CN = {'risk': '收紧风险', 'support': '国家支持', 'mixed': '支持与收紧并存', 'watch': '观察中'}


def load_industries():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'industries', '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        out[os.path.basename(f)[:-5]] = d
    return out


def recency(d, t0):
    days = (t0 - d).days
    if days < 0: return 0.0
    if days <= 90: return 1.0
    if days <= 180: return 0.7
    if days <= 365: return 0.4
    return 0.0


def compute(ind, overrides=None, denom_directional=False):
    """overrides: {node_id: 'up'|'dn'|'0'|{'tier':..,'push':..}}"""
    overrides = overrides or {}
    t0 = datetime.date.fromisoformat(ind['t0'])
    rows, total, up, dn = [], 0.0, 0.0, 0.0
    for n in ind['timeline']:
        if n.get('after_t0') or n.get('out_of_window') or n.get('pending'):
            continue
        d = datetime.date.fromisoformat(n['date'])
        if d > t0:
            continue
        tier, push = n['tier'], n['push']
        ov = overrides.get(n['id'])
        if isinstance(ov, str):
            push = ov
        elif isinstance(ov, dict):
            tier = ov.get('tier', tier); push = ov.get('push', push)
            if 'push_weight' in ov: n = dict(n, push_weight=ov['push_weight'])
        tw = TIER.get(tier, 0.0); lw = LEVEL.get(n.get('issuer_level', ''), 0.0)
        rw = recency(d, t0); rf = 1.0 if n['role'] == 'fact' else 0.5
        c = round(SIGN[push] * 100.0, 2) if n.get('weight_class') in ('core', 'decisive') else round(SIGN[push] * 20 * tw * lw * rw * rf * float(n.get('push_weight', 1)), 2)
        rows.append((n['id'], push, c))
        total += c; up += max(c, 0); dn += min(c, 0)
    n_dir = len([r for r in rows if r[2] != 0])
    denom = max(n_dir, 1) if denom_directional else (n_dir + 5)  # D12
    temp = max(-100, min(100, round(total / denom * 8)))
    if temp <= -30: st = 'risk'
    elif temp >= 30: st = 'support'
    elif up >= 25 and -dn >= 25: st = 'mixed'
    else: st = 'watch'
    return {'temp': temp, 'stance': st, 'stance_cn': STANCE_CN[st], 'up': round(up, 1), 'dn': round(-dn, 1), 'n': len(rows), 'n_dir': denom if denom_directional else len([r for r in rows if r[1] != '0'])}


def split_ref(ref):
    ind, _, nid = ref.partition(':')
    return ind, nid


def overrides_from_choices(items, choices):
    """→ ({ind: {node: override}}, denom_directional)"""
    ov, denom = {}, False
    for it in items:
        key = choices.get(it['id'])
        if not key: continue
        if it['id'] == 'G2':
            denom = (key == 'b'); continue
        opt = next((o for o in it.get('options', []) if o['key'] == key), None)
        if not opt: continue
        for ref, eff in (opt.get('effects') or {}).items():
            ind, nid = split_ref(ref)
            ov.setdefault(ind, {})[nid] = eff
    return ov, denom


def preview(items, inds, choices):
    ov, denom = overrides_from_choices(items, choices)
    temps = {k: compute(v, ov.get(k), denom) for k, v in inds.items()}
    per_item = {}
    for it in items:
        opts = it.get('options') or []
        if not any(o.get('effects') for o in opts) and it['id'] != 'G2':
            continue
        affected = sorted({split_ref(r)[0] for o in opts for r in (o.get('effects') or {})})
        if it['id'] == 'G2':
            affected = sorted(inds)
        res = {}
        for o in opts:
            c2 = dict(choices); c2[it['id']] = o['key']
            ov2, denom2 = overrides_from_choices(items, c2)
            res[o['key']] = {k: compute(inds[k], ov2.get(k), denom2) for k in affected}
        per_item[it['id']] = res
    return {'temps': temps, 'per_item': per_item}


def node_ctx(inds, ref):
    ind, nid = split_ref(ref)
    d = inds.get(ind)
    if not d: return None
    n = next((x for x in d['timeline'] if x['id'] == nid), None)
    if not n: return None
    return {'ref': ref, 'industry': ind, 'industry_name': d['name'], 'id': nid, 'date': n['date'], 'tier': n['tier'],
            'level': n.get('issuer_level'), 'kind': n.get('kind'), 'role': n['role'], 'push': n['push'],
            'title': n.get('title', ''), 'source': n.get('source_name', ''), 'url': n.get('url', ''),
            'use': n.get('use', ''), 'note': n.get('note', ''), 'excerpt': (n.get('excerpt') or '')[:400]}


def card_ctx(inds, ref):
    ind, cid = split_ref(ref)
    d = inds.get(ind)
    if not d: return None
    c = next((x for x in d.get('cards', []) if x['id'] == cid), None)
    if not c: return None
    return {'ref': ref, 'industry': ind, 'industry_name': d['name'], 'id': cid, 'title': c.get('title', ''),
            'verify_date': c.get('verify_date'), 'level': c.get('level'), 'hypotheses': c.get('hypotheses'),
            'impact': c.get('impact'), 'status': c.get('status')}


def state():
    items_doc = json.load(open(ITEMS_PATH, encoding='utf-8'))
    inds = load_industries()
    nodes, cards = {}, {}
    for it in items_doc['items']:
        for r in it.get('nodes', []):
            c = node_ctx(inds, r)
            if c: nodes[r] = c
        for r in it.get('cards', []):
            c = card_ctx(inds, r)
            if c: cards[r] = c
    industries = {}
    for k, d in inds.items():
        dr = d.get('direction') or {}
        industries[k] = {'id': k, 'name': d['name'], 't0': d['t0'], 'temp': d.get('temp'), 'stance': d.get('stance'),
                         'stance_cn': STANCE_CN.get(d.get('stance'), ''), 'n_nodes': len(d['timeline']),
                         'direction': {'stance': dr.get('stance'), 'confirmed': dr.get('confirmed'),
                                       'basis': dr.get('basis_fact_ids'), 'note': dr.get('note'),
                                       'judged_by': dr.get('judged_by'), 'judged_at': dr.get('judged_at')},
                         'computed': compute(d)}
    saved = json.load(open(SAVE_JSON, encoding='utf-8')) if os.path.exists(SAVE_JSON) else None
    return {'round': items_doc['round'], 'rules': items_doc['rules'], 'items': items_doc['items'],
            'howto': items_doc.get('howto', ''), 'legend': items_doc.get('legend', ''),
            'resolved_by_rule': items_doc.get('resolved_by_rule', []), 'nodes': nodes, 'cards': cards,
            'industries': industries, 'order': list(inds), 'saved': saved}


def save(payload):
    items_doc = json.load(open(ITEMS_PATH, encoding='utf-8'))
    inds = load_industries()
    choices = payload.get('choices', {}); notes = payload.get('notes', {}); dirs = payload.get('directions', {})
    moot = set(payload.get('moot') or [])
    choices = {k: v for k, v in choices.items() if k not in moot}
    pv = preview(items_doc['items'], inds, choices)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    doc = {'round': items_doc['round'], 'saved_at': now, 'choices': choices, 'notes': notes, 'moot': sorted(moot),
           'directions_confirmed': dirs, 'temps_preview': pv['temps'],
           'items_snapshot': [{'id': it['id'], 'title': it['title'], 'group': it['group'],
                               'chosen': choices.get(it['id']), 'recommend': it.get('recommend'),
                               'option_label': next((o['label'] for o in it.get('options', []) if o['key'] == choices.get(it['id'])), None),
                               'effects': next((o.get('effects') for o in it.get('options', []) if o['key'] == choices.get(it['id'])), None)}
                              for it in items_doc['items']]}
    json.dump(doc, open(SAVE_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    # markdown
    L = [f"# 行业预判板 · 用户裁定 {ROUND}(保存 {now})", '', '> 由 tools/ruling_server.py 写出;S0 据此批量改 push/tier 并重跑 temp_calc。', '',
         '| 条目 | 行业 | 裁定 | 与建议 | 备注 |', '|---|---|---|---|---|']
    undecided = []
    for it in items_doc['items']:
        if it['id'] == 'DIR': continue
        k = choices.get(it['id'])
        if it['id'] in moot:
            L.append(f"| {it['id']} {it['title']} | {it['group']} | 随 G1(b) 归 0 | — | |"); continue
        if not k:
            undecided.append(it['id']); continue
        lab = next((o['label'] for o in it.get('options', []) if o['key'] == k), k)
        same = '同' if k == it.get('recommend') else '异'
        L.append(f"| {it['id']} {it['title']} | {it['group']} | {k} {lab} | {same} | {(notes.get(it['id']) or '').replace(chr(10), ' ')} |")
    L += ['', '## 产业方向确认', '']
    for k in inds:
        L.append(f"- {inds[k]['name']}({k}):{'确认' if dirs.get(k) else '保持草拟'}")
    L += ['', '## 裁定后温度预览(按所选项重算,分母口径按 G2)', '', '| 行业 | 现 | 裁定后 | 强度 |', '|---|---|---|---|']
    for k in inds:
        t = pv['temps'][k]
        L.append(f"| {inds[k]['name']} | {inds[k].get('temp')} {STANCE_CN.get(inds[k].get('stance'), '')} | {t['temp']} | {t['stance_cn']} |")
    if undecided:
        L += ['', f"未裁定:{', '.join(undecided)}"]
    open(SAVE_MD, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    return {'ok': True, 'saved_at': now, 'json': SAVE_JSON, 'md': SAVE_MD, 'undecided': undecided}


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p in ('/', '/index.html'):
            b = open(PAGE_PATH, 'rb').read()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
        elif p == '/api/state':
            self._json(state())
        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        payload = json.loads(self.rfile.read(n) or b'{}')
        if self.path == '/api/preview':
            items_doc = json.load(open(ITEMS_PATH, encoding='utf-8'))
            self._json(preview(items_doc['items'], load_industries(), payload.get('choices', {})))
        elif self.path == '/api/save':
            self._json(save(payload))
        else:
            self._json({'error': 'not found'}, 404)

    def log_message(self, fmt, *a):
        sys.stderr.write('%s %s\n' % (self.command, self.path))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    print(f'裁定页面 http://127.0.0.1:{port}/  (items: {ITEMS_PATH})')
    HTTPServer(('127.0.0.1', port), H).serve_forever()
