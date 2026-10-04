$ErrorActionPreference = 'Continue'
# cloudflared.exe is not in the repo (it is git-ignored): download it once from
# https://github.com/cloudflare/cloudflared/releases and place it next to this script.
$exe = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $exe)) {
    Write-Host "cloudflared.exe not found in $PSScriptRoot - see the comment at the top of this script." -ForegroundColor Red
    exit 1
}

# Disable "QuickEdit" mode: normally, clicking inside this console window
# freezes whatever is running until you click again or press Enter - which
# silently kills the tunnel if you then close the window. Turning it off
# means clicking around in here is safe.
try {
    Add-Type -Name Console -Namespace Win32 -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll")]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll")]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
    $STD_INPUT_HANDLE = -10
    $ENABLE_QUICK_EDIT_MODE = 0x0040
    $ENABLE_EXTENDED_FLAGS = 0x0080
    $handle = [Win32.Console]::GetStdHandle($STD_INPUT_HANDLE)
    [uint32]$mode = 0
    [Win32.Console]::GetConsoleMode($handle, [ref]$mode) | Out-Null
    $mode = ($mode -band (-bnot $ENABLE_QUICK_EDIT_MODE)) -bor $ENABLE_EXTENDED_FLAGS
    [Win32.Console]::SetConsoleMode($handle, $mode) | Out-Null
} catch {
    Write-Host "(could not auto-disable click-to-pause - just avoid clicking inside this window)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Starting a temporary public link for the dashboard..." -ForegroundColor Cyan
Write-Host "Keep this window OPEN the whole time anyone is using the link." -ForegroundColor Yellow
Write-Host ""

$shown = $false

& $exe tunnel --url http://127.0.0.1:5057 2>&1 | ForEach-Object {
    Write-Host $_
    if (-not $shown -and $_ -match 'https://[a-zA-Z0-9\-]+\.trycloudflare\.com') {
        $shown = $true
        $url = $Matches[0]
        Write-Host ""
        Write-Host "==================================================================" -ForegroundColor Green
        Write-Host " YOUR SHAREABLE LINK:" -ForegroundColor Green
        Write-Host " $url" -ForegroundColor White -BackgroundColor DarkGreen
        Write-Host "==================================================================" -ForegroundColor Green
        try {
            Set-Clipboard -Value $url
            Write-Host "(copied to your clipboard)" -ForegroundColor DarkGray
        } catch {}
        Write-Host ""
        Write-Host "Cloudflare needs a little time to make this reachable worldwide." -ForegroundColor DarkGray
        Write-Host "Waiting 20 seconds before opening it, so it isn't tested too early..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 20
        Write-Host "Opening it now. If it still says the site can't be reached, wait" -ForegroundColor DarkGray
        Write-Host "another 10-15 seconds and refresh the page - don't close this window." -ForegroundColor DarkGray
        try { Start-Process $url } catch {}
        Write-Host ""
    }
}

Write-Host ""
Write-Host "Tunnel stopped - the link above no longer works. Re-run this to get a new one." -ForegroundColor Yellow
