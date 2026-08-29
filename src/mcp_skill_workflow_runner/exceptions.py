"""
Typed exception hierarchy for the mcp-skill-workflow-runner package.

Zero silent fallback: All errors must be explicitly typed with rich context.
Zero swallowed exceptions: No silent catch or pass.
"""

from __future__ import annotations

from typing import Any


class WorkflowRunnerError(Exception):
    """Base exception for all workflow runner errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class SkillWorkflowException(WorkflowRunnerError):
    """Alias for backwards and architecture plan compatibility."""
    pass


class WorkflowResolutionError(WorkflowRunnerError):
    """Raised when a skill or workflow file cannot be found in searched locations."""

    def __init__(
        self,
        skill_name: str,
        searched_paths: list[str],
        message: str | None = None,
    ) -> None:
        msg = message or (
            f"Workflow/Skill '{skill_name}' could not be resolved. "
            f"Tested paths ({len(searched_paths)}):\n" + "\n".join(f"  - {p}" for p in searched_paths)
        )
        super().__init__(msg, details={"skill_name": skill_name, "searched_paths": searched_paths})
        self.skill_name: str = skill_name
        self.searched_paths: list[str] = searched_paths


class WorkflowParseError(WorkflowRunnerError):
    """Raised when YAML frontmatter or Markdown structure cannot be parsed."""

    def __init__(
        self,
        message: str,
        file_path: str | None = None,
        line: int | None = None,
        raw_snippet: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if file_path:
            details["file_path"] = file_path
        if line is not None:
            details["line"] = line
        if raw_snippet:
            details["raw_snippet"] = raw_snippet
        super().__init__(message, details=details)
        self.file_path: str | None = file_path
        self.line: int | None = line
        self.raw_snippet: str | None = raw_snippet


class WorkflowSchemaError(WorkflowRunnerError):
    """Raised when workflow data fails Pydantic schema validation."""

    def __init__(
        self,
        message: str,
        validation_errors: list[dict[str, Any]] | None = None,
        file_path: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "validation_errors": validation_errors or [],
            "file_path": file_path,
        }
        super().__init__(message, details=details)
        self.validation_errors: list[dict[str, Any]] = validation_errors or []
        self.file_path: str | None = file_path


class SectionNotFoundError(WorkflowRunnerError):
    """Raised when a section_matcher does not match any Markdown H2/H3 header in the file."""

    def __init__(
        self,
        section_matcher: str,
        step_id: str,
        available_sections: list[str],
        file_path: str | None = None,
    ) -> None:
        msg = (
            f"Section matching '{section_matcher}' for step '{step_id}' was not found in "
            f"'{file_path or '<unknown>'}'. Available sections ({len(available_sections)}):\n"
            + "\n".join(f"  - '{sec}'" for sec in available_sections)
        )
        details = {
            "section_matcher": section_matcher,
            "step_id": step_id,
            "available_sections": available_sections,
            "file_path": file_path,
        }
        super().__init__(msg, details=details)
        self.section_matcher: str = section_matcher
        self.step_id: str = step_id
        self.available_sections: list[str] = available_sections
        self.file_path: str | None = file_path


class InvalidDAGStructureError(WorkflowRunnerError):
    """Raised when the workflow DAG is structurally invalid (broken transitions, unreachable steps, etc.)."""

    def __init__(
        self,
        message: str,
        workflow_name: str | None = None,
        step_ids: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        d = dict(details or {})
        if workflow_name:
            d["workflow_name"] = workflow_name
        if step_ids:
            d["step_ids"] = step_ids
        super().__init__(message, details=d)
        self.workflow_name: str | None = workflow_name
        self.step_ids: list[str] | None = step_ids


class TransitionEvaluationError(WorkflowRunnerError):
    """Raised when evaluating a transition condition fails or no branch matches without a default."""

    def __init__(
        self,
        message: str,
        step_id: str | None = None,
        condition: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        details = {
            "step_id": step_id,
            "condition": condition,
            "context": context or {},
        }
        super().__init__(message, details=details)
        self.step_id: str | None = step_id
        self.condition: str | None = condition
        self.context: dict[str, Any] = context or {}


class InvalidTransitionError(WorkflowRunnerError):
    """Raised when an invalid transition or jump target is requested."""

    def __init__(
        self,
        current_step_id: str,
        requested_target: str,
        allowed_targets: list[str],
        reason: str | None = None,
    ) -> None:
        msg = (
            f"Invalid transition from step '{current_step_id}' to target '{requested_target}'. "
            f"Allowed transitions: {allowed_targets}"
        )
        if reason:
            msg += f" (Reason: {reason})"
        details = {
            "current_step_id": current_step_id,
            "requested_target": requested_target,
            "allowed_targets": allowed_targets,
            "reason": reason,
        }
        super().__init__(msg, details=details)
        self.current_step_id: str = current_step_id
        self.requested_target: str = requested_target
        self.allowed_targets: list[str] = allowed_targets
        self.reason: str | None = reason


class SessionError(WorkflowRunnerError):
    """Base exception for workflow session errors."""
    pass


class SessionNotFoundError(SessionError):
    """Raised when a requested session ID does not exist."""

    def __init__(self, session_id: str) -> None:
        super().__init__(
            f"Workflow session '{session_id}' was not found in memory or disk storage.",
            details={"session_id": session_id},
        )
        self.session_id: str = session_id


class SessionCorruptedError(SessionError):
    """Raised when a session file on disk cannot be deserialized or is corrupted."""

    def __init__(self, session_id: str, file_path: str, reason: str) -> None:
        super().__init__(
            f"Workflow session '{session_id}' file at '{file_path}' is corrupted: {reason}",
            details={"session_id": session_id, "file_path": file_path, "reason": reason},
        )
        self.session_id: str = session_id
        self.file_path: str = file_path
        self.reason: str = reason
