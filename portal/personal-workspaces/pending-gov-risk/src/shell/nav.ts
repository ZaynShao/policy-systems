// 门户左侧导航。分组沿用公共事务侧栏的写法(标题 + 副标题 + 挂在连接线上的条目),
// 复制进来的模块路径与公共事务原版一致,原代码里的 router.push 不用改。
export type NavItem = { label: string; to: string; icon: string; match: string[] };
export type NavGroup = { title: string; note: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    title: '工作台', note: '我的综合看板',
    items: [
      { label: '总览', icon: 'overview', to: '/overview', match: ['/overview'] },
    ],
  },
  {
    title: '政诉工作', note: '工单系统性原因',
    items: [
      { label: '政诉预判', icon: 'alert', to: '/gov-risk', match: ['/gov-risk'] },
    ],
  },
  {
    title: '政策工作', note: '大盘、解读、知识与月刊',
    items: [
      { label: '政策大盘', icon: 'policy', to: '/dashboard/policy', match: ['/dashboard/policy'] },
      { label: '政策解读', icon: 'policy-library', to: '/policy/interpretation', match: ['/policy/interpretation'] },
      { label: '政策知识库', icon: 'knowledge', to: '/policy/knowledge', match: ['/policy/knowledge'] },
      { label: '政策图谱', icon: 'graph', to: '/policy/graph', match: ['/policy/graph'] },
      { label: '政策月刊', icon: 'news', to: '/monthlies', match: ['/monthlies'] },
    ],
  },
  {
    title: '管理配置', note: '数据源与质量审核',
    items: [
      { label: '政策数据源', icon: 'datasource', to: '/policy/import', match: ['/policy/import'] },
      { label: '源质量审核', icon: 'check', to: '/quality/l1-review', match: ['/quality/l1-review'] },
    ],
  },
];

export function navLabel(path: string): string {
  for (const g of NAV_GROUPS) {
    for (const item of g.items) {
      if (item.match.some(p => path === p || path.startsWith(p + '/'))) return item.label;
    }
  }
  return '';
}
