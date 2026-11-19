// 这个文件原来是同事建的(公共事务后端的大盘统计),本仓只收我写的部分,其余是独立版的最小外壳。
//
// 我写的(原项目 PR 124「政策大盘对齐 pipeline 的 L2」):政策大盘不再按中文关键词去碰,
// 改成按 L2 主题编号精确命中、按 L1 区划代码(adcode)归到省、国家级政策单列"全国"——
// 即下面 policyCoverage 的主体和 knowledgeCoverageByRegion 整个函数,原样搬来。
// 同事写的其他统计(属地大盘 overview、byRegion 等)一行不带。
// 行尾标「外壳」的是独立版补的:类的壳子、导入、时间窗口换算和返回结构这几行原来是同事的,这里按原约定重写。
import { Injectable } from '@nestjs/common'; // 外壳
import { Prisma, PrismaService } from '../prisma/prisma.service'; // 外壳(原来 Prisma 类型从 @prisma/client 引)
import { isNational, resolveProvince } from './region-codes';

@Injectable() // 外壳
export class DashboardService { // 外壳
  constructor(private readonly prisma: PrismaService) {} // 外壳

  /**
   * 政策大盘聚合(对齐工程层 L2,spec C1/C2/C3/C5):
   * - 主题来自 KnowledgeTheme(= themes_registry 投影),按 theme id 精确命中
   *   (KnowledgeEntry.themes array_contains [id]),不再用中文关键词 ILIKE / AnalysisTopic。
   * - region 按 L1 adcode 解析到省级(前2位),区县级上卷;省下 city 由前端按 adcode 钻取。
   * - 国家级(adcode 00 前缀 / level 国家)单列"全国"桶,不进省级 choropleth。
   */
  async policyCoverage(days: number = 365) { // 外壳
    const since = new Date(Date.now() - days * 86_400_000); // 外壳:近 days 天
    const sinceText = since.toISOString().slice(0, 10); // 外壳:政策日期是 YYYY-MM-DD 文本,按文本比
    // C1:主题严格跟 registry 表走(KnowledgeTheme = themes_registry 投影)
    const themes = await this.prisma.knowledgeTheme.findMany({
      orderBy: [{ count: 'desc' }, { id: 'asc' }],
    });

    // 调色板:主题随 registry 扩展,色不够按序循环
    const palette = [ // 外壳
      '#F97316', '#3B82F6', '#8B5CF6', '#10B981', '#EC4899', '#F59E0B',
      '#0EA5E9', '#EF4444', '#14B8A6', '#A855F7', '#84CC16', '#F43F5E',
      '#6366F1', '#22C55E',
    ]; // 外壳

    const results = await Promise.all(
      themes.map(async (theme, i) => {
        const where: Prisma.KnowledgeEntryWhereInput = {
          AND: [
            { date: { gte: sinceText } },
            { themes: { array_contains: [theme.id] } },
          ],
        };
        const { coverage, national } = await this.knowledgeCoverageByRegion(where);
        return {
          topicId: theme.id,
          themeId: theme.id,
          name: theme.name,
          description: undefined as string | undefined,
          isEnergy: true,
          color: palette[i % palette.length],
          keywords: [] as string[],
          coverage,
          national,
          totalPolicies:
            coverage.reduce((sum, row) => sum + row.policyCount, 0) + national.policyCount,
          totalRegions: coverage.length,
        };
      }),
    );

    return { // 外壳
      window: { days, since: since.toISOString() }, // 外壳
      topics: results, // 外壳
    }; // 外壳
  } // 外壳

  /**
   * 命中某主题的 KnowledgeEntry 按省级聚合 + 全国桶。
   * 省级 key = adcode 前2位查表得到的省全名(与 geojson 对齐);name 仅作无 adcode 时兜底。
   * policies 带 adcode/regionLevel,供前端钻取时按 adcode 落到市/区(spec C3)。
   */
  private async knowledgeCoverageByRegion(where: Prisma.KnowledgeEntryWhereInput) {
    const rows = await this.prisma.knowledgeEntry.findMany({
      where,
      select: {
        pid: true, title: true, region: true, regionLevel: true,
        adcode: true, importance: true, date: true,
      },
      orderBy: [{ importance: 'desc' }, { date: { sort: 'desc', nulls: 'last' } }],
      take: 5000,
    });

    type Sample = {
      id: string; title: string; importance: string; issueDate: string;
      adcode: string; regionLevel: string;
    };
    type Agg = {
      region: string; adcode: string;
      policyCount: number; majorCount: number; strategicCount: number; policies: Sample[];
    };
    const POLICY_CAP = 200;
    const provinceMap = new Map<string, Agg>();
    const national = { policyCount: 0, majorCount: 0, strategicCount: 0, policies: [] as Sample[] };

    for (const r of rows) {
      const sample: Sample = {
        id: r.pid,
        title: r.title,
        importance: String(r.importance),
        issueDate: r.date ?? '',
        adcode: r.adcode ?? '',
        regionLevel: r.regionLevel ?? '',
      };
      const isMajor = r.importance >= 4;
      const isStrategic = r.importance >= 5;

      // C5:全国政策单列,不进省级
      if (isNational(r.adcode, r.regionLevel, r.region)) {
        national.policyCount += 1;
        if (isMajor) national.majorCount += 1;
        if (isStrategic) national.strategicCount += 1;
        if (national.policies.length < POLICY_CAP) national.policies.push(sample);
        continue;
      }
      // C2:adcode 前2位定省(区县级上卷);无 adcode 时按 name 兜底
      const prov = resolveProvince(r.adcode, r.region);
      if (!prov) continue; // 极少数无法解析,不污染省级统计
      let agg = provinceMap.get(prov.name);
      if (!agg) {
        agg = { region: prov.name, adcode: prov.adcode, policyCount: 0, majorCount: 0, strategicCount: 0, policies: [] };
        provinceMap.set(prov.name, agg);
      }
      agg.policyCount += 1;
      if (isMajor) agg.majorCount += 1;
      if (isStrategic) agg.strategicCount += 1;
      if (agg.policies.length < POLICY_CAP) agg.policies.push(sample);
    }

    const coverage = Array.from(provinceMap.values())
      .map((a) => ({
        region: a.region,
        adcode: a.adcode,
        policyCount: a.policyCount,
        feedbackCount: 0,
        majorCount: a.majorCount,
        strategicCount: a.strategicCount,
        weight: a.policyCount + a.majorCount * 0.35 + a.strategicCount * 0.65,
        policies: a.policies,
      }))
      .sort((a, b) => b.weight - a.weight); // 外壳(排序这一行原来就在,是同事写的)

    return { coverage, national };
  }
} // 外壳
