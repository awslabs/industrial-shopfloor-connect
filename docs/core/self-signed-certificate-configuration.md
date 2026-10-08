# SelfSignedCertificateConfiguration

[CertificateConfiguration](./certificate-configuration.md) > [SelfSignedCertificate](./certificate-configuration.md#selfsignedcertificate)

Configuration for generating self-signed SSL/TLS certificates with customizable properties like common name, organization details, and validity period. Supports multiple DNS names and IP addresses in the certificate's Subject Alternative Names (SAN). Includes options for application URI and organizational identifiers. Requires at minimum a common name, with other fields being optional.

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [ApplicationUri](#applicationuri)
- [CommonName](#commonname)
- [CountryCode](#countrycode)
- [DnsNames](#dnsnames)
- [IpAddresses](#ipaddresses)
- [LocalityName](#localityname)
- [Organization](#organization)
- [OrganizationalUnit](#organizationalunit)
- [StateName](#statename)
- [ValidPeriodDays](#validperioddays)

---

### ApplicationUri

Specifies the URI that uniquely identifies the application using this certificate. This field is used in the certificate's Subject Alternative Name (SAN) extension to associate the certificate with a specific application.

**Type**: String

Default is `urn:aws-sfc-opcua@<hostname>` (the OPC UA target uses `urn:amazonaws:sfc:opcua-target`)

---
### CommonName

Specifies the fully qualified domain name (FQDN) or hostname that the certificate is issued for. This is a required field and represents the primary identity of the certificate holder (e.g., "example.com", "server.domain.com").

**Type:** string

---
### CountryCode

Specifies the two-letter ISO country code (e.g., "US", "GB", "DE") representing the country where the certificate holder is located. Must be exactly two characters following the ISO 3166-1 alpha-2 standard. 

**Type**:   String

---
### DnsNames
Specifies an array of additional domain names or hostnames to be included in the certificate's Subject Alternative Name (SAN) extension. This allows the certificate to be valid for multiple domains (e.g., "example.com", "*.example.com", "api.example.com").

**Type**:  [String]

Default: the host names of all IPv4 addresses of the host; use [] for none.

---
### IpAddresses

Specifies an array of IP addresses to be included in the certificate's Subject Alternative Name (SAN) extension. While it's generally recommended to use DNS names instead, this allows the certificate to be valid when accessing services via specific IP addresses.

**Type**: [String]

Default: all IPv4 addresses of the host; use [] for none.

---
### LocalityName

Specifies the city or locality where the certificate holder is located. This forms part of the certificate's Distinguished Name (DN) and helps identify the geographic location of the organization (e.g., "Seattle", "London", "Berlin").

**Type:**   String

---
### Organization

Specifies the legal name of the organization that owns the certificate. This should be the full, unabbreviated name of the organization (e.g., "Example Corporation", "Acme Industries Ltd.") and appears in the certificate's Distinguished Name (DN).

**Type:**   String

---
### OrganizationalUnit

Specifies the division or department within the organization that manages or owns the certificate (e.g., "IT Department", "Web Services", "Security Team"). This appears in the certificate's Distinguished Name (DN) as the Organizational Unit (OU).

**Type**: String

---
### StateName

Specifies the state or province where the certificate holder is located. This forms part of the certificate's Distinguished Name (DN) .

**Type:**   String

---
### ValidPeriodDays
Specifies the duration in days for which the self-signed certificate will remain valid from its issue date. If not explicitly set, the certificate will be valid for 1000 days. After this period expires, the certificate will need to be renewed. The value must be greater than 1.

**Type**: Integer

---

[^Top](#selfsignedcertificateconfiguration)



### Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "CommonName": {
      "type": "string",
      "description": "Common name for the certificate"
    },
    "Organization": {
      "type":   "string",
      "description": "Organization name for the certificate"
    },
    "OrganizationalUnit": {
      "type":   "string",
      "description": "Organizational unit for the certificate"
    },
    "LocalityName": {
      "type":   "string",
      "description": "Locality (city) for the certificate"
    },
    "StateName": {
      "type":   "string",
      "description": "State/province for the certificate"
    },
    "CountryCode": {
      "type":   "string",
      "description": "Two-letter country code",
      "minLength": 2,
      "maxLength": 2
    },
    "DnsNames": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "List of DNS names for the certificate"
    },
    "IpAddresses": {
      "type": "array",
      "items": {
        "type": "string",
        "format": "ipv4"
      },
      "description": "List of IP addresses for the certificate"
    },
    "ApplicationUri": {
      "type":   "string",
      "description": "Application URI for the certificate"
    },
    "ValidPeriodDays": {
      "type": "integer",
      "description": "Number of days the certificate will be valid",
      "minimum": 2,
      "default": 1000
    }
  },
  "required": [
    "CommonName"
  ]
}

```



## Examples

Minimal configuration

```json
{
  "CommonName": "example.com"
}
```



Complete configuration

```json
{
  "CommonName": "example.com",
  "Organization": "Example Corporation",
  "OrganizationalUnit": "IT Department",
  "LocalityName": "Seattle",
  "StateName": "Washington",
  "CountryCode": "US",
  "DnsNames": [
    "example.com",
    "*.example.com",
    "api.example.com",
    "web.example.com"
  ],
  "IpAddresses": [
    "192.168.1.1",
    "10.0.0.1",
    "172.16.0.1"
  ],
  "ApplicationUri": "urn:example:application:cert",
  "ValidPeriodDays": 365
}
```



Partial configuration

```json
{
  "CommonName": "api.company.com",
  "Organization": "Company Ltd",
  "CountryCode": "GB",
  "DnsNames": [
    "api.company.com",
    "*.api.company.com"
  ],
  "ValidPeriodDays": 730
}
```
