"""
Session manager for workflow executions.

Provides in-memory caching paired with atomic JSON disk persistence (`.tmp` write followed by `os.replace`).
Supports thread-safe multi-session management, crash recovery, context schema validation,
step history recording, jumping, and structured session closure.

Zero silent fallback: Corrupted sessions, schema violations, or missing sessions raise explicit typed exceptions.
All logs are directed to sys.stderr.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from mcp_skill_workflow_runner.exceptions import (
    SessionCorruptedError,
    SessionError,
    SessionNotFoundError,
    WorkflowSchemaError,
)
from mcp_skill_workflow_runner.models import (
    ContextFieldSchema,
    StepExecutionRecord,
    WorkflowDefinition,
    WorkflowSessionState,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Default path for persistent workflow sessions
DEFAULT_SESSIONS_DIR = Path.home() / ".gemini" / "antigravity" / "workflow_sessions"


def _get_utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def validate_and_prepare_context(
    context_schema: dict[str, ContextFieldSchema],
    provided_context: Optional[dict[str, Any]] = None,
    workflow_name: str = "",
) -> dict[str, Any]:
    """
    Validates provided context variables against the workflow's context schema.
    Applies defaults, verifies required variables, checks type conformance, and enforces enums.

    Raises WorkflowSchemaError if any constraint is violated. Zero silent fallback.
    """
    raw_context = dict(provided_context or {})
    final_context: dict[str, Any] = {}

    # Check declared schema fields
    for field_name, field_def in context_schema.items():
        val = raw_context.get(field_name)

        if val is None:
            if field_def.default is not None:
                final_context[field_name] = field_def.default
            elif field_def.required:
                msg = (
                    f"Workflow '{workflow_name}' requires context variable '{field_name}', "
                    f"but it was not provided (Schema: {field_def.model_dump()})."
                )
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "error": "missing_required_field"}],
                )
            else:
                final_context[field_name] = None
        else:
            # Enum constraint validation
            if field_def.enum is not None and val not in field_def.enum:
                msg = (
                    f"Context variable '{field_name}' in workflow '{workflow_name}' has invalid value '{val}'. "
                    f"Allowed enum values: {field_def.enum}"
                )
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{
                        "field": field_name,
                        "value": val,
                        "allowed_enum": field_def.enum,
                        "error": "enum_mismatch",
                    }],
                )

            # Basic type validation
            expected_type = (field_def.type or "").lower()
            if expected_type in ("integer", "int") and not isinstance(val, int):
                msg = f"Context variable '{field_name}' must be an integer, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )
            elif expected_type in ("number", "float") and not isinstance(val, (int, float)):
                msg = f"Context variable '{field_name}' must be a number/float, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )
            elif expected_type in ("boolean", "bool") and not isinstance(val, bool):
                msg = f"Context variable '{field_name}' must be a boolean, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )
            elif expected_type in ("string", "str") and not isinstance(val, str):
                msg = f"Context variable '{field_name}' must be a string, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )
            elif expected_type in ("list", "array") and not isinstance(val, list):
                msg = f"Context variable '{field_name}' must be a list, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )
            elif expected_type in ("dict", "object", "mapping") and not isinstance(val, dict):
                msg = f"Context variable '{field_name}' must be a dictionary, got {type(val).__name__} ('{val}')."
                logger.error(msg)
                raise WorkflowSchemaError(
                    message=msg,
                    validation_errors=[{"field": field_name, "value": val, "error": "type_mismatch"}],
                )

            final_context[field_name] = val

    # Include any extra context keys provided by caller (allow flexibility while preserving validated keys)
    for k, v in raw_context.items():
        if k not in final_context:
            final_context[k] = v

    return final_context


class SessionManager:
    """
    Thread-safe workflow session manager with atomic disk persistence.
    """

    def __init__(self, storage_dir: Optional[Path | str] = None) -> None:
        """
        Initialize the session manager.

        :param storage_dir: Optional custom storage directory for workflow sessions JSON files.
        """
        if storage_dir is not None:
            self.storage_dir: Path = Path(storage_dir)
        else:
            env_dir = os.environ.get("WORKFLOW_SESSIONS_DIR")
            self.storage_dir = Path(env_dir) if env_dir else DEFAULT_SESSIONS_DIR

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, WorkflowSessionState] = {}
        self._lock = threading.RLock()

    def _get_session_file_path(self, session_id: str) -> Path:
        """Returns the final JSON path for a given session ID."""
        # Sanitize session_id to prevent path traversal
        clean_id = Path(session_id).name
        return self.storage_dir / f"{clean_id}.json"

    def _get_temp_file_path(self, session_id: str) -> Path:
        """Returns the temporary `.tmp` path used for atomic write operations."""
        clean_id = Path(session_id).name
        return self.storage_dir / f"{clean_id}.tmp"

    def _persist_to_disk_atomic(self, session: WorkflowSessionState) -> Path:
        """
        Persists a session state to disk atomically:
        1. Serializes model to JSON.
        2. Writes to `<session_id>.tmp`.
        3. Flushes and syncs to disk.
        4. Replaces atomically via `os.replace` to `<session_id>.json`.
        """
        target_file = self._get_session_file_path(session.session_id)
        temp_file = self._get_temp_file_path(session.session_id)

        try:
            json_bytes = session.model_dump_json(indent=2).encode("utf-8")

            # Write to temporary file
            with open(temp_file, "wb") as f:
                f.write(json_bytes)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            os.replace(temp_file, target_file)
            return target_file
        except Exception as exc:
            msg = f"Failed to atomically persist session '{session.session_id}' to '{target_file}': {exc}"
            logger.error(msg)
            # Cleanup temp file if it remains
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise SessionError(msg, details={"session_id": session.session_id, "target_file": str(target_file)}) from exc

    def create_session(
        self,
        workflow: WorkflowDefinition,
        context: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
        skill_file_path: str = "",
        workspace_dir: str = "",
    ) -> WorkflowSessionState:
        """
        Initializes a new workflow session state, records the initial step execution entry,
        and saves it atomically to memory and disk.

        :param workflow: The validated WorkflowDefinition.
        :param context: Initial context dictionary provided for the workflow.
        :param session_id: Optional custom session ID. If omitted, a unique ID is generated.
        :param skill_file_path: Resolved path to the skill / workflow source file.
        :param workspace_dir: Root workspace directory for the workflow session.
        :return: The initialized WorkflowSessionState.
        """
        with self._lock:
            # Validate and prepare context variables
            prepared_context = validate_and_prepare_context(
                context_schema=workflow.context_schema,
                provided_context=context,
                workflow_name=workflow.name,
            )

            # Generate session ID if not given
            sid = session_id.strip() if session_id and session_id.strip() else f"wf_{workflow.name}_{uuid.uuid4().hex[:8]}"

            # Ensure initial step exists
            init_step = workflow.get_step(workflow.initial_step)
            if init_step is None:
                msg = f"Initial step '{workflow.initial_step}' not found in workflow '{workflow.name}'."
                logger.error(msg)
                raise SessionError(msg, details={"workflow": workflow.name, "initial_step": workflow.initial_step})

            now_iso = _get_utc_now_iso()
            initial_step_index = workflow.step_index(workflow.initial_step)

            initial_record = StepExecutionRecord(
                step_id=workflow.initial_step,
                step_index=initial_step_index,
                cycle_number=1,
                entered_at=now_iso,
            )

            session = WorkflowSessionState(
                session_id=sid,
                workflow_name=workflow.name,
                skill_file_path=skill_file_path or workflow.file_path,
                workspace_dir=workspace_dir,
                context=prepared_context,
                current_step_id=workflow.initial_step,
                cycle_number=1,
                status="in_progress",
                history=[initial_record],
                created_at=now_iso,
                updated_at=now_iso,
            )

            # Save in memory and disk
            self._sessions[sid] = session
            self._persist_to_disk_atomic(session)

            logger.info(
                f"Created new workflow session '{sid}' for workflow '{workflow.name}' "
                f"at initial step '{workflow.initial_step}'."
            )
            return session

    def get_session(self, session_id: str) -> WorkflowSessionState:
        """
        Retrieves a workflow session by ID.
        Checks RAM cache first, then attempts crash recovery loading from disk.

        Raises SessionNotFoundError if not found.
        Raises SessionCorruptedError if disk file exists but cannot be deserialized.
        """
        clean_id = session_id.strip()
        with self._lock:
            # 1. In-memory check
            if clean_id in self._sessions:
                return self._sessions[clean_id]

            # 2. Disk check (Crash recovery)
            file_path = self._get_session_file_path(clean_id)
            if not file_path.exists():
                logger.error(f"Session '{clean_id}' not found in memory or at '{file_path}'.")
                raise SessionNotFoundError(session_id=clean_id)

            try:
                content = file_path.read_text(encoding="utf-8")
                session = WorkflowSessionState.model_validate_json(content)
                self._sessions[clean_id] = session
                logger.info(f"Successfully recovered session '{clean_id}' from disk '{file_path}'.")
                return session
            except (json.JSONDecodeError, ValidationError, Exception) as exc:
                msg = f"Failed to deserialize session '{clean_id}' from disk file '{file_path}': {exc}"
                logger.error(msg)
                raise SessionCorruptedError(
                    session_id=clean_id,
                    file_path=str(file_path),
                    reason=str(exc),
                ) from exc

    def save_session(self, session: WorkflowSessionState) -> None:
        """
        Explicitly saves a workflow session state to RAM and disk atomically.
        """
        with self._lock:
            session.updated_at = _get_utc_now_iso()
            self._sessions[session.session_id] = session
            self._persist_to_disk_atomic(session)

    def update_step(
        self,
        session_id: str,
        next_step_id: Optional[str],
        output_summary: Optional[Any] = None,
        is_loop_restart: bool = False,
        transition_taken: Optional[str] = None,
        context_updates: Optional[dict[str, Any]] = None,
        workflow: Optional[WorkflowDefinition] = None,
    ) -> WorkflowSessionState:
        """
        Updates session progress to the next step:
        - Closes the active step execution record in `history`.
        - Updates session context with any returned variables.
        - Increments `cycle_number` if `is_loop_restart` is True.
        - Sets new `current_step_id` and adds a new `StepExecutionRecord` (or sets status="completed" if None).
        - Persists state atomically.
        """
        with self._lock:
            session = self.get_session(session_id)
            now_iso = _get_utc_now_iso()

            # 1. Close current step execution record
            if session.history:
                last_record = session.history[-1]
                if last_record.step_id == session.current_step_id and last_record.exited_at is None:
                    last_record.exited_at = now_iso
                    last_record.output_summary = output_summary
                    last_record.transition_taken = transition_taken or next_step_id or "terminal"

            # 2. Update context
            if context_updates:
                session.context.update(context_updates)

            # 3. Handle cycle increment
            if is_loop_restart:
                session.cycle_number += 1
                logger.info(f"Workflow session '{session_id}' cycle count incremented to {session.cycle_number}.")

            # 4. Handle transition target
            if next_step_id is None:
                session.status = "completed"
                logger.info(f"Workflow session '{session_id}' completed successfully after {len(session.history)} step(s).")
            else:
                session.current_step_id = next_step_id
                step_idx = workflow.step_index(next_step_id) if workflow else 0
                new_record = StepExecutionRecord(
                    step_id=next_step_id,
                    step_index=step_idx,
                    cycle_number=session.cycle_number,
                    entered_at=now_iso,
                )
                session.history.append(new_record)

            session.updated_at = now_iso
            self.save_session(session)
            return session

    def jump_step(
        self,
        session_id: str,
        target_step_id: str,
        reason: str,
        workflow: Optional[WorkflowDefinition] = None,
        context_updates: Optional[dict[str, Any]] = None,
    ) -> WorkflowSessionState:
        """
        Forces an administrative or exceptional jump to a specified target step,
        logging the explicit reason in the step audit trail.
        """
        with self._lock:
            session = self.get_session(session_id)
            now_iso = _get_utc_now_iso()

            # Close current step record with jump reason
            if session.history:
                last_record = session.history[-1]
                if last_record.step_id == session.current_step_id and last_record.exited_at is None:
                    last_record.exited_at = now_iso
                    last_record.transition_taken = f"jump: {reason}"

            if context_updates:
                session.context.update(context_updates)

            # Check if jump is a backward loop
            step_idx = workflow.step_index(target_step_id) if workflow else 0
            curr_idx = workflow.step_index(session.current_step_id) if workflow else 0
            if workflow and (target_step_id == workflow.initial_step or step_idx <= curr_idx):
                session.cycle_number += 1

            session.current_step_id = target_step_id
            new_record = StepExecutionRecord(
                step_id=target_step_id,
                step_index=step_idx,
                cycle_number=session.cycle_number,
                entered_at=now_iso,
            )
            session.history.append(new_record)
            session.updated_at = now_iso
            self.save_session(session)

            logger.info(
                f"Session '{session_id}' jumped from '{last_record.step_id if session.history else '<none>'}' "
                f"to '{target_step_id}'. Reason: {reason}"
            )
            return session

    def close_session(
        self,
        session_id: str,
        status: str = "completed",
        final_summary: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Closes a workflow session with a final status, closes any open step record,
        and returns a comprehensive audit summary report.
        """
        with self._lock:
            session = self.get_session(session_id)
            now_iso = _get_utc_now_iso()

            if session.history:
                last_record = session.history[-1]
                if last_record.exited_at is None:
                    last_record.exited_at = now_iso
                    if final_summary:
                        last_record.output_summary = final_summary
                    if not last_record.transition_taken:
                        last_record.transition_taken = f"closed_{status}"

            session.status = status
            session.updated_at = now_iso
            self.save_session(session)

            # Compute execution metrics
            start_dt = datetime.fromisoformat(session.created_at)
            end_dt = datetime.fromisoformat(session.updated_at)
            duration_seconds = round((end_dt - start_dt).total_seconds(), 2)

            summary_report: dict[str, Any] = {
                "session_id": session.session_id,
                "workflow_name": session.workflow_name,
                "workspace_dir": session.workspace_dir,
                "status": session.status,
                "final_step_id": session.current_step_id,
                "cycle_count": session.cycle_number,
                "total_steps_executed": len(session.history),
                "created_at": session.created_at,
                "closed_at": session.updated_at,
                "duration_seconds": duration_seconds,
                "final_summary": final_summary,
                "context": session.context,
                "history": [r.model_dump() for r in session.history],
            }

            logger.info(
                f"Workflow session '{session_id}' closed with status '{status}' "
                f"after {duration_seconds}s across {len(session.history)} step(s)."
            )
            return summary_report

    def list_sessions(self, status_filter: Optional[str] = None) -> list[WorkflowSessionState]:
        """
        Discovers and loads all sessions available from RAM and disk.
        """
        with self._lock:
            found_ids: set[str] = set(self._sessions.keys())

            # Discover all json files on disk
            for json_file in self.storage_dir.glob("*.json"):
                sid = json_file.stem
                found_ids.add(sid)

            all_sessions: list[WorkflowSessionState] = []
            for sid in sorted(found_ids):
                try:
                    s = self.get_session(sid)
                    if status_filter is None or s.status == status_filter:
                        all_sessions.append(s)
                except Exception as exc:
                    logger.warning(f"Could not load session '{sid}': {exc}")

            return all_sessions

    def list_active_sessions(self) -> list[dict[str, Any]]:
        """
        Returns a lightweight summary list of all in-progress active sessions.
        """
        active = self.list_sessions(status_filter="in_progress")
        return [
            {
                "session_id": s.session_id,
                "workflow_name": s.workflow_name,
                "workspace_dir": s.workspace_dir,
                "current_step_id": s.current_step_id,
                "cycle_number": s.cycle_number,
                "status": s.status,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in active
        ]

    def get_single_active_session(self) -> Optional[WorkflowSessionState]:
        """
        Helper to return the single active in-progress session if exactly one exists.
        Returns None if 0 or more than 1 active sessions exist.
        """
        active = self.list_sessions(status_filter="in_progress")
        if len(active) == 1:
            return active[0]
        return None

    def delete_session(self, session_id: str) -> None:
        """
        Permanently removes a session from RAM and deletes its file on disk.
        """
        with self._lock:
            clean_id = session_id.strip()
            self._sessions.pop(clean_id, None)

            target_file = self._get_session_file_path(clean_id)
            if target_file.exists():
                try:
                    target_file.unlink()
                except OSError as exc:
                    msg = f"Failed to delete session file '{target_file}': {exc}"
                    logger.error(msg)
                    raise SessionError(msg, details={"session_id": clean_id, "target_file": str(target_file)}) from exc

            temp_file = self._get_temp_file_path(clean_id)
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
