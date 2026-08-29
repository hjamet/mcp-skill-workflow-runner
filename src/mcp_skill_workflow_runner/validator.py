"""
Static validator for workflow DAG structure, uniqueness of IDs, target resolvability, and reachability.

Zero silent fallback: all validation failures raise InvalidDAGStructureError with detailed diagnostics.
All error logs are sent to sys.stderr via configured StreamHandler.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from typing import Any

from mcp_skill_workflow_runner.exceptions import InvalidDAGStructureError
from mcp_skill_workflow_runner.models import (
    StepDefinition,
    StepTypeEnum,
    WorkflowDefinition,
    WorkflowTypeEnum,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def _get_outgoing_targets(step: StepDefinition, is_sequential_fallback: bool = False, next_step_id: str | None = None) -> list[str]:
    """Returns all declared target step IDs outgoing from this step."""
    targets: list[str] = []
    if step.next:
        targets.append(step.next)
    for transition in step.transitions:
        if transition.target:
            targets.append(transition.target)
        if transition.default:
            targets.append(transition.default)

    # In sequential workflow, if no explicit next/transitions are set and step is not terminal,
    # fallback to the next step in sequence.
    if is_sequential_fallback and not targets and step.step_type != StepTypeEnum.TERMINAL and next_step_id:
        targets.append(next_step_id)

    return targets


def validate_dag_structure(workflow: WorkflowDefinition) -> None:
    """
    Performs comprehensive static validation on the workflow DAG structure:
    1. Steps non-empty.
    2. Step IDs uniqueness.
    3. Initial step existence.
    4. Target resolvability (next, transitions, defaults).
    5. Terminal step constraints (no outgoing transitions).
    6. Reachability: all steps must be reachable from initial_step.
    7. Loop workflows must contain at least one backward edge.
    """
    if not workflow.steps:
        msg = f"Workflow '{workflow.name}' contains no steps."
        logger.error(msg)
        raise InvalidDAGStructureError(msg, workflow_name=workflow.name)

    # 1. Uniqueness of step IDs
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    step_id_list: list[str] = []
    step_map: dict[str, StepDefinition] = {}

    for idx, step in enumerate(workflow.steps):
        if not step.id or not step.id.strip():
            msg = f"Step at index {idx} in workflow '{workflow.name}' has an empty or blank 'id'."
            logger.error(msg)
            raise InvalidDAGStructureError(msg, workflow_name=workflow.name)

        if step.id in seen_ids:
            duplicate_ids.add(step.id)
        seen_ids.add(step.id)
        step_id_list.append(step.id)
        step_map[step.id] = step

    if duplicate_ids:
        msg = f"Workflow '{workflow.name}' contains duplicate step IDs: {sorted(duplicate_ids)}"
        logger.error(msg)
        raise InvalidDAGStructureError(
            msg,
            workflow_name=workflow.name,
            step_ids=sorted(duplicate_ids),
            details={"duplicate_ids": sorted(duplicate_ids)},
        )

    # 2. Initial step existence
    if workflow.initial_step not in seen_ids:
        msg = (
            f"Initial step '{workflow.initial_step}' does not exist in workflow '{workflow.name}'. "
            f"Available step IDs: {step_id_list}"
        )
        logger.error(msg)
        raise InvalidDAGStructureError(
            msg,
            workflow_name=workflow.name,
            details={"initial_step": workflow.initial_step, "available_steps": step_id_list},
        )

    # 3. Target resolvability and terminal step constraints
    unresolvable_targets: list[dict[str, Any]] = []
    terminal_violations: list[str] = []

    is_sequential = workflow.type == WorkflowTypeEnum.SEQUENTIAL

    for idx, step in enumerate(workflow.steps):
        next_step_in_sequence = step_id_list[idx + 1] if idx + 1 < len(step_id_list) else None
        outgoing = _get_outgoing_targets(step, is_sequential_fallback=is_sequential, next_step_id=next_step_in_sequence)

        # Check terminal step violation
        if step.step_type == StepTypeEnum.TERMINAL:
            # Explicit transitions or next are forbidden on terminal steps
            if step.next is not None or len(step.transitions) > 0:
                terminal_violations.append(step.id)

        # Check that all outgoing targets exist
        for target in outgoing:
            if target not in seen_ids:
                unresolvable_targets.append({
                    "from_step": step.id,
                    "invalid_target": target,
                })

    if terminal_violations:
        msg = (
            f"Steps declared as 'terminal' in workflow '{workflow.name}' must not define outgoing transitions: "
            f"{terminal_violations}"
        )
        logger.error(msg)
        raise InvalidDAGStructureError(
            msg,
            workflow_name=workflow.name,
            step_ids=terminal_violations,
            details={"terminal_violations": terminal_violations},
        )

    if unresolvable_targets:
        msg = (
            f"Workflow '{workflow.name}' contains unresolvable transition target(s): {unresolvable_targets}. "
            f"Available step IDs: {step_id_list}"
        )
        logger.error(msg)
        raise InvalidDAGStructureError(
            msg,
            workflow_name=workflow.name,
            details={"unresolvable_targets": unresolvable_targets, "available_steps": step_id_list},
        )

    # 4. Reachability: BFS from initial_step
    reachable_steps: set[str] = set()
    queue: deque[str] = deque([workflow.initial_step])

    while queue:
        current_id = queue.popleft()
        if current_id in reachable_steps:
            continue
        reachable_steps.add(current_id)

        curr_step = step_map[current_id]
        curr_idx = workflow.step_index(current_id)
        next_in_seq = step_id_list[curr_idx + 1] if curr_idx + 1 < len(step_id_list) else None

        outgoing = _get_outgoing_targets(curr_step, is_sequential_fallback=is_sequential, next_step_id=next_in_seq)
        for target in outgoing:
            if target not in reachable_steps and target in seen_ids:
                queue.append(target)

    unreachable_steps = seen_ids - reachable_steps
    if unreachable_steps:
        msg = (
            f"Workflow '{workflow.name}' has unreachable / orphan step(s) from initial_step '{workflow.initial_step}': "
            f"{sorted(unreachable_steps)}. All declared steps must be connected to the execution graph."
        )
        logger.error(msg)
        raise InvalidDAGStructureError(
            msg,
            workflow_name=workflow.name,
            step_ids=sorted(unreachable_steps),
            details={"unreachable_steps": sorted(unreachable_steps), "initial_step": workflow.initial_step},
        )

    # 5. Loop Workflow requirement: at least one backward edge
    if workflow.type == WorkflowTypeEnum.LOOP:
        has_backward_edge = False
        for idx, step in enumerate(workflow.steps):
            outgoing = _get_outgoing_targets(step, is_sequential_fallback=False)
            for target in outgoing:
                target_idx = workflow.step_index(target)
                if target == workflow.initial_step or (target_idx != -1 and target_idx <= idx):
                    has_backward_edge = True
                    break
            if has_backward_edge:
                break

        if not has_backward_edge:
            msg = (
                f"Workflow '{workflow.name}' is declared with type='loop', but has no transition looping "
                f"back to initial_step ('{workflow.initial_step}') or to an earlier step."
            )
            logger.error(msg)
            raise InvalidDAGStructureError(
                msg,
                workflow_name=workflow.name,
                details={"workflow_type": "loop", "initial_step": workflow.initial_step},
            )


def validate_workflow(workflow: WorkflowDefinition) -> None:
    """Entry point for full workflow validation."""
    validate_dag_structure(workflow)
