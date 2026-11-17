"""交付脚本保留旧静态依赖，失败时不破坏候选或正在服务的旧目录。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/retain_frontend_assets.py"


def build(path, files):
    (path / "assets").mkdir(parents=True)
    (path / "index.html").write_text("<html>当前入口</html>")
    for name, contents in files.items():
        (path / "assets" / name).parent.mkdir(parents=True, exist_ok=True)
        (path / "assets" / name).write_text(contents)
    return path


def run(old, new, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--previous", str(old), "--candidate", str(new), *args],
        capture_output=True,
        text=True,
        umask=0o077,
    )


def test_preserve_old_hashes_without_replacing_new_entry_and_repeat_is_idempotent(tmp_path):
    old = build(tmp_path / "old", {"chunks/old-abcdefgh.js": "旧分包", "same-abcdefgh.css": "样式"})
    new = build(tmp_path / "new", {"new-abcdefgh.js": "新入口", "same-abcdefgh.css": "样式"})
    response = run(old, new)
    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout)["copied"] == 1
    assert (new / "assets/chunks/old-abcdefgh.js").read_text() == "旧分包"
    assert (new / "assets/chunks").stat().st_mode & 0o777 == 0o755
    assert (new / "assets/chunks/old-abcdefgh.js").stat().st_mode & 0o777 == 0o644
    assert (new / "assets/new-abcdefgh.js").read_text() == "新入口"
    assert (new / "index.html").read_text() == "<html>当前入口</html>"
    assert json.loads(run(old, new).stdout)["copied"] == 0


@pytest.mark.parametrize("reason", ["collision", "bytes", "files", "symlink"])
def test_failure_is_explicit_before_copying_any_old_files(tmp_path, reason):
    old = build(tmp_path / "old", {"old-abcdefgh.js": "旧分包", "same-abcdefgh.css": "样式"})
    new = build(tmp_path / "new", {"new-abcdefgh.js": "新入口", "same-abcdefgh.css": "样式"})
    args = []
    if reason == "collision":
        (new / "assets/same-abcdefgh.css").write_text("同名但内容不同")
    elif reason == "bytes":
        args = ["--max-bytes", "1"]
    elif reason == "files":
        args = ["--max-files", "1"]
    else:
        (old / "assets/link.js").symlink_to(old / "assets/old-abcdefgh.js")
    response = run(old, new, *args)
    assert response.returncode != 0 and "资源保留失败" in response.stderr
    assert not (new / "assets/old-abcdefgh.js").exists()
    assert (old / "assets/old-abcdefgh.js").read_text() == "旧分包"
