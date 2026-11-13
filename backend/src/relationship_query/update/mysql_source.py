"""MySQL一致性初始化及有界binlog事务读取，适配独立更新核心。"""

import re
from collections.abc import Iterator
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import pymysql  # type: ignore[import-untyped]
from pymysqlreplication import BinLogStreamReader  # type: ignore[import-untyped]
from pymysqlreplication.event import (  # type: ignore[import-untyped]
    NotImplementedEvent,
    QueryEvent,
    RotateEvent,
    XAPrepareEvent,
    XidEvent,
)
from pymysqlreplication.row_event import (  # type: ignore[import-untyped]
    DeleteRowsEvent,
    PartialUpdateRowsEvent,
    UpdateRowsEvent,
    WriteRowsEvent,
)

from relationship_query.update.contract import SourceContract
from relationship_query.update.models import (
    Cursor,
    Row,
    RowChange,
    SourceSnapshot,
    SourceTransaction,
    UpdateError,
    digest,
    encode,
)


def json_row(values: dict[str, Any]) -> Row:
    """保留整数精度，数据库日期转协议文本，完整物理镜像由契约筛列。"""
    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, bytes):
            value = value.decode("utf-8", errors="strict")
        result[key] = value
    encode(result)
    return cast(Row, result)


class MySQLSource:
    """每次读取当前可用的完整事务，确认仅推进内存位置，持久位置由UpdateStore维护。"""

    def __init__(
        self,
        settings: dict[str, Any],
        contract: SourceContract,
        generation: str,
        *,
        cursor: Cursor | None = None,
        server_id: int = 183501,
        max_events: int = 10_000,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.settings, self.contract, self.generation = settings, contract, generation
        self.cursor, self.server_id = cursor, server_id
        self.max_events, self.max_bytes = max_events, max_bytes
        self.database = str(settings["database"])
        self.tables: dict[str, str] = {}
        for binding in contract.tables.values():
            parts = binding.physical.split(".")
            if (
                len(parts) != 2
                or parts[0] != self.database
                or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts)
            ):
                raise UpdateError("MYSQL_CONTRACT", "来源表须显式限定同一数据库及安全标识符")
            self.tables[parts[1]] = binding.physical
        if not 1 <= server_id < 2**32 or min(max_events, max_bytes) < 1:
            raise UpdateError("MYSQL_CONFIG", "复制客户端ID及事务预算不合法")

    def connect(self, settings: dict[str, Any] | None = None) -> Any:
        return pymysql.connect(
            **(settings or self.settings), cursorclass=pymysql.cursors.DictCursor, autocommit=True
        )

    def _identity(self, connection: Any) -> tuple[str, str]:
        with connection.cursor() as query:
            query.execute(
                "SELECT @@server_uuid AS uuid,@@log_bin AS enabled,"
                "@@binlog_format AS format,@@binlog_row_image AS image,"
                "@@binlog_row_metadata AS metadata,"
                "@@binlog_transaction_compression AS compression,"
                "@@binlog_row_value_options AS row_options"
            )
            server = query.fetchone()
            if not server["enabled"] or (server["format"], server["image"], server["metadata"]) != (
                "ROW",
                "FULL",
                "FULL",
            ):
                raise UpdateError("MYSQL_BINLOG_CONFIG", "需要ROW、完整行镜像与完整列元数据")
            if server["compression"] or server["row_options"]:
                raise UpdateError("MYSQL_BINLOG_CONFIG", "当前适配器要求完整非压缩行事件")
            query.execute(
                "SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,ORDINAL_POSITION "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s "
                "ORDER BY TABLE_NAME,ORDINAL_POSITION",
                (self.database,),
            )
            columns = [row for row in query.fetchall() if row["TABLE_NAME"] in self.tables]
        if {row["TABLE_NAME"] for row in columns} != set(self.tables):
            raise UpdateError("SCHEMA_MISMATCH", "来源缺少已配置的物理表")
        return f"mysql:{server['uuid']}:{self.database}", digest(columns)

    @staticmethod
    def _position(connection: Any) -> dict[str, Any]:
        with connection.cursor() as query:
            try:
                query.execute("SHOW BINARY LOG STATUS")
            except pymysql.err.ProgrammingError as error:
                if error.args[0] != 1064:
                    raise
                query.execute("SHOW MASTER STATUS")
            status = query.fetchone()
        if status is None:
            raise UpdateError("MYSQL_BINLOG_CONFIG", "来源没有可用日志位点")
        return {"file": status["File"], "pos": status["Position"]}

    def snapshot(self, lock_settings: dict[str, Any], *, max_rows: int = 10_000) -> SourceSnapshot:
        """协调连接持有短全局读锁，只读连接建立RR视图后立即释放，随后读取存量。"""
        with closing(self.connect(lock_settings)) as coordinator, closing(self.connect()) as reader:
            with coordinator.cursor() as lock, reader.cursor() as query:
                lock.execute("FLUSH TABLES WITH READ LOCK")
                try:
                    source, schema = self._identity(reader)
                    query.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    query.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    position = self._position(coordinator)
                finally:
                    lock.execute("UNLOCK TABLES")
                try:
                    tables = self._snapshot_rows(query, max_rows)
                    if self._identity(coordinator) != (source, schema):
                        raise UpdateError("SCHEMA_MISMATCH", "全量读取期间结构发生变化")
                finally:
                    reader.rollback()
        self.cursor = Cursor(source=source, position={**position, "schema": schema})
        return SourceSnapshot(generation=self.generation, cursor=self.cursor, tables=tables)

    def _snapshot_rows(self, query: Any, limit: int) -> dict[str, list[Row]]:
        result: dict[str, list[Row]] = {}
        count = 0
        for table, physical in self.tables.items():
            query.execute(f"SELECT * FROM `{self.database}`.`{table}` LIMIT %s", (limit + 1,))
            rows = [json_row(row) for row in query.fetchall()]
            count += len(rows)
            if count > limit:
                raise UpdateError("ROW_LIMIT", "来源一致性全量超过本次行数预算")
            result[physical] = rows
        return result

    def _check_resume(self) -> None:
        if self.cursor is None:
            raise UpdateError("MYSQL_BASELINE_REQUIRED", "先建立一致性基线或提供持久化游标")
        with closing(self.connect()) as connection:
            identity, schema = self._identity(connection)
            if identity != self.cursor.source or schema != self.cursor.position.get("schema"):
                raise UpdateError("SCHEMA_MISMATCH", "来源实例或结构与CDC基线不符")
            with connection.cursor() as query:
                query.execute("SHOW BINARY LOGS")
                logs = {row["Log_name"]: row["File_size"] for row in query.fetchall()}
        file, position = self.cursor.position.get("file"), self.cursor.position.get("pos")
        if file not in logs or type(position) is not int or not 4 <= position <= logs[file]:
            raise UpdateError("SOURCE_LOG_GAP", "已保存日志位置不可用，须恢复日志或重建基线")

    def transactions(self) -> Iterator[SourceTransaction]:
        try:
            self._check_resume()
        except pymysql.MySQLError as error:
            raise UpdateError("MYSQL_CDC_UNAVAILABLE", "无法核对来源实例及已保存位点") from error
        assert self.cursor is not None
        stream = BinLogStreamReader(
            connection_settings=self.settings,
            server_id=self.server_id,
            log_file=self.cursor.position["file"],
            log_pos=self.cursor.position["pos"],
            resume_stream=True,
            blocking=False,
            verify_checksum=True,
            enable_logging=False,
            filter_non_implemented_events=False,
            only_events=[
                WriteRowsEvent,
                UpdateRowsEvent,
                DeleteRowsEvent,
                QueryEvent,
                RotateEvent,
                XidEvent,
                PartialUpdateRowsEvent,
                XAPrepareEvent,
                NotImplementedEvent,
            ],
        )
        events: list[RowChange] = []
        size = 0
        try:
            for event in stream:
                if isinstance(event, (PartialUpdateRowsEvent, XAPrepareEvent, NotImplementedEvent)):
                    raise UpdateError(
                        "MYSQL_EVENT_UNSUPPORTED", "不支持的日志类型，保持最后完整位点"
                    )
                if isinstance(event, QueryEvent):
                    self._check_query(event)
                elif isinstance(event, (WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent)):
                    changes = self._changes(event, stream.log_file)
                    events.extend(changes)
                    size += sum(len(encode(change.model_dump()).encode()) for change in changes)
                    if len(events) > self.max_events or size > self.max_bytes:
                        raise UpdateError("TRANSACTION_LIMIT", "真实CDC事务超过本次预算")
                elif isinstance(event, XidEvent):
                    transaction = self._transaction(stream.log_file, event.packet.log_pos, events)
                    yield transaction
                    if self.cursor != transaction.cursor:
                        raise UpdateError("SOURCE_ACK_REQUIRED", "事务须持久化并确认后继续")
                    events, size = [], 0
            if events:
                raise UpdateError("SOURCE_INCOMPLETE", "日志流结束于未完成的事务")
        except pymysql.MySQLError as error:
            raise UpdateError(
                "MYSQL_CDC_UNAVAILABLE", "MySQL日志读取失败，保留最后持久位点"
            ) from error
        finally:
            stream.close()

    def _check_query(self, event: Any) -> None:
        schema = event.schema.decode() if isinstance(event.schema, bytes) else event.schema
        statement = event.query.strip().upper()
        if schema == self.database and statement not in {"BEGIN", "COMMIT", "ROLLBACK"}:
            raise UpdateError("SOURCE_DDL", "来源出现语句或DDL事件，暂停并核对契约")

    def _changes(self, event: Any, file: str) -> list[RowChange]:
        if event.schema != self.database or event.table not in self.tables:
            return []
        operation = {WriteRowsEvent: "insert", UpdateRowsEvent: "update", DeleteRowsEvent: "delete"}
        result = []
        for index, row in enumerate(event.rows):
            before = row.get(
                "before_values", row.get("values") if isinstance(event, DeleteRowsEvent) else None
            )
            after = row.get(
                "after_values", row.get("values") if isinstance(event, WriteRowsEvent) else None
            )
            result.append(
                RowChange(
                    event_id=f"{file}:{event.packet.log_pos}:{index}",
                    table=self.tables[event.table],
                    operation=operation[type(event)],  # type: ignore[arg-type]
                    before=json_row(before) if before is not None else None,
                    after=json_row(after) if after is not None else None,
                )
            )
        return result

    def _transaction(self, file: str, position: int, events: list[RowChange]) -> SourceTransaction:
        assert self.cursor is not None
        cursor = Cursor(
            source=self.cursor.source,
            position={
                "file": file,
                "pos": position,
                "schema": self.cursor.position["schema"],
            },
        )
        return SourceTransaction(
            generation=self.generation,
            transaction_id=f"{file}:{position}",
            previous=self.cursor,
            cursor=cursor,
            event_count=len(events),
            events=events,
        )

    def acknowledge(self, transaction: SourceTransaction) -> None:
        if transaction.previous != self.cursor or transaction.generation != self.generation:
            raise UpdateError("SOURCE_ACK_MISMATCH", "确认必须对应当前已交付事务")
        self.cursor = transaction.cursor
