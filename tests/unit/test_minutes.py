import pytest

from app.pipeline import minutes


def _segments():
    return [
        {"idx": 0, "start": 0, "end": 4, "speaker": "王总",
         "text": "今天过一下进度。"},
        {"idx": 1, "start": 4, "end": 8, "speaker": "李工",
         "text": "数据同步还没解决。"},
        {"idx": 2, "start": 8, "end": 12, "speaker": "张敏",
         "text": "我下周把问题清单整理出来。"},
        {"idx": 3, "start": 12, "end": 16, "speaker": "王总",
         "text": "预算待定，回头再看。"},
    ]


def test_validate_rejects_missing_quote():
    data = {
        "summary": "会议。", "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
        "decisions": [{"text": "决定", "quote": "", "segment_ids": [0]}],
        "actions": [], "open_issues": [], "people": [],
    }
    with pytest.raises(minutes.MinutesValidationError):
        minutes.validate_minutes(data, 4)


def test_validate_rejects_out_of_range_and_normalizes_owner():
    data = {
        "summary": "会议。", "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
        "decisions": [],
        "actions": [{"owner": "", "task": "整理清单", "due": "",
                     "quote": "我下周把问题清单整理出来", "segment_ids": [2]}],
        "open_issues": [], "people": [],
    }
    result = minutes.validate_minutes(data, 4)
    assert result["actions"][0]["owner"] == "待指定"

    data["actions"][0]["segment_ids"] = [99]
    with pytest.raises(minutes.MinutesValidationError):
        minutes.validate_minutes(data, 4)


def test_title_is_derived_and_limited():
    data = {
        "summary": "本次会议围绕数据同步方案进行了讨论，并确认下周完成联调与验收。",
        "topics": [{"title": "数据同步", "points": [], "segment_ids": [0]}],
        "decisions": [], "actions": [], "open_issues": [], "people": [],
    }
    result = minutes.validate_minutes(data, 4)
    assert result["title"]
    assert len(result["title"]) <= minutes.TITLE_MAX

    data["title"] = "《预算讨论会》"
    assert minutes.validate_minutes(data, 4)["title"] == "预算讨论会"

    data["title"] = "预算" * 30
    cleaned = minutes.validate_minutes(data, 4)["title"]
    assert len(cleaned) == minutes.TITLE_MAX


def test_generate_with_mock_returns_valid_minutes(cfg):
    result = minutes.generate(cfg, _segments(), "standard")
    assert result["summary"]
    assert result["topics"]
    assert any(a["segment_ids"] == [2] for a in result["actions"])


def test_chunk_segments_covers_all_with_overlap():
    segments = [{"idx": i, "start": i, "end": i + 1, "speaker": "说话人1",
                 "text": "字" * 100} for i in range(50)]
    chunks = minutes.chunk_segments(segments, max_chars=1000, overlap_chars=100)
    assert len(chunks) > 1
    covered = {s["idx"] for chunk in chunks for s in chunk}
    assert covered == {s["idx"] for s in segments}


def test_merge_parts_dedupes():
    part = {"summary": "A", "topics": [{"title": "t", "points": [], "segment_ids": [0]}],
            "decisions": [], "actions": [], "open_issues": [], "people": []}
    merged = minutes.merge_parts([part, part])
    assert len(merged["topics"]) == 1


def test_custom_sections_and_glossary_are_supported():
    data = {
        "summary": "会议。", "topics": [{"title": "进度", "points": [], "segment_ids": [0]}],
        "decisions": [], "actions": [], "open_issues": [], "people": [],
        "custom_sections": [{
            "key": "risks", "title": "风险与依赖",
            "items": [{"text": "数据同步依赖外部排期",
                       "quote": "数据同步还没解决", "segment_ids": [1]}],
        }],
    }
    result = minutes.validate_minutes(data, 4)
    assert result["custom_sections"][0]["title"] == "风险与依赖"

    data["custom_sections"][0]["items"][0]["segment_ids"] = [99]
    with pytest.raises(minutes.MinutesValidationError):
        minutes.validate_minutes(data, 4)

    prompt = minutes.build_user_prompt(
        _segments(), glossary=["张敏"], custom_sections=[
            {"key": "risks", "title": "风险与依赖",
             "instruction": "列出风险和依赖"}])
    assert "张敏" in prompt
    assert "风险与依赖" in prompt


def test_merge_parts_merges_custom_sections():
    item = {"text": "风险一", "quote": "", "segment_ids": []}
    part = {"summary": "A", "topics": [], "decisions": [], "actions": [],
            "open_issues": [], "people": [],
            "custom_sections": [{"key": "risks", "title": "风险与依赖",
                                 "items": [item]}]}
    merged = minutes.merge_parts([part, part])
    assert len(merged["custom_sections"]) == 1
    assert len(merged["custom_sections"][0]["items"]) == 1
