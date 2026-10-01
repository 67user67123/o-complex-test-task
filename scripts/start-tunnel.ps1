# Run explicitly after starting FastAPI. This script never installs a Windows service.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectDirectory '.env'
$toolDirectory = Join-Path $projectDirectory 'tools'
$cloudflaredPath = Join-Path $toolDirectory 'cloudflared.exe'
$originUrl = 'http://127.0.0.1:8000'

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw 'Create .env with a non-empty SERVICE_API_KEY and restart FastAPI first.'
}

# Read only the requested setting. Never print the file, its line, or the key.
$serviceAccessKey = ''
foreach ($envLine in [System.IO.File]::ReadAllLines($envPath)) {
    if ($envLine -match '^\s*(?:export\s+)?SERVICE_API_KEY\s*=\s*(.*?)\s*$') {
        $rawValue = $Matches[1]
        if ($rawValue -match '^"([^"\r\n]*)"\s*(?:#.*)?$') {
            $serviceAccessKey = $Matches[1]
        } elseif ($rawValue -match "^'([^'\r\n]*)'\s*(?:#.*)?$") {
            $serviceAccessKey = $Matches[1]
        } else {
            $serviceAccessKey = ($rawValue -replace '\s+#.*$', '').Trim()
        }
    }
}
if ([string]::IsNullOrWhiteSpace($serviceAccessKey)) {
    throw 'SERVICE_API_KEY in .env must be non-empty. Restart FastAPI after setting it.'
}

try {
    $serviceHealth = Invoke-RestMethod -Uri "$originUrl/health" -TimeoutSec 30
} catch {
    throw 'FastAPI is unavailable at http://127.0.0.1:8000/health. Start the local service first.'
}
if ($serviceHealth.status -ne 'ok') {
    throw 'The service is not ready. Check Ollama models and the knowledge index at /health.'
}

# A changed .env alone does not protect a process started earlier without a key.
$unauthorizedStatus = 0
try {
    $null = Invoke-WebRequest -Uri "$originUrl/examples" -UseBasicParsing -TimeoutSec 10
} catch {
    if ($null -ne $_.Exception.Response) {
        $unauthorizedStatus = [int]$_.Exception.Response.StatusCode
    }
}
if ($unauthorizedStatus -ne 401) {
    throw 'The running service does not require a key. Restart FastAPI with SERVICE_API_KEY before opening a tunnel.'
}
try {
    $null = Invoke-RestMethod -Uri "$originUrl/examples" -Headers @{ Authorization = "Bearer $serviceAccessKey" } -TimeoutSec 10
} catch {
    throw 'The .env key is not accepted by the running service. Restart FastAPI with the same .env.'
} finally {
    $serviceAccessKey = $null
    $rawValue = $null
    $envLine = $null
    $Matches = $null
}

# Quick Tunnels can conflict with a pre-existing cloudflared configuration.
# Leave those files and any already running tunnels untouched.
$profileDirectory = [Environment]::GetFolderPath('UserProfile')
foreach ($configName in @('config.yml', 'config.yaml')) {
    $existingConfig = Join-Path $profileDirectory ('.cloudflared\' + $configName)
    if (Test-Path -LiteralPath $existingConfig -PathType Leaf) {
        throw 'An existing .cloudflared config was found. Use a separate Windows profile for this Quick Tunnel; the existing config was not changed.'
    }
}

if (-not (Test-Path -LiteralPath $cloudflaredPath -PathType Leaf)) {
    New-Item -ItemType Directory -Path $toolDirectory -Force | Out-Null
    $architecture = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { '386' }
    $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-$architecture.exe"
    $downloadPath = Join-Path $toolDirectory ('cloudflared-' + [Guid]::NewGuid().ToString('N') + '.download')
    $previousProtocols = [Net.ServicePointManager]::SecurityProtocol
    try {
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocols -bor [Net.SecurityProtocolType]::Tls12
        Write-Host 'Downloading portable cloudflared from the official Cloudflare GitHub release...'
        Invoke-WebRequest -Uri $downloadUrl -OutFile $downloadPath -UseBasicParsing -TimeoutSec 120
        $downloadedBytes = [System.IO.File]::ReadAllBytes($downloadPath)
        if ($downloadedBytes.Length -lt 1MB -or $downloadedBytes[0] -ne 0x4D -or $downloadedBytes[1] -ne 0x5A) {
            throw 'The download is not a Windows executable.'
        }
        Move-Item -LiteralPath $downloadPath -Destination $cloudflaredPath
    } finally {
        [Net.ServicePointManager]::SecurityProtocol = $previousProtocols
        if (Test-Path -LiteralPath $downloadPath) {
            Remove-Item -LiteralPath $downloadPath
        }
    }
}

Write-Host 'Local service is ready and requires its access key.'
Write-Host 'Copy the https://...trycloudflare.com URL printed below into the amoCRM widget settings.'
Write-Host 'Keep this process running. Press Ctrl+C to stop this tunnel. The next start creates a new URL.'
& $cloudflaredPath tunnel --url $originUrl
if ($LASTEXITCODE -ne 0) {
    throw "cloudflared exited with code $LASTEXITCODE. Review its output above."
}
