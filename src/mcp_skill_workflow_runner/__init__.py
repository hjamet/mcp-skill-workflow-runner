"""
mcp-skill-workflow-runner: FastMCP Deterministic Progressive Disclosure Workflow Runner for Antigravity skills.
"""

from __future__ import annotations

from mcp_skill_workflow_runner.dag_engine import DAGEngine, evaluate_condition
from mcp_skill_workflow_runner.exceptions import (
    InvalidDAGStructureError,
    InvalidTransitionError,
    SectionNotFoundError,
    SessionCorruptedError,
    SessionError,
    SessionNotFoundError,
    SkillWorkflowException,
    TransitionEvaluationError,
    WorkflowParseError,
    WorkflowResolutionError,
    WorkflowRunnerError,
    WorkflowSchemaError,
)
from mcp_skill_workflow_runner.models import (
    ContextFieldSchema,
    StepDefinition,
    StepDirectiveInfo,
    StepEnvelopePayload,
    StepExecutionRecord,
    StepProgressInfo,
    StepResultEnvelope,
    StepTransitionDefinition,
    StepType,
    StepTypeEnum,
    SubagentRecommendation,
    TransitionRule,
    WorkflowDefinition,
    WorkflowSession,
    WorkflowSessionState,
    WorkflowStep,
    WorkflowType,
    WorkflowTypeEnum,
)
from mcp_skill_workflow_runner.parser import (
    MarkdownSection,
    extract_frontmatter_and_body,
    extract_markdown_sections,
    match_section_for_step,
    parse_workflow_content,
    parse_workflow_file,
)
from mcp_skill_workflow_runner.resolver import (
    discover_all_workflows,
    get_search_directories,
    resolve_skill_file,
)
from mcp_skill_workflow_runner.server import app, create_server, mcp
from mcp_skill_workflow_runner.session_manager import (
    DEFAULT_SESSIONS_DIR,
    SessionManager,
    validate_and_prepare_context,
)
from mcp_skill_workflow_runner.validator import (
    validate_dag_structure,
    validate_workflow,
)

__version__ = "0.1.0"

__all__ = [
    # Exceptions
    "WorkflowRunnerError",
    "SkillWorkflowException",
    "WorkflowResolutionError",
    "WorkflowParseError",
    "WorkflowSchemaError",
    "SectionNotFoundError",
    "InvalidDAGStructureError",
    "TransitionEvaluationError",
    "InvalidTransitionError",
    "SessionError",
    "SessionNotFoundError",
    "SessionCorruptedError",
    # Models & Enums
    "WorkflowTypeEnum",
    "WorkflowType",
    "StepTypeEnum",
    "StepType",
    "SubagentRecommendation",
    "StepTransitionDefinition",
    "TransitionRule",
    "ContextFieldSchema",
    "StepDefinition",
    "WorkflowStep",
    "WorkflowDefinition",
    "StepExecutionRecord",
    "WorkflowSessionState",
    "WorkflowSession",
    "StepProgressInfo",
    "StepDirectiveInfo",
    "StepResultEnvelope",
    "StepEnvelopePayload",
    # Parser
    "MarkdownSection",
    "extract_frontmatter_and_body",
    "extract_markdown_sections",
    "match_section_for_step",
    "parse_workflow_content",
    "parse_workflow_file",
    # Validator
    "validate_dag_structure",
    "validate_workflow",
    # DAG Engine
    "DAGEngine",
    "evaluate_condition",
    # Session Manager
    "DEFAULT_SESSIONS_DIR",
    "SessionManager",
    "validate_and_prepare_context",
    # Resolver
    "get_search_directories",
    "resolve_skill_file",
    "discover_all_workflows",
    # FastMCP Server
    "app",
    "mcp",
    "create_server",
]

