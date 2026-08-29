"""
Interactive CLI for mcp-skill-workflow-runner using Click and Rich.

Commands:
- `skill-workflow validate <path_or_name>`: Validates YAML frontmatter, Markdown sections, and DAG connectivity.
- `skill-workflow run <path_or_name>`: Interactive CLI execution of a workflow step-by-step.
- `skill-workflow list`: Discovers and catalog-lists all workspace and global workflows.
- `skill-workflow sessions`: Displays active and historical workflow sessions.
- `skill-workflow serve`: Launches the FastMCP stdio server.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import click
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from mcp_skill_workflow_runner.dag_engine import DAGEngine
from mcp_skill_workflow_runner.exceptions import WorkflowRunnerError
from mcp_skill_workflow_runner.parser import parse_workflow_file
from mcp_skill_workflow_runner.resolver import discover_all_workflows, resolve_skill_file
from mcp_skill_workflow_runner.server import app as mcp_app
from mcp_skill_workflow_runner.session_manager import SessionManager
from mcp_skill_workflow_runner.validator import validate_workflow

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

console = Console(force_terminal=True, legacy_windows=False)
err_console = Console(stderr=True, force_terminal=True, legacy_windows=False)


@click.group()
@click.version_option(version="0.1.0", prog_name="skill-workflow")
def main() -> None:
    """mcp-skill-workflow-runner: Deterministic Progressive Disclosure Workflow Runner for Antigravity."""
    pass


@main.command(name="validate")
@click.argument("target", required=True)
@click.option("--workspace", "-w", default=None, help="Workspace root directory to search for local skills.")
def validate_cmd(target: str, workspace: Optional[str]) -> None:
    """
    Validate a workflow file or skill by name for syntax, sections, and DAG connectivity.
    """
    try:
        file_path = resolve_skill_file(target, workspace_dir=workspace)
        console.print(f"[bold cyan]🔍 Resolving workflow:[/bold cyan] {file_path}")

        workflow = parse_workflow_file(file_path)
        validate_workflow(workflow)

        # Build Summary Table
        table = Table(
            title=f"Workflow: [bold green]{workflow.name}[/bold green] (v{workflow.version})",
            box=box.ROUNDED,
            show_lines=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Step ID", style="bold cyan", width=22)
        table.add_column("Title & Type", style="white", width=30)
        table.add_column("Section Matcher", style="yellow", width=18)
        table.add_column("Mandated Tools & Constraints", style="magenta", width=32)
        table.add_column("Transitions / Next", style="green", width=24)

        for idx, step in enumerate(workflow.steps):
            is_initial = "[bold yellow](Initial)[/bold yellow] " if step.id == workflow.initial_step else ""
            tools_str = ", ".join(step.mandated_tools) if step.mandated_tools else "None"
            constraints_str = f"\nConstraints: {len(step.constraints)}" if step.constraints else ""
            tools_and_constraints = f"Tools: {tools_str}{constraints_str}"

            trans_parts: list[str] = []
            if step.next:
                trans_parts.append(f"next ➔ {step.next}")
            for t in step.transitions:
                if t.condition:
                    trans_parts.append(f"if [{t.condition}] ➔ {t.target}")
                elif t.default:
                    trans_parts.append(f"default ➔ {t.default}")
            trans_str = "\n".join(trans_parts) if trans_parts else "[dim]terminal / seq[/dim]"

            table.add_row(
                str(idx + 1),
                f"{is_initial}{step.id}",
                f"{step.title}\n[dim]({step.step_type.value})[/dim]",
                step.section_matcher or "[dim]N/A[/dim]",
                tools_and_constraints,
                trans_str,
            )

        console.print(table)
        console.print(
            Panel(
                f"[bold green]✓ Validation Passed Successfully![/bold green]\n"
                f"Workflow Type: [bold]{workflow.type.value}[/bold] | Total Steps: [bold]{len(workflow.steps)}[/bold]\n"
                f"Description: {workflow.description or '[dim]None[/dim]'}",
                border_style="green",
            )
        )
    except WorkflowRunnerError as exc:
        err_console.print(
            Panel(
                f"[bold red]❌ Validation Failed[/bold red]\n\n"
                f"[bold]Error:[/bold] {exc.message}\n"
                f"[dim]Details: {exc.details}[/dim]",
                border_style="red",
            )
        )
        sys.exit(1)
    except Exception as exc:
        err_console.print(
            Panel(
                f"[bold red]❌ Unexpected Error During Validation[/bold red]\n\n{exc}",
                border_style="red",
            )
        )
        sys.exit(1)


@main.command(name="list")
@click.option("--workspace", "-w", default=None, help="Workspace root directory to search.")
def list_cmd(workspace: Optional[str]) -> None:
    """
    List all skills and workflows detected in workspace and global Antigravity vaults.
    """
    workflows = discover_all_workflows(workspace_dir=workspace)

    table = Table(
        title=f"Discovered Workflows ({len(workflows)} found)",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Workflow Name", style="bold cyan", width=22)
    table.add_column("Scope", style="yellow", width=12)
    table.add_column("Type", style="magenta", width=12)
    table.add_column("Steps", style="cyan", width=8, justify="right")
    table.add_column("Status", style="green", width=12)
    table.add_column("File Path", style="dim", width=45)

    for wf in workflows:
        status_str = "[bold green]Valid[/bold green]" if wf["valid"] else f"[bold red]Invalid[/bold red]"
        table.add_row(
            wf["name"],
            f"[{'blue' if wf['scope'] == 'workspace' else 'magenta'}]{wf['scope']}[/]",
            wf["workflow_type"],
            str(wf["total_steps"]),
            status_str,
            wf["file_path"],
        )

    console.print(table)


@main.command(name="sessions")
@click.option("--status", "-s", default=None, help="Filter by status: in_progress, completed, aborted.")
def sessions_cmd(status: Optional[str]) -> None:
    """
    List active and persistent workflow execution sessions.
    """
    session_mgr = SessionManager()
    sessions = session_mgr.list_sessions(status_filter=status)

    if not sessions:
        console.print("[yellow]No sessions found matching filter.[/yellow]")
        return

    table = Table(
        title=f"Workflow Sessions ({len(sessions)} found)",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Session ID", style="bold cyan", width=26)
    table.add_column("Workflow", style="bold green", width=18)
    table.add_column("Current Step", style="yellow", width=22)
    table.add_column("Cycle", style="magenta", width=8, justify="center")
    table.add_column("Status", style="white", width=14)
    table.add_column("Updated At", style="dim", width=24)

    for s in sessions:
        status_color = "green" if s.status == "in_progress" else "dim"
        table.add_row(
            s.session_id,
            s.workflow_name,
            s.current_step_id,
            str(s.cycle_number),
            f"[{status_color}]{s.status}[/]",
            s.updated_at,
        )

    console.print(table)


@main.command(name="run")
@click.argument("target", required=True)
@click.option("--workspace", "-w", default=None, help="Workspace root directory.")
@click.option("--session-id", "-s", default=None, help="Custom session ID.")
@click.option("--restart", "-r", is_flag=True, default=False, help="Restart existing session.")
def run_cmd(target: str, workspace: Optional[str], session_id: Optional[str], restart: bool) -> None:
    """
    Interactively execute a workflow step-by-step in the terminal.
    """
    try:
        file_path = resolve_skill_file(target, workspace_dir=workspace)
        workflow = parse_workflow_file(file_path)
        validate_workflow(workflow)

        session_mgr = SessionManager()
        dag_engine = DAGEngine()

        sid = session_id.strip() if session_id else None
        if restart and sid:
            try:
                session_mgr.delete_session(sid)
            except Exception:
                pass

        session = session_mgr.create_session(
            workflow=workflow,
            session_id=sid,
            skill_file_path=str(file_path),
        )

        console.print(
            Panel(
                f"[bold green]▶ Workflow Execution Started[/bold green]\n"
                f"Workflow: [bold]{workflow.name}[/bold] | Session: [bold cyan]{session.session_id}[/bold cyan]\n"
                f"File: [dim]{file_path}[/dim]",
                border_style="green",
            )
        )

        while session.status == "in_progress":
            envelope = dag_engine.build_step_envelope(session=session, workflow=workflow)
            step_info = envelope.current_step

            # Render Step Panel
            step_content: list[str] = [
                f"[bold yellow]Étape :[/bold yellow] {step_info.title} [dim]({step_info.id})[/dim]",
                f"[bold]Type :[/bold] {step_info.step_type} | [bold]Progression :[/bold] {envelope.progress.percentage}% (Cycle {envelope.cycle_number})",
            ]

            if step_info.mandated_tools:
                step_content.append(f"[bold magenta]Outils Mandatés :[/bold magenta] {', '.join(step_info.mandated_tools)}")
            if step_info.constraints:
                step_content.append("[bold red]Contraintes :[/bold red]\n" + "\n".join(f"  • {c}" for c in step_info.constraints))

            if step_info.instructions_markdown:
                step_content.append("\n[bold cyan]--- Instructions Étape ---[/bold cyan]")
                step_content.append(step_info.instructions_markdown)

            console.print(
                Panel(
                    "\n".join(step_content),
                    title=f"Étape Active : {step_info.id}",
                    border_style="cyan",
                )
            )

            # Check if interactive actions
            allowed = step_info.allowed_transitions
            choice_str = ", ".join(allowed) if allowed else "Terminer (Fin de workflow)"
            console.print(f"[bold green]Transitions autorisées :[/bold green] {choice_str}")

            user_output = Prompt.ask("\n[bold]Entrez le livrable / compte-rendu de cette étape[/bold] (ou appuyez sur Entrée)", default="")
            
            selected_transition: Optional[str] = None
            if len(allowed) > 1:
                selected_transition = Prompt.ask(
                    "[bold yellow]Choisissez la transition cible[/bold yellow]",
                    choices=allowed,
                    default=allowed[0],
                )
            elif len(allowed) == 1:
                selected_transition = allowed[0]

            # Advance
            next_step_id, is_loop = dag_engine.resolve_next_step(
                session=session,
                workflow=workflow,
                transition_choice=selected_transition,
            )

            session = session_mgr.update_step(
                session_id=session.session_id,
                next_step_id=next_step_id,
                output_summary=user_output,
                is_loop_restart=is_loop,
                transition_taken=selected_transition,
                workflow=workflow,
            )

            if next_step_id is None:
                report = session_mgr.close_session(
                    session_id=session.session_id,
                    status="completed",
                    final_summary=user_output or "Workflow execution finished naturally.",
                )
                console.print(
                    Panel(
                        f"[bold green]🎉 Workflow Terminé avec Succès ![/bold green]\n\n"
                        f"Durée : [bold]{report['duration_seconds']}s[/bold]\n"
                        f"Étapes exécutées : [bold]{report['total_steps_executed']}[/bold]\n"
                        f"Cycles franchis : [bold]{report['cycle_count']}[/bold]\n"
                        f"Statut final : [bold green]{report['status']}[/bold green]",
                        border_style="green",
                    )
                )
                break

    except WorkflowRunnerError as exc:
        err_console.print(Panel(f"[bold red]Workflow Error:[/bold red] {exc}", border_style="red"))
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Workflow execution cancelled by user.[/yellow]")
        sys.exit(130)


@main.command(name="serve")
def serve_cmd() -> None:
    """
    Start the FastMCP stdio server for Antigravity integration.
    """
    console.print("[bold cyan]Starting FastMCP stdio server...[/bold cyan]", file=sys.stderr)
    mcp_app.run()


if __name__ == "__main__":
    main()
