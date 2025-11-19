# build_wrapper.ps1
param(
[string]$Version = "0.0.0"
)


Write-Host "Building ding.exe with PyInstaller"
pyinstaller ding.spec


$exeName = "dist\ding.exe"
$targetExe = "artifacts\ding-$Version.exe"


if (!(Test-Path artifacts)) { New-Item -ItemType Directory -Path artifacts | Out-Null }
Copy-Item $exeName $targetExe -Force


Write-Host "Creating MSI with MSICreator"
# Create project
pcreate -n "Ding" -v $Version -a "agustinaponte" -m $targetExe -o msibld
# Build
pbuild msibld


# Move MSI to artifacts
Get-ChildItem msibld\dist -Filter *.msi | ForEach-Object { Copy-Item $_.FullName -Destination ("artifacts\" + $_.Name) -Force }


Write-Host "Artifacts prepared in ./artifacts"