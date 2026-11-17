"""响应大小及重复领域对象统计；只输出数量，不记录人物正文。"""

import gzip
import hashlib
import json
from collections import Counter
from typing import Any


def response_usage(body: bytes) -> dict[str, Any]:
    occurrences: dict[str, Counter[bytes]] = {
        kind: Counter() for kind in ("person", "fact", "entity")
    }

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kind = None
            if {"id", "name", "sources", "headline"} <= value.keys():
                kind = "person"
            elif {"id", "person_id", "source_system", "entity_id"} <= value.keys():
                kind = "fact"
            elif {"id", "type", "name", "aliases"} <= value.keys():
                kind = "entity"
            if kind:
                encoded = json.dumps(
                    value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
                occurrences[kind][encoded] += 1
            for item in value.values():
                visit(item)

    visit(json.loads(body))
    return {
        "body_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        # 此为离线压缩估计；不冒充HTTP实际协商／传输测量。
        "offline_gzip_level_5_bytes": len(gzip.compress(body, compresslevel=5, mtime=0)),
        "objects": {
            kind: {
                "occurrences": sum(counts.values()),
                "unique_values": len(counts),
                "duplicate_canonical_bytes": sum(
                    len(value) * (count - 1) for value, count in counts.items()
                ),
            }
            for kind, counts in occurrences.items()
        },
    }
