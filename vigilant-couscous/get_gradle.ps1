$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$tmp = 'C:\devtools\gradle-dl'
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$zip = Join-Path $tmp 'gradle.zip'
Remove-Item $zip -Force -ErrorAction SilentlyContinue

$url = 'https://repo.huaweicloud.com/gradle/gradle-9.3.1-all.zip'
$expected = 224

Write-Host 'Downloading...'
& curl.exe -L --retry 5 --retry-delay 2 -o $zip $url

if (-not (Test-Path $zip)) {
    Write-Host 'DOWNLOAD FAILED'
    exit 1
}

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Size: $mb MB"
if ($mb -lt ($expected - 5)) {
    Write-Host 'SIZE TOO SMALL'
    exit 1
}

$py = 'C:\Users\Administrator\self-evolution-trading\.venv\Scripts\python.exe'
& $py -c "import zipfile; z=zipfile.ZipFile(r'$zip'); n=len(z.namelist()); z.close(); print('ZIP_OK names='+str(n))"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ZIP CORRUPT'
    exit 1
}

$dir = 'C:\Users\Administrator\.gradle\wrapper\dists\gradle-9.3.1-all\9ircgukjuz9qdr1s86j3hja0o'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
Get-ChildItem $dir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host 'Extracting...'
Expand-Archive -Path $zip -DestinationPath $dir -Force
New-Item -ItemType File -Path (Join-Path $dir 'gradle-9.3.1-all.zip.ok') -Force | Out-Null
Copy-Item $zip (Join-Path $dir 'gradle-9.3.1-all.zip') -Force

Write-Host 'DONE'
Get-ChildItem $dir -Name
