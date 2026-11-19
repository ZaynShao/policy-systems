// 月刊 v2 渲染的回归测试。
//
// 真正的判断逻辑在 monthly-content.ts,那边有独立单测。这里盯的是 SFC 这层胶水
// ——它出错的方式是**静默的**:v2 数据喂进 v1 模板不会报错,只会渲染出一片空白
// (v1 读 policyBlocks,v2 里根本没有这个字段)。所以这几条断言看的是
// "分支在不在、绑对了没有",而不是重复测逻辑。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = (rel) => readFile(path.join(frontendRoot, rel), 'utf8');

function compiles(src, filename) {
  const { descriptor, errors } = parse(src, { filename });
  assert.deepEqual(errors, [], `${filename} SFC 解析出错`);
  compileScript(descriptor, { id: 'test' });
  const tpl = compileTemplate({ source: descriptor.template.content, filename, id: 'test' });
  assert.deepEqual(tpl.errors.map(String), [], `${filename} 模板编译出错`);
}

test('两个月刊页面都能编译(模板改坏了会静默渲染成空白)', async () => {
  compiles(await source('src/views/monthly/MonthlyDetail.vue'), 'MonthlyDetail.vue');
  compiles(await source('src/views/monthly/MonthlyList.vue'), 'MonthlyList.vue');
});

test('详情页按 schema 分支,老数据仍走 v1 模板', async () => {
  const page = await source('src/views/monthly/MonthlyDetail.vue');
  assert.match(page, /detectSchema\(detail\.value\?\.content\) === 'v2'/u);
  assert.match(page, /v-if="isV2"/u);
  assert.match(page, /<template v-else>/u, 'v1 分支必须还在——已发布的历史刊不会重生成');
  assert.match(page, /detail\.content\.policyBlocks/u, 'v1 分支仍要读 policyBlocks');
});

test('v2 正文一律文本插值,不走 v-html', async () => {
  const page = await source('src/views/monthly/MonthlyDetail.vue');
  const v2Block = page.slice(page.indexOf('v-if="isV2"'), page.indexOf('<!-- ── 老数据'));
  assert.ok(v2Block.length > 500, '没截到 v2 分支');
  assert.doesNotMatch(v2Block, /v-html/u,
    'v2 正文是纯文字(D 门禁 markdown),用 v-html 只是白白开一个注入口');
  for (const label of ['【政策信息】', '【政策解读】', '【重点关注内容】', '【决策建议】']) {
    assert.ok(v2Block.includes(label), `v2 详情缺 ${label}`);
  }
});

test('caveats 非空时出容错提示条,且不把机器定位串摆给读者', async () => {
  const page = await source('src/views/monthly/MonthlyDetail.vue');
  assert.match(page, /v-if="banner\.show"/u);
  assert.match(page, /banner\.text/u);
  assert.match(page, /item\.where/u, '列出的是 formatLocation 转过的人话');
  assert.doesNotMatch(page, /caveat\.location/u, '不能直接渲染原始 location');
});

test('修改意见栏提交到 revisionNote,并显示已有的待回炉意见', async () => {
  const page = await source('src/views/monthly/MonthlyDetail.vue');
  assert.match(page, /monthlyApi\.revisionNote\(/u);
  assert.match(page, /修改意见/u);
  assert.match(page, /:disabled="!noteDraft\.trim\(\) \|\| savingNote"/u, '空意见不许提交');
  assert.match(page, /detail\.content\.pendingNote/u);
});

test('详情标题只有在映射到 heng 政策时才给链接', async () => {
  const page = await source('src/views/monthly/MonthlyDetail.vue');
  assert.match(page, /d\.link \? 'pointer' : 'default'/u);
  assert.match(page, /v-if="d\.link"/u);
});

test('列表卡片的篇数与标签走共用判断,不再直接读 policyBlocks', async () => {
  const page = await source('src/views/monthly/MonthlyList.vue');
  assert.match(page, /from '\.\/monthly-content'/u);
  assert.match(page, /detailCount\(m\)/u);
  assert.doesNotMatch(page, /m\.content\?\.policyBlocks\?\.length/u,
    'v2 没有 policyBlocks,直接读会让新刊卡片显示 0 政策详情');
});

test('api 类型把两套 schema 的字段都声明了', async () => {
  const api = await source('src/api/monthly.ts');
  for (const field of ['schema?', 'businessTakes?', 'quickTable?', 'details?',
                       'localRoundup?', 'appendix?', 'caveats?', 'pendingNote?']) {
    assert.ok(api.includes(field), `MonthlyContent 缺 ${field}`);
  }
  assert.match(api, /revisionNote:/u);
});
