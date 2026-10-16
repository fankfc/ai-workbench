param([string]$Installer = 'dist/windows/AIBroker-Setup.exe', [string]$Allowlist = 'release/publisher-allowlist.json', [string]$Commit = '')
$ErrorActionPreference = 'Stop'
$taskResult = [ordered]@{source_kind='external'; check='authenticode'; status='blocked'; recorded_at=[DateTime]::UtcNow.ToString('o'); observer='Windows Authenticode and X509Chain'; commit=$Commit; candidate_sha256=$null; authenticode_status='Unknown'; publisher_thumbprint=$null; chain_valid=$false; timestamp_valid=$false; is_test_certificate=$true; blocked_reasons=@()}
try {
  if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw 'candidate_missing' }
  $taskResult.candidate_sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  $taskSignature = Get-AuthenticodeSignature -LiteralPath $Installer
  $taskResult.authenticode_status = $taskSignature.Status.ToString()
  if ($taskSignature.Status -ne 'Valid' -or -not $taskSignature.SignerCertificate) { throw 'signature_not_valid' }
  $taskPins = Get-Content -LiteralPath $Allowlist -Raw | ConvertFrom-Json
  if (-not $taskPins.thumbprints) { throw 'trusted_publisher_missing' }
  $taskResult.publisher_thumbprint = $taskSignature.SignerCertificate.Thumbprint
  if ($taskPins.thumbprints -notcontains $taskResult.publisher_thumbprint) { throw 'publisher_not_allowed' }
  $taskChain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
  $taskChain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::Online
  $taskChain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(10)
  $taskResult.chain_valid = $taskChain.Build($taskSignature.SignerCertificate)
  if (-not $taskResult.chain_valid) { throw 'signer_chain_not_valid' }
  if (-not $taskSignature.TimeStamperCertificate) { throw 'trusted_timestamp_missing' }
  $taskTimestampChain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
  $taskTimestampChain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::Online
  $taskTimestampChain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(10)
  $taskResult.timestamp_valid = $taskTimestampChain.Build($taskSignature.TimeStamperCertificate)
  if (-not $taskResult.timestamp_valid) { throw 'timestamp_chain_not_valid' }
  $taskResult.is_test_certificate = $false
  $taskResult.status = 'passed'
} catch {
  $taskResult.blocked_reasons = @($_.Exception.Message)
}
$taskResult | ConvertTo-Json -Depth 5 -Compress
if ($taskResult.status -ne 'passed') { exit 2 }
