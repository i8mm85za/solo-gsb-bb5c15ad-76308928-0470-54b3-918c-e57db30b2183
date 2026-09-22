"""Run an alignment job and map DB rows to API models."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from . import database as db
from .dtw import AlignmentError, align_beats
from .schemas import (
    AlignmentStats,
    DeviationIntervalOut,
    JobCreate,
    JobOut,
    JobSummary,
    MatchPairOut,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_job(conn: sqlite3.Connection, payload: JobCreate) -> JobOut:
    job_id = uuid4().hex
    params = {
        "band": payload.band,
        "gap_penalty_ms": payload.gap_penalty_ms,
        "deviation_threshold_ms": payload.deviation_threshold_ms,
    }
    conn.execute(
        """INSERT INTO jobs
           (id, name, reference_beats_ms, onset_times_ms, status, params, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
        (
            job_id,
            payload.name,
            db.dumps(payload.reference_beats_ms),
            db.dumps(payload.onset_times_ms),
            db.dumps(params),
            _now(),
        ),
    )
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row)


def run_alignment(
    conn: sqlite3.Connection,
    job_id: str,
    overrides: dict | None = None,
) -> JobOut:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)

    params = db.loads(row["params"])
    if overrides:
        params = {**params, **{k: v for k, v in overrides.items() if v is not None}}

    ref = db.loads(row["reference_beats_ms"])
    ons = db.loads(row["onset_times_ms"])

    try:
        result = align_beats(
            ref,
            ons,
            band=params["band"],
            gap_penalty_ms=params["gap_penalty_ms"],
            deviation_threshold_ms=params["deviation_threshold_ms"],
        )
    except AlignmentError as exc:
        conn.execute(
            "UPDATE jobs SET status='failed', error=? WHERE id=?",
            (str(exc), job_id),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_job(row)

    pairs = [
        {
            "ref_index": p.ref_index,
            "onset_index": p.onset_index,
            "ref_time_ms": p.ref_time,
            "onset_time_ms": p.onset_time,
            "deviation_ms": p.deviation_ms,
            "kind": p.kind,
        }
        for p in result.pairs
    ]
    intervals = [
        {
            "kind": iv.kind,
            "ref_start_index": iv.ref_start_index,
            "ref_end_index": iv.ref_end_index,
            "start_time_ms": iv.start_time_ms,
            "end_time_ms": iv.end_time_ms,
            "mean_deviation_ms": iv.mean_deviation_ms,
            "min_deviation_ms": iv.min_deviation_ms,
            "max_deviation_ms": iv.max_deviation_ms,
            "std_deviation_ms": iv.std_deviation_ms,
            "beat_count": iv.beat_count,
        }
        for iv in result.intervals
    ]
    stats = {
        "matched_beats": result.matched_beats,
        "missing_beats": result.missing_beats,
        "inserted_beats": result.inserted_beats,
        "mean_deviation_ms": result.mean_deviation_ms,
        "std_deviation_ms": result.std_deviation_ms,
        "total_cost": result.total_cost,
        "band": result.band,
        "gap_penalty_ms": result.gap_penalty_ms,
        "deviation_threshold_ms": params["deviation_threshold_ms"],
    }

    conn.execute(
        """UPDATE jobs
           SET status='aligned', error=NULL, params=?, pairs=?, intervals=?,
               stats=?, aligned_at=?
           WHERE id=?""",
        (
            db.dumps(params),
            db.dumps(pairs),
            db.dumps(intervals),
            db.dumps(stats),
            _now(),
            job_id,
        ),
    )
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row)


def get_job(conn: sqlite3.Connection, job_id: str) -> JobOut | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row_to_job(row) if row is not None else None


def list_jobs(conn: sqlite3.Connection, limit: int = 100) -> list[JobSummary]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        JobSummary(
            id=r["id"],
            name=r["name"],
            status=r["status"],
            created_at=r["created_at"],
            aligned_at=r["aligned_at"],
        )
        for r in rows
    ]


def row_to_job(row: sqlite3.Row) -> JobOut:
    return JobOut(
        id=row["id"],
        name=row["name"],
        reference_beats_ms=db.loads(row["reference_beats_ms"]),
        onset_times_ms=db.loads(row["onset_times_ms"]),
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
        aligned_at=row["aligned_at"],
        params=db.loads(row["params"]),
        pairs=[MatchPairOut(**p) for p in db.loads(row["pairs"], [])]
        if row["pairs"]
        else None,
        intervals=[DeviationIntervalOut(**i) for i in db.loads(row["intervals"], [])]
        if row["intervals"]
        else None,
        stats=AlignmentStats(**db.loads(row["stats"])) if row["stats"] else None,
    )
