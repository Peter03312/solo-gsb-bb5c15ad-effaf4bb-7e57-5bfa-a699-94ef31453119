"""Pydantic 请求/响应模型。

非正数、空索引等非法输入在此层直接拒绝（HTTP 422），不进入业务逻辑。
"""
import re
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_INDEX_RE = re.compile(r"^[ACGTNacgtn]+(?:[-\s][ACGTNacgtn]+)*$")


def _normalize_index(v: str) -> str:
    """归一化索引序列：去首尾空白、转大写、内部空白段统一为单个空格。"""
    if not isinstance(v, str):
        raise ValueError("索引序列必须是字符串")
    s = v.strip().upper()
    s = re.sub(r"[\s]+", " ", s)
    if not _INDEX_RE.match(s):
        raise ValueError(
            "索引序列只能由 A/C/G/T/N 碱基组成（双索引可用 '-' 或空格分隔）"
        )
    return s


class SampleCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, description="样本编号")
    concentration: Decimal = Field(..., description="浓度，必须为正数")
    available_volume: Decimal = Field(..., description="可用体积，必须为正数")
    target_dose: Decimal = Field(..., description="目标投料量，必须为正数")
    index_sequence: str = Field(..., min_length=1, description="索引序列")

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("样本编号不能为空")
        return v

    @field_validator("concentration", "available_volume", "target_dose")
    @classmethod
    def _positive(cls, v: Decimal):
        if v is None or not v.is_finite() or v <= 0:
            raise ValueError("必须为正数")
        return v

    @field_validator("index_sequence")
    @classmethod
    def _index(cls, v: str) -> str:
        return _normalize_index(v)


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    available_pools: int = Field(..., ge=1, description="可用池数，必须为正整数")
    pool_capacity: Decimal = Field(..., description="单池体积上限，必须为正数")
    min_pipette_volume: Decimal = Field(..., description="移液量下限，必须为正数")
    samples: list[SampleCreate] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("计划名称不能为空")
        return v

    @field_validator("pool_capacity", "min_pipette_volume")
    @classmethod
    def _positive(cls, v: Decimal):
        if v is None or not v.is_finite() or v <= 0:
            raise ValueError("必须为正数")
        return v

    @field_validator("samples")
    @classmethod
    def _unique_codes(cls, v: list[SampleCreate]):
        codes = [s.code for s in v]
        dup = {c for c in codes if codes.count(c) > 1}
        if dup:
            raise ValueError(f"样本编号重复：{', '.join(sorted(dup))}")
        return v


class SamplesAdd(BaseModel):
    samples: list[SampleCreate] = Field(..., min_length=1)

    @field_validator("samples")
    @classmethod
    def _unique_codes(cls, v: list[SampleCreate]):
        codes = [s.code for s in v]
        dup = {c for c in codes if codes.count(c) > 1}
        if dup:
            raise ValueError(f"样本编号重复：{', '.join(sorted(dup))}")
        return v


class RemeasureItem(BaseModel):
    sample_id: int
    concentration: Decimal
    available_volume: Optional[Decimal] = Field(
        default=None, description="可选：复测同时更新可用体积，必须为正数"
    )

    @field_validator("concentration")
    @classmethod
    def _conc_positive(cls, v: Decimal):
        if v is None or not v.is_finite() or v <= 0:
            raise ValueError("复测浓度必须为正数")
        return v

    @field_validator("available_volume")
    @classmethod
    def _vol_positive(cls, v):
        if v is None:
            return v
        if not v.is_finite() or v <= 0:
            raise ValueError("可用体积必须为正数")
        return v


class RemeasureRequest(BaseModel):
    updates: list[RemeasureItem] = Field(..., min_length=1)

    @field_validator("updates")
    @classmethod
    def _unique(cls, v: list[RemeasureItem]):
        ids = [u.sample_id for u in v]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError("同一批次中样本不能重复提交")
        return v


# ---------- 响应 ----------

class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    concentration: Decimal
    available_volume: Decimal
    target_dose: Decimal
    index_sequence: str


class AssignmentOut(BaseModel):
    sample_id: int
    code: str
    index_sequence: str
    concentration: Decimal
    target_dose: Decimal
    available_volume: Decimal
    take_volume: Optional[Decimal] = None
    status: Literal["arranged", "unarranged"]
    reason: Optional[str] = None


class PoolOut(BaseModel):
    pool_id: int
    position: int
    locked: bool
    version_no: int
    total_volume: Decimal
    warnings: list[str] = []
    assignments: list[AssignmentOut]


class VersionBrief(BaseModel):
    version_no: int
    trigger: str
    note: Optional[str] = None
    created_at: str
    pool_count: int
    arranged_count: int
    proven_optimal: bool = True


class ExperimentDetail(BaseModel):
    id: int
    name: str
    available_pools: int
    pool_capacity: Decimal
    min_pipette_volume: Decimal
    created_at: str
    samples: list[SampleOut]
    pools: list[PoolOut]
    unarranged: list[AssignmentOut]
    versions: list[VersionBrief]
    current_version: int


class ExperimentSummary(BaseModel):
    id: int
    name: str
    available_pools: int
    created_at: str
    current_version: int
    pool_count: int
    arranged_count: int
    total_samples: int
