# AWS SiteWise Target

The AWS IoT [SiteWise](https://aws.amazon.com/iot-sitewise/) target adapter enables Shop Floor Connectivity's uninterrupted streaming of industrial device data directly to AWS IoT SiteWise assets and measurements. This adapter facilitates the mapping of device data to SiteWise asset properties, with the option of automatically creating the necessary SiteWise assets. Additionally, it handles data types and timestamps. 

## Deploy this target

`TargetType` is `AWS-SITEWISE` in every deployment mode. In the uberjar and in-process modes the `TargetTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configure-a-component-in-each-mode). All types and classes: [Target types and classes](../sfc-running-targets.md#target-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"TargetTypes": {
  "AWS-SITEWISE": { "FactoryClassName": "com.amazonaws.sfc.awssitewise.AwsSiteWiseTargetWriter" }
}
```

**In-process** - module bundle `aws-sitewise-target` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"TargetTypes": {
  "AWS-SITEWISE": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/aws-sitewise-target/lib"],
    "FactoryClassName": "com.amazonaws.sfc.awssitewise.AwsSiteWiseTargetWriter"
  }
}
```

**IPC** - no `TargetTypes`; the target runs as its own service:

```json
"Targets": {
  "SiteWiseTarget": {
    "TargetType": "AWS-SITEWISE",
    "TargetServer": "SiteWiseServer"
  }
},
"TargetServers": {
  "SiteWiseServer": { "Address": "localhost", "Port": 50001 }
}
```

Start the service before SFC, on the port of its `TargetServers` entry:

**Linux / macOS**

```shell
aws-sitewise-target/bin/aws-sitewise-target -port 50001
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\aws-sitewise-target\lib\*" com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService -port 50001
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService -port 50001` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.awssitewise.AwsSitewiseTargetService -port 50001`).

**Examples:** uberjar: [uberjar-sim-sitewise](../../examples/uberjar-sim-sitewise/README.md) · in-process: [in-process-s7-sitewise](../../examples/in-process-s7-sitewise/README.md), [in-process-opcua-sitewise](../../examples/in-process-opcua-sitewise/README.md) · all: [examples catalog](../examples/README.md)

**Configuration:**

- [AwsSitewiseTargetConfiguration](#awssitewisetargetconfiguration)
- [AwsSiteWiseAssetCreationConfiguration](#awssitewiseassetcreationconfiguration)
- [AwsSiteWiseAssetConfiguration](#awssitewiseassetconfiguration)
- [AwsSiteWiseAssetPropertyConfiguration](#awssitewiseassetpropertyconfiguration)

---

## AwsSitewiseTargetConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Targets](../core/sfc-configuration.md#targets) >  [Target](../core/target-configuration.md) 

AwsSitewiseTargetConfiguration extends the type  [TargetConfiguration](../core/target-configuration.md) with specific configuration data for sending data to SiteWise assets. The Targets configuration element can contain entries of this type, the TargetType of 
these entries must be set to **"AWS-SITEWISE"**

Required IAM permissions:

- `iotsitewise:BatchPutAssetPropertyValue`
- `iotsitewise:CreateAsset` (*)
- `iotsitewise:CreateAssetModel` (*)
- `iotsitewise:DescribeAsset` (*) (**)
- `iotsitewise:DescribeAssetModel` (*)
- `iotsitewise:ListAssetModels` (*) (**)
- `iotsitewise:ListAssets` (*) (**)
- `iotsitewise:UpdateAssetModel` (*)
- `iotsitewise:UpdateAssetProperty` (*) (only with [AssetPropertyAlias](#assetpropertyalias))
- `iotsitewise:TagResource` (*)

(*) required when using Asset creation

(**) required when an asset uses AssetName or AssetExternalId, or a property uses PropertyName or PropertyExternalId

Without AssetCreation, and with every asset addressed only by AssetId/PropertyId or PropertyAlias, only `iotsitewise:BatchPutAssetPropertyValue` is needed.


- [Schema](#awssitewisetargetconfiguration-schema)
- [Examples](#awssitewisetargetconfiguration-examples)

**Properties:**
- [AssetCreation](#assetcreation)
- [Assets](#assets)
- [BatchSize](#batchsize)
- [CredentialProviderClient](#credentialproviderclient)
- [Endpoint](#endpoint)
- [Interval](#interval)
- [Region](#region)

---
### AssetCreation
Controls the automatic creation of AWS IoT SiteWise asset models and assets by the target. When AssetCreation is present (even as `{}`), SFC creates one asset model ([AssetModelName](#assetmodelname)) and one asset ([AssetName](#assetname)) per source, with one measurement property per channel ([AssetPropertyName](#assetpropertyname)). The data type of a property comes from the first value, and its unit from the channel metadata key named by [AssetPropertyMetadataUnitName](#assetpropertymetadataunitname). Channels that appear later are added to the model. Models and assets are matched by their rendered name: an existing model or asset with that name is reused, so sources whose names render to the same value share one model or asset.

Without AssetCreation, nothing is created, and existing assets must be configured in [Assets](#assets).

Example configuration: [in-process-s7-sitewise-autocreate-assets.json](../../examples/in-process-s7-sitewise/in-process-s7-sitewise-autocreate-assets.json).

**Type**:  [AwsSiteWiseAssetCreationConfiguration](#awssitewiseassetcreationconfiguration)

---
### Assets
Defines the mapping configuration for writing data to existing AWS IoT SiteWise assets. This setting allows you to specify how source data should be mapped to asset properties in your IoT SiteWise asset hierarchy.

Each asset configuration in the list specifies:

- The target asset identifier
- Property mappings for measurements, attributes, or transforms
- Data type conversions and transformations
- Timestamp handling

This configuration can be used alongside automatically created assets (defined in [AssetCreation](#assetcreation)), providing flexibility to:

- Write to existing asset structures
- Combine with dynamically created assets
- Support hybrid deployment scenarios

Required if writing to existing assets. Optional if using only automatically created assets through [AssetCreation](#assetcreation).

**Type**: List of [AwsSiteWiseAssetConfiguration](#awssitewiseassetconfiguration)




---
### BatchSize
Number of target-data messages (schedule reads) to buffer before writing to AWS IoT SiteWise. The buffered values are split automatically into BatchPutAssetPropertyValue requests of at most 10 entries with 10 values each, so BatchSize is not limited to 10.

Optional. If not specified, the default value of 10 will be used.

**Type**: Integer

---
### CredentialProviderClient

The CredentialProviderClient property specifies which AWS credential provider client to use for authentication. It references a client defined in the SFC's top-level configuration under [AwsIotCredentialProviderClients](../core/sfc-configuration.md#awsiotcredentialproviderclients) section. This client uses X.509 certificates to obtain temporary AWS credentials through the  [AWS IoT credentials provider](../sfc-aws-service-credentials.md).

If no CredentialProviderClient is configured the [AWS Java SDK credential provider chain is used](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials.html#credentials-chain)

**Type:** String

---

### Endpoint

The Endpoint property specifies the VPC endpoint URL used to access AWS services privately through AWS PrivateLink without requiring an internet gateway or NAT device. When not specified, the service's default public endpoint for the configured region will be used.

https://docs.aws.amazon.com/vpc/latest/privatelink/aws-services-privatelink-support.html

Region, Endpoint and CredentialProviderClient are also described in [AwsServiceConfiguration](../core/aws-service-configuration.md).

**Type:** String

---

### Interval

Specifies a time-based trigger for sending data to AWS IoT SiteWise, ensuring data is sent even when the [BatchSize](#batchsize) threshold is not met. This helps maintain data freshness during periods of low data volume.

- Triggers data transmission after specified milliseconds
- Works in conjunction with BatchSize
- Ensures timely data delivery regardless of buffer fullness
- Helps optimize real-time monitoring scenarios

Optional. When not specified, data transmission is controlled solely by BatchSize, which may lead to increased latency during low-volume periods.

**Type**: Integer

Optional, if not set only [BatchSize](#batchsize) is used. The value must be greater than 10 (milliseconds).


---
### Region
Specifies the AWS Region where the IoT SiteWise service is deployed. The Region must be one where AWS IoT SiteWise is available and supported. [[1\]](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-iotsitewise.html)

Examples:

- "us-east-1" (US East - N. Virginia)
- "eu-west-1" (Europe - Ireland)
- "ap-southeast-2" (Asia Pacific - Sydney)

Important considerations:

- Must match the region where your assets are defined
- Affects data residency and compliance
- Impacts latency between data source and SiteWise service
- Should align with your organization's AWS infrastructure

Optional. When not set, the AWS SDK default region provider chain is used, e.g. the AWS_REGION environment variable. The target connects to the AWS IoT SiteWise endpoint in that region.

**Type**: String

---



### AwsSitewiseTargetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsSitewiseTargetConfiguration",
  "type": "object",
  "allOf": [
    {
      "$ref": "#/definitions/TargetConfiguration"
    },
    {
      "$ref": "#/definitions/AwsServiceConfig"
    },
    {
      "type": "object",
      "properties": {
        "AssetCreation": {
          "$ref": "#/definitions/AwsSiteWiseAssetCreationConfiguration",
          "description": "Configuration for asset creation"
        },
        "Assets": {
          "type": "array",
          "description": "List of asset configurations",
          "items": {
            "$ref": "#/definitions/AwsSiteWiseAssetConfiguration"
          }
        },
        "BatchSize": {
          "type": "integer",
          "description": "Size of the batch for SiteWise operations"
        },
        "Interval": {
          "type": "integer",
          "description": "Interval in milliseconds between operations"
        },
        "Region": {
          "type": "string",
          "description": "AWS region for SiteWise"
        }
      },
      "anyOf": [
        {
          "required": ["AssetCreation"]
        },
        {
          "required": ["Assets"],
          "properties": {
            "Assets": {
              "minItems": 1
            }
          }
        }
      ]
    }
  ]
}

```

### AwsSitewiseTargetConfiguration Examples

Example configuration: [in-process-s7-sitewise](../../examples/in-process-s7-sitewise/README.md) (existing assets by AssetId and PropertyId).

 Config with full asset creation for all:

```json
{
  "TargetType" : "AWS-SITEWISE",     
  "Region": "us-east-1",
  "AssetCreation": {
    "AssetName": "Production %line% %source%",
    "AssetDescription": "Production line %line%",
    "AssetModelName": "Production %line%  %source%",
    "AssetPropertyName": "%source%-%channel%",
    "AssetTags": {
      "Location": "Plant-1",
      "Department": "Production"
    }
  },
  "CredentialProviderClient": "aws-credentials-provider"
}
```



Mixed: auto-created plus existing assets:

```json
{
  "TargetType" : "AWS-SITEWISE",       
  
  "Region": "eu-west-1",
  
  "AssetCreation": {
    "AssetName": "%plant%-%source%",
    "AssetModelName": "%plant%-%source%-model",
    "AssetPropertyName": "%plant%-%source%-%channel%",
    "AssetTags": {
      "Location": "Plant-1",
      "Department": "Production"
    }
  },
  
  "Assets": [
    {
      "AssetName": "AMS-Motor-1",
      "Properties": [
        {
          "PropertyName": "speed",
          "DataType": "double",
          "DataPath": "@.sources.Motor1.values.Speed.value"
        },
        {
          "PropertyName": "power",
          "DataType": "double",
          "DataPath": "@.sources.Motor1.values.Power.value"
        }
      ]
    },
    {
      "AssetName": "AMS-Motor-2",
      "Properties": [
        {
          "PropertyName": "speed",
          "DataType": "double",
          "DataPath": "@.sources.Motor2.values.Speed.value"
        },
        {
          "PropertyName": "power",
          "DataType": "double",
          "DataPath": "@.sources.Motor2.values.Power.value"
        }
      ]
    }
  ],
  "CredentialProviderClient": "aws-credentials-provider"
}
```



Existing assets only:

```json
{
  
  "TargetType" : "AWS-SITEWISE",     
  
  "Region": "eu-west-1",
  "Assets": [
    {
      "AssetName": "Motor-1",
      "Properties": [
        {
          "PropertyName": "speed",
          "DataType": "double",
          "DataPath": "@.sources.Motor1.values.Speed.value"
        },
        {
          "PropertyName": "power",
          "DataType": "double",
          "DataPath": "@.sources.Motor1.values.Power.value"
        }
      ]
    },
    {
      "AssetName": "Motor-2",
      "Properties": [
        {
          "PropertyName": "speed",
          "DataType": "double",
          "DataPath": "@.sources.Motor2.values.Speed.value"
        },
        {
          "PropertyName": "power",
          "DataType": "double",
          "DataPath": "@.sources.Motor2.values.Power.value"
        }
      ]
    }
  ],
  "CredentialProviderClient": "aws-credentials-provider"
}
```

[^top](#aws-sitewise-target)

## AwsSiteWiseAssetCreationConfiguration

[AwsSitewiseTarget](#awssitewisetargetconfiguration) > [AssetCreation](#assetcreation)

Configuration for automatic creation of AWS IoT SiteWise asset models and assets. Defines the templates for the names, descriptions, external IDs and tags of the asset models, assets and measurement properties the target creates, and how their values are timestamped. What is created is described under [AssetCreation](#assetcreation).

The external ID keys in AssetCreation end in `ID` (AssetExternalID, AssetModelExternalID, AssetModelPropertyExternalID); in an [Assets](#awssitewiseassetconfiguration) entry the key is AssetExternalId.

- [Schema](#awssitewiseassetcreationconfiguration-schema)
- [Examples](#awssitewiseassetcreationconfiguration-examples)

**Properties:**

- [AssetDescription](#assetdescription)
- [AssetExternalID](#assetexternalid)
- [AssetModelDescription](#assetmodeldescription)
- [AssetModelExternalID](#assetmodelexternalid)
- [AssetModelName](#assetmodelname)
- [AssetModelPropertyExternalID](#assetmodelpropertyexternalid)
- [AssetModelTags](#assetmodeltags)
- [AssetName](#assetname)
- [AssetPropertyAlias](#assetpropertyalias)
- [AssetPropertyMetadataUnitName](#assetpropertymetadataunitname)
- [AssetPropertyName](#assetpropertyname)
- [AssetPropertyTimestamp](#assetpropertytimestamp)
- [AssetTags](#assettags)



---
### AssetDescription
Defines the template used to generate descriptions for automatically created assets. The template supports dynamic content through placeholders and metadata values.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier (known limitation: in AssetDescription this is currently replaced by the target identifier)
- %datetime% - Current date/time
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Default: "Asset for target %target%, schedule %schedule%, source %source%"

Optional. When not specified, the default template is used. The description helps identify and organize assets within AWS IoT SiteWise

**Type**: String


---
### AssetExternalID
Defines the template used to generate external IDs for assets. External IDs provide a way to link SiteWise assets with external systems and maintain consistent identification across platforms.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Pattern requirements:

- Must start with a letter or number
- Can contain letters, numbers, hyphens, underscores
- Must be 2-128 characters long
- Must end with a letter or number

Optional. If not specified, no external ID will be assigned to the asset.

**Type**: String


---
### AssetModelDescription
Defines the template used to generate descriptions for automatically created asset models. The template supports dynamic content through placeholders and metadata values to provide context about the model's purpose and origin.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %datetime% - Current date/time
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Default: "Asset model for target %target%, schedule %schedule%, source %source%"

Optional. When not specified, the default template is used. The description helps identify and document asset models within AWS IoT SiteWise.

**Type**: String


---
### AssetModelExternalID
Template for external ID of created or updated asset models.

**Type** : String

Defines the template used to generate external IDs for asset models. External IDs enable integration with external systems by providing a consistent identifier across different platforms and systems. External IDs help maintain referential integrity when synchronizing with external systems.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Optional. If not specified, no external ID will be assigned to the asset model. 

Pattern requirements:

- Must be unique within your AWS account
- Must follow AWS IoT SiteWise naming conventions
- Case-sensitive

**Type**: String


---
### AssetModelName
Defines the template used to generate names for asset models. The template supports dynamic content through placeholders and metadata values to create unique and meaningful model names.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Default: "%target%-%schedule%-%source%-model"

Optional. Must follow AWS IoT SiteWise naming constraints: [[2\]](https://docs.aws.amazon.com/iot-sitewise/latest/userguide/update-asset-models.html)

- Maximum length of 256 characters
- Cannot contain control characters or certain special characters
- Must be unique within your AWS account

**Type**: String


---
### AssetModelPropertyExternalID
Defines the template used to generate external IDs for the measurement properties of created asset models.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %channel% - Channel identifier
- ${name} - Environment variables
- %metadataName% - Channel metadata values

Optional. If not specified, no external ID will be assigned to the properties. A `/` in the rendered value is replaced by `_`.

**Type**: String


---
### AssetModelTags
Defines key-value pairs of tags to be applied to created asset models. Tag values support dynamic content through templates, allowing for automated and consistent tagging based on context.

Available placeholders in value templates:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %datetime% - Current date/time
- ${name} - Environment variables

Metadata placeholders are not replaced in tag values.

Optional. When specified, these tags are automatically applied during asset model creation, enabling better resource organization and management in AWS IoT SiteWise.

**Type**: Map[String,String]

---
### AssetName
Defines the template used to generate names for assets. The template supports dynamic content through placeholders and metadata values to create unique and meaningful asset names.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Default: "%target%-%schedule%-%source%"

Optional. Must follow AWS IoT SiteWise naming constraints:

- Maximum length of 256 characters
- Must be unique within your asset hierarchy
- Cannot contain control characters or certain special characters

Rendered values are truncated to 128 characters.

**Type**: String


---
### AssetPropertyAlias
Defines the template used to generate aliases for asset properties. 

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %channel% - Channel identifier
- %uuid% - Random UUID
- %assetid% - ID of the asset containing the property
- ${name} - Environment variables
- %metadataName% - Source/target metadata values

Optional. If not specified, no alias will be created for the asset property.

Constraints:

- Minimum length of 1 character 
- Maximum length of 1000 characters
- Cannot contain control characters
- Must follow AWS IoT SiteWise alias naming conventions

**Type**: String


---
### AssetPropertyMetadataUnitName
Name of the channel metadata key whose value is used as the unit of the measurement property created for that channel. Channels without this metadata key get a property without a unit.

Default: "Unit"

Optional.

**Type**: String


---
### AssetPropertyName
Defines the template used to generate names for measurement asset properties. The template supports dynamic content through placeholders and metadata values to create descriptive and unique property names.

Available placeholders:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %channel% - Channel identifier
- ${name} - Environment variables
- %metadataName% - Metadata values from top, source, or channel level

Default: "%channel%"

Optional. Must follow AWS IoT SiteWise naming constraints:

- Maximum length of 256 characters
- Must be unique within the asset
- Cannot contain control characters or certain special characters

**Type**: String




---
### AssetPropertyTimestamp
Specifies which value to use for the timestamp of the measurement values written to the asset properties.

The value specifies the starting point in the target output data from where a timestamp is searched for. The following values
can be used. If no timestamp is available at the level in the output data, the next level up is tried. Depending on configuration
and availability at the source, it can happen that a timestamp is not available at source or channel level. The Schedule timestamp, which is at the top level of the target output data, is always available as it is added by the SFC core.

- "Channel" : Value timestamp, Source timestamp, Schedule timestamp
- "Source" : Source timestamp, Schedule timestamp
- "Schedule" : Schedule timestamp
- "System": Current UTC date and time


Default value is "Channel"

**Type**: String

---
### AssetTags
Defines key-value pairs of tags to be applied to created assets. Tag values can be dynamically generated using templates, allowing for consistent and automated asset tagging.

Available placeholders in value templates:

- %schedule% - Schedule identifier
- %target% - Target identifier
- %source% - Source identifier
- %datetime% - Current date/time
- ${name} - Environment variables

Metadata placeholders are not replaced in tag values.

Optional. When specified, these tags are automatically applied during asset creation, enabling better resource organization and management in AWS IoT SiteWise.

**Type**: Map[String,String]



[^top](#aws-sitewise-target)

### AwsSiteWiseAssetCreationConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsSiteWiseAssetCreationConfiguration",
  "type": "object",
  "properties": {
    "AssetDescription": {
      "type": "string",
      "description": "Description of the asset"
    },
    "AssetExternalID": {
      "type": "string",
      "description": "External ID of the asset"
    },
    "AssetModelDescription": {
      "type": "string",
      "description": "Description of the asset model"
    },
    "AssetModelExternalID": {
      "type": "string",
      "description": "External ID of the asset model"
    },
    "AssetModelName": {
      "type": "string",
      "description": "Name of the asset model"
    },
    "AssetModelPropertyExternalID": {
      "type": "string",
      "description": "External ID of the measurement properties of the asset model"
    },
    "AssetModelTags": {
      "type": "object",
      "description": "Tags for the asset model",
      "patternProperties": {
        "^.*$": {
          "type": "string"
        }
      },
      "additionalProperties": false
    },
    "AssetName": {
      "type": "string",
      "description": "Name of the asset"
    },
    "AssetPropertyAlias": {
      "type": "string",
      "description": "Alias for the asset property"
    },
    "AssetPropertyMetadataUnitName": {
      "type": "string",
      "description": "Channel metadata key that holds the unit of the asset property",
      "default": "Unit"
    },
    "AssetPropertyName": {
      "type": "string",
      "description": "Name of the asset property"
    },
    "AssetPropertyTimestamp": {
      "type": "string",
      "description": "Timestamp type for the asset property",
      "enum": ["Channel", "Source", "Schedule", "System"],
      "default": "Channel"
    },
    "AssetTags": {
      "type": "object",
      "description": "Tags for the asset",
      "patternProperties": {
        "^.*$": {
          "type": "string"
        }
      },
      "additionalProperties": false
    }
  }
}

```

### AwsSiteWiseAssetCreationConfiguration Examples

Example configuration: [in-process-s7-sitewise-autocreate-assets.json](../../examples/in-process-s7-sitewise/in-process-s7-sitewise-autocreate-assets.json).

Config using all defaults

```json
{
}
```


Configuration overwriting defaults for AssetPropertyName and alias using values from target- and meta-data.

```json
{
  "AssetPropertyName": "%plant%-%source%-%channel%",
  "AssetPropertyAlias": "%plant%-%source%-%channel%-alias",
  "AssetTags":{
     "environment" : "production",
     "location" : "Plant-1",
     "batch" : "B-1001"
   }
}
```

Setting all possible values and adding tags for assetmodel and asset

```json
{
  "AssetName": "Assembly-Robot-%source%",
  "AssetDescription": "Robotic assembly unit for schedule %schedule% for location %location%",
  "AssetExternalID": "%source%-external",
  "AssetModelName": "RoboticAssemblyModel",
  "AssetModelDescription": "Standard model for robotic assembly units from source %source%",
  "AssetModelExternalID": "%source%-external",
  "AssetModelPropertyExternalID": "%source%-%channel%-external",
  "AssetPropertyName": "%source%-%channel%",
  "AssetPropertyAlias": "%source%-%channel%-alias",
  "AssetPropertyMetadataUnitName": "Unit",
  "AssetPropertyTimestamp": "Channel",
  "AssetTags": {
    "Type": "Robot %source%",
    "Function": "Assembly"
  },
  "AssetModelTags": {
    "Manufacturer": "Robot %source%",
    "Version": "2.0"
  }
}
```



## AwsSiteWiseAssetConfiguration

[AwsSitewiseTarget](#awssitewisetargetconfiguration) > [Assets](#assets) 

Configuration class that defines how data should be mapped to AWS IoT SiteWise assets and their properties.


- [Schema](#awssitewiseassetconfiguration-schema)
- [Examples](#awssitewiseassetconfiguration-examples)

**Properties:**

- [AssetExternalId](#assetexternalid-1)
- [AssetId](#assetid)
- [AssetName](#assetname-1)
- [Properties](#properties)

---
### AssetExternalId
Identifies an existing AWS IoT SiteWise asset using its external ID. This is an alternative to using the asset's UUID or name. Only one of the asset's id, name or external id can be specified. If all properties for the asset use the property alias then ExternalId must NOT be specified.

**Type**: String

---
### AssetId
Identifies an existing AWS IoT SiteWise asset using its ID. Exactly one of the asset's id, name, or external id must be specified. If all properties for the asset use the property alias, then AssetId must NOT be specified.

Must be the asset ID in UUID form (lower-case hex, 8-4-4-4-12), e.g. `a1b2c3d4-5678-90ef-1234-567890abcdef`; any other value is a configuration error. To address the asset by name, use [AssetName](#assetname-1).

**Type**: String

---
### AssetName
Identifies an existing AWS IoT SiteWise asset using its name. Only one of the asset's id, name or external id can be specified. If all properties for the asset use the property alias, then AssetName must NOT be specified.

**Type**: String

---
### Properties
Defines the list of property configurations that map data to AWS IoT SiteWise asset properties.

**Type**: List of [AwsSiteWiseAssetPropertyConfiguration](#awssitewiseassetpropertyconfiguration)

### AwsSiteWiseAssetConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsSiteWiseAssetConfiguration",
  "type": "object",
  "properties": {
    "AssetExternalId": {
      "type": "string",
      "description": "External ID of the asset"
    },
    "AssetId": {
      "type": "string", 
      "description": "ID of the asset"
    },
    "AssetName": {
      "type": "string",
      "description": "Name of the asset"
    },
    "Properties": {
      "type": "array",
      "description": "List of asset property configurations",
      "items": {
        "$ref": "#/definitions/AwsSiteWiseAssetPropertyConfiguration"
      },
      "minItems": 1
    }
  },
  "required": ["Properties"]
}

```

Exactly one of AssetId, AssetName or AssetExternalId, or none when every property uses PropertyAlias.

### AwsSiteWiseAssetConfiguration Examples

```json
{
  "AssetId": "a1b2c3d4-5678-90ef-1234-567890abcdef",
  "Properties": [
    {
      "PropertyName": "IsActive",
      "DataType": "boolean",
      "DataPath": "@.sources.PumpMotor.values.Active.value",
      "WarnIfNotPresent": true
    },
    {
      "PropertyName": "Speed",
      "DataType": "double",
      "DataPath": "@.sources.PumpMotor.values.Speed.value"
    }
  ]
}

```

[^top](#aws-sitewise-target)



## AwsSiteWiseAssetPropertyConfiguration

[AwsSitewiseTarget](#awssitewisetargetconfiguration) > [Assets](#assets) > [Asset](#awssitewiseassetconfiguration) > [Properties](#properties)

Configuration class that defines how data values should be mapped to a specific AWS IoT SiteWise asset property. Specifies how to identify the target property (using ID or alias) and defines the mapping rules for data values and their timestamps.

- [Schema](#awssitewiseassetpropertyconfiguration-schema)
- [Examples](#awssitewiseassetpropertyconfiguration-examples)

**Properties:**

- [DataPath](#datapath)
- [DataType](#datatype)
- [PropertyAlias](#propertyalias)
- [PropertyExternalId](#propertyexternalid)
- [PropertyId](#propertyid)
- [PropertyName](#propertyname)
- [TimestampPath](#timestamppath)
- [WarnIfNotPresent](#warnifnotpresent)

---
### DataPath
[JMES](https://jmespath.org/) path expression that selects the value to write to the AWS IoT SiteWise asset property from the received data structure.

A path typically has the format 

`"sources.<source name>.values.<channel name>.value"` 

The trailing `.value` can be left out; keep it if the value's own timestamp should be used without a [TimestampPath](#timestamppath).

Important notes:

- Names that start with a digit or contain characters other than letters, digits, `_`, `-` and `/` must be enclosed in quotes; `-` and `/` need no quotes
- Path must follow JMESPath syntax rules
- Must resolve to a single value in the data structure
- Case-sensitive

**Type**: String

---
### DataType
Specifies the AWS IoT SiteWise data type for the property value.

Possible values:

- "string"

- "integer"

- "double"

- "boolean"

If no type is specified the type of the value is used to determine type that is used

**Type**: String

---
### PropertyAlias
Alias that identifies the AWS IoT SiteWise asset property.

Only one of the property id, name, external id or alias must be specified.
If PropertyAlias is used for all properties of an asset, then the AssetId, AssetName, and AssetExternalId must not be configured for that asset.

**Type**: String

---
### PropertyExternalId
External ID of the AWS IoT SiteWise asset property.

Only one of the property id, name, external id or alias must be specified.

**Type**: String

---
### PropertyId
ID of the AWS IoT SiteWise asset property. 

Only one of the property id, name, external id or alias must be specified.

Must be the property ID in UUID form (lower-case hex, 8-4-4-4-12), e.g. `a1b2c3d4-5678-90ef-1234-567890abcdef`; any other value is a configuration error. To address the property by name, use [PropertyName](#propertyname).

**Type**: String

---
### PropertyName
Name of the AWS IoT SiteWise asset property.

Only one of the property id, name, external id or alias must be specified.

**Type**: String

---
### TimestampPath
Defines the path to extract timestamp information using JMESPath syntax.

A path typically has the format 

`"sources.<source name>.values.<channel name>.timestamp"`

If not specified, the adapter will look for a timestamp in the order: value level, source level, root level.
Names that start with a digit or contain characters other than letters, digits, `_`, `-` and `/` must be enclosed in quotes; `-` and `/` need no quotes.

**Type**: String


---
### WarnIfNotPresent
Controls whether a warning is generated when the specified data path doesn't return a value.

**Type**: Boolean

Default is true

### AwsSiteWiseAssetPropertyConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AwsSiteWiseAssetPropertyConfiguration",
  "type": "object",
  "properties": {
    "DataPath": {
      "type": "string",
      "description": "JMES Path to the data value in the source message"
    },
    "DataType": {
      "type": "string",
      "description": "Data type of the asset property",
      "enum": ["string", "integer", "double", "boolean"]
    },
    "PropertyAlias": {
      "type": "string",
      "description": "Alias of the asset property"
    },
    "PropertyExternalId": {
      "type": "string",
      "description": "External ID of the asset property"
    },
    "PropertyId": {
      "type": "string",
      "description": "ID of the asset property"
    },
    "PropertyName": {
      "type": "string",
      "description": "Name of the asset property"
    },
    "TimestampPath": {
      "type": "string",
      "description": "JMES Path to the timestamp value in the source message"
    },
    "WarnIfNotPresent": {
      "type": "boolean",
      "description": "Whether to generate a warning if the property is not present"
    }
  },
  "oneOf": [
    {
      "required": ["PropertyId"],
      "not": {
        "anyOf": [
          { "required": ["PropertyName"] },
          { "required": ["PropertyExternalId"] },
          { "required": ["PropertyAlias"] }
        ]
      }
    },
    {
      "required": ["PropertyName"],
      "not": {
        "anyOf": [
          { "required": ["PropertyId"] },
          { "required": ["PropertyExternalId"] },
          { "required": ["PropertyAlias"] }
        ]
      }
    },
    {
      "required": ["PropertyExternalId"],
      "not": {
        "anyOf": [
          { "required": ["PropertyId"] },
          { "required": ["PropertyName"] },
          { "required": ["PropertyAlias"] }
        ]
      }
    },
    {
      "required": ["PropertyAlias"],
      "not": {
        "anyOf": [
          { "required": ["PropertyId"] },
          { "required": ["PropertyName"] },
          { "required": ["PropertyExternalId"] }
        ]
      }
    }
  ]
}


```

### AwsSiteWiseAssetPropertyConfiguration Examples

```json
{
  "PropertyName": "IsActive",
  "DataType": "boolean",
  "DataPath": "@.sources.PumpMotor.values.Active.value",
  "TimestampPath": "@.sources.PumpMotor.values.Active.timestamp",
  "WarnIfNotPresent": true
}

```


[^top](#aws-sitewise-target)

