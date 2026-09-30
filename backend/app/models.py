"""ORM 模型。

所有数值以归一化后的字符串存储（SQLite 的 NUMERIC 亲和性会吞尾零/产生浮点显示
问题），读取后用 Decimal 计算，避免浮点误差。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Experiment(Base):
    """一次拼池计划（工作台文档）。"""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    available_pools: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_capacity: Mapped[str] = mapped_column(String(30), nullable=False)
    min_pipette_volume: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    samples: Mapped[list["Sample"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="Sample.id",
    )
    pools: Mapped[list["Pool"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="Pool.position",
    )
    versions: Mapped[list["PlanVersion"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="PlanVersion.version_no",
    )
    concentration_logs: Mapped[list["ConcentrationLog"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="ConcentrationLog.id",
    )


class Sample(Base):
    __tablename__ = "samples"
    __table_args__ = (
        UniqueConstraint("experiment_id", "code", name="uq_sample_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    concentration: Mapped[str] = mapped_column(String(30), nullable=False)
    available_volume: Mapped[str] = mapped_column(String(30), nullable=False)
    target_dose: Mapped[str] = mapped_column(String(30), nullable=False)
    index_sequence: Mapped[str] = mapped_column(String(200), nullable=False)

    experiment: Mapped["Experiment"] = relationship(back_populates="samples")
    assignments: Mapped[list["PoolAssignment"]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )


class Pool(Base):
    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 池号，从 1 开始
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 锁定后复测产生的警示 JSON 字符串列表；非锁定池为 null
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    experiment: Mapped["Experiment"] = relationship(back_populates="pools")
    assignments: Mapped[list["PoolAssignment"]] = relationship(
        back_populates="pool", cascade="all, delete-orphan", order_by="PoolAssignment.id"
    )


class PoolAssignment(Base):
    """样本当前的安排结果（也承载“未安排”状态）。

    这是“当前状态”表，不按版本留存；每次重算时：
      * 未锁定样本的记录被删除后重建；
      * 锁定池的记录原样保留 —— 锁定配方不会被改写。
    完整历史版本见 PlanVersion.snapshot_json。
    """

    __tablename__ = "pool_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    pool_id: Mapped[int | None] = mapped_column(
        ForeignKey("pools.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # arranged/unarranged
    take_volume: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    sample: Mapped["Sample"] = relationship(back_populates="assignments")
    pool: Mapped["Pool | None"] = relationship(back_populates="assignments")


class PlanVersion(Base):
    """每次（重新）计算的不可变快照，用于版本记录对比。"""

    __tablename__ = "plan_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    # create / remeasure / add_samples
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 本次解是否已由求解器证明为“样本数最多、池数最少”的最优解
    proven_optimal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    experiment: Mapped["Experiment"] = relationship(back_populates="versions")


class ConcentrationLog(Base):
    """复测浓度留痕。"""

    __tablename__ = "concentration_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False
    )
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("samples.id", ondelete="CASCADE"), nullable=False
    )
    old_concentration: Mapped[str] = mapped_column(String(30), nullable=False)
    new_concentration: Mapped[str] = mapped_column(String(30), nullable=False)
    old_available_volume: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_available_volume: Mapped[str | None] = mapped_column(String(30), nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    experiment: Mapped["Experiment"] = relationship(back_populates="concentration_logs")
