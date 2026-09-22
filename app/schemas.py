"""Pydantic request/response models."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class JobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    reference_beats_ms: List[float] = Field(
        ...,
        min_length=1,
        description="参考节拍网格时间（毫秒），严格递增",
    )
    onset_times_ms: List[float] = Field(
        ...,
        min_length=1,
        description="演奏轨音符起始时间（毫秒），严格递增",
    )
    band: int = Field(
        default=2, ge=1, le=100,
        description="Sakoe-Chiba 带宽（节拍索引半径）",
    )
    gap_penalty_ms: float = Field(
        default=200.0, ge=0.0,
        description="漏拍/插入拍的离对角步附加代价（毫秒）",
    )
    deviation_threshold_ms: float = Field(
        default=50.0, ge=0.0,
        description="抢拍/拖拍判定阈值（毫秒）",
    )

    @field_validator("reference_beats_ms", "onset_times_ms")
    @classmethod
    def _strictly_ascending(cls, v: List[float]) -> List[float]:
        if any(b <= a for a, b in zip(v, v[1:])):
            raise ValueError("timestamps must be strictly ascending")
        return v


class AlignRequest(BaseModel):
    band: Optional[int] = Field(default=None, ge=1, le=100)
    gap_penalty_ms: Optional[float] = Field(default=None, ge=0.0)
    deviation_threshold_ms: Optional[float] = Field(default=None, ge=0.0)


class MatchPairOut(BaseModel):
    ref_index: Optional[int]
    onset_index: Optional[int]
    ref_time_ms: Optional[float]
    onset_time_ms: Optional[float]
    deviation_ms: Optional[float]
    kind: Literal["match", "missing_beat", "inserted_beat"]


class DeviationIntervalOut(BaseModel):
    kind: Literal["rushed", "dragging", "steady"]
    ref_start_index: int
    ref_end_index: int
    start_time_ms: float
    end_time_ms: float
    mean_deviation_ms: float
    min_deviation_ms: float
    max_deviation_ms: float
    std_deviation_ms: float
    beat_count: int


class AlignmentStats(BaseModel):
    matched_beats: int
    missing_beats: int
    inserted_beats: int
    mean_deviation_ms: float
    std_deviation_ms: float
    total_cost: float
    band: int
    gap_penalty_ms: float
    deviation_threshold_ms: float


class JobOut(BaseModel):
    id: str
    name: str
    reference_beats_ms: List[float]
    onset_times_ms: List[float]
    status: Literal["pending", "aligned", "failed"]
    error: Optional[str] = None
    created_at: str
    aligned_at: Optional[str] = None
    params: dict
    pairs: Optional[List[MatchPairOut]] = None
    intervals: Optional[List[DeviationIntervalOut]] = None
    stats: Optional[AlignmentStats] = None


class JobSummary(BaseModel):
    id: str
    name: str
    status: Literal["pending", "aligned", "failed"]
    created_at: str
    aligned_at: Optional[str] = None
