# vjarvis-engine: Project Context & Architecture State

> **Persistent Context File**  
> Read this file in any future AI session to instantly restore full architectural context, operational manifests, and development state.

---

## 1. System Overview & Manifest
- **Name**: `vjarvis-engine`
- **Domain**: Autonomous VLSI Verification Engineer CLI tool for EDA suites (Cadence Xcelium/irun, Siemens Questa/vsim, Synopsys VCS).
- **Primary Function**: Intercepts simulation/regression failures, analyzes root cause via LLM inference, generates character-for-character replacements, creates `<filename>.bak` snapshots, verifies via re-run, and executes automated rollbacks if re-runs fail.
- **GitHub Repository**: [https://github.com/sathvikande/vjarvis-engine](https://github.com/sathvikande/vjarvis-engine)
- **Local Directory**: `/Users/sathvikande/vjarvis_engine`

---

## 2. Core Modules & Codebase Map

| File | Module / Responsibility |
| :--- | :--- |
| [`patcher.py`](file:///Users/sathvikande/vjarvis_engine/patcher.py) | **Component 1: File Patcher & Rollback Engine**. Handles `.bak` snapshots, atomic file replacement via `os.replace`, simulation re-run execution, and immediate rollback on non-zero exit codes. |
| [`bridge.py`](file:///Users/sathvikande/vjarvis_engine/bridge.py) | **Component 2: Local FastAPI Bridge & SQLite Store**. Runs on `127.0.0.1:8000`. Endpoints: `POST /api/triage-event`, `GET /api/metrics` (aggregates failures by AXI, PCIe, General UVM). |
| [`client.py`](file:///Users/sathvikande/vjarvis_engine/client.py) | Resilient client connecting CLI to FastAPI bridge. Buffers events offline to `.vjarvis_offline_events.jsonl` if server is down. |
| [`ai_triage.py`](file:///Users/sathvikande/vjarvis_engine/ai_triage.py) | AI inference connectors: Google Gemini API, local Ollama, and OpenAI-compatible endpoints (**FreeLLMAPI** on `http://127.0.0.1:3001/v1`). |
| [`schemas.py`](file:///Users/sathvikande/vjarvis_engine/schemas.py) | Pydantic data schemas: `BrainTriagePayload`, `TriageEventRequest`, `MetricsResponse`, and `detect_protocol()`. |
| [`cli.py`](file:///Users/sathvikande/vjarvis_engine/cli.py) | Main interactive CLI. Subcommands: `vjarvis auto`, `vjarvis patch`, `vjarvis serve`, `vjarvis metrics`. |
| [`install.sh`](file:///Users/sathvikande/vjarvis_engine/install.sh) | 1-Click installer symlinking `vjarvis` to `~/.local/bin/vjarvis`. |
| [`tests/`](file:///Users/sathvikande/vjarvis_engine/tests) | 9/9 passing pytest suites covering patcher, rollback, bridge, CLI, and FreeLLMAPI. |

---

## 3. Strict Brain Output JSON Schema

When prompting an LLM for triage, the output must strictly follow:
```json
{
  "analysis": "Dense, technically rigorous description detailing structural cause of protocol or UVM error.",
  "original_exact_line": "Exact character-for-character line inside target file to be removed.",
  "fixed_exact_line": "Precise replacement SystemVerilog/UVM line.",
  "confidence_score": 0.99
}
```
*If telemetry is insufficient:*
```json
{
  "analysis": "Inconclusive: Telemetry insufficient. Requires detailed waveform analysis.",
  "original_exact_line": "",
  "fixed_exact_line": "",
  "confidence_score": 0.00
}
```

---

## 4. Key CLI Commands

```bash
# 1. 100% Free AI triage using local FreeLLMAPI router
vjarvis auto --file tb/driver.sv --log sim.log --rerun-cmd "vsim -c tb_top" --provider freellmapi

# 2. Automated triage using Gemini API
vjarvis auto --file tb/driver.sv --log sim.log --rerun-cmd "vsim -c tb_top"

# 3. Transactional patch with JSON file & auto-rollback
vjarvis patch --file tb/driver.sv --rerun-cmd "./simulate.sh" --payload-file patch.json

# 4. Start local metrics server & fetch dashboard
vjarvis serve &
vjarvis metrics
```

---

## 5. FreeLLMAPI Integration Details
- Local path: `/Users/sathvikande/freellmapi`
- Start server: `cd /Users/sathvikande/freellmapi && npm run dev -w server`
- Default endpoint: `http://127.0.0.1:3001/v1`
