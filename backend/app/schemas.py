from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_mode: Literal["intersection", "union"] = "intersection"
    department_ids: list[str] = Field(default_factory=list, max_length=2000)
    levels: list[list[str]] = Field(default_factory=lambda: [[], [], []], min_length=3, max_length=3)
    mode: Literal["all", "selected"] = "selected"
    person_ids: list[str] = Field(default_factory=list, max_length=2000)
    extra_ids: list[str] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def validate_matching(self):
        if self.match_mode == "union" and any(self.levels):
            raise ValueError("组合名单不能同时使用旧版部门交集条件")
        if self.match_mode == "intersection" and self.department_ids:
            raise ValueError("部门组合须使用并集匹配方式")
        return self


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_ids: list[str] = Field(min_length=1, max_length=500)
    operation: Literal["plus", "minus"]
    points: StrictInt = Field(gt=0, le=2_000_000_000)
    reason: str = Field(min_length=1, max_length=2000)
    overrides: dict[str, StrictInt] = Field(default_factory=dict)
    recipients: Selection

    @model_validator(mode="after")
    def normalize(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("原因不能为空")
        self.person_ids = sorted(set(self.person_ids))
        if not set(self.overrides).issubset(self.person_ids):
            raise ValueError("总分覆盖只能用于本次记分对象")
        if any(abs(v) > 2_000_000_000 for v in self.overrides.values()):
            raise ValueError("总分超出整数存储范围")
        return self


class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_token: str
    idempotency_key: str = Field(min_length=16, max_length=100)


class PresetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["personal", "public"] = "personal"
    selection: Selection


class RoleRequest(BaseModel):
    role: Literal["admin", "operator", "none"]


class SyncScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    interval_days: StrictInt = Field(ge=1, le=365)
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
