<#
    Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
    SPDX-License-Identifier: Apache-2.0

    sfcup - install Shop Floor Connectivity from a single command.

        irm https://raw.githubusercontent.com/awslabs/industrial-shopfloor-connect/main/sfcup.ps1 | iex

    Installs the SFC uberjar - the core plus every protocol adapter and target in one jar - into
    %USERPROFILE%\.sfc, and puts `sfcx` on your user PATH. Re-run it (or the installed `sfcup`)
    to upgrade.

    Windows counterpart of sfcup.sh. The command is `sfcx` on every OS (plain `sfc` would be shadowed
    by Windows' own System File Checker, C:\Windows\System32\sfc.exe). Same layout, same flags, three
    deliberate differences:

      * No symlinks. Creating them needs administrator rights or Developer Mode, so the command is
        a generated .cmd shim that points at the jar relative to its own folder.
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
# Never `exit`: under `irm ... | iex` the script runs inside the user's own PowerShell session, and
# `exit` would close their window. A terminating error stops the script and keeps the window open;
# run as a file it still ends with a non-zero exit code.
function Fail       { param([string] $Message) Write-Host "ERROR " -ForegroundColor Red    -NoNewline; Write-Host $Message; throw "sfcup stopped: see the error above" }

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

After installing, `sfcx` is on PATH and takes the usual SFC options:

  sfcx -config example.json -info
"@
}

if ($Help) { Show-Usage; return }

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
    return
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
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $url -Method Head -MaximumRedirection 0 -ErrorAction SilentlyContinue
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
Write-Host "$SfcupVersion - installing Shop Floor Connectivity"
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
    Write-Ok "already at $Version in $SfcHome - nothing to do"
    Write-Host "  Reinstall anyway with -Force."
    return
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
        Write-Step "downloading $Bundle (a few hundred MB - it carries every adapter and target)"
        try {
            # Progress rendering makes a large download dramatically slower in Windows PowerShell.
            $prevProgress = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$Bundle" -OutFile $tarball
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
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$Bundle.sha512sum" -OutFile $sumFile
            $haveSum = (Test-Path -LiteralPath $sumFile) -and ((Get-Item -LiteralPath $sumFile).Length -gt 0)
        } catch { $haveSum = $false }

        if ($haveSum) {
            $expected = ((Get-Content -LiteralPath $sumFile -Raw).Trim() -split '\s+')[0]
            $actual   = (Get-FileHash -LiteralPath $tarball -Algorithm SHA512).Hash
            if ($actual -ine $expected) {
                Fail "checksum mismatch for $Bundle - refusing to install.`n  expected $expected`n  actual   $actual"
            }
            Write-Step "sha512 verified"
        } else {
            Write-Warn "no published checksum for $Version - skipping verification"
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

    # A generated shim instead of a symlink: no elevation needed, and `java -cp` keeps the classpath
    # out of cmd.exe's 8191-character line limit. The jar is addressed relative to the shim (%~dp0),
    # so the ASCII-only file never has to spell out a profile path with non-ASCII letters. Only
    # `sfcx` is generated, the same name as on Linux and macOS.
    $shim = @"
@echo off
rem Generated by sfcup $SfcupVersion. Regenerated on every install - do not edit.
java -cp "%~dp0..\versions\$Version\lib\$($jar.Name)" $MainClass %*
"@
    Set-Content -LiteralPath (Join-Path $BinDir 'sfcx.cmd') -Value $shim -Encoding ASCII
    # Earlier installs wrote sfc.cmd and sfc-uberjar.cmd; they would keep pointing at a pruned version.
    foreach ($stale in @('sfc.cmd', 'sfc-uberjar.cmd')) {
        $staleShim = Join-Path $BinDir $stale
        if (Test-Path -LiteralPath $staleShim) { Remove-Item -LiteralPath $staleShim -Force }
    }

    Set-Content -LiteralPath $CurrentFile -Value $Version -Encoding ASCII -NoNewline

    # Keep a copy so `sfcup` can upgrade the install later. Under `irm ... | iex` there is no script
    # file ($PSCommandPath is empty), so fetch the published copy instead. The copy lives outside bin\:
    # PowerShell would run bin\sfcup.ps1 ahead of bin\sfcup.cmd, and the default Restricted execution
    # policy of Windows 10/11 blocks .ps1 files; sfcup.cmd passes -ExecutionPolicy Bypass instead.
    $selfCopy = Join-Path $SfcHome 'sfcup.ps1'
    $staleCopy = Join-Path $BinDir 'sfcup.ps1'
    if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath)) {
        # An upgrade run from the installed copy must not copy the file onto itself.
        if ((Resolve-Path -LiteralPath $PSCommandPath).Path -ne $selfCopy) {
            Copy-Item -LiteralPath $PSCommandPath -Destination $selfCopy -Force
        }
    } else {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/$RepoSlug/main/sfcup.ps1" -OutFile $selfCopy
        } catch {
            Write-Warn "could not save sfcup for later updates; re-run the install command to update"
        }
    }
    if (Test-Path -LiteralPath $selfCopy) {
        Set-Content -LiteralPath (Join-Path $BinDir 'sfcup.cmd') -Encoding ASCII -Value @"
@echo off
rem Generated by sfcup $SfcupVersion.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\sfcup.ps1" %*
"@
    }
    # Earlier installs kept the copy in bin\, where it would shadow sfcup.cmd.
    if ((Test-Path -LiteralPath $staleCopy) -and ($PSCommandPath -ne $staleCopy)) { Remove-Item -LiteralPath $staleCopy -Force }

    # ------------------------------------------------------------------------------------- PATH

    $pathWired = $false
    if (-not $NoModifyPath) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ([string]::IsNullOrEmpty($userPath)) { $userPath = '' }
        $already = @($userPath -split ';' | Where-Object { $_.TrimEnd('\') -eq $BinDir.TrimEnd('\') }).Count -gt 0
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
    Write-Host "  command   " -ForegroundColor DarkGray -NoNewline
    Write-Host "sfcx"
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
    Write-Host "Then try it - this needs no hardware and no cloud account:"
    Write-Host ""
    Write-Host "  sfcx -config <your-config>.json -info" -ForegroundColor White
    Write-Host ""
    Write-Host "  Ready-made configurations: $Repo/blob/main/docs/examples/README.md" -ForegroundColor DarkGray
    Write-Host ""
}
finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
