# SFC Output data formats



## Output data format

```
[schedule]  -- schedule name
[serial]    -- serial number
[timestamp] -- processing timestamp
[sources]   -- source name* --- [values] -- value name* --- [value]-- value
                            |                           |- [metadata]--name* -- meta value
                            |                           |- [timestamp]-- value timestamp
                            |
                            |- [timestamp] -- source timestamp
                            |- [metadata] -- name* -- value
[metadata] --name* -- value
```

One message, from a schedule with `"TimestampLevel": "Channel"`:

```json
{
  "schedule": "OpcuaToS3",
  "serial": "5b0f6c1e-8d2a-4c47-9a53-2f1e7b9d0c64",
  "timestamp": "2026-10-07T11:07:47.946143Z",
  "sources": {
    "OPCUA-SOURCE": {
      "values": {
        "FeedSpeed": { "value": 21.5, "timestamp": "2026-10-07T11:07:47.901Z" }
      }
    }
  }
}
```

See it live: [Uberjar PLC simulator](../examples/uberjar-plc-sim-s3tables/README.md#4-look-at-the-data) and [Simulator to S3 Tables](../examples/in-process-sim-s3tables/README.md) (JMESPath `ValueQuery` over this shape).



## Aggregated output data format 

```

[schedule]  -- schedule name
[serial]    -- serial number
[timestamp] -- processing timestamp
[sources]   -- source name* --- [values] -- value name* --- [value]-- aggregation name* --  [value] --- value
                            |                           |                                       [timestamp] -timestamp
                            |                           |- [metadata] -- name* -- meta value
                            |                           
                            |- [metadata] --- name* --- value
[metadata] --name* -- value
```

Custom element names in brackets can be set for all elements above in brackets using the [ElementNames](./core/sfc-configuration.md#elementnames) configuration
setting. The name keys for the sources and value maps get the value of the "Name" element for the source and channel in
their configuration (default is the key used as the id for the source/value in the configuration).

> **IPC deployments, current limitations:** target services write the default element names, and adapter services
> replace channel timestamps with the time the source data was sent.

The root contains 5 elements

- **schedule**: This element contains the name of the schedule that outputs the data
- **serial**: A unique serial number for the target data
- **timestamp**: Timestamp when the target output data was created
- **sources**: This element contains a map with a node for each source of the schedule that has output data
    - **values**: The values node contains a map for each channel of its source that has an output value
    
        - **value**: This node contains the actual value of a channel or an aggregated value
    
        - **metadata**: This node contains a map with (optional) metadata for a channel
    
        - **timestamp**: Timestamp for the value (only if the schedule's [TimestampLevel](./core/schedule-configuration.md#timestamplevel) is `Channel` or `Both`)
          For aggregated data TimestampLevel has no effect: there are no source or channel timestamps; first and last always carry a timestamp and each item of values carries its own.

    - **timestamp**: source read time (TimestampLevel `Source` or `Both`)
    - **metadata**: the source Metadata


- **metadata**: top-level Metadata merged with the schedule Metadata (schedule values win); omitted when empty

When a target transforms its output with a [velocity template](./core/target-configuration.md#template), set [TemplateEpochTimestamp](./core/target-configuration.md#templateepochtimestamp) to true on that target to add `timestamp_epoch_sec` and `timestamp_epoch_offset_nanosec` (named after the Timestamp element) next to every source, channel and aggregation timestamp in the template data. The message-level pair is currently not reachable from a template.



## SFC output data schemas



When target adapters write data in JSON format, the following schema is employed to structure the data of a  message or a list of messages if batching is enabled. 

Note that the names for the properties can be customized using the [ElementNames](./core/sfc-configuration.md#elementnames) property in the SFC Configuration.

Unsigned 8/16/32-bit values are written as JSON strings; set [UnquoteNumericJsonValues](./core/target-configuration.md#unquotenumericjsonvalues) on the target to emit numbers.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "description": "SFC Target data",
  
  "oneOf": [
    {
      "$ref": "#/definitions/targetdata"
    },
    {
      "type": "array",
      "description": "Array of SFC Target data items",
      "items": {
        "$ref": "#/definitions/targetdata"
      }
    }
  ],
  
  "definitions": {
    
    "targetdata": {
      "type": "object",
      "description": "Single SFC Target data item",
      "required": ["schedule", "serial", "timestamp", "sources"],
      "properties": {
        "schedule": {
          "type": "string",
          "description": "Name of the schedule"
        },
        "serial": {
          "type": "string",
          "description": "Unique identifier for the data message",
          "format": "uuid"
        },
        "timestamp": {
          "$ref": "#/definitions/timestamp",
          "description": "Timestamp when the target data message was created"
        },
        "sources": {
          "type": "object",
          "description": "Data sources containing channel values",
          "minProperties": 0,
          "additionalProperties": {
            "type": "object",
            "description": "Source containing channel values and optional metadata and timestamp",
            "required": ["values"],
            "properties": {
              "values": {
                "type": "object",
                "description": "Channel values for the source",
                "minProperties": 1,
                "additionalProperties": {
                  "type": "object",
                  "description": "Channel containing value and optional metadata and timestamp",
                  "required": ["value"],
                  "properties": {
                    "value": {
                      "$ref": "#/definitions/any"
                    },
                    "metadata": {
                      "$ref": "#/definitions/metadata"
                    },
                    "timestamp": {
                      "$ref": "#/definitions/timestamp"
                    }
                  }
                }
              },
              "metadata": {
                "$ref": "#/definitions/metadata"
              },
              "timestamp": {
                "$ref": "#/definitions/timestamp"
              }
            }
          }
        },
        "metadata": {
          "$ref": "#/definitions/metadata",
          "description": "Optional metadata for the schedule"
        }
      }
    },
    
    "any": {
      "description": "Value which can be of any JSON type (string, number, boolean, array or object)"
    },
    
    "metadata": {
      "type": "object",
      "description": "String key-value pairs containing metadata",
      "additionalProperties": {
        "type": "string"
      }
    },
    
    "timestamp": {
      "type": "string",
      "description": "ISO-8601 formatted timestamp",
      "format": "date-time"
    }
  }
}

```



When [aggregation](./core/aggregation-configuration.md) is enabled for a schedule, an additional level is added for every statistical value defined in the [output definition](./core/aggregation-configuration.md#output) for the aggregation.



```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "description": "SFC Target aggregated data",
  
  "oneOf": [
    {
      "$ref": "#/definitions/aggregatedData"
    },
    {
      "type": "array",
      "description": "Array of aggregated SFC Target data items",
      "items": {
        "$ref": "#/definitions/aggregatedData"
      }
    }
  ],
  
  "definitions": {
    "aggregatedData": {
      "type": "object",
      "required": [
        "schedule",
        "serial",
        "timestamp",
        "sources"
      ],
      "properties": {
        
        "schedule": {
          "type": "string",
          "description": "Name of the schedule"
        },
        
        "serial": {
          "type": "string",
          "description": "Unique identifier for the data message",
          "format": "uuid"
        },
        
        "timestamp": {
          "$ref": "#/definitions/timestamp",
          "description": "Timestamp when the target data message was created"
        },
        
        "sources": {
          "type": "object",
          "description": "Data sources containing channel values",
          "additionalProperties": {
            "type": "object",
            "required": [
              "values"
            ],
            "properties": {
              
              "values": {
                "type": "object",
                "description": "Channel values for the source",
                "additionalProperties": {
                  
                  "type": "object",
                  "required": [
                    "value"
                  ],
                  "properties": {
                    
                    "value": {
                      "type": "object",
                      "description": "Statistical values",
                      "minProperties": 1,
                      "properties": {
                        
                        "avg": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "count": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "max": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "median": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "min": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "mode": {
                          "type": "object",
                          "required": [
                            "value"
                          ],
                          "properties": {
                            "value": {
                              "type": "array",
                              "minItems": 1,
                              "items": {
                                "$ref": "#/definitions/any"
                              }
                            },
                            "timestamp": {
                              "$ref": "#/definitions/timestamp"
                            }
                          }
                        },
                        
                        "stddev": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "sum": {
                          "$ref": "#/definitions/aggregatedValue"
                        },
                        
                        "values": {
                          "type": "object",
                          "required": [
                            "value"
                          ],
                          "properties": {
                            "value": {
                              "type": "array",
                              "minItems": 1,
                              "items": {
                                "type": "object",
                                "required": [
                                  "value"
                                ],
                                "properties": {
                                  "value": {
                                    "$ref": "#/definitions/any"
                                  },
                                  "timestamp": {
                                    "$ref": "#/definitions/timestamp"
                                  }
                                }
                              }
                            }
                          }
                        },
                        
                        "first": {
                          "type": "object",
                          "required": [
                            "value"
                          ],
                          "properties": {
                            "value": {
                              "$ref": "#/definitions/any"
                            },
                            "timestamp": {
                              "$ref": "#/definitions/timestamp"
                            }
                          }
                        },
                        
                        "last": {
                          "type": "object",
                          "required": [
                            "value"
                          ],
                          "properties": {
                            "value": {
                              "$ref": "#/definitions/any"
                            },
                            "timestamp": {
                              "$ref": "#/definitions/timestamp"
                            }
                          }
                        }
                      }
                    },
                    "metadata": {
                      "$ref": "#/definitions/metadata"
                    }
                  }
                }
              },
              "metadata": {
                "$ref": "#/definitions/metadata"
              }
            }
          }
        },
        "metadata": {
          "$ref": "#/definitions/metadata"
        }
      }
    },
    "aggregatedValue": {
      "type": "object",
      "description": "Numeric value or array of numeric values representing an aggregation result",
      "required": [
        "value"
      ],
      "properties": {
        "value": {
          "oneOf": [
            {
              "type": "number"
            },
            {
              "type": "array",
              "items": {
                "type": "number"
              }
            }
          ]
        }
      }
    },
    "any": {
      "description": "Any valid JSON value"
    },
    "metadata": {
      "type": "object",
      "description": "String key-value pairs containing metadata",
      "additionalProperties": {
        "type": "string"
      }
    },
    "timestamp": {
      "type": "string",
      "description": "ISO-8601 formatted timestamp",
      "format": "date-time"
    }
  }
}
```



The following targets serialize the SFC data, except when a transformation template is applied to the target, resulting in JSON format.

- **[AWS IoT Core Service Target](./targets/aws-iot-core.md)**
- **[AWS Kinesis Target](./targets/aws-kinesis.md)**
- **[AWS Kinesis Firehose Target](./targets/aws-kinesis-firehose.md)**
- [**AWS Lambda  Target**](./targets/aws-lambda.md)
- **[AWS MSK Target](./targets/aws-msk.md)**
- **[AWS S3 Target](./targets/aws-s3.md)**
- **[AWS SNS Target](./targets/aws-sns.md)**
- **[AWS SQS Service Target](./targets/aws-sqs.md)**
- **[Debug Target](./targets/debug.md)**
- **[File Target](./targets/file.md)**
- **[MQTT Target](./targets/mqtt.md)**
- **[NATS Target](./targets/nats.md)**

A [Template](./sfc-target-templates.md) replaces the JSON on any of these targets; all of them except the AWS Lambda target can use a custom [Formatter](./sfc-extending.md#custom-formatters) instead (a target cannot have both). The AWS IoT Core, AWS Lambda, AWS S3, MQTT and NATS targets send buffered messages as one JSON array unless the target sets [AsArrayWhenBuffered](./core/target-configuration.md#asarraywhenbuffered) to false.
