"""采集接口及明确标识的文件回放。外部采集器负责快照一致性与完整提交事务组装。"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from relationship_query.update.models import SourceSnapshot, SourceTransaction, UpdateError


class ChangeSource(Protocol):
    def transactions(self) -> Iterator[SourceTransaction]: ...

    def acknowledge(self, transaction: SourceTransaction) -> None: ...


class ReplaySource:
    def __init__(self, path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> None:
        self.path, self.max_bytes = path, max_bytes

    def transactions(self) -> Iterator[SourceTransaction]:
        with self.path.open("rb") as file:
            while line := file.readline(self.max_bytes + 1):
                if len(line) > self.max_bytes:
                    raise UpdateError("TRANSACTION_LIMIT", "完整事务输入超过字节预算")
                if not line.strip():
                    continue
                yield SourceTransaction.model_validate_json(line)

    def acknowledge(self, transaction: SourceTransaction) -> None:
        # 文件回放没有服务器确认；真实采集适配器在此实现传输层确认。
        pass


def read_snapshot(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> SourceSnapshot:
    with path.open("rb") as file:
        payload = file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise UpdateError("SNAPSHOT_LIMIT", "全量回放文件超过本次输入预算")
    return SourceSnapshot.model_validate_json(payload)
