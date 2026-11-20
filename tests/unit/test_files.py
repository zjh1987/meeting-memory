import io

import pytest

from app.storage import files


def test_sanitize_title():
    assert files.sanitize_title('  三季/度:进度会?  ') == "三季-度-进度会-"
    assert files.sanitize_title("") == "未命名会议"
    assert len(files.sanitize_title("长" * 200)) == 80


def test_save_stream_writes_complete_file_and_meta(cfg):
    data = b"fake-audio-bytes"
    path, size, digest = files.save_stream(
        io.BytesIO(data), cfg.inbox_dir, "20261121-100000-abcd",
        "测试会", ".m4a", {"project": "项目A"},
    )
    assert path.name == "20261121-100000-abcd__测试会.m4a"
    assert path.read_bytes() == data
    assert size == len(data)
    assert len(digest) == 64
    assert not list(cfg.inbox_dir.glob("*.part"))
    meta = cfg.inbox_dir / "20261121-100000-abcd__测试会.json"
    assert '"项目A"' in meta.read_text(encoding="utf-8")


def test_save_stream_rejects_oversize(cfg):
    with pytest.raises(ValueError):
        files.save_stream(
            io.BytesIO(b"x" * 100), cfg.inbox_dir, "u", "t", ".m4a",
            {"project": "项目A"}, max_bytes=10,
        )
    assert not list(cfg.inbox_dir.iterdir())


def test_split_stem():
    assert files.split_stem("20261121-100000-abcd__测试会") == (
        "20261121-100000-abcd", "测试会")
    assert files.split_stem("plain") == ("plain", "plain")


def test_move_to_ready(cfg):
    src = cfg.inbox_dir / "a.m4a"
    src.write_bytes(b"x")
    dest = files.move_to_ready(src, cfg.ready_dir)
    assert dest.exists() and not src.exists()
