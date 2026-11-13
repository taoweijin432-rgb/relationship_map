from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "test.sqlite"
    engine = open_engine(path)
    load_dataset(engine, make_dataset())
    engine.dispose()
    with TestClient(create_app(path)) as instance:
        yield instance
