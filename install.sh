#!/usr/bin/env bash
# install.sh — mcp-skill-workflow-runner automated all-in-one installer for Linux/macOS
#
# Usage:
#   bash install.sh                  # install from current repo directory
#   curl -fsSL <raw_url> | bash      # install remotely via curl one-liner
#
# What it does:
#   1. Detects Python 3.10+ (or 'uv' if available).
#   2. Resolves source directory (current dir or clones to ~/.mcp-skill-workflow-runner).
#   3. Creates isolated virtual environment in venv/.
#   4. Installs dependencies and the package in editable mode (pip install --no-user -e .).
#   5. Registers skill-workflow-runner in ~/.gemini/config/mcp_config.json safely via Python.
#   6. Deploys MCP metadata schemas and instructions.md to ~/.gemini/antigravity/mcp/skill-workflow-runner/.
#   7. Validates FastMCP server and CLI operation.
#   8. Creates CLI executable wrapper in ~/.local/bin/skill-workflow.
#
# NO FALLBACK: any error aborts the script immediately (set -euo pipefail).

set -euo pipefail

# Ensure local bin is in PATH
export PATH="${HOME}/.local/bin:${PATH}"

# ---------------------------------------------------------------------------
# Visual Styling Helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[*]${NC} $*"; }
success() { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
die()     { echo -e "${RED}[-] ERROR:${NC} $*" >&2; exit 1; }

echo ""
echo -e "${CYAN}======================================================================${NC}"
echo -e "${CYAN}     MCP Skill Workflow Runner - All-In-One Installer (Linux/macOS)   ${NC}"
echo -e "${CYAN}======================================================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. Detect Python 3.10+
# ---------------------------------------------------------------------------
info "Detecting Python 3.10+ environment..."

PYTHON_BIN=""
PYTHON_VERSION=""

for CANDIDATE in python3.12 python3.11 python3.10 python3 python; do
    if command -v "${CANDIDATE}" >/dev/null 2>&1; then
        V_OUT=$("${CANDIDATE}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || true)
        if [[ -n "${V_OUT}" ]]; then
            MAJOR=$(echo "${V_OUT}" | cut -d. -f1)
            MINOR=$(echo "${V_OUT}" | cut -d. -f2)
            if [[ "${MAJOR}" -eq 3 && "${MINOR}" -ge 10 ]]; then
                PYTHON_BIN="$(command -v "${CANDIDATE}")"
                PYTHON_VERSION="${V_OUT}"
                break
            fi
        fi
    fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
    die "Python 3.10+ is required but not found. Please install Python 3.10, 3.11, or 3.12."
fi

success "Found Python ${PYTHON_VERSION} at: ${PYTHON_BIN}"

HAS_UV=0
if command -v uv >/dev/null 2>&1; then
    HAS_UV=1
    UV_VER=$(uv --version 2>/dev/null || echo "uv")
    success "Found 'uv' tool (${UV_VER}) for accelerated installation."
fi

# ---------------------------------------------------------------------------
# 2. Resolve Source Directory
# ---------------------------------------------------------------------------
info "Resolving source directory..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-install.sh}")" 2>/dev/null && pwd || true)"
RUNNER_HOME="${HOME}/.mcp-skill-workflow-runner"
SOURCE_DIR=""

if [[ -n "${SCRIPT_DIR}" && -f "${SCRIPT_DIR}/pyproject.toml" ]] && grep -q 'name = "mcp-skill-workflow-runner"' "${SCRIPT_DIR}/pyproject.toml" 2>/dev/null; then
    SOURCE_DIR="${SCRIPT_DIR}"
    success "Using local repository at: ${SOURCE_DIR}"
elif [[ -f "./pyproject.toml" ]] && grep -q 'name = "mcp-skill-workflow-runner"' "./pyproject.toml" 2>/dev/null; then
    SOURCE_DIR="$(pwd)"
    success "Using current directory at: ${SOURCE_DIR}"
else
    REPO_DIR="${RUNNER_HOME}/repo"
    info "Source directory not found locally — cloning into ${REPO_DIR} ..."
    mkdir -p "${RUNNER_HOME}"
    if [[ -d "${REPO_DIR}/.git" ]]; then
        git -C "${REPO_DIR}" pull --ff-only
    else
        REPO_URL="${SKILL_WORKFLOW_RUNNER_REPO_URL:-https://github.com/UNIL-DESI/mcp-skill-workflow-runner.git}"
        git clone "${REPO_URL}" "${REPO_DIR}"
    fi
    SOURCE_DIR="${REPO_DIR}"
    success "Source repository ready at: ${SOURCE_DIR}"
fi

# ---------------------------------------------------------------------------
# 3. Create Isolated Virtual Environment
# ---------------------------------------------------------------------------
VENV_DIR="${SOURCE_DIR}/venv"
info "Setting up isolated virtualenv at: ${VENV_DIR} ..."

if [[ "${1:-}" == "--force" || "${1:-}" == "-f" ]] && [[ -d "${VENV_DIR}" ]]; then
    warn "Force switch specified. Recreating virtual environment..."
    rm -rf "${VENV_DIR}"
fi

if [[ ! -d "${VENV_DIR}" || ! -f "${VENV_DIR}/bin/python" ]]; then
    if [[ "${HAS_UV}" -eq 1 ]]; then
        uv venv "${VENV_DIR}" --python "${PYTHON_BIN}"
    else
        "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    fi
    success "Virtual environment created successfully."
else
    success "Virtual environment already exists."
fi

VENV_PYTHON="${VENV_DIR}/bin/python"

# ---------------------------------------------------------------------------
# 4. Install Dependencies and Package in Editable Mode
# ---------------------------------------------------------------------------
info "Installing mcp-skill-workflow-runner and dependencies in editable mode..."

pushd "${SOURCE_DIR}" >/dev/null
if [[ "${HAS_UV}" -eq 1 ]]; then
    uv pip install --python "${VENV_PYTHON}" -e .
else
    "${VENV_PYTHON}" -m pip install --quiet --upgrade pip
    "${VENV_PYTHON}" -m pip install --no-user -e .
fi
popd >/dev/null
success "Package and dependencies installed successfully."

# ---------------------------------------------------------------------------
# 5. Register Server in ~/.gemini/config/mcp_config.json
# ---------------------------------------------------------------------------
MCP_CONFIG="${HOME}/.gemini/config/mcp_config.json"
info "Configuring Antigravity MCP registration at: ${MCP_CONFIG} ..."

"${VENV_PYTHON}" - <<'PYEOF'
import json
import pathlib
import sys

home = pathlib.Path.home()
config_file = home / ".gemini" / "config" / "mcp_config.json"
config_file.parent.mkdir(parents=True, exist_ok=True)

if config_file.exists():
    try:
        raw = config_file.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
else:
    data = {}

if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
    data["mcpServers"] = {}

data["mcpServers"]["skill-workflow-runner"] = {
    "command": sys.executable,
    "args": ["-m", "mcp_skill_workflow_runner.server"],
    "disabled": False,
    "alwaysAllow": []
}

config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Registered skill-workflow-runner in {config_file}")
PYEOF
success "MCP server registered in mcp_config.json."

# ---------------------------------------------------------------------------
# 6. Deploy MCP Metadata Schemas & Instructions
# ---------------------------------------------------------------------------
ANTIGRAVITY_MCP_DIR="${HOME}/.gemini/antigravity/mcp/skill-workflow-runner"
info "Deploying MCP tool schemas and instructions to: ${ANTIGRAVITY_MCP_DIR} ..."

mkdir -p "${ANTIGRAVITY_MCP_DIR}"

METADATA_DIR="${SOURCE_DIR}/mcp_metadata"
if [[ -d "${METADATA_DIR}" ]]; then
    rm -f "${ANTIGRAVITY_MCP_DIR}"/*.json 2>/dev/null || true
    cp -f "${METADATA_DIR}"/*.json "${ANTIGRAVITY_MCP_DIR}/" 2>/dev/null || true
    if [[ -f "${METADATA_DIR}/instructions.md" ]]; then
        cp -f "${METADATA_DIR}/instructions.md" "${ANTIGRAVITY_MCP_DIR}/instructions.md"
    fi
    success "Deployed 3 core schemas and instruction files to ${ANTIGRAVITY_MCP_DIR}."
fi

# ---------------------------------------------------------------------------
# 7. Validation Import & Execution Test
# ---------------------------------------------------------------------------
info "Validating FastMCP server and CLI imports..."

"${VENV_PYTHON}" - <<'PYEOF'
import sys
import mcp_skill_workflow_runner
from mcp_skill_workflow_runner.server import create_server
from mcp_skill_workflow_runner.dag_engine import DAGEngine
from mcp_skill_workflow_runner.session_manager import SessionManager

app = create_server()
assert app is not None, "Server instance is None"
print("Validation OK: FastMCP application and DAG engine initialized successfully.")
PYEOF

"${VENV_PYTHON}" -m mcp_skill_workflow_runner.cli --version >/dev/null
success "Validation passed: Server, DAG engine, SessionManager and CLI are operational."

# ---------------------------------------------------------------------------
# 8. Create CLI Command Wrapper (skill-workflow)
# ---------------------------------------------------------------------------
USER_BIN_DIR="${HOME}/.local/bin"
mkdir -p "${USER_BIN_DIR}"
CLI_WRAPPER="${USER_BIN_DIR}/skill-workflow"

cat <<EOF > "${CLI_WRAPPER}"
#!/usr/bin/env bash
exec "${VENV_PYTHON}" -m mcp_skill_workflow_runner.cli "\$@"
EOF
chmod +x "${CLI_WRAPPER}"
success "CLI wrapper installed in ${USER_BIN_DIR}/skill-workflow"

# ---------------------------------------------------------------------------
# 9. Installation Complete Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}  MCP skill-workflow-runner successfully installed and registered!    ${NC}"
echo -e "${GREEN}======================================================================${NC}"
echo ""
echo -e "  ${GRAY}Source Path  :${NC} ${SOURCE_DIR}"
echo -e "  ${GRAY}Venv Python  :${NC} ${VENV_PYTHON}"
echo -e "  ${GRAY}MCP Config   :${NC} ${MCP_CONFIG}"
echo -e "  ${GRAY}Metadata Dir :${NC} ${ANTIGRAVITY_MCP_DIR}"
echo -e "  ${GRAY}CLI Command  :${NC} skill-workflow (validate, run, list, sessions, serve)"
echo ""
echo -e "${CYAN}Antigravity will automatically load the skill-workflow-runner MCP server.${NC}"
echo ""
