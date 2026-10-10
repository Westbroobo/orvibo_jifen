from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    levels: list[list[str]] = Field(default_factory=lambda: [[], [], []], min_length=3, max_length=3)
    mode: Literal["all", "selected"] = "selected"
    person_ids: list[str] = Field(default_factory=list, max_length=2000)
    extra_ids: list[str] = Field(default_factory=list, max_length=2000)


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
    name: str = Field(min_length=1, max_length=100)
    selection: Selection


class RoleRequest(BaseModel):
    role: Literal["admin", "operator", "none"]
