"""无MySQL／图测试库时的更新核心回归。图目标使用显式测试替身，关系计算不在Python模拟。"""

import copy
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from relationship_query.update.artifacts import artifact_directory, load_active, publisher_lock
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import (
    GraphReceipt,
    SourceSnapshot,
    SourceTransaction,
    UpdateError,
    digest,
)
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.source import ReplaySource
from relationship_query.update.store import UpdateStore

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "resources/examples"


class Transactions:
    def __init__(self, records, *, lose_ack=False):
        self.records, self.acks, self.lose_ack = records, [], lose_ack

    def transactions(self):
        yield from self.records

    def acknowledge(self, transaction):
        if self.lose_ack:
            raise OSError("simulated acknowledgement loss")
        self.acks.append(transaction.transaction_id)


class TestGraph:
    __test__ = False

    def __init__(self, callback=None):
        self.plans, self.contexts, self.callback = [], [], callback

    def build_and_verify(self, projection, context):
        self.plans.append(projection)
        self.contexts.append(context)
        if self.callback:
            self.callback()
        return GraphReceipt(
            backend="test-double",
            space="test-only-space",
            graph_digest="a" * 64,
            node_count=len(projection.nodes),
            fact_count=len(projection.facts),
            relation_count=0,
        )


@pytest.fixture
def inputs():
    contract = json.loads((EXAMPLES / "update-contract-v1.json").read_text())
    snapshot = json.loads((EXAMPLES / "update-baseline-v1.json").read_text())
    transactions = [
        json.loads(line)
        for line in (EXAMPLES / "update-transactions-v1.jsonl").read_text().splitlines()
    ]
    return contract, snapshot, transactions


def program_at(directory, contract_data, snapshot_data):
    contract = SourceContract.model_validate(contract_data)
    store = UpdateStore(directory, contract, create=True)
    program = UpdateProgram(store, NumericProjectionAdapter(contract))
    program.bootstrap(SourceSnapshot.model_validate(snapshot_data), 202611)
    return program


@pytest.fixture
def running(tmp_path, inputs):
    contract, snapshot, transactions = inputs
    program = program_at(tmp_path / "update", contract, snapshot)
    return program, [SourceTransaction.model_validate(row) for row in transactions]


def test_baseline_numeric_namespaces_privacy_and_education(running):
    program, _ = running
    rows = program.store.rows_at(0, max_rows=10000)
    projection = program.adapter.build(rows, 202611)
    assert {node["vid"] for node in projection.nodes} == {
        "p:expert:1",
        "p:resume:1",
        "e:company:1",
        "e:company:2",
        "e:school:1",
        "e:major:1",
    }
    assert {edge["rank"] for edge in projection.facts} == {101, 102, 103, 104, 105, 106}
    for node in projection.nodes:
        if node["type"] == "person":
            assert set(node["properties"]) == {"source_system", "serial_number"}
    education = [
        edge
        for edge in projection.facts
        if edge["source"] == "p:expert:1" and edge["type"] in {"studied_at", "studied_major"}
    ]
    assert len(education) == 2
    assert {edge["properties"]["experience_key"] for edge in education} == {
        "expert:experts_education_experience:1",
    }


def test_three_transactions_correct_targets_mapping_delete_and_cutoff(running):
    program, transactions = running
    assert program.capture(Transactions(transactions)) == {"captured": 3, "replayed": 0}
    first = program.adapter.build(program.store.rows_at(1, max_rows=10000), 202611)
    expert_work = next(edge for edge in first.facts if edge["rank"] == 101)
    assert expert_work["target"] == "e:company:2"
    assert expert_work["properties"]["position_title"] == "模拟技术负责人"
    assert len(first.facts) == 6
    second = program.adapter.build(program.store.rows_at(2, max_rows=10000), 202611)
    assert {edge["rank"] for edge in second.facts} == {101, 103, 104, 105, 106}
    final = program.adapter.build(program.store.rows_at(3, max_rows=10000), 202611)
    assert len(final.nodes) == 7 and len(final.facts) == 6
    assert next(edge for edge in final.facts if edge["rank"] == 107)["source"] == "p:resume:2"
    assert program.store.status()["captured_tx_seq"] == 3


def test_file_replay_restart_and_ack_after_durable_commit(running):
    program, _ = running
    replay = ReplaySource(EXAMPLES / "update-transactions-v1.jsonl")
    program.capture(replay)
    store = UpdateStore(program.store.directory, program.store.contract)
    restarted = UpdateProgram(store, program.adapter)
    assert restarted.capture(replay) == {"captured": 0, "replayed": 3}
    assert store.status()["captured_tx_seq"] == 3


def test_ack_loss_replays_without_reapplying(running):
    program, transactions = running
    with pytest.raises(OSError):
        program.capture(Transactions([transactions[0]], lose_ack=True))
    assert program.store.status()["captured_tx_seq"] == 1
    source = Transactions([transactions[0]])
    assert program.capture(source) == {"captured": 0, "replayed": 1}
    assert source.acks == [transactions[0].transaction_id]


def test_transaction_failure_rolls_back_events_rows_and_cursor(running):
    program, transactions = running
    broken = transactions[0].model_dump(mode="json")
    broken["events"][1]["before"]["standard_entity_id"] = 999
    source = Transactions([SourceTransaction.model_validate(broken)])
    before = digest(program.store.rows_at(0, max_rows=10000))
    with pytest.raises(UpdateError, match="旧值"):
        program.capture(source)
    assert not source.acks
    assert program.store.status()["captured_tx_seq"] == 0
    assert program.store.status()["status"] == "paused"
    assert digest(program.store.rows_at(0, max_rows=10000)) == before
    with program.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rq_cdc_event").fetchone()[0] == 0


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("gap", "CURSOR_GAP"),
        ("generation", "GENERATION_CHANGED"),
        ("ddl", "SCHEMA_CHANGE"),
        ("missing_column", "SCHEMA_MISMATCH"),
        ("wrong_type", "FIELD_TYPE_CHANGED"),
    ],
)
def test_incompatible_input_pauses_without_advancing(running, failure, expected):
    program, transactions = running
    data = transactions[0].model_dump(mode="json")
    if failure == "gap":
        data["previous"]["position"]["offset"] = 999
    elif failure == "generation":
        data["generation"] = "other-source-generation"
    elif failure == "ddl":
        data["events"][0]["operation"] = "ddl"
    elif failure == "missing_column":
        data["events"][0]["after"].pop("position_title")
    else:
        data["events"][0]["after"]["expert_id"] = 1.0
    source = Transactions([SourceTransaction.model_validate(data)])
    with pytest.raises(UpdateError) as error:
        program.capture(source)
    assert error.value.code == expected
    assert not source.acks
    assert program.store.status()["captured_tx_seq"] == 0
    with pytest.raises(UpdateError, match="暂停"):
        program.process(202611)


@pytest.mark.parametrize("failure", ["event_count", "duplicate_event", "missing_image"])
def test_incomplete_protocol_is_rejected_before_ingest(inputs, failure):
    data = inputs[2][0]
    if failure == "event_count":
        data["event_count"] += 1
    elif failure == "duplicate_event":
        data["events"][1]["event_id"] = data["events"][0]["event_id"]
    else:
        data["events"][0]["before"] = None
    with pytest.raises(ValidationError):
        SourceTransaction.model_validate(data)


def test_contract_change_requires_new_baseline(running):
    program, _ = running
    data = program.store.contract.model_dump(mode="json")
    data["version"] = "new-contract"
    with pytest.raises(UpdateError) as error:
        UpdateStore(program.store.directory, SourceContract.model_validate(data))
    assert error.value.code == "CONTRACT_CHANGED"


def test_table_and_field_renames_only_change_binding(tmp_path, inputs):
    contract, snapshot, transactions = inputs
    original = program_at(tmp_path / "original", contract, snapshot)
    original.capture(Transactions([SourceTransaction.model_validate(row) for row in transactions]))
    expected = original.adapter.build(original.store.rows_at(3, max_rows=10000), 202611)
    contract = copy.deepcopy(contract)
    contract["version"] = "renamed-v2"
    binding = contract["tables"]["work_expert"]
    old, new = binding["physical"], "mock.renamed_employment"
    binding["physical"] = new
    binding["columns"]["person_id"] = "owner_id"
    snapshot["tables"][new] = snapshot["tables"].pop(old)
    for row in snapshot["tables"][new]:
        row["owner_id"] = row.pop("expert_id")
    for transaction in transactions:
        for event in transaction["events"]:
            if event["table"] == old:
                event["table"] = new
                for image in (event["before"], event["after"]):
                    if image is not None:
                        image["owner_id"] = image.pop("expert_id")
    renamed = program_at(tmp_path / "renamed", contract, snapshot)
    renamed.capture(Transactions([SourceTransaction.model_validate(row) for row in transactions]))
    assert renamed.adapter.build(renamed.store.rows_at(3, max_rows=10000), 202611) == expected


def test_bigint_string_input_keeps_precision_and_type_namespace(tmp_path, inputs):
    contract, snapshot, _ = inputs
    large = 2**53 + 17
    companies = snapshot["tables"]["mock.graph_company_entity"]
    companies[0]["id"] = str(large)
    for row in snapshot["tables"]["mock.graph_edge_mapping"]:
        if row["edge_type"] == "worked_at":
            row["standard_entity_id"] = str(large)
    for row in snapshot["tables"]["mock.graph_expert_name_mapping"]:
        if row["entity_type"] == "company":
            row["company_id"] = str(large)
    program = program_at(tmp_path / "large", contract, snapshot)
    plan = program.adapter.build(program.store.rows_at(0, max_rows=10000), 202611)
    assert f"e:company:{large}" in {node["vid"] for node in plan.nodes}
    assert "e:school:1" in {node["vid"] for node in plan.nodes}


def test_plan_has_no_ready_graph_or_active_pointer(running):
    program, transactions = running
    program.capture(Transactions(transactions))
    plan = program.process(202611)
    assert plan.state == "planned" and plan.graph is None
    assert not (program.store.directory / "active.json").exists()
    assert program.store.status()["batches"][0]["status"] == "planned"
    second = program.process(202611)
    assert second.batch_id == plan.batch_id and second.token == plan.token + 1


def test_cutoff_stays_fixed_while_capture_moves_forward(running):
    program, transactions = running
    program.capture(Transactions([transactions[0]]))
    target = TestGraph(callback=lambda: program.capture(Transactions([transactions[1]])))
    first = program.process(202611, target)
    assert first.to_seq == 1 and first.graph.backend == "test-double"
    assert len(target.plans[0].facts) == 6
    assert program.store.status()["captured_tx_seq"] == 2
    second = program.process(202611, TestGraph())
    assert (second.from_seq, second.to_seq) == (1, 2)


def test_microbatches_month_rollover_and_noop(running):
    program, transactions = running
    program.capture(Transactions(transactions))
    target = TestGraph()
    for index in range(1, 4):
        batch = program.process(202611, target, max_transactions=1)
        assert (batch.from_seq, batch.to_seq) == (index - 1, index)
    assert program.process(202611, target) is None
    rollover = program.process(202612, target)
    assert (rollover.from_seq, rollover.to_seq) == (3, 3)
    assert target.contexts[-1].reference_month == 202612
    with pytest.raises(UpdateError, match="回退"):
        program.process(202611, target)


def test_failed_build_preserves_active_and_retries_new_attempt(running):
    program, transactions = running
    program.process(202611, TestGraph())
    previous = (program.store.directory / "active.json").read_bytes()
    program.capture(Transactions([transactions[0]]))

    def failed():
        raise UpdateError("SIMULATED_GRAPH_FAILURE", "test failure")

    with pytest.raises(UpdateError):
        program.process(202611, TestGraph(callback=failed))
    assert (program.store.directory / "active.json").read_bytes() == previous
    failed_batch = program.store.status()["batches"][-1]
    recovered = program.process(202611, TestGraph())
    assert recovered.batch_id == failed_batch["batch_id"]
    assert recovered.token == failed_batch["token"] + 1


def test_expired_claim_cannot_change_new_worker_state(running):
    program, _ = running
    store = program.store
    old = store.claim(0, 0, 202611, "old", 100, lease_seconds=-1)
    current = store.claim(0, 0, 202611, "current", 100)
    assert current["token"] == old["token"] + 1
    with pytest.raises(UpdateError, match="租约"):
        store.stage(old, "ready")
    store.fail(old, "STALE")
    assert store.status()["batches"][0]["status"] == "building"


def test_pointer_recovers_after_registration_failure(running, monkeypatch):
    program, _ = running
    from relationship_query.update import service

    replace = service.replace_active

    def interrupted(directory, pointer):
        replace(directory, pointer)
        raise RuntimeError("simulated crash after file replacement")

    monkeypatch.setattr(service, "replace_active", interrupted)
    with pytest.raises(RuntimeError):
        program.process(202611, TestGraph())
    assert program.store.status()["batches"][0]["status"] == "failed"
    monkeypatch.setattr(service, "replace_active", replace)
    restarted = UpdateProgram(
        UpdateStore(program.store.directory, program.store.contract), program.adapter
    )
    assert restarted.process(202611, TestGraph()) is None
    assert restarted.store.status()["batches"][0]["status"] == "published"


def test_artifact_mutation_and_concurrent_publisher_fail_closed(running):
    program, _ = running
    with publisher_lock(program.store.directory), pytest.raises(UpdateError, match="发布进程"):
        program.process(202611, TestGraph())
    manifest = program.process(202611, TestGraph())
    directory = artifact_directory(program.store.directory, manifest.batch_id, manifest.token)
    (directory / "source-snapshot.json").write_text("{}")
    with pytest.raises(UpdateError, match="校验"):
        load_active(program.store.directory, program.store.contract)


def test_transaction_and_row_budgets_do_not_truncate(running):
    program, transactions = running
    limited = UpdateProgram(program.store, program.adapter, max_events=1)
    with pytest.raises(UpdateError, match="预算"):
        limited.capture(Transactions([transactions[0]]))
    assert program.store.status()["captured_tx_seq"] == 0
    with pytest.raises(UpdateError, match="预算"):
        program.store.rows_at(0, max_rows=1)


def test_refuses_unrelated_existing_database(tmp_path, inputs):
    state = tmp_path / "unrelated"
    state.mkdir(mode=0o700)
    database = state / "state.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE user_data(id INTEGER)")
    connection.close()
    database.chmod(0o600)
    before = database.read_bytes()
    with pytest.raises(UpdateError, match="不属于"):
        UpdateStore(state, SourceContract.model_validate(inputs[0]))
    assert database.read_bytes() == before


def test_cli_normal_entrypoints(tmp_path):
    state = tmp_path / "cli"
    base = [sys.executable, "-m", "relationship_query.update"]
    config = ["--contract", str(EXAMPLES / "update-contract-v1.json"), "--state", str(state)]
    commands = [
        [
            "bootstrap",
            *config,
            "--input",
            str(EXAMPLES / "update-baseline-v1.json"),
            "--reference-month",
            "202611",
        ],
        ["capture", *config, "--input", str(EXAMPLES / "update-transactions-v1.jsonl")],
        ["plan", *config, "--reference-month", "202611"],
        ["status", *config],
    ]
    for command in commands:
        result = subprocess.run(
            base + command, cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["ok"]
    assert json.loads(result.stdout)["active_revision"] == 0


def test_selected_datetime_formats_normalize_before_comparison(running):
    program, transactions = running
    data = transactions[0].model_dump(mode="json")
    data["events"][0]["before"]["start_date"] = "2020-01-01T00:00:00+00:00"
    data["events"][0]["after"]["start_date"] = "2019-12-31T19:00:00-05:00"
    program.capture(Transactions([SourceTransaction.model_validate(data)]))
    work = program.store.rows_at(1, max_rows=10000)["work_expert"][0]
    assert work["start_date"] == "2020-01-01T00:00:00.000000+00:00"


def test_unused_new_columns_do_not_change_projection(tmp_path, inputs):
    contract, snapshot, _ = inputs
    base = program_at(tmp_path / "base", contract, snapshot)
    expected = base.adapter.build(base.store.rows_at(0, max_rows=10000), 202611)
    for records in snapshot["tables"].values():
        for row in records:
            row["new_unused_column"] = {"arbitrary": [1, 2, 3]}
    extended = program_at(tmp_path / "extended", contract, snapshot)
    assert extended.adapter.build(extended.store.rows_at(0, max_rows=10000), 202611) == expected


@pytest.mark.parametrize(
    "table,field", [("company", "verification_status"), ("name_mapping", "processing_status")]
)
def test_unknown_status_stops_instead_of_silently_removing_relations(running, table, field):
    program, _ = running
    rows = program.store.rows_at(0, max_rows=10000)
    rows[table][0][field] = "new-unconfigured-status"
    with pytest.raises(UpdateError) as error:
        program.adapter.build(rows, 202611)
    assert error.value.code == "STATUS_MAPPING_REQUIRED"


@pytest.mark.parametrize("conflict", ["transaction", "event"])
def test_replayed_identity_with_different_content_is_rejected(running, conflict):
    program, transactions = running
    program.capture(Transactions([transactions[0]]))
    if conflict == "transaction":
        data = transactions[0].model_dump(mode="json")
        data["events"][0]["after"]["position_title"] = "different-payload"
    else:
        data = transactions[1].model_dump(mode="json")
        data["events"][0]["event_id"] = transactions[0].events[0].event_id
    with pytest.raises(UpdateError) as error:
        program.capture(Transactions([SourceTransaction.model_validate(data)]))
    assert error.value.code == (
        "REPLAY_CONFLICT" if conflict == "transaction" else "EVENT_CONFLICT"
    )
    assert program.store.status()["captured_tx_seq"] == 1


def test_native_target_rejects_budget_before_opening_graph(running, tmp_path):
    from relationship_query.update.models import Projection
    from relationship_query.update.target import BuildContext, NebulaTarget

    program, _ = running
    projection = program.adapter.build(program.store.rows_at(0, max_rows=10000), 202611)
    original = next(edge for edge in projection.facts if edge["type"] == "worked_at")
    oversized = Projection(
        nodes=[], facts=[{**original, "rank": index + 1} for index in range(150)]
    )
    with pytest.raises(UpdateError) as error:
        NebulaTarget(tmp_path / "absent.json").build_and_verify(
            oversized, BuildContext(tmp_path, "test", "a" * 64, 202611)
        )
    assert error.value.code == "RELATION_BUILD_LIMIT"


@pytest.mark.parametrize("bad_read", [False, True])
def test_native_target_calls_graph_materialization_and_verifies_readback(
    running, tmp_path, monkeypatch, bad_read
):
    from relationship_query.update import target

    program, _ = running
    projection = program.adapter.build(program.store.rows_at(0, max_rows=10000), 202611)
    stored_meta, calls = [], []

    @contextmanager
    def session(_credentials):
        yield object()

    class Writer:
        def __init__(self, session):
            pass

        def vertices(self, tag, columns, rows):
            stored_meta.append(dict(zip(columns, rows[0][1])))

    def query(session, statement, **kwargs):
        calls.append(statement)
        return [{"meta": stored_meta[-1]}] if statement.startswith("FETCH PROP") else []

    def reader(session, directory):
        (directory / "reader-credentials.json").write_text("test-only-reader")
        return SimpleNamespace(username="test_reader")

    monkeypatch.setattr(target, "load_credentials", lambda _: object())
    monkeypatch.setattr(target, "connect", session)
    monkeypatch.setattr(target, "query", query)
    monkeypatch.setattr(target, "ProjectionWriter", Writer)
    monkeypatch.setattr(target, "insert_nodes", lambda *args: None)
    monkeypatch.setattr(target, "insert_edges", lambda *args: None)
    calculated = []
    monkeypatch.setattr(
        target,
        "calculate_relations",
        lambda session, nodes, month, **kwargs: calculated.append(month) or [],
    )
    monkeypatch.setattr(
        target,
        "read_all",
        lambda execute, nodes, **kwargs: (nodes, [] if bad_read else projection.facts),
    )
    monkeypatch.setattr(target, "_reader_account", reader)
    checked_readers = []
    monkeypatch.setattr(
        target, "verify_reader", lambda reader, space, meta: checked_readers.append(meta.copy())
    )
    context = target.BuildContext(tmp_path, "mock-native", "a" * 64, 202611)
    if bad_read:
        with pytest.raises(UpdateError, match="回读"):
            target.NebulaTarget(tmp_path / "credentials.json").build_and_verify(projection, context)
        assert stored_meta[-1]["state"] == "staging"
        assert not (tmp_path / "reader-credentials.json").exists()
    else:
        receipt = target.NebulaTarget(tmp_path / "credentials.json").build_and_verify(
            projection, context
        )
        assert receipt.node_count == 6 and receipt.fact_count == 6
        assert stored_meta[-1]["schema_version"] == "numeric-relations-v1"
        assert stored_meta[-1]["state"] == "ready"
        assert checked_readers == [stored_meta[-1]]
    assert calculated == [202611]
    assert any(statement.startswith("CREATE SPACE `relationship_lab_sync_") for statement in calls)


def test_later_correction_can_supersede_failed_intermediate_batch(running):
    program, transactions = running
    data = transactions[0].model_dump(mode="json")
    data["events"][1]["after"]["standard_entity_id"] = 999
    data["events"][2]["after"]["company_id"] = 999
    first = SourceTransaction.model_validate(data)
    program.capture(Transactions([first]))
    with pytest.raises(UpdateError, match="引用"):
        program.process(202611, TestGraph())
    correction = SourceTransaction.model_validate(
        {
            "generation": first.generation,
            "transaction_id": "later-correction",
            "previous": first.cursor.model_dump(),
            "cursor": {
                "source": first.cursor.source,
                "position": {"kind": "offline-replay", "offset": 2},
            },
            "event_count": 1,
            "events": [
                {
                    "event_id": "later-new-company",
                    "table": "mock.graph_company_entity",
                    "operation": "insert",
                    "after": {
                        "id": 999,
                        "standard_name": "模拟纠正公司",
                        "company_code": "corrected-999",
                        "verification_status": "模拟有效",
                        "deleted_at": None,
                    },
                }
            ],
        }
    )
    program.capture(Transactions([correction]))
    batch = program.process(202611, TestGraph())
    assert batch.to_seq == 2
    assert program.store.status()["batches"][0]["status"] == "cancelled"
    assert program.store.status()["batches"][1]["status"] == "published"


def test_public_directory_rejected_before_creating_database(tmp_path, inputs):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    with pytest.raises(UpdateError, match="700"):
        UpdateStore(directory, SourceContract.model_validate(inputs[0]), create=True)
    assert not (directory / "state.sqlite").exists()


@pytest.mark.parametrize("kind", ["snapshot", "transaction", "contract"])
def test_unknown_protocol_version_requires_explicit_migration(inputs, kind):
    contract, snapshot, transactions = inputs
    model, value = {
        "snapshot": (SourceSnapshot, snapshot),
        "transaction": (SourceTransaction, transactions[0]),
        "contract": (SourceContract, contract),
    }[kind]
    value["format_version"] = 2
    with pytest.raises(ValidationError):
        model.model_validate(value)


def test_unknown_table_rolls_back_and_pauses_instead_of_skipping(running):
    program, transactions = running
    record = transactions[0].model_dump(mode="json")
    # 模拟表改名后采集器仍使用旧契约，避免忽略更名表却推进整个事务位点。
    record["events"][0]["table"] = "mock.renamed_work_experience"
    source = Transactions([SourceTransaction.model_validate(record)])
    with pytest.raises(UpdateError) as error:
        program.capture(source)
    assert error.value.code == "UNEXPECTED_TABLE"
    assert not source.acks
    status = program.store.status()
    assert status["captured_tx_seq"] == 0 and status["status"] == "paused"
    with program.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM rq_cdc_event").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["invalid_json", "incomplete", "oversized"])
def test_source_parse_failure_pauses_publication_at_last_commit(running, tmp_path, failure):
    program, transactions = running
    program.process(202611, TestGraph())
    active = (program.store.directory / "active.json").read_bytes()
    first, second = [record.model_dump(mode="json") for record in transactions[:2]]
    if failure == "invalid_json":
        bad_line = "{invalid-json"
    else:
        second["event_count"] += 1
        bad_line = json.dumps(second)
    path = tmp_path / "damaged.jsonl"
    path.write_text(json.dumps(first) + "\n" + bad_line + "\n")
    limit = len(json.dumps(first).encode()) + 1
    if failure == "oversized":
        path.write_text(json.dumps(first) + "\n" + " " * (limit + 1) + "\n")
    source = ReplaySource(path, max_bytes=limit if failure == "oversized" else 8 * 1024 * 1024)
    with pytest.raises(UpdateError):
        program.capture(source)
    status = program.store.status()
    assert status["captured_tx_seq"] == 1 and status["status"] == "paused"
    with pytest.raises(UpdateError, match="暂停"):
        program.process(202611, TestGraph())
    assert (program.store.directory / "active.json").read_bytes() == active


@pytest.mark.parametrize("month,max_rows", [(202613, 10000), (202611, 1), (202611, 0)])
def test_cli_rejected_baseline_keeps_state_path_reusable(tmp_path, month, max_rows):
    state = tmp_path / "reusable"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "relationship_query.update",
            "bootstrap",
            "--contract",
            str(EXAMPLES / "update-contract-v1.json"),
            "--state",
            str(state),
            "--input",
            str(EXAMPLES / "update-baseline-v1.json"),
            "--reference-month",
            str(month),
            "--max-rows",
            str(max_rows),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert not json.loads(result.stdout)["ok"]
    assert not state.exists()


def test_retry_cannot_silently_exceed_smaller_microbatch_budget(running):
    program, transactions = running
    program.capture(Transactions(transactions))
    planned = program.process(202611, max_transactions=3)
    assert planned.to_seq == 3
    with pytest.raises(UpdateError) as error:
        program.process(202611, TestGraph(), max_transactions=1)
    assert error.value.code == "BATCH_RANGE_LIMIT"
    assert not (program.store.directory / "active.json").exists()


@pytest.mark.parametrize("result", ["success", "bad_meta", "timeout"])
def test_native_reader_readiness_checks_real_identity_and_closes_connections(monkeypatch, result):
    from relationship_query.infrastructure.graph_model import ReaderCredentials
    from relationship_query.infrastructure.nebula_lab import LabQueryError
    from relationship_query.update import target

    readers = ReaderCredentials(username="rq_0123456789ab", password="a" * 24)
    expected = {"state": "ready", "schema_version": "numeric-relations-v1"}
    closed, released, calls = [], [], []

    class Session:
        def release(self):
            released.append(True)

    class Pool:
        def init(self, addresses, config):
            assert addresses == [(readers.host, readers.port)]
            return True

        def get_session(self, username, password):
            assert username == readers.username
            return Session()

        def close(self):
            closed.append(True)

    def query(session, statement):
        calls.append(statement)
        if result == "bad_meta":
            return [{"meta": {"state": "staging"}}]
        if len(calls) == 1 or result == "timeout":
            raise LabQueryError(-1004)
        return [{"meta": expected}]

    clock = iter([0, 61] if result == "timeout" else [0, 1])
    monkeypatch.setattr(target, "ConnectionPool", Pool)
    monkeypatch.setattr(target, "query", query)
    monkeypatch.setattr(target, "monotonic", lambda: next(clock))
    monkeypatch.setattr(target, "sleep", lambda seconds: None)
    if result == "success":
        target.verify_reader(readers, "relationship_lab_sync_0123456789ab", expected)
        assert len(calls) == 2
    else:
        with pytest.raises(UpdateError) as error:
            target.verify_reader(readers, "relationship_lab_sync_0123456789ab", expected)
        assert error.value.code == (
            "GRAPH_INTEGRITY" if result == "bad_meta" else "GRAPH_READER_UNAVAILABLE"
        )
    assert len(closed) == len(released) == len(calls)


def test_native_failure_keeps_resource_identity_before_external_creation(
    running, tmp_path, monkeypatch
):
    from relationship_query.update import target

    program, _ = running
    projection = program.adapter.build(program.store.rows_at(0, max_rows=10000), 202611)

    def unavailable_credentials(path):
        raise OSError("mock credential read failure")

    monkeypatch.setattr(target, "load_credentials", unavailable_credentials)
    context = target.BuildContext(tmp_path, "mock-native", "a" * 64, 202611)
    with pytest.raises(UpdateError) as error:
        target.NebulaTarget(tmp_path / "credentials.json").build_and_verify(projection, context)
    assert error.value.code == "GRAPH_BUILD_FAILED"
    resource = json.loads((tmp_path / "build-resource.json").read_text())
    assert resource["backend"] == "nebula"
    assert resource["space"].startswith("relationship_lab_sync_")


@pytest.mark.parametrize("failure", ["non_finite", "oversized_integer"])
def test_invalid_value_encoding_pauses_without_committing(running, failure):
    program, transactions = running
    data = transactions[0].model_dump(mode="json")
    if failure == "non_finite":
        data["events"][0]["after"]["unused_column"] = float("nan")
    else:
        data["events"][0]["after"]["expert_id"] = "9" * 5000
    source = Transactions([SourceTransaction.model_validate(data)])
    with pytest.raises(UpdateError) as error:
        program.capture(source)
    assert error.value.code == "SOURCE_PROTOCOL"
    assert not source.acks
    status = program.store.status()
    assert status["status"] == "paused" and status["captured_tx_seq"] == 0
