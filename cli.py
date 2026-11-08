"""
vjarvis-engine CLI Interactive Loop & Verification Orchestrator.
Fulfills Stage 1-4 pipeline:
- Intercepts brain JSON payloads
- Pre-flight backup (.bak snapshot)
- Prompts engineer: 'Shall I apply this fix, re-run, and update the simulation log? (y/n)'
- Orchestrates atomic replacement & automated rollback on non-zero exit codes
- Emits telemetry metrics to the local FastAPI bridge
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from vjarvis_engine.client import BridgeClient
from vjarvis_engine.patcher import FilePatcher
from vjarvis_engine.schemas import (
    BrainTriagePayload,
    PatchStatus,
    TriageEventRequest,
    detect_protocol,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vjarvis.cli")


def print_patch_preview(payload: BrainTriagePayload, target_file: Path) -> None:
    """
    Renders terminal diff visualization of the proposed fix.
    """
    print("\n" + "=" * 70)
    print(" [vjarvis-engine] INFERENCE TELEMETRY PAYLOAD RECEIVED")
    print("=" * 70)
    print(f"Target File     : {target_file}")
    print(f"Confidence Score: {payload.confidence_score:.2f}")
    print(f"Analysis        : {payload.analysis}")
    print("-" * 70)
    print("[-] ORIGINAL LINE (To be removed):")
    print(f"    {payload.original_exact_line}")
    print("[+] REPLACEMENT LINE (To be inserted):")
    print(f"    {payload.fixed_exact_line}")
    print("=" * 70 + "\n")


def process_triage(
    payload: BrainTriagePayload,
    target_file: Path,
    rerun_command: str,
    auto_approve: bool = False,
    bridge_url: str = "http://127.0.0.1:8000",
) -> bool:
    """
    Executes the interactive triage and verification loop.
    """
    client = BridgeClient(base_url=bridge_url)
    protocol = detect_protocol(payload.analysis, payload.original_exact_line)

    # If telemetry is inconclusive, log and record event immediately
    if not payload.is_conclusive:
        print("\n[!] Inconclusive telemetry payload. Code parameters blank. Aborting patch execution.")
        event = TriageEventRequest(
            analysis=payload.analysis,
            original_exact_line=payload.original_exact_line,
            fixed_exact_line=payload.fixed_exact_line,
            confidence_score=payload.confidence_score,
            target_file=str(target_file),
            protocol=protocol,
            status=PatchStatus.INCONCLUSIVE,
        )
        client.send_event(event)
        return False

    # Present diff preview
    print_patch_preview(payload, target_file)

    # Interactive Stage 4 Prompt
    if auto_approve:
        user_choice = "y"
        print("Auto-approve mode active (-y/--yes). Proceeding...")
    else:
        prompt_str = "Shall I apply this fix, re-run, and update the simulation log? (y/n): "
        try:
            user_choice = input(prompt_str).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled by user.")
            user_choice = "n"

    if user_choice != "y":
        print("[-] Modification rejected by engineer. Development tree unchanged.")
        event = TriageEventRequest(
            analysis=payload.analysis,
            original_exact_line=payload.original_exact_line,
            fixed_exact_line=payload.fixed_exact_line,
            confidence_score=payload.confidence_score,
            target_file=str(target_file),
            protocol=protocol,
            status=PatchStatus.REJECTED,
        )
        client.send_event(event)
        return False

    # Execute atomic patch, backup, simulation re-run, and automated rollback
    patcher = FilePatcher()
    result = patcher.patch_and_verify(
        target_file=target_file,
        payload=payload,
        rerun_command=rerun_command,
    )

    final_status = PatchStatus.PATCHED_SUCCESS if result.success else PatchStatus.ROLLBACK

    if result.success:
        print("\n[SUCCESS] Fix verified! Simulation re-run PASSED with exit code 0.")
        print(f"[SUCCESS] Target file updated cleanly: {target_file}")
    else:
        print(f"\n[FAILURE] Simulation re-run returned non-zero exit code ({result.exit_code}).")
        print(f"[ROLLBACK] Automated rollback executed. Restored from {result.backup_file}")
        if result.stderr:
            print(f"Error output:\n{result.stderr}")

    # Emit telemetry event to local bridge
    event = TriageEventRequest(
        analysis=payload.analysis,
        original_exact_line=payload.original_exact_line,
        fixed_exact_line=payload.fixed_exact_line,
        confidence_score=payload.confidence_score,
        target_file=str(target_file),
        protocol=protocol,
        status=final_status,
        rerun_command=rerun_command,
        rerun_exit_code=result.exit_code,
    )
    client.send_event(event)

    return result.success


def main() -> None:
    parser = argparse.ArgumentParser(
        description="vjarvis-engine: Autonomous VLSI Verification Patcher & Re-run Orchestrator"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # Patch subcommand
    patch_parser = subparsers.add_parser("patch", help="Apply brain JSON patch and re-verify")
    patch_parser.add_argument(
        "--file", "-f", required=True, type=Path, help="Target SystemVerilog/UVM source file to patch"
    )
    patch_parser.add_argument(
        "--rerun-cmd", "-r", required=True, type=str, help="Simulation re-run command (e.g. 'vsim -c ...' or 'pytest ...')"
    )
    patch_parser.add_argument(
        "--payload", "-p", type=str, help="Raw JSON string from brain (or read from stdin if omitted)"
    )
    patch_parser.add_argument(
        "--payload-file", type=Path, help="Path to file containing brain JSON payload"
    )
    patch_parser.add_argument(
        "--yes", "-y", action="store_true", help="Auto-approve without interactive prompt"
    )
    patch_parser.add_argument(
        "--bridge-url", default="http://127.0.0.1:8000", help="FastAPI bridge server endpoint"
    )

    # Server subcommand
    serve_parser = subparsers.add_parser("serve", help="Run local FastAPI metrics bridge")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host binding (default: 127.0.0.1)")
    serve_parser.add_argument("--port", default=8000, type=int, help="Port binding (default: 8000)")

    # Metrics subcommand
    metrics_parser = subparsers.add_parser("metrics", help="Fetch metrics from local bridge")
    metrics_parser.add_argument("--bridge-url", default="http://127.0.0.1:8000", help="FastAPI bridge endpoint")

    # Auto subcommand (End-to-End AI Triage & Patch)
    auto_parser = subparsers.add_parser("auto", help="Automated AI triage from simulation log, patch, and re-run")
    auto_parser.add_argument("--file", "-f", required=True, type=Path, help="Target SystemVerilog/UVM source file")
    auto_parser.add_argument("--rerun-cmd", "-r", required=True, type=str, help="Simulation re-run command")
    auto_parser.add_argument("--log", "-l", type=Path, help="Path to simulation regression log file")
    auto_parser.add_argument("--provider", choices=["gemini", "ollama"], default="gemini", help="AI provider (default: gemini)")
    auto_parser.add_argument("--model", help="Model name (e.g. gemini-2.5-flash or qwen2.5-coder)")
    auto_parser.add_argument("--api-key", help="API key (defaults to GEMINI_API_KEY environment variable)")
    auto_parser.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama endpoint URL")
    auto_parser.add_argument("--yes", "-y", action="store_true", help="Auto-approve patch without confirmation prompt")
    auto_parser.add_argument("--bridge-url", default="http://127.0.0.1:8000", help="FastAPI bridge server endpoint")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from vjarvis_engine.bridge import app
        print(f"Starting vjarvis-engine FastAPI Data Bridge on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return

    if args.command == "metrics":
        client = BridgeClient(base_url=args.bridge_url)
        metrics = client.get_metrics()
        if metrics:
            print(json.dumps(metrics.model_dump(), indent=2))
        else:
            print("Failed to contact local metrics bridge at", args.bridge_url)
        return

    if args.command == "auto":
        from vjarvis_engine.ai_triage import (
            build_triage_prompt,
            call_gemini_api,
            call_ollama_local,
        )
        import os

        # Read log content
        log_content = ""
        if args.log:
            log_content = args.log.read_text(encoding="utf-8", errors="replace")
        elif not sys.stdin.isatty():
            log_content = sys.stdin.read()
        else:
            print("Error: Please provide a simulation log via --log or stdin.", file=sys.stderr)
            sys.exit(1)

        print(f"Analyzing simulation log for {args.file.name} using {args.provider.upper()}...")
        prompt = build_triage_prompt(log_content, args.file)

        try:
            if args.provider == "gemini":
                api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
                if not api_key:
                    print("Error: GEMINI_API_KEY environment variable or --api-key required for Gemini provider.", file=sys.stderr)
                    sys.exit(1)
                model_name = args.model or "gemini-2.5-flash"
                payload = call_gemini_api(prompt, api_key=api_key, model=model_name)
            else:
                model_name = args.model or "qwen2.5-coder"
                payload = call_ollama_local(prompt, base_url=args.ollama_url, model=model_name)
        except Exception as e:
            print(f"AI Triage Inference failed: {e}", file=sys.stderr)
            sys.exit(1)

        success = process_triage(
            payload=payload,
            target_file=args.file,
            rerun_command=args.rerun_cmd,
            auto_approve=args.yes,
            bridge_url=args.bridge_url,
        )
        sys.exit(0 if success else 1)

    if args.command == "patch":
        # Ingest payload
        raw_json = ""
        if args.payload_file:
            raw_json = args.payload_file.read_text(encoding="utf-8")
        elif args.payload:
            raw_json = args.payload
        elif not sys.stdin.isatty():
            raw_json = sys.stdin.read()
        else:
            print("Error: No brain payload provided via --payload, --payload-file, or stdin.", file=sys.stderr)
            sys.exit(1)

        try:
            data = json.loads(raw_json)
            payload = BrainTriagePayload(**data)
        except Exception as e:
            print(f"Error validating brain JSON payload: {e}", file=sys.stderr)
            sys.exit(1)

        success = process_triage(
            payload=payload,
            target_file=args.file,
            rerun_command=args.rerun_cmd,
            auto_approve=args.yes,
            bridge_url=args.bridge_url,
        )
        sys.exit(0 if success else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
