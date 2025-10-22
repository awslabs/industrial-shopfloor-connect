
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.awssitewiseedge.config

import com.amazonaws.sfc.awsiot.AwsIotCredentialProviderClientConfiguration
import com.amazonaws.sfc.config.*
import com.amazonaws.sfc.log.LogLevel
import com.google.gson.annotations.SerializedName
import javax.naming.ConfigurationException
import kotlin.time.Duration
import kotlin.time.DurationUnit
import kotlin.time.toDuration

/**
 * AWS IoT Core target configuration
 */
@ConfigurationClass
class SiteWiseEdgeWriterConfiguration : BaseConfigurationWithMetrics(), Validate {


    @SerializedName(CONFIG_TARGETS)
    private var _targets: Map<String, SiteWiseEdgeTargetConfiguration> = emptyMap()
    val targets: Map<String, SiteWiseEdgeTargetConfiguration>
        get() = _targets.filter { (it.value.targetType == AWS_SITEWISEEDGE_TARGET) }


    /**
     * Validates configuration.
     * @throws ConfigurationException
     */
    @Throws(ConfigurationException::class)
    override fun validate() {
        if (validated) return

        super.validate()
        targets.forEach {
            it.value.validate()
        }
        validated = true

    }

    companion object {
        const val AWS_SITEWISEEDGE_TARGET = "AWS-SITEWISEEDGE-TARGET"

        private val default = SiteWiseEdgeWriterConfiguration()

        fun create(targets: Map<String, SiteWiseEdgeTargetConfiguration> = default._targets,
                   name: String = default._name,
                   version: String = default._version,
                   awsVersion: String? = default._awsVersion,
                   description: String = default._description,
                   schedules: List<ScheduleConfiguration> = default._schedules,
                   logLevel: LogLevel? = default._logLevel,
                   metadata: Map<String, String> = default._metadata,
                   elementNames: ElementNamesConfiguration = default._elementNames,
                   targetServers: Map<String, ServerConfiguration> = default._targetServers,
                   targetTypes: Map<String, InProcessConfiguration> = default._targetTypes,
                   adapterServers: Map<String, ServerConfiguration> = default._protocolAdapterServers,
                   adapterTypes: Map<String, InProcessConfiguration> = default._protocolTypes,
                   awsIotCredentialProviderClients: Map<String, AwsIotCredentialProviderClientConfiguration> = default._awsIoTCredentialProviderClients,
                   secretsManagerConfiguration: SecretsManagerConfiguration? = default._secretsManagerConfiguration,
                   monitorIncludedConfigFiles: Boolean = default._monitorIncludedConfigFiles,
                   monitorIncludedConfigFilesInterval : Duration = default._monitorIncludedConfigFilesInterval.toDuration(DurationUnit.SECONDS),
                   templatesConfiguration: TemplatesConfiguration? = default._templates): SiteWiseEdgeWriterConfiguration {

            val instance = createBaseConfiguration<SiteWiseEdgeWriterConfiguration>(
                name = name,
                version = version,
                awsVersion = awsVersion,
                description = description,
                schedules = schedules,
                logLevel = logLevel,
                metadata = metadata,
                elementNames = elementNames,
                targetServers = targetServers,
                targetTypes = targetTypes,
                adapterServers = adapterServers,
                adapterTypes = adapterTypes,
                awsIotCredentialProviderClients = awsIotCredentialProviderClients,
                secretsManagerConfiguration = secretsManagerConfiguration,
                templates = templatesConfiguration,
                monitorIncludedConfigFilesInterval = monitorIncludedConfigFilesInterval,
                monitorIncludedConfigFiles = monitorIncludedConfigFiles
            )

            instance._targets = targets
            return instance
        }

    }

}