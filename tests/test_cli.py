"""
End-to-end CLI integration test.
"""

from pathlib import Path
import json
import pytest

from vjarvis_engine.cli import process_triage
from vjarvis_engine.schemas import BrainTriagePayload, PatchStatus


def test_cli_process_triage_auto_approve_success(tmp_path: Path):
    target_sv = tmp_path / "top_tb.sv"
    target_sv.write_text("initial begin\n    #10 rst_n = 1'b0;\nend\n", encoding="utf-8")

    payload = BrainTriagePayload(
        analysis="Reset polarity is active-low but was held deasserted incorrectly.",
        original_exact_line="    #10 rst_n = 1'b0;",
        fixed_exact_line="    #10 rst_n = 1'b1;",
        confidence_score=0.97,
    )

    success = process_triage(
        payload=payload,
        target_file=target_sv,
        rerun_command="python3 -c 'import sys; sys.exit(0)'",
        auto_approve=True,
        bridge_url="http://127.0.0.1:9999",  # bridge offline -> will buffer
    )

    assert success is True
    assert target_sv.read_text(encoding="utf-8") == "initial begin\n    #10 rst_n = 1'b1;\nend\n"
    assert target_sv.with_name("top_tb.sv.bak").exists()


def test_cli_process_triage_rejection(tmp_path: Path, monkeypatch):
    target_sv = tmp_path / "top_tb.sv"
    target_sv.write_text("initial begin\n    #10 rst_n = 1'b0;\nend\n", encoding="utf-8")

    payload = BrainTriagePayload(
        analysis="Proposed reset fix",
        original_exact_line="    #10 rst_n = 1'b0;",
        fixed_exact_line="    #10 rst_n = 1'b1;",
        confidence_score=0.97,
    )

    # Simulate user entering 'n'
    monkeypatch.setattr("builtins.input", lambda _: "n")

    success = process_triage(
        payload=payload,
        target_file=target_sv,
        rerun_command="python3 -c 'import sys; sys.exit(0)'",
        auto_approve=False,
        bridge_url="http://127.0.0.1:9999",
    )

    assert success is False
    assert target_sv.read_text(encoding="utf-8") == "initial begin\n    #10 rst_n = 1'b0;\nend\n"
