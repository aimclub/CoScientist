$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$launcherPath = Join-Path $repositoryRoot "scripts\start-a2a.ps1"

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

$composeFile = Join-Path $repositoryRoot "docker\docker-compose.a2a.yml"
$withBuild = @(Get-A2AUpArguments -ComposeFile $composeFile)
$withoutBuild = @(Get-A2AUpArguments -ComposeFile $composeFile -NoBuild)

Assert-Equal ($withBuild -join "|") `
    ("compose|-f|$composeFile|up|-d|--build") `
    "Default Compose arguments must build the image"
Assert-Equal ($withoutBuild -join "|") `
    ("compose|-f|$composeFile|up|-d") `
    "-NoBuild must omit --build"

$services = Get-A2AServiceDefinitions
Assert-Equal $services.Count 8 "All A2A services must be defined"
Assert-Equal $services["a2a-orchestrator"].AgentKey "orchestrator" `
    "Orchestrator key must be exposed"
Assert-Equal $services["a2a-init"].Port 8008 "Init must use port 8008"

$healthyContainers = @(
    foreach ($serviceName in $services.Keys) {
        [pscustomobject]@{
            Service = $serviceName
            State = "running"
            Health = "healthy"
        }
    }
)
$healthySummary = Get-A2AHealthSummary `
    -Containers $healthyContainers `
    -ExpectedServices @($services.Keys)
Assert-True $healthySummary.AllHealthy "Every healthy service must pass"
Assert-True (-not $healthySummary.Fatal) "Healthy services must not be fatal"

$failedContainers = @(
    [pscustomobject]@{
        Service = "a2a-orchestrator"
        State = "exited"
        Health = ""
    }
)
$failedSummary = Get-A2AHealthSummary `
    -Containers $failedContainers `
    -ExpectedServices @($services.Keys)
Assert-True (-not $failedSummary.AllHealthy) "Missing services must not pass"
Assert-True $failedSummary.Fatal "An exited service must be fatal"
Assert-True ($failedSummary.Problems.Count -ge 1) `
    "Failed health evaluation must explain the problem"

$previousPublicHost = [Environment]::GetEnvironmentVariable(
    "A2A_PUBLIC_HOST",
    "Process"
)
[Environment]::SetEnvironmentVariable(
    "A2A_PUBLIC_HOST",
    "before-test",
    "Process"
)

try {
    try {
        Invoke-WithA2APublicHost -PublicHost "localhost" -Action {
            Assert-Equal $env:A2A_PUBLIC_HOST "localhost" `
                "Wrapped action must receive the requested public host"
            throw "expected-test-error"
        }
    }
    catch {
        Assert-Equal $_.Exception.Message "expected-test-error" `
            "The wrapped exception must be preserved"
    }

    Assert-Equal $env:A2A_PUBLIC_HOST "before-test" `
        "A2A_PUBLIC_HOST must be restored after failure"
}
finally {
    [Environment]::SetEnvironmentVariable(
        "A2A_PUBLIC_HOST",
        $previousPublicHost,
        "Process"
    )
}

Write-Output "PowerShell launcher tests passed."
