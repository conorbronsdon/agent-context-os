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
    $previousErrorActionPreference = $ErrorActionPreference
    $probeSucceeded = $false
    try {
        $ErrorActionPreference = "Continue"
        & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >$null 2>$null
        $probeSucceeded = $LASTEXITCODE -eq 0
    } catch {
        $probeSucceeded = $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $probeSucceeded
}

$pythonCommand = $null
if ($env:CONTEXTOS_PYTHON) {
    if (Test-ContextOsPython $env:CONTEXTOS_PYTHON) {
        $pythonCommand = $env:CONTEXTOS_PYTHON
    } else {
        [Console]::Error.WriteLine("CONTEXTOS_PYTHON is set to '$($env:CONTEXTOS_PYTHON)', which is not a working Python 3.9+ interpreter.")
        [Console]::Error.WriteLine("Fix or unset it; an explicit interpreter is never silently replaced with another one.")
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
    [Console]::Error.WriteLine("Python 3.9 or newer is required. Install it as 'python3' or 'python', or set CONTEXTOS_PYTHON.")
    exit 1
}

& $pythonCommand (Join-Path $PSScriptRoot "context-os-hook.py") @HookArguments
exit $LASTEXITCODE
