/* 政诉预判(原"工单系统性原因研判"):本地服务上传脱敏工单,平台研判;本页展示结果、下钻脱敏工单,并记录你对每个候选的跟进。
 * 数据只走 guardian 的 /guardian/api/gov-risk/*(平台登录会话 + 所有者校验),不落浏览器存储。
 * 页面上所有文本都用 textContent 写入,不拼 innerHTML。
 * 门户里切到别的子模块时这块 DOM 会被卸掉:mountGovRisk 返回 dispose,停轮询、清内存;卸载后迟到的请求不再续轮询。 */
export function mountGovRisk(root) {
  var API = '/guardian/api/gov-risk';
  var POLL_MS = 4000;
  var PAGE = 20;
  var STATUS = {
    new: '新发现', investigating: '核查中', confirmed: '根因确认', fixing: '整改中',
    fixed: '已修复', observing: '观察期', dismissed: '误报', closed: '关闭'
  };
  var FACTOR = {
    persistence: '持续出现', volume: '近期数量', spread: '扩散或集中', sensitivity: '监管敏感度',
    systemic: '像系统性问题', escalation: '升级诉求', regulator: '监管渠道占比',
    closed_but_recurring: '关单后仍出现', reference_case: '像已知案例'
  };
  var RUN_STATUS = { queued: '排队中', running: '研判中', succeeded: '已完成', failed: '失败', interrupted: '已中断' };
  var STAGE = { load: '读取数据', judge: '逐条研判', review: '候选复核', done: '收尾' };
  var LLM_REASON = {
    ai_not_configured: '平台没有配置模型密钥', ai_auth_invalid: '模型凭证无效', ai_insufficient_balance: '模型通道账户余额不足',
    ai_timeout: '模型请求超时', ai_rate_limited: '模型请求被限流', ai_unavailable: '模型服务不可用',
    ai_unparseable: '模型输出无法解析', too_many_failures: '连续失败,已停止调用'
  };
  var TEXT_FIELDS = [['description', '问题描述'], ['issue', '存在的具体问题'], ['demand', '诉求'], ['remark', '备注']];

  var state = {
    pkg: null, run: null, dataset: null, renderedRunId: null,
    feedback: { revision: 0, data: { candidates: {} } }, locked: false, pollTimer: null,
    dirty: {} // 有未保存编辑的候选;有它们时新结果不自动替换页面,免得冲掉正在写的备注
  };
  var disposed = false;

  function $(id) { return root.querySelector('#' + id); }

  function el(tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'className') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  // 门户是 Vue 应用,平台下拉 platform-select.js 不接管 Vue 根节点里的 select(怕和框架抢 DOM)。
  // 这里的 select 由本模块自己管:先脱离文档交给平台下拉,再把包好的节点放回原位;
  // 之后被移除时平台脚本会连同菜单一起收掉。平台脚本没加载时保留原生下拉。
  function platformSelect(sel) {
    var ps = window.PlatformSelect;
    if (!ps || sel.dataset.pfSelect === '1') return sel;
    var parent = sel.parentNode, next = sel.nextSibling;
    var holder = document.createElement('div');
    holder.appendChild(sel);
    ps.enhance(sel);
    var node = holder.firstChild;
    if (parent) parent.insertBefore(node, next);
    return node;
  }

  function enhanceFilters() {
    ['f-band', 'f-status', 'f-level'].forEach(function (id) { platformSelect($(id)); });
  }

  function p2(n) { return n < 10 ? '0' + n : String(n); }

  function fmtTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()) + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
  }

  function fmtDate(iso) { return fmtTime(iso).slice(0, 10); }

  function request(method, path, body) {
    var opts = { method: method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(API + path, opts).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var err = new Error((data && (data.message || data.reason)) || ('HTTP ' + res.status));
          err.status = res.status;
          err.reason = data && data.reason;
          throw err;
        }
        return data;
      });
    });
  }

  function explain(err) {
    if (err.status === 401) return '登录已失效,请重新登录平台后再打开本页。';
    if (err.reason === 'not_owner') return '这个工作台只对所有者开放。';
    if (err.reason === 'owner_not_configured') return '平台还没有配置这个工作台的所有者,请联系平台维护人。';
    if (err.reason === 'no_dataset') return '平台上还没有工单数据,先在本机运行 python3 -m gtr run 上传。';
    if (err.status === 429) return '操作过于频繁,请稍后再试。';
    if (err.status === 413) return '内容过大,无法保存。';
    return '读取或保存失败:' + err.message;
  }

  function setStatus(text, kind) {
    var s = $('save-status');
    s.textContent = text || '';
    s.className = 'gr-save' + (kind ? ' is-' + kind : '');
  }

  function isActive(run) { return !!run && (run.status === 'queued' || run.status === 'running'); }

  // ---------- 读取 ----------

  function load() {
    stopPoll();
    $('load-state').hidden = false;
    $('workspace').hidden = true;
    $('load-retry').hidden = true;
    $('load-message').textContent = '正在读取平台数据…';
    Promise.all([request('GET', '/package'), request('GET', '/feedback')]).then(function (r) {
      state.feedback = r[1] && r[1].data ? r[1] : { revision: 0, data: { candidates: {} } };
      if (!state.feedback.data.candidates) state.feedback.data.candidates = {};
      state.locked = false;
      $('conflict-banner').hidden = true;
      applyPackage(r[0] || {});
    }).catch(function (err) {
      $('load-message').textContent = explain(err);
      $('load-retry').hidden = false;
    });
  }

  function applyPackage(res) {
    state.pkg = res.package || null;
    state.run = res.run || null;
    state.dataset = res.dataset || null;
    renderRunBar();
    if (isActive(state.run)) schedulePoll();
    if (!state.pkg) {
      $('load-state').hidden = false;
      $('workspace').hidden = true;
      $('load-message').textContent = emptyMessage();
      $('load-retry').hidden = isActive(state.run);
      return;
    }
    state.renderedRunId = state.pkg.run && state.pkg.run.id;
    state.dirty = {};
    $('run-apply').hidden = true;
    $('load-state').hidden = true;
    $('workspace').hidden = false;
    render();
  }

  function emptyMessage() {
    if (!state.dataset) return '平台上还没有工单数据。在本机运行 python3 -m gtr run,把脱敏后的工单传上来,平台会自动研判。';
    if (isActive(state.run)) return '工单已上传,平台正在研判,完成后这里会自动显示结果。';
    if (state.run && state.run.status !== 'succeeded') return '上次研判没有完成:' + (state.run.error || '原因未知') + '。可以点上方的"重新研判"。';
    return '还没有研判结果,可以点上方的"重新研判"。';
  }

  // ---------- 研判状态与重跑 ----------

  function renderRunBar() {
    var bar = $('run-bar');
    bar.hidden = !state.dataset;
    if (!state.dataset) return;
    var d = state.dataset;
    var sources = (d.sources || []).map(function (s) { return s.channel + ' ' + s.n + ' 条'; }).join('、');
    $('run-data').textContent = '平台数据:' + d.caseCount + ' 条脱敏工单' + (sources ? '(' + sources + ')' : '') +
      ',本机上传于 ' + fmtTime(d.uploadedAt);
    var run = state.run, text = '还没有研判记录';
    if (run) {
      var p = run.progress || {};
      if (run.status === 'running') {
        text = '研判中:' + (STAGE[p.stage] || '准备') + (p.total ? ' ' + (p.done || 0) + '/' + p.total : '');
      } else if (run.status === 'queued') {
        text = '研判排队中';
      } else if (run.status === 'succeeded') {
        text = '最近一次研判 ' + fmtTime(run.finishedAt) + ' 完成(' + (run.trigger === 'manual' ? '手动' : '上传后自动') + ')';
      } else {
        text = '最近一次研判' + (RUN_STATUS[run.status] || run.status) + ':' + (run.error || '原因未知');
      }
    }
    var line = $('run-state');
    line.textContent = text;
    line.className = 'gr-run-state' + (isActive(run) ? ' is-busy' : run && run.status !== 'succeeded' ? ' is-error' : '');
    $('run-start').disabled = isActive(run);
  }

  function startRun() {
    var btn = $('run-start');
    btn.disabled = true;
    $('run-msg').textContent = '';
    request('POST', '/runs').then(function (res) {
      state.run = res.run;
      renderRunBar();
      $('run-msg').textContent = res.queued ? '已有一次研判在排队,数据会在那次里读到。' : '已开始研判,完成后自动刷新。';
      schedulePoll();
    }).catch(function (err) {
      btn.disabled = false;
      $('run-msg').textContent = explain(err);
    });
  }

  function schedulePoll() {
    stopPoll();
    if (disposed) return;
    state.pollTimer = setTimeout(pollRun, POLL_MS);
  }

  function stopPoll() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function pollRun() {
    state.pollTimer = null;
    request('GET', '/run').then(function (res) {
      state.run = res.run;
      state.dataset = res.dataset;
      renderRunBar();
      if (isActive(state.run)) { schedulePoll(); return; }
      if (state.run && state.run.status === 'succeeded' && state.run.id !== state.renderedRunId) {
        if (Object.keys(state.dirty).length && state.pkg) {
          $('run-msg').textContent = '新的研判结果已生成。你有还没保存的跟进,保存后点"载入新结果"。';
          $('run-apply').hidden = false;
        } else {
          loadLatest();
        }
      } else if (!state.pkg) {
        $('load-message').textContent = emptyMessage();
        $('load-retry').hidden = false;
      }
    }).catch(function (err) {
      if (err.status === 401 || err.status === 403) { $('run-msg').textContent = explain(err); return; }
      schedulePoll(); // 网络抖动:继续等
    });
  }

  function loadLatest() {
    request('GET', '/package').then(function (res) {
      $('run-msg').textContent = '';
      applyPackage(res);
    }).catch(function (err) { $('run-msg').textContent = explain(err); });
  }

  // ---------- 渲染 ----------

  function render() {
    var pkg = state.pkg;
    var w = pkg.data_window || {};
    $('meta-line').textContent = '数据范围 ' + (w.from || '?') + ' 至 ' + (w.to || '?') + ' · 结论生成于 ' + fmtTime(pkg.generated_at);
    renderKpi(pkg.kpi || {});
    fillStatusFilter();
    renderCandidates();
    renderRefs(pkg.reference_cases || []);
    renderOverview(pkg.overview || {});
    renderMethod(pkg);
  }

  function renderKpi(k) {
    var box = $('kpi');
    box.textContent = '';
    [
      ['高优先候选', k.candidates_high, 'gr-stat-danger'],
      ['中优先候选', k.candidates_medium, 'gr-stat-warn'],
      ['关单后仍出现(高优先)', k.recurring_after_close_high, 'gr-stat-danger'],
      ['修复后复发', k.recurred_after_fix, 'gr-stat-danger'],
      ['高优先涉及未结工单', k.open_cases_in_high, '']
    ].forEach(function (x) {
      box.appendChild(el('div', { className: 'gr-stat ' + x[2] }, el('span', { text: x[0] }), el('strong', { text: String(x[1] || 0) })));
    });
  }

  function fillStatusFilter() {
    var sel = $('f-status');
    if (sel.options.length > 1) return;
    Object.keys(STATUS).forEach(function (k) { sel.appendChild(el('option', { value: k, text: STATUS[k] })); });
  }

  function currentStatus(c) {
    var fb = state.feedback.data.candidates[c.id];
    return (fb && fb.status) || c.status || 'new';
  }

  function renderCandidates() {
    var list = $('cand-list');
    list.textContent = '';
    var band = $('f-band').value, status = $('f-status').value, level = $('f-level').value;
    var shown = 0;
    (state.pkg.candidates || []).forEach(function (c) {
      if (band && c.band !== band) return;
      if (status && currentStatus(c) !== status) return;
      if (level && c.level !== level) return;
      list.appendChild(candidateCard(c));
      shown++;
    });
    $('cand-empty').hidden = shown > 0;
  }

  function objectText(c) {
    if (c.level !== 'object') return '';
    if (c.object_type === '运营商') return '运营商 ' + (c.object_label || c.object_code || '');
    return (c.object_type || '对象') + ' ' + (c.object_code || '');
  }

  function title(c) {
    if (c.review && c.review.title) return c.review.title;
    return c.symptom_label + (c.level === 'object' ? '(集中在同一' + (c.object_type || '对象') + ')' : '');
  }

  function candidateCard(c) {
    var st = c.stats || {};
    var status = currentStatus(c);
    var statusPill = el('span', { className: 'gr-pill', text: STATUS[status] || status });
    var head = el('div', { className: 'gr-cand-head' },
      el('span', { className: 'gr-band gr-band-' + c.band, text: c.band + ' ' + c.score }),
      el('h3', { text: title(c) }),
      statusPill,
      c.recurred_after_fix ? el('span', { className: 'gr-pill gr-pill-alert', text: '修复后复发 ' + c.recurred_after_fix + ' 条' }) : null,
      st.recurring_after_close ? el('span', { className: 'gr-pill gr-pill-warn', text: '关单后仍在出现' }) : null,
      c.level === 'object' ? el('span', { className: 'gr-pill', text: objectText(c) }) : null
    );
    var channels = Object.keys(st.channels || {}).map(function (k) { return k + ' ' + st.channels[k]; }).join('、');
    var facts = el('p', { className: 'gr-facts', text:
      (st.n || 0) + ' 条' + (channels ? '(' + channels + ')' : '') + ' · 近 90 天 ' + (st.n_90d || 0) + ' 条(此前 90 天 ' + (st.n_prev_90d || 0) +
      ' 条)· 近 6 个月有 ' + (st.active_months_6 || 0) + ' 个月出现 · 已解决 ' + (st.resolved || 0) + ' 条,首次关单后又新增 ' +
      (st.after_first_close || 0) + ' 条 · 涉及 ' + (st.stations || 0) + ' 个场站、' + (st.cities || 0) + ' 个城市' });

    var left = el('div', null);
    left.appendChild(el('p', { className: 'gr-block-title', text: '按月出现情况' }));
    left.appendChild(spark(st.months || {}));
    left.appendChild(el('p', { className: 'gr-block-title', text: '可能机理(逐条研判的分布)' }));
    (c.mechanisms || []).forEach(function (m) {
      var pct = Math.round((m.weight || 0) * 100);
      var meter = el('div', { className: 'gr-meter' }, el('i', { style: 'width:' + pct + '%' }));
      left.appendChild(el('div', { className: 'gr-mech' }, el('span', { text: m.label }), meter, el('span', { className: 'gr-num', text: pct + '%' })));
    });
    if (!(c.mechanisms || []).length) left.appendChild(el('p', { className: 'gr-text', text: '暂无' }));
    left.appendChild(el('p', { className: 'gr-block-title', text: '鉴别线索' }));
    var clues = el('ul', { className: 'gr-list' });
    (c.clues || []).forEach(function (x) {
      clues.appendChild(el('li', { text: x.label + ' ' + x.n + ' 条' + (x.points_to && x.points_to.length ? ' → 指向 ' + x.points_to.join('、') : '') }));
    });
    left.appendChild((c.clues || []).length ? clues : el('p', { className: 'gr-text', text: '文本里没有明确的鉴别线索,需要调订单和设备数据核查。' }));

    var right = el('div', null);
    var rv = c.review;
    if (rv) {
      right.appendChild(el('p', { className: 'gr-block-title', text: '模型复核结论(把握:' + (rv.confidence || '中') + ')' }));
      right.appendChild(el('p', { className: 'gr-text', text: rv.summary || '' }));
      if (rv.why_early) right.appendChild(el('p', { className: 'gr-text', text: '为什么现在处理:' + rv.why_early }));
      if (rv.owner) right.appendChild(el('p', { className: 'gr-text', text: '建议牵头:' + rv.owner }));
    } else {
      right.appendChild(el('p', { className: 'gr-block-title', text: '模型复核' }));
      right.appendChild(el('p', { className: 'gr-text', text: '本期未做模型复核,下面是按可能机理给出的核查建议。' }));
    }
    right.appendChild(el('p', { className: 'gr-block-title', text: '建议核查' }));
    var steps = el('ol', { className: 'gr-list' });
    var stepTexts = rv && rv.verification_steps && rv.verification_steps.length ? rv.verification_steps
      : (c.verify_steps || []).map(function (s) { return s.step; });
    stepTexts.forEach(function (s) { steps.appendChild(el('li', { text: s })); });
    right.appendChild(steps);
    if ((c.reference_matches || []).length) {
      right.appendChild(el('p', { className: 'gr-block-title', text: '与已知案例相似' }));
      var refs = el('div', { className: 'gr-refs' });
      c.reference_matches.forEach(function (r) { refs.appendChild(el('span', { className: 'gr-pill gr-pill-warn', text: r.title + ':' + r.why })); });
      right.appendChild(refs);
    }

    return el('article', { className: 'gr-cand' }, head, facts,
      el('div', { className: 'gr-cols' }, left, right), followEditor(c, statusPill), casesBlock(c));
  }

  function spark(months) {
    var keys = Object.keys(months).sort();
    var all = monthRange(keys[0], (state.pkg.data_window || {}).to || keys[keys.length - 1]);
    var max = 1;
    all.forEach(function (k) { max = Math.max(max, months[k] || 0); });
    var bars = el('div', { className: 'gr-spark', role: 'img', 'aria-label': all.map(function (k) { return k + ' ' + (months[k] || 0) + ' 条'; }).join(',') });
    all.forEach(function (k) {
      var v = months[k] || 0;
      bars.appendChild(el('span', { className: v ? '' : 'is-zero', style: 'height:' + Math.round(v / max * 40) + 'px', title: k + ':' + v + ' 条' }));
    });
    var axis = el('div', { className: 'gr-spark-axis' }, el('span', { text: all[0] || '' }), el('span', { text: all[all.length - 1] || '' }));
    return el('div', null, bars, axis);
  }

  function monthRange(from, to) {
    if (!from) return [];
    var out = [], y = +from.slice(0, 4), m = +from.slice(5, 7), ty = +(to || from).slice(0, 4), tm = +(to || from).slice(5, 7);
    while ((y < ty || (y === ty && m <= tm)) && out.length < 36) {
      out.push(y + '-' + p2(m));
      m++; if (m > 12) { m = 1; y++; }
    }
    return out;
  }

  // ---------- 下钻:候选下的脱敏工单 ----------

  function casesBlock(c) {
    var ids = c.case_ids || [];
    var box = el('details', { className: 'gr-more' }, el('summary', { text: '查看这类工单 ' + ids.length + ' 条(脱敏,最新在前)' }));
    var list = el('div', { className: 'gr-cases' });
    var more = el('button', { type: 'button', className: 'gr-btn', text: '再看 ' + PAGE + ' 条' });
    var msg = el('p', { className: 'gr-follow-msg', role: 'status' });
    var copy = el('button', { type: 'button', className: 'gr-btn', text: '复制全部映射编号' });
    var loaded = 0, busy = false;
    more.hidden = true;

    function next() {
      if (busy || loaded >= ids.length) return;
      busy = true;
      more.disabled = true;
      msg.textContent = '正在读取…';
      msg.className = 'gr-follow-msg';
      var batch = ids.slice(loaded, loaded + PAGE);
      request('GET', '/cases?ids=' + encodeURIComponent(batch.join(','))).then(function (res) {
        var byId = {};
        (res.cases || []).forEach(function (x) { byId[x.case_id] = x; });
        batch.forEach(function (id) { list.appendChild(byId[id] ? caseRow(byId[id]) : missingRow(id)); });
        loaded += batch.length;
        msg.textContent = '';
        more.hidden = loaded >= ids.length;
      }).catch(function (err) {
        msg.textContent = explain(err);
        msg.className = 'gr-follow-msg is-error';
      }).then(function () {
        busy = false;
        more.disabled = false;
      });
    }

    box.addEventListener('toggle', function () { if (box.open && !loaded) next(); });
    more.addEventListener('click', next);
    copy.addEventListener('click', function () { copyText(ids.join('\n'), copy, '复制全部映射编号'); });
    box.appendChild(list);
    box.appendChild(el('div', { className: 'gr-case-actions' }, more, copy));
    box.appendChild(msg);
    box.appendChild(el('p', { className: 'gr-breakdown', text: '评分构成:' + Object.keys(c.score_breakdown || {}).map(function (k) {
      return (FACTOR[k] || k) + ' ' + c.score_breakdown[k];
    }).join(';') + '。回查真实工单和场站:在本机运行 python3 -m gtr lookup 编号,或 python3 -m gtr report 生成带原单链接的本地看板。' }));
    return box;
  }

  function caseRow(x) {
    var meta = [fmtDate(x.created_at), x.channel, x.dept_type, x.city].filter(Boolean).join(' · ');
    var closed = [x.status, x.resolution].filter(Boolean).join(' / ');
    var head = el('div', { className: 'gr-case-head' },
      el('code', { text: x.case_id }),
      el('span', { text: meta }),
      x.station_code ? el('span', { className: 'gr-pill', text: '场站 ' + x.station_code }) : null,
      closed ? el('span', { className: 'gr-muted', text: closed }) : null);
    var body = el('div', { className: 'gr-case-body' });
    TEXT_FIELDS.forEach(function (f) {
      var t = (x.text || {})[f[0]];
      if (t) body.appendChild(el('p', { className: 'gr-case-text' }, el('b', { text: f[1] + ':' }), t));
    });
    var j = x.judgment;
    if (j) {
      var mech = (j.mechanisms || []).filter(function (m) { return m.code !== 'M_UNKNOWN'; })
        .map(function (m) { return m.label.split('(')[0] + ' ' + Math.round((m.confidence || 0) * 100) + '%'; }).join('、');
      var clue = (j.clues || []).map(function (k) { return k.label; }).join('、');
      body.appendChild(el('p', { className: 'gr-case-judge', text:
        (j.source === 'model' ? '模型研判' : '规则判断') + ':' + (j.summary || (j.symptoms || []).map(function (s) { return s.label; }).join('、')) +
        (mech ? ' · 可能机理 ' + mech : '') + (clue ? ' · 线索 ' + clue : '') +
        (j.operator ? ' · 运营商 ' + j.operator : '') + ' · 像系统性问题:' + (j.systemic_likelihood || '中') }));
    }
    return el('div', { className: 'gr-case' }, head, body);
  }

  function missingRow(id) {
    return el('div', { className: 'gr-case' }, el('div', { className: 'gr-case-head' }, el('code', { text: id }),
      el('span', { className: 'gr-muted', text: '平台上已没有这条(可能在之后的上传里被移除)' })));
  }

  function copyText(text, btn, label) {
    var done = function () { btn.textContent = '已复制'; setTimeout(function () { btn.textContent = label; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { btn.textContent = '复制失败,请手动选择'; });
    } else {
      btn.textContent = '浏览器不支持一键复制';
    }
  }

  // ---------- 跟进 ----------

  function followEditor(c, statusPill) {
    var fb = state.feedback.data.candidates[c.id] || {};
    var sel = el('select', { 'aria-label': '跟进状态' });
    Object.keys(STATUS).forEach(function (k) { sel.appendChild(el('option', { value: k, text: STATUS[k] })); });
    sel.value = currentStatus(c);
    var selBox = platformSelect(sel);
    var note = el('textarea', { 'aria-label': '跟进备注', maxlength: '500', placeholder: '核查结论、确认的根因或下一步' });
    note.value = fb.note || '';
    var save = el('button', { type: 'button', className: 'gr-btn gr-btn-primary', text: '保存跟进' });
    var msg = el('p', { className: 'gr-follow-msg', text: fb.updated_at ? '上次更新 ' + fmtTime(fb.updated_at)
      : '标成"已修复"后,观察期内同类再出现,下次研判会标为复发。' });
    var markDirty = function () { state.dirty[c.id] = true; };
    sel.addEventListener('change', markDirty);
    note.addEventListener('input', markDirty);
    save.addEventListener('click', function () { saveFollow(c, sel, note, save, msg, statusPill); });
    return el('div', { className: 'gr-follow' }, selBox, note, save, msg);
  }

  function saveFollow(c, sel, note, btn, msg, statusPill) {
    if (state.locked) return;
    var text = note.value.trim();
    if (text.length > 500) { msg.textContent = '备注不能超过 500 字。'; msg.className = 'gr-follow-msg is-error'; return; }
    var next = JSON.parse(JSON.stringify(state.feedback.data));
    next.candidates[c.id] = { status: sel.value, note: text, updated_at: new Date().toISOString() };
    btn.disabled = true;
    setStatus('正在保存…', 'busy');
    request('PUT', '/feedback', { revision: state.feedback.revision, data: next }).then(function (res) {
      state.feedback = res;
      delete state.dirty[c.id];
      btn.disabled = false;
      statusPill.textContent = STATUS[sel.value] || sel.value;
      msg.textContent = '已保存 ' + fmtTime(res.updatedAt || new Date().toISOString());
      msg.className = 'gr-follow-msg';
      setStatus('已保存', 'ok');
    }).catch(function (err) {
      btn.disabled = false;
      if (err.status === 409) {
        state.locked = true;
        $('conflict-banner').hidden = false;
        setStatus('有冲突,暂停保存', 'error');
        return;
      }
      msg.textContent = explain(err) + ' 你的修改还在,可以再点保存。';
      msg.className = 'gr-follow-msg is-error';
      setStatus('保存失败', 'error');
    });
  }

  // ---------- 其余区块 ----------

  function renderRefs(refs) {
    var box = $('ref-list');
    box.textContent = '';
    if (!refs.length) { box.appendChild(el('p', { className: 'gr-empty', text: '案例库为空。在本机 ~/.config/gov-ticket-risk/reference_cases.json 里维护,随下次上传同步。' })); return; }
    var vocab = (state.pkg.vocab || {});
    refs.forEach(function (r) {
      var mech = (r.mechanisms || []).map(function (m) { return (vocab.mechanisms || {})[m] || m; }).join('、');
      box.appendChild(el('div', { className: 'gr-cand' },
        el('div', { className: 'gr-cand-head' }, el('h3', { text: r.title || r.id }), r.consequence ? el('span', { className: 'gr-pill', text: r.consequence }) : null),
        el('p', { className: 'gr-facts', text: '现象:' + ((vocab.symptoms || {})[r.symptom] || r.symptom || '') + (mech ? ' · 机理:' + mech : '') }),
        el('p', { className: 'gr-text', text: r.summary || '' })));
    });
  }

  function renderOverview(ov) {
    var cells = ov.matrix || [];
    var depts = [], syms = [], map = {};
    cells.forEach(function (x) {
      if (depts.indexOf(x.dept_type) < 0) depts.push(x.dept_type);
      if (syms.indexOf(x.symptom_label) < 0) syms.push(x.symptom_label);
      map[x.symptom_label + '|' + x.dept_type] = String(x.n);
    });
    var table = el('table', { className: 'gr-matrix' });
    var hr = el('tr', null, el('th', { text: '现象' }));
    depts.forEach(function (d) { hr.appendChild(el('th', { text: d })); });
    table.appendChild(el('thead', null, hr));
    var body = el('tbody', null);
    syms.forEach(function (s) {
      var tr = el('tr', null, el('td', { text: s }));
      depts.forEach(function (d) { tr.appendChild(el('td', { text: map[s + '|' + d] || '' })); });
      body.appendChild(tr);
    });
    table.appendChild(body);
    $('matrix').textContent = '';
    $('matrix').appendChild(table);

    var trend = ov.trend || [], max = 1;
    trend.forEach(function (t) { max = Math.max(max, t.n || 0); });
    var bars = $('trend');
    bars.textContent = '';
    bars.setAttribute('role', 'img');
    bars.setAttribute('aria-label', trend.map(function (t) { return t.month + ' ' + t.n + ' 条'; }).join(','));
    var axis = el('div', { className: 'gr-trend-x' });
    trend.forEach(function (t) {
      bars.appendChild(el('div', { className: 'gr-trend-col' }, el('b', { text: String(t.n) }),
        el('span', { style: 'height:' + Math.round((t.n || 0) / max * 96) + 'px', title: t.month + ':' + t.n + ' 条,其中像系统性问题 ' + (t.systemic_high || 0) + ' 条' })));
      axis.appendChild(el('span', { text: (t.month || '').slice(2) }));
    });
    if (bars.nextSibling && bars.nextSibling.className === 'gr-trend-x') bars.parentNode.removeChild(bars.nextSibling);
    bars.parentNode.insertBefore(axis, bars.nextSibling);
  }

  function renderMethod(pkg) {
    var m = pkg.method || {};
    var judged = m.model
      ? ('模型 ' + (m.models && m.models.length ? m.models.join('、') : m.model) + ' 研判 ' + (m.judged_by_model || 0) + ' 条(本次新标 ' +
        (m.judged_new || 0) + ' 条,其余正文没变、沿用上次),规则兜底 ' + (m.judged_by_rules || 0) + ' 条')
      : ('未用模型,全部 ' + (m.judged_by_rules || 0) + ' 条按规则判断');
    var rows = [
      ['数据来源', (pkg.sources || []).map(function (s) { return s.channel + ' ' + s.n + ' 条'; }).join('、')],
      ['研判方式', judged + (m.judge_deferred ? ';超出单次额度 ' + m.judge_deferred + ' 条,下次研判补上' : '')],
      ['模型复核', (m.reviewed || 0) + ' 个候选' + (m.review_failed ? ',' + m.review_failed + ' 个没成功' : '')],
      ['提示词版本', (m.judge_prompt || '') + ' / ' + (m.review_prompt || '')],
      ['数据边界', '平台上存的是本机脱敏后的工单:映射编号代替工单号,去掉了手机号、证件号、车牌、订单号等长编号、邮箱、链接、人名,地址和场站名换成场站编码。真实工单号和场站名只在本机。'],
      ['说明', '机理是根据投诉文本推断的待核查假设,不是定性结论;最终以订单、设备数据核查为准。']
    ];
    if (m.breaker) rows.push(['模型通道', (LLM_REASON[m.breaker] || m.breaker) + ',本次没标到的工单按规则兜底。']);
    if ((m.errors || []).length) rows.push(['模型通道报错', m.errors.map(function (e) { return LLM_REASON[e] || e; }).join(';')]);
    var dl = el('dl', { className: 'gr-dl' });
    rows.forEach(function (r) { dl.appendChild(el('dt', { text: r[0] })); dl.appendChild(el('dd', { text: r[1] })); });
    $('method').textContent = '';
    $('method').appendChild(dl);
  }

  ['f-band', 'f-status', 'f-level'].forEach(function (id) { $(id).addEventListener('change', renderCandidates); });
  $('load-retry').addEventListener('click', load);
  $('conflict-reload').addEventListener('click', load);
  $('run-start').addEventListener('click', startRun);
  $('run-apply').addEventListener('click', loadLatest);
  function release() {
    stopPoll();
    state.pkg = null;
    state.feedback = { revision: 0, data: { candidates: {} } };
  }
  window.addEventListener('pagehide', release);
  if (window.PlatformSelect) enhanceFilters();
  else window.addEventListener('load', enhanceFilters, { once: true });
  load();

  return function dispose() {
    disposed = true;
    window.removeEventListener('pagehide', release);
    window.removeEventListener('load', enhanceFilters);
    release();
  };
}
