from pathlib import Path
from typing import Protocol


class AsrProvider(Protocol):
    def transcribe(self, audio_path: Path) -> list[dict]: ...


class LlmProvider(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...
