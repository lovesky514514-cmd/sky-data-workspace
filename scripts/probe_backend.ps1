$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeInfo = Join-Path $projectRoot 'workspace_data\runtime.json'
& (Join-Path $PSScriptRoot 'start_backend.ps1')
$info = Get-Content -LiteralPath $runtimeInfo -Raw | ConvertFrom-Json
$health = Invoke-RestMethod -Uri ($info.base_url + '/api/health') -Headers @{Authorization=('Bearer ' + $info.token)} -TimeoutSec 5
& (Join-Path $PSScriptRoot 'stop_backend.ps1')
for ($attempt=0; $attempt -lt 40; $attempt++) {
    $alive = $null -ne (Get-Process -Id $info.pid -ErrorAction SilentlyContinue)
    if (-not $alive -and -not (Test-Path -LiteralPath $runtimeInfo)) { break }
    Start-Sleep -Milliseconds 250
}
$probe = [pscustomobject]@{
    product=$health.product
    runtime=$health.runtime
    hidden_process=$true
    session_file_removed=(-not (Test-Path -LiteralPath $runtimeInfo))
    process_exited=(-not (Get-Process -Id $info.pid -ErrorAction SilentlyContinue))
}
$probe | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'artifacts\backend_process_smoke.json') -Encoding utf8
$probe | ConvertTo-Json
if (-not ($probe.process_exited -and $probe.session_file_removed)) { throw '后台退出未完成。' }
