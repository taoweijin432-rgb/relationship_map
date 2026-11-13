"""真实MySQL读取角色与物理连接配置，供双库和合库环境共用。"""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from relationship_query.update.models import UpdateModel


class MySQLReadEndpoint(UpdateModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    user: str = Field(min_length=1, max_length=128)
    password_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    tls_ca_file: str | None = Field(default=None, min_length=1)


class MySQLSourceConfig(UpdateModel):
    format: Literal["real-mysql-source-config-v1"] = "real-mysql-source-config-v1"
    connections: dict[str, MySQLReadEndpoint] = Field(min_length=1)
    entity_source: str = Field(min_length=1)
    person_source: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_sources(self) -> "MySQLSourceConfig":
        if not {self.entity_source, self.person_source}.issubset(self.connections):
            raise ValueError("实体及人物角色须引用已配置连接")
        return self

    def endpoint(self, role: Literal["entities", "people"]) -> MySQLReadEndpoint:
        name = self.entity_source if role == "entities" else self.person_source
        return self.connections[name]

    @classmethod
    def read(cls, path: Path) -> "MySQLSourceConfig":
        config = cls.model_validate_json(path.read_text())
        # 证书路径相对于配置文件，确保从不同工作目录运行结果一致。
        connections = {}
        for name, endpoint in config.connections.items():
            if endpoint.tls_ca_file is not None:
                certificate = (path.resolve().parent / endpoint.tls_ca_file).resolve()
                endpoint = endpoint.model_copy(update={"tls_ca_file": str(certificate)})
            connections[name] = endpoint
        return config.model_copy(update={"connections": connections})


def legacy_source_config(person_database: str) -> MySQLSourceConfig:
    """保持旧采集命令的已验证测试地址，显式配置入口覆盖物理来源。"""
    return MySQLSourceConfig(
        connections={
            "entity-test": MySQLReadEndpoint(
                host="47.113.185.127", database="test_derui_expert", user="test_derui_expert"
            ),
            "person-test": MySQLReadEndpoint(
                host="39.96.40.93", database=person_database, user="root"
            ),
        },
        entity_source="entity-test",
        person_source="person-test",
    )
