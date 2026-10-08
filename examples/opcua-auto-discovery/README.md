# SFC Example OPCUA auto discovery custom config provider

This is an example of a custom config provider allowing auto discovery of nodes to generate channels for configured  OPCUA sources.

The input SFC [configuration file `opcua-auto-discovery-config.json`](opcua-auto-discovery-config.json), used for sfc-main, holds the configuration for the OPCUA sources used by the OPCUA protocol 
adapter. Nodes on the OPCUA servers, which are configured for the sources, are browsed and for selected nodes channels will
be generated and added to the source. The initial list of channels for a source can be left empty. If the source already does 
contain channels, the channels for the discovered nodes are added to the existing ones.

The auto discovery configuration provider uses the OPCUA server configurations of the OPCUA servers used by the sources for which auto 
discovery is configured to connect to the OPCUA servers. This includes the settings as the configured security policy and
X.509 certificates which are used for that policy.

Auto discovery for a source is considered as failed if no nodes where discovered, due to errors connecting to the server or 
browsing or misconfigured auto discovery for that source. The provider can be configured to periodically retry the discovery with a configurable
retry interval and maximum number of retries.

After the provider finishes the auto discovery, sources that still have no channels are reported in the log. The 
configuration is only emitted if at least one source has channels.

As the configuration provider is dynamically loaded by the SFC Core process, the system on which this process executes
must have network access to the OPCUA server from which the nodes are retrieved.

To use the auto discovery provider it must be added as a custom configuration  provider to the SFC configuration as shown in the 
configuration snippet below. In-process, `JarFiles` names the `lib` directory of the `opcua-auto-discovery` module bundle, 
which also contains the OPC UA adapter the provider uses, so no other directory is needed:

```json
"ConfigProvider": {
    "JarFiles": ["${SFC_DEPLOYMENT_DIR}/opcua-auto-discovery/lib"],
    "FactoryClassName": "com.amazonaws.sfc.config.OpcuaAutoDiscoveryConfigProvider"
}
```

The uberjar already contains the provider. There the section keeps an empty list, `"JarFiles": []`, because SFC ignores a 
`ConfigProvider` section without that key.

The __AutoDiscovery__ configuration section contains the configuration for the auto discovery provider.


```json
    "AutoDiscovery": {
       "Sources": {
         "OPCUA-SOURCE": 
         [
           {
               "Prefix" : "Simulation",    
               "NodeId": "ns=3;s=85/0:Simulation",
               "DiscoveryDepth": 10,
               "DiscoveredNodeTypes": "VariablesAndEvents",
               "Exclusions": [ ".*Max\\sValue.*", ".*Min\\sValue.*"]
           },
           {
               "NodeId": "ns=0;i=2253",
               "DiscoveredNodeTypes": "VariablesAndEvents",
               "Exclusions": [ "ServerDiagnostics/.*"]
           },
           {
               "Prefix" : "MyDeviceData",   
               "NodeId": "ns=6;s=MyDevice",
               "DiscoveredNodeTypes": "VariablesAndEvents",
               "Inclusions" : [".*/MyLevel.*"]
           }
         ]
       },
       "IncludeDescription": true,
       "WaitForRetry": 60000,
       "MaxRetries": 10,
       "SavedLastConfig" : "generated-config.json"
     }

```

The __Sources__ section contains a table with an entry for each source for which nodes will be discovered. The key in this
table must match the name an OPCUA source configured for the OPCUA protocol adapter. The sources are configured as "normal"
OPCUA sources with the exception that the source does not have to contain any channels.
Each source entry does have a list of at least one, or more entries which specify from where and how the provider will browse
to discover the nodes. The provider will check if the source names do exist as actual opcua sources and if there are sources that
don't have channels configured do have auto discovery configured.

An entry includes:

- __NodeId__: From this node the provider will browse for sub nodes, this must be a valid and readable node on the server.
- __DiscoveryDepth__ (optional): This is the number of levels the provider wil browse down from the specified NodeId. By setting 
the value to 0, which is the default value, there will be no maximum depth.
- __DiscoveredNodeTypes__ (optional): The types of nodes to discover. Values can be "Variables" (the default) to discover variable nodes only, 
"Events" to discover  event and alarm nodes only, or "VariablesAndEvents" for both types. In order to 
include event and alarm nodes for a source the type of the event node or alarm node must be known as a  name of the OPCUA alarms from 
the model at https://reference.opcfoundation.org/Core/Part9/v105/docs/5.8, an OPCUA event from the model at
https://reference.opcfoundation.org/Core/Part3/v104/docs/9.1 (see [OPC UA alarm and event types](../../docs/adapters/opcua.md#opcua-alarm-and-event-types)) or a custom companion  specification event type configured 
in the profile (see the [OPC UA adapter server profiles](../../docs/adapters/opcua.md#opcuaserverprofileconfiguration) for details on how to configure server profiles with custom event types).
- __Inclusions__ (optional): This is a list of regular expressions which used to filter nodes. If this list is present 
the node path must at least match one expression from this list to be included. The node path is a concatenation of the browse names from the 
specified NodeId from which the provider browses down to, and including the tested node, concatenated with a '/' as separator. 
The whole path must match an expression, so wrap a part of a path in `.*` (e.g. ".*/MyLevel.*").
Note that browse names can include spaces. which must be specified as "\s" in the regex and that special characters in the 
regex like '\' must be escaped with an additional '\\' as to keep JSON syntax of the configuration valid.
- __Exclusions__ (optional): This is a list of regular expressions which will be used to filter nodes. If this list is present
   the node is excluded if an expression in the list matches the node path. (see Inclusions for the definition of a node path)
- __Prefix__ (optional): This is an optional prefix which will be used for the names of the channels generated from this entry.

The provider configuration has the following additional optional settings:

- __IncludeDescription__ (optional): If set to true (the default) then if the server node has a description it will be used as description for 
the channel created for that node
- __WaitForRetry__ (optional): Time in milliseconds between retries if auto discovery for one or more sources fails. The default is 60000 ms.
- __MaxRetries__ (optional): Max number of retries, default is 10 retries. Set to 0 to disable retries.
- __SavedLastConfig__ (optional): This is the name of the file to which the last generated configuration will be saved. 
Note that if the file already exists it will be overwritten by the provider.
- __MaxServerReadsPerSecond__ (optional): Maximum of browse and read operations per second the configuration provider will execute. As autodiscovery
is an intensive operation because of the required browse and read actions it can potentially overload the server, in which case this option can be used
to limit the amount of actions. 

The required node read actions for are executed in batches. The number of nodes in each batch is the value configured of the __ReadBatchSize__ 
option for the OPCUA server configuration. At message level, the client will use the values of __MaxMessageSize__, __MaxChunkSize__ and __MaxChunkCount__ 
configured for the [OPCUA server](../../docs/adapters/opcua.md#opcuaserverconfiguration). These 4 and the MaxServerReadsPerSecond options can be used to reduce the load on the OPCUA server during the 
auto discovery process.

When the content of the file which is used as value for the -config parameter is updated, the provider will automatically run the discovery
process.

The file opcua-auto-discovery-config.json is included as an example and starting point for creating a configuration file leveraging the auto discovery configuration provider.

## Run it

The configuration reads a Prosys OPC UA Simulation Server at `opc.tcp://localhost:53530/OPCUA/SimulationServer`, 
whose node IDs the entries use. SFC needs Java 17 or newer (Windows: 
`winget install EclipseAdoptium.Temurin.17.JDK`).

As configured, it runs in-process: unpack the module bundles `sfc-main`, `opcua-auto-discovery`, `opcua` and 
`debug-target` into the directory named by `SFC_DEPLOYMENT_DIR`, as shown under 
[In-process](../../docs/sfc-deployment.md#in-process) with this list of modules, and start sfc-main in this folder:

**Linux / macOS**

```shell
export SFC_DEPLOYMENT_DIR="$HOME/sfc"
"$SFC_DEPLOYMENT_DIR/sfc-main/bin/sfc-main" -config opcua-auto-discovery-config.json -info
```

**Windows (PowerShell)**

```powershell
$env:SFC_DEPLOYMENT_DIR = "C:/sfc"
java -cp "C:\sfc\sfc-main\lib\*" com.amazonaws.sfc.MainController -config opcua-auto-discovery-config.json -info
```

On Windows keep the forward slashes in `SFC_DEPLOYMENT_DIR`: SFC replaces the `${SFC_DEPLOYMENT_DIR}` placeholders in 
the raw JSON text of the configuration, where a backslash breaks the JSON.

With the uberjar installed by [sfcup](../../README.md#1-install), which already contains the provider, the OPC UA adapter 
and the debug target, set the `JarFiles` of `ConfigProvider` to `[]`, remove the `JarFiles` entries from `AdapterTypes` 
and `TargetTypes`, and run `sfcx -config opcua-auto-discovery-config.json -info`.

The log shows `Discovered <n> nodes for source OPCUA-SOURCE` and `Saving config to generated-config.json`. The generated 
configuration, with a channel for every discovered node, is saved in `generated-config.json`. With the shipped entries 
SFC then rejects it, see the known limitation below; once the channel IDs are accepted, the debug target prints the values 
read from these channels.

> **Known limitation:** SFC rejects channel IDs that contain a '/', but the provider currently joins the names in the path of
> a node with '/' to build its channel ID, and adds a '/' after the Prefix. A node below the first level under the browse
> root, or any node of an entry with a Prefix, therefore makes SFC reject the whole generated configuration. Until this is
> fixed, give every entry `"DiscoveryDepth": 1` and no Prefix; the shipped entries browse deeper.

Docs used: [OPC UA adapter](../../docs/adapters/opcua.md#opcuaserverprofileconfiguration) · [Debug target](../../docs/targets/debug.md) · [ConfigProvider](../../docs/core/sfc-configuration.md#configprovider) · [Custom configuration handlers](../../docs/sfc-extending.md#custom-configuration-handlers) · [In-process mode](../../docs/sfc-deployment.md#in-process) · [All examples](../../docs/examples/README.md)