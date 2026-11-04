param([switch]$SkipChecks)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
$env:CARGO_BUILD_JOBS = '4'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$tauriConfig = Get-Content -LiteralPath 'desktop/src-tauri/tauri.conf.json' -Raw | ConvertFrom-Json
$webviewMode = $tauriConfig.bundle.windows.webviewInstallMode
if ($webviewMode.type -eq 'fixedRuntime') {
    $runtimeDirectory = Join-Path 'desktop/src-tauri' $webviewMode.path
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeDirectory 'msedgewebview2.exe') -PathType Leaf)) {
        throw "The fixed WebView2 runtime is missing at $runtimeDirectory. See BUILDING.md."
    }
}
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Build step failed: $LASTEXITCODE" } }
& $python scripts/release_version.py
Check-Exit
if (-not $SkipChecks) {
    & $python -m pytest backend -q --junitxml=artifacts/tests/desktop-backend.xml
    Check-Exit
    Push-Location desktop
    try {
        npm.cmd run format:check
        Check-Exit
        npm.cmd test
        Check-Exit
    } finally { Pop-Location }
}
New-Item -ItemType Directory -Path desktop/src-tauri/resources/licenses -Force | Out-Null
Copy-Item -LiteralPath LICENSE -Destination desktop/src-tauri/resources/licenses/FIRST_PARTY_LICENSE.txt -Force
& $python scripts/make_runtime_knowledge.py
Check-Exit
& $python scripts/collect_notices.py
Check-Exit
& $python -m PyInstaller --noconfirm --distpath artifacts/frozen --workpath artifacts/pyinstaller packaging/sky-data-runtime.spec
Check-Exit
Copy-Item -LiteralPath artifacts/frozen/sky-data-runtime.exe -Destination desktop/src-tauri/binaries/sky-data-runtime-x86_64-pc-windows-msvc.exe -Force
$icon = (Resolve-Path -LiteralPath 'desktop/src-tauri/icons/icon.ico').Path.Replace('\','/')
$iconConfig = Join-Path $projectRoot 'artifacts/bundle/windows-icons.json'
$iconJson = @{bundle = @{windows = @{nsis = @{installerIcon = $icon; uninstallerIcon = $icon}}}} | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($iconConfig, $iconJson, [System.Text.UTF8Encoding]::new($false))
Push-Location desktop
try {
    npm.cmd run tauri -- build --bundles nsis --config $iconConfig -- --offline
    Check-Exit
} finally { Pop-Location }
$installer = Get-Item -LiteralPath "desktop/src-tauri/target/release/bundle/nsis/SKY Data Workspace_$($tauriConfig.version)_x64-setup.exe"
if (-not $installer) { throw 'NSIS installer not found' }
New-Item -ItemType Directory -Path release -Force | Out-Null
$output = Join-Path $projectRoot "release/SKY_Data_Workspace_$($tauriConfig.version)_x64_Setup.exe"
Copy-Item -LiteralPath $installer.FullName -Destination $output -Force
Get-FileHash -LiteralPath $output -Algorithm SHA256
