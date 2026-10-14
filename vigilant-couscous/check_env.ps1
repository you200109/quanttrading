Write-Host '=== JDK ===' -ForegroundColor Cyan
if (Get-Command java -ErrorAction SilentlyContinue) { java -version 2>&1 } else { Write-Host '未安装 JDK' }

Write-Host ''
Write-Host '=== Android SDK ===' -ForegroundColor Cyan
if ($env:ANDROID_HOME) { Write-Host "ANDROID_HOME=$env:ANDROID_HOME" } else { Write-Host '未配置 ANDROID_HOME' }
$sdkPaths = @("$env:LOCALAPPDATA\Android\Sdk", 'C:\Android\Sdk')
foreach ($p in $sdkPaths) { if (Test-Path $p) { Write-Host "找到 SDK: $p" } }

Write-Host ''
Write-Host '=== Visual Studio ===' -ForegroundColor Cyan
$vsPaths = @('C:\Program Files\Microsoft Visual Studio', 'C:\Program Files (x86)\Microsoft Visual Studio')
$found = $false
foreach ($p in $vsPaths) { if (Test-Path $p) { Write-Host "找到 VS: $p"; $found = $true; Get-ChildItem $p -Name } }
if (-not $found) { Write-Host '未找到 Visual Studio' }

Write-Host ''
Write-Host '=== 包管理器 ===' -ForegroundColor Cyan
if (Get-Command winget -ErrorAction SilentlyContinue) { Write-Host 'winget 可用' } else { Write-Host 'winget 不可用' }
if (Get-Command choco -ErrorAction SilentlyContinue) { Write-Host 'choco 可用' } else { Write-Host 'choco 不可用' }

Write-Host ''
Write-Host '=== 磁盘空间 ===' -ForegroundColor Cyan
Get-PSDrive C | Select-Object @{N='FreeGB';E={[math]::Round($_.Free/1GB,1)}}
