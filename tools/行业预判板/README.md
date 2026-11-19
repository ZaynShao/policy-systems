# 行业预判板的数据构建工具(个人版说明)

这里是我本机 `state/行业预判板/` 下 9-14～9-15 用的那套东西:各行业组照 `PROMPT-*.md` 调研,产出每个行业一份事实 JSON
(结构见 `schema/`),再由 `tools/` 校验、打包、导出成 `portal/industry-board/` 的页面数据。

```bash
cd tools/行业预判板
python3 tools/validate.py snapshots/T0-2026-09-15-r4/industries/*.json          # 逐份校验
python3 tools/build_data.py --src snapshots/T0-2026-09-15-r4/industries           # 打包成 build/data.js(不进仓库)
python3 tools/export_portal.py ../../portal --src snapshots/T0-2026-09-15-r4/industries   # 导出到页面目录
```

- `snapshots/T0-2026-09-15-r4/` 是原项目 PR 1326 发布时用的 24 个行业事实 JSON(唯一发布源);用它打包出的 `data.js`
  除构建时间外与本仓 `portal/industry-board/data.js` 逐字一致。
- 个人版隐去了三件公司内部信息的原文(内部证据节点和引用它们的句子换成占位),分数与推理结构不动,所以与原项目的数据只差这些占位。
- 只用 Python 标准库(要 3.9 以上)。
