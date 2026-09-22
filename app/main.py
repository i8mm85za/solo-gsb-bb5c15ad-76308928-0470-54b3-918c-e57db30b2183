"""FastAPI application: create / align / query beat-alignment jobs."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from . import database as db
from . import service
from .schemas import AlignRequest, JobCreate, JobOut, JobSummary


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(
    title="多轨录音节拍对齐 API",
    description=(
        "提交参考节拍网格与演奏轨音符起始时间，服务端使用带宽约束的动态时间规整"
        "（Sakoe-Chiba Band DTW）处理漏拍、抢拍与插入拍，回溯生成一一对应映射"
        "及连续偏差区间。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED,
          tags=["jobs"], summary="创建对齐任务")
def create_job(payload: JobCreate):
    with db.get_conn() as conn:
        return service.create_job(conn, payload)


@app.post("/jobs/{job_id}/align", response_model=JobOut, tags=["jobs"],
          summary="执行节拍对齐（可覆盖参数）")
async def align_job(job_id: str, payload: AlignRequest | None = None):
    overrides = payload.model_dump(exclude_none=True) if payload else {}

    def _work() -> JobOut:
        with db.get_conn() as conn:
            try:
                return service.run_alignment(conn, job_id, overrides)
            except KeyError:
                raise HTTPException(status_code=404, detail="job not found")

    return await run_in_threadpool(_work)


@app.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"],
         summary="查询任务与对齐结果")
def get_job(job_id: str):
    with db.get_conn() as conn:
        job = service.get_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/jobs", response_model=list[JobSummary], tags=["jobs"],
         summary="列出全部任务")
def list_jobs(limit: int = Query(default=100, ge=1, le=500)):
    with db.get_conn() as conn:
        return service.list_jobs(conn, limit)


@app.get("/health", tags=["meta"], summary="健康检查")
def health():
    return {"status": "ok"}
