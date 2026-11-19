from pathlib import Path
import yaml

def write_business_view(draft, vault: str, sanitized_from: str, extracted_at: str,
                        extracted_model: str, extracted_strategy: str | None = None) -> str:
    """整文件重生 {vault}/_meta/business_view/{pid}.yaml。§C 安全:只写派生层。"""
    out_dir = Path(vault) / "_meta" / "business_view"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{draft.pid}.yaml"
    assert "0_raw" not in str(out_path), "§C 违反:business_view 不得落 0_raw"

    doc = {
        "pid": draft.pid,
        "themes": list(draft.themes or []),
        "primary_theme": draft.primary_theme,
        "comprehensive": bool(draft.comprehensive),
        "scores": draft.scores.to_dict(),
        "重要性": draft.importance,
        "行动分类": draft.action_class,
        "价值标签": list(draft.value_tags or []),
    }
    if draft.gate_passed_deep:
        doc["影响分析"] = draft.影响分析
        doc["行动建议"] = list(draft.行动建议 or [])
        if draft.didi_impact_one_liner:
            doc["didi_impact_one_liner"] = draft.didi_impact_one_liner
    doc["sanitized_from"] = sanitized_from
    doc["extracted_at"] = extracted_at
    doc["extracted_by"] = "scripts/l2_themescore/run_2b.py"
    doc["extracted_model"] = extracted_model
    # 用的是哪版业务战略画像。**必须记**:战略是可替换的,不记这个字段,
    # 等战略换过一轮之后就再也分不清哪些影响分析是按哪版口径写的。
    # 同类教训:全库 1546 篇是两个模型分两批打的,幸亏 extracted_model 记了,
    # 否则连"分不可比"这件事都发现不了。
    if extracted_strategy:
        doc["extracted_strategy"] = extracted_strategy
    doc["gate_passed_deep"] = bool(draft.gate_passed_deep)
    if draft.importance is not None and draft.importance < 3:
        doc["archive"] = "low_score"

    out_path.write_text(yaml.dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(out_path)
