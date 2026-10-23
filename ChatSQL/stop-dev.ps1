$ErrorActionPreference = "SilentlyContinue"

function Stop-ProcessTree([int]$ProcessId) {
  Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" | ForEach-Object {
    Stop-ProcessTree $_.ProcessId
  }
  Stop-Process -Id $ProcessId -Force
}

$RuntimeFile = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) ".runtime\dev-processes.json"
if (Test-Path $RuntimeFile) {
  $State = Get-Content $RuntimeFile | ConvertFrom-Json
  foreach ($Id in @($State.backend, $State.frontend)) {
    if ($Id) {
      Stop-ProcessTree $Id
    }
  }
  Remove-Item $RuntimeFile
}

Write-Host "Development processes stopped."
