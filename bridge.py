"""
Component 2: The Local FastAPI Graph Data Bridge.
High-performance local event receiver and metrics aggregation service.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from vjarvis_engine.schemas import (
    MetricsResponse,
    PatchStatus,
    ProtocolType,
    TriageEventRequest,
    detect_protocol,
)

logger = logging.getLogger("vjarvis.bridge")

DEFAULT_DB_PATH = Path("vjarvis_metrics.db").resolve()


class MetricsDatabase:
    """
    Thread-safe, local SQLite storage engine for triage telemetry events.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    target_file TEXT NOT NULL,
                    analysis TEXT NOT NULL,
                    original_exact_line TEXT,
                    fixed_exact_line TEXT,
                    confidence_score REAL,
                    protocol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rerun_command TEXT,
                    rerun_exit_code INTEGER,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_protocol ON triage_events (protocol)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON triage_events (status)"
            )

    def record_event(self, event: TriageEventRequest) -> int:
        import json

        # Infer protocol if not explicitly supplied
        protocol_val = (
            event.protocol.value
            if event.protocol
            else detect_protocol(event.analysis, event.original_exact_line).value
        )

        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO triage_events (
                    timestamp, target_file, analysis, original_exact_line,
                    fixed_exact_line, confidence_score, protocol, status,
                    rerun_command, rerun_exit_code, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat(),
                    event.target_file,
                    event.analysis,
                    event.original_exact_line,
                    event.fixed_exact_line,
                    event.confidence_score,
                    protocol_val,
                    event.status.value,
                    event.rerun_command,
                    event.rerun_exit_code,
                    json.dumps(event.metadata),
                ),
            )
            return cursor.lastrowid

    def get_metrics(self) -> MetricsResponse:
        with self.get_connection() as conn:
            # Total failures processed
            cursor = conn.execute("SELECT COUNT(*) FROM triage_events")
            total = cursor.fetchone()[0]

            # Successful automated patches
            cursor = conn.execute(
                "SELECT COUNT(*) FROM triage_events WHERE status = ?",
                (PatchStatus.PATCHED_SUCCESS.value,),
            )
            successful = cursor.fetchone()[0]

            # Rollbacks
            cursor = conn.execute(
                "SELECT COUNT(*) FROM triage_events WHERE status = ?",
                (PatchStatus.ROLLBACK.value,),
            )
            rollbacks = cursor.fetchone()[0]

            # Inconclusive
            cursor = conn.execute(
                "SELECT COUNT(*) FROM triage_events WHERE status = ?",
                (PatchStatus.INCONCLUSIVE.value,),
            )
            inconclusive = cursor.fetchone()[0]

            # Grouped by protocol (guarantee AXI, PCIe, General UVM exist)
            proto_counts = {
                ProtocolType.AXI.value: 0,
                ProtocolType.PCIE.value: 0,
                ProtocolType.GENERAL_UVM.value: 0,
            }

            cursor = conn.execute(
                "SELECT protocol, COUNT(*) FROM triage_events GROUP BY protocol"
            )
            for row in cursor.fetchall():
                proto_name, count = row[0], row[1]
                proto_counts[proto_name] = count

            success_rate = round((successful / total * 100.0), 2) if total > 0 else 0.0

            return MetricsResponse(
                total_failures_processed=total,
                successful_automated_patches=successful,
                failures_grouped_by_protocol=proto_counts,
                rollbacks=rollbacks,
                inconclusive=inconclusive,
                success_rate_percent=success_rate,
            )

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        import json

        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM triage_events ORDER BY id DESC LIMIT ?", (limit,)
            )
            events = []
            for row in cursor.fetchall():
                events.append({
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "target_file": row["target_file"],
                    "analysis": row["analysis"],
                    "original_exact_line": row["original_exact_line"],
                    "fixed_exact_line": row["fixed_exact_line"],
                    "confidence_score": row["confidence_score"],
                    "protocol": row["protocol"],
                    "status": row["status"],
                    "rerun_command": row["rerun_command"],
                    "rerun_exit_code": row["rerun_exit_code"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                })
            return events


# Global Database Handle
db = MetricsDatabase()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Local FastAPI Graph Data Bridge...")
    yield
    logger.info("Local FastAPI Graph Data Bridge stopped.")


app = FastAPI(
    title="vjarvis-engine Graph Data Bridge",
    description="High-performance local telemetry and metrics bridge for autonomous VLSI regression triage",
    version="1.0.0",
    lifespan=lifespan,
)

# Restrict to local network for strict data isolation
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["System"])
async def health_check():
    """Confirms local server vitality."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_file": str(db.db_path),
    }


@app.post(
    "/api/triage-event",
    status_code=status.HTTP_201_CREATED,
    tags=["Telemetry"],
    summary="Record simulation failure & automated patch telemetry event",
)
async def record_triage_event(event: TriageEventRequest):
    """
    Invoked by the CLI agent every time an incident is intercepted or patched.
    """
    try:
        event_id = db.record_event(event)
        logger.info(
            "Recorded triage event #%d: [%s] file=%s status=%s",
            event_id,
            event.protocol or "Auto",
            event.target_file,
            event.status.value,
        )
        return {
            "status": "success",
            "event_id": event_id,
            "message": "Telemetry event recorded successfully.",
        }
    except Exception as e:
        logger.exception("Failed to store triage event: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error writing event: {e}",
        )


@app.get(
    "/api/metrics",
    response_model=MetricsResponse,
    tags=["Metrics"],
    summary="Fetch aggregated triage, automated patch counts and protocol breakdowns",
)
async def get_metrics():
    """
    Returns aggregated metrics:
    - total_failures_processed
    - successful_automated_patches
    - failures_grouped_by_protocol (AXI, PCIe, General UVM)
    """
    try:
        return db.get_metrics()
    except Exception as e:
        logger.exception("Failed to compute metrics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading metrics: {e}",
        )


@app.get("/api/events", tags=["Telemetry"], summary="Fetch recent triage events")
async def list_recent_events(limit: int = 50):
    """Returns recent recorded incidents for inspection."""
    return db.get_recent_events(limit=limit)
