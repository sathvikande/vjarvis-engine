"""
Tests for Component 1: File Patcher and Automated Rollback Engine.
"""

import os
from pathlib import Path
import pytest

from vjarvis_engine.patcher import (
    FilePatcher,
    LineNotFoundError,
    TargetFileNotFoundError,
)
from vjarvis_engine.schemas import BrainTriagePayload


@pytest.fixture
def sample_systemverilog_file(tmp_path: Path) -> Path:
    sv_file = tmp_path / "axi_slave_agent.sv"
    content = """// Custom AXI Slave Monitor
module axi_slave_agent;
    logic aclk;
    logic aresetn;
    logic awvalid;
    logic awready;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            awready <= 1'b0;
        end else if (awvalid && !awready) begin
            awready <= 1'b0; // DEFECT: awready deasserted incorrectly
        end
    end
endmodule
"""
    sv_file.write_text(content, encoding="utf-8")
    return sv_file


def test_successful_patch_and_simulation_pass(sample_systemverilog_file: Path):
    patcher = FilePatcher(keep_backup_on_success=True)
    payload = BrainTriagePayload(
        analysis="AXI protocol defect: awready prematurely deasserted during active awvalid handshake.",
        original_exact_line="            awready <= 1'b0; // DEFECT: awready deasserted incorrectly",
        fixed_exact_line="            awready <= 1'b1; // FIXED: assert awready to acknowledge handshake",
        confidence_score=0.98,
    )

    # Simulation command returns 0 (success)
    sim_cmd = "python3 -c 'import sys; sys.exit(0)'"
    result = patcher.patch_and_verify(sample_systemverilog_file, payload, rerun_command=sim_cmd)

    assert result.success is True
    assert result.exit_code == 0
    assert result.rolled_back is False

    # Check that backup file exists
    backup_file = sample_systemverilog_file.with_name(f"{sample_systemverilog_file.name}.bak")
    assert backup_file.exists()

    # Verify that the target file has the replacement
    patched_content = sample_systemverilog_file.read_text(encoding="utf-8")
    assert "awready <= 1'b1; // FIXED" in patched_content
    assert "awready <= 1'b0; // DEFECT" not in patched_content

    # Verify backup contains original content
    backup_content = backup_file.read_text(encoding="utf-8")
    assert "awready <= 1'b0; // DEFECT" in backup_content


def test_simulation_failure_triggers_automated_rollback(sample_systemverilog_file: Path):
    patcher = FilePatcher()
    original_content = sample_systemverilog_file.read_text(encoding="utf-8")

    payload = BrainTriagePayload(
        analysis="AXI defect fix attempt",
        original_exact_line="            awready <= 1'b0; // DEFECT: awready deasserted incorrectly",
        fixed_exact_line="            awready <= 1'b1; // FIXED",
        confidence_score=0.95,
    )

    # Simulation command returns non-zero (failure)
    sim_cmd = "python3 -c 'import sys; sys.stderr.write(\"Assertion Error in AXI VIP\"); sys.exit(2)'"
    result = patcher.patch_and_verify(sample_systemverilog_file, payload, rerun_command=sim_cmd)

    assert result.success is False
    assert result.exit_code == 2
    assert result.rolled_back is True
    assert "Assertion Error in AXI VIP" in result.stderr

    # Verify target file has been restored to exact original content
    restored_content = sample_systemverilog_file.read_text(encoding="utf-8")
    assert restored_content == original_content
    assert "awready <= 1'b0; // DEFECT" in restored_content


def test_line_not_found_leaves_file_unmodified(sample_systemverilog_file: Path):
    patcher = FilePatcher()
    original_content = sample_systemverilog_file.read_text(encoding="utf-8")

    payload = BrainTriagePayload(
        analysis="Invalid target line",
        original_exact_line="non_existent_signal <= 1'b1;",
        fixed_exact_line="valid_signal <= 1'b1;",
        confidence_score=0.90,
    )

    result = patcher.patch_and_verify(sample_systemverilog_file, payload, rerun_command="echo 'ok'")

    assert result.success is False
    assert result.rolled_back is True
    assert "Target string not found" in (result.error_message or "")
    assert sample_systemverilog_file.read_text(encoding="utf-8") == original_content


def test_inconclusive_payload_does_not_modify(sample_systemverilog_file: Path):
    patcher = FilePatcher()
    original_content = sample_systemverilog_file.read_text(encoding="utf-8")

    payload = BrainTriagePayload(
        analysis="Inconclusive: Telemetry insufficient. Requires detailed waveform analysis.",
        original_exact_line="",
        fixed_exact_line="",
        confidence_score=0.0,
    )

    result = patcher.patch_and_verify(sample_systemverilog_file, payload, rerun_command="echo 'ok'")
    assert result.success is False
    assert sample_systemverilog_file.read_text(encoding="utf-8") == original_content
