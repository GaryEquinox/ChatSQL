$RuntimeFile = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) ".runtime\dev-processes.json"
if (-not (Test-Path $RuntimeFile)) {
  Write-Host "No recorded development processes."
  exit 0
}

$State = Get-Content $RuntimeFile | ConvertFrom-Json
foreach ($Name in @("backend", "frontend")) {
  $Id = $State.$Name
  $Process = if ($Id) { Get-Process -Id $Id -ErrorAction SilentlyContinue } else { $null }
  if ($Process) {
    Write-Host "$Name running: PID $Id"
  } else {
    Write-Host "$Name not running: PID $Id"
  }
}

try {
  $Health = Invoke-RestMethod -Uri $State.backend_url -TimeoutSec 2
  Write-Host "backend health: $($Health.status), version $($Health.version)"
} catch {
  Write-Host "backend health: unavailable"
}
