import assert from 'node:assert/strict';
import { readFile, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function loadModule() {
  const filename = path.join(frontendRoot, 'src/views/monthly/monthly-content.ts');
  const output = ts.transpileModule(await readFile(filename, 'utf8'), {
    fileName: filename,
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const artifact = path.join(frontendRoot, `.monthly-content-${process.pid}-${Date.now()}.mjs`);
  await writeFile(artifact, output, 'utf8');
  try {
    return await import(`${pathToFileURL(artifact).href}?v=${Date.now()}`);
  } finally {
    await unlink(artifact).catch(() => {});
  }
}

const { detectSchema, summaryText, detailCount, extractKeywords, caveatBanner, formatLocation, normalizeV2 } =
  await loadModule();

const V1 = {
  overview: '四月概述。',
  quickList: [{ category: '国家级', policyTitle: '甲' }],
  policyBlocks: [{ no: '01', title: '甲', keywords: ['节能', '降碳'], info: '', focus: '' }],
};

const V2 = {
  schema: 'monthly.v2',
  month: '2026-07',
  narrative: '本月定调',
  overview: '七月概述。',
  businessTakes: [{ business: '充电', text: '备案口径要摸清。' }],
  quickTable: [{ no: '01', level: '国家级', score: '5分', title: '甲', issuer: '国家能源局', date: '2026-07-23', doc_no: '发改能源〔2026〕1号' }],
  details: [{ no: '01', policyId: 'cuid-1', pipelinePid: 'P_A', title: '甲文件', info: '发文机关:国家能源局。', reading: '改了口径。', focus: '第三条。', advice: [{ business: '充电', tag: 'B 研究/跟进', text: '跟进备案。' }] }],
  localRoundup: '江苏等省集中调整。',
  appendix: '国务院专题学习。',
  uncovered: '',
  caveats: [],
};

// ── 分辨新旧 ────────────────────────────────────────────────────
test('老数据没有 schema 字段,必须走 v1 分支', () => {
  assert.equal(detectSchema(V1), 'v1');
  assert.equal(detectSchema({}), 'v1');
  assert.equal(detectSchema(null), 'v1');
});

test('新数据按 schema 认成 v2', () => {
  assert.equal(detectSchema(V2), 'v2');
});

test('认不出的 schema 值当 v1 处理,不能白屏', () => {
  assert.equal(detectSchema({ schema: 'monthly.v9' }), 'v1');
});

// ── 列表卡片两套 schema 都要有数 ────────────────────────────────
test('列表卡片的摘要与篇数对 v1 仍然对', () => {
  assert.match(summaryText(V1), /四月概述/u);
  assert.equal(detailCount(V1), 1);
  assert.deepEqual(extractKeywords(V1), ['节能', '降碳']);
});

test('v2 没有 policyBlocks,列表卡片不能因此显示 0 篇', () => {
  assert.match(summaryText(V2), /七月概述/u);
  assert.equal(detailCount(V2), 1, 'v2 的篇数要数 details');
});

test('v2 没有 keywords 字段,用业务线名兜底而不是空数组', () => {
  assert.deepEqual(extractKeywords(V2), ['充电']);
});

test('内容缺字段时列表不炸', () => {
  assert.equal(summaryText(undefined), '');
  assert.equal(detailCount(undefined), 0);
  assert.deepEqual(extractKeywords({ schema: 'monthly.v2' }), []);
});

// ── 容错提示条 ─────────────────────────────────────────────────
test('没有 caveats 就不出提示条', () => {
  assert.equal(caveatBanner(V2).show, false);
  assert.equal(caveatBanner(V1).show, false);
});

test('有 caveats 时出提示条,并说清是 AI 出稿', () => {
  const b = caveatBanner({ ...V2, caveats: [{ gate: 'F', location: 'details[01].reading', note: '某数字未能回指原文' }] });
  assert.equal(b.show, true);
  assert.match(b.text, /AI/u);
  assert.match(b.text, /敬请谅解/u);
});

test('提示条上不能出现 details\\[01\\].reading 这种机器串', () => {
  const b = caveatBanner({ ...V2, caveats: [
    { gate: 'F', location: 'details[01].reading', note: 'x' },
    { gate: 'D', location: 'businessTakes[0].text', note: 'y' },
    { gate: 'F', location: 'quickTable[02]', note: 'z' },
  ] });
  assert.equal(b.items.length, 3);
  for (const item of b.items) {
    assert.doesNotMatch(item.where, /\[|\]|details|businessTakes|quickTable/u, item.where);
  }
});

test('同一段有多条只列一次', () => {
  const b = caveatBanner({ ...V2, caveats: [
    { gate: 'F', location: 'details[01].reading', note: 'a' },
    { gate: 'D', location: 'details[01].reading', note: 'b' },
  ] });
  assert.equal(b.items.length, 1);
});

// ── 定位串转人话 ───────────────────────────────────────────────
test('每种定位串都要有人话', () => {
  const cases = [
    ['overview', /概述/u],
    ['businessTakes[0].text', /业务速判/u],
    ['localRoundup', /地方/u],
    ['appendix', /附录/u],
    ['details[01].info', /政策信息/u],
    ['details[01].reading', /政策解读/u],
    ['details[01].focus', /重点关注/u],
    ['details[01].advice[0].text', /决策建议/u],
    ['quickTable[02]', /速览/u],
    ['pack', /素材/u],
  ];
  for (const [loc, re] of cases) {
    const out = formatLocation(loc);
    assert.match(out, re, loc);
    assert.doesNotMatch(out, /\[|\]/u, `${loc} → ${out} 仍带方括号`);
  }
});

test('没见过的定位串也不能把原串直接抛给读者', () => {
  const out = formatLocation('someNewBlock[3].x');
  assert.doesNotMatch(out, /\[|\]/u);
  assert.ok(out.length > 0);
});

// ── v2 视图模型 ────────────────────────────────────────────────
test('normalizeV2 给出稳定的段落顺序,空段落不出现', () => {
  const v = normalizeV2({ ...V2, localRoundup: '', appendix: '' });
  const titles = v.sections.map((s) => s.title);
  assert.ok(titles.includes('概述'));
  assert.ok(!titles.includes('地方政策综述'));
  assert.ok(!titles.includes('附录'));
});

test('速览表列头与列数固定,缺字段补空串不塌行', () => {
  const v = normalizeV2({ ...V2, quickTable: [{ no: '01', title: '甲' }] });
  assert.deepEqual(v.quickTable.head, ['打分', '日期', '文件', '发文机关']);
  assert.equal(v.quickTable.rows[0].length, 4);
  assert.ok(v.quickTable.rows[0].every((c) => typeof c === 'string'));
});

test('文号跟在文件名后,与公文成品一致', () => {
  const v = normalizeV2(V2);
  assert.match(v.quickTable.rows[0][2], /甲（?发改能源〔2026〕1号）?|甲\(发改能源〔2026〕1号\)/u);
});

test('详情里的 policyId 为空时不给链接', () => {
  const v = normalizeV2({ ...V2, details: [{ ...V2.details[0], policyId: '' }] });
  assert.equal(v.details[0].link, '');
  const withLink = normalizeV2(V2);
  assert.match(withLink.details[0].link, /cuid-1/u);
});

// ── 章节序号 ───────────────────────────────────────────────────
const { v2Chapters } = await loadModule();

test('章节序号按实际有内容的段连编,不跳号', () => {
  const view = normalizeV2({ ...V2, quickTable: [], localRoundup: '', appendix: '' });
  const chapters = v2Chapters(view);
  assert.deepEqual(chapters.map((c) => c.num), ['一', '二']);
  assert.deepEqual(chapters.map((c) => c.title), ['概述', '政策详情']);
});

test('全段齐全时顺序固定', () => {
  const chapters = v2Chapters(normalizeV2({ ...V2, uncovered: '某文件未纳入。' }));
  assert.deepEqual(chapters.map((c) => c.title),
    ['概述', '政策速览', '政策详情', '地方政策综述', '附录', '已知未覆盖']);
  assert.deepEqual(chapters.map((c) => c.num), ['一', '二', '三', '四', '五', '六']);
});

test('只有业务速判没有概述正文时,概述章仍然要出', () => {
  const view = normalizeV2({ ...V2, overview: '' });
  assert.ok(v2Chapters(view).some((c) => c.key === 'overview'));
});
