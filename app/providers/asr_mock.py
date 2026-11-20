from pathlib import Path

SCRIPT = [
    ("王总", "今天主要过一下三季度的进度，顺便把年底前要落的几件事定下来。"),
    ("李工", "系统这边三季度的功能都上完了，还有一个数据同步的问题没有解决。"),
    ("王总", "数据同步卡在哪里了？"),
    ("李工", "对方接口不稳定，高峰期会丢数据。"),
    ("张敏", "这个问题我们提过两次了，对方一直没给排期。"),
    ("王总", "这个不能再拖了，决定月底前走一次高层协调，张敏负责对接。"),
    ("张敏", "好的，我下周先把问题清单整理出来。"),
    ("李工", "另外测试环境下周可以交付，需要提前申请资源。"),
    ("王总", "资源的事让运维配合，李工负责提申请。"),
    ("张敏", "座谈这块的预算还没定，要看四季度有没有调整。"),
    ("王总", "预算先待定，回头再看。"),
    ("李工", "还有一个想法，能不能把会议记录自动归档，省得每次翻聊天记录。"),
    ("王总", "这个可以研究一下，先做个原型看看效果。"),
]


class MockAsr:
    def transcribe(self, audio_path: Path) -> list[dict]:
        segments = []
        cursor = 0.0
        for speaker, text in SCRIPT:
            duration = max(3.0, len(text) * 0.28)
            segments.append({
                "idx": len(segments),
                "start": round(cursor, 1),
                "end": round(cursor + duration, 1),
                "speaker": speaker,
                "text": text,
            })
            cursor += duration + 0.8
        return segments
