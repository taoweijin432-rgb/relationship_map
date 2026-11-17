"""人物展示按发布身份批量回源，关系与背景筛选仍绑定已发布事实。"""

import os
import ssl
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table, cast, or_, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

from relationship_query.contracts import SearchRequest
from relationship_query.domain.models import Person, Source
from relationship_query.domain.path_budget import PathBudgetExceeded, shared_relation_budget
from relationship_query.infrastructure.mysql import TLSConnection, _open_mysql_engine
from relationship_query.infrastructure.real_api import RealGraphRepository
from relationship_query.infrastructure.sql_repository import prefix_match
from relationship_query.runtime.diagnostics import observe, traced
from relationship_query.runtime.person_reads import current_person_reads
from relationship_query.services.query import QueryError
from relationship_query.update.source_config import MySQLSourceConfig

PERSON_TABLES: dict[Source, str] = {"expert": "experts", "resume": "resume"}


def open_people_engine(config: MySQLSourceConfig, insecure_tls: bool) -> Engine:
    endpoint = config.endpoint("people")
    password = os.environ.get(endpoint.password_env or "")
    if not password:
        raise ValueError("在线人物源需要通过password_env指定非空密码环境变量")
    context = ssl.create_default_context(cafile=endpoint.tls_ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if insecure_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    url = URL.create(
        "mysql+pymysql",
        username=endpoint.user,
        password=password,
        host=endpoint.host,
        port=endpoint.port,
        database=endpoint.database,
    )
    return _open_mysql_engine(
        url, writable=False, connect_args={"ssl": context}, connect_factory=TLSConnection
    )


class MySQLPeople:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        schema = MetaData()
        self.tables = {
            source: Table(
                name,
                schema,
                *(
                    Column(field)
                    for field in ("id", "name", "city", "job_name", "serial_number", "deleted_at")
                ),
            )
            for source, name in PERSON_TABLES.items()
        }

    def check(self, config: MySQLSourceConfig, published: dict) -> None:
        endpoint = config.endpoint("people")
        if (endpoint.host, endpoint.port, endpoint.database) != (
            published.get("host"),
            published.get("port"),
            published.get("database"),
        ):
            raise ValueError("在线人物端点与图发布的人物来源不一致")
        with self.engine.connect() as connection:
            identity = connection.execute(text("SELECT @@server_uuid")).scalar_one()
            if identity != published.get("server", {}).get("server_uuid"):
                raise ValueError("在线人物服务器身份与发布不一致")
            raw = connection.connection.driver_connection
            if raw is None or not isinstance(raw._sock, ssl.SSLSocket):
                raise ValueError("在线人物源需要TLS连接")
            for table in self.tables.values():
                connection.execute(select(table).limit(0))

    @staticmethod
    def _person(source: Source, row: dict) -> Person:
        return Person(
            id=f"p:{source}:{row['id']}",
            name=row["name"] or "",
            city=row["city"] or "",
            headline=row["job_name"] or "",
            sources=[source],
            serial_number=str(row["serial_number"]) if row["serial_number"] is not None else None,
        )

    @traced("MySQLPeople.read")
    def read(self, ids: list[str]) -> dict[str, Person]:
        reads = current_person_reads()
        return reads.read(self, ids, self._read) if reads is not None else self._read(ids)

    @traced("MySQLPeople.fetch")
    def _read(self, ids: list[str]) -> dict[str, Person]:
        result: dict[str, Person] = {}
        if not ids:
            return result
        try:
            with self.engine.connect() as connection:
                for source, table in self.tables.items():
                    keys = [int(key.split(":")[2]) for key in ids if key.startswith(f"p:{source}:")]
                    for offset in range(0, len(keys), 200):
                        rows = connection.execute(
                            select(table).where(
                                table.c.id.in_(keys[offset : offset + 200]),
                                table.c.deleted_at.is_(None),
                            )
                        ).mappings()
                        for row in rows:
                            person = self._person(source, dict(row))
                            result[person.id] = person
        except SQLAlchemyError:
            raise QueryError(
                "PERSON_SOURCE_UNAVAILABLE", "人物来源暂不可用，请稍后重试", 503
            ) from None
        return result

    @traced("MySQLPeople.suggestions")
    def suggestions(self, source: Source, keyword: str, after: str | None) -> list[Person]:
        table = self.tables[source]
        query = select(table).where(table.c.deleted_at.is_(None))
        identity = cast(table.c.id, String)
        if after is not None:
            query = query.where(identity > after)
        if keyword:
            query = query.where(
                or_(
                    prefix_match(self.engine, table.c.name, keyword),
                    prefix_match(self.engine, table.c.serial_number, keyword),
                )
            )
        try:
            with self.engine.connect() as connection:
                people = [
                    self._person(source, dict(row))
                    for row in connection.execute(query.order_by(identity).limit(128)).mappings()
                ]
            observe("people.suggestion_pages")
            observe("people.suggestion_candidates", len(people))
            return people
        except SQLAlchemyError:
            raise QueryError(
                "PERSON_SOURCE_UNAVAILABLE", "人物来源暂不可用，请稍后重试", 503
            ) from None


class LiveRealGraphRepository(RealGraphRepository):
    person_display = "mysql-live"

    def __init__(self, directory: Path, people: MySQLPeople) -> None:
        super().__init__(directory)
        self.people = people
        with self.engine.connect() as connection:
            self.published_sources = set(
                connection.execute(
                    select(self.tables.sources.c.source)
                    .join(
                        self.tables.people,
                        self.tables.people.c.id == self.tables.sources.c.person_id,
                    )
                    .where(self.tables.people.c.active.is_(True))
                    .distinct()
                ).scalars()
            )

    def _members(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(self.tables.people.c.id).where(
                        self.tables.people.c.id.in_(ids), self.tables.people.c.active.is_(True)
                    )
                ).scalars()
            )

    def person(self, person_id: str) -> Person | None:
        return self.people.read(self._members([person_id])).get(person_id)

    def persons(self, ids: list[str]) -> list[Person]:
        members = self._members(ids)
        people = self.people.read(members)
        if set(people) != set(ids):
            raise QueryError("PERSON_SOURCE_CHANGED", "人物已删除或失效，请等待关系批次更新", 503)
        return [people[key] for key in dict.fromkeys(ids)]

    def suggest_people(self, keyword: str, limit: int) -> list[Person]:
        if not keyword:
            ids = self.search_ids(SearchRequest(page_size=limit), None, None)[:limit]
            return self.persons(ids)
        found = []
        try:
            with shared_relation_budget() as budget:
                for source in PERSON_TABLES:
                    if source not in self.published_sources:
                        continue
                    after = None
                    selected: list[Person] = []
                    while len(selected) < limit:
                        budget.check()
                        page = self.people.suggestions(source, keyword, after)
                        members = set(self._members([person.id for person in page]))
                        selected.extend(person for person in page if person.id in members)
                        if len(page) < 128:
                            break
                        after = page[-1].id.split(":")[2]
                    found.extend(selected[:limit])
                budget.check()
        except PathBudgetExceeded as error:
            raise QueryError(
                "PERSON_QUERY_LIMIT",
                f"人物选择查询达到预算（{error.label}），请缩小关键词范围",
                503,
            ) from None
        return sorted(found, key=lambda person: person.id)[:limit]

    def search_ids(
        self, request: SearchRequest, reference_id: str | None, after: str | None
    ) -> list[str]:
        found: list[str] = []
        try:
            with shared_relation_budget() as budget:
                while len(found) <= request.page_size:
                    budget.check()
                    page = super().search_ids(request, reference_id, after)
                    # 同时核对分页探针，活跃人物足够时可直接确定has_more。
                    people = self.people.read(page)
                    found.extend(key for key in page if key in people)
                    if len(page) <= request.page_size:
                        break
                    after = page[-1]
                budget.check()
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"人物召回达到预算（{error.label}），请缩小查询范围", 503
            ) from None
        return found[: request.page_size + 1]

    def matches_person(self, request: SearchRequest, reference_id: str, candidate_id: str) -> bool:
        return self.person(candidate_id) is not None and super().matches_person(
            request, reference_id, candidate_id
        )
