"""MA8 收尾:把成稿投影进 heng-pg。

照仓内既有的 `scripts/sync/pg_writer.py` 同一范式:**SQL 构造是纯函数(可单测)**,
执行是薄 psycopg2 封装。列名用 Prisma 默认 camelCase 并加引号,对齐 heng-guan 的
`Monthly` / `MonthlyVersion` / `MonthlyPolicy`。任一侧改列都要同步这里。

两件容易出事、由测试钉住的:

1. **每次投影都留一行 MonthlyVersion**。heng 现有的 `generate()` 不写版本行,
   `changeNote` 那一列至今没人写过,版本历史从第一版起就是断的。首版也写,
   `changeNote` 记「自动生成」,人工意见回炉(MA9)才有得接。
2. **content 里的 policyId 是 pipeline 的 pid,前端要的是 heng 的 `Policy.id`**。
   投影时按 `Policy.pipelinePid` 映射,原 pid 另存 `pipelinePid` 备查。
   映射不到就留空——宁可没链接,也不要链到别人身上。
"""
import argparse
import copy
import datetime
import json
import os
import sys

MONTHLY_INSERT = '''
INSERT INTO "Monthly"
  ("id", "type", "title", "year", "month", "coverDate", "publishDate",
   "status", "content", "aiModel", "aiTokensIn", "aiTokensOut", "aiCostCny",
   "version", "createdAt", "updatedAt")
VALUES
  (gen_random_uuid()::text, 'MONTHLY'::"MonthlyType", %(title)s, %(year)s, %(month)s,
   %(cover_date)s::timestamp, %(publish_date)s,
   %(status)s::"MonthlyStatus", %(content)s::jsonb, %(ai_model)s,
   %(tokens_in)s, %(tokens_out)s, %(cost_cny)s, 1, now(), now())
RETURNING "id"
'''

MONTHLY_UPDATE = '''
UPDATE "Monthly" SET
  "title"       = %(title)s,
  "publishDate" = %(publish_date)s,
  "status"      = %(status)s::"MonthlyStatus",
  "content"     = %(content)s::jsonb,
  "aiModel"     = %(ai_model)s,
  "aiTokensIn"  = %(tokens_in)s,
  "aiTokensOut" = %(tokens_out)s,
  "aiCostCny"   = %(cost_cny)s,
  "version"     = "Monthly"."version" + 1,
  "updatedAt"   = now()
WHERE "id" = %(monthly_id)s
'''

VERSION_INSERT = '''
INSERT INTO "MonthlyVersion"
  ("id", "monthlyId", "version", "content", "changeNote", "createdAt")
VALUES
  (gen_random_uuid()::text, %(monthly_id)s, %(version)s, %(content)s::jsonb,
   %(change_note)s, now())
'''

JOIN_UPSERT = '''
INSERT INTO "MonthlyPolicy" ("monthlyId", "policyId")
VALUES (%(monthly_id)s, %(policy_id)s)
ON CONFLICT ("monthlyId", "policyId") DO NOTHING
'''

MONTHLY_LOOKUP = '''
SELECT "id", "version" FROM "Monthly"
WHERE "type" = 'MONTHLY'::"MonthlyType" AND "year" = %(year)s AND "month" = %(month)s
ORDER BY "createdAt" DESC LIMIT 1
'''

POLICY_LOOKUP = 'SELECT "id" FROM "Policy" WHERE "pipelinePid" = %(pipeline_pid)s'

CONTENT_LOOKUP = '''
SELECT "content" FROM "Monthly"
WHERE "type" = 'MONTHLY'::"MonthlyType" AND "year" = %(year)s AND "month" = %(month)s
ORDER BY "createdAt" DESC LIMIT 1
'''


def build_monthly_insert(row):
    return MONTHLY_INSERT, dict(row, publish_date=_publish_date(row["status"]))


def build_monthly_update(row, monthly_id):
    return MONTHLY_UPDATE, dict(row, monthly_id=monthly_id,
                                publish_date=_publish_date(row["status"]))


def build_version_insert(monthly_id, version, content, change_note):
    return VERSION_INSERT, {"monthly_id": monthly_id, "version": version,
                            "content": content, "change_note": change_note}


def build_join_upsert(monthly_id, policy_id):
    return JOIN_UPSERT, {"monthly_id": monthly_id, "policy_id": policy_id}


def _publish_date(status):
    """只有发布态才落 publishDate;草稿/审核态留空。"""
    if status != "PUBLISHED":
        return None
    return datetime.datetime.now(datetime.timezone.utc)


def _year_month(month):
    year, mon = str(month).split("-")[:2]
    return int(year), int(mon)


def map_policy_ids(content, pid_map):
    """把详情里的 pipeline pid 换成 heng 的 Policy.id,原 pid 留在 pipelinePid。

    映射不到就留空:前端拿空串不渲染链接,拿一个错 id 会把读者送到别的政策上。
    """
    out = copy.deepcopy(content)
    hits = []
    for det in out.get("details") or []:
        pid = det.get("policyId") or ""
        cuid = pid_map.get(pid)
        det["pipelinePid"] = pid
        det["policyId"] = cuid or ""
        if cuid:
            hits.append(cuid)
    return out, hits


def _fetchone(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _execute(conn, sql, params):
    with conn.cursor() as cur:
        cur.execute(sql, params)


def resolve_policy_id(conn, pipeline_pid):
    row = _fetchone(conn, POLICY_LOOKUP, {"pipeline_pid": pipeline_pid})
    return row[0] if row else None


def fetch_content(conn, month):
    """读回某期已投影的 content(MA9 要拿 pendingNote)。没有该期返回 None。"""
    year, mon = _year_month(month)
    row = _fetchone(conn, CONTENT_LOOKUP, {"year": year, "month": mon})
    return row[0] if row else None


def project(conn, content, *, model="", status="PUBLISHED", change_note="自动生成",
            tokens_in=0, tokens_out=0, cost_cny=0.0, dry_run=False):
    """投影一期。返回 {monthly_id, version, policies, dry_run}。"""
    year, month = _year_month(content["month"])
    if dry_run:
        return {"monthly_id": None, "version": 1, "policies": 0, "dry_run": True}
    try:
        pid_map = {}
        for det in content.get("details") or []:
            pid = det.get("policyId")
            if not pid:
                continue
            cuid = resolve_policy_id(conn, pid)
            if cuid:
                pid_map[pid] = cuid
        mapped, hits = map_policy_ids(content, pid_map)
        row = {"title": f"能源政策月刊 · {year} 年 {month} 月",
               "year": year, "month": month,
               "cover_date": f"{year:04d}-{month:02d}-01",
               "status": status, "content": json.dumps(mapped, ensure_ascii=False),
               "ai_model": model or (content.get("provenance") or {}).get("writerModel", ""),
               "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_cny": cost_cny}

        existing = _fetchone(conn, MONTHLY_LOOKUP, {"year": year, "month": month})
        if existing:
            monthly_id, version = existing[0], int(existing[1]) + 1
            _execute(conn, *build_monthly_update(row, monthly_id))
        else:
            monthly_id = _fetchone(conn, *build_monthly_insert(row))[0]
            version = 1
        _execute(conn, *build_version_insert(monthly_id, version,
                                             row["content"], change_note))
        for cuid in hits:
            _execute(conn, *build_join_upsert(monthly_id, cuid))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"monthly_id": monthly_id, "version": version,
            "policies": len(hits), "dry_run": False}


def main(argv=None):
    ap = argparse.ArgumentParser(description="把月刊成稿投影进 heng-pg")
    ap.add_argument("--content", required=True, help="run_monthly 产出的 content.json")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""),
                    help="默认读 DATABASE_URL;不要写进命令行历史")
    ap.add_argument("--status", default="PUBLISHED",
                    choices=["DRAFT", "AUDITING", "PUBLISHED", "ARCHIVED"])
    ap.add_argument("--change-note", default="自动生成")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    with open(a.content, encoding="utf-8") as f:
        content = json.load(f)
    if a.dry_run:
        print(json.dumps(project(None, content, dry_run=True), ensure_ascii=False))
        return 0
    if not a.dsn:
        print("[l3_monthly] 中止:没有 DSN(--dsn 或 DATABASE_URL)", file=sys.stderr)
        return 1
    import psycopg2
    conn = psycopg2.connect(a.dsn)
    try:
        res = project(conn, content, status=a.status, change_note=a.change_note)
    finally:
        conn.close()
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
