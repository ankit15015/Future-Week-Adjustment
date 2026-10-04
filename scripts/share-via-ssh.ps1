$ErrorActionPreference = 'Continue'

try {
    Add-Type -Name Console -Namespace Win32b -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll")]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll")]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
    $handle = [Win32b.Console]::GetStdHandle(-10)
    [uint32]$mode = 0
    [Win32b.Console]::GetConsoleMode($handle, [ref]$mode) | Out-Null
    $mode = ($mode -band (-bnot 0x0040)) -bor 0x0080
    [Win32b.Console]::SetConsoleMode($handle, $mode) | Out-Null
} catch {}

Write-Host ""
Write-Host "Starting a temporary public link via SSH (localhost.run)." -ForegroundColor Cyan
Write-Host "Keep this window OPEN the whole time anyone is using the link." -ForegroundColor Yellow
Write-Host ""

$shown = $false
$sshExe = "$env:WINDIR\System32\OpenSSH\ssh.exe"

& $sshExe -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -R 80:localhost:5057 nokey@localhost.run 2>&1 | ForEach-Object {
    Write-Host $_
    if (-not $shown -and $_ -match 'https://[a-zA-Z0-9\-]+\.lhr\.life') {
        $shown = $true
        $url = $Matches[0]
        Write-Host ""
        Write-Host "==================================================================" -ForegroundColor Green
        Write-Host " YOUR SHAREABLE LINK (via localhost.run):" -ForegroundColor Green
        Write-Host " $url" -ForegroundColor White -BackgroundColor DarkGreen
        Write-Host "==================================================================" -ForegroundColor Green
        try {
            Set-Clipboard -Value $url
            Write-Host "(copied to your clipboard)" -ForegroundColor DarkGray
        } catch {}
        Write-Host ""
        try { Start-Process $url } catch {}
    }
}

Write-Host ""
Write-Host "Tunnel stopped - the link above no longer works. Re-run this to get a new one." -ForegroundColor Yellow
