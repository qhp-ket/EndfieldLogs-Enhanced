param([switch]$Check)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$candidates = @(
    (Join-Path $repoRoot '.toolchains/dotnet/dotnet.exe'),
    (Join-Path (Split-Path $repoRoot -Parent) '.toolchains/dotnet/dotnet.exe'),
    $(if ($env:DOTNET_ROOT) { Join-Path $env:DOTNET_ROOT 'dotnet.exe' }),
    $((Get-Command dotnet -ErrorAction SilentlyContinue).Source)
)
$dotnet = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $dotnet) { throw 'Install the .NET SDK specified in _internal/dotnet/global.json.' }
$env:DOTNET_ROOT = Split-Path $dotnet -Parent
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_CLI_HOME = Join-Path $repoRoot '.dotnet-home'
$env:NUGET_PACKAGES = Join-Path $repoRoot '.nuget/packages'
Push-Location $PSScriptRoot
try {
    $sdk = & $dotnet --version
    if ($LASTEXITCODE) { throw 'Cannot use the SDK required by global.json.' }
    if ($Check) {
        Write-Host "SDK: $sdk"
        Write-Host "Project: $(Join-Path $PSScriptRoot 'Desktop/EndfieldLogs.Desktop.csproj')"
        return
    }
    & $dotnet build Desktop/EndfieldLogs.Desktop.csproj -c Release -r win-x64 --self-contained true `
        -p:RestoreLockedMode=true -p:DebugType=None -p:DebugSymbols=false -p:UseSharedCompilation=false -nodeReuse:false -m:1 --nologo
    if ($LASTEXITCODE) { throw 'Build failed. See the output above.' }
    $executable = Join-Path $PSScriptRoot 'Desktop/bin/Release/net10.0-windows10.0.19041.0/win-x64/EndfieldLogs-Enhanced.exe'
    Start-Process -FilePath $executable -WorkingDirectory $repoRoot -WindowStyle Normal
}
finally { Pop-Location }
