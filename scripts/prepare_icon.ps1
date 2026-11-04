param([Parameter(Mandatory=$true)][string]$SourceImage)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$assetDirectory = Join-Path $projectRoot 'desktop\public'
New-Item -ItemType Directory -Path $assetDirectory -Force | Out-Null
Copy-Item -LiteralPath $SourceImage -Destination (Join-Path $assetDirectory 'app-avatar.jpg')
Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Image]::FromFile((Join-Path $assetDirectory 'app-avatar.jpg'))
$canvas = [System.Drawing.Bitmap]::new(1024,1024)
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
try {
    $graphics.Clear([System.Drawing.Color]::White)
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $scale = [Math]::Min(1024.0/$source.Width,1024.0/$source.Height)
    $width = [int][Math]::Round($source.Width*$scale)
    $height = [int][Math]::Round($source.Height*$scale)
    $graphics.DrawImage($source,[int]((1024-$width)/2),[int]((1024-$height)/2),$width,$height)
    $canvas.Save((Join-Path $assetDirectory 'app-icon.png'),[System.Drawing.Imaging.ImageFormat]::Png)
} finally { $graphics.Dispose(); $canvas.Dispose(); $source.Dispose() }
Write-Output '原图已保留，正方形图标源文件已生成。'
