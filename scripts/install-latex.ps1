<#
.SYNOPSIS
    Install the LaTeX toolchain required by GETKAN-CV on Windows.

.DESCRIPTION
    Installs a TeX distribution (MiKTeX by default, or TeX Live) plus the
    LaTeX packages used by getkan-cv.cls, and verifies the result.

.PARAMETER Distribution
    MiKTeX (default) or TeXLive.

.PARAMETER VerifyOnly
    Only check that the required tools and packages are present.

.PARAMETER DryRun
    Print the commands that would run without executing them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install-latex.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install-latex.ps1 -VerifyOnly
#>

[CmdletBinding()]
param(
    [ValidateSet('MiKTeX', 'TeXLive')]
    [string]$Distribution = 'MiKTeX',
    [switch]$VerifyOnly,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Write-Log { param([string]$Message) Write-Host "[install-latex] $Message" }
function Write-Err { param([string]$Message) Write-Host "[install-latex] ERROR: $Message" -ForegroundColor Red }

function Invoke-Step {
    param([string]$File, [string[]]$Arguments)
    Write-Log "run: $File $($Arguments -join ' ')"
    if ($DryRun) { return }
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "command failed with exit code ${LASTEXITCODE}: $File $($Arguments -join ' ')"
    }
}

$RequiredCommands = @('xelatex', 'latexmk', 'kpsewhich')

$RequiredStyles = @(
    'fontspec', 'unicode-math', 'fontawesome5', 'sourcesanspro', 'tcolorbox',
    'enumitem', 'ragged2e', 'geometry', 'fancyhdr', 'xcolor', 'xifthen',
    'etoolbox', 'setspace', 'parskip', 'hyperref', 'array'
)

# MiKTeX package names differ slightly from .sty names.
$MiKTeXPackages = @(
    'fontspec', 'unicode-math', 'fontawesome5', 'sourcesanspro', 'tcolorbox',
    'enumitem', 'ragged2e', 'geometry', 'fancyhdr', 'xcolor', 'xifthen',
    'etoolbox', 'setspace', 'parskip', 'hyperref', 'iftex', 'latexmk',
    'pgf', 'l3packages', 'l3kernel', 'ms', 'tools'
)

function Install-TexDistribution {
    $existing = Get-Command xelatex -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "existing xelatex found at $($existing.Source), skipping distribution install"
        return
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    $choco = Get-Command choco -ErrorAction SilentlyContinue

    if ($winget) {
        $id = if ($Distribution -eq 'MiKTeX') { 'MiKTeX.MiKTeX' } else { 'TeXLive.TeXLive' }
        Invoke-Step -File 'winget' -Arguments @(
            'install', '--id', $id, '-e', '--accept-package-agreements', '--accept-source-agreements'
        )
    }
    elseif ($choco) {
        $pkg = if ($Distribution -eq 'MiKTeX') { 'miktex' } else { 'texlive' }
        Invoke-Step -File 'choco' -Arguments @('install', $pkg, '-y')
    }
    else {
        Write-Err 'Neither winget nor Chocolatey is available.'
        Write-Err 'Install MiKTeX from https://miktex.org/download or TeX Live from https://tug.org/texlive/windows.html, then re-run with -VerifyOnly.'
        throw 'no supported package manager found'
    }

    Write-Log 'Distribution installed. Open a new terminal so PATH changes take effect.'
}

function Install-Packages {
    $mpm = Get-Command mpm -ErrorAction SilentlyContinue
    $tlmgr = Get-Command tlmgr -ErrorAction SilentlyContinue

    if ($mpm) {
        Invoke-Step -File 'mpm' -Arguments (@('--admin', '--update-db'))
        foreach ($pkg in $MiKTeXPackages) {
            Invoke-Step -File 'mpm' -Arguments @('--admin', '--install', $pkg)
        }
    }
    elseif ($tlmgr) {
        Invoke-Step -File 'tlmgr' -Arguments @('update', '--self')
        Invoke-Step -File 'tlmgr' -Arguments (@('install') + @(
            'latexmk', 'collection-xetex', 'collection-fontsrecommended',
            'fontspec', 'unicode-math', 'fontawesome5', 'sourcesanspro',
            'tcolorbox', 'enumitem', 'ragged2e', 'geometry', 'fancyhdr',
            'xcolor', 'xifthen', 'etoolbox', 'setspace', 'parskip',
            'hyperref', 'iftex'
        ))
    }
    else {
        Write-Log 'Neither mpm nor tlmgr found in this session.'
        Write-Log 'Open a new terminal and re-run this script to install LaTeX packages.'
    }
}

function Test-Installation {
    $failures = 0

    foreach ($cmd in $RequiredCommands) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            Write-Log "OK: $cmd -> $($found.Source)"
        }
        else {
            Write-Err "missing command: $cmd"
            $failures++
        }
    }

    $pdfinfo = Get-Command pdfinfo -ErrorAction SilentlyContinue
    if ($pdfinfo) {
        Write-Log "OK: pdfinfo -> $($pdfinfo.Source)"
    }
    else {
        Write-Log 'WARN: pdfinfo not found (optional, used for page count metadata)'
    }

    if (Get-Command kpsewhich -ErrorAction SilentlyContinue) {
        foreach ($sty in $RequiredStyles) {
            & kpsewhich "$sty.sty" > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Log "OK: $sty.sty"
            }
            else {
                Write-Err "missing LaTeX package: $sty"
                $failures++
            }
        }
    }

    if ($failures -ne 0) {
        Write-Err "verification failed with $failures problem(s)"
        return $false
    }

    Write-Log 'verification passed'
    return $true
}

if ($VerifyOnly) {
    if (Test-Installation) { exit 0 } else { exit 1 }
}

Install-TexDistribution
Install-Packages

if ($DryRun) {
    Write-Log 'dry run complete'
    exit 0
}

if (Test-Installation) { exit 0 } else { exit 1 }
