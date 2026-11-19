// 独立版补的:政策分析 pipeline 链路看板的页面逻辑。数据由 build.py 内嵌在 #pp-data 里,不联网、不调接口。
(function () {
  'use strict';

  var DATA = JSON.parse(document.getElementById('pp-data').textContent);
  var O = DATA.overview, A = DATA.audit, P = DATA.policies;
  var ITEMS = P.items;

  // ---------- 小工具 ----------
  function $(sel, root) { return (root || document).querySelector(sel); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(n) { return n == null ? '—' : Number(n).toLocaleString('zh-CN'); }
  function sum(arr, f) { return arr.reduce(function (a, x) { return a + f(x); }, 0); }
  function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
  function issueLabel(s) { var m = /\d{4}-(\d{2})月刊/.exec(s || ''); return m ? Number(m[1]) + ' 月刊' : s; }

  var THEME_ZH = {};
  P.themes.forEach(function (t) { THEME_ZH[t.id] = t.zh; });
  var SOURCE_TYPE = { A: '政府网站', B: '媒体', C: '公众号', D: 'PDF 文件', E: '会议讲话' };
  var ACTION = { A: 'A 趁早', B: 'B 研究', C: 'C 跟进', D: 'D 跟踪' };
  var SCORE_NAMES = { D1: '业务关联度', D2: '直接影响度', D3: '发布主体层级', D4: '紧迫性', D5: '实操性', D6: '机会窗口' };
  var IMPACT_ZH = { '加油': '加油', '充电': '充电', '电力_储能_V2G_交易': '电力 · 储能 · V2G · 交易' };
  var LEVELS = ['国家', '省', '市', '区', '县'];

  var ICON = {
    warn: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 15 14H1z" fill="var(--warning)"/><path d="M8 6v3.6M8 11.4v.1" stroke="#0b0b0b" stroke-width="1.6" stroke-linecap="round"/></svg>',
    na: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="none" stroke="var(--muted)" stroke-width="1.5"/><path d="M5 8h6" stroke="var(--muted)" stroke-width="1.6" stroke-linecap="round"/></svg>',
    ok: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--good)"/><path d="m4.8 8.2 2.2 2.2 4.2-4.6" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    no: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--serious)"/><path d="m5.5 5.5 5 5m0-5-5 5" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>',
    info: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="var(--accent)"/><path d="M8 7.2v4M8 4.8v.1" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>'
  };

  // ---------- 主题切换(跟随系统 / 浅色 / 深色) ----------
  var THEMES = ['auto', 'light', 'dark'], THEME_TEXT = { auto: '跟随系统', light: '浅色', dark: '深色' };
  function applyTheme(t) {
    if (t === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
    $('#theme-btn').innerHTML = '<span aria-hidden="true">◐</span><span class="theme-text">' + THEME_TEXT[t] + '</span>';
    $('#theme-btn').setAttribute('aria-label', '外观:' + THEME_TEXT[t] + '(点一下切换)');
    $('#theme-btn').dataset.theme = t;
  }
  var savedTheme = 'auto';
  try { savedTheme = localStorage.getItem('pp-theme') || 'auto'; } catch (e) { /* 存储不可用就跟随系统 */ }
  if (THEMES.indexOf(savedTheme) < 0) savedTheme = 'auto';
  applyTheme(savedTheme);
  $('#theme-btn').addEventListener('click', function () {
    var next = THEMES[(THEMES.indexOf(this.dataset.theme) + 1) % THEMES.length];
    applyTheme(next);
    try { localStorage.setItem('pp-theme', next); } catch (e) { /* 忽略 */ }
  });

  // ---------- 页头 ----------
  var head = O.vault_head || {};
  var headTime = (head.committed_at || '').replace('T', ' ').slice(0, 16);
  var SUBJECT_ZH = {
    'l2(signals): nightly derived signals': '夜间派生信号', 'l2: daily derive': 'L2 每日派生',
    'l1(policy): daily incremental': 'L1 每日增量', 'l2(relations): nightly increment': '夜间关系增量'
  };
  var headWhat = SUBJECT_ZH[head.subject] || head.subject || '';
  $('#asof').innerHTML = '<span class="dot"></span><span>数据截至 <b>' + esc(O.as_of) + '</b></span>'
    + '<span class="muted">政策库最后一次写入 ' + esc(headTime) + (headWhat ? '(' + esc(headWhat) + ')' : '')
    + ' · 看板数据录于 ' + esc(O.recorded_at) + '</span>';
  document.querySelectorAll('[data-asof]').forEach(function (el) { el.textContent = O.as_of; });

  // ---------- 链路图 ----------
  var L1 = O.l1, L2 = O.l2, EX = O.exits;
  var levelText = L1.by_level.slice().sort(function (a, b) { return LEVELS.indexOf(a[0]) - LEVELS.indexOf(b[0]); })
    .map(function (x) { return esc(x[0]) + ' ' + fmt(x[1]); }).join(' · ');
  var issues = EX.monthly.issues || [];
  var monthlySel = sum(issues, function (x) { return x.selected; });
  var monthlyIn = sum(issues, function (x) { return x.in_vault; });
  var rejected = {};
  EX.platform.rejected.forEach(function (x) { rejected[x[0]] = x[1]; });

  function kv(rows) {
    return '<dl class="kv">' + rows.map(function (r) {
      return '<dt' + (r[2] ? ' class="warn-dot"' : '') + '>' + r[0] + '</dt><dd>' + r[1] + '</dd>';
    }).join('') + '</dl>';
  }
  function arrow(main, drop, tip) {
    return '<div class="arrow"><span class="arrow-note"' + (tip ? ' data-tip="' + esc(tip) + '" tabindex="0"' : '') + '><b>' + main + '</b>'
      + (drop ? '<span class="drop">' + drop + '</span>' : '') + '</span></div>';
  }

  var flowHtml = ''
    + '<div class="stage card">'
    + '<div class="stage-head"><span class="stage-tag">L1</span><h3>采集</h3></div>'
    + '<div class="stage-hero num">' + fmt(L1.policy_files) + '<small>篇政策原文</small></div>'
    + '<div class="stage-sub">' + fmt(L1.policy_pids) + ' 个编号;' + levelText + '</div>'
    + kv([
      ['评论、解读原文', fmt(L1.commentaries) + ' 篇'],
      ['采集渠道', fmt(L1.channels.total) + ' 条<span class="muted">(验证 ' + fmt(L1.channels.by_status['验证'] || 0) + ')</span>'],
      ['编号撞车', fmt(L1.collision_groups) + ' 组 / ' + fmt(L1.collision_files) + ' 篇', true],
      ['换版归档 · 去重隔离', fmt(L1.archived) + ' · ' + fmt(L1.duplicates)]
    ])
    + '<div class="stage-foot">按行业发现渠道 → 扫列表页 → 抓正文 → 入库,每天增量</div>'
    + '</div>'
    + arrow(fmt(L2.business_view_with_raw) + ' 有 L2', fmt(L2.pids_without_l2) + ' 个还没有',
      L1.policy_pids + ' 个编号里,' + L2.business_view_with_raw + ' 个已经做了 L2;' + L2.pids_without_l2 + ' 个还没有(守恒巡检①)')
    + '<div class="stage card">'
    + '<div class="stage-head"><span class="stage-tag">L2</span><h3>分析</h3></div>'
    + '<div class="stage-hero num">' + fmt(L2.business_view) + '<small>份主题打分</small></div>'
    + '<div class="stage-sub">挂上业务主题 ' + fmt(L2.themed) + ' 份,其中 ' + fmt(L2.impact) + ' 份过了深度门、写了影响分析</div>'
    + kv([
      ['影响分析与行动建议', fmt(L2.impact) + ' 份'],
      ['客观摘要', fmt(L2.summaries) + ' 条'],
      ['政策关系', fmt(L2.relations) + ' 条'],
      ['评论信号 · 市场信号', fmt(L2.commentary_signals) + ' · ' + fmt(L2.market_intel_signals)],
      ['找不到原文的 L2', fmt(L2.business_view_orphan) + ' 份', true]
    ])
    + '<div class="stage-foot">六维打分 → 挂主题 → 深度门 → 影响分析;关系、摘要另跑</div>'
    + '</div>'
    + arrow('写回政策库', '整体重写', 'L2 产物整体重写进 1_extracted/ 和 _meta/business_view/,原文层不动')
    + '<div class="stage card">'
    + '<div class="stage-head"><span class="stage-tag">vault</span><h3>政策库</h3></div>'
    + '<div class="stage-hero num">' + fmt(L1.policy_pids) + '<small>个政策编号</small></div>'
    + '<div class="stage-sub">截至 ' + esc(headTime) + '</div>'
    + '<ul class="dirs">' + O.vault_dirs.map(function (d) {
      return '<li><span class="dir-top"><code>' + esc(d.dir) + '</code><span class="num">' + fmt(d.count) + ' ' + esc(d.unit) + '</span></span>'
        + '<span class="dir-what">' + esc(d.what) + '</span></li>';
    }).join('') + '</ul>'
    + '<div class="stage-foot">原文可以出去,判断不能出去:对外接口只给原文</div>'
    + '</div>'
    + arrow(fmt(EX.platform.rows) + ' 篇投影', fmt(rejected['发文日缺失'] || 0) + ' 篇被拒',
      '同步按 L2 逐篇投影进平台库;' + (rejected['发文日缺失'] || 0) + ' 篇缺发文日被拒、' + (rejected['L2 找不到原文'] || 0) + ' 份 L2 找不到原文')
    + '<div class="exits">'
    + '<div class="exit card"><h4>平台库 · 政策大盘<span class="big num">' + fmt(EX.platform.rows) + '<small>行</small></span></h4>'
    + '<p>同步代码算出应写入的行(本机只算不写)。' + fmt(rejected['发文日缺失'] || 0) + ' 篇缺发文日被拒;'
    + fmt(EX.platform.rows_without_adcode) + ' 行缺区划代码,大盘只能按地区名兜底认省份。库里实有多少行要连库才知道(巡检②)。</p></div>'
    + '<div class="exit card"><h4>问答助手<span class="big num">' + fmt(EX.qa.searchable) + '<small>篇可查</small></span></h4>'
    + '<p>问答查的就是平台库里 pipeline 投影的行。没有 L2 的 ' + fmt(EX.qa.no_l2) + ' 篇查不到(巡检①);编号撞车多出的 '
    + fmt(EX.qa.collision_hidden) + ' 篇按编号存不下。</p></div>'
    + '<div class="exit card"><h4>月刊<span class="big num">' + fmt(issues.length) + '<small>期</small></span></h4>'
    + '<p>' + (issues.length ? esc(issueLabel(issues[0].issue)) + '—' + esc(issueLabel(issues[issues.length - 1].issue))
      + '共选用 ' + fmt(monthlySel) + ' 件,其中库里有 ' + fmt(monthlyIn) + ' 件、库外 ' + fmt(monthlySel - monthlyIn) + ' 件。'
      + issues.map(function (x) { return esc(issueLabel(x.issue)) + ' ' + fmt(x.selected); }).join(' · ') : '没有带月刊选目单。') + '</p></div>'
    + '<div class="exit card"><h4>对外只读接口<span class="big num">' + fmt(EX.corpus.exported) + '<small>篇</small></span></h4>'
    + '<p>只出政策原文,不出 L2(白名单投影)。' + EX.corpus.excluded.map(function (x) { return '排除' + esc(x[0]) + ' ' + fmt(x[1]) + ' 篇'; }).join(',')
    + '。按本机库重算,服务器上的语料包以部署时为准。</p></div>'
    + '</div>';
  $('#flow').innerHTML = flowHtml;

  // ---------- 分布小图 ----------
  (function () {
    var months = L1.by_fetch_month;
    var max = Math.max.apply(null, months.map(function (m) { return m[1]; }));
    var last = months[months.length - 1];
    var asOfMonth = O.as_of.slice(0, 7);
    var cols = months.map(function (m, i) {
      var h = Math.max(2, Math.round((m[1] / max) * 100));
      var partial = m[0] === asOfMonth;
      var showVal = m[1] === max || i === months.length - 1;
      return '<div class="col" data-tip="' + esc(m[0] + ' 新入库 ' + fmt(m[1]) + ' 篇' + (partial ? '(只到 ' + O.as_of.slice(5) + ')' : '')) + '" tabindex="0">'
        + (showVal ? '<span class="val num" style="bottom:' + h + '%">' + fmt(m[1]) + '</span>' : '')
        + '<div class="bar' + (partial ? ' part' : '') + '" style="height:' + h + '%"></div></div>';
    }).join('');
    var labels = months.map(function (m) { return '<span>' + Number(m[0].slice(5)) + '月</span>'; }).join('');
    var themeMax = Math.max.apply(null, L2.by_theme.map(function (t) { return t[2]; }));
    var bars = L2.by_theme.map(function (t) {
      var w = (t[2] / themeMax) * 82;
      return '<div class="hbar" data-tip="' + esc(t[1] + ':' + fmt(t[2]) + ' 份 L2 挂了这个主题') + '" tabindex="0"><span class="name">' + esc(t[1]) + '</span>'
        + '<span class="track"><span class="fill" style="width:' + w + '%"></span><span class="v num" style="left:calc(' + w + '% + 6px)">' + fmt(t[2]) + '</span></span></div>';
    }).join('');
    var meters = L2.by_model.map(function (m) {
      var p = pct(m.themed, m.count);
      return '<div class="meter-row" data-tip="' + esc(m.model + ':' + fmt(m.count) + ' 份里 ' + fmt(m.themed) + ' 份挂上了主题') + '" tabindex="0">'
        + '<div class="top"><span>' + esc(m.model) + '</span><span class="num">' + fmt(m.themed) + ' / ' + fmt(m.count) + ' · ' + p + '%</span></div>'
        + '<div class="meter"><i style="width:' + p + '%"></i></div></div>';
    }).join('');
    $('#minis').innerHTML = ''
      + '<div class="mini card"><h3>每月新入库的政策</h3><p class="cap">按采集时间;' + esc(last[0]) + ' 只到 ' + esc(O.as_of.slice(5)) + '(斜纹)</p>'
      + '<div class="cols">' + cols + '</div><div class="col-labels">' + labels + '</div></div>'
      + '<div class="mini card"><h3>L2 挂上的业务主题</h3><p class="cap">份数;一份可挂多个主题,共 ' + L2.by_theme.length + ' 个主题</p>'
      + '<div class="hbars">' + bars + '</div></div>'
      + '<div class="mini card"><h3>两批打分模型的挂主题率</h3><p class="cap">挂上主题的份数 / 打分份数</p>' + meters
      + '<div class="note-box">两批模型挂主题率差很多,跨批比较「重要性」「挂没挂主题」要小心:主题分只当信号用,编辑判断为主。</div></div>';
  })();

  // ---------- 口径说明 ----------
  (function () {
    var rows = [
      ['政策原文 / 编号', fmt(L1.policy_files) + ' / ' + fmt(L1.policy_pids), '<code>0_raw/policies/*.md</code> 的文件数;编号是 frontmatter 的 id 去重(读法同 <code>scripts/l1_audit/corpus.py</code>)'],
      ['编号撞车', fmt(L1.collision_groups) + ' 组 ' + fmt(L1.collision_files) + ' 篇', '同一个 id 对应多份文件;平台库、问答按编号存,每组只留得下一篇'],
      ['采集渠道', fmt(L1.channels.total), '本仓 <code>state/T1_channels/channel_catalog.yaml</code>(最后改于原项目 PR 1183,2026-09-14),不是服务器上的最新版'],
      ['L2 主题打分', fmt(L2.business_view), '<code>_meta/business_view/*.yaml</code>;挂主题 = themes 非空;影响分析 = 有「影响分析」段'],
      ['客观摘要 / 政策关系', fmt(L2.summaries) + ' / ' + fmt(L2.relations), '<code>1_extracted/policy_summaries.jsonl</code>、<code>1_extracted/relations/*.jsonl</code>'],
      ['平台库应写入', fmt(EX.platform.rows), '<code>scripts/sync/run_sync.py</code> 的 <code>collect_policy_rows</code>:只取行、不连库'],
      ['问答可查', fmt(EX.qa.searchable), '问答检索平台库里 pipeline 投影的行(pipelinePid 非空),与上一行同数'],
      ['月刊', fmt(issues.length) + ' 期', '本机月刊产线各期选目单 <code>slate.json</code> 里逐条详述和合并综述的选用件,只数件数'],
      ['对外只读接口', fmt(EX.corpus.exported), '<code>scripts/public_export/run.py</code> 的 <code>export</code>:白名单投影,只读原文'],
      ['守恒巡检', '①③④', '<code>scripts/service/conservation_audit.py</code>(原项目 PR 1184)的 <code>run</code>,today 取数据截至日,不给 DATABASE_URL,所以②跳过']
    ];
    $('#method').innerHTML = '<summary>每个数怎么来的</summary><table class="method-table"><thead><tr><th>项目</th><th>件数</th><th>口径与算它的代码</th></tr></thead><tbody>'
      + rows.map(function (r) { return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td><td>' + r[2] + '</td></tr>'; }).join('')
      + '</tbody></table>';
  })();

  // ---------- 条目索引(巡检清单、相关政策要跳过来) ----------
  var BY_PID = {};
  ITEMS.forEach(function (it, i) {
    it._i = i;
    if (!BY_PID[it.pid] || it.l2) BY_PID[it.pid] = it;
    var s = it.summary || {}, l2 = it.l2 || {};
    it._hay = [it.title, it.doc_no, it.issuer.join(' '), it.pid, it.region, it.province, it.site,
      s.text, s.one_liner, l2.one_liner].join(' ').toLowerCase();
    it._issuer = it.issuer.join(' ').toLowerCase();
  });
  function titleLink(pid, title) {
    var it = BY_PID[pid];
    if (!it) return '<span class="plain-title">' + esc(title) + '</span>';
    return '<button type="button" class="linkish" data-open="' + it._i + '">' + esc(title || it.title) + '</button>';
  }

  // ---------- 守恒巡检 ----------
  (function () {
    var asMonth = A.as_of.slice(0, 7);
    var recent = A.derivation.filter(function (x) { return (x.fetched_at || '').slice(0, 7) === asMonth; }).length;
    var byLevel = {};
    A.derivation.forEach(function (x) { byLevel[x.level || '未标'] = (byLevel[x.level || '未标'] || 0) + 1; });
    var broke = A.stale.filter(function (x) { return x.kind === '停更'; });
    var never = A.stale.filter(function (x) { return x.kind !== '停更'; });
    var covMax = Math.max.apply(null, A.coverage.map(function (c) { return c.mentions; }).concat([1]));

    function status(kind, text) { return '<span class="status ' + kind + '">' + ICON[kind === 'gap' ? 'warn' : 'na'] + text + '</span>'; }

    var c1 = '<div class="audit-card card">'
      + '<h3>① 有原文、没有 L2(问答查不到)</h3>'
      + '<div class="audit-top"><span class="audit-num num">' + fmt(A.derivation.length) + '<small>篇</small></span>' + status('gap', '有差额') + '</div>'
      + '<p class="why">平台库按 L2 逐篇投影,没有 L2 的政策进不了库,问答也就查不到。其中 <b>' + fmt(recent) + '</b> 篇是 '
      + esc(asMonth) + ' 才入库的,' + fmt(A.derivation.length - recent) + ' 篇是更早入库的。</p>'
      + '<div class="chips">' + LEVELS.filter(function (l) { return byLevel[l]; }).map(function (l) { return '<span class="chip">' + l + ' <b class="num">' + fmt(byLevel[l]) + '</b></span>'; }).join('') + '</div>'
      + '<div class="list-tools"><input type="search" id="a1-q" placeholder="在这 ' + fmt(A.derivation.length) + ' 篇里搜标题或编号" aria-label="在巡检①清单里搜索"></div>'
      + '<div class="tbl-wrap"><table class="tbl" id="a1-tbl"><thead><tr><th>发文日</th><th>标题</th><th>层级</th><th>入库</th></tr></thead><tbody></tbody></table></div>'
      + '</div>';

    var c2 = '<div class="audit-card card">'
      + '<h3>② 投影守恒(L2 份数 对 平台库行数)</h3>'
      + '<div class="audit-top"><span class="audit-num">—</span>' + status('na', '本机算不了') + '</div>'
      + '<p class="why">要数平台库(heng-pg)里 pipeline 投影的行,巡检从环境变量 DATABASE_URL 连库;本机没有库,也不该连生产,这一段原样跳过,不编数。</p>'
      + '<p class="why">能算的只有「应有」这一边:L2 <b>' + fmt(A.projection.business_view) + '</b> 份 → 同步代码算出能写进库 <b>'
      + fmt(A.projection.sync_rows) + '</b> 行,' + fmt(A.projection.sync_rejected) + ' 份会被拒('
      + EX.platform.rejected.map(function (x) { return esc(x[0]) + ' ' + fmt(x[1]); }).join('、') + ')。巡检拿 L2 份数去比,不扣被拒的,所以库里就算和同步完全一致,这一段也会报差 '
      + fmt(A.projection.business_view - A.projection.sync_rows) + '。</p>'
      + '</div>';

    var c3 = '<div class="audit-card card">'
      + '<h3>③ 解读反复引用、库里没原文</h3>'
      + '<div class="audit-top"><span class="audit-num num">' + fmt(A.coverage.length) + '<small>篇</small></span>' + status('gap', '有差额') + '</div>'
      + '<p class="why">评论、解读文章里用《》点名 ≥' + A.min_mentions + ' 次的能源政策,在政策原文里按名字找不到——这是唯一能发现「根本没采到」的信号。</p>'
      + '<div class="hbars">' + A.coverage.map(function (c) {
        var w = (c.mentions / covMax) * 60;
        return '<div class="hbar" style="grid-template-columns:minmax(0,1fr) 90px" data-tip="' + esc('《' + c.name + '》被点名 ' + c.mentions + ' 次') + '" tabindex="0">'
          + '<span class="name" title="' + esc(c.name) + '">《' + esc(c.name) + '》</span>'
          + '<span class="track"><span class="fill" style="width:' + w + '%"></span><span class="v num" style="left:calc(' + w + '% + 6px)">' + c.mentions + ' 次</span></span></div>';
      }).join('') + '</div>'
      + '</div>';

    var staleRows = A.stale.map(function (x) {
      return '<tr><td class="nowrap">' + esc(x.kind) + '</td><td class="nowrap">' + esc(x.level) + '</td><td>' + esc(x.city) + '</td><td>' + esc(x.domain)
        + '</td><td class="nowrap num">' + esc(x.last) + '</td><td class="n">' + (x.age == null ? '—' : fmt(x.age)) + '</td><td class="n">' + fmt(x.limit) + '</td></tr>';
    }).join('');
    var c4 = '<div class="audit-card card">'
      + '<h3>④ 采集渠道停更</h3>'
      + '<div class="audit-top"><span class="audit-num num">' + fmt(broke.length) + '<small>条停更</small></span>' + status('gap', '有差额') + '</div>'
      + '<p class="why">看的是渠道最近一件的发文日,不是有没有产出:国家级 ' + A.stale_days['国家'] + ' 天、省级 ' + A.stale_days['省']
      + ' 天没有新件算停更(按数据截至日 ' + esc(A.today_used) + ' 算)。另有从未出件 ' + fmt(never.length) + ' 条;市级可疑 ' + fmt(A.city_suspect) + ' 条只统计不点名。</p>'
      + '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>类别</th><th>层级</th><th>机关</th><th>域名</th><th>最近一件</th><th>距今天数</th><th>限期</th></tr></thead><tbody>'
      + staleRows + '</tbody></table></div>'
      + '</div>';

    $('#audit-grid').innerHTML = c1 + c2 + c3 + c4;
    $('#audit-raw').innerHTML = '<summary>巡检原样输出(告警推送用的那段文字)</summary><pre class="raw">' + esc(A.report_text) + '</pre>';
    $('#audit-note').textContent = '豁免表(' + A.exemptions + ')三节都是空的:' + Object.keys(A.exemption_counts).map(function (k) { return k + ' ' + A.exemption_counts[k] + ' 条'; }).join('、')
      + ';渠道目录用本仓那份(' + A.catalog + ')。';

    function renderA1(q) {
      q = (q || '').trim().toLowerCase();
      var rows = A.derivation.filter(function (x) { return !q || (x.title + ' ' + x.pid).toLowerCase().indexOf(q) >= 0; });
      $('#a1-tbl tbody').innerHTML = rows.map(function (x) {
        return '<tr><td class="nowrap num">' + esc(x.date || '—') + '</td><td>' + titleLink(x.pid, x.title) + '<div class="muted num" style="font-size:12px">' + esc(x.pid) + '</div></td><td class="nowrap">'
          + esc(x.level) + '</td><td class="nowrap num">' + esc((x.fetched_at || '').slice(5)) + '</td></tr>';
      }).join('') || '<tr><td colspan="4" class="muted">没有匹配的</td></tr>';
    }
    renderA1('');
    $('#a1-q').addEventListener('input', function () { renderA1(this.value); });
  })();

  // ---------- 政策库:筛选 ----------
  var state = { q: '', level: '', prov: '', issuer: '', from: '', to: '', theme: '', status: '', sort: 'date_desc', page: 1 };
  var PAGE = 40;

  (function initFilters() {
    var provCount = {};
    ITEMS.forEach(function (it) { provCount[it.province] = (provCount[it.province] || 0) + 1; });
    var provs = Object.keys(provCount).sort(function (a, b) { return a === '全国' ? -1 : b === '全国' ? 1 : provCount[b] - provCount[a]; });
    $('#f-prov').innerHTML = '<option value="">全部</option>' + provs.map(function (p) { return '<option value="' + esc(p) + '">' + esc(p) + '(' + provCount[p] + ')</option>'; }).join('');
    var lvCount = {};
    ITEMS.forEach(function (it) { lvCount[it.level] = (lvCount[it.level] || 0) + 1; });
    $('#f-level').innerHTML = '<option value="">全部</option>' + LEVELS.filter(function (l) { return lvCount[l]; }).map(function (l) { return '<option value="' + l + '">' + l + '(' + lvCount[l] + ')</option>'; }).join('');
    var thCount = {}, noTheme = 0, noL2 = 0;
    ITEMS.forEach(function (it) {
      if (!it.l2) { noL2++; return; }
      if (!it.l2.themes.length) noTheme++;
      it.l2.themes.forEach(function (t) { thCount[t] = (thCount[t] || 0) + 1; });
    });
    $('#f-theme').innerHTML = '<option value="">全部</option>'
      + P.themes.filter(function (t) { return thCount[t.id]; }).sort(function (a, b) { return thCount[b.id] - thCount[a.id]; })
        .map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.zh) + '(' + thCount[t.id] + ')</option>'; }).join('')
      + '<option value="__none">有 L2、没挂主题(' + noTheme + ')</option><option value="__nol2">没有 L2(' + noL2 + ')</option>';
    $('#issuer-list').innerHTML = P.issuer_suggestions.map(function (s) { return '<option value="' + esc(s) + '"></option>'; }).join('');
    $('#lib-total').textContent = fmt(ITEMS.length);
    var excl = P.excluded.map(function (x) { return esc(x.reason) + ' ' + x.count + ' 条'; }).join('、');
    $('#lib-excluded').innerHTML = excl ? '没放进列表的:' + excl + '(链路件数照算)。' : '';
  })();

  function matches(it) {
    var s = state;
    if (s.level && it.level !== s.level) return false;
    if (s.prov && it.province !== s.prov) return false;
    if (s.from && (!it.date || it.date < s.from)) return false;
    if (s.to && (!it.date || it.date > s.to)) return false;
    if (s.issuer && it._issuer.indexOf(s.issuer) < 0) return false;
    if (s.theme) {
      if (s.theme === '__nol2') { if (it.l2) return false; }
      else if (s.theme === '__none') { if (!it.l2 || it.l2.themes.length) return false; }
      else if (!it.l2 || it.l2.themes.indexOf(s.theme) < 0) return false;
    }
    if (s.status) {
      var f = it.flags;
      if (s.status === 'qa_yes' && !f.in_platform) return false;
      if (s.status === 'qa_no' && f.in_platform) return false;
      if (s.status === 'impact' && !(it.l2 && Object.keys(it.l2.impact).length)) return false;
      if (s.status === 'collision' && !f.same_pid_files) return false;
      if (s.status === 'monthly' && !f.monthly) return false;
    }
    if (s.q) {
      var words = s.q.split(/\s+/);
      for (var i = 0; i < words.length; i++) if (words[i] && it._hay.indexOf(words[i]) < 0) return false;
    }
    return true;
  }

  function sorted(list) {
    var by = state.sort;
    return list.slice().sort(function (a, b) {
      if (by === 'imp_desc') {
        var ia = a.l2 && a.l2.importance != null ? a.l2.importance : -1, ib = b.l2 && b.l2.importance != null ? b.l2.importance : -1;
        if (ia !== ib) return ib - ia;
      }
      if (by === 'date_asc') return (a.date || '9999') < (b.date || '9999') ? -1 : (a.date || '9999') > (b.date || '9999') ? 1 : 0;
      return (a.date || '') < (b.date || '') ? 1 : (a.date || '') > (b.date || '') ? -1 : 0;
    });
  }

  function impDots(n) {
    if (n == null) return '';
    var h = '<span class="imp" data-tip="重要性 ' + n + ' / 5" aria-label="重要性 ' + n + ' / 5">';
    for (var i = 1; i <= 5; i++) h += '<i class="' + (i <= n ? 'on' : '') + '"></i>';
    return h + '</span>';
  }

  function renderList() {
    var list = sorted(ITEMS.filter(matches));
    var pages = Math.max(1, Math.ceil(list.length / PAGE));
    if (state.page > pages) state.page = pages;
    var slice = list.slice((state.page - 1) * PAGE, state.page * PAGE);
    $('#lib-count').innerHTML = '找到 <b class="num">' + fmt(list.length) + '</b> 条' + (list.length !== ITEMS.length ? '<span class="muted">(共 ' + fmt(ITEMS.length) + ' 条)</span>' : '');
    $('#results').innerHTML = slice.length ? slice.map(function (it) {
      var meta = [];
      meta.push('<span class="num">' + esc(it.date || '发文日缺失') + '</span>');
      meta.push(esc(it.level) + ' · ' + esc(it.province === '全国' ? '全国' : (it.region || it.province)));
      if (it.doc_no) meta.push(esc(it.doc_no));
      if (it.issuer.length) meta.push(esc(it.issuer.join('、')));
      var tags = '';
      if (it.l2) {
        tags += it.l2.themes.map(function (t) { return '<span class="chip' + (t === it.l2.primary_theme ? ' primary' : '') + '">' + esc(THEME_ZH[t] || t) + '</span>'; }).join('');
        tags += impDots(it.l2.importance);
      }
      if (it.flags.no_l2) tags += '<span class="flag">没有 L2,问答查不到</span>';
      else if (!it.flags.in_platform) tags += '<span class="flag">不在平台库</span>';
      if (it.flags.same_pid_files) tags += '<span class="flag quiet">编号撞车 ×' + it.flags.same_pid_files + '</span>';
      if (it.flags.monthly) tags += '<span class="chip">' + it.flags.monthly.map(issueLabel).join('、') + '</span>';
      return '<button type="button" class="res" data-open="' + it._i + '"><span class="t">' + esc(it.title) + '</span>'
        + '<span class="m">' + meta.join('<span class="sep">|</span>') + '</span>'
        + (tags ? '<span class="m">' + tags + '</span>' : '') + '</button>';
    }).join('') : '<div class="empty">没有符合条件的条目,换个条件试试。</div>';
    $('#pager').innerHTML = pages > 1
      ? '<button type="button" data-page="' + (state.page - 1) + '"' + (state.page <= 1 ? ' disabled' : '') + '>上一页</button>'
        + '<span class="num">第 ' + state.page + ' / ' + pages + ' 页</span>'
        + '<button type="button" data-page="' + (state.page + 1) + '"' + (state.page >= pages ? ' disabled' : '') + '>下一页</button>'
      : '';
  }

  var fieldMap = { 'f-q': 'q', 'f-level': 'level', 'f-prov': 'prov', 'f-issuer': 'issuer', 'f-from': 'from', 'f-to': 'to', 'f-theme': 'theme', 'f-status': 'status', 'f-sort': 'sort' };
  var debounce;
  Object.keys(fieldMap).forEach(function (id) {
    var el = document.getElementById(id);
    el.addEventListener(el.tagName === 'SELECT' || el.type === 'date' ? 'change' : 'input', function () {
      var key = fieldMap[id], v = el.value;
      state[key] = (key === 'q' || key === 'issuer') ? v.trim().toLowerCase() : v;
      state.page = 1;
      clearTimeout(debounce);
      debounce = setTimeout(renderList, key === 'q' || key === 'issuer' ? 120 : 0);
    });
  });
  $('#f-reset').addEventListener('click', function () {
    Object.keys(fieldMap).forEach(function (id) { var el = document.getElementById(id); el.value = id === 'f-sort' ? 'date_desc' : ''; });
    state = { q: '', level: '', prov: '', issuer: '', from: '', to: '', theme: '', status: '', sort: 'date_desc', page: 1 };
    renderList();
  });
  $('#pager').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-page]');
    if (!b || b.disabled) return;
    state.page = Number(b.dataset.page);
    renderList();
    var lib = $('#library');
    if (lib.scrollIntoView) lib.scrollIntoView({ block: 'start' });
  });
  renderList();

  // ---------- 详情抽屉 ----------
  var drawer = $('#drawer'), scrim = $('#scrim'), lastFocus = null;

  function stateRow(ok, text) { return '<div class="state">' + ICON[ok === true ? 'ok' : ok === false ? 'no' : 'info'] + '<span>' + text + '</span></div>'; }

  function detailHtml(it) {
    var f = it.flags, l2 = it.l2, s = it.summary;
    var h = '';
    h += '<div class="d-sec"><h4>基本信息</h4><dl class="d-grid">'
      + '<dt>编号</dt><dd class="num">' + esc(it.pid) + '</dd>'
      + '<dt>文号</dt><dd>' + (it.doc_no ? esc(it.doc_no) : '<span class="muted">无</span>') + '</dd>'
      + '<dt>发文机关</dt><dd>' + (it.issuer.length ? esc(it.issuer.join('、')) : '<span class="muted">原文没填</span>') + '</dd>'
      + '<dt>发文日</dt><dd class="num">' + (it.date ? esc(it.date) : '<span class="muted">缺失</span>') + '</dd>'
      + '<dt>层级 · 地区</dt><dd>' + esc(it.level) + ' · ' + esc(it.region || '—') + (it.province && it.province !== it.region && it.province !== '全国' ? '<span class="muted">(' + esc(it.province) + ')</span>' : '')
      + (it.region_code ? ' <span class="muted num">' + esc(it.region_code) + '</span>' : '') + '</dd>'
      + '<dt>来源</dt><dd>' + esc(SOURCE_TYPE[it.source_type] || '未标') + ' · ' + esc(it.site || '—') + '</dd>'
      + '<dt>入库</dt><dd class="num">' + esc(it.fetched_at || '—') + '</dd>'
      + '<dt>原文链接</dt><dd>' + (it.url ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer">打开原文网页</a> <span class="muted">(需要联网)</span>' : '—') + '</dd>'
      + '</dl></div>';

    h += '<div class="d-sec"><h4>摘要 / 要点</h4>';
    if (s && (s.text || s.one_liner)) {
      if (s.one_liner) h += '<p class="d-text"><b>' + esc(s.one_liner) + '</b>' + (s.reading_value ? '<span class="muted"> · 读点:' + esc(s.reading_value) + '</span>' : '') + '</p>';
      if (s.text) h += '<p class="d-text">' + esc(s.text) + '</p>';
    }
    if (l2 && l2.one_liner) h += '<p class="d-text">' + esc(l2.one_liner) + '</p>';
    if (it.excerpt) h += '<p class="d-quote"><span class="muted">正文开头(截断;联系方式和带职务称呼的句子已去掉):</span><br>' + esc(it.excerpt) + '</p>';
    if (!(s && s.text) && !(l2 && l2.one_liner) && !it.excerpt) h += '<p class="muted">没有摘要,正文多半在附件里;请看原文。</p>';
    h += '</div>';

    h += '<div class="d-sec"><h4>L2 主题与影响判断</h4>';
    if (l2) {
      h += '<div class="chips">' + (l2.themes.length ? l2.themes.map(function (t) {
        return '<span class="chip' + (t === l2.primary_theme ? ' primary' : '') + '">' + (t === l2.primary_theme ? '主 · ' : '') + esc(THEME_ZH[t] || t) + '</span>';
      }).join('') : '<span class="chip">没挂主题</span>')
        + '<span class="chip">重要性 <b class="num">' + (l2.importance == null ? '—' : l2.importance) + '</b>/5</span>'
        + (l2.action ? '<span class="chip">' + esc(ACTION[l2.action] || l2.action) + '</span>' : '')
        + l2.value_tags.map(function (v) { return '<span class="chip">' + esc(v) + '</span>'; }).join('')
        + '</div>';
      h += '<div class="scores">' + Object.keys(SCORE_NAMES).map(function (k) {
        var v = Number(l2.scores[k] || 0), bars = '';
        for (var i = 1; i <= 5; i++) bars += '<i class="' + (i <= v ? 'on' : '') + '"></i>';
        return '<div class="score"><span>' + k + ' ' + SCORE_NAMES[k] + ' <b class="num">' + v + '</b></span><span class="sbar">' + bars + '</span></div>';
      }).join('') + '</div>';
      var imp = Object.keys(l2.impact || {});
      if (imp.length) {
        h += '<div class="impact">' + imp.map(function (k) { return '<div><b>' + esc(IMPACT_ZH[k] || k) + '</b>' + esc(l2.impact[k]) + '</div>'; }).join('') + '</div>';
      } else {
        h += '<p class="muted" style="margin:6px 0 0">没过深度门,没有写影响分析' + (l2.archived ? '(综合分低,已归档)' : '') + '。</p>';
      }
      if (l2.advice.length) h += '<h4 style="margin-top:12px">行动建议</h4><ul class="advice">' + l2.advice.map(function (a) { return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>';
      h += '<p class="muted" style="font-size:12px;margin:10px 0 0">打分模型 ' + esc(l2.model || '—') + ' · ' + esc(l2.extracted_at || '') + '</p>';
    } else if (f.l2_on_other_file) {
      h += '<p class="muted">这个编号的 L2 是按同编号的另一篇算的,这一篇没有自己的 L2。</p>';
    } else {
      h += '<p class="muted">还没有 L2(守恒巡检①会点到它)。</p>';
    }
    h += '</div>';

    h += '<div class="d-sec"><h4>链路状态</h4><div class="state-list">';
    if (f.in_platform) h += stateRow(true, '已投影进平台库,问答查得到,政策大盘也统计它');
    else if (f.platform_rejected) h += stateRow(false, '有 L2,但同步时被拒:' + esc(f.platform_rejected));
    else if (f.no_l2) h += stateRow(false, '没有 L2,进不了平台库,问答查不到');
    else h += stateRow(false, '不在平台库:同编号按编号只存一篇,存的是《' + esc(f.platform_file_title || '') + '》');
    if (f.same_pid_files) h += stateRow(null, '编号撞车:同一个编号对应 ' + f.same_pid_files + ' 篇不同的文件,平台库和问答按编号只留得下一篇');
    if (f.monthly) h += stateRow(true, '进过月刊:' + f.monthly.map(issueLabel).join('、'));
    h += stateRow(true, '对外只读接口:原文在语料里(只出原文,不出上面的 L2)');
    h += '</div></div>';

    if (it.relations && it.relations.length) {
      h += '<div class="d-sec"><h4>相关政策(L2 关系)</h4><ul class="rel-list">' + it.relations.map(function (r) {
        var names = P.relation_types[r[0]] || [r[0], r[0]];
        var other = BY_PID[r[2]];
        return '<li><span class="rk">' + esc(r[1] === 'out' ? names[0] : names[1]) + '</span>' + (other ? titleLink(r[2], other.title) : esc(r[2])) + '</li>';
      }).join('') + '</ul></div>';
    }
    return h;
  }

  function openItem(i, fromHash) {
    var it = ITEMS[i];
    if (!it) return;
    $('#d-title').textContent = it.title;
    $('#d-body').innerHTML = detailHtml(it);
    $('#d-body').scrollTop = 0;
    drawer.hidden = false; scrim.hidden = false;
    document.body.style.overflow = 'hidden';
    $('#d-close').focus();
    if (!fromHash) {
      try { history.replaceState(null, '', '#pid=' + encodeURIComponent(it.pid)); } catch (e) { /* 双击打开时个别浏览器不让改网址 */ }
    }
  }
  function closeDrawer() {
    if (drawer.hidden) return;
    drawer.hidden = true; scrim.hidden = true;
    document.body.style.overflow = '';
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* 忽略 */ }
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-open]');
    if (!b) return;
    if (drawer.hidden) lastFocus = b;
    openItem(Number(b.dataset.open));
  });
  $('#d-close').addEventListener('click', closeDrawer);
  scrim.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });
  (function openFromHash() {
    var m = /pid=([^&]+)/.exec(location.hash);
    if (m) { var it = BY_PID[decodeURIComponent(m[1])]; if (it) openItem(it._i, true); }
  })();

  // ---------- 悬停提示 ----------
  var tip = document.createElement('div');
  tip.className = 'tip'; tip.hidden = true; tip.setAttribute('role', 'tooltip');
  document.body.appendChild(tip);
  function showTip(el, x, y) {
    tip.textContent = el.getAttribute('data-tip');
    tip.hidden = false;
    var r = tip.getBoundingClientRect();
    var left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x + 12));
    var top = y + 16 + r.height > window.innerHeight ? y - r.height - 10 : y + 16;
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
  }
  document.addEventListener('mousemove', function (e) {
    var el = e.target.closest && e.target.closest('[data-tip]');
    if (el) showTip(el, e.clientX, e.clientY); else tip.hidden = true;
  });
  document.addEventListener('focusin', function (e) {
    var el = e.target.closest && e.target.closest('[data-tip]');
    if (el) { var r = el.getBoundingClientRect(); showTip(el, r.left, r.bottom - 8); }
  });
  document.addEventListener('focusout', function () { tip.hidden = true; });
  window.addEventListener('scroll', function () { tip.hidden = true; }, { passive: true });
})();
