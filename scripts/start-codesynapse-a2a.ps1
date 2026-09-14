<#
.SYNOPSIS
Starts the single CoScientist A2A façade for Codesynapse on Docker Desktop.

.DESCRIPTION
Maps host-side MONGODB_URI/MONGODB_DATABASE to the CoScientist façade's
isolated MongoDB settings, ensures the internal Docker network exists, starts
the service, and waits for its readiness endpoint.

The default A2A URL is intentionally reachable only from the shared Docker
network.
#>
[CmdletBinding()]
param(
    [string]$MongoUri = $env:MONGODB_URI,

    [string]$MongoDatabase = $env:MONGODB_DATABASE,

    [string]$A2aPublicUrl = $env:CODESYNAPSE_A2A_PUBLIC_URL,

    [string]$NetworkName = $env:CODESYNAPSE_INTERNAL_NETWORK,

    [ValidateRange(1, 900)]
    [int]$TimeoutSeconds = 180,

    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Convert-LocalMongoUriForDocker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    if ($Uri -notmatch "(?i)^mongodb(?:\+srv)?://") {
        throw "MongoDB URI must begin with mongodb:// or mongodb+srv://."
    }

    return [regex]::Replace(
        $Uri,
        "(?i)^(mongodb(?:\+srv)?://(?:[^@/]+@)?)(localhost|127\.0\.0\.1|\[::1\])(?=[:/?]|$)",
        '${1}host.docker.internal'
    )
}

function Invoke-Docker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$CaptureOutput
    )

    if ($CaptureOutput) {
        $output = @(& docker @Arguments 2>&1)
    }
    else {
        & docker @Arguments
        $output = @()
    }
    if ($LASTEXITCODE -ne 0) {
        $details = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        $message = "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
        if ($details) {
            $message += ":$([Environment]::NewLine)$details"
        }
        throw $message
    }
    return $output
}

function Show-FacadeDiagnostics {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ComposeFile)

    Write-Host "Docker Compose state:" -ForegroundColor Yellow
    & docker compose -f $ComposeFile ps
    Write-Host "Recent façade logs:" -ForegroundColor Yellow
    & docker compose -f $ComposeFile logs --tail 100 coscientist-facade
}

function Wait-FacadeReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ComposeFile,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $containerId = ((Invoke-Docker -Arguments @("compose", "-f", $ComposeFile, "ps", "-q", "coscientist-facade") -CaptureOutput) -join "").Trim()
        if ($containerId) {
            $state = ((Invoke-Docker -Arguments @("inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", $containerId) -CaptureOutput) -join "").Trim()
            if ($state -eq "healthy") {
                $ready = (Invoke-Docker -Arguments @("exec", $containerId, "curl", "--fail", "--silent", "http://localhost:8010/readyz") -CaptureOutput) -join ""
                if ($ready -match '"status"\s*:\s*"ready"') {
                    return $containerId
                }
            }
            if ($state -in @("unhealthy", "exited", "dead")) {
                throw "CoScientist façade entered terminal container state: $state"
            }
        }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "CoScientist façade did not reach /readyz within $TimeoutSeconds seconds."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not installed or is unavailable in PATH."
}
Invoke-Docker -Arguments @("compose", "version") | Out-Null
Invoke-Docker -Arguments @("info") | Out-Null

if ([string]::IsNullOrWhiteSpace($MongoUri)) {
    throw "Set MONGODB_URI or pass -MongoUri."
}
if ([string]::IsNullOrWhiteSpace($MongoDatabase)) {
    throw "Set MONGODB_DATABASE or pass -MongoDatabase."
}
if ([string]::IsNullOrWhiteSpace($A2aPublicUrl)) {
    $A2aPublicUrl = "http://coscientist-facade:8010"
}
if ([string]::IsNullOrWhiteSpace($NetworkName)) {
    $NetworkName = "codesynapse-internal"
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeFile = Join-Path $repositoryRoot "docker\docker-compose.codesynapse-facade.yml"
$envFile = Join-Path $repositoryRoot ".env"
if (-not (Test-Path -LiteralPath $composeFile)) {
    throw "Compose file was not found: $composeFile"
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Create $envFile with the CoScientist LLM/MCP runtime credentials before starting the façade."
}

$containerMongoUri = Convert-LocalMongoUriForDocker -Uri $MongoUri
if ($containerMongoUri -ne $MongoUri) {
    Write-Host "Using host.docker.internal for MongoDB inside Docker." -ForegroundColor Cyan
}

$networkExists = & docker network inspect $NetworkName 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Docker -Arguments @("network", "create", $NetworkName) | Out-Null
}

$environmentValues = @{
    "CODESYNAPSE_ENABLED" = "true"
    "CODESYNAPSE_MONGO_URI" = $containerMongoUri
    "CODESYNAPSE_MONGO_DATABASE" = $MongoDatabase
    "CODESYNAPSE_A2A_PUBLIC_URL" = $A2aPublicUrl
    "CODESYNAPSE_INTERNAL_NETWORK" = $NetworkName
}
$previousValues = @{}
foreach ($key in $environmentValues.Keys) {
    $previousValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    [Environment]::SetEnvironmentVariable($key, $environmentValues[$key], "Process")
}

try {
    $upArguments = @("compose", "-f", $composeFile, "up", "-d")
    if (-not $NoBuild) {
        $upArguments += "--build"
    }
    Invoke-Docker -Arguments $upArguments | Out-Null
    $containerId = Wait-FacadeReady -ComposeFile $composeFile -TimeoutSeconds $TimeoutSeconds
    $agentCard = (Invoke-Docker -Arguments @("exec", $containerId, "curl", "--fail", "--silent", "http://localhost:8010/.well-known/agent-card.json") -CaptureOutput) -join ""
}
catch {
    Show-FacadeDiagnostics -ComposeFile $composeFile
    throw
}
finally {
    foreach ($key in $previousValues.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previousValues[$key], "Process")
    }
}

Write-Host "CoScientist A2A façade is ready." -ForegroundColor Green
Write-Host "AgentCard for Codesynapse: $A2aPublicUrl/.well-known/agent-card.json"
Write-Host "A2A JSON-RPC endpoint: $A2aPublicUrl/"
Write-Host "Container AgentCard: $agentCard"
