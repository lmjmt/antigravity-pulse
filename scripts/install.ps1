# Antigravity Pulse Installer Wrapper (Windows PowerShell)
# Usage (local):
#   .\scripts\install.ps1
#   .\scripts\install.ps1 --doctor
# Usage (remote one-liner):
#   irm https://raw.githubusercontent.com/lmjmt/antigravity-pulse/main/scripts/install.ps1 | iex

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$InstallerArgs
)

$ErrorActionPreference = "Stop"

$Repo = if ($env:ANTIGRAVITY_PULSE_REPO) { $env:ANTIGRAVITY_PULSE_REPO } else { "lmjmt/antigravity-pulse" }
$Ref = if ($env:ANTIGRAVITY_PULSE_REF) { $env:ANTIGRAVITY_PULSE_REF } else { "main" }

function Resolve-Python {
    foreach ($cmd in @("python3", "python", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            if ($cmd -eq "py") { return @("py", "-3") }
            return @($cmd)
        }
    }
    throw "Python 3.9+ is required to install and run Antigravity Pulse."
}

$PyCmd = Resolve-Python
$PyExe = $PyCmd[0]
$PyPrefix = if ($PyCmd.Count -gt 1) { $PyCmd[1..($PyCmd.Count - 1)] } else { @() }

$LocalScript = if ($PSScriptRoot) { Join-Path $PSScriptRoot "install.py" } else { "" }
$LocalManifest = if ($PSScriptRoot) { Join-Path (Split-Path $PSScriptRoot -Parent) "plugin.json" } else { "" }

if ($LocalScript -and (Test-Path $LocalScript) -and (Test-Path $LocalManifest)) {
    & $PyExe @PyPrefix $LocalScript @InstallerArgs
    exit $LASTEXITCODE
}

$TmpFile = Join-Path ([System.IO.Path]::GetTempPath()) ("ag-pulse-install-" + [Guid]::NewGuid().ToString("N") + ".py")
$RawUrl = "https://raw.githubusercontent.com/$Repo/$Ref/scripts/install.py"
$Headers = @{}
if ($env:GITHUB_TOKEN) {
    $Headers["Authorization"] = "Bearer $($env:GITHUB_TOKEN)"
}

try {
    Write-Host "Fetching Antigravity Pulse installer from $RawUrl ..."
    Invoke-WebRequest -Uri $RawUrl -Headers $Headers -OutFile $TmpFile -UseBasicParsing
    & $PyExe @PyPrefix $TmpFile "--remote" "--repo" $Repo @InstallerArgs
    exit $LASTEXITCODE
} finally {
    if (Test-Path $TmpFile) { Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue }
}
