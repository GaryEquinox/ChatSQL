$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$SeedTarget = Join-Path $Backend "app\seed\ChatSQLData"
$SourceData = if ($env:CHATSQL_SOURCE_DATA_ROOT) { $env:CHATSQL_SOURCE_DATA_ROOT } else { Join-Path (Split-Path -Parent $Root) "ChatSQLData" }
if (-not (Test-Path (Join-Path $SourceData "meta.sqlite3"))) {
  if ($env:CHATSQL_SOURCE_DATA_ROOT) { throw "Source metadata database is missing." }
  $SourceData = $SeedTarget
}
$Venv = Join-Path $Root ".venv311"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
  py -3.11 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Backend "requirements.txt") pyinstaller

Push-Location $Frontend
npm install
npm run build
Pop-Location

& $Python (Join-Path $Root "packaging\create_seed.py") --source $SourceData --target $SeedTarget

Push-Location $Root
& $Python -m PyInstaller --clean --noconfirm (Join-Path $Root "packaging\ChatSQL.spec")
Pop-Location

Write-Host "EXE output: $(Join-Path $Root 'dist\ChatSQL\ChatSQL.exe')"
