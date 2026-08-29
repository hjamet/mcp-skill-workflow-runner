"""
Parser for workflow definitions.

Extracts YAML frontmatter (under 'workflow:' key) and segments Markdown sections (H2/H3)
while strictly ignoring code fences (``` or ~~~).
Zero silent fallbacks: any syntax, schema, or missing section error raises an explicit typed exception.
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mcp_skill_workflow_runner.exceptions import (
    SectionNotFoundError,
    WorkflowParseError,
    WorkflowSchemaError,
)
from mcp_skill_workflow_runner.models import (
    ContextFieldSchema,
    StepDefinition,
    StepTransitionDefinition,
    WorkflowDefinition,
    WorkflowTypeEnum,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@dataclass
class MarkdownSection:
    """Represents an extracted Markdown section."""
    level: int
    header_raw: str
    header_text: str
    content: str
    start_line: int
    end_line: int


def extract_frontmatter_and_body(raw_text: str, file_path: str = "") -> tuple[dict[str, Any], str]:
    """
    Extracts YAML frontmatter dict and remaining markdown body.
    Supports standard YAML frontmatter bounded by '---' at start of file,
    or pure YAML documents.
    """
    normalized = raw_text.replace("\r\n", "\n")
    stripped = normalized.lstrip()

    if stripped.startswith("---"):
        # Find closing ---
        lines = normalized.split("\n")
        first_delim_idx = -1
        second_delim_idx = -1

        for idx, line in enumerate(lines):
            if line.strip() == "---":
                if first_delim_idx == -1:
                    first_delim_idx = idx
                elif second_delim_idx == -1:
                    second_delim_idx = idx
                    break

        if first_delim_idx != -1 and second_delim_idx != -1 and second_delim_idx > first_delim_idx:
            fm_text = "\n".join(lines[first_delim_idx + 1 : second_delim_idx])
            body_text = "\n".join(lines[second_delim_idx + 1 :])

            try:
                fm_data = yaml.safe_load(fm_text)
            except yaml.YAMLError as exc:
                mark = getattr(exc, "problem_mark", None)
                line_no = mark.line + 1 if mark else None
                logger.error(f"Failed to parse YAML frontmatter in '{file_path}': {exc}")
                raise WorkflowParseError(
                    f"Invalid YAML syntax in frontmatter of '{file_path or '<raw text>'}': {exc}",
                    file_path=file_path,
                    line=line_no,
                    raw_snippet=fm_text[:300],
                ) from exc

            if not isinstance(fm_data, dict):
                raise WorkflowParseError(
                    f"Frontmatter in '{file_path or '<raw text>'}' must be a YAML dictionary/mapping, got {type(fm_data).__name__}.",
                    file_path=file_path,
                )

            return fm_data, body_text
        else:
            raise WorkflowParseError(
                f"File '{file_path or '<raw text>'}' starts with '---' but is missing the closing '---' frontmatter delimiter.",
                file_path=file_path,
            )

    # If no frontmatter delimiter, attempt to parse as a direct YAML document if it has workflow properties
    try:
        data = yaml.safe_load(normalized)
        if isinstance(data, dict) and ("workflow" in data or "steps" in data):
            return data, ""
    except yaml.YAMLError:
        pass

    raise WorkflowParseError(
        f"File '{file_path or '<raw text>'}' does not contain valid YAML frontmatter delimited by '---'.",
        file_path=file_path,
    )


def extract_markdown_sections(markdown_text: str) -> list[MarkdownSection]:
    """
    Extracts all H1, H2, H3, H4 headers and their content, strictly ignoring
    any header characters within fenced code blocks (``` or ~~~).
    Content spans up until the next header of equal or higher rank (or EOF).
    """
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    header_regex = re.compile(r"^(#{1,6})\s+(.+)$")

    raw_headers: list[tuple[int, int, str, str]] = []  # (line_idx, level, header_raw, header_text)
    in_code_block = False
    code_fence_char = ""

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # Check code fences
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            if not in_code_block:
                in_code_block = True
                code_fence_char = fence
            elif code_fence_char == fence:
                in_code_block = False
                code_fence_char = ""
            continue

        if in_code_block:
            continue

        match = header_regex.match(line)
        if match:
            level = len(match.group(1))
            header_text = match.group(2).strip()
            raw_headers.append((idx, level, line.strip(), header_text))

    sections: list[MarkdownSection] = []
    num_headers = len(raw_headers)

    for i, (start_line_idx, level, header_raw, header_text) in enumerate(raw_headers):
        # The section content extends until the next header of level <= current level (or EOF)
        end_line_idx = len(lines)
        for j in range(i + 1, num_headers):
            next_start_idx, next_level, _, _ = raw_headers[j]
            if next_level <= level:
                end_line_idx = next_start_idx
                break

        # Content includes lines from start_line_idx to end_line_idx (excluding next header line)
        content_lines = lines[start_line_idx:end_line_idx]
        content_str = "\n".join(content_lines).strip()

        sections.append(
            MarkdownSection(
                level=level,
                header_raw=header_raw,
                header_text=header_text,
                content=content_str,
                start_line=start_line_idx + 1,
                end_line=end_line_idx,
            )
        )

    return sections


def match_section_for_step(
    matcher: str,
    step_id: str,
    sections: list[MarkdownSection],
    file_path: str = "",
) -> MarkdownSection:
    """
    Finds the Markdown section that corresponds to `matcher`.
    Raises SectionNotFoundError if no section matches. Zero silent fallback.
    """
    matcher_stripped = matcher.strip()

    # 1. Exact match with header_raw or header_text
    for sec in sections:
        if matcher_stripped == sec.header_raw or matcher_stripped == sec.header_text:
            return sec

    # 2. Prefix match (e.g. '### 3.1' matches '### 3.1 💡 Étape 1 : Exploration...')
    for sec in sections:
        if sec.header_raw.startswith(matcher_stripped) or sec.header_text.startswith(matcher_stripped):
            return sec

    # 3. Substring match
    for sec in sections:
        if matcher_stripped in sec.header_raw or matcher_stripped in sec.header_text:
            return sec

    # 4. Regex match
    try:
        compiled = re.compile(matcher_stripped, re.IGNORECASE)
        for sec in sections:
            if compiled.search(sec.header_raw) or compiled.search(sec.header_text):
                return sec
    except re.error:
        pass

    # No match found: Raise SectionNotFoundError with all available sections
    available_headers = [sec.header_raw for sec in sections]
    logger.error(
        f"Section matcher '{matcher}' for step '{step_id}' failed in '{file_path}'. "
        f"Found {len(available_headers)} headers."
    )
    raise SectionNotFoundError(
        section_matcher=matcher,
        step_id=step_id,
        available_sections=available_headers,
        file_path=file_path,
    )


def parse_workflow_content(content: str, file_path: str = "") -> WorkflowDefinition:
    """
    Parses raw workflow markdown/yaml string into a validated WorkflowDefinition.
    Extracts frontmatter, builds models, parses markdown sections, and binds them to steps.
    """
    frontmatter_dict, raw_body = extract_frontmatter_and_body(content, file_path=file_path)

    # Frontmatter must contain 'workflow:' block or be direct workflow dictionary
    if "workflow" in frontmatter_dict and isinstance(frontmatter_dict["workflow"], dict):
        wf_data = dict(frontmatter_dict["workflow"])
        # Merge top-level metadata if not present in workflow block
        if "name" not in wf_data and "name" in frontmatter_dict:
            wf_data["name"] = frontmatter_dict["name"]
        if "description" not in wf_data and "description" in frontmatter_dict:
            wf_data["description"] = frontmatter_dict["description"]
    elif "steps" in frontmatter_dict:
        wf_data = dict(frontmatter_dict)
    else:
        raise WorkflowParseError(
            f"YAML frontmatter in '{file_path or '<raw content>'}' must contain a 'workflow:' block with step definitions.",
            file_path=file_path,
        )

    # Ensure required name is present
    if not wf_data.get("name"):
        if frontmatter_dict.get("name"):
            wf_data["name"] = frontmatter_dict["name"]
        elif file_path:
            wf_data["name"] = Path(file_path).stem
        else:
            raise WorkflowParseError(
                "Workflow is missing required field 'name' in frontmatter.",
                file_path=file_path,
            )

    # Attach raw markdown body and file_path
    wf_data["raw_markdown_body"] = raw_body
    wf_data["file_path"] = file_path

    # Construct Pydantic WorkflowDefinition
    try:
        workflow_def = WorkflowDefinition.model_validate(wf_data)
    except ValidationError as err:
        logger.error(f"Schema validation error in '{file_path}': {err}")
        raise WorkflowSchemaError(
            message=f"Workflow definition schema validation failed for '{file_path or wf_data.get('name')}': {err}",
            validation_errors=err.errors(),
            file_path=file_path,
        ) from err

    # Extract markdown sections and bind to steps if raw_body is non-empty
    if raw_body.strip():
        sections = extract_markdown_sections(raw_body)
        for step in workflow_def.steps:
            if step.section_matcher:
                matched_sec = match_section_for_step(
                    matcher=step.section_matcher,
                    step_id=step.id,
                    sections=sections,
                    file_path=file_path,
                )
                step.extracted_markdown = matched_sec.content
            else:
                # If no explicit section_matcher, try matching by step title if it exists
                for sec in sections:
                    if step.title and (step.title in sec.header_raw or sec.header_text.startswith(step.title)):
                        step.extracted_markdown = sec.content
                        break

    return workflow_def


def parse_workflow_file(file_path: str | Path) -> WorkflowDefinition:
    """
    Loads and parses a workflow definition from a file path.
    Raises WorkflowParseError if the file cannot be read.
    """
    path_obj = Path(file_path)
    if not path_obj.exists() or not path_obj.is_file():
        raise WorkflowParseError(
            f"Workflow file does not exist or is not a file: '{file_path}'",
            file_path=str(file_path),
        )

    try:
        content = path_obj.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"Failed to read workflow file '{file_path}': {exc}")
        raise WorkflowParseError(
            f"Failed to read file '{file_path}': {exc}",
            file_path=str(file_path),
        ) from exc

    return parse_workflow_content(content, file_path=str(path_obj.resolve()))
