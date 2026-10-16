param([string]$SourceFile, [string]$OutputFile)
$ErrorActionPreference = "Stop"
$wordApp = $null
$wordDoc = $null
$saveOption = 0
$exportCompleted = $false
$documentClosed = $false
$renderMutex = New-Object System.Threading.Mutex($false, 'Local\AIWorkbenchDocxRender')
$mutexOwned = $false
try {
    try { $mutexOwned = $renderMutex.WaitOne(30000) }
    catch [System.Threading.AbandonedMutexException] { $mutexOwned = $true }
    if (-not $mutexOwned) { throw 'DOCX_RENDERER_BUSY' }
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $wordDoc = $wordApp.Documents.Open($SourceFile, $false, $true, $false)
    $wordDoc.ExportAsFixedFormat($OutputFile, 17)
    $exportCompleted = $true
    Write-Output $wordApp.Version
} finally {
    if ($null -ne $wordDoc) {
        $wordDoc.Close([ref]$saveOption)
        $documentClosed = $true
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDoc)
    }
    if ($null -ne $wordApp) {
        try { $wordApp.Quit([ref]$saveOption) }
        catch {
            # Compatible hosts may disconnect after closing the document.
            # Accept only those RPC errors after a successful export/close;
            # output bytes still undergo independent content/layout checks.
            $rpcDisconnected = $false
            $cleanupException = $_.Exception
            while ($null -ne $cleanupException) {
                if ($cleanupException.HResult -in @(-2147023174, -2147023170)) { $rpcDisconnected = $true }
                $cleanupException = $cleanupException.InnerException
            }
            if (-not ($exportCompleted -and $documentClosed -and $rpcDisconnected)) { throw }
        }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
    if ($mutexOwned) { $renderMutex.ReleaseMutex() }
    $renderMutex.Dispose()
}
