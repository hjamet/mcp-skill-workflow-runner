# install.ps1 — mcp-skill-workflow-runner automated all-in-one installer for Windows
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1        # Run locally from repo
#   irm https://raw.githubusercontent.com/.../install.ps1 | iex    # Run remotely via PowerShell
#
# Options:
#   -InstallDir <path> : Custom installation directory
#   -RepoUrl <url>    : Custom Git repository URL
#   -PythonPath <path>: Explicit Python executable path (>= 3.10)
#   -Force            : Cleanly recreate virtual environment

[CmdletBinding()]
param (
    [string]$InstallDir = "",
    [string]$RepoUrl = $env:SKILL_WORKFLOW_RUNNER_REPO_URL,
    [string]$PythonPath = "",
    [switch]$Force = $false
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Visual Styling Helpers
# ---------------------------------------------------------------------------
function Write-Header {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "     MCP Skill Workflow Runner - All-In-One Installer (Windows)       " -ForegroundColor Cyan
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Message)
    Write-Host "[*] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[+] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Write-ErrorExit {
    param([string]$Message)
    Write-Host "`n[-] ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Invoke-PythonCode {
    param(
        [string]$PythonExe,
        [string]$Code
    )
    $TempScript = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), ("mcp_setup_" + [System.Guid]::NewGuid().ToString("N") + ".py"))
    try {
        [System.IO.File]::WriteAllText($TempScript, $Code, [System.Text.Encoding]::UTF8)
        & "$PythonExe" "$TempScript"
        if ($LASTEXITCODE -ne 0) {
            throw ("Python script execution failed with exit code " + $LASTEXITCODE)
        }
    } finally {
        if (Test-Path $TempScript) {
            Remove-Item -Force $TempScript -ErrorAction SilentlyContinue
        }
    }
}

# ---------------------------------------------------------------------------
# 1. Detect Python 3.10+
# ---------------------------------------------------------------------------
Write-Header
Write-Step "Detecting Python 3.10+ environment..."

$ResolvedPython = $null
$ResolvedVersion = $null

if ($PythonPath -and (Test-Path $PythonPath)) {
    try {
        $vOutput = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        $vParts = $vOutput.Trim().Split('.')
        if ([int]$vParts[0] -eq 3 -and [int]$vParts[1] -ge 10) {
            $ResolvedPython = $PythonPath
            $ResolvedVersion = $vOutput.Trim()
        }
    } catch {}
}

if (-not $ResolvedPython) {
    $Candidates = @(
        "py -3.12",
        "py -3.11",
        "py -3.10",
        "py -3",
        "python3",
        "python",
        "py"
    )

    foreach ($Cand in $Candidates) {
        try {
            $split = $Cand.Split(' ')
            $exe = $split[0]
            $cArgs = if ($split.Length -gt 1) { $split[1..($split.Length - 1)] } else { @() }
            
            $testArgs = $cArgs + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}|{sys.executable}')")
            $procOutput = & $exe $testArgs 2>$null
            if ($procOutput) {
                $outStr = ($procOutput | Out-String).Trim()
                $parts = $outStr.Split('|')
                if ($parts.Length -ge 2) {
                    $ver = $parts[0].Trim()
                    $pPath = $parts[1].Trim()
                    $vParts = $ver.Split('.')
                    if ([int]$vParts[0] -eq 3 -and [int]$vParts[1] -ge 10) {
                        $ResolvedPython = $pPath
                        $ResolvedVersion = $ver
                        break
                    }
                }
            }
        } catch {
            continue
        }
    }
}

if (-not $ResolvedPython) {
    Write-ErrorExit "Python 3.10+ not found on your system.`nPlease install Python 3.10, 3.11, or 3.12 (e.g. via 'winget install Python.Python.3.12' or from https://www.python.org/downloads/)."
}

Write-Success "Found Python $ResolvedVersion at: $ResolvedPython"

# Check uv availability (optional accelerator)
$HasUv = $false
try {
    $uvVer = & uv --version 2>$null
    if ($uvVer) {
        $HasUv = $true
        $uvClean = ($uvVer | Out-String).Trim()
        Write-Success "Found 'uv' tool ($uvClean) for accelerated installation."
    }
} catch {
    $HasUv = $false
}

# ---------------------------------------------------------------------------
# 2. Resolve Source Directory
# ---------------------------------------------------------------------------
Write-Step "Resolving source directory..."

$SourceDir = $null

if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) {
    $content = Get-Content (Join-Path $PSScriptRoot "pyproject.toml") -Raw -ErrorAction SilentlyContinue
    if ($content -match 'name\s*=\s*"mcp-skill-workflow-runner"') {
        $SourceDir = $PSScriptRoot
        Write-Success "Using local repository at: $SourceDir"
    }
}

if (-not $SourceDir -and (Test-Path ".\pyproject.toml")) {
    $content = Get-Content ".\pyproject.toml" -Raw -ErrorAction SilentlyContinue
    if ($content -match 'name\s*=\s*"mcp-skill-workflow-runner"') {
        $SourceDir = (Get-Item .).FullName
        Write-Success "Using current directory at: $SourceDir"
    }
}

if (-not $SourceDir) {
    if ($InstallDir) {
        $TargetDir = $InstallDir
    } else {
        $DefaultCodeDir = Join-Path $env:USERPROFILE "Documents\code\mcp-skill-workflow-runner"
        if (Test-Path (Join-Path $DefaultCodeDir "pyproject.toml")) {
            $TargetDir = $DefaultCodeDir
        } else {
            $TargetDir = Join-Path $env:USERPROFILE ".mcp-skill-workflow-runner\repo"
        }
    }

    if (Test-Path (Join-Path $TargetDir "pyproject.toml")) {
        $SourceDir = $TargetDir
        Write-Success "Found existing repository at: $SourceDir"
    } else {
        Write-Step "Source directory not found locally. Cloning into: $TargetDir ..."
        $ParentDir = Split-Path -Parent $TargetDir
        if (-not (Test-Path $ParentDir)) {
            New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null
        }

        $CloneUrl = if ($RepoUrl) { $RepoUrl } else { "https://github.com/UNIL-DESI/mcp-skill-workflow-runner.git" }
        
        try {
            & git clone $CloneUrl $TargetDir
            if ($LASTEXITCODE -ne 0) {
                throw "Git clone returned non-zero exit code $LASTEXITCODE"
            }
            $SourceDir = $TargetDir
            Write-Success "Cloned repository to: $SourceDir"
        } catch {
            Write-ErrorExit "Failed to clone repository from $CloneUrl. Please specify a valid -RepoUrl or clone manually."
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Create Isolated Virtual Environment
# ---------------------------------------------------------------------------
$VenvDir = Join-Path $SourceDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Step "Setting up isolated virtualenv at: $VenvDir ..."

if ($Force -and (Test-Path $VenvDir)) {
    Write-Warn "Force switch specified. Recreating virtual environment..."
    Remove-Item -Recurse -Force $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    if ($HasUv) {
        & uv venv "$VenvDir" --python "$ResolvedPython"
    } else {
        & $ResolvedPython -m venv "$VenvDir"
    }

    if (-not (Test-Path $VenvPython)) {
        Write-ErrorExit "Failed to create virtual environment at $VenvDir"
    }
    Write-Success "Virtual environment created successfully."
} else {
    Write-Success "Virtual environment already exists."
}

# ---------------------------------------------------------------------------
# 4. Install Dependencies and Editable Package
# ---------------------------------------------------------------------------
Write-Step "Installing mcp-skill-workflow-runner and dependencies in editable mode..."

Push-Location $SourceDir
try {
    if ($HasUv) {
        & uv pip install --python "$VenvPython" -e .
        if ($LASTEXITCODE -ne 0) {
            throw "uv pip install failed with exit code $LASTEXITCODE"
        }
    } else {
        & "$VenvPython" -m pip install --quiet --upgrade pip
        & "$VenvPython" -m pip install --no-user -e .
        if ($LASTEXITCODE -ne 0) {
            throw "pip install failed with exit code $LASTEXITCODE"
        }
    }
    Write-Success "Package and dependencies installed successfully."
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# 5. Register Server in ~/.gemini/config/mcp_config.json
# ---------------------------------------------------------------------------
$McpConfigPath = Join-Path $env:USERPROFILE ".gemini\config\mcp_config.json"
Write-Step "Configuring Antigravity MCP registration at: $McpConfigPath ..."

$PyConfigCode = @'
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
'@

try {
    Invoke-PythonCode -PythonExe $VenvPython -Code $PyConfigCode
    Write-Success "MCP server registered in mcp_config.json."
} catch {
    Write-ErrorExit "Failed to register MCP server configuration in $McpConfigPath : $_"
}

# ---------------------------------------------------------------------------
# 6. Deploy MCP Metadata Schemas & Instructions
# ---------------------------------------------------------------------------
$AntigravityMcpDir = Join-Path $env:USERPROFILE ".gemini\antigravity\mcp\skill-workflow-runner"
Write-Step "Deploying MCP tool schemas and instructions to: $AntigravityMcpDir ..."

if (-not (Test-Path $AntigravityMcpDir)) {
    New-Item -ItemType Directory -Force -Path $AntigravityMcpDir | Out-Null
}

$MetadataSourceDir = Join-Path $SourceDir "mcp_metadata"
$SchemaFiles = @(
    "start_workflow.json",
    "next_step.json",
    "end_workflow.json",
    "instructions.md"
)

# Clean up any obsolete schema files
Get-ChildItem -Path $AntigravityMcpDir -Filter "*.json" -File | Where-Object { $_.Name -notin $SchemaFiles } | Remove-Item -Force -ErrorAction SilentlyContinue

$CopiedCount = 0
foreach ($File in $SchemaFiles) {
    $SrcFile = Join-Path $MetadataSourceDir $File
    $DstFile = Join-Path $AntigravityMcpDir $File
    if (Test-Path $SrcFile) {
        Copy-Item -Path $SrcFile -Destination $DstFile -Force
        $CopiedCount++
    }
}

if ($CopiedCount -ge 4) {
    Write-Success "Deployed $CopiedCount schema and instruction files to $AntigravityMcpDir."
} else {
    Write-Warn "Could not find all metadata files in $MetadataSourceDir."
}

# ---------------------------------------------------------------------------
# 7. Validation Import & Execution Test
# ---------------------------------------------------------------------------
Write-Step "Validating FastMCP server and CLI imports..."

$PyTestCode = @'
import sys
import mcp_skill_workflow_runner
from mcp_skill_workflow_runner.server import create_server
from mcp_skill_workflow_runner.dag_engine import DAGEngine
from mcp_skill_workflow_runner.session_manager import SessionManager

app = create_server()
assert app is not None, "Server instance is None"
print("Validation OK: FastMCP application and DAG engine initialized successfully.")
'@

try {
    Invoke-PythonCode -PythonExe $VenvPython -Code $PyTestCode
} catch {
    Write-ErrorExit "Validation test failed: $_"
}

# Test CLI help
& "$VenvPython" -m mcp_skill_workflow_runner.cli --version | Out-Null
Write-Success "Validation passed: Server, DAG engine, SessionManager and CLI are operational."

# ---------------------------------------------------------------------------
# 8. Create CLI Command Wrapper (skill-workflow)
# ---------------------------------------------------------------------------
$LocalBinDir = Join-Path $env:USERPROFILE ".local\bin"
if (-not (Test-Path $LocalBinDir)) {
    New-Item -ItemType Directory -Force -Path $LocalBinDir | Out-Null
}

$CmdWrapper = Join-Path $LocalBinDir "skill-workflow.cmd"
$PsWrapper = Join-Path $LocalBinDir "skill-workflow.ps1"

$CmdLines = @(
    "@echo off",
    ('"{0}" -m mcp_skill_workflow_runner.cli %*' -f $VenvPython)
)
[System.IO.File]::WriteAllLines($CmdWrapper, $CmdLines)

$PsLines = @(
    ('& "{0}" -m mcp_skill_workflow_runner.cli $args' -f $VenvPython)
)
[System.IO.File]::WriteAllLines($PsWrapper, $PsLines)

Write-Success "CLI wrapper installed in $LocalBinDir"

# ---------------------------------------------------------------------------
# 9. Installation Complete Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  MCP skill-workflow-runner successfully installed and registered!    " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Source Path  : $SourceDir" -ForegroundColor Gray
Write-Host "  Venv Python  : $VenvPython" -ForegroundColor Gray
Write-Host "  MCP Config   : $McpConfigPath" -ForegroundColor Gray
Write-Host "  Metadata Dir : $AntigravityMcpDir" -ForegroundColor Gray
Write-Host "  CLI Command  : skill-workflow" -ForegroundColor Gray
Write-Host ""
Write-Host "Antigravity will automatically load the skill-workflow-runner MCP server." -ForegroundColor Cyan
Write-Host ""
