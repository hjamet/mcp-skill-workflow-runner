"""
Manual End-to-End Verification Protocol for mcp-skill-workflow-runner.

Simulates 4 critical execution flows:
1. Scenario A: Socratic Infinite Loop Workflow (/work) - 5 steps cycling back to Step 1 with cycle_number=2.
2. Scenario B: Conditional Branching DAG Workflow (/scout) - evaluates context conditions (Mode B).
3. Scenario C: Zero-Tolerance Error Handling - resolution, parse, section matcher, and transition errors.
4. Scenario D: Crash & Atomic State Recovery - in-memory cache clear, seamless JSON disk reload.

Run with:
    python scripts/verify_workflow.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mcp_skill_workflow_runner.dag_engine import DAGEngine
from mcp_skill_workflow_runner.exceptions import (
    InvalidDAGStructureError,
    InvalidTransitionError,
    SectionNotFoundError,
    SessionError,
    SessionNotFoundError,
    WorkflowParseError,
    WorkflowResolutionError,
    WorkflowRunnerError,
)
from mcp_skill_workflow_runner.models import WorkflowDefinition
from mcp_skill_workflow_runner.parser import parse_workflow_content, parse_workflow_file
from mcp_skill_workflow_runner.resolver import discover_all_workflows, resolve_skill_file
from mcp_skill_workflow_runner.server import create_server
from mcp_skill_workflow_runner.session_manager import SessionManager
from mcp_skill_workflow_runner.validator import validate_workflow

console = Console(force_terminal=True, legacy_windows=False)
passed_checks = 0
failed_checks = 0


def record_check(name: str, condition: bool, details: str = "") -> None:
    """Record and print a verification check result."""
    global passed_checks, failed_checks
    if condition:
        passed_checks += 1
        console.print(f"  [bold green][PASS][/bold green] - {name}")
        if details:
            console.print(f"    [dim]{details}[/dim]")
    else:
        failed_checks += 1
        console.print(f"  [bold red][FAIL][/bold red] - {name}")
        if details:
            console.print(f"    [bold red]{details}[/bold red]")


# ============================================================================
# SCENARIO A: Socratic Work Loop (Nominal Loop Workflow)
# ============================================================================
def verify_scenario_a(temp_sessions_dir: Path) -> None:
    console.print("\n[bold cyan]============================================================[/bold cyan]")
    console.print("[bold yellow]>> SCENARIO A: Socratic Work Loop Workflow (/work)[/bold yellow]")
    console.print("[bold cyan]============================================================[/bold cyan]")

    work_example = PROJECT_ROOT / "examples" / "work_skill.md"
    session_mgr = SessionManager(storage_dir=temp_sessions_dir)
    dag_engine = DAGEngine()

    # Step 1: Initialize Workflow
    wf_def = parse_workflow_file(work_example)
    validate_workflow(wf_def)
    record_check("Parse & Validate work_skill.md", wf_def.type.value == "loop" and len(wf_def.steps) == 5)

    session = session_mgr.create_session(
        workflow=wf_def,
        context={"project": "VoiceNotes", "iteration": 1},
        session_id="session-work-001",
        skill_file_path=str(work_example),
    )
    envelope_1 = dag_engine.build_step_envelope(session=session, workflow=wf_def)

    record_check("Session Created & Atomic File Exists", (temp_sessions_dir / "session-work-001.json").exists())
    record_check("Step 1 Initialized", envelope_1.current_step.id == "step_1_exploration")
    record_check("Cycle Number is 1", envelope_1.cycle_number == 1)
    record_check("Mandated Tools present", "view_file" in envelope_1.current_step.mandated_tools)
    record_check("Section Markdown Extracted", "Étape 1" in envelope_1.current_step.instructions_markdown or "Step 1" in envelope_1.current_step.instructions_markdown or len(envelope_1.current_step.instructions_markdown) > 0)

    # Step 2: Transition Step 1 -> Step 2
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    session = session_mgr.update_step(
        session_id="session-work-001",
        next_step_id=next_id,
        output_summary="Candidate questions: [Axe 1: cache coherence, Axe 2: metrics]",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_2 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Transition 1 -> 2 (step_2_scouts)", envelope_2.current_step.id == "step_2_scouts" and not is_loop)
    record_check("Subagent Recommendation in Step 2", envelope_2.current_step.subagent_recommendation is not None)

    # Step 3: Transition Step 2 -> Step 3
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    session = session_mgr.update_step(
        session_id="session-work-001",
        next_step_id=next_id,
        output_summary="Scouts returned: No existing code cache invalidator.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_3 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Transition 2 -> 3 (step_3_ask)", envelope_3.current_step.id == "step_3_ask")

    # Step 4: Transition Step 3 -> Step 4
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    session = session_mgr.update_step(
        session_id="session-work-001",
        next_step_id=next_id,
        output_summary="User answered: Implement LRU cache invalidation strategy.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_4 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Transition 3 -> 4 (step_4_action)", envelope_4.current_step.id == "step_4_action")

    # Step 5: Transition Step 4 -> Step 5
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    session = session_mgr.update_step(
        session_id="session-work-001",
        next_step_id=next_id,
        output_summary="Action subagents completed code and notes updated.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_5 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Transition 4 -> 5 (step_5_loop)", envelope_5.current_step.id == "step_5_loop")

    # Step 6: Loop Restart: Step 5 -> Step 1 (Cycle 2)
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    record_check("Loop Trigger Detected at Step 5", is_loop and next_id == "step_1_exploration")

    session = session_mgr.update_step(
        session_id="session-work-001",
        next_step_id=next_id,
        output_summary="Looping back to Step 1 for next continuous iteration.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_loop = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Back to Step 1 on Cycle 2", envelope_loop.current_step.id == "step_1_exploration")
    record_check("History Contains 6 Recorded Step Transitions", len(session.history) == 6)

    # Step 7: Close Session
    closure_report = session_mgr.close_session(
        session_id="session-work-001",
        status="completed",
        final_summary="Finished 1 full socratic cycle and started cycle 2.",
    )
    record_check("Session Closure Report Generated", closure_report["status"] == "completed")
    record_check("Total Steps Count in Report", closure_report.get("total_steps_executed") == 6)


# ============================================================================
# SCENARIO B: Conditional Branching DAG Workflow (/scout)
# ============================================================================
def verify_scenario_b(temp_sessions_dir: Path) -> None:
    console.print("\n[bold cyan]============================================================[/bold cyan]")
    console.print("[bold yellow]>> SCENARIO B: Conditional Branching DAG Workflow (/scout)[/bold yellow]")
    console.print("[bold cyan]============================================================[/bold cyan]")

    scout_example = PROJECT_ROOT / "examples" / "scout_workflow.md"
    session_mgr = SessionManager(storage_dir=temp_sessions_dir)
    dag_engine = DAGEngine()

    # Step 1: Initialize Workflow with mode='B'
    wf_def = parse_workflow_file(scout_example)
    validate_workflow(wf_def)
    record_check("Parse & Validate scout_workflow.md", wf_def.type.value == "dag")

    session = session_mgr.create_session(
        workflow=wf_def,
        context={"mode": "B", "n_redundancy": 3},
        session_id="session-scout-mode-b",
        skill_file_path=str(scout_example),
    )
    envelope_1 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Scout Initialized at Step 1", envelope_1.current_step.id == "step_1_intake")

    # Step 2: Transition evaluates condition: context.get('mode') == 'B' -> step_2_mode_b
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    record_check("Condition 'mode == B' Routed to step_2_mode_b", next_id == "step_2_mode_b")

    session = session_mgr.update_step(
        session_id="session-scout-mode-b",
        next_step_id=next_id,
        output_summary="Mission intake complete: 3 redundant research agents requested.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_2 = dag_engine.build_step_envelope(session=session, workflow=wf_def)
    record_check("Step 2 Active is step_2_mode_b", envelope_2.current_step.id == "step_2_mode_b")
    record_check("Step 2 Type is subagent_barrier", str(envelope_2.current_step.step_type) == "subagent_barrier")

    # Step 3: Transition to step_3_synthesis
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    record_check("Transition to step_3_synthesis", next_id == "step_3_synthesis")
    session = session_mgr.update_step(
        session_id="session-scout-mode-b",
        next_step_id=next_id,
        output_summary="Parallel agents A, B, C completed independent explorations.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )

    # Step 4: Transition to step_4_deliverable (Terminal)
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    record_check("Transition to step_4_deliverable", next_id == "step_4_deliverable")
    session = session_mgr.update_step(
        session_id="session-scout-mode-b",
        next_step_id=next_id,
        output_summary="Synthesized cross-agent findings.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )

    # Step 5: Terminal step resolution returns None
    next_id, is_loop = dag_engine.resolve_next_step(session=session, workflow=wf_def)
    record_check("Terminal Step Produces next_step_id=None", next_id is None)

    closure = session_mgr.close_session(
        session_id="session-scout-mode-b",
        status="completed",
        final_summary="exploration_report.md generated successfully.",
    )
    record_check("Scout DAG Completed Cleanly", closure["status"] == "completed")


# ============================================================================
# SCENARIO C: Zero-Tolerance Error Handling & Typed Exceptions
# ============================================================================
def verify_scenario_c(temp_sessions_dir: Path) -> None:
    console.print("\n[bold cyan]============================================================[/bold cyan]")
    console.print("[bold yellow]>> SCENARIO C: Zero-Tolerance Error Handling[/bold yellow]")
    console.print("[bold cyan]============================================================[/bold cyan]")

    session_mgr = SessionManager(storage_dir=temp_sessions_dir)
    dag_engine = DAGEngine()

    # 1. Non-existent skill file -> WorkflowResolutionError
    res_err_caught = False
    try:
        resolve_skill_file("non_existent_skill_xyz_123", workspace_dir=temp_sessions_dir)
    except WorkflowResolutionError as exc:
        res_err_caught = True
        record_check("WorkflowResolutionError Raised for Missing Skill", True, f"Tested paths logged: {len(exc.searched_paths)}")
    except Exception as exc:
        record_check("WorkflowResolutionError Raised for Missing Skill", False, f"Wrong exception: {type(exc)}")
    if not res_err_caught:
        record_check("WorkflowResolutionError Raised for Missing Skill", False, "No exception raised")

    # 2. Malformed YAML Frontmatter -> WorkflowParseError
    bad_yaml = """---
name: broken_yaml
workflow:
  type: loop
  steps: [broken json yaml
---
# Content
"""
    parse_err_caught = False
    try:
        parse_workflow_content(bad_yaml, file_path="broken.md")
    except WorkflowParseError:
        parse_err_caught = True
        record_check("WorkflowParseError Raised on Malformed YAML", True)
    except Exception as exc:
        record_check("WorkflowParseError Raised on Malformed YAML", False, f"Wrong exception: {type(exc)}")
    if not parse_err_caught:
        record_check("WorkflowParseError Raised on Malformed YAML", False, "No exception raised")

    # 3. Missing Markdown Section Header -> SectionNotFoundError
    missing_section_yaml = """---
name: missing_section_test
workflow:
  version: "1.0"
  type: "sequential"
  initial_step: "step_1"
  steps:
    - id: "step_1"
      title: "Step 1"
      section_matcher: "### 99.9 NonExistent Section"
---
# Title

## Real Section
Some content.
"""
    section_err_caught = False
    try:
        wf = parse_workflow_content(missing_section_yaml, file_path="missing_sec.md")
    except SectionNotFoundError as exc:
        section_err_caught = True
        record_check("SectionNotFoundError Raised for Missing Header", True, f"Found headers: {exc.available_sections}")
    except Exception as exc:
        record_check("SectionNotFoundError Raised for Missing Header", False, f"Wrong exception: {type(exc)}")
    if not section_err_caught:
        record_check("SectionNotFoundError Raised for Missing Header", False, "No exception raised")

    # 4. Invalid Target in DAG -> InvalidDAGStructureError
    broken_dag_yaml = """---
name: broken_dag
workflow:
  version: "1.0"
  type: "sequential"
  initial_step: "step_1"
  steps:
    - id: "step_1"
      title: "Step 1"
      next: "step_orphan_target"
---
# Title
"""
    dag_err_caught = False
    try:
        wf = parse_workflow_content(broken_dag_yaml, file_path="broken_dag.md")
        validate_workflow(wf)
    except InvalidDAGStructureError as exc:
        dag_err_caught = True
        record_check("InvalidDAGStructureError Raised for Orphan Next Target", True, str(exc))
    except Exception as exc:
        record_check("InvalidDAGStructureError Raised for Orphan Next Target", False, f"Wrong exception: {type(exc)}")
    if not dag_err_caught:
        record_check("InvalidDAGStructureError Raised for Orphan Next Target", False, "No exception raised")

    # 5. Invalid Transition Choice at Runtime -> InvalidTransitionError
    work_example = PROJECT_ROOT / "examples" / "work_skill.md"
    wf_def = parse_workflow_file(work_example)
    session = session_mgr.create_session(
        workflow=wf_def,
        context={"project": "Test"},
        session_id="session-err-trans",
        skill_file_path=str(work_example),
    )
    trans_err_caught = False
    try:
        dag_engine.resolve_next_step(session=session, workflow=wf_def, transition_choice="forbidden_step_target")
    except InvalidTransitionError:
        trans_err_caught = True
        record_check("InvalidTransitionError Raised for Forbidden Target Choice", True)
    except Exception as exc:
        record_check("InvalidTransitionError Raised for Forbidden Target Choice", False, f"Wrong exception: {type(exc)}")
    if not trans_err_caught:
        record_check("InvalidTransitionError Raised for Forbidden Target Choice", False, "No exception raised")


# ============================================================================
# SCENARIO D: Crash & Atomic State Recovery
# ============================================================================
def verify_scenario_d(temp_sessions_dir: Path) -> None:
    console.print("\n[bold cyan]============================================================[/bold cyan]")
    console.print("[bold yellow]>> SCENARIO D: Crash & Atomic State Recovery[/bold yellow]")
    console.print("[bold cyan]============================================================[/bold cyan]")

    work_example = PROJECT_ROOT / "examples" / "work_skill.md"
    wf_def = parse_workflow_file(work_example)

    # 1. Create session and execute 2 steps with session_mgr_1
    session_mgr_1 = SessionManager(storage_dir=temp_sessions_dir)
    dag_engine = DAGEngine()

    session_id = "session-crash-recovery-test"
    session_mgr_1.create_session(
        workflow=wf_def,
        context={"project": "VoiceNotes", "checkpoint": "step1_done"},
        session_id=session_id,
        skill_file_path=str(work_example),
    )

    # Advance to Step 2
    session_mgr_1.update_step(
        session_id=session_id,
        next_step_id="step_2_scouts",
        output_summary="Completed step 1 questions.",
        is_loop_restart=False,
        transition_taken="step_2_scouts",
        context_updates={"checkpoint": "step2_active", "scouts_count": 4},
        workflow=wf_def,
    )

    # Verify JSON file on disk
    json_path = temp_sessions_dir / f"{session_id}.json"
    record_check("Atomic JSON File Persisted to Disk", json_path.exists())

    with open(json_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    record_check("Disk JSON Contains Step 2 State", disk_data["current_step_id"] == "step_2_scouts")
    record_check("Disk JSON Contains Updated Context", disk_data["context"].get("scouts_count") == 4)

    # 2. SIMULATE HARD PROCESS CRASH / RESTART:
    # Instantiate completely clean SessionManager with EMPTY in-memory RAM cache
    session_mgr_cold = SessionManager(storage_dir=temp_sessions_dir)
    record_check("Cold SessionManager RAM Cache is Empty", len(session_mgr_cold._sessions) == 0)

    # 3. Reload Session Cold from Disk
    recovered_session = session_mgr_cold.get_session(session_id)
    record_check("Cold Session Reloaded Successfully", recovered_session is not None)
    record_check("Recovered Session ID Matches", recovered_session.session_id == session_id)
    record_check("Recovered Current Step is step_2_scouts", recovered_session.current_step_id == "step_2_scouts")
    record_check("Recovered History Contains 2 Steps", len(recovered_session.history) == 2)
    record_check("Recovered Context Has scouts_count=4", recovered_session.context.get("scouts_count") == 4)

    # 4. Resume Workflow Seamlessly after Crash
    next_id, is_loop = dag_engine.resolve_next_step(session=recovered_session, workflow=wf_def)
    record_check("Post-Crash Next Step Resolved (step_3_ask)", next_id == "step_3_ask")

    resumed_session = session_mgr_cold.update_step(
        session_id=session_id,
        next_step_id=next_id,
        output_summary="Post-crash scout analysis completed.",
        is_loop_restart=is_loop,
        transition_taken=next_id,
        workflow=wf_def,
    )
    envelope_resumed = dag_engine.build_step_envelope(session=resumed_session, workflow=wf_def)
    record_check("Post-Crash Directive Envelope Generated", envelope_resumed.current_step.id == "step_3_ask")
    record_check("Total History Count is Now 3", len(resumed_session.history) == 3)


# ============================================================================
# SCENARIO E: FastMCP Server Tools (No session_id, Single-Project Workflow)
# ============================================================================
def verify_scenario_e(temp_sessions_dir: Path) -> None:
    import asyncio
    import inspect
    import mcp_skill_workflow_runner.server as server_mod

    console.print("\n[bold cyan]============================================================[/bold cyan]")
    console.print("[bold yellow]>> SCENARIO E: FastMCP Server Tools (Zero session_id Argument)[/bold yellow]")
    console.print("[bold cyan]============================================================[/bold cyan]")

    # Isolate session manager storage dir
    server_mod.session_mgr.storage_dir = temp_sessions_dir
    temp_sessions_dir.mkdir(parents=True, exist_ok=True)

    app = server_mod.create_server("test-runner")
    work_example = str((PROJECT_ROOT / "examples" / "work_skill.md").resolve())

    # 1. Inspect FastMCP Tool Function Signatures
    async def run_inspections():
        tools = await app.list_tools()
        tool_names = {t.name for t in tools}
        record_check("FastMCP Exposes 3 Workflow Tools", tool_names == {"start_workflow", "next_step", "end_workflow"})

        for t in tools:
            schema_props = t.input_schema.get("properties", {})
            has_session_id = "session_id" in schema_props
            record_check(f"Tool '{t.name}' has NO 'session_id' in input schema", not has_session_id)

    asyncio.run(run_inspections())

    # 2. Test start_workflow with NO session_id
    async def run_tool_lifecycle():
        # Start workflow
        res1 = await app.call_tool(
            "start_workflow",
            {
                "skill_name": work_example,
                "workspace_dir": str(PROJECT_ROOT),
                "initial_context": {"project": "VoiceNotes"},
            },
        )
        data1 = json.loads(res1.content[0].text) if hasattr(res1, "content") else res1
        record_check("start_workflow tool returned Step 1 envelope", data1["current_step"]["id"] == "step_1_exploration")
        record_check("start_workflow generated active session", data1["session_id"] is not None)
        first_sid = data1["session_id"]

        # Call start_workflow again with restart=False -> Reuses session
        res_reuse = await app.call_tool(
            "start_workflow",
            {
                "skill_name": work_example,
                "workspace_dir": str(PROJECT_ROOT),
                "restart": False,
            },
        )
        data_reuse = json.loads(res_reuse.content[0].text)
        record_check("start_workflow (restart=False) reuses active session", data_reuse["session_id"] == first_sid)

        # Call start_workflow with restart=True -> Aborts previous and creates fresh session
        res_restart = await app.call_tool(
            "start_workflow",
            {
                "skill_name": work_example,
                "workspace_dir": str(PROJECT_ROOT),
                "restart": True,
                "initial_context": {"project": "VoiceNotes"},
            },
        )
        data_restart = json.loads(res_restart.content[0].text)
        fresh_sid = data_restart["session_id"]
        record_check("start_workflow (restart=True) creates fresh session", fresh_sid != first_sid)

        # Verify old session was cleanly aborted
        old_session = server_mod.session_mgr.get_session(first_sid)
        record_check("Previous session status is 'aborted'", old_session.status == "aborted")

        # 3. Test next_step with NO session_id
        res2 = await app.call_tool(
            "next_step",
            {"step_output": "Exploration complete. Questions listed."},
        )
        data2 = json.loads(res2.content[0].text)
        record_check("next_step tool advanced to Step 2 (step_2_scouts)", data2["current_step"]["id"] == "step_2_scouts")
        record_check("next_step operated on active session", data2["session_id"] == fresh_sid)

        # Advance to Step 3
        res3 = await app.call_tool(
            "next_step",
            {"step_output": "Scouts reported results."},
        )
        data3 = json.loads(res3.content[0].text)
        record_check("next_step tool advanced to Step 3 (step_3_ask)", data3["current_step"]["id"] == "step_3_ask")

        # 4. Test end_workflow with NO session_id
        res_end = await app.call_tool(
            "end_workflow",
            {"final_summary": "E2E verification completed successfully.", "status": "completed"},
        )
        data_end = json.loads(res_end.content[0].text)
        record_check("end_workflow tool closed session cleanly", data_end["status"] == "completed")
        record_check("end_workflow report includes history and duration", data_end["total_steps_executed"] == 3 and "duration_seconds" in data_end)

        # 5. Calling next_step or end_workflow when no session is active raises SessionNotFoundError
        no_session_next_err = False
        try:
            await app.call_tool("next_step", {"step_output": "Orphan step"})
        except Exception:
            no_session_next_err = True
        record_check("next_step raises error when no active session exists", no_session_next_err)

        no_session_end_err = False
        try:
            await app.call_tool("end_workflow", {"final_summary": "Orphan end"})
        except Exception:
            no_session_end_err = True
        record_check("end_workflow raises error when no active session exists", no_session_end_err)

    asyncio.run(run_tool_lifecycle())


# ============================================================================
# MAIN PROTOCOL RUNNER
# ============================================================================
def main() -> int:
    global passed_checks, failed_checks

    console.print(
        Panel(
            "[bold white]MCP SKILL WORKFLOW RUNNER - END-TO-END VERIFICATION PROTOCOL[/bold white]\n"
            "[dim]Deterministic Progressive Disclosure & DAG Execution Engine[/dim]",
            border_style="cyan",
        )
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="mcp_wf_verify_"))
    try:
        verify_scenario_a(temp_dir / "sessions_a")
        verify_scenario_b(temp_dir / "sessions_b")
        verify_scenario_c(temp_dir / "sessions_c")
        verify_scenario_d(temp_dir / "sessions_d")
        verify_scenario_e(temp_dir / "sessions_e")

        console.print("\n[bold cyan]============================================================[/bold cyan]")
        console.print("[bold white]VERIFICATION SUMMARY[/bold white]")
        console.print("[bold cyan]============================================================[/bold cyan]")

        summary_table = Table(box=None)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Result", style="bold")

        summary_table.add_row("Total Scenarios Tested", "5 (Loop, DAG, Errors, Crash-Recovery, FastMCP Tools)")
        summary_table.add_row("Total Verification Checks", str(passed_checks + failed_checks))
        summary_table.add_row("Passed Checks", f"[green]{passed_checks}[/green]")
        summary_table.add_row("Failed Checks", f"[red]{failed_checks}[/red]" if failed_checks > 0 else "[green]0[/green]")

        console.print(summary_table)

        if failed_checks == 0:
            console.print(Panel("[bold green]ALL VERIFICATION CHECKS PASSED PERFECTLY![/bold green]", border_style="green"))
            return 0
        else:
            console.print(Panel(f"[bold red]{failed_checks} CHECKS FAILED[/bold red]", border_style="red"))
            return 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
