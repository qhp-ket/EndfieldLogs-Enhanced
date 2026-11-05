param(
    [string]$DotNet,
    [string]$OutputDirectory,
    [string[]]$Suite,
    [string[]]$Group,
    [switch]$SkipBuild,
    [switch]$NativeCapture
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $PSScriptRoot 'Verification/BuildState.ps1')
$suites = [ordered]@{
    foundations = 'compare-foundations'
    fields = 'compare-fields'
    observations = 'compare-observations'
    timers = 'compare-timers'
    'skill-identities' = 'compare-skill-identities'
    'skill-damage' = 'compare-skill-damage'
    'hit-observations' = 'compare-hit-observations'
    'packet-evidence' = 'compare-packet-evidence'
    'evidence-json' = 'compare-evidence-json'
    'json-diagnostics' = 'compare-evidence-json'
    'python-display' = 'compare-evidence-json'
    'official-timers' = 'compare-official-timers'
    catalogs = 'compare-catalogs'
    'action-indices' = 'compare-action-indices'
    'buff-instances' = 'compare-buff-instances'
    'buff-dynamics' = 'compare-buff-instances'
    'buff-keywords' = 'compare-buff-instances'
    'effect-approval' = 'compare-effect-approval'
    'effect-conditions' = 'compare-effect-conditions'
    'effect-windows' = 'compare-effect-windows'
    'effect-stacks' = 'compare-effect-stacks'
    'effect-registry' = 'compare-effect-registry'
    'effect-specifications' = 'compare-effect-registry'
    'dynamic-effect-specifications' = 'compare-effect-registry'
    'combo-windows' = 'compare-combo-windows'
    'packet-effect-display' = 'compare-packet-effect-display'
    'buff-classification' = 'compare-buff-classification'
    'buff-labels' = 'compare-buff-labels'
    'report-effect-windows' = 'compare-report-effect-windows'
    'report-loadouts' = 'compare-report-loadouts'
    'baseline-evidence' = 'compare-baseline-evidence'
    'static-arts-strength' = 'compare-static-arts-strength'
    'static-multipliers' = 'compare-static-multipliers'
    'static-applicability' = 'compare-static-applicability'
    'report-baseline' = 'compare-report-baseline'
    'attack-dependence' = 'compare-attack-dependence'
    'packet-allocation' = 'compare-packet-allocation'
    'allocation-context' = 'compare-allocation-context'
    'allocation-debug' = 'compare-allocation-phases'
    'allocation-baseline' = 'compare-allocation-phases'
    'allocation-resistance' = 'compare-allocation-phases'
    'allocation-multipliers' = 'compare-allocation-phases'
    'allocation-contributors' = 'compare-allocation-phases'
    'allocation-arts' = 'compare-allocation-phases'
    'allocation-hit' = 'compare-allocation-phases'
    'ink-provenance' = 'compare-ink-provenance'
    'damage-ledger' = 'compare-damage-ledger'
    'report-accounting' = 'compare-report-accounting'
    'allocation-preflight' = 'compare-allocation-preflight'
    'report-lifecycle' = 'compare-report-lifecycle'
    'report-projection' = 'compare-report-projection'
    'critical-evidence' = 'compare-critical-evidence'
    'report-timeline' = 'compare-report-timeline'
    'report-buffs' = 'compare-report-buffs'
    'report-export' = 'compare-report-export'
    'live-projection' = 'compare-live-projection'
    'live-engine' = 'compare-live-engine'
    'live-allocation' = 'compare-live-allocation'
    'live-clock' = 'compare-live-projection'
    'live-session' = 'compare-live-session'
    'live-publication' = 'compare-live-publication'
    'session-business' = 'compare-session-business'
    'session-scene' = 'compare-session-scene'
    'session-inventory' = 'compare-session-inventory'
    'trace-bridge' = 'compare-trace-bridge'
    'app-settings' = 'compare-app-settings'
    'native-skins' = 'compare-native-skins'
    'raw-log-proofs' = 'compare-raw-log-proofs'
    'history-index' = 'compare-history-index'
    'damage-series' = 'compare-damage-series'
    'timeline-skills' = 'compare-timeline-skills'
    'energy-observations' = 'compare-energy-observations'
    'enemy-observations' = 'compare-enemy-observations'
    'buff-display' = 'compare-buff-display'
    'battle-evidence' = 'compare-battle-evidence'
    'battle-presentation' = 'compare-battle-presentation'
    'release-updates' = 'compare-release-updates'
    'input-interpretation' = 'compare-input-interpretation'
    'input-evidence' = 'compare-input-evidence'
    'input-backends' = 'compare-input-backends'
    vision = 'compare-vision'
    'weapon-refinement' = 'compare-weapon-refinement'
    'loadout-snapshots' = 'compare-loadout-snapshots'
    'loadout-state' = 'compare-loadout-state'
    'battle-ingestion' = 'compare-battle-ingestion'
    framing = 'compare-framing'
    'message-session' = 'compare-session'
    packets = 'compare-packets'
    transport = 'compare-transport'
    protocol = 'compare-protocol'
}
$full = -not $PSBoundParameters.ContainsKey('Suite') -and -not $PSBoundParameters.ContainsKey('Group')
$selected = @($Suite | Select-Object -Unique)
if ($full) { $selected = @($suites.Keys) }
foreach ($name in $selected) { if (-not $suites.Contains($name)) { throw "Unknown differential suite: $name" } }
if (-not $full -and -not $selected.Count -and -not $Group.Count) { throw 'Select at least one suite or spec group.' }

if (-not $DotNet) {
    $candidates = @(
        $(if ($env:DOTNET_ROOT) { Join-Path $env:DOTNET_ROOT 'dotnet.exe' }),
        (Join-Path $repoRoot '.toolchains/dotnet/dotnet.exe'),
        (Join-Path (Split-Path $repoRoot -Parent) '.toolchains/dotnet/dotnet.exe'),
        $((Get-Command dotnet -ErrorAction SilentlyContinue).Source)
    )
    $DotNet = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $DotNet) { throw 'Install the SDK specified in global.json or pass -DotNet.' }
$DotNet = [IO.Path]::GetFullPath($DotNet)
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot '_development/verification/dotnet' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$env:DOTNET_ROOT = Split-Path $DotNet -Parent
$env:DOTNET_CLI_HOME = Join-Path $repoRoot '.dotnet-home'
$env:NUGET_PACKAGES = Join-Path $repoRoot '.nuget/packages'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$stateDirectory = Join-Path $repoRoot '_development/verification/dotnet/build-state'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$receiptPath = Join-Path $stateDirectory 'build.json'
$restorePath = Join-Path $stateDirectory 'restore.json'
$projects = @('Core','Protocol','Native','Capture','Runtime','Specs','Tools')
if ($full) { $projects += 'Desktop' }
$report = [ordered]@{full=$full; suites=[ordered]@{}; specs=@{status='not_selected'; groups=@($Group)}; native=@{status='not_selected'}; fixtures=[ordered]@{}}
$report.resource_manifest_sha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot '_internal/data/resource-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()
foreach ($name in $suites.Keys) {
    $report.suites[$name] = @{status=$(if ($name -in $selected) {'not_run'} else {'not_selected'})}
}

function Invoke-DotNet([string[]]$Arguments) {
    & $DotNet @Arguments
    if ($LASTEXITCODE -ne 0) { throw "dotnet command failed ($LASTEXITCODE): $($Arguments[0])" }
}

$failure = $false
Push-Location $PSScriptRoot
try {
    $sdk = (& $DotNet --version).Trim()
    if ($LASTEXITCODE) { throw 'Cannot query selected SDK.' }
    $source = Get-VerificationSource $repoRoot $sdk
    $report.source = $source
    if ($SkipBuild) {
        $receipt = if (Test-Path -LiteralPath $receiptPath) { Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json } else { $null }
        Assert-VerificationBuild $receipt $source $PSScriptRoot $projects
        $report.build = 'validated_receipt'
    }
    else {
        $restore = if (Test-Path -LiteralPath $restorePath) { Get-Content -LiteralPath $restorePath -Raw | ConvertFrom-Json } else { $null }
        $assetsMissing = @($projects | Where-Object { -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "$_/obj/project.assets.json")) })
        if ($null -eq $restore -or $restore.sha256 -ne $source.restore_sha256 -or $restore.sdk -ne $sdk -or $assetsMissing.Count -or @($projects | Where-Object { $_ -notin $restore.projects }).Count) {
            $report.restore = 'locked_restore'
            $targets = if ($full) { @('EndfieldLogs.slnx') } else { @('Tools/EndfieldLogs.Tools.csproj','Specs/EndfieldLogs.Specs.csproj') }
            foreach ($target in $targets) { Invoke-DotNet @('restore',$target,'--locked-mode','--disable-build-servers') }
            @{sdk=$sdk;sha256=$source.restore_sha256;projects=$projects} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $restorePath -Encoding UTF8
        }
        else { $report.restore = 'unchanged_dependency_inputs' }
        $targets = if ($full) { @('EndfieldLogs.slnx') } else { @('Tools/EndfieldLogs.Tools.csproj','Specs/EndfieldLogs.Specs.csproj') }
        foreach ($target in $targets) { Invoke-DotNet @('build',$target,'--no-restore','--disable-build-servers') }
        $after = Get-VerificationSource $repoRoot $sdk
        if ($after.sha256 -ne $source.sha256) { throw 'Source changed during build; build receipt refused.' }
        @{source=$source;projects=$projects;artifacts=(Get-VerificationArtifacts $PSScriptRoot $projects)} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
        $report.build = 'built'
    }
    if ($full -or $Group.Count) {
        $groupJson = & $DotNet 'Specs/bin/Debug/net10.0/EndfieldLogs.Specs.dll' --list-groups
        if ($LASTEXITCODE) { throw 'Cannot query spec groups.' }
        # Windows PowerShell keeps a parsed JSON array as one pipeline object; flatten it before scope checks/serialization.
        [string[]]$knownGroups = @((ConvertFrom-Json -InputObject ($groupJson -join "`n")) | ForEach-Object { [string]$_ })
        [string[]]$executedGroups = if ($full) { $knownGroups } else { @($Group | Select-Object -Unique) }
        $report.specs = @{status='not_run';groups=$executedGroups}
        $report.specs.not_selected = @($knownGroups | Where-Object { $_ -notin $report.specs.groups })
        $arguments = @('Specs/bin/Debug/net10.0/EndfieldLogs.Specs.dll')
        if (-not $full) { $arguments += @('--groups',($report.specs.groups -join ',')) }
        try {
            $summary = @(Invoke-DotNet $arguments)
            $summary | ForEach-Object { Write-Host $_ }
            $report.specs.assertions = ($summary[-1] | ConvertFrom-Json).groups
            $report.specs.status='passed'
        }
        catch { $failure=$true; $report.specs.status='failed'; $report.specs.error=$_.Exception.Message; Write-Warning $_ }
    }
    foreach ($name in $selected) {
        try {
            $report.fixtures[$name]=(Get-FileHash -LiteralPath "Specs/Fixtures/$name.json" -Algorithm SHA256).Hash.ToLowerInvariant()
            Invoke-DotNet @('Tools/bin/Debug/net10.0/EndfieldLogs.Tools.dll',$suites[$name],"Specs/Fixtures/$name.json",(Join-Path $OutputDirectory "$name.json"))
            $report.suites[$name]=@{status='passed'}
        }
        catch { $failure=$true; $report.suites[$name]=@{status='failed';error=$_.Exception.Message}; Write-Warning $_ }
    }
    if ($NativeCapture) {
        $report.native.status='not_run'
        try { Invoke-DotNet @('Specs/bin/Debug/net10.0/EndfieldLogs.Specs.dll','--native-capture'); $report.native.status='passed' }
        catch { $failure=$true; $report.native=@{status='failed';error=$_.Exception.Message}; Write-Warning $_ }
    }
}
catch { $failure=$true; $report.error=$_.Exception.Message; Write-Warning $_ }
finally {
    $report.passed = -not $failure
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'verification.json') -Encoding UTF8
    Pop-Location
}
if ($failure) { throw "Verification failed; see $OutputDirectory/verification.json" }
Write-Host "Verification passed; executed: $($selected -join ', '); specs: $($report.specs.status)."
