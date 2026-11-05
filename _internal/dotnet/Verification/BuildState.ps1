# Source/artifact receipts are local evidence, never release inputs.
function Get-VerificationHash($Rows) {
    $text = ($Rows | ForEach-Object { "$($_.path)`t$($_.sha256)" }) -join "`n"
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($text)
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function Get-VerificationSource([string]$Root, [string]$Sdk) {
    $directory = Join-Path $Root '_internal/dotnet'
    $files = @(Get-ChildItem -LiteralPath $directory -Recurse -File | Where-Object {
        $_.FullName -notmatch '[\\/](bin|obj)[\\/]' -and (
            $_.Extension -in @('.cs', '.xaml', '.csproj', '.props', '.targets', '.slnx', '.ps1', '.pb', '.manifest') -or
            $_.Name -in @('global.json', 'packages.lock.json', 'NuGet.Config') -or $_.FullName -match '[\\/]Schema[\\/]manifest.json$' -or
            $_.FullName -match '[\\/]Runtime[\\/](Overlays[\\/]Skins|Resources)[\\/][^\\/]+\.json$')
    })
    $rows = @($files | Sort-Object FullName | ForEach-Object {
        [ordered]@{path=$_.FullName.Substring($Root.Length+1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    $restore = @($rows | Where-Object { $_.path -match '(\.csproj|\.props|\.targets|packages\.lock\.json|NuGet\.Config|global\.json)$' })
    return [ordered]@{sdk=$Sdk; sha256=(Get-VerificationHash $rows); restore_sha256=(Get-VerificationHash $restore); files=$rows}
}

function Get-VerificationArtifacts([string]$Directory, [string[]]$Projects) {
    $rows = @()
    foreach ($project in $Projects) {
        $path = Join-Path $Directory "$project/bin/Debug"
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing build output: $project" }
        $files = @(Get-ChildItem -LiteralPath $path -Recurse -File)
        if (-not ($files | Where-Object Extension -eq '.dll')) { throw "Missing assemblies: $project" }
        $rows += @($files | ForEach-Object {
            [ordered]@{path=$_.FullName.Substring($Directory.Length+1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
        })
    }
    $rows = @($rows | Sort-Object { $_.path })
    return [ordered]@{sha256=(Get-VerificationHash $rows); files=$rows}
}

function Assert-VerificationBuild($Receipt, $Source, [string]$Directory, [string[]]$Projects) {
    if ($null -eq $Receipt -or $Receipt.source.sdk -ne $Source.sdk -or $Receipt.source.sha256 -ne $Source.sha256) {
        throw 'SkipBuild requires a successful Verify build of the current source and SDK.'
    }
    foreach ($project in $Projects) {
        if ($project -notin $Receipt.projects) { throw "SkipBuild receipt does not cover $project." }
    }
    $actual = Get-VerificationArtifacts $Directory $Receipt.projects
    if ($actual.sha256 -ne $Receipt.artifacts.sha256) { throw 'SkipBuild build artifacts changed; rebuild before verification.' }
}
