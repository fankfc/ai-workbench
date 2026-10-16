param([string]$SourceFile, [string]$OutputFile)
$ErrorActionPreference = "Stop"
$wordApp = $null
$wordDoc = $null
$saveOption = 0
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $wordDoc = $wordApp.Documents.Open($SourceFile, $false, $true, $false)
    $wordDoc.ExportAsFixedFormat($OutputFile, 17)
    Write-Output $wordApp.Version
} finally {
    if ($null -ne $wordDoc) { $wordDoc.Close([ref]$saveOption); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDoc) }
    if ($null -ne $wordApp) {
        try { $wordApp.Quit([ref]$saveOption) }
        catch {
            # Some compatible Word COM hosts exit after the last private
            # document closes. RPC disconnect then confirms that exit.
            if ($_.Exception.InnerException.HResult -ne -2147023174) { throw }
        }
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
