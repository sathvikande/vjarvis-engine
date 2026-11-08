"""
AI Triage Integration for vjarvis-engine.
Seamlessly connects EDA regression simulation logs with Google Gemini API or local Ollama
to extract failing contexts, generate strict JSON triage payloads, and drive automated patching.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import httpx

from vjarvis_engine.schemas import BrainTriagePayload

logger = logging.getLogger("vjarvis.ai")

SYSTEM_MANIFEST = """SYSTEM OPERATIONAL MANIFEST: PRINCIPAL AUTONOMOUS VLSI AGENT (vjarvis-engine)
You are "vjarvis-engine", an elite, hardware-native Autonomous Verification Engineer operating within an EDA server workspace.
Your single purpose is to intercept compilation and simulation regression failures, isolate protocol/testbench defects, and engineer precise code fixes.

ABSOLUTE RESTRICTION: Return your analysis EXCLUSIVELY as a single, perfectly validated JSON object.
NO markdown code fences, NO backticks, NO commentary.

Output Schema:
{
  "analysis": "Dense, technically rigorous description detailing the exact structural cause of the error or timing protocol violation.",
  "original_exact_line": "The exact, character-for-character code string current inside the target source file that must be removed.",
  "fixed_exact_line": "The precise, executable SystemVerilog or UVM code string replacement that corrects the failure state.",
  "confidence_score": 0.00
}

If telemetry is insufficient, return:
{
  "analysis": "Inconclusive: Telemetry insufficient. Requires detailed waveform analysis.",
  "original_exact_line": "",
  "fixed_exact_line": "",
  "confidence_score": 0.00
}
"""


def call_gemini_api(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> BrainTriagePayload:
    """
    Calls Google Gemini REST API directly using zero temperature and strict JSON mode.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    headers = {"Content-Type": "application/json"}
    body = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_MANIFEST}]
        },
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            candidates = result.get("candidates", [])
            if not candidates:
                raise RuntimeError("No candidate response returned from Gemini API.")

            raw_text = candidates[0]["content"]["parts"][0]["text"].strip()
            # Clean possible markdown wrapping if returned
            clean_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()
            data = json.loads(clean_text)
            return BrainTriagePayload(**data)
    except Exception as e:
        logger.error("Gemini API call failed: %s", e)
        raise


def call_ollama_local(
    prompt: str,
    base_url: str = "http://127.0.0.1:11434",
    model: str = "qwen2.5-coder",
) -> BrainTriagePayload:
    """
    Calls a local Ollama instance on air-gapped EDA servers.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "system": SYSTEM_MANIFEST,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.0},
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text}")

            result = resp.json()
            raw_text = result.get("response", "").strip()
            clean_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()
            data = json.loads(clean_text)
            return BrainTriagePayload(**data)
    except Exception as e:
        logger.error("Local Ollama call failed: %s", e)
        raise


def build_triage_prompt(log_content: str, target_file_path: Path) -> str:
    """
    Extracts relevant context from the error log and target source file.
    """
    file_content = target_file_path.read_text(encoding="utf-8", errors="replace")
    return f"""Target Source File: {target_file_path.name}
Full Target File Content:
=========================================
{file_content}
=========================================

Simulation Regression Error Telemetry Log:
=========================================
{log_content}
=========================================

Instructions:
1. Examine the simulation error log and identify the protocol failure, UVM assertion, or syntax defect.
2. Locate the exact single failing line within the source file.
3. Generate the corrected SystemVerilog replacement line.
4. Output strictly according to the required JSON schema.
"""
