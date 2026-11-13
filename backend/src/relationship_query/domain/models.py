from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Source = Literal["expert", "resume"]
EntityType = Literal["organization", "school", "major", "role"]
RelationType = Literal["same_company", "same_company_overlap", "same_school", "same_major"]


def validate_month(value: int) -> int:
    if not 190001 <= value <= 210012 or not 1 <= value % 100 <= 12:
        raise ValueError("月份必须为有效的 YYYYMM，年份范围 1900–2100")
    return value


Month = Annotated[int, AfterValidator(validate_month)]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Person(DomainModel):
    id: str
    name: str
    city: str
    headline: str
    sources: list[Source]
    active: bool = True
    serial_number: str | None = None


class Entity(DomainModel):
    id: str
    type: EntityType
    name: str
    aliases: list[str] = Field(default_factory=list)


class Fact(DomainModel):
    id: str
    person_id: str
    type: Literal["employment", "education", "major"]
    entity_id: str
    role_id: str | None = None
    start_month: Month | None = None
    end_month: Month | None = None
    is_current: bool = False
    active: bool = True
    source_system: Source
    source_record_id: str
    experience_key: str | None = None
    position_title: str | None = None
    education_level: str | None = None
    is_regular_enrollment: str | None = None

    @model_validator(mode="after")
    def check_interval(self) -> "Fact":
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("经历开始月份晚于结束月份")
        if self.is_current and self.end_month is not None:
            raise ValueError("当前任职经历不能同时提供结束月份")
        return self


class Dataset(DomainModel):
    version: str
    reference_month: Month
    people: list[Person]
    entities: list[Entity]
    facts: list[Fact]
