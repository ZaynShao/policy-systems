"""MA4→MA8 编排:装包 → 分块写作 → 两道门 → 返修 → 组稿。

MA0–MA3(选目)已经有 run_slate 那条链,这里从**已有 slate.json** 接上,
因为选目一轮要判两百多篇、几十万 token,写作出了 bug 不该把它重跑一遍。

这条链的验收标准只有一条:**它永远交得出稿**。门过不了转容错提示照常发布,
是用户定的口径。
"""
import json
import os

import pytest

from scripts.l3_monthly import run_monthly


PROFILE_YAML = """\
schema_version: 1
status: active
profile_id: t2026
effective_from: 2026-08-31
businesses:
  - id: fuel
    zh: 加油
    headline: 加油站网络
    decision_variables: [消费税]
  - id: charging
    zh: 充电
    headline: 充电网络
    decision_variables: [电价]
  - id: power
    zh: 电力
    headline: 电力交易
    decision_variables: [现货]
relevance_rules:
  core_test: 是否改变在做的决策
signals: []
open_questions: []
"""


def _vault(tmp_path):
    v = tmp_path / "vault"
    pol = v / "0_raw" / "policies"
    os.makedirs(str(pol))
    os.makedirs(str(v / "_meta" / "business_view"))
    os.makedirs(str(v / "_meta" / "framework"))
    os.makedirs(str(v / "0_raw" / "commentaries"))
    (v / "_meta" / "framework" / "business_strategy.yaml").write_text(
        PROFILE_YAML, encoding="utf-8")
    for pid, title in (("P_A", "甲文件"), ("P_B", "乙文件"), ("P_C", "丙文件")):
        (pol / f"{pid}.md").write_text(
            f"---\nid: {pid}\ntitle: {title}\nofficial_number: \ndate: 2026-07-10\n"
            f"type: policy\nregion:\n  name: 江苏省\n  level: province\n---\n\n"
            f"{title}正文。第三条要求年底前完成备案。国家能源局\n2026年7月8日\n", encoding="utf-8")
    return str(v)


def _slate(out):
    os.makedirs(out, exist_ok=True)
    slate = {"month": "2026-07", "narrative": "本月定调", "sections": {
        "national_detail": [{"policy_id": "P_A", "title_hint": "甲文件", "score": "5分",
                             "rank": 1, "why": "旗舰", "dq": ""}],
        "local_detail": [{"policy_id": "P_B", "title_hint": "乙文件", "score": "4分",
                          "rank": 2, "why": "地方", "dq": ""}],
        "roundup": [{"policy_id": "P_C", "title_hint": "丙文件", "score": "3分",
                     "rank": 3, "why": "速览", "dq": ""}],
        "appendix": []}}
    with open(os.path.join(out, "slate.json"), "w", encoding="utf-8") as f:
        json.dump(slate, f, ensure_ascii=False)
    with open(os.path.join(out, "judgments.jsonl"), "w", encoding="utf-8") as f:
        for pid, hits in (("P_A", ["charging"]), ("P_B", ["charging"]),
                          ("P_C", ["fuel"])):
            f.write(json.dumps({
                "policy_id": pid, "level": "国家", "business_hits": hits,
                "decision_variables_touched": [], "relevance": "high",
                "why": "改变备案口径", "dq": "",
                "issue_date_from_body": "2026年7月8日",
                "issuer_from_body": "国家能源局",
                "official_number_from_body": "国能发〔2026〕42号"}, ensure_ascii=False) + "\n")
    return out


DETAIL = json.dumps({"info": "发文机关:国家能源局。", "reading": "改了备案口径。",
                     "focus": "第三条要求年底前完成。",
                     "advice": [{"business": "充电", "tag": "C 跟踪",
                                 "text": "跟进备案。"}]}, ensure_ascii=False)
OVERVIEW = json.dumps({"overview": "本月政策密度抬升。", "businessTakes": [
    {"business": "充电", "text": "备案口径要摸清。"},
    {"business": "加油", "text": "成品油调价密集。"}]}, ensure_ascii=False)


class RouterClient:
    """按 system 段分派——编排里各步用的是同一个 client。"""

    def __init__(self, detail=DETAIL, overview=OVERVIEW):
        self.detail, self.overview = detail, overview
        self.by_step = {}

    def complete(self, system, user, max_tokens=None):
        if system.startswith("你是《能源政策月刊》的撰稿人,为一家能源平台公司的决策层"):
            step = "detail"
            out = self.detail
        elif "写本期的省级综述" in system:
            step, out = "roundup", "江苏等省本月集中调整了备案口径。"
        elif "写本期附录" in system:
            step, out = "appendix", "国务院专题学习释放信号。"
        elif "写本期概述与三大业务速判" in system:
            step, out = "overview", self.overview
        else:
            step, out = "repair", "改了备案口径。"
        self.by_step[step] = self.by_step.get(step, 0) + 1
        return out


def test_end_to_end_produces_v2_content_and_files(tmp_path):
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    client = RouterClient()
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=client, skip_slate=True)

    content = res["content"]
    assert content["schema"] == "monthly.v2" and content["month"] == "2026-07"
    assert [d["policyId"] for d in content["details"]] == ["P_A", "P_B"]
    assert content["localRoundup"] and content["overview"]
    assert os.path.exists(os.path.join(out, "content.json"))
    assert os.path.exists(res["outputs"]["final_md"])
    # 每篇详情各一次调用,综述/概述各一次
    assert client.by_step["detail"] == 2 and client.by_step["overview"] == 1


def test_roundup_business_reaches_the_takes(tmp_path):
    """P_C 只进速览、只命中加油。速判必须还能给加油一条——
    否则一个满是成品油调价的月份会出一份「本月加油线没事」的月刊。"""
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=RouterClient(), skip_slate=True)
    assert {t["business"] for t in res["content"]["businessTakes"]} == {"充电", "加油"}


def test_quick_table_comes_from_ma2_facts(tmp_path):
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=RouterClient(), skip_slate=True)
    row = res["content"]["quickTable"][0]
    assert row["issuer"] == "国家能源局" and row["doc_no"] == "国能发〔2026〕42号"


def test_gate_failures_become_caveats_and_still_publish(tmp_path):
    """门过不了**不是不发布**。返修两轮仍不过 → 挂容错提示照常出稿。"""
    bad = json.dumps({"info": "发文机关:国家能源局。", "reading": "改了「备案」口径。",
                      "focus": "第三条要求年底前完成。", "advice": []},
                     ensure_ascii=False)
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    client = RouterClient(detail=bad)
    client.complete = lambda system, user, max_tokens=None, _c=client: (
        "还是「不行」。" if "【审计意见】" in user
        else RouterClient.complete(_c, system, user, max_tokens))
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=client, skip_slate=True)
    caveats = res["content"]["caveats"]
    assert any(c["gate"] == "D" for c in caveats)
    assert res["content"]["provenance"]["auditRounds"] == 2
    assert os.path.exists(res["outputs"]["final_md"])
    assert "敬请谅解" in open(res["outputs"]["final_md"], encoding="utf-8").read()


def test_one_failed_detail_does_not_sink_the_issue(tmp_path):
    """一篇写不出来不该毁掉整期:它变成 caveat,其余照常出。"""
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    client = RouterClient()
    calls = {"n": 0}
    orig = client.complete

    def flaky(system, user, max_tokens=None):
        if "甲文件" in user and "【审计意见】" not in user:
            calls["n"] += 1
            return "不是 JSON"
        return orig(system, user, max_tokens)

    client.complete = flaky
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=client, skip_slate=True)
    assert [d["policyId"] for d in res["content"]["details"]] == ["P_B"]
    assert any("P_A" in c["note"] for c in res["content"]["caveats"])


def test_missing_slate_is_a_clear_error_not_a_crash(tmp_path):
    with pytest.raises(run_monthly.MonthlyError):
        run_monthly.run(month="2026-07", vault=_vault(tmp_path),
                        state=str(tmp_path / "st"), out=str(tmp_path / "empty"),
                        client=RouterClient(), skip_slate=True)


def test_repair_chain_runs_exactly_once(tmp_path):
    """返修链只能跑一遍。跑两遍会把返修预算和账单都翻倍,而且 auditRounds 说不清。"""
    bad = json.dumps({"info": "发文机关:国家能源局。", "reading": "改了「备案」口径。",
                      "focus": "第三条要求年底前完成。", "advice": []},
                     ensure_ascii=False)
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    client = RouterClient(detail=bad)
    n = {"repair": 0}
    base = client.complete

    def counting(system, user, max_tokens=None):
        if "【审计意见】" in user:
            n["repair"] += 1
            return "还是「不行」。"
        return base(system, user, max_tokens)

    client.complete = counting
    res = run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                          out=out, client=client, skip_slate=True)
    # 2 篇详情 × 1 个违规段 × 2 轮 = 4 次;跑两遍链路就会变成 8 次
    assert n["repair"] == 4 and res["content"]["provenance"]["auditRounds"] == 2


def test_invalid_slate_is_refused_rather_than_silently_miswritten(tmp_path):
    """跨分区重复的 policy_id 会让装包写出两个 bundle 而 bundles 字典只留最后一个,
    第二篇详情就拿着别人的素材写。--skip-slate 复用旧 slate 时这是真会发生的。"""
    vault, out = _vault(tmp_path), str(tmp_path / "wk")
    _slate(out)
    with open(os.path.join(out, "slate.json"), encoding="utf-8") as f:
        slate = json.load(f)
    slate["sections"]["local_detail"][0]["policy_id"] = "P_A"   # 与国家级重复
    with open(os.path.join(out, "slate.json"), "w", encoding="utf-8") as f:
        json.dump(slate, f, ensure_ascii=False)
    with pytest.raises(run_monthly.MonthlyError) as exc:
        run_monthly.run(month="2026-07", vault=vault, state=str(tmp_path / "st"),
                        out=out, client=RouterClient(), skip_slate=True)
    assert "P_A" in str(exc.value)
