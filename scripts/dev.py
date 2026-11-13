"""启动及回收本次创建的子进程，不终止其他占用端口的服务。"""

import errno
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from relationship_query.settings import database_path, default_numeric_store

ROOT = Path(__file__).resolve().parents[1]


def assert_port_available(port: int) -> None:
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                raise RuntimeError(f"端口 {port} 已被占用，请先停止该服务后再启动。") from exc
            raise RuntimeError(f"无法监听本地端口 {port}：{exc}") from exc


def wait_ready(url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"子进程已退出，无法启动 {url}，请查看上方日志。")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"启动超时：{url}")


def main() -> int:
    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    children: list[subprocess.Popen] = []
    try:
        api_port = int(os.environ.get("RELATIONSHIP_API_PORT", "8000"))
        web_port = int(os.environ.get("RELATIONSHIP_WEB_PORT", "5173"))
        for port in (api_port, web_port):
            assert_port_available(port)
        if (
            not os.environ.get("RELATIONSHIP_SOURCE_API_MANIFEST")
            and not os.environ.get("RELATIONSHIP_SOURCE_RELEASE_STORE")
            and not os.environ.get("RELATIONSHIP_MYSQL_URL")
            and not os.environ.get("RELATIONSHIP_NUMERIC_RELEASE_STORE")
            and (os.environ.get("RELATIONSHIP_DATABASE") or default_numeric_store() is None)
            and not database_path().is_file()
        ):
            subprocess.run(
                [sys.executable, "-m", "relationship_query.cli", "init"],
                cwd=ROOT / "backend",
                check=True,
            )
        commands = [
            (
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "relationship_query.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--reload",
                    "--reload-dir",
                    str(ROOT / "backend" / "src"),
                ],
                ROOT / "backend",
                f"http://127.0.0.1:{api_port}/api/v1/health",
            ),
            (["npm", "run", "dev"], ROOT / "frontend", f"http://127.0.0.1:{web_port}"),
        ]
        for command, directory, url in commands:
            child = subprocess.Popen(command, cwd=directory, start_new_session=True)
            children.append(child)
            wait_ready(url, child)
        print(
            f"\n人物关系原型：http://127.0.0.1:{web_port}\nAPI 文档：http://127.0.0.1:{api_port}/docs\n"
            "本机验证环境。按 Ctrl+C 停止本次启动的全部进程。\n",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("服务意外退出，正在停止本次启动的其他服务。")
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
