# 工单研判本地客户端：设备密钥直传 v1.0

日期：2026-10-22。所有者：shaoziyuan（个人工作台 `pending-gov-risk`）。

## 需求

所有者内网 Mac 上的本地脱敏客户端要能直接把脱敏工单推到平台，不再依赖运维另发共享口令
`GOV_RISK_AGENT_TOKEN`。安全上只需确认"是这台设备在推"；使用场景单一：一个所有者、一台设备。

验收：

- 平台登记某台设备的指纹后，该设备不带共享口令也能调用 `/heng/api/v1/internal/gov-risk/*`；
- 未登记设备、错误密钥、弱密钥、拿指纹本身冒充密钥，一律 401 `gov_risk_agent_unauthorized`；
- 页面接口 `/heng/api/v1/gov-risk/*` 仍只认平台登录 + 所有者，设备密钥不能访问；
- 已配置的共享口令照常可用。

## 方案

- 设备第一次运行时用系统随机数生成 256 位设备密钥（64 位十六进制），只存在本机
  `~/.config/gov-ticket-risk/secrets.json`（权限 600），请求时放在原有请求头 `x-gov-risk-agent-token`。
- 平台只登记它的 SHA-256 指纹：环境变量 `GOV_RISK_AGENT_KEY_SHA256`。指纹不是秘密，可以放进已审核配置；
  生产 overlay 给出所有者当前设备的指纹作为默认值，与 `GOV_RISK_OWNER_USERNAME` 默认值同一做法，显式非空配置仍优先。
- `gov-risk.http.ts` 新增 `isGovRiskAgentCredential`，`JwtAuthGuard` 在内部前缀改用它：
  1. 提供值必须是强密钥（沿用守卫的 `hasStrongSecret`），否则拒绝；
  2. 共享口令已配置且相等 → 通过（定长比较）；
  3. 否则对提供值做 SHA-256，与登记指纹定长比较；指纹不是 64 位十六进制时永不匹配。
- 不改 nginx（内部前缀例外和请求头透传不变），不改数据库，不改页面接口鉴权。

## 风险与边界

- 设备密钥等同原共享口令的权限（上传/撤回该所有者的脱敏工单、读结果包），作用域仍只限内部前缀。
- 指纹公开后无法反推密钥（256 位随机数）；拿到指纹本身不能通过校验（测试覆盖）。
- 换设备或本机密钥文件丢失：指纹会变，需要更新 `GOV_RISK_AGENT_KEY_SHA256` 后重新部署 heng-backend。
- 测试站目前仍返回 503 `gov_risk_storage_not_ready`：部署时仍需按 [GOV-RISK-HENG-MIGRATION.md](GOV-RISK-HENG-MIGRATION.md)
  跑迁移工具写入完成标记，本改动不绕过就绪检查。

## 验证

- `services/heng-guan/backend`：`npm run build`、`tsc --noEmit -p tsconfig.spec.json`、`npm run test:gov-risk`
  （`gov-risk.http.spec.ts` 新增设备指纹的通过、拒绝、页面隔离和与共享口令共存用例）、`ts-node test/nest-runtime.smoke.ts`。
- `tests/test_personal_workbench_deployment.py`：生产 overlay 的指纹是 64 位十六进制、开发环境为空、guardian-backend 不带；
  改这一行只重建 heng-backend。本机无 Docker，Compose 用例以 CI 为准。
- 本地客户端（私有仓库）用同一指纹在模拟平台走完 体检 → 上传 → 研判 → 汇总。

## 回滚

直接 revert：共享口令路径不受影响；回滚后设备密钥失效，需改回运维配置共享口令。无数据库改动。
