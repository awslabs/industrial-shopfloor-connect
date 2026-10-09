# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes sim-to-kinesis.json: the uberjar configuration of the e2e case AWS-KIN-01 (ci/e2e/cases/aws/kinesis.json),
# without the CI-only Metadata and Metrics sections.
$ErrorActionPreference = 'Stop'
$cases = Get-Content -Raw (Join-Path $PSScriptRoot '..\..\ci\e2e\cases\aws\kinesis.json') | ConvertFrom-Json
$case = $cases.cases | Where-Object { $_.id -eq 'AWS-KIN-01' }

function Merge($base, $patch) {
    foreach ($p in $patch.PSObject.Properties) {
        $b = $base.PSObject.Properties[$p.Name]
        if ($b -and $b.Value -is [pscustomobject] -and $p.Value -is [pscustomobject]) { Merge $b.Value $p.Value }
        else { $base | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force }
    }
}

$config = $case.config
Merge $config $case.uberjar
$config.PSObject.Properties.Remove('Metadata')
$config.PSObject.Properties.Remove('Metrics')
$utf8 = New-Object System.Text.UTF8Encoding $false
$out = Join-Path $PSScriptRoot 'sim-to-kinesis.json'
[System.IO.File]::WriteAllText($out, ($config | ConvertTo-Json -Depth 100), $utf8)
Write-Host "wrote $out"
