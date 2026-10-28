$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$utf8 = New-Object System.Text.UTF8Encoding $false
$utf8Strict = New-Object System.Text.UTF8Encoding $false, $true
$latin1 = [Text.Encoding]::GetEncoding(1252)

$files = Get-ChildItem -Path $root -Recurse -File -Include *.py,*.txt,*.toml,*.md,*.bat,*.example |
    Where-Object { $_.FullName -notmatch '\\.venv\\' }

foreach ($file in $files) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    if ($bytes.Length -eq 0) { continue }

    $text = $null
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 255 -and $bytes[1] -eq 254) {
        $text = [Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    } elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {
        $text = $utf8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        try {
            $text = $utf8Strict.GetString($bytes)
        } catch {
            $text = $latin1.GetString($bytes)
        }
    }

    [System.IO.File]::WriteAllText($file.FullName, $text, $utf8)
    Write-Output ("UTF-8: " + $file.FullName)
}

Write-Output "Ferdig. Start appen med:"
Write-Output ".\.venv\Scripts\python.exe -m streamlit run app.py"
