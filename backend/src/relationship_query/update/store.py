"""本地独立更新状态。每个来源世代使用一个私有目录，SQLite事务保护事件与位点。"""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

from relationship_query.update.contract import SourceContract
from relationship_query.update.models import (
    Row,
    SourceSnapshot,
    SourceTransaction,
    UpdateError,
    digest,
    encode,
)

APPLICATION_ID = 0x52515550
SCHEMA = """
CREATE TABLE rq_cdc_checkpoint (
 id INTEGER PRIMARY KEY CHECK(id=1), format_version INTEGER NOT NULL,
 contract_digest TEXT NOT NULL, generation TEXT NOT NULL,
 baseline_cursor TEXT NOT NULL, capture_cursor TEXT NOT NULL,
 captured_tx_seq INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error_code TEXT
);
CREATE TABLE rq_cdc_transaction (
 tx_seq INTEGER PRIMARY KEY, transaction_id TEXT NOT NULL UNIQUE,
 digest TEXT NOT NULL, previous_cursor TEXT NOT NULL, commit_cursor TEXT NOT NULL,
 event_count INTEGER NOT NULL, bytes INTEGER NOT NULL
);
CREATE TABLE rq_cdc_event (
 tx_seq INTEGER NOT NULL REFERENCES rq_cdc_transaction(tx_seq),
 event_index INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 PRIMARY KEY(tx_seq,event_index)
);
CREATE TABLE rq_source_row (
 logical_table TEXT NOT NULL, row_key TEXT NOT NULL,
 tx_seq INTEGER NOT NULL, payload TEXT,
 PRIMARY KEY(logical_table,row_key,tx_seq)
);
CREATE TABLE rq_projection_batch (
 batch_id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
 from_seq INTEGER NOT NULL, to_seq INTEGER NOT NULL, reference_month INTEGER NOT NULL,
 base_revision INTEGER NOT NULL, status TEXT NOT NULL,
 token INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL,
 artifact_dir TEXT, error_code TEXT
);
"""


class UpdateStore:
    def __init__(self, directory: Path, contract: SourceContract, *, create: bool = False) -> None:
        self.directory, self.contract = directory.resolve(), contract
        self.path = self.directory / "state.sqlite"
        if create:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.directory.stat().st_mode & 0o077:
                raise UpdateError("INVALID_STATE", "更新状态目录权限应为700")
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise UpdateError(
                    "STATE_EXISTS", "状态已存在，请使用原目录或为新基线指定新目录"
                ) from None
            os.close(fd)
            with closing(sqlite3.connect(self.path)) as connection:
                connection.executescript(f"PRAGMA application_id={APPLICATION_ID};" + SCHEMA)
        if not self.directory.is_dir() or self.directory.stat().st_mode & 0o077:
            raise UpdateError("INVALID_STATE", "更新状态目录权限应为700")
        if not self.path.is_file() or self.path.stat().st_mode & 0o077:
            raise UpdateError("INVALID_STATE", "需要已有的私有更新状态文件，权限应为600")
        with self.connection() as connection:
            self._checkpoint(connection, optional=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise UpdateError("INVALID_STATE", "该文件不属于独立更新程序")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _checkpoint(self, connection: sqlite3.Connection, *, optional: bool = False) -> Any:
        row = connection.execute("SELECT * FROM rq_cdc_checkpoint WHERE id=1").fetchone()
        if row is None:
            if optional:
                return None
            raise UpdateError("BASELINE_REQUIRED", "请先导入完整基线")
        if row["contract_digest"] != self.contract.fingerprint:
            raise UpdateError("CONTRACT_CHANGED", "来源契约已变，请核对映射并在新目录建立新基线")
        if row["format_version"] != 1:
            raise UpdateError("STATE_VERSION", "本地状态版本需要显式迁移")
        return row

    def bootstrap(self, snapshot: SourceSnapshot, rows: dict[str, list[Row]]) -> None:
        with self.connection() as connection:
            if self._checkpoint(connection, optional=True) is not None:
                raise UpdateError("BASELINE_EXISTS", "已存在基线，拒绝覆盖")
            connection.execute(
                "INSERT INTO rq_cdc_checkpoint VALUES (1,1,?,?,?,?,0,'streaming',NULL)",
                (
                    self.contract.fingerprint,
                    snapshot.generation,
                    encode(snapshot.cursor.model_dump()),
                    encode(snapshot.cursor.model_dump()),
                ),
            )
            for logical, records in rows.items():
                binding = self.contract.tables[logical]
                for row in records:
                    try:
                        connection.execute(
                            "INSERT INTO rq_source_row VALUES (?,?,0,?)",
                            (logical, binding.row_key(row), encode(row)),
                        )
                    except sqlite3.IntegrityError:
                        raise UpdateError("DUPLICATE_KEY", "全量来源存在重复主键") from None

    def capture(self, transaction: SourceTransaction) -> bool:
        """返回False表示精确重放，位点与事件不会重复推进。"""
        payload = transaction.model_dump(mode="json")
        with self.connection() as connection:
            checkpoint = self._checkpoint(connection)
            if transaction.generation != checkpoint["generation"]:
                raise UpdateError("GENERATION_CHANGED", "事务与本次全量基线不属于同一来源世代")
            if checkpoint["status"] != "streaming":
                raise UpdateError("CAPTURE_PAUSED", "采集已暂停，请检查契约并建立新基线")
            prior = connection.execute(
                "SELECT digest FROM rq_cdc_transaction WHERE transaction_id=?",
                (transaction.transaction_id,),
            ).fetchone()
            if prior is not None:
                if prior["digest"] != digest(payload):
                    raise UpdateError("REPLAY_CONFLICT", "相同事务编号收到不同内容")
                return False
            if encode(transaction.previous.model_dump()) != checkpoint["capture_cursor"]:
                raise UpdateError("CURSOR_GAP", "事务未衔接已持久化位点")
            sequence = checkpoint["captured_tx_seq"] + 1
            connection.execute(
                "INSERT INTO rq_cdc_transaction VALUES (?,?,?,?,?,?,?)",
                (
                    sequence,
                    transaction.transaction_id,
                    digest(payload),
                    encode(transaction.previous.model_dump()),
                    encode(transaction.cursor.model_dump()),
                    transaction.event_count,
                    len(encode(payload).encode()),
                ),
            )
            for index, event in enumerate(transaction.events):
                if event.operation == "ddl":
                    raise UpdateError("SCHEMA_CHANGE", "检测到DDL，需核对契约并建立新基线")
                try:
                    connection.execute(
                        "INSERT INTO rq_cdc_event VALUES (?,?,?,?)",
                        (
                            sequence,
                            index,
                            event.event_id,
                            encode(event.model_dump(mode="json")),
                        ),
                    )
                except sqlite3.IntegrityError:
                    raise UpdateError("EVENT_CONFLICT", "事件编号已被其他事务使用") from None
                logical = self.contract.logical_table(event.table)
                if logical is None:
                    raise UpdateError("UNEXPECTED_TABLE", "采集事件表未在来源契约中配置")
                before = (
                    self.contract.tables[logical].normalize(event.before)
                    if event.before is not None
                    else None
                )
                after = (
                    self.contract.tables[logical].normalize(event.after)
                    if event.after is not None
                    else None
                )
                self._apply(connection, logical, sequence, before, after)
            connection.execute(
                "UPDATE rq_cdc_checkpoint SET capture_cursor=?,captured_tx_seq=? WHERE id=1",
                (encode(transaction.cursor.model_dump()), sequence),
            )
        return True

    def _apply(
        self,
        connection: sqlite3.Connection,
        logical: str,
        sequence: int,
        before: Row | None,
        after: Row | None,
    ) -> None:
        binding = self.contract.tables[logical]
        old_key = binding.row_key(before) if before is not None else None
        new_key = binding.row_key(after) if after is not None else None

        def current(key: str) -> str | None:
            row = connection.execute(
                "SELECT payload FROM rq_source_row WHERE logical_table=? AND row_key=? "
                "ORDER BY tx_seq DESC LIMIT 1",
                (logical, key),
            ).fetchone()
            return row[0] if row is not None else None

        if old_key is not None and current(old_key) != encode(before):
            raise UpdateError("BEFORE_IMAGE_MISMATCH", "事件旧值与当前来源状态不符")
        if new_key is not None and new_key != old_key and current(new_key) is not None:
            raise UpdateError("DUPLICATE_KEY", "新增来源主键已存在")
        changes = {
            key: value for key, value in ((old_key, None), (new_key, after)) if key is not None
        }
        for key, value in changes.items():
            connection.execute(
                "INSERT INTO rq_source_row VALUES (?,?,?,?) "
                "ON CONFLICT(logical_table,row_key,tx_seq) "
                "DO UPDATE SET payload=excluded.payload",
                (logical, key, sequence, encode(value) if value is not None else None),
            )

    def pause(self, code: str) -> None:
        with self.connection() as connection:
            self._checkpoint(connection)
            connection.execute("UPDATE rq_cdc_checkpoint SET status='paused',error_code=?", (code,))

    def status(self) -> dict[str, Any]:
        with self.connection() as connection:
            checkpoint = dict(self._checkpoint(connection))
            checkpoint.pop("contract_digest")
            checkpoint["baseline_cursor"] = json.loads(checkpoint["baseline_cursor"])
            checkpoint["capture_cursor"] = json.loads(checkpoint["capture_cursor"])
            checkpoint["batches"] = [
                dict(row)
                for row in connection.execute(
                    "SELECT batch_id,from_seq,to_seq,status,token,error_code "
                    "FROM rq_projection_batch"
                )
            ]
            return checkpoint

    def rows_at(self, sequence: int, *, max_rows: int) -> dict[str, list[Row]]:
        with self.connection() as connection:
            checkpoint = self._checkpoint(connection)
            if sequence < 0 or sequence > checkpoint["captured_tx_seq"]:
                raise UpdateError("INVALID_RANGE", "来源截止点超出持久化范围")
            rows: dict[str, list[Row]] = {name: [] for name in self.contract.tables}
            records = connection.execute(
                "SELECT r.logical_table,r.payload FROM rq_source_row r JOIN "
                "(SELECT logical_table,row_key,MAX(tx_seq) AS latest FROM rq_source_row "
                "WHERE tx_seq<=? GROUP BY logical_table,row_key) v "
                "ON r.logical_table=v.logical_table AND r.row_key=v.row_key AND r.tx_seq=v.latest "
                "WHERE r.payload IS NOT NULL ORDER BY r.logical_table,r.row_key LIMIT ?",
                (sequence, max_rows + 1),
            ).fetchall()
            if len(records) > max_rows:
                raise UpdateError("ROW_LIMIT", "来源快照达到本次构建行数预算")
            for record in records:
                rows[record["logical_table"]].append(json.loads(record["payload"]))
            return rows

    def claim(
        self,
        revision: int,
        start: int,
        month: int,
        owner: str,
        max_transactions: int,
        lease_seconds: float = 300,
        allow_empty: bool = False,
    ) -> dict[str, Any] | None:
        with self.connection() as connection:
            checkpoint = self._checkpoint(connection)
            if checkpoint["status"] != "streaming":
                raise UpdateError("CAPTURE_PAUSED", "采集已暂停，候选发布被阻断")
            end = min(start + max_transactions, checkpoint["captured_tx_seq"])
            pending = connection.execute(
                "SELECT * FROM rq_projection_batch WHERE base_revision=? AND from_seq=? "
                "AND reference_month=? "
                "AND status IN ('queued','building','verifying','ready','failed','planned') "
                "ORDER BY rowid LIMIT 1",
                (revision, start, month),
            ).fetchone()
            if pending is not None and pending["status"] == "failed" and end > pending["to_seq"]:
                # 后续事务可能纠正中间状态，允许在同一已发布基线上合并更完整范围。
                connection.execute(
                    "UPDATE rq_projection_batch SET status='cancelled' WHERE batch_id=?",
                    (pending["batch_id"],),
                )
                pending = None
            if pending is None:
                if start == end and revision > 0 and not allow_empty:
                    return None
                batch_id = uuid4().hex
                request = digest([self.contract.fingerprint, revision, start, end, month])
                connection.execute(
                    "INSERT INTO rq_projection_batch(batch_id,request_key,from_seq,to_seq,"
                    "reference_month,"
                    "base_revision,status) VALUES (?,?,?,?,?,?,'queued')",
                    (batch_id, request, start, end, month, revision),
                )
            else:
                batch_id = pending["batch_id"]
                if pending["to_seq"] - pending["from_seq"] > max_transactions:
                    raise UpdateError("BATCH_RANGE_LIMIT", "已有候选范围超出本次微批预算")
                if pending["lease_until"] is not None and pending["lease_until"] > time():
                    raise UpdateError("WORKER_BUSY", "已有Worker持有该批次")
            connection.execute(
                "UPDATE rq_projection_batch SET status='building',token=token+1,owner=?,"
                "lease_until=?,artifact_dir=NULL,error_code=NULL WHERE batch_id=?",
                (owner, time() + lease_seconds, batch_id),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM rq_projection_batch WHERE batch_id=?",
                    (batch_id,),
                ).fetchone()
            )

    def assert_claim(self, connection: sqlite3.Connection, batch: dict[str, Any]) -> None:
        self._checkpoint(connection)
        current = connection.execute(
            "SELECT * FROM rq_projection_batch WHERE batch_id=?", (batch["batch_id"],)
        ).fetchone()
        if (
            current is None
            or current["token"] != batch["token"]
            or current["owner"] != batch["owner"]
            or current["lease_until"] is None
            or current["lease_until"] <= time()
        ):
            raise UpdateError("LEASE_LOST", "批次租约已失效")

    def finish(
        self,
        batch: dict[str, Any],
        status: str,
        artifact: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection() as connection:
            self.assert_claim(connection, batch)
            connection.execute(
                "UPDATE rq_projection_batch SET status=?,artifact_dir=?,error_code=?,"
                "lease_until=NULL "
                "WHERE batch_id=?",
                (status, artifact, error, batch["batch_id"]),
            )

    def stage(self, batch: dict[str, Any], status: str, artifact: str | None = None) -> None:
        with self.connection() as connection:
            self.assert_claim(connection, batch)
            connection.execute(
                "UPDATE rq_projection_batch SET status=?,artifact_dir=? WHERE batch_id=?",
                (status, artifact, batch["batch_id"]),
            )

    def fail(self, batch: dict[str, Any], code: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE rq_projection_batch SET status='failed',error_code=?,lease_until=NULL "
                "WHERE batch_id=? AND token=? AND owner=? AND status<>'published'",
                (code, batch["batch_id"], batch["token"], batch["owner"]),
            )

    def reconcile(self, batch_id: str, token: int, artifact: str) -> None:
        """激活指针为事实依据，补记文件替换后、状态事务提交前的崩溃。"""
        with self.connection() as connection:
            checkpoint = self._checkpoint(connection)
            row = connection.execute(
                "SELECT * FROM rq_projection_batch WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if (
                row is None
                or row["token"] != token
                or row["to_seq"] > checkpoint["captured_tx_seq"]
            ):
                raise UpdateError("STATE_INTEGRITY", "激活指针与任务记录不一致")
            connection.execute(
                "UPDATE rq_projection_batch SET status='published',artifact_dir=?,"
                "lease_until=NULL,error_code=NULL WHERE batch_id=?",
                (artifact, batch_id),
            )
