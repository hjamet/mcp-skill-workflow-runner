"""
DAG execution engine for workflow navigation, sandbox condition evaluation, and cycle management.

Responsible for:
1. Validating and resolving transitions between steps (conditional, default, next, sequential fallback).
2. Secure sandboxed condition evaluation without access to dangerous builtins or modules.
3. Detecting loop restarts, tracking cycles, and alerting when cycle threshold is reached or exceeded.
4. Constructing deterministic progressive disclosure StepResultEnvelope payloads for agents.

Zero silent fallback: All transition evaluation errors or invalid jumps raise explicit typed exceptions.
All logs are directed to sys.stderr.
"""

from __future__ import annotations

import ast
import logging
import sys
from typing import Any, Optional

from mcp_skill_workflow_runner.exceptions import (
    InvalidDAGStructureError,
    InvalidTransitionError,
    TransitionEvaluationError,
)
from mcp_skill_workflow_runner.models import (
    StepDefinition,
    StepDirectiveInfo,
    StepProgressInfo,
    StepResultEnvelope,
    StepTypeEnum,
    WorkflowDefinition,
    WorkflowSessionState,
    WorkflowTypeEnum,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Safe builtins exposed to transition conditions
SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "round": round,
    "set": set,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "True": True,
    "False": False,
    "None": None,
}

# Forbidden AST node types to prevent arbitrary code execution in eval sandbox
FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.Exec if hasattr(ast, "Exec") else type(None),
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.AsyncFunctionDef,
    ast.FunctionDef,
    ast.ClassDef,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
)


def _validate_ast_safety(expr_str: str, step_id: str = "") -> None:
    """
    Parses expression into AST and checks for forbidden operations (imports, dunder attributes, statements).
    Raises TransitionEvaluationError if expression contains unsafe constructs.
    """
    try:
        tree = ast.parse(expr_str, mode="eval")
    except SyntaxError as exc:
        msg = f"Syntax error in transition condition '{expr_str}': {exc}"
        logger.error(msg)
        raise TransitionEvaluationError(
            message=msg,
            step_id=step_id,
            condition=expr_str,
        ) from exc

    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_AST_NODES):
            msg = f"Unsafe construct '{type(node).__name__}' found in transition condition '{expr_str}'."
            logger.error(msg)
            raise TransitionEvaluationError(
                message=msg,
                step_id=step_id,
                condition=expr_str,
            )

        # Disallow access to dangerous dunder attributes like __class__, __subclasses__, __globals__, etc.
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            msg = f"Access to private attribute '{node.attr}' is forbidden in condition '{expr_str}'."
            logger.error(msg)
            raise TransitionEvaluationError(
                message=msg,
                step_id=step_id,
                condition=expr_str,
            )


def evaluate_condition(
    condition_str: str,
    context: dict[str, Any],
    variables: Optional[dict[str, Any]] = None,
    cycle_number: int = 1,
    step_id: str = "",
) -> bool:
    """
    Safely evaluates a boolean condition string within a sandboxed execution namespace.

    Exposed variables in sandbox:
    - 'context': dict containing the workflow session context
    - 'variables': dict containing recent step variables/outputs
    - 'cycle_number': current iteration/loop count (int)
    - Flattened keys from context and variables (for direct expression like `mode == 'A'`)
    - SAFE_BUILTINS (len, int, str, bool, min, max, etc.)

    Raises TransitionEvaluationError if evaluation fails or expression is invalid.
    Zero silent fallback.
    """
    cleaned = condition_str.strip()
    if not cleaned:
        msg = f"Empty condition string provided for evaluation on step '{step_id}'."
        logger.error(msg)
        raise TransitionEvaluationError(
            message=msg,
            step_id=step_id,
            condition=condition_str,
            context=context,
        )

    # Validate AST safety
    _validate_ast_safety(cleaned, step_id=step_id)

    # Build evaluation environment
    eval_globals: dict[str, Any] = {"__builtins__": SAFE_BUILTINS}
    eval_locals: dict[str, Any] = {
        "context": dict(context),
        "variables": dict(variables or {}),
        "cycle_number": cycle_number,
    }

    # Flatten context and variables for direct variable access (without overriding core keys)
    for k, v in context.items():
        if k not in eval_locals:
            eval_locals[k] = v
    if variables:
        for k, v in variables.items():
            if k not in eval_locals:
                eval_locals[k] = v

    try:
        # Evaluate in sandbox
        result = eval(cleaned, eval_globals, eval_locals)  # noqa: S307
        return bool(result)
    except Exception as exc:
        msg = f"Failed to evaluate transition condition '{cleaned}' on step '{step_id}': {exc}"
        logger.error(msg)
        raise TransitionEvaluationError(
            message=msg,
            step_id=step_id,
            condition=cleaned,
            context=context,
        ) from exc


class DAGEngine:
    """
    Execution engine responsible for traversing workflow DAGs, selecting transitions,
    tracking loops/cycles, and building deterministic progressive disclosure envelopes.
    """

    def __init__(self, max_cycles_alert: int = 50) -> None:
        """
        Initialize the DAG Engine.

        :param max_cycles_alert: Threshold cycle count at which warnings / alerts are triggered.
        """
        if max_cycles_alert < 1:
            raise ValueError(f"max_cycles_alert must be >= 1, got {max_cycles_alert}")
        self.max_cycles_alert: int = max_cycles_alert

    def get_step(self, workflow: WorkflowDefinition, step_id: str) -> StepDefinition:
        """
        Look up a step by ID within the workflow definition.
        Raises InvalidDAGStructureError if the step does not exist.
        """
        step = workflow.get_step(step_id)
        if step is None:
            available = workflow.step_ids()
            msg = f"Step '{step_id}' was not found in workflow '{workflow.name}'. Available steps: {available}"
            logger.error(msg)
            raise InvalidDAGStructureError(
                message=msg,
                workflow_name=workflow.name,
                step_ids=[step_id],
                details={"step_id": step_id, "available_steps": available},
            )
        return step

    def get_allowed_transitions(self, step: StepDefinition, workflow: WorkflowDefinition) -> list[str]:
        """
        Calculates all valid candidate destination step IDs reachable from the current step.
        """
        if step.step_type == StepTypeEnum.TERMINAL:
            return []

        allowed: list[str] = []

        # Explicit transitions
        for transition in step.transitions:
            if transition.target and transition.target not in allowed:
                allowed.append(transition.target)
            if transition.default and transition.default not in allowed:
                allowed.append(transition.default)

        # Sequential next
        if step.next and step.next not in allowed:
            allowed.append(step.next)

        # Sequential topology fallback
        if workflow.type == WorkflowTypeEnum.SEQUENTIAL and not allowed:
            curr_idx = workflow.step_index(step.id)
            if curr_idx != -1 and curr_idx + 1 < len(workflow.steps):
                next_in_order = workflow.steps[curr_idx + 1].id
                allowed.append(next_in_order)

        return allowed

    def is_loop_transition(
        self,
        current_step_id: str,
        target_step_id: str,
        workflow: WorkflowDefinition,
    ) -> bool:
        """
        Determines if transitioning from current_step_id to target_step_id constitutes a loop restart.
        A transition is a loop restart if:
        1. target_step_id is the initial step (and current is not initial or it's a self-loop).
        2. target_step_id has an index <= current_step_id in the declared steps list.
        """
        if target_step_id == workflow.initial_step:
            return True

        curr_idx = workflow.step_index(current_step_id)
        target_idx = workflow.step_index(target_step_id)

        if curr_idx != -1 and target_idx != -1 and target_idx <= curr_idx:
            return True

        return False

    def resolve_next_step(
        self,
        session: WorkflowSessionState,
        workflow: WorkflowDefinition,
        transition_choice: Optional[str] = None,
        variables: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[str], bool]:
        """
        Determines the next step in the workflow DAG according to conditions, choices, or sequential rules.

        :param session: Current workflow session state.
        :param workflow: Validated workflow definition.
        :param transition_choice: Explicit target chosen by agent/user (validated against allowed targets).
        :param variables: Supplementary output variables from the completed step.
        :return: Tuple `(next_step_id, is_loop_restart)`. If `next_step_id` is None, workflow terminates.
        """
        current_step = self.get_step(workflow, session.current_step_id)
        allowed_targets = self.get_allowed_transitions(current_step, workflow)

        target_step_id: Optional[str] = None

        # 1. Explicit transition choice provided by caller
        if transition_choice is not None:
            choice_clean = transition_choice.strip()
            if choice_clean not in allowed_targets:
                msg = (
                    f"Requested transition '{choice_clean}' is not among allowed targets from step '{current_step.id}'. "
                    f"Allowed targets: {allowed_targets}"
                )
                logger.error(msg)
                raise InvalidTransitionError(
                    current_step_id=current_step.id,
                    requested_target=choice_clean,
                    allowed_targets=allowed_targets,
                    reason="Target step is not declared in step transitions or next rule.",
                )
            target_step_id = choice_clean

        # 2. Terminal step with no transition choice -> End workflow
        elif current_step.step_type == StepTypeEnum.TERMINAL:
            target_step_id = None

        # 3. Step defines conditional transitions
        elif len(current_step.transitions) > 0:
            matched_target: Optional[str] = None
            default_target: Optional[str] = None

            for t in current_step.transitions:
                if t.default is not None:
                    default_target = t.default
                elif t.condition is not None:
                    is_match = evaluate_condition(
                        condition_str=t.condition,
                        context=session.context,
                        variables=variables,
                        cycle_number=session.cycle_number,
                        step_id=current_step.id,
                    )
                    if is_match:
                        matched_target = t.target
                        break

            if matched_target is not None:
                target_step_id = matched_target
            elif default_target is not None:
                target_step_id = default_target
            else:
                msg = (
                    f"No conditional branch evaluated to True for step '{current_step.id}' "
                    f"and no 'default' transition target was specified. "
                    f"Tested transitions: {[t.model_dump() for t in current_step.transitions]}"
                )
                logger.error(msg)
                raise TransitionEvaluationError(
                    message=msg,
                    step_id=current_step.id,
                    context=session.context,
                )

        # 4. Direct sequential next target
        elif current_step.next is not None:
            target_step_id = current_step.next

        # 5. Sequential workflow fallback
        elif workflow.type == WorkflowTypeEnum.SEQUENTIAL:
            curr_idx = workflow.step_index(current_step.id)
            if curr_idx != -1 and curr_idx + 1 < len(workflow.steps):
                target_step_id = workflow.steps[curr_idx + 1].id
            else:
                target_step_id = None

        # 6. Default fallback: no outgoing targets -> workflow finishes
        else:
            target_step_id = None

        # Workflow termination
        if target_step_id is None:
            return None, False

        # Validate that the resolved target actually exists in the workflow
        _ = self.get_step(workflow, target_step_id)

        # Detect loop restart
        is_loop = self.is_loop_transition(current_step.id, target_step_id, workflow)

        if is_loop:
            predicted_cycle = session.cycle_number + 1
            if predicted_cycle >= self.max_cycles_alert:
                logger.warning(
                    f"Workflow '{workflow.name}' session '{session.session_id}' cycle count ({predicted_cycle}) "
                    f"reached or exceeded alert threshold ({self.max_cycles_alert}). "
                    f"Potential infinite loop detected."
                )

        return target_step_id, is_loop

    def build_step_envelope(
        self,
        session: WorkflowSessionState,
        workflow: WorkflowDefinition,
        message: Optional[str] = None,
    ) -> StepResultEnvelope:
        """
        Builds the deterministic progressive disclosure envelope for the active step in the session.
        """
        current_step = self.get_step(workflow, session.current_step_id)
        total_steps = len(workflow.steps)
        curr_idx = workflow.step_index(current_step.id)

        # Progress calculation
        percentage = round(((curr_idx + 1) / total_steps) * 100, 1) if total_steps > 0 else 100.0
        progress_info = StepProgressInfo(
            current_step_index=curr_idx,
            total_steps=total_steps,
            percentage=percentage,
        )

        # Directive info for current step
        allowed_transitions = self.get_allowed_transitions(current_step, workflow)
        directive_info = StepDirectiveInfo(
            id=current_step.id,
            title=current_step.title,
            step_type=current_step.step_type.value,
            instructions_markdown=current_step.extracted_markdown,
            mandated_tools=current_step.mandated_tools,
            constraints=current_step.constraints,
            expected_outputs=current_step.expected_outputs,
            subagent_recommendation=current_step.subagent_recommendation,
            allowed_transitions=allowed_transitions,
        )

        # Check loop alert message injection
        final_message = message
        if session.cycle_number >= self.max_cycles_alert:
            cycle_alert = (
                f"⚠️ ALERTE CYCLE ELEVÉ : Le cycle actuel ({session.cycle_number}) a atteint ou dépassé "
                f"le seuil d'alerte configuré ({self.max_cycles_alert}). "
                f"Veuillez vérifier les conditions de sortie de boucle."
            )
            final_message = f"{message} | {cycle_alert}" if message else cycle_alert

        return StepResultEnvelope(
            session_id=session.session_id,
            workflow_name=workflow.name,
            workflow_title=workflow.description or workflow.name,
            status=session.status,
            cycle_number=session.cycle_number,
            progress=progress_info,
            current_step=directive_info,
            message=final_message,
        )
