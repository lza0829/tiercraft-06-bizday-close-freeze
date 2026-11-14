from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["分层任务"])


class JobBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")
    biz_day: str | None = Field(default=None, description="定点重算的业务日；缺省为主题域全量重跑")


def _run(callable_step, body: JobBody):
    try:
        return callable_step(body.domain_id, body.biz_day)
    except pipeline.RejectError as exc:
        # 拒绝已落 layer_jobs；400 同时回传任务记录，前端可直接刷新任务列表
        raise HTTPException(
            status_code=400,
            detail={"原因": str(exc), "任务": exc.job},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
def list_jobs(domain_id: int | None = None):
    return pipeline.list_jobs(domain_id)


@router.post("/jobs/paste-to-detail")
def paste_to_detail(body: JobBody):
    return _run(pipeline.run_paste_to_detail, body)


@router.post("/jobs/detail-to-summary")
def detail_to_summary(body: JobBody):
    return _run(pipeline.run_detail_to_summary, body)
