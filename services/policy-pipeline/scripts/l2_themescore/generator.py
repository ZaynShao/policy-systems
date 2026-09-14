import json, re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

def parse_json_block(text: str) -> dict:
    m = _FENCE.search(text)
    raw = m.group(1) if m else text
    return json.loads(raw)


class MalformedOutput(ValueError):
    """模型这次没给出可用结果:不是 JSON、顶层不是对象、或缺必需键。"""


def _coerce(text: str, required_keys) -> dict:
    """解析 + 形状校验。任一不过都抛 MalformedOutput,由调用方决定是否重试。

    `json.loads("null")` 会**成功**并返回 None,所以顶层类型必须显式判。
    """
    out = parse_json_block(text)
    if not isinstance(out, dict):
        raise MalformedOutput(f"顶层不是对象:{type(out).__name__}")
    missing = [k for k in required_keys if k not in out]
    if missing:
        raise MalformedOutput(f"缺必需键:{','.join(missing)}")
    return out


def _complete_json(client, system, user, max_tokens=1024, required_keys=()) -> dict:
    """三次机会拿到一个**形状正确**的 JSON。

    required_keys 的校验必须在重试圈**内**。模型返回合法 JSON 但少了字段,与返回
    非 JSON 是同一件事——这次没生成出来,都该再试一次。2026-09-07 查实:少 scores
    这种情况以前在圈外才被发现(plan() 里 o1["scores"] 抛 KeyError),一次重试都没有,
    该篇政策当场出局且不再重来;51 篇静默丢件里有相当一部分是这么没的。
    """
    hint = ""
    if required_keys:
        hint = f"\n必须包含这些顶层键:{', '.join(required_keys)}。"
    txt = client.complete(system=system, user=user, max_tokens=max_tokens)
    try:
        return _coerce(txt, required_keys)
    except Exception:
        txt = client.complete(system=system + "\n\n严格:只输出 JSON,不要任何其他字符。" + hint,
                              user=user, max_tokens=max_tokens)
        try:
            return _coerce(txt, required_keys)
        except Exception:
            repair_user = (
                "下面文本本应是 JSON,但格式有误。请只返回修复后的合法 JSON,不要解释。"
                f"{hint}\n\n{txt}"
            )
            txt = client.complete(system="你是 JSON 修复器。只输出合法 JSON,不要任何其他字符。",
                                  user=repair_user, max_tokens=max_tokens)
            return _coerce(txt, required_keys)

# reasoning 模型(MiniMax-M2.7 等)先思考再出答案,预算须覆盖"思考+输出";原 896/1024 偏紧→截断风险。
def gen_pass1(client, system: str, user: str) -> dict:
    # scores 是 plan() 唯一以 [] 取的键,缺了必然 KeyError;themes 走 .get 有默认值,不强求。
    return _complete_json(client, system, user, max_tokens=2048, required_keys=("scores",))

def gen_pass2(client, system: str, user: str) -> dict:
    # 影响分析缺失会让 business_view 写出一份空影响,过不了 program_gate 也没有价值。
    return _complete_json(client, system, user, max_tokens=3072, required_keys=("影响分析",))
