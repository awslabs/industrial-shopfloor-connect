<#
    Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
    SPDX-License-Identifier: Apache-2.0

    sfcup - install Shop Floor Connectivity from a single command.

        irm https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.ps1 | iex

    Installs the SFC uberjar - the core plus every protocol adapter and target in one jar - into
    %USERPROFILE%\.sfc, and puts `sfc` on your user PATH. Re-run it (or the installed `sfcup`) to
    upgrade.

    Windows counterpart of sfcup.sh. Same layout, same flags, three deliberate differences:

      * No symlinks. Creating them needs administrator rights or Developer Mode, so the commands
        are generated .cmd shims with the resolved jar path written into them instead.
      * Java is invoked directly with -cp rather than through the bundle's bin\sfc-uberjar.bat.
        Those generated launchers put the whole classpath on one `set CLASSPATH=` line, and
        cmd.exe caps a line at 8191 characters.
      * PATH is set through [Environment]::SetEnvironmentVariable, not setx, which truncates at
        1024 characters and can clobber an existing Path.

    Dependencies: java 17+, and the curl/tar that ship with Windows 10 and later.
#>

[CmdletBinding()]
param(
    # Install a specific release, e.g. v1.11.0. Defaults to the latest.
    [string] $Version = $env:SFC_VERSION,

    # Install root. Defaults to ~\.sfc.
    [string] $Dir = $env:SFC_HOME,

    # Install from build\distribution\sfc-uberjar.tar.gz in a source checkout.
    [switch] $Local,

    # Keep the previous version instead of removing it.
    [switch] $KeepOld,

    # Do not touch the user PATH.
    [switch] $NoModifyPath,

    # Reinstall even if this version is already current.
    [switch] $Force,

    # Remove the installation and the PATH entry.
    [switch] $Uninstall,

    [switch] $Help
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SfcupVersion = '1.0.0'

$RepoSlug  = 'awslabs/industrial-shopfloor-connect'
$Repo      = "https://github.com/$RepoSlug"
$Bundle    = 'sfc-uberjar.tar.gz'
$BundleDir = 'sfc-uberjar'
$MainClass = 'com.amazonaws.sfc.MainController'

# The uberjar is compiled to bytecode 17, so an older JVM dies with UnsupportedClassVersionError
# rather than anything helpful.
$MinJava = 17

# ------------------------------------------------------------------------------------- reporting

# Output is deliberately ASCII-only. Windows PowerShell 5.1 reads a UTF-8 file without a BOM as ANSI,
# which would turn box-drawing and tick glyphs into mojibake on the most common Windows shell.
function Write-Step { param([string] $Message) Write-Host "  - " -ForegroundColor DarkGray -NoNewline; Write-Host $Message }
function Write-Ok   { param([string] $Message) Write-Host "OK   " -ForegroundColor Green   -NoNewline; Write-Host $Message }
function Write-Warn { param([string] $Message) Write-Host "WARN " -ForegroundColor Yellow  -NoNewline; Write-Host $Message }
function Fail       { param([string] $Message) Write-Host "ERROR " -ForegroundColor Red    -NoNewline; Write-Host $Message; exit 1 }

function Show-Usage {
    @"
sfcup $SfcupVersion - install Shop Floor Connectivity

Usage: .\sfcup.ps1 [options]

  -Version <tag>     install a specific release, e.g. v1.11.0    (env: SFC_VERSION)
  -Dir <path>        install root, default ~\.sfc                (env: SFC_HOME)
  -Local             install from build\distribution\$Bundle in a source checkout
  -KeepOld           keep the previous version instead of removing it
  -NoModifyPath      do not touch the user PATH
  -Force             reinstall even if this version is already current
  -Uninstall         remove the installation and the PATH entry
  -Help              show this message

After installing, both `sfc` and `sfc-uberjar` are on PATH and take the usual SFC options:

  sfc -config example.json -info
"@
}

if ($Help) { Show-Usage; exit 0 }

# ---------------------------------------------------------------------------------------- paths

if ([string]::IsNullOrWhiteSpace($Dir)) { $Dir = Join-Path $HOME '.sfc' }
$SfcHome     = $Dir
$BinDir      = Join-Path $SfcHome 'bin'
$VersionsDir = Join-Path $SfcHome 'versions'
# Records the active version, so the shims can be regenerated and the installer can short-circuit.
# Stands in for the Unix `current` symlink, which would need elevation on Windows.
$CurrentFile = Join-Path $SfcHome 'current.txt'

function Get-CurrentVersion {
    if (Test-Path -LiteralPath $CurrentFile) { return (Get-Content -LiteralPath $CurrentFile -Raw).Trim() }
    return $null
}

# ------------------------------------------------------------------------------------ uninstall

function Remove-FromUserPath {
    param([string] $Entry)
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrEmpty($current)) { return $false }
    $parts = $current -split ';' | Where-Object { $_ -ne '' -and $_.TrimEnd('\') -ne $Entry.TrimEnd('\') }
    $updated = ($parts -join ';')
    if ($updated -ne $current) {
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        return $true
    }
    return $false
}

if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $SfcHome)) { Fail "nothing installed at $SfcHome" }
    if (Remove-FromUserPath -Entry $BinDir) {
        Write-Step "removed $BinDir from your user PATH"
    } else {
        Write-Step "no user PATH entry found"
    }
    Remove-Item -LiteralPath $SfcHome -Recurse -Force
    Write-Ok "removed $SfcHome"
    Write-Host ""
    Write-Host "Open a new terminal for the PATH change to take effect."
    exit 0
}

# -------------------------------------------------------------------------------- prerequisites

function Get-JavaMajor {
    # `java -version` writes to stderr, hence the redirect. Handles both "21.0.11" and "1.8.0_402".
    try { $out = (& java -version 2>&1 | Select-Object -First 1) } catch { return $null }
    if ($out -notmatch '"([^"]+)"') { return $null }
    $parts = $Matches[1].Split('.')
    $major = $parts[0]
    if ($major -eq '1' -and $parts.Count -gt 1) { $major = $parts[1] }
    $parsed = 0
    if ([int]::TryParse($major, [ref] $parsed)) { return $parsed }
    return $null
}

function Test-Java {
    if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
        # Not fatal: a JVM may be installed after provisioning.
        Write-Warn "java not found on PATH. SFC needs a Java $MinJava+ runtime to run.`n  e.g. 'winget install EclipseAdoptium.Temurin.17.JDK'"
        return
    }
    $major = Get-JavaMajor
    if ($null -eq $major) { Write-Warn "could not determine the Java version; continuing"; return }
    if ($major -lt $MinJava) {
        Fail "Java $major found, but SFC needs $MinJava or newer.`n  The uberjar is compiled to bytecode $MinJava; an older JVM fails with UnsupportedClassVersionError."
    }
    Write-Step "java $major"
}

# --------------------------------------------------------------------------- resolve the version

function Resolve-LatestVersion {
    # GitHub redirects /releases/latest/download/<asset> to the concrete tag, so the tag can be read
    # out of the Location header. No JSON parsing, and it avoids the API's rate limit.
    $url = "$Repo/releases/latest/download/$Bundle"
    try {
        $resp = Invoke-WebRequest -Uri $url -Method Head -MaximumRedirection 0 -ErrorAction SilentlyContinue
    } catch {
        # Older PowerShell raises on a 3xx when redirection is capped; the response still carries the header.
        $resp = $_.Exception.Response
    }
    $location = $null
    if ($resp -and $resp.Headers) {
        if ($resp.Headers -is [System.Collections.IDictionary] -and $resp.Headers.ContainsKey('Location')) {
            $location = [string] $resp.Headers['Location']
        } elseif ($resp.Headers.Location) {
            $location = [string] $resp.Headers.Location
        }
    }
    if (-not $location) { return $null }
    # .../releases/download/v1.11.0/sfc-uberjar.tar.gz  ->  v1.11.0
    if ($location -match '/releases/download/([^/]+)/') { return $Matches[1] }
    return $null
}

# -------------------------------------------------------------------------------------- install

Write-Host ""
Write-Host "sfcup " -NoNewline -ForegroundColor White
Write-Host "$SfcupVersion — installing Shop Floor Connectivity"
Write-Host ""

Test-Java

$srcTarball = $null
if ($Local) {
    # Developer path: install what this checkout just built.
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $srcTarball = Join-Path $here "build\distribution\$Bundle"
    if (-not (Test-Path -LiteralPath $srcTarball)) {
        Fail "no local bundle at $srcTarball`n  Build it first:  .\gradlew build"
    }
    $Version = 'local'
    Write-Step "installing from the local build"
} else {
    if ([string]::IsNullOrWhiteSpace($Version)) {
        Write-Step "resolving the latest release"
        $Version = Resolve-LatestVersion
        if (-not $Version) {
            Fail "could not determine the latest release tag.`n  Check network access, or pass -Version vX.Y.Z."
        }
    }
    Write-Step "version $Version"
}

$target = Join-Path $VersionsDir $Version

if (-not $Force -and $Version -ne 'local' -and (Test-Path -LiteralPath $target) -and (Get-CurrentVersion) -eq $Version) {
    Write-Ok "already at $Version in $SfcHome — nothing to do"
    Write-Host "  Reinstall anyway with -Force."
    exit 0
}

New-Item -ItemType Directory -Force -Path $VersionsDir, $BinDir | Out-Null

# Everything lands in a scratch directory first, so an interrupted run never leaves a half install.
$tmp = Join-Path $SfcHome ".tmp.$PID"
if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    $tarball = Join-Path $tmp $Bundle

    if ($Local) {
        Copy-Item -LiteralPath $srcTarball -Destination $tarball
    } else {
        $base = if ($PSBoundParameters.ContainsKey('Version') -or $env:SFC_VERSION) {
            "$Repo/releases/download/$Version"
        } else {
            "$Repo/releases/latest/download"
        }

        Write-Host ""
        Write-Step "downloading $Bundle (a few hundred MB — it carries every adapter and target)"
        try {
            # Progress rendering makes a large download dramatically slower in Windows PowerShell.
            $prevProgress = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri "$base/$Bundle" -OutFile $tarball
        } catch {
            Fail "could not download $Bundle for $Version.`n  Check that the release exists: $Repo/releases"
        } finally {
            $ProgressPreference = $prevProgress
        }

        # Verify against the checksum the release workflow publishes beside each tarball. A missing
        # checksum is a warning; a mismatching one is fatal.
        $sumFile = "$tarball.sha512sum"
        $haveSum = $false
        try {
            Invoke-WebRequest -Uri "$base/$Bundle.sha512sum" -OutFile $sumFile
            $haveSum = (Test-Path -LiteralPath $sumFile) -and ((Get-Item -LiteralPath $sumFile).Length -gt 0)
        } catch { $haveSum = $false }

        if ($haveSum) {
            $expected = ((Get-Content -LiteralPath $sumFile -Raw).Trim() -split '\s+')[0]
            $actual   = (Get-FileHash -LiteralPath $tarball -Algorithm SHA512).Hash
            if ($actual -ine $expected) {
                Fail "checksum mismatch for $Bundle — refusing to install.`n  expected $expected`n  actual   $actual"
            }
            Write-Step "sha512 verified"
        } else {
            Write-Warn "no published checksum for $Version — skipping verification"
        }
    }

    Write-Step "unpacking"
    if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
        Fail "need tar to unpack the bundle. It ships with Windows 10 and later."
    }
    & tar -xf $tarball -C $tmp
    if ($LASTEXITCODE -ne 0) { Fail "tar failed to unpack $Bundle" }

    $extracted = Join-Path $tmp $BundleDir
    if (-not (Test-Path -LiteralPath $extracted)) {
        Fail "unexpected bundle layout: no $BundleDir inside $Bundle"
    }

    # Note which versions existed before, so the old one is pruned only after a successful swap.
    $oldVersions = @()
    if (Test-Path -LiteralPath $VersionsDir) {
        $oldVersions = @(Get-ChildItem -LiteralPath $VersionsDir -Directory -ErrorAction SilentlyContinue |
                         Where-Object { $_.Name -ne $Version })
    }

    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    Move-Item -LiteralPath $extracted -Destination $target

    # Locate the jar; its name carries the version, so resolve rather than assume.
    $jar = Get-ChildItem -LiteralPath (Join-Path $target 'lib') -Filter 'sfc-uberjar-*.jar' |
           Select-Object -First 1
    if (-not $jar) { Fail "no sfc-uberjar-<version>.jar found in $target\lib" }

    # Generated shims instead of symlinks: no elevation needed, and `java -cp` keeps the classpath
    # out of cmd.exe's 8191-character line limit. Both names are provided, so new documentation can
    # use `sfc` while every existing reference to `sfc-uberjar` keeps working.
    $shim = @"
@echo off
rem Generated by sfcup $SfcupVersion. Regenerated on every install - do not edit.
java -cp "$($jar.FullName)" $MainClass %*
"@
    foreach ($name in @('sfc.cmd', 'sfc-uberjar.cmd')) {
        Set-Content -LiteralPath (Join-Path $BinDir $name) -Value $shim -Encoding ASCII
    }

    Set-Content -LiteralPath $CurrentFile -Value $Version -Encoding ASCII -NoNewline

    # Keep a copy so `sfcup` can upgrade the install later.
    if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath)) {
        Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $BinDir 'sfcup.ps1') -Force
        Set-Content -LiteralPath (Join-Path $BinDir 'sfcup.cmd') -Encoding ASCII -Value @"
@echo off
rem Generated by sfcup $SfcupVersion.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sfcup.ps1" %*
"@
    }

    # ------------------------------------------------------------------------------------- PATH

    $pathWired = $false
    if (-not $NoModifyPath) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ([string]::IsNullOrEmpty($userPath)) { $userPath = '' }
        $already = ($userPath -split ';' | Where-Object { $_.TrimEnd('\') -eq $BinDir.TrimEnd('\') }).Count -gt 0
        if ($already) {
            Write-Step "already on your user PATH"
        } else {
            # SetEnvironmentVariable rather than setx: setx truncates at 1024 characters.
            $newPath = if ($userPath -eq '') { $BinDir } else { "$BinDir;$userPath" }
            [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
            Write-Step "added to your user PATH"
        }
        # Make it usable in this session too, without waiting for a new terminal.
        if (-not ($env:Path -split ';' | Where-Object { $_.TrimEnd('\') -eq $BinDir.TrimEnd('\') })) {
            $env:Path = "$BinDir;$env:Path"
        }
        $pathWired = $true
    }

    # Prune the previous version now that the new one is live.
    if (-not $KeepOld -and $oldVersions.Count -gt 0) {
        foreach ($old in $oldVersions) {
            Remove-Item -LiteralPath $old.FullName -Recurse -Force -ErrorAction SilentlyContinue
            Write-Step "removed the previous version $($old.Name)"
        }
    }

    # ------------------------------------------------------------------------------------- done

    Write-Host ""
    Write-Ok "SFC $Version installed in $SfcHome"
    Write-Host ""
    Write-Host "  commands  " -ForegroundColor DarkGray -NoNewline
    Write-Host "sfc, sfc-uberjar          " -NoNewline
    Write-Host "(same jar, either name)" -ForegroundColor DarkGray
    Write-Host "  jar       " -ForegroundColor DarkGray -NoNewline
    Write-Host $jar.FullName
    Write-Host "  update    " -ForegroundColor DarkGray -NoNewline
    Write-Host "sfcup"
    Write-Host ""
    if ($pathWired) {
        Write-Host "Ready to use in this terminal. Open a new one for other shells to see it."
    } else {
        Write-Host "To put it on PATH, add this directory yourself:"
        Write-Host ""
        Write-Host "  $BinDir" -ForegroundColor White
    }
    Write-Host ""
    Write-Host "Then try it — this needs no hardware and no cloud account:"
    Write-Host ""
    Write-Host "  sfc -config <your-config>.json -info" -ForegroundColor White
    Write-Host ""
    Write-Host "  Ready-made configurations: $Repo/tree/main/examples" -ForegroundColor DarkGray
    Write-Host ""
}
finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
