$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeInfo = Join-Path $projectRoot 'workspace_data\runtime.json'
if (-not (Test-Path -LiteralPath $runtimeInfo)) { Write-Output '后端没有运行中的会话。'; return }
$info = Get-Content -LiteralPath $runtimeInfo -Raw | ConvertFrom-Json
if ($info.base_url -notmatch '^http://127\.0\.0\.1:\d+$') { throw '拒绝无效的运行时地址。' }
$null = Invoke-RestMethod -Method Post -Uri ($info.base_url + '/api/shutdown') -Headers @{Authorization=('Bearer ' + $info.token)} -ContentType 'application/json' -Body '{}' -TimeoutSec 5
Write-Output '已请求正常关闭后端；正在进行的调用按超时边界收尾。Ollama 服务保持运行。'
