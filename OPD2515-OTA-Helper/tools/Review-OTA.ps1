param(
    [Parameter(Mandatory=$true)][string]$Baseline,
    [Parameter(Mandatory=$true)][string]$Images,
    [Parameter(Mandatory=$true)][string]$TargetBuild,
    [Parameter(Mandatory=$true)][string]$CurrentPackage,
    [Parameter(Mandatory=$true)][string]$TargetPackage,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$python = (Get-Command python -ErrorAction Stop).Source
& $python (Join-Path $PSScriptRoot 'review.py') --baseline $Baseline --images $Images --target-build $TargetBuild --current-package $CurrentPackage --target-package $TargetPackage --out $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw '检查未通过，不能安装这次 OTA。查看 BLOCKED 原因。' }
