$ErrorActionPreference = "Stop"

$ProjectDir = "C:\Users\Administrator\Desktop\news20\fixed_clean\global-news-ranker_fixed"
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir "scheduled_run.log"

# Force UTF-8 output for Python and PowerShell logs.
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONIOENCODING = "utf-8"

if (!(Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

Set-Location $ProjectDir

function Write-Log {
    param([string]$Message)

    $Message | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Run-Step {
    param(
        [string]$Name,
        [string]$Command
    )

    Write-Log ""
    Write-Log "----- $Name -----"

    Invoke-Expression $Command 2>&1 | ForEach-Object {
        Write-Log ($_ | Out-String).TrimEnd()
    }

    $Code = $LASTEXITCODE

    if ($null -eq $Code) {
        $Code = 0
    }

    Write-Log "$Name ExitCode: $Code"

    if ($Code -ne 0) {
        throw "$Name failed with ExitCode: $Code"
    }
}

$Now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Log ""
Write-Log "=============================="
Write-Log "Scheduled run started: $Now"
Write-Log "ProjectDir: $ProjectDir"

try {
    Run-Step -Name "Global News Ranker" -Command "python main.py"

    Run-Step -Name "Chinese brief" -Command "python generate_chinese_brief.py"

    Run-Step -Name "Email report" -Command "python send_email_report.py"

    $End = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    Write-Log ""
    Write-Log "Scheduled run finished: $End"
    Write-Log "ExitCode: 0"

    exit 0
}
catch {
    $End = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    Write-Log ""
    Write-Log "Scheduled run failed: $End"
    Write-Log $_.Exception.Message
    Write-Log "ExitCode: 1"

    exit 1
}
