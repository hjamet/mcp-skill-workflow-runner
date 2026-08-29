"""
FastMCP Server for mcp-skill-workflow-runner.

Exposes 3 deterministic progressive disclosure MCP tools over stdio JSON-RPC:
1. `start_workflow`: Resolves skill, validates DAG, creates atomic session, returns Step 1 directive envelope.
2. `next_step`: Records step output, evaluates conditional DAG transitions/loops, returns next Step directive envelope.
3. `end_workflow`: Closes session, computes metrics, and produces execution audit report.

Zero silent fallback: All errors raise explicit typed exceptions.
Logs are strictly directed to sys.stderr to maintain JSON-RPC stdio protocol integrity.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional, Union

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from mcp_skill_workflow_runner.dag_engine import DAGEngine
from mcp_skill_workflow_runner.exceptions import (
    SessionError,
    SessionNotFoundError,
    WorkflowRunnerError,
)
from mcp_skill_workflow_runner.models import WorkflowSessionState
from mcp_skill_workflow_runner.parser import parse_workflow_file
from mcp_skill_workflow_runner.resolver import resolve_skill_file
from mcp_skill_workflow_runner.session_manager import SessionManager
from mcp_skill_workflow_runner.validator import validate_workflow

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [FastMCP] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Global singleton engine and session manager instances
session_mgr = SessionManager()
dag_engine = DAGEngine(max_cycles_alert=50)


def _get_active_session() -> WorkflowSessionState:
    """
    Retrieves the single active in-progress session.
    - If exactly one active session exists, returns it.
    - If multiple active sessions exist, auto-selects the most recently updated session.
    - If no active session exists, raises SessionNotFoundError.
    """
    active_sessions = session_mgr.list_sessions(status_filter="in_progress")
    if not active_sessions:
        msg = "No active workflow session found. Please invoke 'start_workflow' to begin a workflow."
        logger.error(msg)
        raise SessionNotFoundError(session_id="<active_session>")

    if len(active_sessions) == 1:
        return active_sessions[0]

    # Sort descending by updated_at and pick the most recent active session
    active_sessions.sort(key=lambda s: s.updated_at, reverse=True)
    chosen = active_sessions[0]
    logger.warning(
        f"Multiple active sessions found ({[s.session_id for s in active_sessions]}). "
        f"Auto-selected most recent session '{chosen.session_id}'."
    )
    return chosen


def create_server(name: str = "skill-workflow-runner") -> FastMCP:
    """
    Factory function creating and configuring the FastMCP server with the 3 core workflow tools.
    """
    mcp = FastMCP(name)

    @mcp.tool()
    def start_workflow(
        skill_name: str,
        workspace_dir: str,
        restart: bool = False,
        initial_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Start a new workflow execution for a given skill name or file path within a specified workspace directory.

        Resolves the SKILL.md/workflow.md file taking workspace_dir as top priority (.agent/skills/, .agents/skills/, skills/),
        parses YAML frontmatter and Markdown sections, validates DAG graph connectivity, manages the single active session,
        and returns the Step 1 directive envelope.

        :param skill_name: Name of the skill (e.g. 'work', 'scout') or path to SKILL.md.
        :param workspace_dir: Root directory of the target workspace / repository (e.g. 'c:/Users/hjamet/Documents/VoiceNotes').
        :param restart: If True, resets/aborts any active session and creates a fresh one. If False and an active session exists for this workflow, reuses it.
        :param initial_context: Optional initial context variables (e.g. {'mode': 'B', 'project': 'VoiceNotes'}).
        :return: Deterministic Progressive Disclosure StepResultEnvelope dictionary.
        """
        try:
            logger.info(f"Starting workflow '{skill_name}' in workspace '{workspace_dir}' (restart={restart})")
            skill_path = resolve_skill_file(skill_name=skill_name, workspace_dir=workspace_dir)
            workflow_def = parse_workflow_file(skill_path)
            validate_workflow(workflow_def)

            active_sessions = session_mgr.list_sessions(status_filter="in_progress")

            # Handle restart = True: abort/clean up any existing active sessions
            if restart and active_sessions:
                for s in active_sessions:
                    try:
                        session_mgr.close_session(
                            session_id=s.session_id,
                            status="aborted",
                            final_summary=f"Restarted by start_workflow for '{workflow_def.name}'.",
                        )
                    except Exception as exc:
                        logger.warning(f"Could not abort session '{s.session_id}': {exc}")

            # Handle restart = False: check if active session already exists for this workflow
            elif not restart and active_sessions:
                active_sessions.sort(key=lambda s: s.updated_at, reverse=True)
                active = active_sessions[0]
                if active.workflow_name == workflow_def.name:
                    logger.info(
                        f"Reusing existing active session '{active.session_id}' for workflow '{workflow_def.name}' "
                        f"at step '{active.current_step_id}'."
                    )
                    if initial_context:
                        active.context.update(initial_context)
                        session_mgr.save_session(active)
                    envelope = dag_engine.build_step_envelope(
                        session=active,
                        workflow=workflow_def,
                        message=f"Resuming existing active session '{active.session_id}' for workflow '{workflow_def.name}' at step '{active.current_step_id}'.",
                    )
                    return envelope.model_dump()
                else:
                    # Different workflow active: close previous and start new
                    for s in active_sessions:
                        try:
                            session_mgr.close_session(
                                session_id=s.session_id,
                                status="aborted",
                                final_summary=f"Superseded by new workflow '{workflow_def.name}'.",
                            )
                        except Exception as exc:
                            logger.warning(f"Could not abort session '{s.session_id}': {exc}")

            # Create brand new session
            session = session_mgr.create_session(
                workflow=workflow_def,
                context=initial_context,
                skill_file_path=str(skill_path),
                workspace_dir=str(workspace_dir) if workspace_dir else "",
            )

            envelope = dag_engine.build_step_envelope(
                session=session,
                workflow=workflow_def,
                message=f"Workflow '{workflow_def.name}' initialized at entrypoint step '{workflow_def.initial_step}'.",
            )
            return envelope.model_dump()
        except WorkflowRunnerError as exc:
            logger.error(f"start_workflow failed for '{skill_name}': {exc}")
            raise
        except Exception as exc:
            msg = f"Unexpected error while starting workflow '{skill_name}': {exc}"
            logger.error(msg)
            raise WorkflowRunnerError(msg, details={"skill_name": skill_name, "error": str(exc)}) from exc

    @mcp.tool()
    def next_step(
        user_response: Optional[str] = None,
        step_output: Optional[Union[str, dict[str, Any]]] = None,
        transition_choice: Optional[str] = None,
        variables: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Advance the active workflow to the next step based on step deliverables and DAG transitions.

        Records the current step deliverable, updates context variables, evaluates conditional
        branches or default transitions, increments cycle count if looping, and returns the next step directive envelope.

        :param user_response: Response or text output from the completed step.
        :param step_output: Alternative or structured output payload from the completed step.
        :param transition_choice: Explicit choice among declared step transitions.
        :param variables: Context updates to record in the session state.
        :return: Next Step directive envelope dictionary, or completion report if finished.
        """
        try:
            session = _get_active_session()
            target_sid = session.session_id

            if session.status != "in_progress":
                msg = f"Cannot advance session '{target_sid}': session status is '{session.status}'."
                logger.error(msg)
                raise SessionError(msg, details={"session_id": target_sid, "status": session.status})

            # Load workflow definition from skill_file_path
            skill_path = Path(session.skill_file_path)
            if not skill_path.exists():
                skill_path = resolve_skill_file(session.workflow_name, workspace_dir=session.workspace_dir or None)
            workflow_def = parse_workflow_file(skill_path)

            # Consolidate outputs and variable updates
            output_to_record: Optional[Any] = user_response if user_response is not None else step_output
            context_updates: dict[str, Any] = dict(variables or {})
            if isinstance(step_output, dict):
                context_updates.update(step_output)

            # Evaluate next step via DAG engine
            next_step_id, is_loop_restart = dag_engine.resolve_next_step(
                session=session,
                workflow=workflow_def,
                transition_choice=transition_choice,
                variables=context_updates,
            )

            # Update session state
            updated_session = session_mgr.update_step(
                session_id=target_sid,
                next_step_id=next_step_id,
                output_summary=output_to_record,
                is_loop_restart=is_loop_restart,
                transition_taken=transition_choice or next_step_id,
                context_updates=context_updates,
                workflow=workflow_def,
            )

            # Check if workflow terminated
            if next_step_id is None:
                closure = session_mgr.close_session(
                    session_id=target_sid,
                    status="completed",
                    final_summary=str(output_to_record or "Workflow reached completion."),
                )
                return {
                    "session_id": target_sid,
                    "workflow_name": workflow_def.name,
                    "status": "completed",
                    "message": f"Workflow '{workflow_def.name}' completed all steps successfully.",
                    "closure_report": closure,
                }

            # Return progressive disclosure envelope for the new active step
            envelope = dag_engine.build_step_envelope(
                session=updated_session,
                workflow=workflow_def,
            )
            return envelope.model_dump()
        except WorkflowRunnerError as exc:
            logger.error(f"next_step failed: {exc}")
            raise
        except Exception as exc:
            msg = f"Unexpected error during next_step execution: {exc}"
            logger.error(msg)
            raise WorkflowRunnerError(msg, details={"error": str(exc)}) from exc

    @mcp.tool()
    def end_workflow(
        final_summary: Optional[str] = None,
        status: str = "completed",
    ) -> dict[str, Any]:
        """
        Close the active workflow session with a final status and obtain a complete execution report.

        :param final_summary: Final wrap-up summary or conclusion text.
        :param status: Closure status ('completed', 'aborted', 'paused', 'failed'). Default: 'completed'.
        :return: Comprehensive execution report dictionary with duration, step history, and metrics.
        """
        try:
            session = _get_active_session()
            target_sid = session.session_id
            report = session_mgr.close_session(
                session_id=target_sid,
                status=status,
                final_summary=final_summary,
            )
            return report
        except WorkflowRunnerError as exc:
            logger.error(f"end_workflow failed: {exc}")
            raise
        except Exception as exc:
            msg = f"Unexpected error during end_workflow: {exc}"
            logger.error(msg)
            raise WorkflowRunnerError(msg, details={"error": str(exc)}) from exc
    return mcp


# Default application instance
app = create_server()
mcp = app


def main() -> None:
    """Run FastMCP server over stdio transport."""
    logger.info("Starting FastMCP stdio server for skill-workflow-runner...")
    app.run()


if __name__ == "__main__":
    main()
