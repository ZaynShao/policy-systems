"""推理模型的 token 预算。

`deepseek-v4-pro` 是**推理模型**。max_tokens 不够时它不是把正文截断,而是
推理把预算吃光、**正文返回空串**(`finish_reason: length`)。而
`OpenAICompatClient.complete()` 只取 `content` 不看 `finish_reason`,
于是「预算不够」和「模型没话说」在代码里长得一模一样——整条链会安静地降级成
一份近乎空白的月刊,同时把几十万 token 花完。

2026-09-08 在生产端点拿 **5 篇真 vault 政策**实测(判定任务,与 MA2 同形):

    推理 token  min 1291 / 中位 1558 / max 2564
    正文        约 50 token(100 字上下)

所以判定这种「输出极短」的步骤照样要给到 4000 上下——**预算是给推理留的,
不是给正文留的**。写作类步骤正文本身就长,再叠推理,给得更宽。

样本只有 5 个,故各档都留了大约一倍余量;真跑后按 `llm_calls.jsonl` 校准。
"""

# 判定 / 短 JSON:正文极短,预算基本全给推理
JUDGE = 4000
SHORT_JSON = 4000

# 选目:输入 12–19K,输出是一整份 JSON,再叠推理
SLATE = 8000

# 写作:正文本身 600–1500 token,再叠推理
WRITE = 6000
SECTION = 6000

# 返修:一段文字,但要读懂审计意见
REPAIR = 5000


def escalate(max_tokens, attempt):
    """第 n 次重试把预算翻倍。

    原样重试一遍解决不了「预算被推理吃光」——失败往往正是预算不够,
    同样的预算再要一次只会再空一次。
    """
    return max_tokens * (2 ** attempt)
