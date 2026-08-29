"""
Pydantic V2 models for workflow definitions, steps, transitions, sessions, and envelopes.

Strict typing and validation ensure deterministic progressive disclosure.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowTypeEnum(str, Enum):
    """Workflow execution paradigm."""
    SEQUENTIAL = "sequential"
    DAG = "dag"
    LOOP = "loop"


# Alias for convenience and architectural plan compatibility
WorkflowType = WorkflowTypeEnum


class StepTypeEnum(str, Enum):
    """Step operational category."""
    STANDARD = "standard"
    INTERACTIVE = "interactive"
    SUBAGENT_BARRIER = "subagent_barrier"
    LOOP_DECISION = "loop_decision"
    TERMINAL = "terminal"


# Alias for convenience and architectural plan compatibility
StepType = StepTypeEnum


class SubagentRecommendation(BaseModel):
    """Configuration guidelines for deploying subagents in an execution step."""
    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="Subagent profile or role (e.g. 'research', 'builder', 'scout')")
    clustering_rule: Optional[str] = Field(
        default=None,
        description="Clustering heuristic (e.g. '1 subagent per orthogonal domain')",
    )
    model: Optional[str] = Field(
        default=None,
        description="Recommended model tier (e.g. 'flash', 'pro', 'sonnet')",
    )
    max_parallel: Optional[int] = Field(
        default=None,
        description="Maximum concurrent subagents allowed",
    )
    prompt_template: Optional[str] = Field(
        default=None,
        description="Optional prompt template for subagent spawning",
    )


class StepTransitionDefinition(BaseModel):
    """Conditional branching rule leading to a target step."""
    model_config = ConfigDict(extra="forbid")

    condition: Optional[str] = Field(
        default=None,
        description="Python expression to evaluate against workflow context/variables",
    )
    target: Optional[str] = Field(
        default=None,
        description="Target step ID if condition evaluates to True",
    )
    default: Optional[str] = Field(
        default=None,
        description="Fallback target step ID if no other condition evaluates to True",
    )

    @model_validator(mode="after")
    def validate_transition_integrity(self) -> StepTransitionDefinition:
        if self.default is not None and (self.condition is not None or self.target is not None):
            if self.condition is not None:
                raise ValueError("A 'default' transition rule must not define a 'condition'.")
        if self.condition is not None and self.target is None:
            raise ValueError("A transition with a 'condition' must also specify a 'target'.")
        if self.condition is None and self.target is None and self.default is None:
            raise ValueError("A transition rule must specify either ('condition' and 'target'), 'target', or 'default'.")
        return self


# Alias for plan compatibility
TransitionRule = StepTransitionDefinition


class ContextFieldSchema(BaseModel):
    """Schema declaration for a contextual workflow variable."""
    model_config = ConfigDict(extra="forbid")

    type: str = Field(default="string", description="Type name: string, integer, number, boolean, list, dict")
    required: bool = Field(default=False, description="Whether the variable is mandatory at startup")
    default: Optional[Any] = Field(default=None, description="Default value if not provided")
    enum: Optional[list[Any]] = Field(default=None, description="List of allowed discrete values")
    description: Optional[str] = Field(default=None, description="Human-readable variable description")


class StepDefinition(BaseModel):
    """Complete specification of an individual workflow step."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique step identifier (e.g. 'step_1_exploration')")
    title: str = Field(description="Human-readable title with optional emojis")
    section_matcher: Optional[str] = Field(
        default=None,
        description="Markdown H2/H3 header prefix or exact title to extract instructions from",
    )
    step_type: StepTypeEnum = Field(
        default=StepTypeEnum.STANDARD,
        description="Operational classification of this step",
    )
    mandated_tools: list[str] = Field(
        default_factory=list,
        description="List of tools the agent is mandated to invoke during this step",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Explicit negative or positive constraints enforced at this step",
    )
    expected_outputs: list[str] = Field(
        default_factory=list,
        description="Expected artifacts, variables, or deliverables from this step",
    )
    subagent_recommendation: Optional[SubagentRecommendation] = Field(
        default=None,
        description="Subagent deployment recommendations if applicable",
    )
    next: Optional[str] = Field(
        default=None,
        description="Direct sequential successor step ID",
    )
    transitions: list[StepTransitionDefinition] = Field(
        default_factory=list,
        description="List of conditional or default branching rules",
    )
    extracted_markdown: str = Field(
        default="",
        description="Instruction text extracted from matching Markdown section",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary supplementary metadata",
    )


# Alias for plan compatibility
WorkflowStep = StepDefinition


class WorkflowDefinition(BaseModel):
    """Parsed and validated top-level workflow definition."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Unique workflow / skill name")
    description: str = Field(default="", description="Functional overview of the workflow")
    version: str = Field(default="1.0", description="Workflow specification version")
    engine: Optional[str] = Field(default=None, description="Workflow execution engine")
    type: WorkflowTypeEnum = Field(
        default=WorkflowTypeEnum.SEQUENTIAL,
        description="Workflow topology type: sequential, dag, or loop",
    )
    initial_step: str = Field(description="ID of the entrypoint step")
    context_schema: dict[str, ContextFieldSchema] = Field(
        default_factory=dict,
        description="Declared context variables and validation rules",
    )
    steps: list[StepDefinition] = Field(
        default_factory=list,
        description="Ordered or DAG step definitions",
    )
    raw_markdown_body: str = Field(
        default="",
        description="Raw markdown body excluding YAML frontmatter",
    )
    file_path: str = Field(
        default="",
        description="Absolute or relative path to the source file",
    )

    def get_step(self, step_id: str) -> Optional[StepDefinition]:
        """Look up a step by its ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def step_ids(self) -> list[str]:
        """Return list of all step IDs in declaration order."""
        return [step.id for step in self.steps]

    def step_index(self, step_id: str) -> int:
        """Return 0-based index of a step, or -1 if not found."""
        for idx, step in enumerate(self.steps):
            if step.id == step_id:
                return idx
        return -1


class StepExecutionRecord(BaseModel):
    """Audit record of a single step execution within a session."""
    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_index: int = 0
    cycle_number: int = 1
    entered_at: str
    exited_at: Optional[str] = None
    output_summary: Optional[Any] = None
    transition_taken: Optional[str] = None


class WorkflowSessionState(BaseModel):
    """State of an ongoing or completed workflow session."""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    workflow_name: str
    skill_file_path: str = ""
    workspace_dir: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    current_step_id: str
    cycle_number: int = 1
    status: str = "in_progress"  # "in_progress", "completed", "aborted", "paused"
    history: list[StepExecutionRecord] = Field(default_factory=list)
    created_at: str
    updated_at: str


# Alias for plan compatibility
WorkflowSession = WorkflowSessionState


class StepProgressInfo(BaseModel):
    """Progress metrics within the workflow."""
    model_config = ConfigDict(extra="forbid")

    current_step_index: int
    total_steps: int
    percentage: float


class StepDirectiveInfo(BaseModel):
    """Directive envelope delivered to the agent for the active step."""
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    step_type: str
    instructions_markdown: str = ""
    mandated_tools: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    subagent_recommendation: Optional[SubagentRecommendation] = None
    allowed_transitions: list[str] = Field(default_factory=list)


class StepResultEnvelope(BaseModel):
    """Deterministic Progressive Disclosure Envelope returned to the agent."""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    workflow_name: str
    workflow_title: str
    status: str
    cycle_number: int
    progress: StepProgressInfo
    current_step: StepDirectiveInfo
    message: Optional[str] = None


# Alias for plan compatibility
StepEnvelopePayload = StepResultEnvelope
