# 本机起一个临时 Postgres 跑真库测试

`tests/test_pg_integration.py` 默认跳过,因为它需要一个真的 Postgres。
这份是本机起一个用完即弃的实例的办法——**不要连生产库跑它**,它会
`DROP TABLE` 再重建。

需要本机装了 PostgreSQL(`brew install postgresql@15`)。

```bash
export PATH=/opt/homebrew/opt/postgresql@15/bin:$PATH
export LC_ALL=C LANG=C          # 缺了它 postmaster 在 macOS 上会以 "变成多线程" 启动失败
DATA=$(mktemp -d)/pg

initdb -D "$DATA" -U probe --auth=trust -E UTF8
# 走 TCP:scratchpad 之类的深路径会撑爆 unix socket 的 103 字节上限
pg_ctl -D "$DATA" -o "-k /tmp -h 127.0.0.1 -p 55432" -l "$DATA/pg.log" start
createdb -h 127.0.0.1 -p 55432 -U probe hengguan_probe
```

跑测试:

```bash
POLICY_QA_TEST_DATABASE_URL=postgresql://probe@127.0.0.1:55432/hengguan_probe \
  .venv/bin/python -m pytest tests/test_pg_integration.py -v
```

用完拆掉:

```bash
pg_ctl -D "$DATA" stop && rm -rf "$DATA"
```

## 为什么值得费这个事

其余测试全都注入 fake executor 或读 vault 文件,**SQL 文本从没被数据库解析过**。
`::text IN`、`@> ::jsonb`、ILIKE 转义、列名大小写——写错了本地照样全绿,
第一次执行是在生产上。2026-08-18 线上第一次接真库就炸了,而当时全套测试是绿的。

表结构取自 `services/heng-guan/backend/prisma/schema.prisma`,固化在
`tests/fixtures/heng_pg_schema.sql`。**那份 Prisma schema 改了,fixture 要跟着改**,
否则这套测试会给出虚假的安全感。
