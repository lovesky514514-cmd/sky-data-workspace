$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $projectRoot 'workspace_data'
$runtimeInfo = Join-Path $runtimeDirectory 'runtime.json'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按 README 安装项目虚拟环境。' }
if (Test-Path -LiteralPath $runtimeInfo) {
    $existing = Get-Content -LiteralPath $runtimeInfo -Raw | ConvertFrom-Json
    if ($existing.base_url -match '^http://127\.0\.0\.1:\d+$') {
        try {
            $health = Invoke-RestMethod -Uri ($existing.base_url + '/api/health') -Headers @{Authorization=('Bearer ' + $existing.token)} -TimeoutSec 3
            if ($health.product -eq 'SKY Data Workspace') {
                Write-Output ('后端已经运行：' + $existing.base_url)
                return
            }
        } catch { }
    }
}
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$launchId = [guid]::NewGuid().ToString()
$childProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','sky_data_workspace','--launch-id',$launchId,'serve') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDirectory 'stdout.log') -RedirectStandardError (Join-Path $runtimeDirectory 'stderr.log')
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($childProcess.HasExited) { throw '后端启动失败，请检查 workspace_data/stderr.log。' }
    if (Test-Path -LiteralPath $runtimeInfo) {
        $info = Get-Content -LiteralPath $runtimeInfo -Raw | ConvertFrom-Json
        # Windows venv 启动器的 PID 可能不同，用本次启动标识绑定实际运行进程。
        if ($info.launch_id -eq $launchId) {
            Write-Output ('后端已在后台启动：' + $info.base_url)
            Write-Output ('进程 ID：' + $info.pid)
            return
        }
    }
}
throw '后端尚未生成启动信息，请检查日志。'
