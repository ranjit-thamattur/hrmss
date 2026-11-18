<#
.SYNOPSIS
  Apply an updated Peak HRMS codebase zip on a new feature branch, commit, push and open a PR into qa.

.EXAMPLE
  cd $HOME\Downloads\PeakAI\hrms_HV\hrmss   (Git Bash users: scripts/apply-update.sh)
  .\scripts\apply-update.ps1 -Zip "$HOME\Downloads\peak-hrms-full.zip" -Branch "feature/payroll-fixes" -Message "Payroll fixes from review"

.NOTES
  - The zip must contain the full project (a top folder with docker-compose.yml inside).
  - Files in the repo that are not in the zip are deleted (mirror), except .git, node_modules, .venv, dist,
    storage, .env and the local SQLite database. Git keeps the history, so nothing is lost for good.
  - Requires: git; gh (GitHub CLI) only if you want the PR opened for you.
#>
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [Parameter(Mandatory = $true)][string]$Branch,
    [string]$Message = "Update codebase",
    [string]$Base = "",   # empty = the branch you are on now
    [string]$PrInto = "qa",
    [switch]$NoPr
)
$ErrorActionPreference = "Stop"

$repo = (git rev-parse --show-toplevel 2>$null)
if (-not $repo) { throw "Run this inside the cloned repository folder." }
$repo = $repo -replace "/", "\"
Set-Location $repo
if (-not (Test-Path $Zip)) { throw "Zip not found: $Zip" }
if (git status --porcelain) { throw "You have uncommitted changes. Commit or stash them first (git stash)." }
if (-not $Base) { $Base = (git branch --show-current) }

Write-Host "1/6  Updating $Base from GitHub..." -ForegroundColor Cyan
git fetch origin
git checkout $Base
git pull --ff-only origin $Base

Write-Host "2/6  Creating branch $Branch from $Base..." -ForegroundColor Cyan
git checkout -b $Branch

Write-Host "3/6  Unzipping..." -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP ("hrms-update-" + [guid]::NewGuid().ToString("N"))
Expand-Archive -Path $Zip -DestinationPath $tmp -Force
$src = Get-ChildItem -Path $tmp -Recurse -Filter "docker-compose.yml" | Select-Object -First 1 | ForEach-Object { $_.DirectoryName }
if (-not $src) { throw "No docker-compose.yml in the zip - is this the full Peak HRMS codebase?" }

Write-Host "4/6  Copying over the project (mirror)..." -ForegroundColor Cyan
robocopy $src $repo /MIR /NFL /NDL /NJH /NJS /NP `
    /XD .git node_modules .venv venv dist storage __pycache__ .pytest_cache .ruff_cache `
    /XF .env *.db *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }
Remove-Item $tmp -Recurse -Force

Write-Host "5/6  Committing..." -ForegroundColor Cyan
git add -A
if (-not (git status --porcelain)) {
    Write-Host "No changes compared with $Base. Nothing to commit." -ForegroundColor Yellow
    git checkout $Base; git branch -D $Branch; exit 0
}
git status --short
git commit -m $Message
git push -u origin $Branch

if (-not $NoPr) {
    Write-Host "6/6  Opening pull request $Branch -> $PrInto..." -ForegroundColor Cyan
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        gh pr create --base $PrInto --head $Branch --title $Message --body "Codebase update applied from $(Split-Path $Zip -Leaf)."
    } else {
        Write-Host "GitHub CLI not installed. Open the PR in the browser: base '$PrInto' <- compare '$Branch'." -ForegroundColor Yellow
    }
}
Write-Host "Done." -ForegroundColor Green
