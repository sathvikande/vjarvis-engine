# vjarvis-engine

> **Autonomous VLSI Verification Patcher & Telemetry Bridge**  
> Hardware-native EDA regression triage, transactional SystemVerilog/UVM code patching, and local telemetry aggregation.

---

## ⚡ 1-Click Quickstart

Clone the repository and run the installer on any Linux/macOS/WSL machine:

```bash
git clone https://github.com/AndeSanath/vjarvis-engine.git
cd vjarvis-engine
./install.sh
```

The installer automatically:
1. Sets up the isolated environment and installs all dependencies (`FastAPI`, `Uvicorn`, `Pydantic`, `HTTPX`, `Pytest`).
2. Symlinks the `vjarvis` binary to `~/.local/bin/vjarvis` so you can use it from any directory.
3. Runs the test suite to ensure 100% operational readiness.

*(Ensure `~/.local/bin` is in your `PATH` by adding `export PATH="$HOME/.local/bin:$PATH"` to your `~/.bashrc` or `~/.zshrc`).*

---

## 🚀 How to Use

### 1. Automated AI Triage & Verification (`vjarvis auto`)
Analyze simulation logs, extract failing logic, generate the patch, and re-run verification in one command:

```bash
# Set your Gemini API key (or configure local Ollama for air-gapped EDA servers)
export GEMINI_API_KEY="your-api-key"

vjarvis auto \
  --file path/to/axi_master_agent.sv \
  --log simulation.log \
  --rerun-cmd "vsim -c -do 'run -all; quit' tb_top"
```

### 2. Transactional Code Patcher (`vjarvis patch`)
Safely apply an AI JSON patch with automated rollback on failure:

```bash
vjarvis patch \
  --file path/to/axi_master_agent.sv \
  --rerun-cmd "vsim -c -do 'run -all; quit' tb_top" \
  --payload-file brain_payload.json
```

**Zero Corruption Guarantee:**
- Creates `<filename>.bak` prior to modification.
- Atomically replaces the target line.
- Re-runs simulation command.
- If simulation fails (exit code != 0), it automatically restores `<filename>.bak`.

### 3. Local Metrics Bridge (`vjarvis serve` & `vjarvis metrics`)
Start the background server on `http://127.0.0.1:8000`:

```bash
# Start background server
vjarvis serve &

# Query live aggregated statistics
vjarvis metrics
```

Example output:
```json
{
  "total_failures_processed": 4,
  "successful_automated_patches": 3,
  "failures_grouped_by_protocol": {
    "AXI": 2,
    "General UVM": 1,
    "PCIe": 1
  },
  "rollbacks": 1,
  "success_rate_percent": 75.0
}
```

---

## 🧪 Testing

Run all unit and integration tests:
```bash
make test
# or: pytest -v tests
```
