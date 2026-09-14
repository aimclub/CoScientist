[CmdletBinding()]
param(
    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 300,

    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:McpRepositoryRoot = Split-Path -Parent $PSScriptRoot

function Get-McpComposeFile {
    [CmdletBinding()]
    param()

    return Join-Path $script:McpRepositoryRoot "mcp-servers\docker-compose.yml"
}

function Get-McpRequiredEnvFiles {
    [CmdletBinding()]
    param()

    $base = Join-Path $script:McpRepositoryRoot "mcp-servers"
    return @(
        Join-Path $base "papers-search-mcp-server\.env"
        Join-Path $base "chemical-mcp-server\.env"
        Join-Path $base "dataset-collection-mcp-server\.env"
        Join-Path $base "paper-analysis-mcp-server\.env"
    )
}

function Get-McpServiceDefinitions {
    [CmdletBinding()]
    param()

    return [ordered]@{
        "papers-search-mcp-server" = [pscustomobject]@{
            DisplayName = "Papers Search"
            Port = 7331
        }
        "chemical-mcp-server" = [pscustomobject]@{
            DisplayName = "Chemical"
            Port = 7332
        }
        "dataset-collection-mcp-server" = [pscustomobject]@{
            DisplayName = "Dataset Collection"
            Port = 7333
        }
        "paper-analysis-mcp-server" = [pscustomobject]@{
            DisplayName = "Paper Analysis"
            Port = 7334
        }
    }
}

function Get-McpUpArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile,

        [switch]$NoBuild
    )

    $arguments = @(
        "compose"
        "-f"
        $ComposeFile
        "up"
        "-d"
    )
    if (-not $NoBuild) {
        $arguments += "--build"
    }
    return $arguments
}

function ConvertFrom-McpComposePsJson {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [string[]]$JsonLines
    )

    $content = ($JsonLines | Where-Object { $_.Trim() }) -join [Environment]::NewLine
    if (-not $content) {
        return @()
    }

    try {
        return @($content | ConvertFrom-Json)
    }
    catch {
        $containers = @()
        foreach ($line in $JsonLines) {
            if ($line.Trim()) {
                $containers += $line | ConvertFrom-Json
            }
        }
        return $containers
    }
}

function Get-McpHealthSummary {
    [CmdletBinding()]
    param(
        [AllowEmptyCollection()]
        [object[]]$Containers,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedServices
    )

    $byService = @{}
    foreach ($container in $Containers) {
        if ($null -ne $container.Service) {
            $byService[[string]$container.Service] = $container
        }
    }

    $fatal = $false
    $pending = $false
    $problems = @()

    foreach ($service in $ExpectedServices) {
        if (-not $byService.ContainsKey($service)) {
            $pending = $true
            $problems += "$service is not created yet"
            continue
        }

        $container = $byService[$service]
        $state = ([string]$container.State).ToLowerInvariant()
        $health = ([string]$container.Health).ToLowerInvariant()

        if ($state -in @("exited", "dead", "removing")) {
            $fatal = $true
            $problems += "$service is $state"
            continue
        }
        if ($health -eq "unhealthy") {
            $fatal = $true
            $problems += "$service is unhealthy"
            continue
        }
        if ($state -eq "running" -and $health -eq "healthy") {
            continue
        }

        $pending = $true
        $displayState = if ($health) { "$state/$health" } else { $state }
        $problems += "$service is $displayState"
    }

    return [pscustomobject]@{
        AllHealthy = (-not $fatal -and -not $pending)
        Fatal = $fatal
        Problems = @($problems)
    }
}

function Invoke-McpDocker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [switch]$CaptureOutput,

        [switch]$Quiet
    )

    if ($CaptureOutput -or $Quiet) {
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

    if ($CaptureOutput) {
        return $output
    }
}

function Test-McpPrerequisites {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile
    )

    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
        throw "Docker Compose file not found: $ComposeFile"
    }

    foreach ($envFile in Get-McpRequiredEnvFiles) {
        if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
            $example = "$envFile.example"
            throw (
                "Environment file not found: $envFile$([Environment]::NewLine)" +
                "Create it without credentials, then fill required values manually:$([Environment]::NewLine)" +
                "Copy-Item `"$example`" `"$envFile`""
            )
        }
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install or start Docker Desktop."
    }

    Invoke-McpDocker -Arguments @("compose", "version") -Quiet
    Invoke-McpDocker -Arguments @("info") -Quiet
}

function Get-McpComposeContainers {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile
    )

    $output = @(Invoke-McpDocker -Arguments @(
        "compose"
        "-f"
        $ComposeFile
        "ps"
        "--format"
        "json"
    ) -CaptureOutput)
    return @(ConvertFrom-McpComposePsJson -JsonLines $output)
}

function Wait-McpServicesHealthy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedServices,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastProblems = @()

    while ([DateTime]::UtcNow -lt $deadline) {
        $containers = @(Get-McpComposeContainers -ComposeFile $ComposeFile)
        $summary = Get-McpHealthSummary `
            -Containers $containers `
            -ExpectedServices $ExpectedServices

        if ($summary.AllHealthy) {
            return
        }
        $lastProblems = @($summary.Problems)
        if ($summary.Fatal) {
            throw "An MCP service failed: $($lastProblems -join '; ')"
        }

        Write-Host "`rWaiting for MCP services: $($lastProblems -join '; ')   " `
            -NoNewline
        Start-Sleep -Seconds 2
    }

    Write-Host ""
    throw "Timed out after $TimeoutSeconds seconds: $($lastProblems -join '; ')"
}

function Show-McpDiagnostics {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile
    )

    Write-Host ""
    Write-Host "Docker Compose service state:" -ForegroundColor Yellow
    & docker compose -f $ComposeFile ps 2>&1 | ForEach-Object {
        Write-Host ([string]$_)
    }

    Write-Host ""
    Write-Host "Last 100 log lines:" -ForegroundColor Yellow
    & docker compose -f $ComposeFile logs --tail 100 2>&1 | ForEach-Object {
        Write-Host ([string]$_)
    }
}

function Show-McpEndpoints {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Services
    )

    Write-Host ""
    Write-Host "All local MCP services are transport-ready." -ForegroundColor Green
    foreach ($serviceName in $Services.Keys) {
        $service = $Services[$serviceName]
        Write-Host ""
        Write-Host $service.DisplayName
        Write-Host "  Windows:       http://localhost:$($service.Port)/mcp"
        Write-Host "  A2A container: http://host.docker.internal:$($service.Port)/mcp"
    }
    Write-Host ""
    Write-Host "Run the MCP protocol smoke test before using scientific tools:"
    Write-Host "  .\.venv\Scripts\python.exe scripts\check-local-mcp.py"
}

function Invoke-McpStartup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds,

        [switch]$NoBuild
    )

    $composeFile = Get-McpComposeFile
    $services = Get-McpServiceDefinitions

    Test-McpPrerequisites -ComposeFile $composeFile

    try {
        $upArguments = Get-McpUpArguments `
            -ComposeFile $composeFile `
            -NoBuild:$NoBuild
        Invoke-McpDocker -Arguments $upArguments

        Wait-McpServicesHealthy `
            -ComposeFile $composeFile `
            -ExpectedServices @($services.Keys) `
            -TimeoutSeconds $TimeoutSeconds
    }
    catch {
        Show-McpDiagnostics -ComposeFile $composeFile
        throw
    }

    Invoke-McpDocker -Arguments @(
        "compose"
        "-f"
        $composeFile
        "ps"
    )
    Show-McpEndpoints -Services $services
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Invoke-McpStartup `
            -TimeoutSeconds $TimeoutSeconds `
            -NoBuild:$NoBuild
    }
    catch {
        Write-Error $_.Exception.Message
        exit 1
    }
}
