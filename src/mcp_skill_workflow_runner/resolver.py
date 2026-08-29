"""
Skill & Workflow file resolver for mcp-skill-workflow-runner.

Hierarchical deterministic resolution:
1. Direct file or folder path.
2. Workspace-local directories (.agent/skills/, .agents/skills/, skills/, agents/skills/).
3. Global Antigravity vaults (~/.gemini/antigravity/builtin/skills/, ~/.gemini/config/skills/,
   ~/.gemini/antigravity/skills/, ~/.gemini/antigravity/global_workflows/, ~/.antigravity/skills/).

Zero silent fallback: If not found, raises WorkflowResolutionError listing all tested paths.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from mcp_skill_workflow_runner.exceptions import WorkflowResolutionError
from mcp_skill_workflow_runner.parser import parse_workflow_file

logger = logging.getLogger(__name__)


def get_search_directories(workspace_dir: Optional[str | Path] = None) -> list[tuple[str, Path]]:
    """
    Return candidate search root directories with their scope tag ("workspace" | "global").
    Order of preference:
    1. Workspace-local search directories
    2. Global user-level Antigravity vaults
    """
    roots: list[tuple[str, Path]] = []
    ws = Path(workspace_dir).expanduser().resolve() if workspace_dir else Path.cwd().resolve()

    # Workspace-local roots (priority order)
    workspace_candidates = [
        ws / ".agent" / "skills",
        ws / ".agents" / "skills",
        ws / "skills",
        ws / "agents" / "skills",
    ]
    for p in workspace_candidates:
        roots.append(("workspace", p))

    # Global Antigravity vaults
    home = Path.home()
    global_candidates = [
        home / ".gemini" / "antigravity" / "builtin" / "skills",
        home / ".gemini" / "config" / "skills",
        home / ".gemini" / "antigravity" / "skills",
        home / ".gemini" / "antigravity" / "global_workflows",
        home / ".antigravity" / "skills",
    ]
    for p in global_candidates:
        roots.append(("global", p))

    return roots


def resolve_skill_file(
    skill_name: str,
    workspace_dir: Optional[str | Path] = None,
) -> Path:
    """
    Resolve a skill name or file path to an existing SKILL.md / workflow.md / .yaml file.

    Search sequence:
    1. Direct filesystem check (absolute or relative to cwd/workspace).
    2. Workspace candidate folders (.agent/skills/<skill_name>/SKILL.md, etc.).
    3. Global Antigravity vaults (~/.gemini/antigravity/builtin/skills/<skill_name>/SKILL.md, etc.).

    Raises:
        WorkflowResolutionError: If no matching file is found among all tested paths.
    """
    searched_paths: list[str] = []
    name_clean = skill_name.strip()

    # 1. Direct path check
    direct_candidates: list[Path] = []
    p_direct = Path(name_clean).expanduser()
    if p_direct.is_absolute():
        direct_candidates.append(p_direct)
    else:
        if workspace_dir:
            direct_candidates.append(Path(workspace_dir).expanduser().resolve() / name_clean)
        direct_candidates.append(Path.cwd().resolve() / name_clean)

    for cand in direct_candidates:
        searched_paths.append(str(cand))
        if cand.is_file():
            logger.debug("Resolved skill '%s' via direct file path: %s", skill_name, cand)
            return cand.resolve()
        if cand.is_dir():
            # Check for standard skill files inside directory
            for inner_name in ("SKILL.md", "skill.md", "workflow.md", "workflow.yaml", "workflow.yml"):
                inner = cand / inner_name
                searched_paths.append(str(inner))
                if inner.is_file():
                    logger.debug("Resolved skill '%s' in directory: %s", skill_name, inner)
                    return inner.resolve()

    # 2 & 3. Search candidate roots
    search_roots = get_search_directories(workspace_dir)

    for _scope, root_dir in search_roots:
        # Check folder-based skill: root_dir / name / SKILL.md (or variants)
        skill_dir = root_dir / name_clean
        for inner_name in ("SKILL.md", "skill.md", "workflow.md", "workflow.yaml", "workflow.yml"):
            target = skill_dir / inner_name
            searched_paths.append(str(target))
            if target.is_file():
                logger.debug("Resolved skill '%s' at: %s", skill_name, target)
                return target.resolve()

        # Check direct file: root_dir / f"{name}.md" / f"{name}.yaml"
        for ext in (".md", ".yaml", ".yml"):
            target = root_dir / f"{name_clean}{ext}"
            searched_paths.append(str(target))
            if target.is_file():
                logger.debug("Resolved skill '%s' as single file: %s", skill_name, target)
                return target.resolve()

    # If we reached here, resolution failed
    sys.stderr.write(
        f"[ERROR] [WorkflowResolutionError] Skill '{skill_name}' could not be resolved across {len(searched_paths)} tested locations.\n"
    )
    raise WorkflowResolutionError(
        skill_name=skill_name,
        searched_paths=searched_paths,
    )


def discover_all_workflows(
    workspace_dir: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """
    Scan all workspace and global search directories to discover all available skills/workflows.

    Returns:
        List of dictionaries with keys:
            - name: str (workflow/skill name)
            - file_path: str (absolute path)
            - scope: str ("workspace" | "global")
            - valid: bool (whether YAML frontmatter workflow is valid)
            - description: str
            - workflow_type: str ("sequential" | "dag" | "loop" | "unknown")
            - initial_step: str
            - total_steps: int
            - error: Optional[str] (error message if invalid)
    """
    discovered: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    search_roots = get_search_directories(workspace_dir)

    for scope, root_dir in search_roots:
        if not root_dir.exists() or not root_dir.is_dir():
            continue

        # Look for subdirectories containing SKILL.md / workflow.md
        try:
            for item in root_dir.iterdir():
                candidate_files: list[Path] = []
                if item.is_dir():
                    for target_name in ("SKILL.md", "skill.md", "workflow.md", "workflow.yaml", "workflow.yml"):
                        f = item / target_name
                        if f.is_file():
                            candidate_files.append(f)
                elif item.is_file() and item.suffix in (".md", ".yaml", ".yml"):
                    candidate_files.append(item)

                for f in candidate_files:
                    abs_path_str = str(f.resolve())
                    if abs_path_str in seen_paths:
                        continue
                    seen_paths.add(abs_path_str)

                    # Inspect the workflow file
                    entry: dict[str, Any] = {
                        "name": item.name if item.is_dir() else item.stem,
                        "file_path": abs_path_str,
                        "scope": scope,
                        "valid": False,
                        "description": "",
                        "workflow_type": "unknown",
                        "initial_step": "",
                        "total_steps": 0,
                        "error": None,
                    }

                    try:
                        wf = parse_workflow_file(f)
                        entry["valid"] = True
                        entry["name"] = wf.name or entry["name"]
                        entry["description"] = wf.description
                        entry["workflow_type"] = (
                            wf.type.value if hasattr(wf.type, "value") else str(wf.type)
                        )
                        entry["initial_step"] = wf.initial_step
                        entry["total_steps"] = len(wf.steps)
                    except Exception as exc:
                        entry["valid"] = False
                        entry["error"] = str(exc)

                    discovered.append(entry)
        except Exception as scan_err:
            sys.stderr.write(f"[WARN] Failed scanning directory '{root_dir}': {scan_err}\n")

    return discovered
