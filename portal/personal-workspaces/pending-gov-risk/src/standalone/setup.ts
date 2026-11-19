// 独立版演示入口的准备工作(在 ../main 之前执行,见 ./main.ts):读页面里内置的演示数据、装上接口替身,
// 再在页面顶部挂一条醒目提示:演示数据是编的样例,不是真实工单。
import { installDemo, type DemoData } from './mock';
import './demo.css';

const el = document.getElementById('gov-risk-demo-data');
if (!el?.textContent) throw new Error('缺少内置演示数据(#gov-risk-demo-data)');
const data = JSON.parse(el.textContent) as DemoData;
installDemo(data);

const pkg = data.result.package || {};
const total = pkg.kpi?.cases ?? data.cases.cases.length;
const window_ = pkg.data_window ? `${pkg.data_window.from} 至 ${pkg.data_window.to}` : '';

const bar = document.createElement('div');
bar.className = 'gr-demo-bar';
bar.setAttribute('role', 'note');
const tag = document.createElement('b');
tag.className = 'gr-demo-tag';
tag.textContent = '演示版';
const head = document.createElement('strong');
head.textContent = '演示数据是编的样例,不是真实工单。';
const note = document.createElement('span');
note.textContent = `内置 ${total} 条编造的脱敏样例工单(${window_}),研判结果是用我的研判引擎在本机对这些样例算出来的`
  + `(${data.recorded_at} 录入;没配模型,逐条研判走规则兜底)。跟进、备注、重新研判只在本页生效,刷新即还原。`;
bar.append(tag, head, note);
document.body.classList.add('gr-demo');
document.body.prepend(bar);

// 提示条吸顶;左侧导航也吸顶,让它从提示条下面开始
const syncHeight = () => document.documentElement.style.setProperty('--gr-demo-bar-h', `${bar.offsetHeight}px`);
syncHeight();
if ('ResizeObserver' in window) new ResizeObserver(syncHeight).observe(bar);
