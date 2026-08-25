param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$HookArguments
)

$ErrorActionPreference = "Stop"

function Test-ContextOsPython {
    param([string]$Candidate)

    if (-not (Get-Command -Name $Candidate -ErrorAction SilentlyContinue)) {
        return $false
    }
    & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

$pythonCommand = $null
if ($env:CONTEXTOS_PYTHON) {
    if (Test-ContextOsPython $env:CONTEXTOS_PYTHON) {
        $pythonCommand = $env:CONTEXTOS_PYTHON
    } else {
        Write-Error "CONTEXTOS_PYTHON is not a working Python 3.9+ interpreter. Fix or unset it; an explicit interpreter is never silently replaced."
        exit 1
    }
} else {
    foreach ($candidate in @("python3", "python")) {
        if (Test-ContextOsPython $candidate) {
            $pythonCommand = $candidate
            break
        }
    }
}

if (-not $pythonCommand) {
    Write-Error "Python 3.9 or newer is required. Install it as 'python3' or 'python', or set CONTEXTOS_PYTHON."
    exit 1
}

& $pythonCommand (Join-Path $PSScriptRoot "context-os-hook.py") @HookArguments
exit $LASTEXITCODE
