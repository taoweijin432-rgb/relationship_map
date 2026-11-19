"""同版冻结事实的静态成员CSR；收据与完整发布绑定，损坏时拒绝载入。"""

import json
import mmap
import re
import struct
import sys
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from relationship_query.update.artifacts import checksum, write_json
from relationship_query.update.models import GraphReceipt, Projection, UpdateModel

MAX_INDEX_BYTES = 64 * 1024 * 1024
FILES = {
    "people.json",
    "entities.json",
    "person-offsets.u64",
    "person-entities.u32",
    "entity-offsets.u64",
    "entity-people.u32",
}


class QueryIndexReceipt(UpdateModel):
    format: Literal["member-index-v1"] = "member-index-v1"
    path: Literal["member-index"] = "member-index"
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class IndexBinding(UpdateModel):
    version: str
    source_digest: str
    reference_month: int
    graph: GraphReceipt
    sql_sha256: str
    graph_plan_sha256: str


class IndexFile(UpdateModel):
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class IndexManifest(UpdateModel):
    format: Literal["member-index-v1"] = "member-index-v1"
    algorithm: Literal["person-layer-prefix-bfs-v1"] = "person-layer-prefix-bfs-v1"
    support: Literal["static-all-shared-v1"] = "static-all-shared-v1"
    byte_order: Literal["little"] = "little"
    people: int = Field(ge=0, lt=2**32)
    entities: int = Field(ge=0, lt=2**32)
    memberships: int = Field(ge=0)
    binding: IndexBinding
    files: dict[str, IndexFile]


def index_binding(
    release: Path, version: str, source_digest: str, reference_month: int, graph: GraphReceipt
) -> IndexBinding:
    return IndexBinding(
        version=version,
        source_digest=source_digest,
        reference_month=reference_month,
        graph=graph,
        sql_sha256=checksum(release / "source.sqlite"),
        graph_plan_sha256=checksum(release / "graph-plan.json"),
    )


def _write_array(path: Path, values: array) -> None:
    if sys.byteorder != "little":
        values.byteswap()
    with path.open("xb") as stream:
        path.chmod(0o600)
        values.tofile(stream)


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("成员索引人物或实体身份必须为字符串")
    return value


def _write_csr(directory: Path, prefix: str, count: int, pairs: list[tuple[int, int]]) -> None:
    offsets, values = array("Q", [0]), array("I")
    position = 0
    for owner in range(count):
        while position < len(pairs) and pairs[position][0] == owner:
            values.append(pairs[position][1])
            position += 1
        offsets.append(len(values))
    assert position == len(pairs)
    target = "person-entities.u32" if prefix == "person" else "entity-people.u32"
    _write_array(directory / f"{prefix}-offsets.u64", offsets)
    _write_array(directory / target, values)


def build_member_index(
    release: Path,
    projection: Projection,
    binding: IndexBinding,
    *,
    maximum_bytes: int = MAX_INDEX_BYTES,
) -> QueryIndexReceipt:
    """只写新候选；调用方必须继续完成原图构建和全量核验。"""
    directory = release / "member-index"
    directory.mkdir(mode=0o700, exist_ok=False)
    people = sorted(_identity(node["vid"]) for node in projection.nodes if node["type"] == "person")
    memberships = {
        (_identity(edge["source"]), _identity(edge["target"]))
        for edge in projection.facts
        if edge["type"] in {"worked_at", "studied_at", "studied_major"}
    }
    entities = sorted({entity for _, entity in memberships})
    if max(len(people), len(entities)) >= 2**32:
        raise ValueError("成员索引字典超过uint32范围")
    # 提前拒绝明显超限的候选，最终仍以所有实际文件大小为准。
    minimum = (len(people) + len(entities) + 2) * 8 + len(memberships) * 8
    if minimum > maximum_bytes:
        raise ValueError("成员索引工件超过容量边界")
    people_map = {key: i for i, key in enumerate(people)}
    entities_map = {key: i for i, key in enumerate(entities)}
    pairs = sorted((people_map[p], entities_map[e]) for p, e in memberships)
    write_json(directory / "people.json", people)
    write_json(directory / "entities.json", entities)
    _write_csr(directory, "person", len(people), pairs)
    _write_csr(directory, "entity", len(entities), sorted((e, p) for p, e in pairs))
    manifest = IndexManifest(
        people=len(people),
        entities=len(entities),
        memberships=len(pairs),
        binding=binding,
        files={
            name: IndexFile(
                size=(directory / name).stat().st_size, sha256=checksum(directory / name)
            )
            for name in sorted(FILES)
        },
    )
    write_json(directory / "manifest.json", manifest.model_dump(mode="json"))
    receipt = QueryIndexReceipt(manifest_sha256=checksum(directory / "manifest.json"))
    with MemberIndex(release, receipt, binding, maximum_bytes=maximum_bytes):
        pass
    return receipt


@dataclass
class MappedIntegers:
    mapping: mmap.mmap | None
    decoder: struct.Struct
    count: int

    @classmethod
    def open(cls, path: Path, code: str) -> "MappedIntegers":
        decoder = struct.Struct("<" + code)
        size = path.stat().st_size
        if size % decoder.size:
            raise ValueError("成员索引数组长度异常")
        with path.open("rb") as stream:
            mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) if size else None
        return cls(mapping, decoder, size // decoder.size)

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> int:
        if not 0 <= index < self.count or self.mapping is None:
            raise IndexError(index)
        return self.decoder.unpack_from(self.mapping, index * self.decoder.size)[0]

    def close(self) -> None:
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None


class MemberIndex:
    def __init__(
        self,
        release: Path,
        receipt: QueryIndexReceipt,
        binding: IndexBinding,
        *,
        maximum_bytes: int = MAX_INDEX_BYTES,
    ) -> None:
        self.arrays: list[MappedIntegers] = []
        self.closed = False
        directory = release / receipt.path
        try:
            self._check_files(directory, receipt, binding, maximum_bytes)
            self.people = self._dictionary(directory / "people.json", r"p:(expert|resume):[0-9]+")
            self.entities = self._dictionary(
                directory / "entities.json", r"e:(company|school|major):[0-9]+"
            )
            self.person_offsets = self._map(directory / "person-offsets.u64", "Q")
            self.person_entities = self._map(directory / "person-entities.u32", "I")
            self.entity_offsets = self._map(directory / "entity-offsets.u64", "Q")
            self.entity_people = self._map(directory / "entity-people.u32", "I")
            self._validate_csr()
            if self._file_stats != self._stats(directory):
                raise ValueError("成员索引在启动核验期间发生变化")
        except BaseException:
            self.close()
            raise

    def _check_files(
        self, directory: Path, receipt: QueryIndexReceipt, binding: IndexBinding, maximum: int
    ) -> None:
        if directory.is_symlink() or set(p.name for p in directory.iterdir()) != FILES | {
            "manifest.json"
        }:
            raise ValueError("成员索引工件集合异常")
        paths = [directory / name for name in FILES | {"manifest.json"}]
        self._file_stats = self._stats(directory)
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise ValueError("成员索引不允许链接或非普通文件")
        if sum(p.stat().st_size for p in paths) > maximum:
            raise ValueError("成员索引工件超过容量边界")
        if checksum(directory / "manifest.json") != receipt.manifest_sha256:
            raise ValueError("成员索引清单摘要不符")
        self.manifest = IndexManifest.model_validate_json((directory / "manifest.json").read_text())
        if self.manifest.binding != binding or set(self.manifest.files) != FILES:
            raise ValueError("成员索引与完整发布身份不符")
        for name, expected in self.manifest.files.items():
            path = directory / name
            if path.stat().st_size != expected.size or checksum(path) != expected.sha256:
                raise ValueError("成员索引分片大小或摘要不符")

    @staticmethod
    def _stats(directory: Path) -> dict[str, tuple[int, int, int, int, int]]:
        return {
            path.name: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            for path in (directory, *(directory / name for name in FILES | {"manifest.json"}))
            for s in (path.stat(),)
        }

    @staticmethod
    def _dictionary(path: Path, pattern: str) -> tuple[str, ...]:
        values = json.loads(path.read_text())
        if (
            not isinstance(values, list)
            or any(
                not isinstance(v, str)
                or not re.fullmatch(pattern, v)
                or len(v.rsplit(":", 1)[-1]) > 19
                or not 0 < int(v.rsplit(":", 1)[-1]) < 2**63
                for v in values
            )
            or values != sorted(set(values))
        ):
            raise ValueError("成员索引字典身份、排序或唯一性异常")
        return tuple(values)

    def _map(self, path: Path, code: str) -> MappedIntegers:
        result = MappedIntegers.open(path, code)
        self.arrays.append(result)
        return result

    @staticmethod
    def _validate_rows(
        offsets: MappedIntegers, values: MappedIntegers, rows: int, bound: int
    ) -> None:
        if len(offsets) != rows + 1 or offsets[0] != 0 or offsets[rows] != len(values):
            raise ValueError("成员索引CSR偏移或数量异常")
        for owner in range(rows):
            lo, hi = offsets[owner], offsets[owner + 1]
            if not 0 <= lo <= hi <= len(values):
                raise ValueError("成员索引CSR偏移越界")
            previous = -1
            for at in range(lo, hi):
                value = values[at]
                if not previous < value < bound:
                    raise ValueError("成员索引CSR数值、排序或唯一性异常")
                previous = value

    def _validate_csr(self) -> None:
        n, m, count = self.manifest.people, self.manifest.entities, self.manifest.memberships
        if (len(self.people), len(self.entities)) != (n, m):
            raise ValueError("成员索引字典数量异常")
        if len(self.person_entities) != count or len(self.entity_people) != count:
            raise ValueError("成员索引归属数量异常")
        self._validate_rows(self.person_offsets, self.person_entities, n, m)
        self._validate_rows(self.entity_offsets, self.entity_people, m, n)
        for person in range(n):
            for at in range(self.person_offsets[person], self.person_offsets[person + 1]):
                entity = self.person_entities[at]
                lo, hi = self.entity_offsets[entity], self.entity_offsets[entity + 1]
                position = bisect_left(self.entity_people, person, lo, hi)
                if position == hi or self.entity_people[position] != person:
                    raise ValueError("成员索引两向CSR不一致")

    def close(self) -> None:
        for mapped in self.arrays:
            mapped.close()
        self.closed = True

    def __enter__(self) -> "MemberIndex":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
