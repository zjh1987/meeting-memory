import re

LINE = re.compile(r"^\[#(\d+)\] \d{2}:\d{2}:\d{2} (\S+) (.+)$", re.M)
DECISION = ("决定", "定了", "结论", "拍板", "确定")
ACTION = ("负责", "跟进", "下周", "月底", "之前", "提交", "整理", "对接", "配合", "推进")
OPEN = ("待定", "再看看", "没定", "回头", "再说", "看情况")


class MockLlm:
    def complete_json(self, system: str, user: str) -> dict:
        segments = [
            {"idx": int(m.group(1)), "speaker": m.group(2), "text": m.group(3).strip()}
            for m in LINE.finditer(user)
        ]
        if not segments:
            return {"title": "无有效内容", "summary": "无有效内容。",
                    "topics": [{"title": "无内容", "points": [], "segment_ids": []}],
                    "decisions": [], "actions": [], "open_issues": [], "people": []}

        topics = []
        for start in range(0, len(segments), 4):
            group = segments[start:start + 4]
            topics.append({
                "title": (group[0]["text"][:14] or "议题") + "…",
                "points": [s["text"] for s in group],
                "segment_ids": [s["idx"] for s in group],
            })

        def hits(keywords):
            return [s for s in segments if any(k in s["text"] for k in keywords)]

        decisions = [{"text": s["text"], "quote": s["text"],
                      "segment_ids": [s["idx"]]} for s in hits(DECISION)]
        actions = [{"owner": "待指定", "task": s["text"], "due": "",
                    "quote": s["text"], "segment_ids": [s["idx"]]}
                   for s in hits(ACTION)]
        open_issues = [{"text": s["text"], "reason": "未形成结论", "quote": s["text"],
                        "segment_ids": [s["idx"]]} for s in hits(OPEN)]
        people = [{"name": name, "role": "参会人"}
                  for name in sorted({s["speaker"] for s in segments})]
        summary = "本次会议共 " + str(len(segments)) + " 段发言，讨论了" + \
                  "、".join(t["title"] for t in topics[:3])
        return {"title": topics[0]["title"][:20], "summary": summary,
                "topics": topics, "decisions": decisions,
                "actions": actions, "open_issues": open_issues, "people": people}
