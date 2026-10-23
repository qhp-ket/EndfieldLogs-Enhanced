[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Isolated,
    [switch]$Offline,
    [ValidateSet('Auto', 'Download')][string]$PythonSource = 'Auto',
    [string]$PythonPath,
    [string]$EnvironmentPath = '.venv',
    [string]$Wheelhouse,
    [string]$PythonArchive,
    [string]$ResourceArchive
)

$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Probe = Join-Path $PSScriptRoot 'dev_environment.py'
$PythonVersion = '3.14.2'
$PythonSha256 = 'c8d5e2b95f0250ceb84aafc2ded952c1c3ae65870651042aff7c2f19de856b75'

function Probe-Python([string]$Executable, [bool]$Clean) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return $null }
    $ArgsList = @('-B')
    if ($Clean) { $ArgsList += '-I' }
    $ArgsList += @($Probe, '--root', $Root)
    if ($Clean) { $ArgsList += '--isolated' }
    try {
        $Output = & $Executable @ArgsList 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return ($Output | Select-Object -Last 1 | ConvertFrom-Json)
    } catch { return $null }
}

function Show-Probe($Result) {
    Write-Host ('Python: ' + $Result.executable)
    Write-Host ('Dependencies ready: ' + $Result.ready)
    if ($Result.missing.Count) { Write-Host ('Missing: ' + ($Result.missing -join ', ')) }
    if ($Result.import_errors.PSObject.Properties.Count) { Write-Host ('Import errors: ' + ($Result.import_errors | ConvertTo-Json -Compress)) }
    Write-Host ('External capture key present: ' + $Result.capture_key_present)
    Write-Host ('System Npcap present: ' + $Result.npcap_present)
}

function Save-Environment([string]$Executable) {
    $ResourceArgs = @('-B', (Join-Path $PSScriptRoot 'prepare_resources.py'))
    if ($ResourceArchive) { $ResourceArgs += @('--archive', [IO.Path]::GetFullPath($ResourceArchive)) }
    if ($Offline) { $ResourceArgs += '--offline' }
    & $Executable @ResourceArgs
    if ($LASTEXITCODE -ne 0) { throw 'Runtime resource preparation failed; no environment selection was saved.' }
    [IO.Directory]::CreateDirectory((Join-Path $Root '.dev-gui')) | Out-Null
    $SelectedPython = $Executable
    if ($Executable.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        $SelectedPython = $Executable.Substring($Root.Length + 1)
    }
    [IO.File]::WriteAllText((Join-Path $Root '.dev-gui/dev-python.txt'), $SelectedPython, (New-Object Text.UTF8Encoding($false)))
}

function Candidates {
    if ($PythonPath) { return @([IO.Path]::GetFullPath($PythonPath)) }
    $Found = @()
    if ($env:ENDFIELD_GUI_PYTHON) { $Found += $env:ENDFIELD_GUI_PYTHON }
    foreach ($Name in @('python.exe', 'python3.exe')) {
        $Command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($Command -and $Command.Source -notlike '*WindowsApps*') { $Found += $Command.Source }
    }
    $Launcher = Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Launcher) {
        # Enumerate installed interpreters; never ask a manager to auto-install globally.
        foreach ($Line in (& $Launcher.Source -0p 2>$null)) {
            if ($Line -match '(?<path>[A-Za-z]:\\.*python(?:\.exe)?)\s*$') { $Found += $Matches.path.Trim() }
        }
    }
    return @($Found | Select-Object -Unique)
}

function Local-Python {
    $Cache = Join-Path $Root '_development/cache'
    [IO.Directory]::CreateDirectory($Cache) | Out-Null
    if ($PythonArchive) { $Archive = [IO.Path]::GetFullPath($PythonArchive) }
    else { $Archive = Join-Path $Cache ('python.' + $PythonVersion + '.nupkg') }
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        if ($Offline) { throw 'Offline bootstrap needs -PythonArchive pointing to the official NuGet Python package.' }
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $Download = $Archive + '.download'
        Write-Host ('Downloading official workspace-local Python ' + $PythonVersion)
        Invoke-WebRequest -UseBasicParsing -Uri ('https://api.nuget.org/v3-flatcontainer/python/' + $PythonVersion + '/python.' + $PythonVersion + '.nupkg') -OutFile $Download
        if ((Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PythonSha256) { throw 'Python package checksum mismatch.' }
        Move-Item -LiteralPath $Download -Destination $Archive
    }
    if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PythonSha256) { throw 'Python package checksum mismatch.' }
    $Destination = Join-Path $Cache ('python-' + $PythonVersion)
    $Executable = Join-Path $Destination 'tools/python.exe'
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
        try {
            foreach ($Entry in $Zip.Entries) {
                if (-not $Entry.FullName.StartsWith('tools/')) { continue }
                $Target = [IO.Path]::GetFullPath((Join-Path $Destination $Entry.FullName))
                if (-not $Target.StartsWith($Destination + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe Python archive path.' }
                if (-not $Entry.Name) { [IO.Directory]::CreateDirectory($Target) | Out-Null; continue }
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Target)) | Out-Null
                $Source = $Entry.Open()
                try {
                    $Output = [IO.File]::Create($Target)
                    try { $Source.CopyTo($Output) } finally { $Output.Dispose() }
                } finally { $Source.Dispose() }
            }
        } finally { $Zip.Dispose() }
    }
    return $Executable
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if ([IO.Path]::IsPathRooted($EnvironmentPath)) { $Environment = [IO.Path]::GetFullPath($EnvironmentPath) }
    else { $Environment = [IO.Path]::GetFullPath((Join-Path $Root $EnvironmentPath)) }
    if (-not $Environment.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'EnvironmentPath must stay inside this workspace.' }
    $ManagedPython = Join-Path $Environment 'Scripts/python.exe'
    $Current = Probe-Python $ManagedPython $true
    if ($Current -and $Current.ready) {
        if (-not $Check) { Save-Environment $ManagedPython }
        Show-Probe $Current
        if ($Check) {
            & $ManagedPython -B (Join-Path $PSScriptRoot 'prepare_resources.py') --check
            exit $LASTEXITCODE
        }
        Write-Host 'Existing isolated environment is complete; no install needed.'
        exit 0
    }
    $BasePython = $null
    if ($PythonSource -eq 'Auto') {
        foreach ($Candidate in (Candidates)) {
            $Result = Probe-Python $Candidate $false
            if (-not $Result -or -not $Result.compatible) { continue }
            if (-not $BasePython) { $BasePython = $Candidate }
            if (-not $Isolated -and -not $Current -and $Result.ready) {
                if (-not $Check) { Save-Environment $Candidate }
                Show-Probe $Result
                if ($Check) {
                    & $Candidate -B (Join-Path $PSScriptRoot 'prepare_resources.py') --check
                    exit $LASTEXITCODE
                }
                Write-Host 'Existing workspace environment is complete; no packages changed. Use -Isolated for a fresh venv.'
                exit 0
            }
        }
    }
    if ($Check) {
        if ($Current) { Show-Probe $Current }
        elseif ($BasePython) { Show-Probe (Probe-Python $BasePython $false) }
        else { Write-Host 'No compatible Python found. Run Setup-Dev.cmd to prepare workspace-local Python and dependencies.' }
        exit 2
    }
    if ($Current -and -not $Current.compatible) { throw 'Existing environment uses incompatible Python; choose another -EnvironmentPath. It has not been overwritten.' }
    if (-not $Current) {
        if (-not $BasePython) { $BasePython = Local-Python }
        Write-Host ('Creating isolated environment: ' + $Environment)
        & $BasePython -I -B -m venv $Environment
        if ($LASTEXITCODE -ne 0) { throw 'Could not create venv; existing files were not cleared.' }
    }
    & $ManagedPython -I -B -m ensurepip
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize pip in the managed environment.' }
    $BeforeInstall = Probe-Python $ManagedPython $true
    if (-not $BeforeInstall) { throw 'Could not inspect the managed environment.' }
    $PipArgs = @('-I', '-B', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                 '--timeout', '20', '--retries', '1')
    if ($Offline) {
        if (-not $Wheelhouse) { throw 'Offline installation needs -Wheelhouse when packages are missing.' }
        $PipArgs += @('--no-index', '--find-links', [IO.Path]::GetFullPath($Wheelhouse))
    } else { $PipArgs += @('--index-url', 'https://pypi.org/simple') }
    if ($BeforeInstall.missing.Count) {
        Write-Host 'Installing missing packages into the managed venv; existing versions are reused.'
        $PipArgs += @($BeforeInstall.missing)
        & $ManagedPython @PipArgs
        if ($LASTEXITCODE -ne 0) { throw 'Dependency install incomplete. Rerun the same command to resume; the environment was not deleted.' }
    }
    $Result = Probe-Python $ManagedPython $true
    if (-not $Result -or -not $Result.ready) {
        if ($Result) { Show-Probe $Result }
        throw 'Environment verification failed. No system packages were modified.'
    }
    Save-Environment $ManagedPython
    Show-Probe $Result
    Write-Host 'Ready. Start-GUI.cmd will use this environment. No system Python, PATH, driver or game files were changed.'
    exit 0
} catch {
    Write-Error -ErrorAction Continue ('Setup failed: ' + $_.Exception.Message)
    exit 1
}
