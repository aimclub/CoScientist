$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$launcherPath = Join-Path $repositoryRoot "scripts\start-mcp.ps1"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Launcher does not exist: $launcherPath"
}

. $launcherPath

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "$Message. Expected '$Expected', got '$Actual'."
    }
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

$composeFile = Get-McpComposeFile
Assert-Equal $composeFile `
    (Join-Path $repositoryRoot "mcp-servers\docker-compose.yml") `
    "Compose file must resolve relative to the launcher"

$envFiles = @(Get-McpRequiredEnvFiles)
Assert-Equal $envFiles.Count 4 "Four MCP env files must be required"

$withBuild = @(Get-McpUpArguments -ComposeFile $composeFile)
$withoutBuild = @(Get-McpUpArguments -ComposeFile $composeFile -NoBuild)
Assert-Equal ($withBuild -join "|") `
    ("compose|-f|$composeFile|up|-d|--build") `
    "Default startup must build images"
Assert-Equal ($withoutBuild -join "|") `
    ("compose|-f|$composeFile|up|-d") `
    "-NoBuild must omit --build"

$services = Get-McpServiceDefinitions
Assert-Equal $services.Count 4 "Four local MCP services must be defined"
Assert-Equal $services["papers-search-mcp-server"].Port 7331 `
    "Papers Search must use port 7331"
Assert-Equal $services["paper-analysis-mcp-server"].Port 7334 `
    "Paper Analysis must use port 7334"

$healthyContainers = @(
    foreach ($serviceName in $services.Keys) {
        [pscustomobject]@{
            Service = $serviceName
            State = "running"
            Health = "healthy"
        }
    }
)
$healthySummary = Get-McpHealthSummary `
    -Containers $healthyContainers `
    -ExpectedServices @($services.Keys)
Assert-True $healthySummary.AllHealthy "All healthy services must pass"
Assert-True (-not $healthySummary.Fatal) "Healthy services must not be fatal"

$failedContainers = @(
    [pscustomobject]@{
        Service = "chemical-mcp-server"
        State = "running"
        Health = "unhealthy"
    }
)
$failedSummary = Get-McpHealthSummary `
    -Containers $failedContainers `
    -ExpectedServices @($services.Keys)
Assert-True (-not $failedSummary.AllHealthy) "Unhealthy services must not pass"
Assert-True $failedSummary.Fatal "An unhealthy service must be fatal"
Assert-True ($failedSummary.Problems.Count -ge 1) `
    "Health failure must include diagnostics"

Write-Output "PowerShell MCP launcher tests passed."
