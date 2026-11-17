"""在切换静态目录前保留旧页面依赖；碰撞或体积超限时拒绝交付候选。"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def asset_files(directory: Path) -> dict[str, Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("assets必须为真实目录")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("assets不接受符号链接")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = path
    return result


def digest(path: Path) -> bytes:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(128 * 1024):
            value.update(chunk)
    return value.digest()


def retain(previous: Path, candidate: Path, max_bytes: int, max_files: int) -> dict[str, int]:
    previous, candidate = previous.resolve(), candidate.resolve()
    if previous == candidate or previous in candidate.parents or candidate in previous.parents:
        raise ValueError("新旧构建目录必须独立且不能互相包含")
    if not all(
        (directory / "index.html").is_file() and not (directory / "index.html").is_symlink()
        for directory in (previous, candidate)
    ):
        raise ValueError("新旧构建目录均需具有index.html")
    old, new = asset_files(previous / "assets"), asset_files(candidate / "assets")
    for name in old.keys() & new.keys():
        if digest(old[name]) != digest(new[name]):
            raise ValueError(f"同名资源内容不同，拒绝覆盖：{name}")
    combined = old | new
    total = sum(path.stat().st_size for path in combined.values())
    if len(combined) > max_files or total > max_bytes:
        raise ValueError("旧资源合并超过文件数或体积上限，请先评估历史构建保留范围")
    missing = old.keys() - new.keys()
    for name in sorted(missing):
        target = candidate / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old[name], target)
        target.chmod(0o644)
    # 构建可在严格umask下运行；仅调整候选公开产物，避免Nginx读取旧分包时403。
    for directory in [
        candidate,
        candidate / "assets",
        *(path for path in (candidate / "assets").rglob("*") if path.is_dir()),
    ]:
        directory.chmod(0o755)
    for path in asset_files(candidate / "assets").values():
        path.chmod(0o644)
    (candidate / "index.html").chmod(0o644)
    return {"copied": len(missing), "assets_total": len(combined), "total_bytes": total}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--max-files", type=int, default=10000)
    args = parser.parse_args()
    try:
        if args.max_bytes <= 0 or args.max_files <= 0:
            raise ValueError("资源上限必须为正数")
        print(json.dumps(retain(args.previous, args.candidate, args.max_bytes, args.max_files)))
    except (ValueError, OSError) as error:
        parser.exit(1, f"资源保留失败：{error}\n")


if __name__ == "__main__":
    main()
