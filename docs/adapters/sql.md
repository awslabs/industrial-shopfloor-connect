# SQL Adapter Configuration

The SQL adapter for Shop Floor Connectivity (SFC) enables data ingestion from SQL databases using JDBC connections. It allows you to execute custom SQL queries to retrieve data from MySQL, MariaDB, PostgreSQL, Microsoft SQL Server and Oracle databases. 

## Deploy this adapter

`AdapterType` is `SQL` in every deployment mode. In the uberjar and in-process modes the `AdapterTypes` key is the same value. How the modes differ: [Configure a component in each mode](../sfc-deployment.md#configuration-in-each-mode). All types and classes: [Protocol adapter types and classes](../sfc-running-adapters.md#protocol-adapter-types-and-classes).

**Uberjar** - installed by [sfcup](../../README.md#1-install); run with `sfcx`:

```json
"AdapterTypes": {
  "SQL": { "FactoryClassName": "com.amazonaws.sfc.sql.SqlAdapter" }
}
```

**In-process** - module bundle `sql` unpacked into the directory named by `SFC_DEPLOYMENT_DIR`, run with `sfc-main`:

```json
"AdapterTypes": {
  "SQL": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/sql/lib"],
    "FactoryClassName": "com.amazonaws.sfc.sql.SqlAdapter"
  }
}
```

**IPC** - no `AdapterTypes`; the adapter runs as its own service:

```json
"ProtocolAdapters": {
  "SqlAdapter": {
    "AdapterType": "SQL",
    "AdapterServer": "SqlAdapterServer"
  }
},
"AdapterServers": {
  "SqlAdapterServer": { "Address": "localhost", "Port": 50000 }
}
```

Start the service before SFC, on the port of its `AdapterServers` entry:

**Linux / macOS**

```shell
sql/bin/sql -port 50000
```

**Windows (PowerShell)**

```powershell
java -cp "C:\sfc\sql\lib\*" com.amazonaws.sfc.sql.SqlProtocolService -port 50000
```

From an sfcup install, start the same service from the uberjar: `java -cp "$HOME/.sfc/current/lib/*" com.amazonaws.sfc.sql.SqlProtocolService -port 50000` (Windows: `java -cp "$HOME\.sfc\versions\$(Get-Content $HOME\.sfc\current.txt)\lib\*" com.amazonaws.sfc.sql.SqlProtocolService -port 50000`).

**Examples:** uberjar: [uberjar-sql-file](../../examples/uberjar-sql-file/README.md) · all: [examples catalog](../examples/README.md)

**Configuration:**

- [SqlSourceConfiguration](#sqlsourceconfiguration)
- [SqlChannelConfiguration](#sqlchannelconfiguration)
- [SqlAdapterConfiguration](#sqladapterconfiguration)
- [DbServerConfiguration](#dbserverconfiguration)

---

## SqlSourceConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) >  [Source](../core/source-configuration.md) 

SqlSourceConfiguration defines the mapping between SQL query results and IoT channels, specifying which database server to use (referenced from the configured database servers in the adapter) and how to read data from it. It contains the configuration parameters needed to execute queries.

 This type extends the [SourceConfiguration](../core/source-configuration.md) type.

- [Schema](#sqlsourceconfiguration-schema)
- [Examples](#sqlsourceconfiguration-examples)

**Properties:**
- [AdapterDbServer](#adapterdbserver)
- [Channels](#channels)
- [SingleRow](#singlerow)
- [SqlReadParameters](#sqlreadparameters)
- [SqlReadStatement](#sqlreadstatement)

---
### AdapterDbServer
The Database Server Identifier property specifies which database server configuration to use from the DbServers section defined in the SQL adapter configuration. This identifier must match exactly with one of the database server configurations defined in the adapter's [DbServers](#dbservers) section, creating a link between the source and its specific database connection parameters.

**Type**: String

---
### Channels
The Channels property defines the mapping between SQL query results and IoT channels. Each channel specifies how to retrieve data from the results of SQL statements. Channels can be selectively disabled by prefixing their identifier with a "#" character, enabling temporary removal of specific channels without deleting their configuration.

**Type**: Map[String,[SqlChannelConfiguration](#sqlchannelconfiguration)]

At least 1 channel must be configured.

---
### SingleRow
The SingleRow property, when set to true, ensures that only the first record from the SQL query result set is processed and returned. This simplifies channel value handling by returning single values instead of arrays - particularly useful when you know your query will (or should) only return one row. If false, the adapter will process all returned rows and the channel values will be arrays containing all retrieved values.

**Type**: Boolean

Default is false.

---
### SqlReadParameters
The SqlReadStatement parameters property accepts a list of values that will be substituted for the "?" placeholders in the SQL query statement. The number of parameters in this list must exactly match the number of placeholders in the query, and the values will be applied in order. 

**Type**: List[Any]

The number of items in the list must match the number of "?" placeholders in the SqlReadStatement.

---
### SqlReadStatement
The SqlReadStatement property defines the SQL statement that will be executed to retrieve data from the database. It must be a single statement that returns a result set, such as a SELECT, because the adapter runs it with JDBC `executeQuery`. Values for the statement are passed as "?" placeholders with [SqlReadParameters](#sqlreadparameters); named parameters such as ":machineId" are not supported. The statement is responsible for implementing the appropriate data retrieval strategy, such as marking processed records or implementing a mechanism to prevent duplicate reads. For example, the statement might only select unprocessed records and update their status, or delete records once they've been read, as long as it returns the rows it read as a result set.

**Type**: String



### SqlSourceConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for SQL source",
  "allOf": [
    {
      "$ref": "#/definitions/SourceConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "AdapterDbServer": {
          "type": "string",
          "description": "Reference to the database server configuration in the adapter"
        },
        "Channels": {
          "type": "object",
          "description": "Map of SQL channel configurations",
          "additionalProperties": {
            "$ref": "#/definitions/SqlChannelConfiguration"
          },
          "minProperties": 1
        },
        "SingleRow": {
          "type": "boolean",
          "description": "Indicates if the query should return only a single row",
          "default": false
        },
        "SqlReadParameters": {
          "type": "array",
          "description": "Values for the ? placeholders in the SQL read statement, in order",
          "items": {}
        },
        "SqlReadStatement": {
          "type": "string",
          "description": "SQL statement to read data from the database"
        }
      },
      "required": ["AdapterDbServer", "Channels", "SqlReadStatement"]
    }
  ]
}

```

### SqlSourceConfiguration Examples

```json
{
  "ProtocolAdapter": "SqlAdapter",
  "Description": "Process monitoring metrics",
  "AdapterDbServer": "MainDB",
  "SqlReadStatement": "SELECT timestamp, temperature, pressure, flow_rate FROM process_metrics WHERE machine_id = ?",
  "SqlReadParameters": ["MACHINE001"],
  "SingleRow": true,
  "Channels": {
    "Temperature": {
      "Name": "Temperature",
      "Description": "Process temperature",
      "ColumnNames": ["temperature"]
    },
    "Pressure": {
      "Name": "Pressure",
      "Description": "Process pressure",
      "ColumnNames": ["pressure"]
    },
    "FlowRate": {
      "Name": "FlowRate",
      "Description": "Process flow rate",
      "ColumnNames": ["flow_rate"]
    }
  }
}
```

[^top](#sql-adapter-configuration)



## SqlChannelConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [Sources](../core/sfc-configuration.md#sources) > [Source](../core/source-configuration.md)  > [Channels](../core/source-configuration.md#channels) > [Channel](../core/channel-configuration.md)

SqlChannelConfiguration extends ChannelConfiguration to provide SQL-specific channel mapping functionality, inheriting base channel properties like data type handling, validation, and transformation settings. This class adds SQL-specific configurations to define how values should be extracted from database query results  and how to process these values.

The SqlChannelConfiguration type extends the [ChannelConfiguration](../core/channel-configuration.md) class with channel properties for the SQL protocol adapter.

- [Schema](#sqlchannelconfiguration-schema)
- [Examples](#sqlchannelconfiguration-examples)


**Properties:**
- [ColumnNames](#columnnames)

---
### ColumnNames

The ColumnNames property specifies which columns from the SQL query result set should be included in the channel value. It accepts either a list of specific column names or  *  to include all columns.

 When a single column is specified, the channel value will be the direct value from that column. When multiple columns or  * is specified, the channel value becomes a map where keys are column names and values are the corresponding data from those columns. 

The default value  *  includes all columns from the result set

Column names are matched case-insensitively; with "*" the keys are the lowercase column names.

> Columns that the JDBC driver reports as type DATE or TIME cannot be converted yet and make the read fail; convert them in the SELECT to a date-time type that the driver reports as TIMESTAMP, or to text. A NULL value reads as 0 in integer and floating-point columns and makes the read fail in NUMERIC, DECIMAL and TIMESTAMP columns; use COALESCE for nullable columns.

**Type**: String[]

Default value is ["*"]

### SqlChannelConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for SQL channel",
  "allOf": [
    {
      "$ref": "#/definitions/ChannelConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "ColumnNames": {
          "type": "array",
          "description": "List of column names for the SQL query results",
          "items": {
            "type": "string"
          },
          "minItems": 1,
          "default": ["*"]
        }
      }
    }
  ]
}

```

### SqlChannelConfiguration Examples

```json
{
  "Name": "ProductionStatus",
  "Description": "Production line monitoring columns",
  "ColumnNames": [
    "line_id",
    "product_code",
    "quantity",
    "cycle_time",
    "defect_count",
    "operator_id"
  ]
}

```

[^top](#sql-adapter-configuration)

## SqlAdapterConfiguration

[SFC Configuration](../core/sfc-configuration.md) > [ProtocolAdapters](../core/sfc-configuration.md#protocoladapters) > [Adapter](../core/protocol-adapter-configuration.md) 

SqlAdapterConfiguration defines the configuration for the SQL adapter, including database server configurations (DbServers) and protocol-specific settings for connecting to and reading from SQL databases. It extends the class  [ProtocolAdapterConfiguration](../core/protocol-adapter-configuration.md)  class to include SQL-specific functionality.

- [Schema](#sqladapterconfiguration-schema)
- [Examples](#sqladapterconfiguration-examples)


**Properties:**
- [DbServers](#dbservers)

---
### DbServers
The DbServers property defines a collection of database server configurations that can be used by SQL sources in the adapter. Each source must reference one of these predefined server configurations using its [AdapterDbServer](#adapterdbserver) attribute, allowing for centralized configuration of database connection settings and reuse across multiple sources.

**Type**: Map[String,[DbServerConfiguration](#dbserverconfiguration)]

### SqlAdapterConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for SQL adapter with database servers",
  "allOf": [
    {
      "$ref": "#/definitions/AdapterConfiguration"
    },
    {
      "type": "object",
      "properties": {
        "DbServers": {
          "type": "object",
          "description": "Map of database server configurations",
          "additionalProperties": {
            "$ref": "#/definitions/DbServerConfiguration"
          },
          "minProperties": 1
        }
      },
      "required": ["DbServers"]
    }
  ]
}

```

### SqlAdapterConfiguration Examples

Basic configuration with single database:

```json
{
  "AdapterType": "SQL",
  "Description": "Process database",
  "DbServers": {
    "MainDB": {
      "DatabaseType": "postgresql",
      "Host": "localhost",
      "Port": 5432,
      "DatabaseName": "process_db",
      "UserName": "${user}",
      "Password": "${password}",
      "ConnectTimeout": 30000
    }
  }
}
```



Example 2 - Multi-database configuration:

```json
{
  "AdapterType": "SQL",
  "DbServers": {
    "PrimaryDB": {
      "DatabaseType": "mysql",
      "Host": "primary.db.local",
      "Port": 3306,
      "DatabaseName": "primary-db",
      "UserName": "${user}",
      "Password": "${password}",
      "ConnectTimeout": 30000,
      "InitScript": "init.sql"
    },
    "BackupDB": {
      "DatabaseType": "mysql",
      "Host": "backup.db.local",
      "Port": 3306,
      "DatabaseName": "backup-db",
      "UserName": "${user}",
      "Password": "${password}",
      "ConnectTimeout": 30000,
      "InitScript": "init.sql"
    }
  }
}
```




[^top](#sql-adapter-configuration)



## DbServerConfiguration

[SqlAdapter](#sqladapterconfiguration) > [DbServers](#dbservers)

DbServerConfiguration defines the connection settings and authentication details needed to connect to a specific database server, including the server address, port, credentials, and database type. It supports various database types and connection parameters required for establishing database connections.

- [Schema](#dbserverconfiguration-schema)
- [Examples](#dbserverconfiguration-examples)

**Properties:**
- [ConnectTimeout](#connecttimeout)
- [DatabaseName](#databasename)
- [DatabaseType](#databasetype)
- [Host](#host)
- [InitScript](#initscript)
- [InitSql](#initsql)
- [Password](#password)
- [Port](#port)
- [UserName](#username)
- [WaitAfterConnectError](#waitafterconnecterror)
- [WaitAfterReadError](#waitafterreaderror)

---
### ConnectTimeout
The ConnectTimeout property specifies how long (in milliseconds) the adapter will wait while attempting to establish a connection to the database server before timing out. It must be at least 1000 milliseconds (1 second), with a default value of 10000 milliseconds (10 seconds).

**Type**: Integer

---
### DatabaseName
The DatabaseName property specifies the name of the database to connect to, or in the case of Oracle databases, it represents the System Identifier (SID). For Oracle, the SID uniquely identifies the database instance and its memory and processes, while for other database types like MySQL, PostgreSQL, or SQL Server, it's simply the name of the database to be accessed.

**Type**: String

---
### DatabaseType
The DatabaseType property specifies which JDBC driver should be used to connect to the database, with supported options being (lowercase, exactly as listed): 

- "postgresql"
- "mariadb"
- "sqlserver"
- "mysql"
- "oracle"

 This setting determines which database-specific driver and connection protocol will be used for establishing the database connection. 

The JDBC drivers for all five types ship with the adapter (the `sql` module bundle and the uberjar), so there is nothing to install; other databases cannot be added through configuration. In the in-process mode the adapter loads the driver for each used DatabaseType from the `JarFiles` of the `AdapterTypes` entry `SQL`.

For "sqlserver", TLS is enabled and the server certificate is trusted without validation.

**SQL Server on Windows:** only SQL Server authentication ([UserName](#username) and [Password](#password)) is supported, not Windows integrated authentication (`integratedSecurity`). Enable SQL Server authentication on the server and create a SQL login for SFC.


**Type**: String

---
### Host
The Host property specifies the hostname or IP address of the database server to connect to. 

**Type**: String

---
### InitScript
The InitScript property specifies the path to a SQL script file that is executed when the adapter starts, before the sources read, on a separate connection that is closed afterwards. Session-level settings made by the script therefore do not carry over to the connections used for reads. The script cannot contain placeholders for secrets or environment variables. A relative path is resolved against the working directory of the process that runs the adapter. Note that if both InitScript and [InitSql](#initsql) properties are defined, the InitSql property will take precedence.

**Type**: String

---
### InitSql
The InitSql property allows you to specify SQL commands that are executed when the adapter starts, in the same way as [InitScript](#initscript). Unlike InitScript, InitSql accepts the SQL commands directly as text rather than from a file, and it supports placeholders for secrets and environment variables. If both InitSql and [InitScript](#initscript) are configured, the InitSql commands will be executed instead of the InitScript.

**Type**: String

---
### Password
The Password property specifies the authentication password used to connect to the database server. For security best practices, it is strongly recommended to not store this password directly in the configuration, but instead use a placeholder that references a password stored in [AWS Secrets manager](../core/secrets-manager-configuration.md), which provides secure, encrypted storage and management of database credentials.

**Type**: String

---
### Port
The Port property specifies the TCP port number where the database server is listening for connections. Required; there is no default.

The usual ports of the supported database servers are 3306 for MySQL/MariaDB, 1433 for SQL Server, 5432 for PostgreSQL, or 1521 for Oracle.

**Type**: Integer

---
### UserName
The UserName property specifies the database user account used to authenticate with the database server. For security best practices, it is strongly recommended to not store this username directly in the configuration, but instead use a placeholder that references a value stored in  [AWS Secrets manager](../core/secrets-manager-configuration.md), which provides secure, encrypted storage and management of database credentials.

**Type**: String

---
### WaitAfterConnectError
The WaitAfterConnectError property specifies how long (in milliseconds) a source pauses reading after a failed attempt to connect to the database server. It must be at least 1000 milliseconds.

**Type**: Integer

Default is 10000

---
### WaitAfterReadError
The WaitAfterReadError property specifies how long (in milliseconds) a source pauses reading after a failed read.

**Type**: Integer

Default is 10000



### DbServerConfiguration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "description": "Configuration for database server connection",
  "properties": {
    "ConnectTimeout": {
      "type": "integer",
      "description": "Connection timeout in milliseconds",
      "minimum": 1000,
      "default": 10000
    },
    "DatabaseName": {
      "type": "string",
      "description": "Name of the database to connect to"
    },
    "DatabaseType": {
      "type": "string",
      "description": "Type of database server",
      "enum": ["mysql", "postgresql", "sqlserver", "oracle", "mariadb"]
    },
    "Host": {
      "type": "string",
      "description": "Hostname or IP address of the database server"
    },
    "InitScript": {
      "type": "string",
      "description": "Path to initialization script file"
    },
    "InitSql": {
      "type": "string",
      "description": "SQL statements to execute upon connection"
    },
    "Password": {
      "type": "string",
      "description": "Database user password"
    },
    "Port": {
      "type": "integer",
      "description": "Database server port number"
    },
    "UserName": {
      "type": "string",
      "description": "Database username"
    },
    "WaitAfterConnectError": {
      "type": "integer",
      "description": "Time in milliseconds a source pauses after a failed connect",
      "minimum": 1000,
      "default": 10000
    },
    "WaitAfterReadError": {
      "type": "integer",
      "description": "Time in milliseconds a source pauses after a failed read",
      "default": 10000
    }
  },
  "required": ["DatabaseName", "DatabaseType", "Host", "Port"]
}

```

### DbServerConfiguration Examples

```json
{
  "DatabaseType": "mysql",
  "Host": "localhost",
  "Port": 3306,
  "DatabaseName": "myapp_db",
  "UserName": "${user}",
  "Password": "${password}",
  "ConnectTimeout": 30000
}

```

[^top](#sql-adapter-configuration)

