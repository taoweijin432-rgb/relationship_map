import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from relationship_query.api.routes import router
from relationship_query.contracts import ErrorResponse
from relationship_query.infrastructure.graph_paths import GraphPathRepository
from relationship_query.infrastructure.mysql import MySQLPathRepository, open_mysql_engine
from relationship_query.infrastructure.source_api import (
    SourceGraphRepository,
    SourceRepository,
    open_source_engine,
    read_source_manifest,
)
from relationship_query.infrastructure.source_releases import load_active
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import open_engine
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.services.graph_paths import GraphPathService
from relationship_query.services.paths import PathService
from relationship_query.services.ports import PathRepository
from relationship_query.services.query import QueryError, QueryService
from relationship_query.settings import database_path, default_numeric_store

logger = logging.getLogger("relationship_query")


@asynccontextmanager
async def _source_lifespan(
    app: FastAPI, manifest: Path, value: str, check: Callable[[], None] | None = None
) -> AsyncIterator[None]:
    definition = read_source_manifest(manifest)
    engine = open_source_engine(value, definition, manifest)
    try:
        from relationship_query.infrastructure.uuid_api import UUIDRepository
        from relationship_query.infrastructure.uuid_graph import UUIDGraphRepository
        from relationship_query.infrastructure.uuid_source import UUIDManifest
        from relationship_query.services.materialized_query import MaterializedQueryService

        if isinstance(definition, UUIDManifest):
            uuid_source = UUIDRepository(engine, definition, release_check=check)
            uuid_graph = UUIDGraphRepository(uuid_source, manifest)
            app.state.graph_client = uuid_graph.client
            uuid_source.graph = uuid_graph
            app.state.query_service = MaterializedQueryService(uuid_source, uuid_graph)
            app.state.source_guard = uuid_source
            app.state.path_service = GraphPathService(
                uuid_graph, app.state.query_service, projection_id=definition.projection_id
            )
            yield
            return
        source = SourceRepository(engine, definition, release_check=check)
        app.state.query_service = QueryService(source)
        app.state.source_guard = source
        graph = SourceGraphRepository(source, manifest)
        app.state.graph_client = graph.client
        app.state.path_service = GraphPathService(
            graph,
            app.state.query_service,
            projection_id=graph.manifest.projection_id,
        )
        yield
    finally:
        _close_graph_client(app)
        engine.dispose()


def create_app(
    path: Path | None = None,
    *,
    mysql_url: str | None = None,
    graph_manifest: Path | None = None,
    graph_engine: Literal["paths", "candidates"] | None = None,
    source_manifest: Path | None = None,
    source_mysql_url: str | None = None,
    source_release_store: Path | None = None,
    numeric_release_store: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configured = any(
            (
                path,
                mysql_url,
                graph_manifest,
                graph_engine,
                source_manifest,
                source_mysql_url,
                source_release_store,
            )
        ) or any(
            os.environ.get(name)
            for name in (
                "RELATIONSHIP_SOURCE_RELEASE_STORE",
                "RELATIONSHIP_SOURCE_API_MANIFEST",
                "RELATIONSHIP_SOURCE_API_MYSQL_URL",
                "RELATIONSHIP_MYSQL_URL",
                "RELATIONSHIP_NEBULA_MANIFEST",
                "RELATIONSHIP_GRAPH_ENGINE",
                "RELATIONSHIP_DATABASE",
            )
        )
        selected_numeric = numeric_release_store or (
            Path(os.environ["RELATIONSHIP_NUMERIC_RELEASE_STORE"])
            if path is None and os.environ.get("RELATIONSHIP_NUMERIC_RELEASE_STORE")
            else None
        )
        if selected_numeric is None and not configured:
            selected_numeric = default_numeric_store()
        if selected_numeric is not None:
            if configured:
                raise ValueError("数字发布模式与其他数据源配置不能混用")
            async with _numeric_lifespan(app, selected_numeric):
                yield
            return
        selected_store = source_release_store or (
            Path(os.environ["RELATIONSHIP_SOURCE_RELEASE_STORE"])
            if path is None and os.environ.get("RELATIONSHIP_SOURCE_RELEASE_STORE")
            else None
        )
        if selected_store:
            if any(
                (path, mysql_url, graph_manifest, graph_engine, source_manifest, source_mysql_url)
            ) or any(
                os.environ.get(name)
                for name in (
                    "RELATIONSHIP_SOURCE_API_MANIFEST",
                    "RELATIONSHIP_SOURCE_API_MYSQL_URL",
                    "RELATIONSHIP_MYSQL_URL",
                    "RELATIONSHIP_NEBULA_MANIFEST",
                    "RELATIONSHIP_GRAPH_ENGINE",
                    "RELATIONSHIP_DATABASE",
                )
            ):
                raise ValueError("激活目录模式不能与其他数据源配置混用")
            pin = load_active(selected_store)
            async with _source_lifespan(
                app, pin.bundle.directory / "manifest.json", pin.bundle.mysql_url, pin.check
            ):
                yield
            return
        selected_source = source_manifest or (
            Path(os.environ["RELATIONSHIP_SOURCE_API_MANIFEST"])
            if path is None and os.environ.get("RELATIONSHIP_SOURCE_API_MANIFEST")
            else None
        )
        if not selected_source and (
            source_mysql_url
            or (path is None and os.environ.get("RELATIONSHIP_SOURCE_API_MYSQL_URL"))
        ):
            raise ValueError("原表模式缺少 RELATIONSHIP_SOURCE_API_MANIFEST，不能回退旧演示库")
        if selected_source:
            if (
                path
                or mysql_url
                or graph_manifest
                or graph_engine
                or os.environ.get("RELATIONSHIP_MYSQL_URL")
                or os.environ.get("RELATIONSHIP_NEBULA_MANIFEST")
                or os.environ.get("RELATIONSHIP_GRAPH_ENGINE")
                or os.environ.get("RELATIONSHIP_DATABASE")
            ):
                raise ValueError("原表模式与旧演示 SQL／图配置不能混用，请清除旧配置")
            value = source_mysql_url or os.environ.get("RELATIONSHIP_SOURCE_API_MYSQL_URL")
            if not value:
                raise ValueError("原表模式需要 RELATIONSHIP_SOURCE_API_MYSQL_URL")
            async with _source_lifespan(app, selected_source, value):
                yield
            return
        selected_mysql = mysql_url or (
            os.environ.get("RELATIONSHIP_MYSQL_URL") if path is None else None
        )
        if selected_mysql:
            engine = open_mysql_engine(selected_mysql)
        else:
            selected = path or database_path()
            if not selected.is_file():
                raise RuntimeError(
                    "模拟数据库尚未初始化，请先运行 python -m relationship_query.cli init"
                )
            engine = open_engine(selected)
        try:
            app.state.query_service = QueryService(SQLRepository(engine))
            repository = app.state.query_service.repository
            paths: PathRepository = (
                MySQLPathRepository(engine, repository.version, repository.reference_month)
                if selected_mysql
                else SQLitePathRepository(engine, repository.version, repository.reference_month)
            )
            selected_graph = graph_manifest or (
                Path(os.environ["RELATIONSHIP_NEBULA_MANIFEST"])
                if path is None and os.environ.get("RELATIONSHIP_NEBULA_MANIFEST")
                else None
            )
            if selected_graph:
                graph = GraphPathRepository(paths, engine, selected_graph)
                app.state.graph_client = graph.client
                mode = graph_engine or os.environ.get("RELATIONSHIP_GRAPH_ENGINE", "paths")
                if mode == "paths":
                    app.state.path_service = GraphPathService(
                        graph,
                        app.state.query_service,
                        projection_id=graph.manifest.projection_id,
                    )
                elif mode == "candidates":
                    app.state.path_service = PathService(
                        graph,
                        app.state.query_service,
                        query_backend="nebula_sql",
                        projection_id=graph.manifest.projection_id,
                    )
                else:
                    raise ValueError("RELATIONSHIP_GRAPH_ENGINE 必须为 paths 或 candidates")
            else:
                app.state.path_service = PathService(paths, app.state.query_service)
            yield
        finally:
            _close_graph_client(app)
            engine.dispose()

    app = FastAPI(
        title="人物关系查询原型",
        version="0.1.0",
        lifespan=lifespan,
        description="仅供本地虚构数据验证。接口不代表生产字段契约。",
        responses={
            404: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    app.include_router(router)
    _install_handlers(app)
    return app


@asynccontextmanager
async def _numeric_lifespan(app: FastAPI, directory: Path) -> AsyncIterator[None]:
    from relationship_query.infrastructure.numeric_api import NumericRepository
    from relationship_query.services.materialized_query import MaterializedQueryService

    source: NumericRepository
    people_engine = None
    if (directory / "manifest.json").is_file():
        from relationship_query.infrastructure.real_api import RealGraphRepository

        configured_people = os.environ.get("RELATIONSHIP_MYSQL_SOURCE_CONFIG")
        if configured_people:
            from relationship_query.infrastructure.live_people import (
                LiveRealGraphRepository,
                MySQLPeople,
                open_people_engine,
            )
            from relationship_query.update.source_config import MySQLSourceConfig

            config = MySQLSourceConfig.read(Path(configured_people))
            people_engine = open_people_engine(
                config, os.environ.get("RELATIONSHIP_MYSQL_INSECURE_TLS") == "1"
            )
            try:
                source = LiveRealGraphRepository(directory, MySQLPeople(people_engine))
                source.people.check(config, source.real_build.sources[1])
            except Exception:
                people_engine.dispose()
                if "source" in locals():
                    source.engine.dispose()
                raise
        else:
            source = RealGraphRepository(directory)
            if source.real_build.person_display == "mysql-live":
                source.engine.dispose()
                raise ValueError("此关系发布要求配置在线MySQL人物来源")
    else:
        source = NumericRepository(directory)
    try:
        graph = source.graph_repository()
        app.state.graph_client = graph.client
        app.state.query_service = MaterializedQueryService(source, graph)
        app.state.source_guard = source
        app.state.path_service = GraphPathService(
            graph,
            app.state.query_service,
            projection_id=source.manifest.projection_id,
        )
        yield
    finally:
        _close_graph_client(app)
        source.engine.dispose()
        if people_engine is not None:
            people_engine.dispose()


def _close_graph_client(app: FastAPI) -> None:
    client = getattr(app.state, "graph_client", None)
    if client is not None:
        client.close()
        app.state.graph_client = None


def _error(request: Request, code: str, message: str, status: int) -> JSONResponse:
    query = getattr(request.app.state, "query_service", None)
    version = query.repository.version if query else None
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            code=code,
            message=message,
            data_version=version,
            data_mode=query.metadata()["data_mode"] if query else "mock",
        ).model_dump(),
    )


def _install_handlers(app: FastAPI) -> None:
    @app.exception_handler(QueryError)
    async def query_error(request: Request, exc: QueryError) -> JSONResponse:
        return _error(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = ".".join(str(x) for x in first["loc"])
        return _error(request, "INVALID_INPUT", f"{field}: {first['msg']}", 422)

    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("query storage failure", exc_info=exc)
        return _error(request, "STORAGE_UNAVAILABLE", "查询存储暂不可用，请稍后重试", 503)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected query failure", exc_info=exc)
        return _error(request, "INTERNAL_ERROR", "查询服务发生异常，请稍后重试", 500)

    @app.middleware("http")
    async def request_metrics(request: Request, call_next: object) -> Response:
        started = perf_counter()
        request_id = uuid4().hex
        guard = getattr(request.app.state, "source_guard", None)
        try:
            if guard:
                await run_in_threadpool(guard.verify_snapshot)
            response = await call_next(request)  # type: ignore[operator]
            if guard:
                await run_in_threadpool(guard.verify_snapshot)
        except QueryError as exc:
            response = _error(request, exc.code, exc.message, exc.status)
        except SQLAlchemyError as exc:
            logger.exception("source snapshot verification failure", exc_info=exc)
            response = _error(request, "STORAGE_UNAVAILABLE", "原表查询存储暂不可用", 503)
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.1f}"
        return response


app = create_app()
