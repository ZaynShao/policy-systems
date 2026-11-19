/**
 * 月刊内容的两套 schema。
 *
 * 老数据是 v1(overview / quickList / policyBlocks / tipBoxes),新产线出的是
 * v2(monthly.v2)。两套要并存很久:已发布的历史刊不会重生成,而 v2 的字段是**改名**
 * 不是**加字段**(details[].reading 对 policyBlocks[].contentList),模板复用不了。
 *
 * 渲染判断放在这个纯模块里而不是 .vue 里,是为了能被 `node --test` 直接跑到——
 * 前端这边没有组件测试环境,逻辑留在 SFC 里就等于没有测试。
 */

export type MonthlySchema = 'v1' | 'v2';

export interface CaveatItem {
  where: string;
  notes: string[];
}

export interface CaveatBanner {
  show: boolean;
  text: string;
  items: CaveatItem[];
}

export interface V2Section {
  key: string;
  title: string;
  body: string;
}

export interface V2Advice {
  business: string;
  tag: string;
  text: string;
}

export interface V2Detail {
  no: string;
  title: string;
  link: string;
  info: string;
  reading: string;
  focus: string;
  advice: V2Advice[];
}

export interface V2View {
  narrative: string;
  sections: V2Section[];
  businessTakes: Array<{ business: string; text: string }>;
  quickTable: { head: string[]; rows: string[][] };
  details: V2Detail[];
}

const QUICK_HEAD = ['打分', '日期', '文件', '发文机关'];
const CN_NUM = ['一', '二', '三', '四', '五', '六', '七', '八'];

export const CAVEAT_TEXT =
  '本期部分内容由 AI 生成，下列部分可能不够符合要求，敬请谅解。' +
  '如有需要，可在页面下方提交修改意见，我们会据此再过一轮。';

/** 老数据没有 schema 字段;认不出的值一律按 v1 渲染,不能让页面白屏。 */
export function detectSchema(content: unknown): MonthlySchema {
  const schema = (content as { schema?: unknown } | null)?.schema;
  return schema === 'monthly.v2' ? 'v2' : 'v1';
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function arr<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/** 列表卡片的摘要。两套 schema 的概述都在 overview,但 v1 里带 markdown 强调符。 */
export function summaryText(content: unknown): string {
  const overview = str((content as { overview?: unknown } | null)?.overview);
  return overview.replace(/\*\*/gu, '').trim();
}

/** 列表卡片的「N 政策详情」。v2 没有 policyBlocks,不分辨就会显示成 0。 */
export function detailCount(content: unknown): number {
  const c = content as { policyBlocks?: unknown; details?: unknown } | null;
  return detectSchema(content) === 'v2'
    ? arr(c?.details).length
    : arr(c?.policyBlocks).length;
}

/** 列表卡片的标签。v2 不产 keywords,用本期真出过速判的业务线兜底。 */
export function extractKeywords(content: unknown): string[] {
  const c = content as Record<string, unknown> | null;
  const out: string[] = [];
  if (detectSchema(content) === 'v2') {
    for (const take of arr<{ business?: unknown }>(c?.businessTakes)) {
      const name = str(take?.business);
      if (name && !out.includes(name)) out.push(name);
    }
    return out;
  }
  for (const block of arr<{ keywords?: unknown }>(c?.policyBlocks)) {
    for (const kw of arr<unknown>(block?.keywords)) {
      const name = str(kw);
      if (name && !out.includes(name)) out.push(name);
    }
  }
  return out;
}

const PLAIN_LOCATIONS: Record<string, string> = {
  overview: '概述',
  localRoundup: '地方政策综述',
  appendix: '附录',
  uncovered: '已知未覆盖',
  pack: '素材装配',
  details: '政策详情',
  businessTakes: '业务速判',
  quickTable: '速览表',
};

const DETAIL_FIELDS: Record<string, string> = {
  info: '政策信息',
  reading: '政策解读',
  focus: '重点关注内容',
};

/**
 * 定位串转人话。
 *
 * caveats 里的 location 是给 MA7 定位用的机器串(details[01].reading)。
 * 直接摆给读者看,就是把内部字段名印在给决策层的材料上——那正是 D 门在禁的事。
 */
export function formatLocation(location: string): string {
  const loc = str(location).trim();
  if (PLAIN_LOCATIONS[loc]) return PLAIN_LOCATIONS[loc];

  const take = /^businessTakes\[(\d+)\]/u.exec(loc);
  if (take) return `业务速判 第 ${Number(take[1]) + 1} 条`;

  const quick = /^quickTable\[([^\]]+)\]/u.exec(loc);
  if (quick) return `速览表 第 ${quick[1]} 行`;

  const detail = /^details\[([^\]]+)\](?:\.(\w+))?/u.exec(loc);
  if (detail) {
    const no = detail[1];
    const advice = /\.advice\[(\d+)\]/u.exec(loc);
    if (advice) return `详情 ${no} · 决策建议 第 ${Number(advice[1]) + 1} 条`;
    const field = DETAIL_FIELDS[detail[2] ?? ''];
    return field ? `详情 ${no} · ${field}` : `详情 ${no}`;
  }
  return '其他段落';
}

/** 容错提示条。同一段有多条只列一次,免得一段三条问题在页面上刷成三行。 */
export function caveatBanner(content: unknown): CaveatBanner {
  const caveats = arr<{ location?: unknown; note?: unknown }>(
    (content as { caveats?: unknown } | null)?.caveats,
  );
  const byWhere = new Map<string, string[]>();
  for (const caveat of caveats) {
    const where = formatLocation(str(caveat?.location));
    const notes = byWhere.get(where) ?? [];
    const note = str(caveat?.note);
    if (note) notes.push(note);
    byWhere.set(where, notes);
  }
  const items = [...byWhere.entries()].map(([where, notes]) => ({ where, notes }));
  return { show: items.length > 0, text: CAVEAT_TEXT, items };
}

function section(key: string, title: string, body: unknown): V2Section | null {
  const text = str(body).trim();
  return text ? { key, title, body: text } : null;
}

/** v2 的视图模型:段落顺序固定,空段不出现(不留空标题),表格列数固定(不塌行)。 */
export function normalizeV2(content: unknown): V2View {
  const c = (content ?? {}) as Record<string, unknown>;
  const sections = [
    section('overview', '概述', c.overview),
    section('localRoundup', '地方政策综述', c.localRoundup),
    section('appendix', '附录', c.appendix),
    section('uncovered', '已知未覆盖', c.uncovered),
  ].filter((s): s is V2Section => s !== null);

  const rows = arr<Record<string, unknown>>(c.quickTable).map((row) => {
    const title = str(row.title);
    const docNo = str(row.doc_no);
    return [
      str(row.score),
      str(row.date),
      docNo ? `${title}(${docNo})` : title,
      str(row.issuer),
    ];
  });

  const details = arr<Record<string, unknown>>(c.details).map((det) => {
    const policyId = str(det.policyId);
    return {
      no: str(det.no),
      title: str(det.title),
      // 投影时映射不到 heng 的 Policy.id 就留空;宁可没链接,也不要链到别的政策上
      link: policyId ? `/policy?openId=${encodeURIComponent(policyId)}` : '',
      info: str(det.info),
      reading: str(det.reading),
      focus: str(det.focus),
      advice: arr<Record<string, unknown>>(det.advice).map((a) => ({
        business: str(a.business),
        tag: str(a.tag),
        text: str(a.text),
      })),
    };
  });

  return {
    narrative: str(c.narrative),
    sections,
    businessTakes: arr<Record<string, unknown>>(c.businessTakes).map((t) => ({
      business: str(t.business),
      text: str(t.text),
    })),
    quickTable: { head: QUICK_HEAD, rows },
    details,
  };
}

export interface V2Chapter {
  key: string;
  num: string;
  title: string;
  sub: string;
}

/**
 * 章节序号按**实际有内容的段**连编。
 *
 * 写死「三、政策详情」的话,某期没有速览表就会出现「一、二、四」;
 * 这在给决策层的材料上很显眼,而它只是渲染顺序的问题。
 */
export function v2Chapters(view: V2View): V2Chapter[] {
  const has = (key: string) => view.sections.some((s) => s.key === key);
  const candidates: Array<[boolean, string, string, string]> = [
    [has('overview') || view.businessTakes.length > 0, 'overview', '概述', 'OVERVIEW'],
    [view.quickTable.rows.length > 0, 'quickTable', '政策速览', 'POLICY OVERVIEW'],
    [view.details.length > 0, 'details', '政策详情', 'POLICY DETAILS'],
    [has('localRoundup'), 'localRoundup', '地方政策综述', 'LOCAL ROUNDUP'],
    [has('appendix'), 'appendix', '附录', 'APPENDIX'],
    [has('uncovered'), 'uncovered', '已知未覆盖', 'NOT COVERED'],
  ];
  return candidates
    .filter(([show]) => show)
    .map(([, key, title, sub], i) => ({ key, num: CN_NUM[i] ?? String(i + 1), title, sub }));
}
