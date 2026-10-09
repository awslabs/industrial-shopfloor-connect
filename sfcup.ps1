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

    Two AWS modes publish the same sfc-uberjar.tar.gz to an AWS account instead of installing it:
    -AwsEcr builds the sfcx container image and pushes it to Amazon ECR, -AwsGreengrass creates an
    AWS IoT Greengrass v2 component. Both need the AWS CLI v2; -AwsEcr also docker, podman or finch
    with Linux containers.

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

    # AWS mode: build the sfcx container image and push it to Amazon ECR.
    [switch] $AwsEcr,

    # AWS mode: create an AWS IoT Greengrass v2 component.
    [switch] $AwsGreengrass,

    # AWS region. Defaults to AWS_REGION, AWS_DEFAULT_REGION, then `aws configure get region`.
    [string] $Region,

    # -AwsEcr: the ECR repository (default sfcx), the image tag (default the SFC version) and an
    # optional build platform such as linux/amd64.
    [string] $Repo = 'sfcx',
    [string] $Tag,
    [string] $Platform,

    # -AwsGreengrass: the S3 bucket for the jar (default sfcx-greengrass-<account>-<region>), the
    # component name and its x.y.z version (default the release version).
    [string] $Bucket,
    [string] $Component = 'com.amazonaws.sfc.Sfcx',
    [string] $ComponentVersion,

    # Show the generated Dockerfile or recipe; build and create nothing.
    [switch] $DryRun,

    [switch] $Help
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SfcupVersion = '1.0.0'

$RepoSlug  = 'awslabs/industrial-shopfloor-connect'
$RepoUrl   = "https://github.com/$RepoSlug"
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

After installing, 'sfcx' is on PATH and takes the usual SFC options:

  sfcx -config example.json -info

AWS modes - publish the same $Bundle to your AWS account; nothing is installed locally:

  -AwsEcr                     build the sfcx container image and push it to Amazon ECR
                              (needs the AWS CLI v2 and docker, podman or finch, Linux containers)
    -Repo <name>              ECR repository, default sfcx (created if missing)
    -Tag <tag>                image tag, default the SFC version
    -Platform <platform>      build for another platform, e.g. linux/amd64
  -AwsGreengrass              create an AWS IoT Greengrass v2 component (needs the AWS CLI v2);
                              its default configuration runs the simulator to the debug target
    -Bucket <name>            S3 bucket for the jar, default sfcx-greengrass-<account>-<region>
                              (created if missing)
    -Component <name>         component name, default com.amazonaws.sfc.Sfcx
    -ComponentVersion <v>     x.y.z, default the release version
  -Region <region>            AWS region, default AWS_REGION, AWS_DEFAULT_REGION or aws configure
  -DryRun                     show the generated Dockerfile or recipe; build and create nothing

  -Version and -Local choose the bundle for the AWS modes too.
"@
}

if ($Help) { Show-Usage; return }

if ($AwsEcr -and $AwsGreengrass) { Fail "choose one of -AwsEcr and -AwsGreengrass" }
$AwsMode = if ($AwsEcr) { 'ecr' } elseif ($AwsGreengrass) { 'greengrass' } else { $null }
if ($AwsMode -and $Uninstall) { Fail "-Uninstall cannot be combined with an AWS mode" }
if ($DryRun -and -not $AwsMode) { Fail "-DryRun needs -AwsEcr or -AwsGreengrass" }
# Captured here: inside a function, $PSBoundParameters is that function's own.
$VersionGiven = $PSBoundParameters.ContainsKey('Version') -or [bool] $env:SFC_VERSION

# ---------------------------------------------------------------------------------------- paths

if ([string]::IsNullOrWhiteSpace($Dir)) { $Dir = Join-Path $HOME '.sfc' }
# Absolute from here on: [IO.File] resolves relative paths from the process directory, which neither
# follows `cd` nor expands ~, while the cmdlets resolve them from the PowerShell location.
$Dir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Dir)
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
    # 'Continue' for the call: Windows PowerShell 5.1 turns the redirected stderr into error records,
    # which 'Stop' would make fatal, and the version would never be read.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = [string] (& java -version 2>&1 | Select-Object -First 1) } catch { return $null } finally { $ErrorActionPreference = $prev }
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
    $url = "$RepoUrl/releases/latest/download/$Bundle"
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

# ------------------------------------------------------------------------------------- the bundle

# Fetch $Bundle into the scratch dir - copied with -Local, else downloaded and checked against the
# published sha512 - and unpack it there. The install and both AWS modes use this one verified bundle.
function Get-Bundle {
    param([string] $Scratch)
    $tarball = Join-Path $Scratch $Bundle

    if ($Local) {
        Copy-Item -LiteralPath $srcTarball -Destination $tarball
    } else {
        $base = if ($VersionGiven) { "$RepoUrl/releases/download/$Version" } else { "$RepoUrl/releases/latest/download" }

        Write-Host ""
        Write-Step "downloading $Bundle"
        try {
            # Progress rendering makes a large download dramatically slower in Windows PowerShell.
            $prevProgress = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$Bundle" -OutFile $tarball
        } catch {
            Fail "could not download $Bundle for $Version.`n  Check that the release exists: $RepoUrl/releases"
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
                Fail "checksum mismatch for $Bundle - refusing to use it.`n  expected $expected`n  actual   $actual"
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
    & tar -xf $tarball -C $Scratch | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "tar failed to unpack $Bundle" }
    if (-not (Test-Path -LiteralPath (Join-Path $Scratch $BundleDir))) {
        Fail "unexpected bundle layout: no $BundleDir inside $Bundle"
    }
}

# The uberjar inside the unpacked bundle; its name carries the version, so it is resolved, not assumed.
function Get-BundleJar {
    param([string] $Extracted)
    $jar = Get-ChildItem -LiteralPath (Join-Path $Extracted 'lib') -Filter 'sfc-uberjar-*.jar' | Select-Object -First 1
    if (-not $jar) { Fail "no sfc-uberjar-<version>.jar inside $Bundle" }
    return $jar.FullName
}

# ------------------------------------------------------------------------------------- AWS modes

# Every IPC service in the uberjar, as "<name> <main class>": the name is the module's directory, the
# class that module's application mainClass (adapters/*/build.gradle.kts, targets/*/build.gradle.kts).
$IpcServices = @(@'
ads com.amazonaws.sfc.ads.AdsProtocolService
j1939 com.amazonaws.sfc.j1939.J1939ProtocolService
modbus-tcp com.amazonaws.sfc.modbus.tcp.ModbusTcpProtocolService
mqtt com.amazonaws.sfc.mqtt.MqttProtocolService
nats com.amazonaws.sfc.nats.NatsProtocolService
opcua com.amazonaws.sfc.opcua.OpcuaProtocolService
pccc com.amazonaws.sfc.pccc.PcccProtocolService
rest com.amazonaws.sfc.rest.RestProtocolService
s7 com.amazonaws.sfc.s7.S7ProtocolService
simulator com.amazonaws.sfc.simulator.SimulatorService
slmp com.amazonaws.sfc.slmp.SlmpProtocolService
snmp com.amazonaws.sfc.snmp.SnmpProtocolService
sql com.amazonaws.sfc.sql.SqlProtocolService
aws-iot-core-target com.amazonaws.sfc.awsiotcore.AwsIotCoreTargetService
aws-kinesis-firehose-target com.amazonaws.sfc.awsfirehose.AwsKinesisFirehoseTargetService
aws-kinesis-target com.amazonaws.sfc.awskinesis.AwsKinesisTargetService
aws-lambda-target com.amazonaws.sfc.awslambda.AwsLambdaTargetService
aws-msk-target com.amazonaws.sfc.awsmsk.AwsMskTargetService
aws-s3-tables-target com.amazonaws.sfc.awss3tables.AwsS3TablesTargetService
aws-s3-target com.amazonaws.sfc.awss3.AwsS3TargetService
aws-sitewise-target com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService
aws-sitewiseedge-target com.amazonaws.sfc.awssitewiseedge.SiteWiseEdgeTargetService
aws-sns-target com.amazonaws.sfc.awssns.AwsSnsTargetService
aws-sqs-target com.amazonaws.sfc.awssqs.AwsSqsTargetService
debug-target com.amazonaws.sfc.debugtarget.DebugTargetService
file-target com.amazonaws.sfc.filetarget.FileTargetService
mqtt-target com.amazonaws.sfc.mqtt.MqttTargetService
nats-target com.amazonaws.sfc.natstarget.NatsTargetService
opcua-target com.amazonaws.sfc.opcuatarget.OpcuaTargetService
opcua-writer-target com.amazonaws.sfc.opcuawritetarget.OpcuaWriterTargetService
router-target com.amazonaws.sfc.router.AwsRouterTargetService
store-forward-target com.amazonaws.sfc.storeforward.AwsStoreForwardTargetService
'@ -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })

# The Greengrass component's default configuration: the simulator to the debug target, the same
# configuration as the first example in README.md (uberjar style: FactoryClassName only).
$DefaultConfig = @'
{
  "AWSVersion": "2022-04-02",
  "Name": "Simulator to console",
  "Version": 1,
  "LogLevel": "Info",
  "Schedules": [
    {
      "Name": "SimSchedule",
      "Interval": 1000,
      "Active": true,
      "TimestampLevel": "Both",
      "Sources": { "Simulator": ["*"] },
      "Targets": ["DebugTarget"]
    }
  ],
  "Sources": {
    "Simulator": {
      "Name": "Sim",
      "ProtocolAdapter": "SimulatorAdapter",
      "Channels": {
        "sinus":    { "Simulation": { "SimulationType": "Sinus",    "DataType": "Double", "Min": 0, "Max": 100  } },
        "triangle": { "Simulation": { "SimulationType": "Triangle", "DataType": "Double", "Min": 0, "Max": 100  } },
        "sawtooth": { "Simulation": { "SimulationType": "Sawtooth", "DataType": "Double", "Min": 0, "Max": 100  } },
        "square":   { "Simulation": { "SimulationType": "Square",   "DataType": "Double", "Min": 0, "Max": 100  } },
        "random":   { "Simulation": { "SimulationType": "Random",   "DataType": "Byte",   "Min": 0, "Max": 100  } },
        "counter":  { "Simulation": { "SimulationType": "Counter",  "DataType": "Int",    "Min": 0, "Max": 1000 } }
      }
    }
  },
  "Targets": {
    "DebugTarget": { "Active": true, "TargetType": "DEBUG-TARGET" }
  },
  "TargetTypes": {
    "DEBUG-TARGET": { "FactoryClassName": "com.amazonaws.sfc.debugtarget.DebugTargetWriter" }
  },
  "ProtocolAdapters": {
    "SimulatorAdapter": { "AdapterType": "SIMULATOR" }
  },
  "AdapterTypes": {
    "SIMULATOR": { "FactoryClassName": "com.amazonaws.sfc.simulator.SimulatorAdapter" }
  }
}
'@

# The component recipe. The SFC configuration travels as component configuration (SfcConfig), reaches
# the run script as the SFC_CONFIG_JSON environment variable - Greengrass replaces a recipe variable
# that points at an object with that object serialized as JSON - and is written to disk from the
# variable, every time the component starts, right before java. It never passes through a command
# line, so no shell (sh, cmd.exe, PowerShell) parses or re-quotes it. Install only checks the JVM.
$RecipeTemplate = @'
{
  "RecipeFormatVersion": "2020-01-25",
  "ComponentName": "@@COMPONENT@@",
  "ComponentVersion": "@@CVERSION@@",
  "ComponentDescription": "Shop Floor Connectivity (SFC) @@SFCVERSION@@ from sfc-uberjar.tar.gz: sfc-main with every protocol adapter and target. Default configuration: the simulator to the debug target, which writes to the component log.",
  "ComponentPublisher": "sfcup @@SFCUP@@",
  "ComponentConfiguration": { "DefaultConfiguration": { "SfcConfig": @@CONFIG@@ } },
  "Manifests": [
    {
      "Platform": { "os": "linux" },
      "Lifecycle": {
        "Install": "m=$(java -XshowSettings:properties -version 2>&1 | grep java.specification.version | head -n 1 | sed 's/.*= *//'); m=${m%%.*}; [ ${m:-0} -ge 17 ] || { echo 'SFC needs Java 17 or newer on the PATH of the Greengrass user' >&2; exit 1; }",
        "Run": {
          "Setenv": { "SFC_CONFIG_JSON": "{configuration:/SfcConfig}" },
          "Script": "printf '%s' \"$SFC_CONFIG_JSON\" > {work:path}/sfc-config.json && exec java -cp {artifacts:path}/sfc-uberjar.jar com.amazonaws.sfc.MainController -config {work:path}/sfc-config.json -nocolor"
        }
      },
      "Artifacts": [ { "URI": "@@URI@@" } ]
    },
    {
      "Platform": { "os": "windows" },
      "Lifecycle": {
        "Install": "powershell -NoProfile -NonInteractive -Command \"$s = (java -XshowSettings:properties -version 2>&1 | Out-String); $m = [regex]::Match($s, 'java\\.specification\\.version = (\\d+)'); if (-not $m.Success -or [int]$m.Groups[1].Value -lt 17) { [Console]::Error.WriteLine('SFC needs Java 17 or newer on the PATH of the Greengrass user'); exit 1 }\"",
        "Run": {
          "Setenv": { "SFC_CONFIG_JSON": "{configuration:/SfcConfig}" },
          "Script": "powershell -NoProfile -NonInteractive -Command \"[IO.File]::WriteAllText('{work:path}\\sfc-config.json', $env:SFC_CONFIG_JSON)\" && java -cp \"{artifacts:path}\\sfc-uberjar.jar\" com.amazonaws.sfc.MainController -config \"{work:path}\\sfc-config.json\" -nocolor"
        }
      },
      "Artifacts": [ { "URI": "@@URI@@" } ]
    }
  ]
}
'@

# Values end up in generated files and AWS names, so each is checked against what AWS accepts.
function Test-Value {
    param([string] $Name, [string] $Value, [string] $Pattern)
    if ($Value -cnotmatch $Pattern) { Fail "invalid ${Name}: '$Value'" }
}

# Files for the Linux image and for AWS: LF line endings and UTF-8 without a BOM, whatever line endings
# this script was checked out with.
function Write-LfFile {
    param([string] $Path, [string] $Text)
    $lf = $Text -replace "`r`n", "`n"
    if (-not $lf.EndsWith("`n")) { $lf += "`n" }
    [IO.File]::WriteAllText($Path, $lf, (New-Object System.Text.UTF8Encoding($false)))
}

# A native command with all its output discarded; returns the exit code. Windows PowerShell 5.1 turns
# redirected stderr into error records, which $ErrorActionPreference = 'Stop' would make fatal.
function Invoke-Quiet {
    param([string] $Exe, [string[]] $Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Exe @Arguments *> $null } finally { $ErrorActionPreference = $prev }
    return $LASTEXITCODE
}

function Get-AwsRegion {
    foreach ($candidate in @($Region, $env:AWS_REGION, $env:AWS_DEFAULT_REGION)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) { return $candidate }
    }
    if (Get-Command aws -ErrorAction SilentlyContinue) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { $configured = & aws configure get region 2>$null | Select-Object -First 1 } finally { $ErrorActionPreference = $prev }
        if ($configured) { return ([string] $configured).Trim() }
    }
    return $null
}

# Region and account for a real run: both are needed for every AWS name below.
function Initialize-AwsContext {
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { Fail "need the AWS CLI v2 (aws) on PATH" }
    $script:AwsRegion = Get-AwsRegion
    if (-not $script:AwsRegion) { Fail "no AWS region: pass -Region, or set AWS_REGION" }
    $account = & aws sts get-caller-identity --query Account --output text
    if ($LASTEXITCODE -ne 0 -or -not $account) { Fail "the AWS CLI has no usable credentials (aws sts get-caller-identity failed)" }
    $script:AwsAccount = ([string] $account).Trim()
    Write-Step "AWS account $($script:AwsAccount), region $($script:AwsRegion)"
}

# The image's build context: the jar from the bundle, the Dockerfile and three small scripts, plus a
# usage text. The scripts are POSIX sh, so the image needs nothing beyond the Corretto base.
function New-ImageContext {
    param([string] $Dir, [string] $Jar)
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    Move-Item -LiteralPath $Jar -Destination (Join-Path $Dir 'sfc-uberjar.jar')

    $dockerfile = @'
# Generated by sfcup @@SFCUP@@ from sfc-uberjar.tar.gz (SFC @@VERSION@@).
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21
LABEL org.opencontainers.image.title="sfcx" \
      org.opencontainers.image.version="@@VERSION@@" \
      org.opencontainers.image.source="https://github.com/awslabs/industrial-shopfloor-connect"
COPY sfc-uberjar.jar USAGE.txt /opt/sfc/
COPY entrypoint sfcx ipc /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint /usr/local/bin/sfcx /usr/local/bin/ipc
WORKDIR /opt/sfc
ENTRYPOINT ["/usr/local/bin/entrypoint"]
'@
    Write-LfFile (Join-Path $Dir 'Dockerfile') $dockerfile.Replace('@@SFCUP@@', $SfcupVersion).Replace('@@VERSION@@', $Version)

    Write-LfFile (Join-Path $Dir 'sfcx') @'
#!/bin/sh
# Generated by sfcup: sfc-main from the uberjar.
exec java ${JAVA_OPTS:-} -cp /opt/sfc/sfc-uberjar.jar com.amazonaws.sfc.MainController "$@"
'@

    Write-LfFile (Join-Path $Dir 'entrypoint') @'
#!/bin/sh
# Generated by sfcup. Without a known first word the arguments go to sfc-main; see: docker run IMAGE help
case "${1:-}" in
  help|-h|--help) exec cat /opt/sfc/USAGE.txt ;;
  ipc)            shift; exec /usr/local/bin/ipc "$@" ;;
  sh|bash)        exec "$@" ;;
  "")             [ -n "${SFC_CONFIG:-}" ] && exec /usr/local/bin/sfcx
                  exec cat /opt/sfc/USAGE.txt ;;
  *)              exec /usr/local/bin/sfcx "$@" ;;
esac
'@

    $ipc = New-Object System.Collections.Generic.List[string]
    $ipc.Add('#!/bin/sh')
    $ipc.Add('# Generated by sfcup. Runs one SFC IPC service from the uberjar:  ipc <service> -port <port> [options]')
    $ipc.Add('case "${1:-list}" in')
    $ipc.Add('  list|-h|--help)')
    $ipc.Add('    echo "IPC services in this image - run one with: ipc <service> -port <port>"')
    foreach ($line in $IpcServices) { $n, $c = $line -split ' '; $ipc.Add(('    echo "  {0,-28} {1}"' -f $n, $c)) }
    $ipc.Add('    exit 0 ;;')
    foreach ($line in $IpcServices) { $n, $c = $line -split ' '; $ipc.Add(('  {0}) cls={1} ;;' -f $n, $c)) }
    $ipc.Add('  *) echo "ipc: unknown service ''$1'' - run: ipc list" >&2; exit 2 ;;')
    $ipc.Add('esac')
    $ipc.Add('shift')
    $ipc.Add('exec java ${JAVA_OPTS:-} -cp /opt/sfc/sfc-uberjar.jar "$cls" "$@"')
    Write-LfFile (Join-Path $Dir 'ipc') ($ipc -join "`n")

    $usage = @'
sfcx @@VERSION@@ - Shop Floor Connectivity in one image, built by sfcup from sfc-uberjar.tar.gz

/opt/sfc/sfc-uberjar.jar holds sfc-main plus every protocol adapter and target. In this jar a
component is named by its FactoryClassName alone: AdapterTypes and TargetTypes need no JarFiles.

SFC-MAIN (the default)
  docker run --rm -v "$PWD:/cfg" IMAGE -config /cfg/sfc-config.json -info
  docker run --rm -e SFC_CONFIG="$(cat sfc-config.json)" IMAGE
      without -config, sfc-main reads its configuration from the SFC_CONFIG variable
  log level:  -info | -warning | -error | -trace        plain output:  -nocolor

IPC SERVICES (one protocol adapter or target per container)
  docker run --rm IMAGE ipc list
  docker run --rm -p 50000:50000 IMAGE ipc opcua -port 50000
  options:  -port <port> or -envport <variable holding the port>, -connection <type>,
            -cert <file> -key <file> -ca <file>; adapters also -adapter <id>, targets -target <id>
  sfc-main reaches a service through AdapterServers / TargetServers (Address and Port) and
  ProtocolAdapters.<id>.AdapterServer / Targets.<id>.TargetServer in its configuration.

OTHER
  docker run --rm IMAGE help          this text
  docker run --rm -it IMAGE sh        a shell in the image
  -e JAVA_OPTS="-Xmx512m"             JVM options for sfc-main and every IPC service

IPC SERVICES IN THIS IMAGE
'@
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add($usage.Replace('@@VERSION@@', $Version).TrimEnd())
    foreach ($line in $IpcServices) { $n, $c = $line -split ' '; $lines.Add(('  {0,-28} {1}' -f $n, $c)) }
    Write-LfFile (Join-Path $Dir 'USAGE.txt') ($lines -join "`n")
}

function Invoke-AwsEcr {
    param([string] $Extracted)
    $imageTag = if ($Tag) { $Tag } else { $Version }
    Test-Value '-Repo' $Repo '^[a-z0-9]+([._/-][a-z0-9]+)*$'
    Test-Value '-Tag' $imageTag '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
    $ctx = Join-Path $tmp 'image'
    New-ImageContext -Dir $ctx -Jar (Get-BundleJar $Extracted)

    if ($DryRun) {
        Write-Host ""
        Write-Host "Dockerfile  (build context ${ctx}: Dockerfile, sfc-uberjar.jar, entrypoint, sfcx, ipc, USAGE.txt)" -ForegroundColor White
        Get-Content -LiteralPath (Join-Path $ctx 'Dockerfile') | ForEach-Object { Write-Host $_ }
        Write-Host ""
        Write-Host "USAGE.txt" -ForegroundColor White
        Get-Content -LiteralPath (Join-Path $ctx 'USAGE.txt') | ForEach-Object { Write-Host $_ }
        Write-Host ""
        Write-Ok "dry run: nothing was built or pushed"
        return
    }

    $builder = $null
    foreach ($candidate in @($env:SFCUP_BUILDER, 'docker', 'podman', 'finch')) {
        if ($candidate -and (Get-Command $candidate -ErrorAction SilentlyContinue)) { $builder = $candidate; break }
    }
    if (-not $builder) { Fail "need docker, podman or finch to build the image (or set SFCUP_BUILDER)" }
    Initialize-AwsContext
    $registry = "$($script:AwsAccount).dkr.ecr.$($script:AwsRegion).amazonaws.com"
    $image = "$registry/${Repo}:$imageTag"

    if ((Invoke-Quiet 'aws' @('ecr', 'describe-repositories', '--region', $script:AwsRegion, '--repository-names', $Repo)) -eq 0) {
        Write-Step "ECR repository $Repo exists"
    } else {
        & aws ecr create-repository --region $script:AwsRegion --repository-name $Repo --image-scanning-configuration scanOnPush=true | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "could not create the ECR repository $Repo" }
        Write-Step "created the ECR repository $Repo"
    }
    $password = & aws ecr get-login-password --region $script:AwsRegion
    if ($LASTEXITCODE -ne 0 -or -not $password) { Fail "could not get an ECR login password" }
    $password | & $builder login --username AWS --password-stdin $registry | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "$builder could not log in to $registry" }

    Write-Step "building $image with $builder"
    $buildArgs = @('build')
    if ($Platform) { $buildArgs += @('--platform', $Platform) }
    $buildArgs += @('-t', $image, $ctx)
    & $builder @buildArgs
    if ($LASTEXITCODE -ne 0) { Fail "the image build failed" }
    Write-Step "pushing"
    & $builder push $image
    if ($LASTEXITCODE -ne 0) { Fail "the push to $registry failed" }

    Write-Host ""
    Write-Ok "pushed $image"
    Write-Host ""
    Write-Host "  usage     $builder run --rm $image help"
    Write-Host "  sfc-main  $builder run --rm -v `"`${PWD}:/cfg`" $image -config /cfg/sfc-config.json"
    Write-Host "  ipc       $builder run --rm -p 50000:50000 $image ipc opcua -port 50000"
    Write-Host ""
}

function Invoke-AwsGreengrass {
    param([string] $Extracted)
    $cversion = $ComponentVersion
    if (-not $cversion) {
        # A release tag vX.Y.Z gives X.Y.Z. Anything else (-Local) gets a fresh version, because a
        # component version can be created only once: 0.<days since 1970>.<second of the day>, each
        # part under Greengrass's maximum of 999999.
        $cversion = $Version -replace '^v', ''
        if ($cversion -notmatch '^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$') {
            $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $cversion = "0.$([math]::Floor($now / 86400)).$($now % 86400)"
        }
    }
    Test-Value '-ComponentVersion' $cversion '^[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}$'
    Test-Value '-Component' $Component '^[A-Za-z0-9][A-Za-z0-9._-]*$'
    $jar = Get-BundleJar $Extracted

    if ($DryRun) {
        $bucketName = if ($Bucket) { $Bucket } else { 'sfcx-greengrass-ACCOUNT-REGION' }
    } else {
        Initialize-AwsContext
        $bucketName = if ($Bucket) { $Bucket } else { "sfcx-greengrass-$($script:AwsAccount)-$($script:AwsRegion)" }
    }
    Test-Value '-Bucket' $bucketName '^[A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9]$'
    $uri = "s3://$bucketName/sfcx/$Component/$cversion/sfc-uberjar.jar"
    $recipe = Join-Path $tmp 'recipe.json'
    $text = $RecipeTemplate.Replace('@@COMPONENT@@', $Component).Replace('@@CVERSION@@', $cversion)
    $text = $text.Replace('@@SFCVERSION@@', $Version).Replace('@@SFCUP@@', $SfcupVersion)
    $text = $text.Replace('@@CONFIG@@', $DefaultConfig.Trim()).Replace('@@URI@@', $uri)
    Write-LfFile $recipe $text

    if ($DryRun) {
        Write-Host ""
        Write-Host "recipe  (the jar would go to $uri)" -ForegroundColor White
        Get-Content -LiteralPath $recipe | ForEach-Object { Write-Host $_ }
        Write-Host ""
        Write-Ok "dry run: nothing was uploaded or created"
        return
    }

    if ((Invoke-Quiet 'aws' @('s3api', 'head-bucket', '--bucket', $bucketName)) -eq 0) {
        Write-Step "bucket $bucketName exists"
    } else {
        & aws s3 mb "s3://$bucketName" --region $script:AwsRegion | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "could not create the bucket $bucketName - pass another name with -Bucket" }
        Write-Step "created the bucket $bucketName"
    }
    # The jar of an existing version must not be replaced: Greengrass checks it against the recorded digest.
    $versionArn = "arn:aws:greengrass:$($script:AwsRegion):$($script:AwsAccount):components:${Component}:versions:$cversion"
    if ((Invoke-Quiet 'aws' @('greengrassv2', 'describe-component', '--region', $script:AwsRegion, '--arn', $versionArn)) -eq 0) {
        Fail "$Component $cversion exists already - pass another -ComponentVersion"
    }
    Write-Step "uploading the jar to $uri"
    & aws s3 cp $jar $uri --region $script:AwsRegion --only-show-errors
    if ($LASTEXITCODE -ne 0) { Fail "could not upload the jar to $uri" }
    Write-Step "creating the component $Component $cversion"
    $arn = & aws greengrassv2 create-component-version --region $script:AwsRegion --inline-recipe "fileb://$recipe" --query arn --output text
    if ($LASTEXITCODE -ne 0 -or -not $arn) { Fail "could not create the component version (it may exist already: pass -ComponentVersion)" }

    Write-Host ""
    Write-Ok "created $Component $cversion"
    Write-Host "  arn      $arn"
    Write-Host "  status   aws greengrassv2 describe-component --region $($script:AwsRegion) --arn $arn --query status"
    Write-Host ""
    Write-Host "Deploy it to a core device (Java 17+ on the PATH of the Greengrass user): save"
    Write-Host ""
    Write-Host "  {`"$Component`": {`"componentVersion`": `"$cversion`"}}" -ForegroundColor White
    Write-Host ""
    Write-Host "as components.json and run:"
    Write-Host ""
    Write-Host "  aws greengrassv2 create-deployment --region $($script:AwsRegion) ``" -ForegroundColor White
    Write-Host "    --target-arn arn:aws:iot:$($script:AwsRegion):$($script:AwsAccount):thing/<core-device> ``" -ForegroundColor White
    Write-Host "    --components file://components.json" -ForegroundColor White
    Write-Host ""
    Write-Host "  The core device's token exchange role needs s3:GetObject on arn:aws:s3:::$bucketName/*."
    Write-Host "  A deployment to a thing replaces that thing's previous deployment - add the component to"
    Write-Host "  your existing deployment instead if the device runs other components."
    Write-Host "  Another SFC configuration: deploy with a configuration update that resets /SfcConfig and"
    Write-Host "  merges {`"SfcConfig`": {...}}; it is written to sfc-config.json each time the component starts."
    Write-Host "  SFC's output is in the component log."
    Write-Host ""
}

# -------------------------------------------------------------------------------------- install

Write-Host ""
Write-Host "sfcup " -NoNewline -ForegroundColor White
switch ($AwsMode) {
    'ecr'        { Write-Host "$SfcupVersion - building the sfcx image for Amazon ECR" }
    'greengrass' { Write-Host "$SfcupVersion - creating an AWS IoT Greengrass component" }
    default      { Write-Host "$SfcupVersion - installing Shop Floor Connectivity" }
}
Write-Host ""

# The AWS modes run nothing locally, so a local JVM does not matter for them.
if (-not $AwsMode) { Test-Java }

$srcTarball = $null
if ($Local) {
    # Developer path: install what this checkout just built.
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $srcTarball = Join-Path $here "build\distribution\$Bundle"
    if (-not (Test-Path -LiteralPath $srcTarball)) {
        Fail "no local bundle at $srcTarball`n  Build it first:  .\gradlew build"
    }
    $Version = 'local'
    Write-Step "using the local build"
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

# AWS modes: the same bundle, unpacked into a scratch dir and published; nothing is installed.
if ($AwsMode) {
    $sfcHomeCreated = -not (Test-Path -LiteralPath $SfcHome)
    New-Item -ItemType Directory -Force -Path $SfcHome | Out-Null
    $tmp = Join-Path $SfcHome ".tmp.$PID"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Get-Bundle -Scratch $tmp
        $extracted = Join-Path $tmp $BundleDir
        if ($AwsMode -eq 'ecr') { Invoke-AwsEcr -Extracted $extracted } else { Invoke-AwsGreengrass -Extracted $extracted }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
        if ($sfcHomeCreated -and -not (Get-ChildItem -LiteralPath $SfcHome -Force -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $SfcHome -Force -ErrorAction SilentlyContinue
        }
    }
    return
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
    Get-Bundle -Scratch $tmp
    $extracted = Join-Path $tmp $BundleDir

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
    Write-Host "  Ready-made configurations: $RepoUrl/blob/main/docs/examples/README.md" -ForegroundColor DarkGray
    Write-Host ""
}
finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
