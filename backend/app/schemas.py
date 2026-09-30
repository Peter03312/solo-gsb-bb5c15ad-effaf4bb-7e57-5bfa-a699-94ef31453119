"""Request / response validation models.

All physical quantities must be strictly positive; non-positive or malformed
input is rejected with HTTP 422 and never reaches the planner.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

INDEX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def _strip(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("不能为空")
    return v


def _check_index(v: str) -> str:
    v = v.strip()
    if not INDEX_RE.match(v):
        raise ValueError("索引序列仅允许字母/数字，可含 - 或 _，长度 1-64")
    return v


class BatchCreate(BaseModel):
    name: str = Field(..., max_length=100)
    num_pools: int = Field(..., gt=0)
    max_pool_volume: float = Field(..., gt=0)
    min_transfer: float = Field(..., gt=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _strip(v)


class SampleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., max_length=100)
    concentration: float = Field(..., gt=0)
    available_volume: float = Field(..., gt=0)
    target_amount: float = Field(..., gt=0)
    index_seq: str = Field(..., max_length=64)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _strip(v)

    @field_validator("index_seq")
    @classmethod
    def _index(cls, v: str) -> str:
        return _check_index(v)


class SampleBulkIn(BaseModel):
    samples: list[SampleIn]

    @field_validator("samples")
    @classmethod
    def _nonempty(cls, v: list[SampleIn]) -> list[SampleIn]:
        if not v:
            raise ValueError("至少需要一条样本")
        return v


class RemeasureIn(BaseModel):
    concentration: float = Field(..., gt=0)

    @field_validator("concentration")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("复测浓度必须为正数")
        return v
