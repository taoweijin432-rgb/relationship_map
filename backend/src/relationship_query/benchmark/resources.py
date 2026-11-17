"""Unix进程内核内存及独占产物目录测量，文件大小不作为RSS估计。"""

import os
import resource
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def peak_rss_bytes(value: int, platform: str) -> int:
    if platform == "darwin":
        return value
    if platform.startswith("linux"):
        return value * 1024
    raise ValueError("内存测量仅支持当前项目的Linux和macOS环境")


def current_rss_bytes() -> int:
    if sys.platform.startswith("linux"):
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    if sys.platform == "darwin":
        result = subprocess.check_output(
            ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        return int(result.strip()) * 1024
    raise ValueError("当前RSS测量不支持此平台")


def process_usage() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result: dict[str, Any] = {
        "pid": os.getpid(),
        "peak_rss_bytes": peak_rss_bytes(usage.ru_maxrss, sys.platform),
        "user_cpu_seconds": usage.ru_utime,
        "system_cpu_seconds": usage.ru_stime,
        "major_page_faults": usage.ru_majflt,
    }
    try:
        result["current_rss_bytes"] = current_rss_bytes()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(current_rss_bytes=None, current_rss_error=type(error).__name__)
    return result


@dataclass
class DirectoryUsage:
    regular_file_count: int = 0
    logical_bytes: int = 0
    unique_file_allocated_bytes: int = 0
    skipped_links: int = 0


def directory_usage(directory: Path) -> dict[str, int]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("测量需要真实产物目录，不跟随符号链接")
    usage, seen = DirectoryUsage(), set()
    for current, directories, files in os.walk(directory, followlinks=False):
        usage.skipped_links += sum((Path(current) / name).is_symlink() for name in directories)
        for name in files:
            info = (Path(current) / name).lstat()
            if stat.S_ISLNK(info.st_mode):
                usage.skipped_links += 1
            elif stat.S_ISREG(info.st_mode):
                usage.regular_file_count += 1
                usage.logical_bytes += info.st_size
                identity = info.st_dev, info.st_ino
                if identity not in seen:
                    seen.add(identity)
                    usage.unique_file_allocated_bytes += info.st_blocks * 512
    return asdict(usage)
