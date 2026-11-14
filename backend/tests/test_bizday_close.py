from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
FIXTURES = BACKEND.parent / "fixtures"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    # 确保以干净的模块状态启动，startup 时建库并播种
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _domain_id(client) -> int:
    return client.get("/api/domains").json()[0]["id"]


def test_all_routes_registered(client):
    """防止新增路由模块后忘记 include_router（dashboard 曾因此漏挂）。"""
    paths = {r.path for r in client.app.routes}
    expected = {
        "/api/dashboard",
        "/api/domains",
        "/api/closed-days",
        "/api/biz-days/overview",
        "/api/closed-days/close",
        "/api/closed-days/reopen",
        "/api/paste/load",
        "/api/layers/counts",
        "/api/jobs",
        "/api/jobs/paste-to-detail",
        "/api/jobs/detail-to-summary",
        "/api/reconcile",
    }
    assert expected <= paths


def test_close_list_and_overview_consistent(client):
    did = _domain_id(client)
    # 初始贴源：11-10 三行，11-11 三行
    overview = client.get(f"/api/biz-days/overview?domain_id={did}").json()
    by_day = {r["biz_day"]: r for r in overview}
    assert by_day["2026-11-10"]["paste_count"] == 3
    assert by_day["2026-11-11"]["paste_count"] == 3
    assert all(not r["closed"] for r in overview)

    r = client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10", "reason": "月结"},
    )
    assert r.status_code == 200
    # 重复关闭走更新而非报错
    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10", "reason": "月结完成"},
    )

    closed = client.get(f"/api/closed-days?domain_id={did}").json()
    assert len(closed) == 1 and closed[0]["biz_day"] == "2026-11-10"
    assert closed[0]["reason"] == "月结完成"

    overview = client.get(f"/api/biz-days/overview?domain_id={did}").json()
    by_day = {r["biz_day"]: r for r in overview}
    assert by_day["2026-11-10"]["closed"] is True
    # 贴源按日计数不受关闭影响
    assert by_day["2026-11-10"]["paste_count"] == 3

    # 贴源列表带关闭标记，与名单同源
    paste = client.get(f"/api/layers/贴源?domain_id={did}").json()
    assert all(r["closed"] is True for r in paste if r["biz_day"] == "2026-11-10")
    assert all(r["closed"] is False for r in paste if r["biz_day"] == "2026-11-11")


def test_paste_load_rejects_closed_day_but_keeps_existing_rows(client):
    did = _domain_id(client)
    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )

    # 全量装载：关闭日 3 行拒绝，未关闭日 3 行重写
    job = client.post("/api/paste/load", json={"domain_id": did}).json()
    assert job["step"] == "paste_load"
    assert job["reject_count"] == 3
    assert job["out_count"] == 3
    assert job["in_count"] == 6
    assert "成功（含拒绝）" == job["status"]
    assert "2026-11-10已关闭" in job["message"]

    # 关闭日贴源原样保留，总行数仍是 6
    paste = client.get(f"/api/layers/贴源?domain_id={did}").json()
    assert len(paste) == 6
    assert sum(1 for r in paste if r["biz_day"] == "2026-11-10") == 3

    # 定点装载关闭日：整单拒绝
    job2 = client.post(
        "/api/paste/load", json={"domain_id": did, "biz_day": "2026-11-10"}
    ).json()
    assert job2["status"] == "拒绝"
    assert job2["reject_count"] == 3 and job2["out_count"] == 0

    # 装载结果进任务列表，刷新（重新请求）仍在
    jobs = client.get(f"/api/jobs?domain_id={did}").json()
    steps = {(j["step"], j["status"], j["reject_count"]) for j in jobs}
    assert ("paste_load", "拒绝", 3) in steps
    assert ("paste_load", "成功（含拒绝）", 3) in steps


def test_layer_jobs_reject_closed_day_for_both_steps(client):
    did = _domain_id(client)
    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )

    # 定点重算关闭日：贴源到明细被拒绝（400），任务已落库
    r = client.post(
        "/api/jobs/paste-to-detail",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )
    assert r.status_code == 400
    assert "已关闭" in r.json()["detail"]["原因"]
    assert r.json()["detail"]["任务"]["status"] == "拒绝"

    # 明细到汇总定点同样被拒绝
    r = client.post(
        "/api/jobs/detail-to-summary",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["任务"]["step"] == "detail_to_summary"

    # 拒绝后没有任何分层数据被写入
    assert client.get(f"/api/layers/明细?domain_id={did}").json() == []
    assert client.get(f"/api/layers/汇总?domain_id={did}").json() == []


def test_full_runs_skip_closed_days_and_reopen_restores(client):
    did = _domain_id(client)
    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )

    # 全量贴源到明细：关闭日 3 行跳过；11-11 三行中 1 行因空店名/负金额被剔除
    job = client.post("/api/jobs/paste-to-detail", json={"domain_id": did}).json()
    assert job["reject_count"] == 3 and job["out_count"] == 2 and job["drop_count"] == 1
    detail = client.get(f"/api/layers/明细?domain_id={did}").json()
    assert {r["biz_day"] for r in detail} == {"2026-11-11"}

    # 全量明细到汇总：明细层本就不含关闭日，只汇总未关闭日
    job = client.post("/api/jobs/detail-to-summary", json={"domain_id": did}).json()
    assert job["reject_count"] == 0
    summary = client.get(f"/api/layers/汇总?domain_id={did}").json()
    assert {r["biz_day"] for r in summary} == {"2026-11-11"}

    # 重新打开后行为恢复：全量重跑不再有拒绝
    client.post(
        "/api/closed-days/reopen",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )
    job = client.post("/api/jobs/paste-to-detail", json={"domain_id": did}).json()
    assert job["reject_count"] == 0 and job["status"] == "成功"
    # 6 行贴源中 1 行因空店名/负金额被剔除
    assert job["out_count"] == 5 and job["drop_count"] == 1
    detail = client.get(f"/api/layers/明细?domain_id={did}").json()
    assert {r["biz_day"] for r in detail} == {"2026-11-10", "2026-11-11"}

    client.post("/api/jobs/detail-to-summary", json={"domain_id": did})
    summary = client.get(f"/api/layers/汇总?domain_id={did}").json()
    assert {r["biz_day"] for r in summary} == {"2026-11-10", "2026-11-11"}


def test_open_day_behavior_unchanged(client):
    did = _domain_id(client)
    # 未关闭任何业务日时，两个步骤与原始行为一致
    j1 = client.post("/api/jobs/paste-to-detail", json={"domain_id": did}).json()
    assert j1["status"] == "成功" and j1["reject_count"] == 0 and j1["out_count"] == 5
    j2 = client.post("/api/jobs/detail-to-summary", json={"domain_id": did}).json()
    assert j2["status"] == "成功" and j2["reject_count"] == 0

    # 定点重算未关闭日正常执行（11-11 三行中 1 行被清洗剔除）
    j3 = client.post(
        "/api/jobs/paste-to-detail",
        json={"domain_id": did, "biz_day": "2026-11-11"},
    ).json()
    assert j3["status"] == "成功" and j3["biz_day"] == "2026-11-11" and j3["out_count"] == 2


def test_reconcile_report_records_closed_days(client):
    did = _domain_id(client)
    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )
    report = client.post("/api/reconcile", json={"domain_id": did}).json()
    assert report["detail"]["已关闭业务日"] == ["2026-11-10"]


def test_full_runs_preserve_legacy_closed_day_data(client):
    """关闭日前已产出的明细/汇总，在全量重跑时必须原样保留、不被重写。"""
    did = _domain_id(client)
    # 先在未关闭状态下把三层都跑出来
    client.post("/api/jobs/paste-to-detail", json={"domain_id": did})
    client.post("/api/jobs/detail-to-summary", json={"domain_id": did})
    detail_before = client.get(f"/api/layers/明细?domain_id={did}").json()
    summary_before = client.get(f"/api/layers/汇总?domain_id={did}").json()
    closed_detail = [r for r in detail_before if r["biz_day"] == "2026-11-10"]
    closed_summary = [r for r in summary_before if r["biz_day"] == "2026-11-10"]
    assert closed_detail and closed_summary

    client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026-11-10"},
    )
    client.post("/api/jobs/paste-to-detail", json={"domain_id": did})
    client.post("/api/jobs/detail-to-summary", json={"domain_id": did})

    detail_after = client.get(f"/api/layers/明细?domain_id={did}").json()
    summary_after = client.get(f"/api/layers/汇总?domain_id={did}").json()
    assert [r for r in detail_after if r["biz_day"] == "2026-11-10"] == closed_detail
    assert [r for r in summary_after if r["biz_day"] == "2026-11-10"] == closed_summary


def test_invalid_biz_day_rejected(client):
    did = _domain_id(client)
    r = client.post(
        "/api/closed-days/close",
        json={"domain_id": did, "biz_day": "2026/11/10"},
    )
    assert r.status_code == 400


def test_legacy_db_migration(tmp_path, monkeypatch):
    """旧版库没有 reject_count/biz_day 列与 closed_biz_days 表，启动时自动迁移。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES))
    db = data_dir / "app.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE domains (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
          biz_key TEXT NOT NULL, fixture_file TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE layer_paste (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL, biz_day TEXT NOT NULL,
          store_code TEXT NOT NULL, store_name TEXT NOT NULL, category TEXT NOT NULL,
          amount REAL NOT NULL, qty INTEGER NOT NULL, raw_json TEXT NOT NULL
        );
        CREATE TABLE layer_detail (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL, biz_day TEXT NOT NULL,
          store_code TEXT NOT NULL, store_name TEXT NOT NULL, category TEXT NOT NULL,
          amount REAL NOT NULL, qty INTEGER NOT NULL, clean_flag TEXT NOT NULL
        );
        CREATE TABLE layer_summary (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL, biz_day TEXT NOT NULL,
          store_code TEXT NOT NULL, amount_sum REAL NOT NULL, qty_sum INTEGER NOT NULL,
          line_count INTEGER NOT NULL, UNIQUE(domain_id, biz_day, store_code)
        );
        CREATE TABLE layer_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL, step TEXT NOT NULL,
          status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', in_count INTEGER NOT NULL DEFAULT 0,
          out_count INTEGER NOT NULL DEFAULT 0, drop_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE reconcile_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain_id INTEGER NOT NULL,
          paste_count INTEGER NOT NULL, detail_count INTEGER NOT NULL,
          summary_line_sum INTEGER NOT NULL, key_mismatch INTEGER NOT NULL,
          amount_drift REAL NOT NULL, status TEXT NOT NULL, detail_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO domains(name, biz_key, fixture_file, description)
          VALUES ('旧主题域', '业务日', 'x.jsonl', '');
        INSERT INTO layer_jobs(domain_id, step, status) VALUES (1, 'paste_to_detail', '成功');
        """
    )
    conn.commit()
    conn.close()

    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]
    from app import seed

    seed.init_db()

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(layer_jobs)").fetchall()}
    assert {"reject_count", "biz_day"} <= cols
    # 旧任务记录迁移后默认值正确
    row = conn.execute("SELECT reject_count, biz_day FROM layer_jobs").fetchone()
    assert row == (0, None)
    # 关闭名单表可用
    conn.execute(
        "INSERT INTO closed_biz_days(domain_id, biz_day) VALUES (1, '2026-11-10')"
    )
    conn.commit()
    conn.close()
