"""事务接收与微批发布编排，不依赖来源物理字段或CDC服务协议。"""

import os
from typing import Any, Protocol
from uuid import uuid4

from pydantic import TypeAdapter

from relationship_query.domain.models import Month
from relationship_query.infrastructure.numeric_read_model import write_query_model
from relationship_query.update.artifacts import (
    BuildManifest,
    ReleasePointer,
    artifact_directory,
    checksum,
    load_active,
    publisher_lock,
    replace_active,
    source_sqlite,
    write_json,
)
from relationship_query.update.models import (
    Projection,
    Row,
    SourceSnapshot,
    UpdateError,
    digest,
    encode,
)
from relationship_query.update.source import ChangeSource
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import BuildContext, GraphTarget


class ProjectionAdapter(Protocol):
    def build(self, rows: dict[str, list[Row]], reference_month: int) -> Projection: ...


class UpdateProgram:
    def __init__(
        self,
        store: UpdateStore,
        adapter: ProjectionAdapter,
        *,
        max_rows: int = 10_000,
        max_events: int = 10_000,
        max_transaction_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if min(max_rows, max_events, max_transaction_bytes) < 1:
            raise UpdateError("INVALID_BUDGET", "处理预算必须为正数")
        self.store, self.adapter = store, adapter
        self.max_rows, self.max_events = max_rows, max_events
        self.max_transaction_bytes = max_transaction_bytes

    def bootstrap(self, snapshot: SourceSnapshot, reference_month: int) -> None:
        TypeAdapter(Month).validate_python(reference_month)
        rows = self.store.contract.snapshot(snapshot.tables)
        if sum(len(records) for records in rows.values()) > self.max_rows:
            raise UpdateError("ROW_LIMIT", "全量输入达到本次行数预算")
        self.adapter.build(rows, reference_month)
        self.store.bootstrap(snapshot, rows)

    def capture(self, source: ChangeSource) -> dict[str, int]:
        captured = replayed = 0
        try:
            for transaction in source.transactions():
                if (
                    transaction.event_count > self.max_events
                    or len(encode(transaction.model_dump(mode="json")).encode())
                    > self.max_transaction_bytes
                ):
                    raise UpdateError("TRANSACTION_LIMIT", "事务超过预算，保持原消费位点")
                changed = self.store.capture(transaction)
                # 持久化成功后再确认。确认失败重放时由事务摘要与事件键去重。
                source.acknowledge(transaction)
                captured += int(changed)
                replayed += int(not changed)
        except ValueError:
            self.store.pause("SOURCE_PROTOCOL")
            raise UpdateError(
                "SOURCE_PROTOCOL", "采集输入不符合完整事务编码或协议，已暂停发布"
            ) from None
        except UpdateError as error:
            # 迭代器解析错误同样阻断发布，保留最后完整提交的消费位置。
            self.store.pause(error.code)
            raise
        return {"captured": captured, "replayed": replayed}

    def process(
        self,
        reference_month: int,
        target: GraphTarget | None = None,
        *,
        max_transactions: int = 100,
    ) -> BuildManifest | None:
        TypeAdapter(Month).validate_python(reference_month)
        if max_transactions < 1:
            raise UpdateError("INVALID_BUDGET", "微批事务预算必须为正数")
        with publisher_lock(self.store.directory):
            active = load_active(self.store.directory, self.store.contract)
            revision, start, old_month = 0, 0, reference_month
            if active is not None:
                pointer, manifest = active
                self.store.reconcile(
                    pointer.batch_id,
                    pointer.token,
                    str(artifact_directory(self.store.directory, pointer.batch_id, pointer.token)),
                )
                revision, start, old_month = (
                    pointer.revision,
                    manifest.to_seq,
                    manifest.reference_month,
                )
            if reference_month < old_month:
                raise UpdateError("REFERENCE_MONTH", "基准月回退需明确建立新基线")
            batch = self.store.claim(
                revision,
                start,
                reference_month,
                f"{os.getpid()}-{uuid4().hex}",
                max_transactions,
                allow_empty=reference_month != old_month,
            )
            if batch is None:
                return None
            try:
                return self._build(batch, target)
            except Exception as error:
                # 记录可恢复的任务失败；控制文件替换后的结果由下次启动按指针补记。
                self.store.fail(
                    batch, error.code if isinstance(error, UpdateError) else type(error).__name__
                )
                raise

    def _build(self, batch: dict[str, Any], target: GraphTarget | None) -> BuildManifest:
        rows = self.store.rows_at(batch["to_seq"], max_rows=self.max_rows)
        projection = self.adapter.build(rows, batch["reference_month"])
        directory = artifact_directory(self.store.directory, batch["batch_id"], batch["token"])
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        source_digest = digest(rows)
        version = (
            f"sync-{self.store.contract.fingerprint[:12]}-{batch['batch_id']}-{batch['token']}"
        )
        context = BuildContext(directory, version, source_digest, batch["reference_month"])
        write_json(directory / "source-snapshot.json", rows)
        source_sqlite(directory / "source.sqlite", self.store.contract, rows)
        write_query_model(
            directory / "source.sqlite",
            self.store.contract,
            rows,
            projection,
            version,
            batch["reference_month"],
        )
        write_json(directory / "graph-plan.json", projection.model_dump(mode="json"))
        receipt = target.build_and_verify(projection, context) if target is not None else None
        self.store.stage(batch, "verifying", str(directory))
        if receipt is not None and (
            receipt.node_count != len(projection.nodes)
            or receipt.fact_count != len(projection.facts)
        ):
            raise UpdateError("GRAPH_INTEGRITY", "图目标收据与事实计划不符")
        names = ["source-snapshot.json", "source.sqlite", "graph-plan.json"]
        if receipt is not None and receipt.backend == "nebula":
            names.extend(["reader-credentials.json", "build-resource.json"])
        status = self.store.status()
        manifest = BuildManifest(
            state="verified" if receipt else "planned",
            batch_id=batch["batch_id"],
            token=batch["token"],
            contract_digest=self.store.contract.fingerprint,
            generation=status["generation"],
            from_seq=batch["from_seq"],
            to_seq=batch["to_seq"],
            reference_month=batch["reference_month"],
            version=version,
            source_digest=source_digest,
            files={name: checksum(directory / name) for name in names},
            graph=receipt,
        )
        write_json(directory / "manifest.json", manifest.model_dump(mode="json"))
        if receipt is None:
            self.store.finish(batch, "planned", str(directory))
        else:
            self.store.stage(batch, "ready", str(directory))
            self._activate(batch, manifest)
        return manifest

    def _activate(self, batch: dict[str, Any], manifest: BuildManifest) -> None:
        directory = artifact_directory(self.store.directory, manifest.batch_id, manifest.token)
        with self.store.connection() as connection:
            self.store.assert_claim(connection, batch)
            active = load_active(self.store.directory, self.store.contract)
            revision = active[0].revision if active else 0
            if revision != batch["base_revision"]:
                raise UpdateError("RELEASE_CHANGED", "候选基线已变化，请重新构建")
            if (
                connection.execute("SELECT status FROM rq_cdc_checkpoint WHERE id=1").fetchone()[0]
                != "streaming"
            ):
                raise UpdateError("CAPTURE_PAUSED", "采集暂停期间阻断候选发布")
            replace_active(
                self.store.directory,
                ReleasePointer(
                    revision=revision + 1,
                    batch_id=manifest.batch_id,
                    token=manifest.token,
                    manifest_digest=checksum(directory / "manifest.json"),
                ),
            )
            connection.execute(
                "UPDATE rq_projection_batch SET status='published',lease_until=NULL,"
                "error_code=NULL "
                "WHERE batch_id=?",
                (manifest.batch_id,),
            )
