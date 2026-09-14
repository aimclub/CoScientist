[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$PublicHost = "localhost",

    [ValidateRange(1, 3600)]
    [int]$TimeoutSeconds = 300,

    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-A2AServiceDefinitions {
    [CmdletBinding()]
    param()

    return [ordered]@{
        "a2a-orchestrator" = [pscustomobject]@{
            AgentKey = "orchestrator"
            Port = 8000
        }
        "a2a-planner" = [pscustomobject]@{
            AgentKey = "planner"
            Port = 8001
        }
        "a2a-hypotheses" = [pscustomobject]@{
            AgentKey = "hypotheses"
            Port = 8002
        }
        "a2a-research" = [pscustomobject]@{
            AgentKey = "research"
            Port = 8003
        }
        "a2a-task-execution" = [pscustomobject]@{
            AgentKey = "task_execution"
            Port = 8004
        }
        "a2a-medical" = [pscustomobject]@{
            AgentKey = "medical"
            Port = 8005
        }
        "a2a-coder" = [pscustomobject]@{
            AgentKey = "coder"
            Port = 8006
        }
        "a2a-init" = [pscustomobject]@{
            AgentKey = "init"
            Port = 8008
        }
    }
}

function Get-A2AUpArguments {
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

function ConvertFrom-A2AComposePsJson {
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

function Get-A2AHealthSummary {
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

function Invoke-WithA2APublicHost {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PublicHost,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    $previous = [Environment]::GetEnvironmentVariable(
        "A2A_PUBLIC_HOST",
        "Process"
    )
    try {
        [Environment]::SetEnvironmentVariable(
            "A2A_PUBLIC_HOST",
            $PublicHost,
            "Process"
        )
        & $Action
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "A2A_PUBLIC_HOST",
            $previous,
            "Process"
        )
    }
}

function Invoke-A2ADocker {
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

function Show-A2ADiagnostics {
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

function Get-A2AComposeContainers {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ComposeFile
    )

    $output = @(Invoke-A2ADocker -Arguments @(
        "compose"
        "-f"
        $ComposeFile
        "ps"
        "--format"
        "json"
    ) -CaptureOutput)
    return @(ConvertFrom-A2AComposePsJson -JsonLines $output)
}

function Wait-A2AServicesHealthy {
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
        $containers = @(Get-A2AComposeContainers -ComposeFile $ComposeFile)
        $summary = Get-A2AHealthSummary `
            -Containers $containers `
            -ExpectedServices $ExpectedServices

        if ($summary.AllHealthy) {
            return
        }
        $lastProblems = @($summary.Problems)
        if ($summary.Fatal) {
            throw "An A2A service failed: $($lastProblems -join '; ')"
        }

        Write-Host "`rWaiting for A2A services: $($lastProblems -join '; ')   " `
            -NoNewline
        Start-Sleep -Seconds 2
    }

    Write-Host ""
    throw "Timed out after $TimeoutSeconds seconds: $($lastProblems -join '; ')"
}

function Test-A2APrerequisites {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $true)]
        [string]$ComposeFile
    )

    $envFile = Join-Path $RepositoryRoot ".env"
    if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
        throw "Docker Compose file not found: $ComposeFile"
    }
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Environment file not found: $envFile"
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install or start Docker Desktop."
    }

    Invoke-A2ADocker -Arguments @("compose", "version") -Quiet
    Invoke-A2ADocker -Arguments @("info") -Quiet
}

function Show-A2AEndpoints {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Services,

        [Parameter(Mandatory = $true)]
        [string]$PublicHost
    )

    Write-Host ""
    Write-Host "All A2A services are healthy." -ForegroundColor Green
    Write-Host "Agent Cards:"
    foreach ($serviceName in $Services.Keys) {
        $service = $Services[$serviceName]
        $url = "http://${PublicHost}:$($service.Port)/.well-known/agent-card.json"
        Write-Host ("  {0,-16} {1}" -f $service.AgentKey, $url)
    }
    Write-Host ""
    Write-Host "JSON-RPC path for Synapse registration: /"
    Write-Host "A2A protocol profile: 0.3.0"
}

function Invoke-A2AStartup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PublicHost,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds,

        [switch]$NoBuild
    )

    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $composeFile = Join-Path $repositoryRoot "docker\docker-compose.a2a.yml"
    $services = Get-A2AServiceDefinitions

    Test-A2APrerequisites `
        -RepositoryRoot $repositoryRoot `
        -ComposeFile $composeFile

    try {
        Invoke-WithA2APublicHost -PublicHost $PublicHost -Action {
            $upArguments = Get-A2AUpArguments `
                -ComposeFile $composeFile `
                -NoBuild:$NoBuild
            Invoke-A2ADocker -Arguments $upArguments

            Wait-A2AServicesHealthy `
                -ComposeFile $composeFile `
                -ExpectedServices @($services.Keys) `
                -TimeoutSeconds $TimeoutSeconds
        }
    }
    catch {
        Show-A2ADiagnostics -ComposeFile $composeFile
        throw
    }

    Invoke-A2ADocker -Arguments @(
        "compose"
        "-f"
        $composeFile
        "ps"
    )
    Show-A2AEndpoints -Services $services -PublicHost $PublicHost
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Invoke-A2AStartup `
            -PublicHost $PublicHost `
            -TimeoutSeconds $TimeoutSeconds `
            -NoBuild:$NoBuild
    }
    catch {
        Write-Error $_.Exception.Message
        exit 1
    }
}
