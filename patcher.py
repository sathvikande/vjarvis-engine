"""
Component 1: The Dynamic File Patcher & Automated Rollback Engine.
Safely swaps failing SystemVerilog/UVM lines and orchestrates automated verification rollbacks.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from vjarvis_engine.schemas import BrainTriagePayload

logger = logging.getLogger("vjarvis.patcher")


class PatcherError(Exception):
    """Base exception for all patcher failures."""
    pass


class TargetFileNotFoundError(PatcherError):
    """Raised when the specified target file does not exist."""
    pass


class PermissionDeniedError(PatcherError):
    """Raised when read or write permissions are lacking."""
    pass


class LineNotFoundError(PatcherError):
    """Raised when original_exact_line is not found in the target file."""
    pass


@dataclass
class PatchResult:
    """
    Detailed telemetry result of the patch and re-run execution.
    """
    success: bool
    exit_code: int
    rolled_back: bool
    target_file: Path
    backup_file: Path
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None


class FilePatcher:
    """
    Manages safe file patching, character-for-character replacements,
    simulation re-run orchestration, and automated restoration upon regression.
    """

    def __init__(self, keep_backup_on_success: bool = True):
        self.keep_backup_on_success = keep_backup_on_success

    @staticmethod
    def create_backup(target_path: Path) -> Path:
        """
        Creates an identical file snapshot named <filename>.bak.
        Preserves permissions and file modification timestamps.
        """
        backup_path = target_path.with_name(f"{target_path.name}.bak")
        try:
            shutil.copy2(target_path, backup_path)
            logger.info("Created backup snapshot: %s", backup_path)
            return backup_path
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied creating backup snapshot {backup_path}: {e}") from e
        except OSError as e:
            raise PatcherError(f"Failed to create backup snapshot {backup_path}: {e}") from e

    @staticmethod
    def restore_backup(target_path: Path, backup_path: Path) -> None:
        """
        Restores target_path from backup_path character-for-character.
        """
        if not backup_path.exists():
            raise PatcherError(f"Cannot restore: Backup snapshot does not exist at {backup_path}")
        try:
            shutil.copy2(backup_path, target_path)
            logger.warning("Automated rollback executed: restored %s from %s", target_path, backup_path)
        except OSError as e:
            raise PatcherError(f"Fatal: Failed to restore backup snapshot {backup_path} to {target_path}: {e}") from e

    def apply_replacement(self, target_path: Path, original_line: str, fixed_line: str) -> None:
        """
        Locates the exact original_line and safely replaces it with fixed_line.
        Uses atomic file replacement to prevent corruptions during power/IO interruptions.
        """
        if not target_path.is_file():
            raise TargetFileNotFoundError(f"Target file not found: {target_path}")

        # Check read/write permissions
        if not os.access(target_path, os.R_OK):
            raise PermissionDeniedError(f"Read access denied for {target_path}")
        if not os.access(target_path, os.W_OK):
            raise PermissionDeniedError(f"Write access denied for {target_path}")

        # Read contents with newline preservation
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace", newline="") as f:
                content = f.read()
        except OSError as e:
            raise PatcherError(f"Error reading file {target_path}: {e}") from e

        # Ensure target line exists
        if original_line not in content:
            raise LineNotFoundError(
                f"Target string not found in {target_path.name}.\n"
                f"Looked for exact match: {repr(original_line)}"
            )

        # Replace exact target string
        new_content = content.replace(original_line, fixed_line, 1)

        # Atomic write to temporary file inside target directory before rename
        temp_file = None
        try:
            target_dir = target_path.parent
            with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8", newline="") as tf:
                temp_file = Path(tf.name)
                tf.write(new_content)
                tf.flush()
                os.fsync(tf.fileno())

            # Atomic swap
            os.replace(temp_file, target_path)
            logger.info("Successfully patched %s", target_path)
        except OSError as e:
            if temp_file and temp_file.exists():
                temp_file.unlink(missing_ok=True)
            raise PatcherError(f"Failed to atomically write patched content to {target_path}: {e}") from e

    def patch_and_verify(
        self,
        target_file: str | Path,
        payload: BrainTriagePayload,
        rerun_command: str,
        timeout_seconds: float = 300.0,
    ) -> PatchResult:
        """
        Full transactional patch loop:
        1. Pre-validates payload & target file.
        2. Creates <filename>.bak.
        3. Swaps original_exact_line with fixed_exact_line.
        4. Executes rerun_command.
        5. If exit code != 0 or an error occurs, automatically rolls back <filename>.bak.
        """
        target_path = Path(target_file).resolve()
        if not target_path.is_file():
            raise TargetFileNotFoundError(f"Target file does not exist: {target_path}")

        if not payload.is_conclusive:
            return PatchResult(
                success=False,
                exit_code=-1,
                rolled_back=False,
                target_file=target_path,
                backup_file=target_path.with_name(f"{target_path.name}.bak"),
                error_message=f"Inconclusive telemetry payload: {payload.analysis}",
            )

        # Step 1: Create Backup
        backup_path = self.create_backup(target_path)

        # Step 2: Apply Patch
        try:
            self.apply_replacement(
                target_path=target_path,
                original_line=payload.original_exact_line,
                fixed_line=payload.fixed_exact_line,
            )
        except Exception as patch_err:
            # If replacement fails, ensure state remains clean
            logger.error("Failed to apply replacement on %s: %s", target_path, patch_err)
            self.restore_backup(target_path, backup_path)
            return PatchResult(
                success=False,
                exit_code=-1,
                rolled_back=True,
                target_file=target_path,
                backup_file=backup_path,
                error_message=str(patch_err),
            )

        # Step 3: Simulation Re-Run Execution
        logger.info("Executing simulation re-run command: %s", rerun_command)
        try:
            proc = subprocess.run(
                rerun_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as te:
            logger.error("Simulation re-run timed out after %s seconds", timeout_seconds)
            exit_code = 124
            stdout = te.stdout or "" if isinstance(te.stdout, str) else ""
            stderr = f"TIMEOUT: Execution exceeded {timeout_seconds}s"
        except Exception as exec_err:
            logger.error("Failed executing re-run command: %s", exec_err)
            exit_code = 1
            stdout = ""
            stderr = str(exec_err)

        # Step 4: Verification and Rollback Decision
        if exit_code != 0:
            logger.warning(
                "Simulation re-run failed with non-zero exit code (%d). Initiating automated rollback.",
                exit_code,
            )
            self.restore_backup(target_path, backup_path)
            return PatchResult(
                success=False,
                exit_code=exit_code,
                rolled_back=True,
                target_file=target_path,
                backup_file=backup_path,
                stdout=stdout,
                stderr=stderr,
                error_message=f"Simulation re-run failed (exit code {exit_code}). Automated rollback executed.",
            )

        # Step 5: Verification Succeeded
        logger.info("Verification re-run PASSED (exit code 0). Patch validated successfully.")
        if not self.keep_backup_on_success:
            backup_path.unlink(missing_ok=True)

        return PatchResult(
            success=True,
            exit_code=0,
            rolled_back=False,
            target_file=target_path,
            backup_file=backup_path,
            stdout=stdout,
            stderr=stderr,
        )
