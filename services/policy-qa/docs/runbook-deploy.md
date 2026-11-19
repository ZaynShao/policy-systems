# policy-qa 部署 runbook

> 照抄执行,每步带验证命令,验证不过就停下来问,别往下走。
>
> **执行者需要的前置知识:零。** 但有两步(建数据库角色、改平台 .env)会碰生产数据库和
> 凭据,必须由有权限的 operator 亲手做。
>
> 这个服务是**对内工具**:它会输出内部评分、业务影响分析和行动建议。
> 它的"只对内"不是靠自己的令牌保证的,是靠 nginx 的平台登录态。§5 的最后一条验证
> (未登录访问必须进不去)是本 runbook **最重要**的一步,不能跳。

## 0. 前置检查

| # | 项 | 验法 | 不通过怎么办 |
|---|---|---|---|
| 1 | 本 PR 已合 master,服务器代码已更新 | `git -C /root/safety-platform log --oneline -1` | 先合并再部署 |
| 2 | 平台栈在跑 | `docker ps --filter name=platform-nginx --format '{{.Status}}'` | 先起平台 |
| 3 | heng-pg 在跑 | `docker ps --filter name=platform-heng-pg --format '{{.Status}}'` | 先起 heng-pg |
| 4 | 平台 .env 里有 DeepSeek key | `grep -cE '^DEEPSEEK_API_KEY=.+' /root/safety-platform/.env` | 输出 0 就先补,本服务不另配 key |

## 1. 建只读数据库角色(operator 亲手)

本服务只读 heng-pg,**永远不写**。除了代码里连接级设了 `default_transaction_read_only`,
数据库侧再上一道锁:给它一个只有 SELECT 权限的独立角色,不复用 heng 的应用账号。

先想一个强口令(下面用 `<口令>` 代替,**别用示例值**):

```bash
docker exec -i platform-heng-pg psql -U "$HENG_PG_USER" -d hengguan_staging <<'SQL'
CREATE ROLE policy_qa_ro WITH LOGIN PASSWORD '<口令>';
GRANT CONNECT ON DATABASE hengguan_staging TO policy_qa_ro;
GRANT USAGE ON SCHEMA public TO policy_qa_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO policy_qa_ro;
-- pipeline 以后新建的表也自动只读可见,免得每次加表都要回来补授权
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO policy_qa_ro;
SQL
```

验证(**必须两条都符合预期**):

```bash
# 读得到:应输出政策条数
docker exec -i platform-heng-pg psql -U policy_qa_ro -d hengguan_staging \
  -c 'SELECT count(*) FROM "Policy" WHERE "pipelinePid" IS NOT NULL;'

# 写不了:应报 permission denied
docker exec -i platform-heng-pg psql -U policy_qa_ro -d hengguan_staging \
  -c 'UPDATE "Policy" SET title = title;'
```

第二条**必须失败**。若它成功了,说明角色权限给大了,停下来别继续。

## 2. 平台 .env 增加三行

```bash
cd /root/safety-platform
cat >> .env <<'EOF'

# policy-qa 只读数据库角色(见 services/policy-qa/docs/runbook-deploy.md §1)
POLICY_QA_PG_USER=policy_qa_ro
POLICY_QA_PG_PASSWORD=<第1步那个口令>
POLICY_QA_PG_DB=hengguan_staging
EOF
```

DeepSeek 的三个变量复用平台已有的,不用加。

验证:

```bash
grep -c '^POLICY_QA_PG_' /root/safety-platform/.env   # 应为 3
```

## 3. 构建并启动

本服务挂在 `policy-qa` profile 下,**不会被日常部署自动拉起**——这是有意的:
平台部署用 `up -d --wait` 会等健康状态,若在只读库凭据还没配好时被自动启动,
本服务连不上库会拖垮整个平台部署。所以必须显式带 profile 启用:

```bash
cd /root/safety-platform
docker compose --profile policy-qa build policy-qa
docker compose --profile policy-qa up -d policy-qa
```

**注意:以后每次带 profile 的操作都要加 `--profile policy-qa`**,否则 compose 看不见它。

验证(容器内自测,不经 nginx):

```bash
docker exec platform-policy-qa python -c "
import urllib.request as u, json
print(json.loads(u.urlopen('http://127.0.0.1:8741/v1/health').read()))"
```

预期输出里 `"ok": true`、`"backend": "pg"`、`"policies"` 是个上千的数、
`"auth": "平台登录态(上游 nginx)"`。

**若 policies 为 0**:说明连上了库但没数据——检查 `POLICY_QA_PG_DB` 是不是指错库
(staging 还是生产),停下来问,别继续。

## 4. nginx 生效

本 PR 已含路由配置,只需重载:

```bash
cd /root/safety-platform
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```

## 5. 验证(最后一条最重要)

```bash
# a) 未登录访问:必须**进不去**——期望 302 跳登录页,或 401/403。
#    若返回 200,立即 `docker compose --profile policy-qa stop policy-qa` 并上报,不要放着不管。
curl -s -o /dev/null -w "%{http_code}\n" https://<对外域名>/policy-qa/

# b) 未登录直接打接口:同样必须进不去
curl -s -o /dev/null -w "%{http_code}\n" https://<对外域名>/policy-qa/v1/health
```

```
# c) 已登录访问:浏览器登录平台后打开 https://<对外域名>/policy-qa/
#    应看到问答页面,输入框可用,**不该弹出要令牌的对话框**
#    (弹了说明 POLICY_QA_TRUST_PLATFORM_AUTH 没生效)
```

```
# d) 端到端:在页面里问一句「最近对充电业务影响大的政策有哪些」
#    应看到检索过程逐条出现、回答逐字流式吐出、末尾带引用卡片。
#    这是第一次用真实 heng-pg 数据跑,**重点看回答里的政策是不是真存在**。
```

d 这步是这套东西第一次接真库(此前只在本地用 vault 文件验过),
如果回答里出现明显不对的政策或报错,把 `docker logs platform-policy-qa --tail 50` 贴出来。

## 6. 回滚

```bash
cd /root/safety-platform
docker compose --profile policy-qa stop policy-qa
docker compose --profile policy-qa rm -f policy-qa
```

nginx 那条 location 留着无害(上游没了会 502,但该路径本来就只有登录用户能碰到)。
要连 nginx 一起回滚,就 `git revert` 本 PR 后重载 nginx。

只读角色可以留着,不影响任何人;真要清:

```sql
DROP ROLE policy_qa_ro;   -- 先 REVOKE 各项权限,否则会报依赖
```

## 日常操作

| 事 | 命令 |
|---|---|
| 看日志 | `docker logs platform-policy-qa --tail 50` |
| 看问答记录 | `docker exec platform-policy-qa sh -c 'tail -3 /app/qa_logs/chat-*.jsonl'` |
| 重启 | `docker compose --profile policy-qa restart policy-qa` |
| 换模型 | 改平台 .env 的 `DEEPSEEK_MODEL` 后 `docker compose --profile policy-qa up -d policy-qa` |

数据是 pipeline 每天 21:00 投影进 heng-pg 的,本服务只读,**不需要为了更新数据做任何事**。

## 切生产库

现在指的是 `hengguan_staging`。等 heng 生产库 cutover 完成后:

1. 在生产库上重跑 §1 的建角色 SQL(角色是 per-database 授权的)
2. 改 .env 的 `POLICY_QA_PG_DB=hengguan`
3. `docker compose --profile policy-qa up -d policy-qa`,重跑 §3 与 §5 的验证

## 已知限制(先看一眼,免得被当成故障上报)

- 同一 pid 在库里可能对应多份文件(实测 14 组),回答里会带"已知数据缺陷"的说明。
  这是 pipeline 侧的 id 生成问题,不是本服务的 bug。
- 库里有极少数未来日期的政策(最远 2030),按日期排序会排在最前。
- 部分政策正文带网站导航噪声或编码损伤,本服务原样传给模型,不做去噪。

完整清单见 `services/policy-qa/README.md` 的「已知限制」。
