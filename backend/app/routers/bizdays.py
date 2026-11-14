from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import pipeline

router = APIRouter(tags=["业务日关闭"])


class CloseBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")
    biz_day: str = Field(..., description="业务日，格式 YYYY-MM-DD")
    reason: str = Field(default="", description="关闭原因")


class BizDayBody(BaseModel):
    domain_id: int = Field(..., description="主题域编号")
    biz_day: str | None = Field(default=None, description="业务日，格式 YYYY-MM-DD；缺省为全部业务日")


@router.get("/closed-days")
def list_closed(domain_id: int | None = Query(default=None)):
    return pipeline.list_closed_biz_days(domain_id)


@router.get("/biz-days/overview")
def overview(domain_id: int = Query(..., description="主题域编号")):
    try:
        return pipeline.biz_day_overview(domain_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/closed-days/close")
def close_day(body: CloseBody):
    try:
        return pipeline.close_biz_day(body.domain_id, body.biz_day, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/closed-days/reopen")
def reopen_day(body: CloseBody):
    try:
        pipeline.reopen_biz_day(body.domain_id, body.biz_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"已重新打开": True, "domain_id": body.domain_id, "biz_day": body.biz_day}


@router.post("/paste/load")
def load_paste(body: BizDayBody):
    try:
        return pipeline.load_paste_fixture(body.domain_id, body.biz_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
