"""L3 月刊产线的数据结构。

只放跨步骤传递的结构;单步内部的中间形态不进这里。
"""
from dataclasses import dataclass


@dataclass
class Candidate:
    """MA0 收上来的一条候选政策。

    `date` 与 `official_number` 取自 frontmatter,**均不可信**——只用于取窗与去重
    这类粗活;真实发文日与发文机关由 MA2 按 RAW 落款判定。
    """
    policy_id: str
    title: str
    official_number: str
    date: str
    date_missing: bool
    raw_path: str
    body_len: int
    region_name: str
    near_dup_group: str = ""   # MA1 软标记:疑似同一份文件的多次采集
    dup_of: str = ""           # MA1 硬合并:被哪个 policy_id 取代
    drop_reason: str = ""      # noise / dup
    docno_conflict: bool = False  # 与别人共用文号但内容不相干 → 至少一方文号是错抓的
    id_collision: bool = False    # 同一 policy_id 挂了不同文件 → slate 必须给 title_hint
    series_group: str = ""        # 周期性系列(如各省成品油调价),同系列整体算一条
    series_size: int = 0
