## SFC Core Configuration



  - ### **[SFC top level configuration](sfc-configuration.md)**

    Core configuration file that defines the overall SFC service settings including sources, targets, schedules, and system-wide parameters

    

    ### Core Configuration types

  - [AggregationConfiguration](./aggregation-configuration.md)

    Buffers Size reads of a schedule and outputs per-channel aggregates (avg, min, max, ...) instead of every value.

    

  - [AwsIotCredentialProviderClientConfiguration](./aws-iot-credential-provider-configuration.md)

    Configuration for AWS IoT Core credential provider client that uses X.509 certificates to obtain temporary AWS credentials.

  - [AwsServiceConfiguration](./aws-service-configuration.md)
 
     Base configuration settings for AWS services

  - [BaseSourceConfiguration](./base-source-configuration.md)

    Base configuration class for data sources that defines common properties

  - [ChangeFilterConfiguration](./change-filter-configuration.md)

    Configuration for filtering data values based on whether they have changed from their previous value.

  - [ChannelConfiguration](./channel-configuration.md)

    Configuration that defines common properties for all adapter channel types 

  - [CertificateConfiguration](./certificate-configuration.md)

    Configuration for certificates of OPC UA adapters and targets: certificate file, private key, format and optional self-signed generation.

  - [ClientProxyConfiguration](./client-proxy-configuration.md)

    Configuration for HTTP/HTTPS proxy settings for network connections: ProxyUrl, ProxyUsername, ProxyPassword and NoProxyAddresses.

  - [CloudSecretConfiguration](./cloud-secret-configuration.md)

    Configuration for retrieving and managing secrets from AWS Secrets Manager.

  - [ConditionFilterConfiguration](./condition-filter-configuration.md)

    Configuration for filtering data based on specific conditions like the existence or non-existence of channels read from a source

  - [HealthProbeConfiguration](./health-probe-configuration.md)

    Configuration for setting up health check endpoints to monitor and report the operational status of services.

  - [InProcessConfiguration](./in-process-configuration.md)

    FactoryClassName (plus JarFiles outside the uberjar) for in-process adapters, targets, formatters, metrics writers, log writers and config providers. ConfigProvider and LogWriter always need a JarFiles list, `[]` with the uberjar.

  - [MetricsConfiguration](./metrics-configuration.md)

    Configuration for collecting and reporting system performance metrics and operational statistics.

  - [MetricsSourceConfiguration](./metrics-source-configuration.md)

    Configuration for defining data sources and collection settings for system metrics and performance measurements.

  - [MetricsWriterConfiguration](./metrics-writer-configuration.md)

    Configuration settings for the metrics writer service that handles the processing and output of collected metrics data.

  - [ProtocolAdapterConfiguration](./protocol-adapter-configuration.md)

    Base configuration structure for protocol adapters, defining how they operate either in-process or as separate services

  - [Schedule](./schedule-configuration.md)

    A schedule defines when and how often data is read from a source and processed by the SFC.

  - [SecretsManagerConfiguration](secrets-manager-configuration.md)

    Configuration for accessing secrets stored in AWS Secrets Manager to retrieve sensitive configuration values.

  - [SelfSignedCertificateConfiguration](./self-signed-certificate-configuration.md)

    Configuration settings for self-signed certificates generated for OPC UA adapters and targets.

  - [ServerConfiguration](server-configuration.md)

    Configuration settings for the SFC servers

  - [SourceConfiguration](source-configuration.md)

    Configuration settings that define data sources and how SFC should collect data from them.

  - [TargetConfiguration](target-configuration.md)

    Configuration settings that define where and how SFC should publish processed data from sources.

  - [TransformationOperatorConfiguration](transformation-operator-configuration.md)

    Configuration settings that define how to transform data as it flows from sources to targets.

  - [TuningConfiguration](tuning-configuration.md)

    Performance tuning parameters to optimize SFC's operation including buffer sizes, timeouts and concurrency settings.

  - [ValueFilterConfiguration](value-filter-configuration.md)

    Configuration for filtering data points based on their values using comparison operators and thresholds