# 行业预判板(生成物,不要手改)

- 来源:policy pipeline 仓 `state/行业预判板/`(`build/index.html` + `build/data.js`,由 `tools/export_portal.py` 导出)。
- 事实来源:`state/行业预判板/industries/<id>.json`(19 个行业,schema v1.1,导出前必过 `tools/validate.py`)。
- 挂载方式:`portal/policy-predict.html` 侧栏「行业预判板」视图用同源 iframe 加载本目录 `index.html`;页面在 iframe 内自动隐藏自带的平台页签条。
- 刷新数据:在 policy pipeline 仓执行 `python3 state/行业预判板/tools/export_portal.py <safety-platform>/portal`,提交生成的两个文件。
- 本次导出:2026-09-15 13:26;T0 = 2026-09-14;`data.js` 带 `?v=` 版本参数以绕过 5 分钟静态缓存。
