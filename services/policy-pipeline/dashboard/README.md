# 链路看板(独立版补的)

一个双击就能打开的单文件页面,看政策分析 pipeline 整条链路:

- **链路**:L1 采集 → L2 分析 → 政策库(vault)→ 四个出口(平台库与政策大盘、问答助手、月刊、对外只读接口),每段的真实件数,以及每一段过去了多少、卡住了多少;
- **守恒巡检**:用原项目 PR 1184 写的巡检代码(`scripts/service/conservation_audit.py`)在本机重算 ①③④,② 要连平台库,写明算不了的原因;
- **政策库**:2,102 条政策可搜、可按层级、省份、发文机关、发文日、L2 主题、链路状态筛,点开看文号、机关、摘要、L2 主题与影响判断、相关政策和原文链接。

页面不联网、不引外部脚本和字体,数据内嵌在页面里;只有点「打开原文网页」才会去政府网站。

## 生成页面

只要 Python 3(标准库),在 `services/policy-pipeline` 下:

```bash
python3 dashboard/build.py
```

生成 `dashboard/dist/政策分析pipeline-独立版.html`(约 5 MB;`dist/` 不进仓库)。也可以指定输出位置:
`python3 dashboard/build.py ~/Desktop/链路看板.html`。

## 换成新数据

演示数据在 `data/`(来历见 `data/README.md`)。政策库更新以后,先装好依赖(见上一级 README),再从本机政策库克隆重录:

```bash
python dashboard/export_data.py --vault <政策库克隆目录> --monthly-state <月刊产线的 state 目录>
python3 dashboard/build.py
```

`export_data.py` 只读政策库,用的都是本服务自己的代码:守恒巡检 `scripts/service/conservation_audit.py`、
平台库同步的取行函数 `scripts/sync/run_sync.py`(只算不写库)、对外语料导出 `scripts/public_export/run.py`;
不连数据库、不联网、不调用大模型。`--monthly-state` 可以不给,月刊那一格就显示「没有带月刊选目单」。

## 文件

| 文件 | 内容 |
|---|---|
| `src/page.html` | 页面骨架(三个占位:样式、数据、脚本) |
| `src/style.css` | 样式,浅色/深色两套,只用系统字体 |
| `src/app.js` | 页面逻辑:链路图、分布小图、巡检清单、政策库搜索筛选、详情 |
| `build.py` | 打包成单文件 HTML(只用标准库;超过 25 MB 会报错) |
| `export_data.py` | 从本机政策库录演示数据到 `data/` |
| `data/` | 演示数据:`overview.json` 链路件数,`audit.json` 守恒巡检结果,`policies.json` 政策库条目 |
