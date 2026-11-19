"""调用用量记录。

`OpenAICompatClient` 只把 content 交出来,响应里的 `usage` 被丢掉了;
`llm_calls.jsonl` 因此只有 model / temperature / prompt_sha / output_chars,
**没有 token 数**。而 spec §11 与 runbook 都写着"用这份日志校准成本"——
2026-09-08 首跑时才发现这件事对不上。

`llm.py` 不在本次可改范围,但 `OpenAICompatClient` 的 `_post` 是可注入的,
从那里把 usage 抄一份出来即可,不动共用客户端。

v4pro 是推理模型,**推理 token 计在 completion_tokens 里、按输出价计费**,
所以这份记录必须把 reasoning 单列出来,否则看不出钱花在哪。
"""
import json

from scripts.l3_monthly import usage


def _response(prompt=100, completion=200, reasoning=150, cache_hit=0):
    return {
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"content": "答复"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
            "prompt_cache_hit_tokens": cache_hit,
            "prompt_cache_miss_tokens": prompt - cache_hit,
        },
    }


def test_wrap_passes_the_response_through_untouched():
    rec = usage.UsageRecorder("/dev/null")
    inner_called = {}

    def inner(url, payload, key):
        inner_called["url"] = url
        return _response()

    out = rec.wrap(inner)("http://x/chat/completions", {"model": "m"}, "k")
    assert out == _response() and inner_called["url"] == "http://x/chat/completions"


def test_records_tokens_including_reasoning(tmp_path):
    path = str(tmp_path / "usage.jsonl")
    rec = usage.UsageRecorder(path)
    rec.wrap(lambda u, p, k: _response(prompt=2800, completion=1700,
                                       reasoning=1600, cache_hit=1900))(
        "u", {"model": "deepseek-v4-pro"}, "k")
    row = json.loads(open(path, encoding="utf-8").read().strip())
    assert row["prompt_tokens"] == 2800 and row["completion_tokens"] == 1700
    assert row["reasoning_tokens"] == 1600
    assert row["cache_hit_tokens"] == 1900 and row["cache_miss_tokens"] == 900


def test_records_finish_reason_so_truncation_is_visible(tmp_path):
    """预算被推理吃光时 finish_reason=length 且正文为空——这是唯一能看出来的地方。"""
    path = str(tmp_path / "usage.jsonl")
    resp = _response(completion=4000, reasoning=4000)
    resp["choices"][0]["finish_reason"] = "length"
    resp["choices"][0]["message"]["content"] = ""
    usage.UsageRecorder(path).wrap(lambda u, p, k: resp)("u", {}, "k")
    row = json.loads(open(path, encoding="utf-8").read().strip())
    assert row["finish_reason"] == "length" and row["output_chars"] == 0


def test_missing_usage_does_not_break_the_call(tmp_path):
    """网关不返回 usage 也不能让整条链挂掉。"""
    path = str(tmp_path / "usage.jsonl")
    out = usage.UsageRecorder(path).wrap(lambda u, p, k: {"choices": [
        {"message": {"content": "x"}}]})("u", {}, "k")
    assert out["choices"][0]["message"]["content"] == "x"
    row = json.loads(open(path, encoding="utf-8").read().strip())
    assert row["prompt_tokens"] == 0


def test_summarise_totals_and_costs(tmp_path):
    path = str(tmp_path / "usage.jsonl")
    rec = usage.UsageRecorder(path)
    post = rec.wrap(lambda u, p, k: _response(prompt=1000, completion=2000,
                                              reasoning=1900, cache_hit=800))
    for _ in range(3):
        post("u", {"model": "deepseek-v4-pro"}, "k")
    s = usage.summarise(path)
    assert s["calls"] == 3
    assert s["prompt_tokens"] == 3000 and s["completion_tokens"] == 6000
    assert s["reasoning_tokens"] == 5700
    assert s["cache_hit_tokens"] == 2400 and s["cache_miss_tokens"] == 600
    # 推理占了输出的绝大部分——这正是 v4pro 账单的大头
    assert s["reasoning_share"] > 0.9


def test_summarise_on_missing_file_is_empty(tmp_path):
    assert usage.summarise(str(tmp_path / "nope.jsonl"))["calls"] == 0


def test_build_client_wires_the_recorder(tmp_path):
    """真跑要能自动记账,不能靠operator另外加参数。"""
    from scripts.l3_monthly import run_slate
    path = str(tmp_path / "usage.jsonl")
    client = run_slate.build_client("openai", "deepseek-v4-pro",
                                    str(tmp_path / "calls.jsonl"), usage_path=path)
    assert client._post is not client._http_post, "_post 没有被包上,usage 不会被记"


def test_build_client_without_usage_path_is_unchanged(tmp_path):
    from scripts.l3_monthly import run_slate
    client = run_slate.build_client("openai", "m", str(tmp_path / "c.jsonl"))
    assert client._post == client._http_post
