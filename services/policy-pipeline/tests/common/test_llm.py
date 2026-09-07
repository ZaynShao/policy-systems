import json
from scripts.common.llm import LLMClient, OpenAICompatClient

class _FakeMessages:
    def create(self, **kw):
        class R:  # 模拟 anthropic 响应
            content = [type("B", (), {"text": "POLICY"})()]
        return R()

class _FakeAnthropic:
    def __init__(self, **kw): self.messages = _FakeMessages()

def test_complete_returns_text_and_logs(tmp_path):
    log = tmp_path / "llm_calls.jsonl"
    c = LLMClient(client=_FakeAnthropic(), model="m-test", log_path=str(log))
    out = c.complete("sys", "user")
    assert out == "POLICY"
    line = json.loads(log.read_text().strip())
    assert line["model"] == "m-test"
    assert line["temperature"] == 0
    assert "prompt_sha" in line and "ts" in line


def test_openai_compat_complete_and_log(tmp_path):
    captured = {}
    def fake_post(url, payload, api_key):
        captured["url"] = url; captured["payload"] = payload; captured["key"] = api_key
        return {"choices": [{"message": {"content": "通了"}}]}
    log = tmp_path / "calls.jsonl"
    c = OpenAICompatClient(model="qwen3.6-plus", log_path=str(log),
                           base_url="https://x/v1", api_key="k", _post=fake_post)
    out = c.complete("sys", "user", max_tokens=64)
    assert out == "通了"
    assert captured["url"] == "https://x/v1/chat/completions"
    assert captured["payload"]["model"] == "qwen3.6-plus"
    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["max_tokens"] == 64
    assert captured["payload"]["messages"][0] == {"role": "system", "content": "sys"}
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "user"}
    assert captured["key"] == "k"
    line = json.loads(log.read_text().strip())
    assert line["model"] == "qwen3.6-plus" and line["output_chars"] == 2


# ── 网关别名:请求的模型名 ≠ 真正跑的模型 ────────────────────────────
#
# 本平台网关 /models 只有 deepseek-v4-flash / v4-pro / v4-flash-vision-exp 三条。
# 请求 deepseek-chat 或 deepseek-reasoner 一律 HTTP 200,响应里却自报
# deepseek-v4-flash(2026-08-28 实测)。只记我们请求的名字,日志就会信誓旦旦地说
# "这批换了模型跑",而其实没换——2026-09-03 那轮复判测量正是这么白跑的。
def test_reported_model_is_logged_when_the_gateway_swaps_it(tmp_path):
    def fake_post(url, payload, api_key):
        return {"model": "deepseek-v4-flash",          # 网关自报:不是我们点的那个
                "choices": [{"message": {"content": "ok"}}]}
    log = tmp_path / "calls.jsonl"
    c = OpenAICompatClient(model="deepseek-chat", log_path=str(log),
                           base_url="https://x/v1", api_key="k", _post=fake_post)
    c.complete("sys", "user")
    line = json.loads(log.read_text().strip())
    assert line["model"] == "deepseek-chat", "请求的名字照记"
    assert line["model_reported"] == "deepseek-v4-flash", "网关自报的名字也要留痕"
    assert c.last_reported_model == "deepseek-v4-flash", "调用方要能当场读到"


def test_reported_model_is_not_logged_when_it_matches(tmp_path):
    """没换的时候不记,免得每行都多一个恒等字段。"""
    def fake_post(url, payload, api_key):
        return {"model": "qwen3.6-plus", "choices": [{"message": {"content": "ok"}}]}
    log = tmp_path / "calls.jsonl"
    c = OpenAICompatClient(model="qwen3.6-plus", log_path=str(log),
                           base_url="https://x/v1", api_key="k", _post=fake_post)
    c.complete("sys", "user")
    assert "model_reported" not in json.loads(log.read_text().strip())


def test_missing_model_field_does_not_break_the_call(tmp_path):
    """有些兼容端点不回 model 字段。读不到就是读不到,不该让调用挂掉。"""
    def fake_post(url, payload, api_key):
        return {"choices": [{"message": {"content": "ok"}}]}
    c = OpenAICompatClient(model="m", log_path=str(tmp_path / "c.jsonl"),
                           base_url="https://x/v1", api_key="k", _post=fake_post)
    assert c.complete("sys", "user") == "ok"
    assert c.last_reported_model is None
