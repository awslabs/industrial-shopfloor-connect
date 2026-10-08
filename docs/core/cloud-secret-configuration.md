## CloudSecretConfiguration

[SFC Configuration](./sfc-configuration.md) > [SecretsManager](./sfc-configuration.md#secretsmanager) > [Secrets](./secrets-manager-configuration.md#secrets)

The CloudSecretConfiguration class defines how to retrieve and reference secrets from AWS Secrets Manager. It specifies the secret's identifier (name or ARN), an optional alias for local reference, and version labels for accessing specific secret values. This configuration enables secure access to sensitive information stored in AWS Secrets Manager.

Use a secret as `${<SecretId, name or Alias>}` anywhere in the configuration; an environment variable with the same name takes precedence. See [Configuration secrets](../sfc-configuration.md#configuration-secrets). The full SecretString is inserted, so store the value as plaintext, not as JSON key/value pairs. Use an Alias if the name contains characters other than letters, digits, `-`, `_`, `:` and `/`.

- [Schema](#schema)
- [Examples](#examples)

**Properties:**

- [Alias](#alias)
- [Labels](#labels)
- [SecretId](#secretid)

  

---
### Alias
The Alias property provides an alternative local name for referencing the secret within configuration placeholders. This optional string property allows you to use a simpler or more context-appropriate name when referring to the secret instead of using its actual SecretId or ARN.

**Type**: String

---
### Labels
The Labels property lists extra AWS Secrets Manager staging labels to download and cache. AWSCURRENT is always retrieved and is the version used by `${...}` placeholders.

**Type**: [String]

---
### SecretId
The SecretId property identifies the AWS Secrets Manager secret using either its name or Amazon Resource Name (ARN). This required string property allows referencing the secret in configuration placeholders using either format, providing flexibility in how the secret is identified and accessed.

 If the ARN of a secret is used, both the ARN or the name of the read secret can be used as a reference in the placeholder.

**Type**: String

[^top](#cloudsecretconfiguration)



## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "SecretId": {
      "type": "string",
      "description": "The ID or ARN of the secret"
    },
    "Alias": {
      "type": "string",
      "description": "Alias name for the secret"
    },
    "Labels": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "List of labels/staging labels associated with the secret"
    }
  }
}
```



### Examples



Basic configuration with just SecretId:

```json
{
  "SecretId": "myApplicationSecret"
}
```

Using AWS Secrets Manager ARN:

```json
{
  "SecretId": "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/database/credentials"
}
```



With SecretId and Alias:

```json
{
  "SecretId": "database-credentials",
  "Alias": "prod-db-creds"
}
```

With SecretId and staging Labels:

```json
{
  "SecretId": "app-secrets",
  "Labels": ["AWSCURRENT", "AWSPENDING"]
}
```



Secret by ARN with alias

```json
{
  "SecretId": "arn:aws:secretsmanager:us-west-2:123456789012:secret:api/keys",
  "Alias": "api-credentials"
}
```

[^top](#cloudsecretconfiguration)
