# L1 跨条线机关渠道:pin 落地首跑（operator 手册）

分支 `feat/l1-cross-domain-channels`（monorepo `gloriahao0909/safety-platform`）。
代码已合，**生产未动**。这份手册是把 pin 落到生产 catalog 的那一跑。

---

## 一句话

税务总局这类跨条线机关**早就在渠道表里**，坏的是 `list_url`：自动发现把它挑成了
栏目内的单篇文章，状态停在「候选」→ 采集只扫「验证」→ 一天也没扫过。
能源局更隐蔽：`list_url` 指向 2017 年冻结的旧栏目，probe 一直 ok、每天照扫、零新增。
本次把 6 个机关的列表页**钉死**（pin），并新增一条把 pin 落到既有 catalog 的路径。

---

## 落地前必须知道的一件事

6 条 pin 里有 5 条是 **JS 渲染**的列表页，静态 HTML 只是空壳。
它们要判成 `ok` 必须走 firecrawl 渲染，也就是**这一跑必须带 `FIRECRAWL_API_KEY`**
（生产 `/etc/policy-pipeline/models.env` 里有）。

`policy-producer` 的 `env_file` 已经带 `models.env`，key 在容器里，命令不用自己 source
（别把生产密钥 source 进你的 shell）。若 key 缺失/额度用尽，pin 依然会写进 catalog，
但状态会压回「候选」→ 依旧不被扫，等于白跑——所以第 1 步的 `verified=` 计数就是验收点。

| 机关 | pin 的列表页 | 静态/JS | 本机验证 |
|---|---|---|---|
| 国家能源局 | `https://www.nea.gov.cn/policy/zxwj.htm` | JS | 渲染后确认在滚动更新（2026-09-04 最新） |
| 国家税务总局 | `https://fgk.chinatax.gov.cn/zcfgk/c100012/listflfg.html` | JS | 渲染后确认含目标公告（2026年第11号） |
| 中国人民银行 | `https://www.pbc.gov.cn/zhengwugongkai/4081330/4406346/4693545/index.html` | 静态 | **probe 直接 ok** |
| 国家市场监督管理总局 | `https://www.samr.gov.cn/zw/zjwj/` | JS | 渲染后确认（2026-09-04 最新） |
| 交通运输部 | `https://xxgk.mot.gov.cn/2020/jigou?gk=5` | JS | 渲染后确认（2026 年部令） |
| 工业和信息化部 | `https://www.miit.gov.cn/zwgk/zcwj/index.html` | JS | **未渲染核**（本机访问不到 miit），首跑时留意 |

---

## 步骤

### 1. 先 dry-run，看变更集

```bash
cd /root/safety-platform/services/policy-pipeline && docker compose -f docker-compose.server.yml run --rm policy-producer python -m scripts.l1_collect.pin_channels
```

期望输出：6 行 `→ 机关/类型  probe=…  status=…`，每行带旧 URL / 新 URL，
末行 `mode=dry-run added=0 repaired=6 unchanged=0 verified=? candidate=?`。

**判读：**
- `verified=6` → 六条全渲染成功，可以 apply。
- `verified<6` → 记下哪几条是 `candidate`，连同 `probe=` 值贴回来再定；
  **不要**为了凑数手改 YAML 状态（那正是这次要根治的病）。

### 2. apply（写仓内 state，不碰 vault）

```bash
cd /root/safety-platform/services/policy-pipeline && docker compose -f docker-compose.server.yml run --rm policy-producer python -m scripts.l1_collect.pin_channels --apply
```

写的是 `state/T1_channels/channel_catalog.yaml`（git-tracked，容器内挂在 `/app/state`）。
**不写 vault、不入库任何政策**。跑完 `git diff` 看一眼那 6 行，确认只动了
`list_url / status / probe_result / last_probed_at / source / notes`。

### 3. 单渠道试扫（仍不入库）

先只扫这几个新渠道，看能不能扫出行：

```bash
cd /root/safety-platform/services/policy-pipeline && set -a && . /etc/policy-pipeline/fetch-proxy.env && set +a && docker compose -f docker-compose.server.yml run --rm -e POLICY_FETCH_PROXY_URL policy-producer python -m scripts.l1_collect.run_incremental --level national --channel-type 税务总局,央行,市监总局,交通运输部,能源局,工信部 --vault-dir /vault/0_raw/policies --dry-run
```

`--dry-run` 只到 Step3（扫 + 过滤 + 查重），**不抓正文、不进 LLM 门、不写 vault**。

期望：`scan=` 非 0，尤其
- 税务总局 → 应扫到「成品油零售…交易即开票」这类（该公告 2026-06-08，在第 1 页）；
- 能源局 → 应扫到 2026 年的文件，而不再是 2017 年那批。

`scan=0` 的渠道把 `state/T1_incremental/scan/` 下对应 jsonl 贴回来，别自己调词表。

### 4. 正式一跑（会写 vault）

确认第 3 步有料后，再跑不带 `--dry-run` 的那条；或者干脆等 09:00 的 cron 自己跑
（cron 命令未变，catalog 一改它下一轮就带上这些渠道）。

第一次正式跑会有一波历史积压入库（税务总局那个栏目有 1924 条，能源局的
「最新文件」也攒了几年），量比平时大是正常的，**不是 bug**。
若想控量，先只放行税务总局一个 channel-type 跑一轮。

---

## 回滚

catalog 是 git-tracked 的：

```bash
cd /root/safety-platform/services/policy-pipeline && git checkout -- state/T1_channels/channel_catalog.yaml
```

代码侧回滚就是 revert 那个 commit；pin 只在 catalog 生效，revert 后下一次
`pin_channels` 不再写。

---

## 这次没做、但建议排期的三件事

1. **渠道「哑火」检测**。能源局这种「probe 一直 ok、状态一直验证、却零新增」
   是最贵的失败模式：`/zcfb` 最新一条是 2017-10-11，现网 vault 里 96 篇 nea 来源
   全部来自建设期人工采集，本管道一篇也没从这个渠道收进来过，而它每天都在扫。
   建议按渠道记「上次产出新政策的日期」，超过 N 天没新增就进 review_pool。
   这次没做，因为它是独立一块设计。
2. **`channel_reprobe` 没有 cron**。754 个候选渠道从建 catalog 起就没被重探过。
   跨条线这 6 条已用 pin 绕开，但省市那 700 多条还躺着。
3. **未 pin 的跨条线来源**：住建部、标准委（都停在 `http_error` 的裸域名首页）、
   国家金融监督管理总局（nfra.gov.cn，F05 支付/预付资金相关，但其站点静态 HTML
   只有 214 字节，需要单独定位栏目）。证监会（csrc）本轮未做站点核查——从三条业务线
   的信号看它关联最弱，若要纳入应先说明是冲哪条信号去的。

---

## 附：为什么不新增 `level` 取值

`Channel` 的 city/province/city_code 对非地理来源已有既定表达，不用改：
`city=机关名`、`province=国家`、`level=国家`、`city_code="000000"`。
`ingester._infer_region` 按 `city_code == "000000"` 映射成
`region{level: 国家, code: "000000", name: 全国}` 写进 vault frontmatter，
现网 13 条国家级渠道全是这么存的。新增 level 会造出第二套约定，反而要改 ingester
和已入库数据。已加测试锁住这条约定。
