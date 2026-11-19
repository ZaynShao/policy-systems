// 独立版补的测试:核对从同事文件里拆出来的政策大盘聚合(src/dashboard/dashboard.service.ts 里我写的两段)
// 单独也能跑对——按 L2 主题编号命中、按区划代码归省、国家级单列"全国"、无区划代码时按名称兜底。
// 写法照原项目这几个测试的样子:不连库,传入替身数据。
import assert from 'assert/strict';
import { DashboardService } from '../src/dashboard/dashboard.service';

type Row = {
  pid: string; title: string; region: string | null; regionLevel: string | null;
  adcode: string | null; importance: number; date: string | null; themes: string[];
};

const THEMES = [
  { id: 'vpp_theme', name: '虚拟电厂', count: 3 },
  { id: 'charging_infra', name: '充电基础设施', count: 2 },
  { id: 'v2g', name: 'V2G(车网互动)', count: 0 },
];

function day(offset: number) {
  return new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
}

const ROWS: Row[] = [
  // 国家级:adcode 00 开头,或层级写"国家"
  { pid: 'P_N1', title: '国家级虚拟电厂文件', region: '全国', regionLevel: '国家', adcode: '100000', importance: 5, date: day(-10), themes: ['vpp_theme'] },
  { pid: 'P_N2', title: '国家级充电文件', region: '国家能源局', regionLevel: '国家', adcode: null, importance: 3, date: day(-20), themes: ['charging_infra'] },
  // 省级:区县代码上卷到省
  { pid: 'P_JS1', title: '苏州虚拟电厂细则', region: '苏州市', regionLevel: '市', adcode: '320500', importance: 4, date: day(-5), themes: ['vpp_theme'] },
  // 名称被发文机关污染、又没有区划代码:按全名前缀兜底归江苏
  { pid: 'P_JS2', title: '江苏市监充电文件', region: '江苏省市场监督管理局', regionLevel: '省', adcode: null, importance: 2, date: day(-6), themes: ['charging_infra'] },
  // 直辖市的区:310115 → 上海市
  { pid: 'P_SH1', title: '浦东虚拟电厂文件', region: '浦东新区', regionLevel: '区', adcode: '310115', importance: 3, date: day(-7), themes: ['vpp_theme'] },
  // 裸区名、无代码:解析不出省,不进省级统计
  { pid: 'P_X1', title: '无法归省的文件', region: '浦东新区', regionLevel: '区', adcode: null, importance: 1, date: day(-8), themes: ['vpp_theme'] },
  // 时间窗口外
  { pid: 'P_OLD', title: '两年前的文件', region: '江苏省', regionLevel: '省', adcode: '320000', importance: 5, date: day(-800), themes: ['vpp_theme'] },
];

// 替身:只认 policyCoverage 会发的条件 { AND: [{ date: { gte } }, { themes: { array_contains: [id] } }] }
function fakePrisma(seen: any[]) {
  return {
    knowledgeTheme: {
      findMany: async (args: any) => {
        seen.push(['theme', args]);
        return THEMES;
      },
    },
    knowledgeEntry: {
      findMany: async (args: any) => {
        seen.push(['entry', args]);
        const [dateCond, themeCond] = args.where.AND;
        const gte: string = dateCond.date.gte;
        const id: string = themeCond.themes.array_contains[0];
        return ROWS
          .filter((r) => (r.date ?? '') >= gte && r.themes.includes(id))
          .sort((a, b) => b.importance - a.importance || (b.date ?? '').localeCompare(a.date ?? ''));
      },
    },
  };
}

async function testCoverageByThemeIdAndAdcode() {
  const seen: any[] = [];
  const service = new DashboardService(fakePrisma(seen) as any);
  const resp = await service.policyCoverage(365);

  assert.equal(resp.window.days, 365);
  assert.deepEqual(resp.topics.map((t) => t.topicId), ['vpp_theme', 'charging_infra', 'v2g']);
  assert.deepEqual(seen[0], ['theme', { orderBy: [{ count: 'desc' }, { id: 'asc' }] }]);

  const vpp = resp.topics[0];
  assert.equal(vpp.themeId, 'vpp_theme');
  assert.equal(vpp.name, '虚拟电厂');
  assert.equal(vpp.color, '#F97316');
  // 全国单列;江苏(区县代码上卷)、上海(区的代码)各 1;无法归省的 1 条不计;窗口外的不计
  assert.equal(vpp.national.policyCount, 1);
  assert.equal(vpp.national.strategicCount, 1);
  assert.deepEqual(vpp.coverage.map((c) => [c.region, c.adcode, c.policyCount]), [
    ['江苏省', '320000', 1],
    ['上海市', '310000', 1],
  ]);
  assert.equal(vpp.totalPolicies, 3);
  assert.equal(vpp.totalRegions, 2);
  // 省下的政策带着原始区划代码与层级,前端据此钻取到市/区
  assert.deepEqual(vpp.coverage[1].policies[0], {
    id: 'P_SH1', title: '浦东虚拟电厂文件', importance: '3', issueDate: ROWS[4].date, adcode: '310115', regionLevel: '区',
  });

  const charging = resp.topics[1];
  assert.equal(charging.national.policyCount, 1); // 层级"国家"、无代码,也算全国
  assert.deepEqual(charging.coverage.map((c) => c.region), ['江苏省']); // 名称兜底
  assert.equal(charging.coverage[0].policies[0].adcode, '');

  const v2g = resp.topics[2];
  assert.equal(v2g.totalPolicies, 0);
  assert.deepEqual(v2g.coverage, []);
}

async function testCoverageSortedByWeight() {
  const service = new DashboardService({
    knowledgeTheme: { findMany: async () => [{ id: 'power_market', name: '电力市场', count: 3 }] },
    knowledgeEntry: {
      findMany: async () => [
        { pid: 'A', title: 'a', region: '广东省', regionLevel: '省', adcode: '440000', importance: 1, date: day(-1) },
        { pid: 'B', title: 'b', region: '广东省', regionLevel: '省', adcode: '440100', importance: 1, date: day(-1) },
        { pid: 'C', title: 'c', region: '山东省', regionLevel: '省', adcode: '370000', importance: 5, date: day(-1) },
      ],
    },
  } as any);
  const [topic] = (await service.policyCoverage(30)).topics;
  // 广东 2 条普通 → 权重 2;山东 1 条战略级 → 1 + 0.35 + 0.65 = 2,同分保持先到先排
  assert.deepEqual(topic.coverage.map((c) => [c.region, c.weight]), [['广东省', 2], ['山东省', 2]]);
  assert.equal(topic.coverage[1].majorCount, 1);
  assert.equal(topic.coverage[1].strategicCount, 1);
}

async function main() {
  await testCoverageByThemeIdAndAdcode();
  await testCoverageSortedByWeight();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
