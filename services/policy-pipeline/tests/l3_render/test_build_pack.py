"""MA4 装包:必须能被程序调用,且上游缺件时告警而非崩。

装包是 F 门成立的物理前提——稿子里每个数字都要在某个 bundle 里回指得到。
所以这一步的失败模式不是"跑不出来",而是**悄悄少装了料**:
关系文件不存在就整批没有承接血缘、analysis_context 缺件就没有信号叠加,
而稿子照写不误。故缺件一律显式告警并记进 INDEX,不静默吞掉。
"""
import json
import os

import pytest

from scripts.l3_render import build_month_pack as bp


# ── 夹具 ────────────────────────────────────────────────────────
def _policy(pol_dir, pid, title, body, docno="", date="2026-07-10",
            region="江苏省", level="province", fname=None):
    os.makedirs(pol_dir, exist_ok=True)
    md = (f"---\nid: {pid}\ntitle: {title}\nofficial_number: {docno}\n"
          f"date: {date}\ntype: policy\nregion:\n  name: {region}\n"
          f"  level: {level}\n---\n\n{body}\n")
    path = os.path.join(pol_dir, (fname or f"{pid}") + ".md")
    open(path, "w", encoding="utf-8").write(md)
    return path


def _slate(**over):
    base = {
        "month": "2026-07",
        "narrative": "本月定调",
        "sections": {
            "national_detail": [{"policy_id": "P_A", "title_hint": "甲文件",
                                 "score": "5分", "rank": 1, "why": "旗舰", "dq": ""}],
            "local_detail": [{"policy_id": "P_B", "title_hint": "乙文件",
                              "score": "4分", "rank": 2, "why": "地方", "dq": ""}],
            "roundup": [], "appendix": [],
        },
    }
    base.update(over)
    return base


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    pol = str(v / "0_raw" / "policies")
    _policy(pol, "P_A", "甲文件", "甲正文" * 10, docno="发改能源〔2026〕1号")
    _policy(pol, "P_B", "乙文件", "乙正文" * 10)
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    open(str(v / "_meta" / "business_view" / "P_A.yaml"), "w",
         encoding="utf-8").write("signals: [F02]\n")
    os.makedirs(str(v / "0_raw" / "commentaries"), exist_ok=True)
    return str(v)


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "state"
    d = s / "analysis_layer" / "nightly"
    os.makedirs(str(d), exist_ok=True)
    open(str(d / "analysis_context.jsonl"), "w", encoding="utf-8").write(
        json.dumps({"policy_id": "P_A", "audit_refs": {"commentary_ids": []}},
                   ensure_ascii=False) + "\n")
    return str(s)


# ── ① 可程序调用 ────────────────────────────────────────────────
def test_exposes_build_pack():
    """MA8 编排要在进程内调用装包,不能只有 CLI。"""
    assert hasattr(bp, "build_pack")


def test_build_pack_writes_bundles_and_index(vault, state, tmp_path):
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), vault, state, out)

    idx = json.load(open(os.path.join(out, "INDEX.json"), encoding="utf-8"))
    assert idx["month"] == "2026-07" and idx["narrative"] == "本月定调"
    assert res.index == idx
    files = [i["file"] for i in idx["items"]]
    assert files == ["01_national_detail__P_A.md", "02_local_detail__P_B.md"]
    for f in files:
        assert os.path.exists(os.path.join(out, f))
    a = next(i for i in idx["items"] if i["policy_id"] == "P_A")
    assert a["level_editorial"] == "国家级" and a["has_bv"] and a["has_ac"]


def test_bundle_contains_the_five_ingredients(vault, state, tmp_path):
    """RAW / business_view / analysis_context / 关系边 / 评论校准——F 门的物理前提。"""
    out = str(tmp_path / "pack")
    bp.build_pack(_slate(), vault, state, out)
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    for section in ("## RAW 原文", "## business_view", "## analysis_context", "## 关系边"):
        assert section in txt
    assert "甲正文" in txt


# ── ② 上游缺件:告警不崩 ────────────────────────────────────────
def test_missing_relations_file_warns_not_crashes(vault, state, tmp_path):
    """本地热备 vault 就没有 relations_canonical.jsonl(只有 _index_by_policy)。
    原实现直接 open() 会 FileNotFoundError,整个装包炸掉。"""
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), vault, state, out)
    assert any("relations" in w for w in res.warnings)
    assert res.index["warnings"] == res.warnings


def test_missing_analysis_context_warns_not_crashes(vault, tmp_path):
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), vault, str(tmp_path / "no_state"), out)
    assert any("analysis_context" in w for w in res.warnings)
    assert res.index["items"] and all(not i.get("has_ac") for i in res.index["items"])


def test_missing_raw_recorded_and_numbering_stays_contiguous(vault, state, tmp_path):
    """选目里有库里没有的 pid 时,既不能崩,也不能把编号让出一个空位。"""
    s = _slate()
    s["sections"]["national_detail"].insert(
        0, {"policy_id": "P_GHOST", "title_hint": "查无此件", "score": "5分",
            "rank": 0, "why": "", "dq": ""})
    out = str(tmp_path / "pack")
    res = bp.build_pack(s, vault, state, out)
    ghost = next(i for i in res.index["items"] if i["policy_id"] == "P_GHOST")
    assert ghost["status"] == "MISSING_RAW" and "file" not in ghost
    assert [i["file"] for i in res.index["items"] if i.get("file")] == [
        "01_national_detail__P_A.md", "02_local_detail__P_B.md"]


# ── ③ MA2 判定入包(MA5a 的决策建议靠它) ────────────────────────
def _judgment(pid, hits):
    return {"policy_id": pid, "level": "国家", "issue_date_from_body": "2026年7月8日",
            "issuer_from_body": "国家能源局", "official_number_from_body": "国能发〔2026〕42号",
            "business_hits": hits, "decision_variables_touched": ["F02"],
            "relevance": "high", "why": "改变加油站开票流程", "dq": ""}


def test_bundle_carries_ma2_judgment(vault, state, tmp_path):
    """spec §6.3:MA5a 的决策建议**只列 MA2 算出的 business_hits**——
    那就必须装进 bundle,否则写作那步无从遵守。"""
    out = str(tmp_path / "pack")
    bp.build_pack(_slate(), vault, state, out,
                  judgments={"P_A": _judgment("P_A", ["fuel", "charging"])})
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    assert "## MA2 判定" in txt
    assert "fuel" in txt and "charging" in txt
    assert "国家能源局" in txt and "国能发〔2026〕42号" in txt and "2026年7月8日" in txt


def test_business_ids_rendered_with_profile_names(vault, state, tmp_path):
    """中文名取自画像的 businesses[].zh,**不在代码里另抄一份口径**。"""
    out = str(tmp_path / "pack")
    bp.build_pack(_slate(), vault, state, out,
                  judgments={"P_A": _judgment("P_A", ["fuel"])},
                  business_names={"fuel": "加油", "charging": "充电", "power": "电力"})
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    assert "加油" in txt


def test_no_ma2_section_when_no_judgment(vault, state, tmp_path):
    out = str(tmp_path / "pack")
    bp.build_pack(_slate(), vault, state, out)
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    assert "## MA2 判定" not in txt


def test_judgment_error_is_not_passed_off_as_fact(vault, state, tmp_path):
    """relevance=error 是「这篇没判成」,不是判定。装进包里会被当成事实写进稿。"""
    j = _judgment("P_A", [])
    j.update(relevance="error", dq="模型输出连续 2 次不可用")
    out = str(tmp_path / "pack")
    bp.build_pack(_slate(), vault, state, out, judgments={"P_A": j})
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    assert "国家能源局" not in txt
    assert "未判定" in txt


# ── ④ 长正文:RAW 段头尾都取,给 MA5d 的正文不截断 ────────────
def test_long_raw_keeps_signoff_via_head_and_tail(tmp_path, state):
    """本地 vault 实测 14.7% 的政策正文超 9000 字符。bundle 明写「以 RAW 落款为准」,
    而落款在文末——只截头就等于把它承诺的事实源切掉了。与 MA2 摘录同一条规则。"""
    v = tmp_path / "v"
    pol = str(v / "0_raw" / "policies")
    long_body = "开头标记" + "正文" * 6000 + "\n\n国家能源局\n2026年7月8日\n"
    _policy(pol, "P_A", "甲文件", long_body, docno="发改能源〔2026〕1号")
    _policy(pol, "P_B", "乙文件", "乙正文")
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), str(v), state, out)

    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    raw = txt.split("## RAW 原文", 1)[1].split("## business_view", 1)[0]
    assert "开头标记" in raw, "文头必须在"
    assert "国家能源局" in raw and "2026年7月8日" in raw, "落款必须在"
    assert "略" in raw, "中间省略要标出来,免得读成连续正文"
    # 余量给小标题、中略标记与截断声明,正文本身仍是 7500+1500
    assert len(raw) <= bp.RAW_HEAD + bp.RAW_TAIL + 300, "预算不得超出原来的 9000"


def test_meta_body_is_untruncated_for_ma5d(tmp_path, state):
    """速览表(MA5d)从正文抽落款,拿的必须是全文——它不受 bundle 的上下文预算约束。"""
    v = tmp_path / "v"
    pol = str(v / "0_raw" / "policies")
    long_body = "正文" * 6000 + "\n\n国家能源局\n2026年7月8日\n"
    _policy(pol, "P_A", "甲文件", long_body)
    _policy(pol, "P_B", "乙文件", "乙正文")
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    res = bp.build_pack(_slate(), str(v), state, str(tmp_path / "pack"))
    assert res.meta_by_pid["P_A"]["body"].strip() == long_body.strip()
    assert res.meta_by_pid["P_A"]["title"] == "甲文件"


# ── ⑤ id 撞车靠 title_hint 消歧 ────────────────────────────────
def test_id_collision_resolved_by_title_hint(tmp_path, state):
    """已知 vault 缺陷:一个 policy_id 挂多份文件(JS_FGW_10 挂了 7 份)。"""
    v = tmp_path / "v"
    pol = str(v / "0_raw" / "policies")
    _policy(pol, "P_A", "甲文件第一期", "第一期正文", fname="a1")
    _policy(pol, "P_A", "甲文件第二期", "第二期正文", fname="a2")
    _policy(pol, "P_B", "乙文件", "乙正文")
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    s = _slate()
    s["sections"]["national_detail"][0]["title_hint"] = "第二期"
    out = str(tmp_path / "pack")
    res = bp.build_pack(s, str(v), state, out)
    a = next(i for i in res.index["items"] if i["policy_id"] == "P_A")
    assert a["dup_raw"] == 2
    assert "第二期正文" in res.meta_by_pid["P_A"]["body"]


# ── ⑥ CLI 仍可用 ───────────────────────────────────────────────
def test_cli_still_works(vault, state, tmp_path, capsys):
    out = str(tmp_path / "pack")
    slate_path = str(tmp_path / "slate.json")
    json.dump(_slate(), open(slate_path, "w", encoding="utf-8"), ensure_ascii=False)
    rc = bp.main(["--slate", slate_path, "--vault", vault,
                  "--state", state, "--out", out])
    assert rc == 0
    assert os.path.exists(os.path.join(out, "INDEX.json"))
    assert "bundles: 2" in capsys.readouterr().out


def test_cli_loads_judgments_jsonl(vault, state, tmp_path):
    out = str(tmp_path / "pack")
    slate_path = str(tmp_path / "slate.json")
    json.dump(_slate(), open(slate_path, "w", encoding="utf-8"), ensure_ascii=False)
    jpath = str(tmp_path / "judgments.jsonl")
    with open(jpath, "w", encoding="utf-8") as f:
        f.write(json.dumps(_judgment("P_A", ["fuel"]), ensure_ascii=False) + "\n")
    assert bp.main(["--slate", slate_path, "--vault", vault, "--state", state,
                    "--out", out, "--judgments", jpath]) == 0
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    assert "## MA2 判定" in txt


# ── ⑦ 真数据审计补上的两条(2026-09-07) ─────────────────────────
def test_present_but_empty_analysis_context_still_warns(vault, tmp_path):
    """本地路线跑真数据时:ac 文件在、但是空的,10/10 个 bundle 一条信号都没装,
    而 warnings 是空的。**文件存在**不等于**装到了料**——最安静的失败模式。"""
    st = tmp_path / "st"
    d = st / "analysis_layer" / "nightly"
    os.makedirs(str(d), exist_ok=True)
    open(str(d / "analysis_context.jsonl"), "w").close()
    res = bp.build_pack(_slate(), vault, str(st), str(tmp_path / "pack"))
    assert any("无一命中" in w for w in res.warnings)


def test_truncated_raw_is_declared_in_bundle_and_manifest(tmp_path, state):
    """实测有一篇 21 万字符的《行业标准制定计划》附件表进了 shortlist,
    装进来的只有 4%。不说出来,写作那步会以为自己读的是全文。"""
    v = tmp_path / "v"
    pol = str(v / "0_raw" / "policies")
    _policy(pol, "P_A", "甲文件", "正文" * 8000)
    _policy(pol, "P_B", "乙文件", "短正文")
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), str(v), state, out)

    a = next(i for i in res.index["items"] if i["policy_id"] == "P_A")
    b = next(i for i in res.index["items"] if i["policy_id"] == "P_B")
    assert a["raw_truncated"] and a["body_len"] == 16000
    assert not b["raw_truncated"]
    txt = open(os.path.join(out, a["file"]), encoding="utf-8").read()
    assert "不得声称已通读全文" in txt and "16000" in txt
    assert any("超出 RAW 预算" in w and "P_A" in w for w in res.warnings)


def test_bundle_raw_has_no_urls(vault, state, tmp_path):
    """URL 本身在 D 门禁项上(过程性元信息),装进事实源里只是招违规。"""
    v = tmp_path / "v"
    pol = str(v / "0_raw" / "policies")
    _policy(pol, "P_A", "甲文件", "![](http://a.gov.cn/1.jpg)[新闻中心](https://a.gov.cn/x/)第一条 正文")
    _policy(pol, "P_B", "乙文件", "乙正文")
    os.makedirs(str(v / "_meta" / "business_view"), exist_ok=True)
    out = str(tmp_path / "pack")
    res = bp.build_pack(_slate(), str(v), state, out)
    txt = open(os.path.join(out, "01_national_detail__P_A.md"), encoding="utf-8").read()
    raw = txt.split("## RAW 原文", 1)[1].split("## business_view", 1)[0]
    assert "http" not in raw and "新闻中心第一条 正文" in raw
    # 速览表抽落款用的仍是未清理的全文,免得动摇已实测过的抽取口径
    assert "http" in res.meta_by_pid["P_A"]["body"]
