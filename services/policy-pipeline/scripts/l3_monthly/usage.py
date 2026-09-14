"""调用用量记录。

`OpenAICompatClient` 只把 content 交出来,响应里的 `usage` 被丢掉了;
`llm_calls.jsonl` 因此只有 model / temperature / prompt_sha / output_chars,
**没有 token 数**——而 spec §11 与 runbook 都写着"用这份日志校准成本"。
2026-09-08 首跑时才发现这件事对不上。

`scripts/common/llm.py` 是共用客户端、不在本次可改范围,但
`OpenAICompatClient(_post=...)` 是可注入的:从那个口子把 usage 抄一份出来,
既拿到数据又不动共用代码。

v4pro 是推理模型,**推理 token 计在 completion_tokens 里、按输出价计费**
(实测判定任务:推理 1291–2564,正文只有约 50 token),所以这份记录必须把
reasoning 单列——不然看不出钱花在哪。同时记 finish_reason:预算被推理吃光时
它是 `length` 且正文为空,那是唯一能看出"这一次其实什么都没产出"的地方。
"""
import json
import os


class UsageRecorder:
    """包住 `_post`,把每次调用的 usage 追加成一行 JSON。"""

    def __init__(self, path):
        self.path = path

    def wrap(self, post):
        def wrapped(url, payload, api_key):
            data = post(url, payload, api_key)
            try:
                self._record(payload, data)
            except Exception:  # noqa: BLE001 —— 记账失败绝不能影响正事
                pass
            return data
        return wrapped

    def _record(self, payload, data):
        u = (data or {}).get("usage") or {}
        choice = ((data or {}).get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        row = {
            "model": (data or {}).get("model") or (payload or {}).get("model", ""),
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "reasoning_tokens": (u.get("completion_tokens_details") or {})
                                .get("reasoning_tokens", 0),
            "cache_hit_tokens": u.get("prompt_cache_hit_tokens", 0),
            "cache_miss_tokens": u.get("prompt_cache_miss_tokens", 0),
            "finish_reason": choice.get("finish_reason", ""),
            "output_chars": len(content),
        }
        if self.path and self.path != "/dev/null":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".",
                        exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


_FIELDS = ("prompt_tokens", "completion_tokens", "reasoning_tokens",
           "cache_hit_tokens", "cache_miss_tokens")


def summarise(path):
    """把一次跑的用量汇总。`reasoning_share` 是推理占输出的比例——v4pro 的账单大头。"""
    out = {"calls": 0, "truncated": 0, "empty": 0, **{f: 0 for f in _FIELDS}}
    if not os.path.exists(path):
        out["reasoning_share"] = 0.0
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            out["calls"] += 1
            for field in _FIELDS:
                out[field] += row.get(field, 0)
            if row.get("finish_reason") == "length":
                out["truncated"] += 1
            if not row.get("output_chars"):
                out["empty"] += 1
    completion = out["completion_tokens"]
    out["reasoning_share"] = (out["reasoning_tokens"] / completion) if completion else 0.0
    return out
