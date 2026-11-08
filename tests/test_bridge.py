"""
Tests for Component 2: Local FastAPI Graph Data Bridge & Metrics API.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from vjarvis_engine.bridge import app, db, MetricsDatabase
from vjarvis_engine.schemas import PatchStatus, ProtocolType, TriageEventRequest


@pytest.fixture(autouse=True)
def setup_isolated_test_db(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / "test_metrics.db"
    test_db = MetricsDatabase(db_path=test_db_path)
    # Monkeypatch global db in bridge
    monkeypatch.setattr("vjarvis_engine.bridge.db", test_db)
    return test_db


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_post_triage_event_and_metrics_aggregation(client):
    # Initial metrics should be 0
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    metrics = resp.json()
    assert metrics["total_failures_processed"] == 0
    assert metrics["successful_automated_patches"] == 0
    assert metrics["failures_grouped_by_protocol"]["AXI"] == 0
    assert metrics["failures_grouped_by_protocol"]["PCIe"] == 0
    assert metrics["failures_grouped_by_protocol"]["General UVM"] == 0

    # Event 1: AXI Protocol successful patch
    event1 = {
        "analysis": "AXI protocol defect: awready handshake missing assertion.",
        "original_exact_line": "awready <= 1'b0;",
        "fixed_exact_line": "awready <= 1'b1;",
        "confidence_score": 0.99,
        "target_file": "tb/axi_agent.sv",
        "protocol": "AXI",
        "status": "patched_success",
        "rerun_command": "vsim -c tb_axi",
        "rerun_exit_code": 0,
    }
    r1 = client.post("/api/triage-event", json=event1)
    assert r1.status_code == 201

    # Event 2: PCIe Protocol failed / rollback
    event2 = {
        "analysis": "PCIe TLP header format error in root complex model.",
        "original_exact_line": "tlp_fmt <= 3'b000;",
        "fixed_exact_line": "tlp_fmt <= 3'b010;",
        "confidence_score": 0.92,
        "target_file": "tb/pcie_rc.sv",
        "protocol": "PCIe",
        "status": "rollback",
        "rerun_command": "vsim -c tb_pcie",
        "rerun_exit_code": 1,
    }
    r2 = client.post("/api/triage-event", json=event2)
    assert r2.status_code == 201

    # Event 3: General UVM Phase timeout with auto protocol detection
    event3 = {
        "analysis": "UVM_ERROR: run_phase timeout reached before objection dropped.",
        "original_exact_line": "phase.drop_objection(this);",
        "fixed_exact_line": "phase.drop_objection(this);",
        "confidence_score": 0.85,
        "target_file": "tb/test_base.sv",
        "status": "patched_success",
    }
    r3 = client.post("/api/triage-event", json=event3)
    assert r3.status_code == 201

    # Query updated metrics
    resp_metrics = client.get("/api/metrics")
    assert resp_metrics.status_code == 200
    data = resp_metrics.json()

    assert data["total_failures_processed"] == 3
    assert data["successful_automated_patches"] == 2
    assert data["rollbacks"] == 1
    assert data["failures_grouped_by_protocol"]["AXI"] == 1
    assert data["failures_grouped_by_protocol"]["PCIe"] == 1
    assert data["failures_grouped_by_protocol"]["General UVM"] == 1
    assert data["success_rate_percent"] == 66.67
