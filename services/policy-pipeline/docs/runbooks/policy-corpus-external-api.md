# 政策原文对外只读 API · 部署 runbook

> 照抄执行，每步带验证命令，验证不过就停。
> 背景:外团队需要查看已梳理的政策**原文**,不给代码、不给任何分析产出物
> (摘要/评分/关系/主题/business_view 一律不出)。
> 架构:vault `0_raw/policies` → `scripts.public_export.run` 白名单导出 →
> 语料包(host 目录)→ `policy-corpus` 容器(只挂语料包,**从不挂 vault**)→
> nginx `/policy-corpus/` 转发。凭据独立签发,不接平台账号体系。

## 0. 前置 checklist

| # | 项 | 验法 |
|---|---|---|
| 1 | 本 PR 已合 master,服务器代码已更新 | `git -C /root/policy-pipeline-src log --oneline -1` 包含本 PR |
| 2 | vault 在位 | `ls /root/policy-vault/0_raw/policies/ \| head -3` 有 md 文件 |
| 3 | platform-net 存在(平台栈已起) | `docker network ls \| grep safety-platform_platform-net` |

## 1. 导出语料包(host,只读 vault)

```bash
cd /root/policy-pipeline-src/services/policy-pipeline
# 干跑:只统计不写盘
docker compose -f docker-compose.server.yml run --rm --no-deps \
  -v /root/policy-corpus:/out policy-pipeline \
  python -m scripts.public_export.run --vault /vault --out /out/dist --dry-run
```

看「可导出 N 篇,排除 M 篇」。N 明显偏少或为 0 → 停,查 vault 挂载。正常则正式导出:

```bash
docker compose -f docker-compose.server.yml run --rm --no-deps \
  -v /root/policy-corpus:/out policy-pipeline \
  python -m scripts.public_export.run --vault /vault --out /out/dist
```

验证(泄露审计,照抄整段;必须 PASS):

```bash
python3 - <<'PY'
import json
ALLOWED={"id","title","official_number","issuer","date","region","source_url","fetched_at","body"}
bad=n=0
for line in open("/root/policy-corpus/dist/policies.jsonl", encoding="utf-8"):
    r=json.loads(line); n+=1
    if set(r)-ALLOWED or set(r.get("region") or {})-{"level","code","name"}: bad+=1
print(f"{n} 篇, 违规 {bad} -> {'PASS' if bad==0 else 'FAIL 停下'}")
PY
```

## 2. 签发外团队令牌

```bash
cd /root/policy-pipeline-src/services/policy-pipeline
PYTHONPATH=. python3 -m scripts.corpus_service.issue_token \
  --registry /etc/policy-pipeline/corpus-tokens.json \
  issue --name 外团队A --expires-at 2027-01-27
```

- 屏幕上那行明文令牌**只显示一次,当场存好**;注册表只存 sha256。
- 限额默认 60 次/分钟、全文 200 篇/天;要改加 `--rpm` / `--full-text-per-day`。
- 撤销:`... revoke --name 外团队A`;查看:`... list`。

验证:`ls -l /etc/policy-pipeline/corpus-tokens.json` 权限 0600,`cat` 无明文。

## 3. 起服务

> **顺序纪律:必须先做完 §2 再 up。** 注册表文件不存在时 docker 会把挂载点
> 建成**目录**,之后签发会失败,只能删目录重来。

```bash
cd /root/policy-pipeline-src/services/policy-pipeline
docker compose -f docker-compose.server.yml build policy-corpus
docker compose -f docker-compose.server.yml up -d policy-corpus
```

验证(在任一平台网内容器视角,或直接 exec):

```bash
docker exec policy-corpus python -c "import urllib.request as u; print(u.urlopen(u.Request('http://127.0.0.1:8731/v1/manifest')).status)" 2>&1 | tail -1
# 预期抛 401(无令牌被拒即为通)。带令牌应 200:
docker exec policy-corpus python -c "
import urllib.request as u
r=u.urlopen(u.Request('http://127.0.0.1:8731/v1/manifest', headers={'Authorization':'Bearer <粘贴令牌>'}))
print(r.status, r.read()[:120])"
```

## 4. nginx 生效(本 PR 已含配置,只需 reload)

```bash
cd /root/safety-platform && docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```

验证:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<对外域名>/policy-corpus/v1/manifest        # 401
curl -s -H "Authorization: Bearer <令牌>" https://<对外域名>/policy-corpus/v1/manifest      # 200 + JSON
```

## 5. 交付外团队

通过安全渠道(当面/加密 IM,不走明文邮件)给对方:

1. 令牌明文 + 接口地址 `https://<对外域名>/policy-corpus`
2. 仓内 `services/policy-pipeline/external/policy-corpus-skill/` 目录的**拷贝**
   (对方放进自己项目 `.claude/skills/policy-corpus/`,配置
   `POLICY_CORPUS_API` / `POLICY_CORPUS_TOKEN` 两个 env)

## 日常操作

| 事 | 命令 |
|---|---|
| 对方要新数据 | 重跑 §1 正式导出,然后 `docker compose -f docker-compose.server.yml restart policy-corpus` |
| 新增/撤销令牌 | §2 的 issue/revoke,然后 restart policy-corpus |
| 看日志 | `docker logs policy-corpus --tail 50` |

> 签发/撤销/重导出后都要 restart 才生效(注册表与语料包启动后首次请求时加载缓存)。
> 无 cron:导出是**按需**的,对方提需求时响应(用户裁决 2026-07-27)。
