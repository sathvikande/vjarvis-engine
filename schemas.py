"""
Pydantic schemas and protocol models for the vjarvis-engine framework.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


class ProtocolType(str, Enum):
    AXI = "AXI"
    PCIE = "PCIe"
    GENERAL_UVM = "General UVM"


class PatchStatus(str, Enum):
    DETECTED = "detected"
    PATCHED_SUCCESS = "patched_success"
    ROLLBACK = "rollback"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    FAILED_TO_PATCH = "failed_to_patch"


class BrainTriagePayload(BaseModel):
    """
    Validated brain inference payload emitted by vjarvis-engine core.
    """
    model_config = ConfigDict(extra="ignore")

    analysis: str = Field(..., description="Dense technical description of failure root cause")
    original_exact_line: str = Field(..., description="Character-for-character line to be replaced")
    fixed_exact_line: str = Field(..., description="Replacement SystemVerilog/UVM line")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence metric (0.0 to 1.0)")

    @property
    def is_conclusive(self) -> bool:
        if self.confidence_score <= 0.0:
            return False
        if not self.original_exact_line.strip() or not self.fixed_exact_line.strip():
            return False
        if "Telemetry insufficient" in self.analysis:
            return False
        return True


class TriageEventRequest(BaseModel):
    """
    Telemetry event recorded every time an incident is processed.
    """
    model_config = ConfigDict(extra="ignore")

    analysis: str
    original_exact_line: str = ""
    fixed_exact_line: str = ""
    confidence_score: float = 0.0
    target_file: str = Field(..., description="Relative or absolute path to target source file")
    protocol: Optional[ProtocolType] = None
    status: PatchStatus = PatchStatus.DETECTED
    rerun_command: Optional[str] = None
    rerun_exit_code: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetricsResponse(BaseModel):
    """
    Aggregated failure and automated patch performance metrics.
    """
    total_failures_processed: int
    successful_automated_patches: int
    failures_grouped_by_protocol: Dict[str, int]
    rollbacks: int = 0
    inconclusive: int = 0
    success_rate_percent: float = 0.0


def detect_protocol(analysis: str, code_snippet: str = "") -> ProtocolType:
    """
    Dynamically infers the protocol domain from telemetry analysis or code strings.
    """
    corpus = f"{analysis} {code_snippet}".lower()

    # High-speed PCIe patterns
    if any(k in corpus for k in ["pcie", "tlp", "dllp", "root complex", "endpoint", "cxl", "pipe interface", "ltssm"]):
        return ProtocolType.PCIE

    # AMBA / AXI patterns
    if any(k in corpus for k in ["axi", "awvalid", "awready", "wvalid", "wready", "bvalid", "bready", "arvalid", "arready", "rvalid", "rready", "amba", "apb", "ahb"]):
        return ProtocolType.AXI

    # Default to General UVM
    return ProtocolType.GENERAL_UVM
