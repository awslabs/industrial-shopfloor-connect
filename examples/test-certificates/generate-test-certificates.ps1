#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.SPDX-License-Identifier: MIT-0
#
# Windows PowerShell counterpart of generate-test-certififcates.sh, for testing only. In the current folder it
# creates a test CA (ca-key.pem, ca-cert.pem) and a server and a client key and certificate signed by that CA
# (server-key.pem, server-cert.pem, client-key.pem, client-cert.pem), valid for 365 days. Their subject
# alternative names are this host's name, localhost, its IPv4 addresses, 127.0.0.1 and 0.0.0.0.
#
# It first deletes every *.pem, *.srl and *.cnf file in the current folder, so run it in an empty one.
# Needs openssl.exe on PATH; Git for Windows includes one:  $env:Path += ";C:\Program Files\Git\usr\bin"
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\generate-test-certificates.ps1

if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
    throw 'openssl.exe is not on PATH. Git for Windows includes one: $env:Path += ";C:\Program Files\Git\usr\bin"'
}

# Stops the script when the last openssl call failed
function Assert-OpenSsl([string] $Step) {
    if ($LASTEXITCODE -ne 0) { throw "openssl failed: $Step (exit code $LASTEXITCODE)" }
}

Remove-Item -Path *.pem, *.srl, *.cnf -ErrorAction SilentlyContinue

$C = "US"
$ST = "WA"
$L = "SEATTLE"
$O = "AWS"
$OU = "AIP"

$ipList = @(Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.IPAddress -ne "127.0.0.1" } |
            ForEach-Object { "IP:$($_.IPAddress)" })
$ipList += "IP:127.0.0.1", "IP:0.0.0.0"

$hostName = [System.Net.Dns]::GetHostName()
$dnsNames = "DNS:$hostName,DNS:localhost"
$cn = "/C=$C/ST=$ST/L=$L/O=$O/OU=$OU/CN=$hostName"
$subjectAltName = "subjectAltName=$dnsNames," + ($ipList -join ",")

# CA
# Private key and self-signed certificate
openssl req -x509 -newkey rsa:4096 -days 365 -nodes -keyout ca-key.pem -out ca-cert.pem -subj "${cn}-CA"
Assert-OpenSsl "CA key and certificate"

Write-Output "CA's self-signed certificate"
openssl x509 -in ca-cert.pem -noout -text



# SERVER
# Private key and certificate signing request
openssl req -newkey rsa:4096 -nodes -keyout server-key.pem -out server-req.pem -subj "${cn}-SERVER"
Assert-OpenSsl "server key and signing request"

# ASCII, because Windows PowerShell 5.1 writes UTF-16 with > and Out-File, which openssl cannot read
Set-Content -Path server-ext.cnf -Value $subjectAltName -Encoding Ascii

# Create certificate
openssl x509 -req -in server-req.pem -days 365 -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -extfile server-ext.cnf
Assert-OpenSsl "server certificate"

Write-Output "Server's signed certificate"
openssl x509 -in server-cert.pem -noout -text



# CLIENT
# Private key and certificate signing request
openssl req -newkey rsa:4096 -nodes -keyout client-key.pem -out client-req.pem -subj "${cn}-CLIENT"
Assert-OpenSsl "client key and signing request"

Set-Content -Path client-ext.cnf -Value $subjectAltName -Encoding Ascii

# Create certificate
openssl x509 -req -in client-req.pem -days 365 -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial -out client-cert.pem -extfile client-ext.cnf
Assert-OpenSsl "client certificate"

Write-Output "Client's signed certificate"
openssl x509 -in client-cert.pem -noout -text
