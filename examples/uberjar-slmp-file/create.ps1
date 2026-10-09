# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Writes slmp-to-file.json: the uberjar configuration of the e2e case ADP-SLMP-PILOT (ci/e2e/cases/adapters/slmp.json),
# without the CI-only Metadata and Metrics sections.
$ErrorActionPreference = 'Stop'
$cases = Get-Content -Raw (Join-Path $PSScriptRoot '..\..\ci\e2e\cases\adapters\slmp.json') | ConvertFrom-Json
$case = $cases.cases | Where-Object { $_.id -eq 'ADP-SLMP-PILOT' }

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
$out = Join-Path $PSScriptRoot 'slmp-to-file.json'
[System.IO.File]::WriteAllText($out, ($config | ConvertTo-Json -Depth 100), $utf8)
Write-Host "wrote $out"
