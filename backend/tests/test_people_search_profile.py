"""诊断必须解释实际执行的SQL，且记录稀疏发布成员造成的候选翻页。"""

import re

from sqlalchemy import text

from relationship_query.benchmark.people_search import plan_summary, profile
from relationship_query.infrastructure.live_people import LiveRealGraphRepository, MySQLPeople
from relationship_query.infrastructure.mysql import open_mysql_engine

from .test_mysql import LIVE, new_lab
from .test_real_query import real_release as real_release


def test_plan_summary_drops_literals_but_retains_access_paths_and_row_estimates():
    summary = plan_summary(
        {
            "query_block": {
                "ordering_operation": {
                    "using_filesort": True,
                    "table": {
                        "table_name": "experts",
                        "access_type": "ALL",
                        "rows_examined_per_scan": 500,
                        "possible_keys": ["idx_name"],
                        "attached_condition": "private search literal",
                    },
                }
            }
        }
    )
    table = summary["query_block"]["ordering_operation"]["table"]
    assert table["rows_examined_per_scan"] == 500 and table["possible_keys"] == ["idx_name"]
    assert "attached_condition" not in table
    assert summary["query_block"]["ordering_operation"]["using_filesort"] is True


@LIVE
def test_native_actual_query_explain_and_sparse_membership_metrics(real_release):
    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)
        repository = None
        try:
            with engine.begin() as connection:
                for table in ("experts", "resume"):
                    connection.exec_driver_sql(
                        f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, name VARCHAR(100), "
                        "city VARCHAR(50), job_name VARCHAR(100), serial_number VARCHAR(100), "
                        "deleted_at DATETIME NULL, INDEX idx_name(name), "
                        "INDEX idx_serial(serial_number))"
                    )
                connection.execute(
                    text(
                        "INSERT INTO experts VALUES (:id,:name,'模拟城市','模拟岗位',:serial,NULL)"
                    ),
                    [
                        {"id": key, "name": f"张模拟{key}", "serial": f"QA-{key}"}
                        for key in range(1, 501)
                    ],
                )
            repository = LiveRealGraphRepository(real_release, MySQLPeople(engine))
            report = profile(repository, ["张", "O'Brien"], 50)
            first, empty = report["queries"]
            assert first["passed"] and first["items"] == 1
            assert first["source_queries"] == 5 and first["candidate_rows"] == 500
            assert re.search(
                r"\(actual time=[^)]* rows=500 loops=1\)",
                first["plans"]["expert"]["actual_tree"],
            )
            assert "actual" in first["plans"]["expert"]["actual_tree"]
            assert "张" not in str(report) and "O'Brien" not in str(report)
            assert "error" not in first["plans"]["expert"]
            assert empty["passed"] and empty["items"] == 0 and empty["candidate_rows"] == 0
            assert engine.pool.checkedout() == 0
        finally:
            if repository is not None:
                repository.engine.dispose()
            engine.dispose()
