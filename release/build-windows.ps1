param([switch]$InternalUnsigned, [string]$Output = 'dist/windows')
$ErrorActionPreference = 'Stop'
$taskRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Push-Location -LiteralPath $taskRepo
try {
  if ((node --version).Trim() -ne 'v24.19.0' -or (npm --version).Trim() -ne '11.17.0') { throw 'Pinned Node 24.19.0 and npm 11.17.0 are required.' }
  $taskPackage = Get-Content -LiteralPath 'apps/desktop/package.json' -Raw | ConvertFrom-Json
  if ($taskPackage.devDependencies.'electron-builder' -ne '26.15.3') { throw 'electron-builder must be exactly locked at 26.15.3.' }
  $taskBuilder = Join-Path $taskRepo 'node_modules/.bin/electron-builder.cmd'
  if (-not (Test-Path -LiteralPath $taskBuilder -PathType Leaf)) { throw 'Run npm ci with the committed lock first.' }
  if (-not (Test-Path -LiteralPath 'release/staging/python/python.exe' -PathType Leaf)) { throw 'No reviewed staged Python runtime. Do not package the development venv.' }
  if (-not (Test-Path -LiteralPath 'release/staging/tool-inventory.json' -PathType Leaf)) { throw 'Staged format-tool hashes and licenses are required.' }
  $taskTools = Get-Content -LiteralPath 'release/staging/tool-inventory.json' -Raw | ConvertFrom-Json
  $taskAllowedInventory = @('verified')
  if ($InternalUnsigned) { $taskAllowedInventory += 'internal_hash_inventory' }
  if ($taskTools.status -notin $taskAllowedInventory -or -not $taskTools.tools -or -not $taskTools.runtime_sha256) { throw 'Runtime and tool inventory is incomplete.' }
  $taskRuntimeHash = (Get-FileHash -LiteralPath 'release/staging/python/python.exe' -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($taskRuntimeHash -ne $taskTools.runtime_sha256) { throw 'Staged Python runtime changed.' }
  foreach ($taskFile in $taskTools.files) {
    $taskPath = [IO.Path]::GetFullPath((Join-Path 'release/staging' $taskFile.path))
    $taskStage = [IO.Path]::GetFullPath('release/staging') + [IO.Path]::DirectorySeparatorChar
    if (-not $taskPath.StartsWith($taskStage, [StringComparison]::OrdinalIgnoreCase)) { throw 'Staged inventory path escaped its root.' }
    if ((Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskFile.sha256) { throw 'Staged runtime file changed.' }
  }
  if (-not $InternalUnsigned) {
    $taskPins = Get-Content -LiteralPath 'release/publisher-allowlist.json' -Raw | ConvertFrom-Json
    if (-not $taskPins.thumbprints -or -not $env:CSC_LINK) { throw 'Production signing material and a reviewed publisher allowlist are required.' }
  }
  npm run typecheck:desktop
  if ($LASTEXITCODE -ne 0) { throw 'Desktop typecheck failed.' }
  npm run build:desktop
  if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
  $taskConfig = (Resolve-Path -LiteralPath 'apps/desktop/electron-builder.yml').Path
  $taskOutputPath = [IO.Path]::GetFullPath((Join-Path $taskRepo $Output))
  $taskArgs = @('--projectDir', 'apps/desktop', '--config', $taskConfig, '--win', '--x64', '--publish', 'never', "--config.directories.output=$taskOutputPath")
  if ($InternalUnsigned) { $taskArgs += '--config.forceCodeSigning=false' }
  & $taskBuilder @taskArgs
  if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
  if ($InternalUnsigned) { Write-Output 'Internal unsigned package only: installation, runtime and release qualification remain unverified.' }
} finally { Pop-Location }
