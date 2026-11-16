"""详情装配内复用人物读取，返回前重新读取并确认展示快照仍有效。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from relationship_query.domain.models import Person

FetchPeople = Callable[[list[str]], dict[str, Person]]


class PersonReadChanged(Exception):
    pass


@dataclass
class PersonReads:
    people: dict[object, dict[str, Person | None]] = field(default_factory=dict)
    fetchers: dict[object, FetchPeople] = field(default_factory=dict)

    def read(self, namespace: object, ids: list[str], fetch: FetchPeople) -> dict[str, Person]:
        if not ids:
            return {}
        known = self.people.setdefault(namespace, {})
        missing = sorted(set(ids) - known.keys())
        if missing:
            found = fetch(missing)
            known.update((key, found.get(key)) for key in missing)
            self.fetchers[namespace] = fetch
        return {key: person for key in ids if (person := known[key]) is not None}

    def verify(self) -> None:
        for namespace, expected in self.people.items():
            current = self.fetchers[namespace](sorted(expected))
            if any(current.get(key) != person for key, person in expected.items()):
                raise PersonReadChanged


_current: ContextVar[PersonReads | None] = ContextVar("detail_person_reads", default=None)


def current_person_reads() -> PersonReads | None:
    return _current.get()


@contextmanager
def person_reads() -> Iterator[PersonReads]:
    reads = PersonReads()
    token = _current.set(reads)
    try:
        yield reads
    finally:
        _current.reset(token)
