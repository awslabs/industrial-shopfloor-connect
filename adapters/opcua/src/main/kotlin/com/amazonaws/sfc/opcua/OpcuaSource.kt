// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.opcua

import com.amazonaws.sfc.config.BaseConfiguration.Companion.CONFIG_USERNAME
import com.amazonaws.sfc.config.BaseConfiguration.Companion.CONFIG_USER_CERTIFICATE
import com.amazonaws.sfc.crypto.*
import com.amazonaws.sfc.data.*
import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.metrics.MetricDimensions
import com.amazonaws.sfc.metrics.MetricUnits
import com.amazonaws.sfc.metrics.MetricsCollector
import com.amazonaws.sfc.opcua.FilterHelper.Companion.DEFAULT_EVENT_TYPE
import com.amazonaws.sfc.opcua.FilterHelper.Companion.UNKNOWN_EVENT_TYPE
import com.amazonaws.sfc.opcua.config.*
import com.amazonaws.sfc.opcua.config.OpcuaAdapterConfiguration.Companion.CONFIG_EVENT_MAX_RETAIN_PERIOD
import com.amazonaws.sfc.opcua.config.OpcuaAdapterConfiguration.Companion.CONFIG_EVENT_MAX_RETAIN_SIZE
import com.amazonaws.sfc.system.DateTime
import com.amazonaws.sfc.system.DateTime.add
import com.amazonaws.sfc.system.DateTime.systemDateTime
import com.amazonaws.sfc.system.DateTime.systemDateUTC
import com.amazonaws.sfc.util.buildScope
import com.amazonaws.sfc.util.isJobCancellationException
import com.amazonaws.sfc.util.launch
import kotlinx.coroutines.*
import kotlinx.coroutines.future.await
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.eclipse.milo.opcua.sdk.client.OpcUaClient
import org.eclipse.milo.opcua.sdk.client.OpcUaClientConfigBuilder
import org.eclipse.milo.opcua.stack.transport.client.tcp.OpcTcpClientTransportConfigBuilder
import org.eclipse.milo.opcua.sdk.client.identity.UsernameProvider
import org.eclipse.milo.opcua.sdk.client.identity.X509IdentityProvider
import org.eclipse.milo.opcua.sdk.client.subscriptions.OpcUaMonitoredItem
import org.eclipse.milo.opcua.sdk.client.subscriptions.OpcUaSubscription
import org.eclipse.milo.opcua.sdk.client.subscriptions.MonitoredItemSynchronizationException
import org.eclipse.milo.opcua.stack.core.security.DefaultClientCertificateValidator
import org.eclipse.milo.opcua.stack.core.AttributeId
import org.eclipse.milo.opcua.stack.core.NodeIds
import org.eclipse.milo.opcua.stack.core.StatusCodes
import org.eclipse.milo.opcua.stack.core.UaException
import org.eclipse.milo.opcua.stack.core.channel.EncodingLimits
import org.eclipse.milo.opcua.stack.core.encoding.EncodingContext
import org.eclipse.milo.opcua.stack.core.types.builtin.*
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.UInteger
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.Unsigned.uint
import org.eclipse.milo.opcua.stack.core.types.enumerated.*
import org.eclipse.milo.opcua.stack.core.types.structured.*
import org.eclipse.milo.opcua.stack.core.util.EndpointUtil
import java.net.URI
import java.util.function.Consumer
import java.security.KeyPair
import java.security.cert.X509Certificate
import java.time.Instant
import java.time.Period
import java.time.temporal.ChronoUnit
import java.util.*
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.locks.ReentrantLock
import kotlin.io.path.Path
import kotlin.io.path.exists
import kotlin.jvm.optionals.getOrNull
import kotlin.time.Duration
import kotlin.time.DurationUnit
import kotlin.time.measureTime
import kotlin.time.toDuration


open class OpcuaSource(
    private val sourceID: String,
    private val configuration: OpcuaConfiguration,
    private val clientHandleAtomic: AtomicInteger,
    private val logger: Logger,
    private val metricsCollector: MetricsCollector?,
    adapterMetricDimensions: MetricDimensions?
) {

    // Working storage for nodes being read
    inner class OpcuaNodeData(
        val channelID: String,
        val readValueId: ReadValueId,
        val eventType: String?,
        val nodeEventSampleInterval: Int?,
        val eventProperties: List<Pair<NodeId, QualifiedName>>?
    ) {
        val isDataNode = eventType.isNullOrBlank()
        val isEventNode = !isDataNode

    }


    // milo 1.1.7 replaced the client-wide UaSubscriptionManager.SubscriptionListener with a
    // per-subscription OpcUaSubscription.SubscriptionListener. onPublishFailure has no successor -
    // publish recovery is internal to the SDK now - so connection loss is surfaced via
    // onStatusChanged / onWatchdogTimerElapsed instead.
    inner class SubscriptionListener(
        private val logger: Logger,
        private val fnOnConnectionLost: () -> Unit,
        private val fnOnSubscriptionTransferFailed: (OpcUaSubscription?, StatusCode?) -> Unit
    ) : OpcUaSubscription.SubscriptionListener {

        override fun onTransferFailed(subscription: OpcUaSubscription?, statusCode: StatusCode?) {
            val log = logger.getCtxLoggers(this::class.java.name, "onTransferFailed")
            try {
                log.warning("onTransferFailed event received with status code ${statusCode.toString()} ")
                fnOnSubscriptionTransferFailed(subscription, statusCode)
            } catch (e: Exception) {
                log.error("Error executing onSubscriptionTransferFailedAction, $e")
            }
        }

        override fun onStatusChanged(subscription: OpcUaSubscription?, statusCode: StatusCode?) {
            val log = logger.getCtxLoggers(this::class.java.name, "onStatusChanged")
            log.warning("Subscription status changed to ${statusCode.toString()}")
            if (statusCode?.value == StatusCodes.Bad_ConnectionClosed) fnOnConnectionLost()
        }

        override fun onWatchdogTimerElapsed(subscription: OpcUaSubscription?) {
            logger.getCtxLoggers(this::class.java.name, "onWatchdogTimerElapsed")
                .warning("No publish responses received within the watchdog interval, resetting client")
            fnOnConnectionLost()
        }

        override fun onNotificationDataLost(subscription: OpcUaSubscription?) {
            logger.getCtxLoggers(this::class.java.name, "onNotificationDataLost")
                .warning("Subscription notification data was lost")
        }
    }

    private val className = this::class.simpleName.toString()
    private val sourceScope = buildScope("OPCUA Source")

    private var isClosing: Boolean = false

    private var connectionWatchdog: Job? = null

    // configuration for this source instance
    private val sourceConfiguration = configuration.sources[sourceID]
            ?: throw OpcuaSourceException(sourceID, "Unknown source identifier, available sources are ${configuration.sources.keys}")

    // adapter configuration for source
    private val protocolAdapterID = sourceConfiguration.protocolAdapterID
    private val opcuaAdapterConfiguration = configuration.protocolAdapters[protocolAdapterID]
            ?: throw OpcuaSourceException(
                sourceID,
                "Unknown protocol adapter identifier \"$protocolAdapterID\", available OPCUA protocol adapters are ${configuration.protocolAdapters}"
            )


    private val dimensions = mapOf(MetricsCollector.METRICS_DIMENSION_SOURCE to "$protocolAdapterID:$sourceID") + adapterMetricDimensions as Map<String, String>

    // server from the adapter used by the source instance
    private val sourceAdapterOpcuaServerID = sourceConfiguration.sourceAdapterOpcuaServerID
    private val opcuaServerConfiguration = opcuaAdapterConfiguration.opcuaServers[sourceAdapterOpcuaServerID]
            ?: throw OpcuaSourceException(
                sourceID,
                "Unknown protocol adapter OPCUA server identifier \"$sourceAdapterOpcuaServerID\", available servers for adapter \"$protocolAdapterID\" are ${opcuaAdapterConfiguration.opcuaServers.keys}"
            )


    // optional profile for a server which does contain additional event/alarm types
    private val serverProfile =
        if (opcuaServerConfiguration.serverProfile != null)
            opcuaAdapterConfiguration.serverProfiles[opcuaServerConfiguration.serverProfile]
                    ?: throw OpcuaSourceException(
                        sourceID,
                        "Unknown server profile \"${opcuaServerConfiguration.serverProfile}\", available profiles for adapter \"$protocolAdapterID\" are ${opcuaAdapterConfiguration.serverProfiles.keys}"
                    )
        else OpcuaServerProfileConfiguration()

    // batch size for interacting with the server
    private val batchSize = opcuaServerConfiguration.readBatchSize

    // last fault whilst reading from the server
    private var sourceServerFault: ServiceFault? = null

    // subscription and monitored items for this source
    private var subscription: OpcUaSubscription? = null

    // milo 1.1.7 no longer passes an EncodingContext into the value/event listeners.
    // The client's static context is stable, so capture it once.
    private val encodingContext: EncodingContext
        get() = client!!.staticEncodingContext

    // backup field for client, used explicit field to allow testing the actual value without creating a new one on demand
    private var _opcuaClient: OpcUaClient? = null

    private var certificateExpiryChecker: Job? = null
    private var userCertificateExpiryChecker: Job? = null

    // opcua client used to interact with server
    private val client
        get() = runBlocking { getClient() }

    // gets a OPCUA client for a source
    suspend fun getClient(): OpcUaClient? {

        // pause after errors
        if (systemDateTime() < pauseWaitUntil) {
            return null
        }

        // use existing client
        if ((_opcuaClient != null)) {
            return _opcuaClient
        }

        connectionWatchdog?.cancel()
        connectionWatchdog = null

        // or create a new client
        createClientLock.withLock {
            if (_opcuaClient == null) {
                _opcuaClient = createOpcuaClient()
                subscription = _opcuaClient?.let { createSubscriptionWithMonitoredItems(it) }
                _opcuaClient?.addFaultListener { fault ->
                    // Bad_NoSubscription is returned incorrectly after creating a new connection with subscriptions
                    if (fault.responseHeader.serviceResult != StatusCode(StatusCodes.Bad_NoSubscription))
                        sourceServerFault = fault
                }
            }

            // after failing to connect temporary pause reading from the source
            if (_opcuaClient == null) {
                val waitingPeriod = opcuaServerConfiguration.waitAfterConnectError
                pauseWaitUntil = systemDateTime().plusMillis(waitingPeriod.inWholeMilliseconds)
                logger.getCtxInfoLog(className, "getClient")("Reading from source \"$sourceID\" paused for $waitingPeriod until $pauseWaitUntil")
            } else {
                if (_opcuaClient?.subscriptions?.isNotEmpty() == true) {
                    connectionWatchdog = startConnectionWatchdog()
                }
            }
        }

        return _opcuaClient
    }

    private fun startConnectionWatchdog(): Job? {


        // only needed in subscription mode as in read node the read will fail anyway if connection is lost
        if (sourceConfiguration.readingMode != OpcuaSourceReadingMode.SUBSCRIPTION && _opcuaClient?.subscriptions?.isEmpty() == true) return null

        if (opcuaServerConfiguration.connectionWatchdogInterval.inWholeMilliseconds == 0L) {
            logger.getCtxInfoLog(className, "startConnectionWatchdog")("Connection watchdog disabled as it's interval is set to 0")
        }

        return sourceScope.launch(Dispatchers.Default) {
            val log = logger.getCtxLoggers(className, "connectionWatchdog")
            while (isActive) {
                try {
                    // try to read server status
                    if (!isClosing) {
                        withTimeout(opcuaServerConfiguration.readTimeout) {
                            _opcuaClient?.readAsync(
                                0.0, TimestampsToReturn.Source, mutableListOf(
                                    ReadValueId(NodeIds.Server_ServerStatus_State, AttributeId.Value.uid(), null, QualifiedName.NULL_VALUE)
                                )
                            )?.await()
                        }
                        log.trace("Connection to server ${opcuaServerConfiguration.endPoint} for source \"${sourceID}\" checked")
                    }
                    delay(opcuaServerConfiguration.connectionWatchdogInterval)
                } catch (e: Exception) {
                    if (!e.isJobCancellationException) {
                        log.error("Unable to read from server ${opcuaServerConfiguration.endPoint} for source \"${sourceID}\"")
                        resetClient(1000)
                        delay(opcuaServerConfiguration.waitAfterReadError)
                    }
                }
            }
        }
    }

    // monitored data/event nodes
    private var monitoredItems: MutableList<OpcUaMonitoredItem>? = null

    // if an error occurs the source will pause for a configured period
    private var pauseWaitUntil: Instant = Instant.ofEpochSecond(0L)
    private val readingMode = sourceConfiguration.readingMode

    // lock to prevent creation of clients whilst one is being created
    private val createClientLock = Mutex()

    // nodes indexed by client handle used to create a subscription for that node

    private val anyEventNodes by lazy {
        sourceConfiguration.channels.values.any { channel: OpcuaNodeChannelConfiguration -> channel.isEventNode }
    }
    private val inSubscriptionReadingMode = readingMode == OpcuaSourceReadingMode.SUBSCRIPTION
    private val eventsHelper = if (anyEventNodes) OpcuaProfileEventsHelper(serverProfile) else null

    private val allValidTypesStr =
        eventsHelper?.allEventClasses?.sortedBy { it.first }?.map { "${it.first} (ns=${it.second?.namespaceIndex}i=${it.second?.identifier})" }

    private var trustManager: ClientTrustListManager? = null

    private val OpcuaNodeChannelConfiguration.eventProperties: List<Pair<NodeId, QualifiedName>>
        get() = if (this.isEventNode) {
            val event = eventsHelper?.findEvent(this.nodeEventType)
            event?.properties ?: eventsHelper?.findEvent(DEFAULT_EVENT_TYPE)?.properties ?: emptyList()
        } else emptyList()

    // working set of node data for the source instance
    private val sourceNodes by lazy {

        sourceConfiguration.channels.map { (channelID, nodeChannel) ->
            val attribute = if (nodeChannel.isDataNode) AttributeId.Value else AttributeId.EventNotifier

            val readValueId = ReadValueId(nodeChannel.nodeID, attribute.uid(), nodeChannel.indexRange, QualifiedName.NULL_VALUE)
            val configuredEventType = nodeChannel.nodeEventType

            val eventType = checkNodeEventType(configuredEventType, nodeChannel, channelID)

            channelID to OpcuaNodeData(
                channelID = channelID,
                readValueId = readValueId,
                eventType = eventType,
                nodeEventSampleInterval = nodeChannel.eventSamplingInterval,
                eventProperties = nodeChannel.eventProperties
            )
        }.toMap()
    }

    private fun checkNodeEventType(eventType: String?, nodeChannel: OpcuaNodeChannelConfiguration, channelID: String): String? =

        if (eventType.isNullOrBlank() || eventsHelper?.isKnownEvent(eventType) == true) eventType
        else {
            logger.getCtxWarningLog(className, "checkNodeEventType")(
                "Event type \"${nodeChannel.nodeEventType}\" for source \"$sourceID\" channel \"$channelID\" is not a valid event type, " +
                        "use the name or node id of any of the following valid event types $allValidTypesStr, " +
                        "adapter will collect events of any type and will use type \"$DEFAULT_EVENT_TYPE\" to collect the event properties"
            )
            UNKNOWN_EVENT_TYPE
        }


    // *** Data subscriptions ***

    // store for values changes for a monitored data node
    private val dataValueChangesStore = if (inSubscriptionReadingMode) SourceDataValuesStore<ChannelReadValue>() else null

    private fun EndpointDescription.asString(): String =
        "${this.endpointUrl}: " +
                "Security policy: \"${(this.securityPolicyUri ?: "None").split("#").last()}\", " +
                "Security mode: \"${this.securityMode.name}\", " +
                "User token types:[ ${
                    this.userIdentityTokens.orEmpty().joinToString { u ->
                        "\"${u.tokenType.name}:${(u.securityPolicyUri ?: "None").split("#").last()}\""
                    }
                }]"


    // *** Event Subscriptions ***

    // store for received event data for monitored event nodes
    private val eventStore = if (anyEventNodes) {
        SourceDataMultiValuesStore<Any>(opcuaAdapterConfiguration.maxEventRetainSize, opcuaAdapterConfiguration.maxEventRetainPeriod) { channel, duration, size, full ->
            if (full) {
                val ctxWarningLog = logger.getCtxWarningLog(className, "sourceDataStores")
                if (size != null)
                    ctxWarningLog("Source \"$sourceID\", channel \"$channel\" number of kept events reached maximum of $size values, oldest events are dropped, consider a larger $CONFIG_EVENT_MAX_RETAIN_SIZE for adapter or a faster reading interval.")
                else
                    ctxWarningLog("Source \"$sourceID\", channel \"$channel\" expired events older than configured $CONFIG_EVENT_MAX_RETAIN_PERIOD $duration are being dropped, consider a larger a faster reading interval.")
            } else {
                val ctxInfoLog = logger.getCtxInfoLog(className, "sourceDataStores")
                if (size != null)
                    ctxInfoLog("Source \"$sourceID\", channel \"$channel\" number of kept events is now again below maximum of $size values.")
                else
                    ctxInfoLog("Source \"$sourceID\", channel \"$channel\" no more expired events older than ${duration}are being dropped.")
            }
        }
    } else null


    // creates the client to communicate with the server the source is reading from
    private suspend fun createOpcuaClient(): OpcUaClient? {

        val log = logger.getCtxLoggers(className, "createServerClient")

        log.info("Creating client for source \"$sourceID\", on ${opcuaServerConfiguration.endPoint}")

        val securityPolicy = opcuaServerConfiguration.securityPolicy

        val predicateUserToken = when {

            (opcuaServerConfiguration.userCertificateConfiguration != null) -> {
                log.trace("Using user token type \"${UserTokenType.Certificate}\" as $CONFIG_USER_CERTIFICATE is set to select server endpoints")
                UserTokenType.Certificate
            }

            (opcuaServerConfiguration.username != null) -> {
                log.trace("Using user token type \"${UserTokenType.UserName}\" as $CONFIG_USERNAME is set to select server endpoints")
                UserTokenType.UserName
            }

            else -> {
                log.trace("Using user token type \"${UserTokenType.Anonymous}\" as no user token type, user certificate or username is configured, to select server endpoints")
                UserTokenType.Anonymous
            }
        }

        log.info("Fetching all available endpoints for server \"${opcuaServerConfiguration.endPoint}\", using user token type $predicateUserToken to select endpoint for OPCUA client")

        var predicateIndex = 0

        val predicate =
            { e: EndpointDescription ->

                log.trace("Evaluating endpoint: [$predicateIndex] ${e.asString()}")

                predicateIndex += 1

                securityPolicy.policy.uri == e.securityPolicyUri &&
                 //       (configuredSecurityMode == null || configuredSecurityMode.mode == e.securityMode) &&
                        Arrays.stream(e.userIdentityTokens)
                            .anyMatch { p: UserTokenPolicy ->
                                p.tokenType == predicateUserToken
                            }
            }


        // Milo 1.1.7 moved the connect timeout onto the pluggable transport config, and
        // OpcUaClient.create now takes a Consumer<OpcUaClientConfigBuilder> rather than a
        // function returning a built config.
        val transportConfig = Consumer { transportBuilder: OpcTcpClientTransportConfigBuilder ->
            transportBuilder.setConnectTimeout(UInteger.valueOf(opcuaServerConfiguration.connectTimeout.inWholeMilliseconds))
        }

        // build the client configuration
        val clientConfig = Consumer { configBuilder: OpcUaClientConfigBuilder ->
            configBuilder.setRequestTimeout(UInteger.valueOf(opcuaServerConfiguration.readTimeout.inWholeMilliseconds))
                .setEncodingLimits(messageLimits)
                .setupClientSecurity { dir ->
                    log.info("Certificate or CRL Update to directory $dir, reconnecting client")
                    resetClient()
                }
                .setupCertificateValidation { dir ->
                    log.info("Certificate or CRL Update to directory $dir, reconnecting client")
                    resetClient()
                }
        }

        // create the client
        val client = try {
            val host = URI(opcuaServerConfiguration.address).host
            OpcUaClient.create(
                opcuaServerConfiguration.endPoint,
                { endpoints: List<EndpointDescription> ->

                    if (endpoints.isEmpty())
                        log.error("No endpoints could be retrieved from server")
                    else
                        log.trace("${endpoints.size} available endpoints:\n\t${endpoints.mapIndexed { i, e -> i to e }.joinToString(separator = "\n\t") { "[${it.first}] ${it.second.asString()}" }}")

                    val selectedEndpoint = endpoints.stream()
                        .filter(predicate)
                        .map { endpoint -> EndpointUtil.updateUrl(endpoint, host) }
                        .findFirst()

                    if (selectedEndpoint.getOrNull() != null)
                        log.info("Using endpoint ${selectedEndpoint.get().asString()}")
                    else
                        log.error("No endpoint found for source \"$sourceID\" using user token type \"$predicateUserToken\" to select endpoint for OPCUA client")

                    selectedEndpoint

                }, transportConfig, clientConfig
            )

        } catch (e: UaException) {
            val cause = (if (e.cause != null) e.cause!!.message else e.message).toString()
            log.error("Error creating client for for source \"$sourceID\" at  ${opcuaServerConfiguration.endPoint}, $cause")
            null
        } catch (e: Exception) {
            log.errorEx("Error creating client for for source \"$sourceID\" at  ${opcuaServerConfiguration.endPoint}", e)
            null
        }

        // if the client was created connect to server
        return if (client != null) {
            try {
                val opcuaClient = client.connectAsync().await()
                log.info("Client for source \"$sourceID\" connected to ${opcuaServerConfiguration.endPoint}")
                metricsCollector?.put(protocolAdapterID, MetricsCollector.METRICS_CONNECTIONS, 1.0, MetricUnits.COUNT, dimensions)
                opcuaClient
            } catch (e: Exception) {
                log.error("Error connecting at ${opcuaServerConfiguration.endPoint} for source \"$sourceID\", $e")
                metricsCollector?.put(protocolAdapterID, MetricsCollector.METRICS_CONNECTION_ERRORS, 1.0, MetricUnits.COUNT, dimensions)
                null
            }
        } else null

    }

    private fun getUserCertificateAndKeyPair(): Pair<X509Certificate, KeyPair>? {

        val log = logger.getCtxLoggers(className, "getUserCertificateKeyPair")

        val userCertificateConfiguration = opcuaServerConfiguration.userCertificateConfiguration

        if (userCertificateConfiguration == null) return null


        if (userCertificateConfiguration.format == CertificateFormat.Unknown) {
            log.error("Type of user certificate could not be determined from filename of format configuration")
            return null
        }

        if (userCertificateConfiguration.format != userCertificateConfiguration.certificateFileFormatFromName()) {
            log.warning("User certificate type from filename does possibly not match with specified format")
        }

        log.trace("User certificate is of format ${userCertificateConfiguration.format}")

        val certificateHelper = when (userCertificateConfiguration.format) {
            CertificateFormat.Pkcs12 -> PkcsCertificateHelper(userCertificateConfiguration, logger)
            else -> CertificateHelper(userCertificateConfiguration, logger)
        }

        val (userCertificate, userKeyPair) = certificateHelper.getCertificateAndKeyPair()
        userCertificateExpiryChecker = startUserCertificateExpiryChecker(userCertificate)

        if (userCertificate == null || userKeyPair == null) return null
        log.trace("User certificate is $userCertificate")
        log.trace("User keypair is $userKeyPair")

        return userCertificate to userKeyPair

    }

    private val messageLimits: EncodingLimits
        get() = EncodingLimits(
            opcuaServerConfiguration.maxChunkSize,
            opcuaServerConfiguration.maxChunkCount,
            opcuaServerConfiguration.maxMessageSize,
            EncodingLimits.DEFAULT_MAX_RECURSION_DEPTH
        )

    private fun OpcUaClientConfigBuilder.setupClientSecurity(onUpdate: (String) -> Unit): OpcUaClientConfigBuilder {

        val log = logger.getCtxLoggers(className, "OpcUaClientConfigBuilder.setupClientSecurity")

        setupClientCertificateAuthentication()
        setupClientUsernamePasswordAuthentication(onUpdate)

        if (opcuaServerConfiguration.securityPolicy == OpcuaSecurityPolicy.None) return this

        val certificateConfiguration = opcuaServerConfiguration.certificateConfiguration
        if (certificateConfiguration == null) {
            log.error("A certificate must be configured for a server using security policy ${opcuaServerConfiguration.securityPolicy}")
            return this
        }

        if (certificateConfiguration.format == CertificateFormat.Unknown) {
            log.error("Type of certificate could not be determined from filename of format configuration")
            return this
        }

        if (certificateConfiguration.format != certificateConfiguration.certificateFileFormatFromName()) {
            log.warning("WARNING certificate type from filename does possibly not match with specified format")
        }

        log.trace("Certificate is of format ${certificateConfiguration.format}")
        val certificateHelper = when (certificateConfiguration.format) {
            CertificateFormat.Pkcs12 -> PkcsCertificateHelper(certificateConfiguration, logger)
            else -> CertificateHelper(certificateConfiguration, logger)
        }

        val (certificate, keyPair) = certificateHelper.getCertificateAndKeyPair()
        certificateExpiryChecker = startCertificateExpiryChecker(certificate)

        if (certificate == null) return this
        log.trace("Certificate is $certificate")
        this.setCertificate(certificate)

        if (keyPair == null) return this
        this.setKeyPair(keyPair)


        val uri = certificate.subjectAlternativeApplicationUri
        if (uri == null) {
            log.warning("Application URI is not set in certificate")
        } else {
            log.trace("Application URI set to $uri")
            this.setApplicationUri(uri.toASCIIString())
        }

        val applicationName = uri?.schemeSpecificPart
        if (uri == null) {
            log.warning("Application is not set in certificate")
        } else {
            val localizedApplicationName = LocalizedText(applicationName)
            log.trace("Application name set to $localizedApplicationName")
            this.setApplicationName(localizedApplicationName)
        }

        return this
    }

    private fun OpcUaClientConfigBuilder.setupClientUsernamePasswordAuthentication(onUpdate: (String) -> Unit) {
        val log = logger.getCtxLoggers(className, "OpcUaClientConfigBuilder.setupUsernamePasswordAuthentication")
        try {
            if (opcuaServerConfiguration.username != null && opcuaServerConfiguration.password != null) {
                val certificateValidationConfiguration = opcuaServerConfiguration.certificateValidationConfiguration
                if (certificateValidationConfiguration != null) {
                    val tlm = ClientTrustListManager(certificateValidationConfiguration.directory, logger) { dir ->
                        log.info("Certificate or CLR update in directory \"$dir\"")
                        onUpdate(dir.toString())
                    }
                    if (tlm.trustedCrls.isEmpty()) {
                        log.warning("There are no trusted certificates in ${tlm.trustedCertificatesDirectory}, when connection for the first time to a server fails with an error message \"the trustAnchors parameter must be non-empty\" move the rejected certificate for that server from  ${tlm.rejectedPath} into ${tlm.trustedCertificatesDirectory}")
                    }
                    val certificateValidator = DefaultClientCertificateValidator(tlm, tlm)
                    this.setIdentityProvider(UsernameProvider(opcuaServerConfiguration.username, opcuaServerConfiguration.password, certificateValidator))
                } else {
                    this.setIdentityProvider(UsernameProvider(opcuaServerConfiguration.username, opcuaServerConfiguration.password))
                }
            }
        } catch (e: Exception) {
            log.errorEx("Error setting username and password for server of source  \"$sourceID\"", e)
        }
    }

    private fun OpcUaClientConfigBuilder.setupClientCertificateAuthentication() {
        val log = logger.getCtxLoggers(className, "OpcUaClientConfigBuilder.setupClientCertificateAuthentication")
        try {
            if (opcuaServerConfiguration.userCertificateConfiguration != null) {
                val userCertificateAndKeyPair = getUserCertificateAndKeyPair()
                if (userCertificateAndKeyPair != null) {
                    this.setIdentityProvider(X509IdentityProvider(userCertificateAndKeyPair.first, userCertificateAndKeyPair.second.private))
                }
            }
        } catch (e: Exception) {
            log.errorEx("Error setting client certificate authentication server of source  \"$sourceID\"", e)
        }
    }

    private fun startCertificateExpiryChecker(certificate: X509Certificate?): Job? =
        startCertificateChecker("OPCUA security", certificate, opcuaServerConfiguration.certificateConfiguration, certificateExpiryChecker)

    private fun startUserCertificateExpiryChecker(certificate: X509Certificate?): Job? =
        startCertificateChecker("User Authentication", certificate, opcuaServerConfiguration.userCertificateConfiguration, userCertificateExpiryChecker)


    private fun startCertificateChecker(checkedCertificateType: String, certificate: X509Certificate?, certificateConfiguration: CertificateConfiguration?, checkerJob: Job?): Job? {

        if (certificate == null || certificateConfiguration == null || certificateConfiguration.expirationWarningPeriod <= 0) {
            checkerJob?.cancel()
            return null
        }
        val expirationWarningPeriod = certificateConfiguration.expirationWarningPeriod


        return sourceScope.launch("OPCUA Certificate Expiry Watcher for $checkedCertificateType certificate", Dispatchers.IO) {

            try {
                while (isActive) {

                    val now = systemDateUTC()
                    if (certificate.notAfter <= now.add(Period.ofDays(expirationWarningPeriod * -1))) {
                        val ctxLog = logger.getCtxLoggers(className, "Check $checkedCertificateType Certificate Expiration")
                        if (certificate.notAfter >= now) {
                            ctxLog.error("Certificate expired at ${certificate.notAfter}")
                        } else {
                            val daysBetween = ChronoUnit.DAYS.between(certificate.notAfter.toInstant(), now.toInstant())
                            ctxLog.warning("$checkedCertificateType certificate $certificate will expire in $daysBetween days at ${certificate.notAfter}")
                        }
                    }
                    DateTime.delayUntilNextMidnightUTC()
                }
            } catch (e: Exception) {
                logger.getCtxErrorLogEx(className, "startCertificateExpiryChecker")("Error while checking $checkedCertificateType certificate expiration", e)
            }
        }

    }

    private fun OpcUaClientConfigBuilder.setupCertificateValidation(onUpdate: (String) -> Unit): OpcUaClientConfigBuilder {
        if (opcuaServerConfiguration.securityPolicy == OpcuaSecurityPolicy.None) return this

        val validationConfiguration = opcuaServerConfiguration.certificateValidationConfiguration ?: return this
        if (!validationConfiguration.active) return this

        val log = logger.getCtxLoggers(className, "setupCertificateValidation")

        if (!Path(validationConfiguration.directory).exists()) {
            log.error("Directory ${validationConfiguration.directory} does not exist")
            return this
        }

        log.trace("Loading certificated and CLRs from directory ${validationConfiguration.directory}")
        trustManager = ClientTrustListManager(validationConfiguration.directory, logger) { dir ->
            log.info("Certificate or CLR update in directory \"$dir\"")
            onUpdate(dir.toString())
        }

        if (trustManager?.trustedCertificates?.isEmpty() == true) {
            log.warning("No trusted certificates in trusted certificates directory ${trustManager!!.trustedCertificatesDirectory}")
            trustManager?.close()
            trustManager = null
            return this
        }

        log.trace("Certificate validation options ${validationConfiguration.configurationOptions.options}")
        val certificateValidator = DefaultClientCertificateValidator(trustManager, validationConfiguration.configurationOptions.options, trustManager)
        this.setCertificateValidator(certificateValidator)
        return this

    }


    private fun createSubscriptionWithMonitoredItems(client: OpcUaClient): OpcUaSubscription? {

        val sourceNeedsSubscription = inSubscriptionReadingMode || anyEventNodes
        if (!sourceNeedsSubscription) return null

        // get the smallest interval for the source from all schedules in which it is used
        val minIntervalUsedInSchedulesForSource: Duration =
            configuration.schedules
                .filter { sourceID in it.activeSourceIDs }
                .minByOrNull { schedule -> schedule.interval }?.interval ?: DEFAULT_INTERVAL

        val configuredSourceInterval = sourceConfiguration.subscribePublishingInterval

        // create new subscription
        val connectTimeOut = opcuaServerConfiguration.connectTimeout.inWholeMilliseconds
        val createdSubscription = run {
            val interval = (configuredSourceInterval ?: minIntervalUsedInSchedulesForSource).toDouble(DurationUnit.MILLISECONDS)
            runBlocking {
                withTimeoutOrNull(connectTimeOut) {
                    // milo 1.1.7: a subscription is constructed locally then created on the server.
                    // createAsync() parks no thread, unlike the old future.get().
                    val newSubscription = OpcUaSubscription(client, interval)
                    newSubscription.setSubscriptionListener(
                        SubscriptionListener(
                            logger,
                            fnOnConnectionLost = { resetClient(0) },
                            fnOnSubscriptionTransferFailed = { _, _ -> resetClient(0) })
                    )
                    newSubscription.createAsync().await()
                    newSubscription
                }
            }
        }

        if (createdSubscription != null) {
            monitoredItems = createMonitoredItems(createdSubscription)
        }

        return createdSubscription
    }

    private val dataNodeMonitoredItemRequests by lazy {
        sequence {

            if (!inSubscriptionReadingMode) return@sequence

            val dataNodes = sourceNodes.filter { it.value.isDataNode }

            dataNodes.values.forEach { node: OpcuaNodeData ->

                // milo 1.1.7 assigns client handles itself; the node is carried on the item's
                // userObject instead of a handle -> node map maintained here.
                val item = OpcUaMonitoredItem(node.readValueId, MonitoringMode.Reporting)
                item.setSamplingInterval(-1.0)
                item.setQueueSize(uint(1))
                item.setDiscardOldest(true)
                buildDataChangeFilter(sourceConfiguration.channels[node.channelID]?.nodeChangeFilter)?.let { item.setFilter(it) }
                item.setUserObject(node)
                item.setDataValueListener(onSubscribedDataReceived())
                yield(item)
            }
        }
    }


    private fun buildDataChangeFilter(nodeChangeFilter: OpcuaNodeChangeFilter?) =
        if (nodeChangeFilter == null) null
        else {
            val deadBandType = UInteger.valueOf(
                when (nodeChangeFilter.filterType) {
                    OpcuaChangeFilterType.ABSOLUTE -> DeadbandType.Absolute
                    OpcuaChangeFilterType.PERCENT -> DeadbandType.Percent
                }.value
            )
            val filterValue = nodeChangeFilter.filterValue
            // milo 1.1.7 setFilter takes a typed MonitoringFilter, so no ExtensionObject
            // encoding (and no EncodingContext) is needed here any more.
            DataChangeFilter(DataChangeTrigger.StatusValue, deadBandType, filterValue)
        }

    private val eventNodeMonitoredItemRequests by lazy {
        sequence {

            val eventNodes = sourceNodes.filter { it.value.isEventNode }

            if (client == null) return@sequence

            val filterHelper = FilterHelper(client!!, sourceID, configuration, logger)

            eventNodes.values.forEach { node ->
                if (node.eventType != null) {
                    val eventFilter = filterHelper[node.eventType]
                    val eventSamplingInterval = (node.nodeEventSampleInterval ?: sourceConfiguration.eventSamplingInterval).toDouble()

                    val item = OpcUaMonitoredItem(node.readValueId, MonitoringMode.Reporting)
                    item.setSamplingInterval(eventSamplingInterval)
                    item.setQueueSize(uint(sourceConfiguration.eventQueueSize))
                    item.setDiscardOldest(true)
                    eventFilter?.let { item.setFilter(it) }
                    item.setUserObject(node)
                    item.setEventValueListener(onMonitoredEventReceived())
                    yield(item)
                }
            }
        }
    }

    private fun createMonitoredItems(subscription: OpcUaSubscription): MutableList<OpcUaMonitoredItem> {

        val log = logger.getCtxLoggers(className, "createMonitoredItems")

        val items = (dataNodeMonitoredItemRequests + eventNodeMonitoredItemRequests).toList()

        monitoredItems?.clear()
        monitoredItems = mutableListOf()

        // milo 1.1.7 partitions the service calls itself against the server's operation limits,
        // so the previous manual windowing by batchSize is expressed as a limit instead.
        subscription.setMaxMonitoredItemsPerCall(uint(batchSize))
        subscription.addMonitoredItems(items)
        try {
            subscription.synchronizeMonitoredItems()
        } catch (e: MonitoredItemSynchronizationException) {
            log.warning("Not all monitored items could be created for source \"$sourceID\", $e")
        }

        // per-item outcome now comes back on the item itself rather than via a creation callback
        items.forEach { item ->
            val node = item.userObject.getOrNull() as? OpcuaNodeData
            val createResult = item.createResult.getOrNull()
            if (createResult == null || !createResult.isGood) {
                log.error(
                    "Error creating subscription for source \"$sourceID\" " +
                            "node \"${node?.channelID ?: "unknown channel"}\" " +
                            "(${item.readValueId.nodeId}), $createResult "
                )
            } else {
                monitoredItems!!.add(item)
            }
        }

        return monitoredItems as MutableList<OpcUaMonitoredItem>
    }


    // returns all nodes to read in polling mode for a source
    private fun nodesToReadInPollingMode(channels: List<String>?): Sequence<Pair<String, ReadValueId>> = sequence {

        val channelsToRead = sourceConfiguration.channels.filter { (channelID, channel) ->
            channel.isDataNode && (channels == null || channelID in channels)
        }.keys

        channelsToRead.forEach { ch ->
            val readNode = sourceNodes[ch]
            if (readNode != null) {
                // channel, ReadNodeId pairs
                yield(ch to readNode.readValueId)
            }
        }
    }

    // returns the nodes to read in windowed batches
    private fun nodesToReadInPollingModeBatches(channels: List<String>?): Sequence<Map<String, ReadValueId>> = sequence {

        // return batches of nodes
        nodesToReadInPollingMode(channels)
            .windowed(size = batchSize, step = batchSize, partialWindows = true).forEach { n ->
                yield(n.associate { it.first to it.second })
            }
    }

    // milo 1.1.7 DataValueListener: no EncodingContext parameter, and the node travels on
    // the item's userObject rather than being looked up by client handle.
    private fun onSubscribedDataReceived(): OpcUaMonitoredItem.DataValueListener =
        OpcUaMonitoredItem.DataValueListener { item: OpcUaMonitoredItem, value: DataValue ->

            val log = logger.getCtxLoggers(className, "onSubscribedDataReceived")
            try {
                if (value.statusCode.isGood) {
                    val nativeValue = OpcuaDataTypesConverter(encodingContext).asNativeValue(value.value)

                    try {
                        val node = item.userObject.getOrNull() as? OpcuaNodeData

                        if (node != null) {
                            log.trace("Received subscription data for source \"$sourceID\", \"${node.channelID}\"")


                            dataValueChangesStore?.add(node.channelID, ChannelReadValue(nativeValue, value.sourceTime?.javaInstant))

                        } else {
                            log.warning("Received subscription data for source \"$sourceID\" but the monitored item carried no node")
                        }
                    } catch (e: Exception) {
                        logger.getCtxLoggers(className, "onSubscribedNodeData").errorEx("Error processing subscription data for source \"$sourceID\"", e)
                    }
                }

            } catch (e: Exception) {
                val errorLogEx = logger.getCtxErrorLogEx(className, "onSubscribedDataReceived")
                errorLogEx("Error processing subscription data source \"$sourceID\", node \"${item.readValueId}\" (${item.createResult.getOrNull()})", e)
            }

        }

    // milo 1.1.7 EventValueListener: no EncodingContext parameter, node via userObject.
    private fun onMonitoredEventReceived(): OpcUaMonitoredItem.EventValueListener =
        OpcUaMonitoredItem.EventValueListener { item: OpcUaMonitoredItem, eventPropertyVariantValues: Array<Variant> ->

            if (eventsHelper != null) {
                val log = logger.getCtxLoggers(className, "onMonitoredEventReceived")
                try {

                    val node = item.userObject.getOrNull() as? OpcuaNodeData
                    if ((item.createResult.getOrNull() ?: StatusCode.GOOD).isGood) {
                        if (node != null) {

                            val properties = node.eventProperties ?: eventsHelper.findEvent(NodeIds.BaseEventType)?.properties

                            if (properties != null) {

                                val propertiesValuesMap = eventsHelper.variantPropertiesToMap(eventPropertyVariantValues, properties, encodingContext)

                                log.trace("Received event data for source \"$sourceID\", \"${node.channelID}\"")
                                eventStore?.add(node.channelID, propertiesValuesMap)
                            }

                        } else {
                            val nodeChannelID = "unknown channel"
                            val errorLog = logger.getCtxErrorLog(className, "onMonitoredEventReceived")
                            errorLog("Error status on monitored event item for source \"$sourceID\", node \"$nodeChannelID\" (${item.readValueId}), ${item.createResult.getOrNull()}")
                        }
                    }

                } catch (e: Exception) {
                    val errorLogEx = logger.getCtxErrorLogEx(className, "onMonitoredEventReceived")
                    errorLogEx("Error processing monitored event item for source \"$sourceID\", node \"${item.readValueId}\" (${item.createResult.getOrNull()})", e)
                }
            }
        }

    private var lock = ReentrantLock()

    private fun resetClient(waitFor: Long = 0) {

        if (lock.isHeldByCurrentThread || !lock.tryLock()) return

        try {

            if (isClosing) return

            isClosing = true

            trustManager?.close()
            trustManager = null

            if (!monitoredItems.isNullOrEmpty() && subscription != null) {
                subscription?.removeMonitoredItems(monitoredItems!!)
                try {
                    subscription?.synchronizeMonitoredItems()
                } catch (e: MonitoredItemSynchronizationException) {
                    logger.getCtxLoggers(className, "close").warning("Not all monitored items could be deleted, $e")
                }
            }

            sourceServerFault = null

            subscription = null

            monitoredItems?.clear()
            monitoredItems = null

            _opcuaClient?.disconnect()
            _opcuaClient = null
            sourceServerFault = null
            pauseWaitUntil = systemDateTime().plusMillis(waitFor)
        } finally {
            isClosing = false
            lock.unlock()
        }
    }


    fun close() {
        connectionWatchdog?.cancel()
        certificateExpiryChecker?.cancel()
        userCertificateExpiryChecker?.cancel()
        _opcuaClient?.disconnect()
    }

    // get the flow to read the source values, the flow depends on the mode the adapter is using
    private fun readSourceValues(channels: List<String>?): List<Pair<String, ChannelReadValue>> {

        val events = (eventStore?.read(channels) ?: emptyList()).map { it.first to ChannelReadValue(it.second) }

        val data = if (configuration.sources[sourceID]!!.readingMode == OpcuaSourceReadingMode.SUBSCRIPTION)
            serverReadsInSubscriptionMode(channels)
        else
            serverReadsInPollingMode(channels)

        return data + events
    }


    private fun processGoodValue(
        channelID: String,
        value: ChannelReadValue,
        serverTimestamp: Instant?
    ): ChannelReadValue {

        // don't set value timestamp if it is equal to server timestamp to reduce IPC data flow, the receiving side will add the timestamps
        val valueTimestamp = if (value.timestamp != serverTimestamp) value.timestamp else null


        val nativeValue = applyChannelValueSelector(channelID, value.value)

        return ChannelReadValue(nativeValue, valueTimestamp)
    }

    // applies selector for node to select fields from structured types
    private fun applyChannelValueSelector(channelID: String, nativeValue: Any?): Any? {

        val channel = sourceConfiguration.channels[channelID]
        val selector = channel?.selector
        return if (selector != null) {
            val log = logger.getCtxLoggers(className, "applyChannelValueSelector")
            try {
                val selected = selector.search(nativeValue)
                if (selected == null) {
                    log.warning("Applying selector \"${channel.selectorStr}\" for source \"$sourceID\", node \"$channelID\" on value \"$nativeValue\" returns null")
                } else {
                    log.trace("Applying selector \"${channel.selectorStr}\" for source \"$sourceID\", node \"$channelID\" on value \"$nativeValue\" returns \"$selected\"")
                }
                selected
            } catch (e: java.lang.Exception) {
                log.error("Error applying selector \"${channel.selectorStr}\" for source \"$sourceID\", node \"$channelID\", ${e.message}")
            }
        } else nativeValue
    }

    suspend fun read(channels: List<String>?): SourceReadResult {

        if (client == null || isClosing) return SourceReadSuccess(emptyMap(), systemDateTime())

        val log = logger.getCtxLoggers(className, "read")

        log.trace("Reading from source \"$sourceID\"")

        val sourceInSubscriptionMode = configuration.sources[sourceID]?.readingMode == OpcuaSourceReadingMode.SUBSCRIPTION
        val serverTimestamp: Instant? = if (sourceInSubscriptionMode) systemDateTime() else null

        var errorResult: SourceReadResult? = null
        val values = mutableMapOf<String, ChannelReadValue>()

        try {

            val duration = measureTime {

                // collect and process al read source values
                readSourceValues(channels).toList().forEach { (channelID, value) ->
                    values[channelID] = processGoodValue(channelID, value, serverTimestamp)
                }

                // test if a fault was stored by the fault handler used for the connection with the server of the source
                if (sourceServerFault != null) {
                    throw java.lang.Exception(sourceServerFault!!.responseHeader.serviceResult.toString())
                }
            }

            createMetrics(protocolAdapterID, duration.inWholeMilliseconds.toDouble(), values)

        } catch (e: Throwable) {

            // if (!isClosing) resetClient(1000)

            metricsCollector?.put(protocolAdapterID, MetricsCollector.METRICS_READ_ERRORS, 1.0, MetricUnits.COUNT, dimensions)
            errorResult = if (e is TimeoutException) {
                SourceReadError("Timeout reading  source $sourceID from server ${opcuaServerConfiguration.endPoint} within ${opcuaServerConfiguration.readTimeout}")
            } else {
                if (e.isJobCancellationException)
                    SourceReadSuccess(emptyMap(), systemDateTime())
                else
                    SourceReadError("Error reading source $sourceID from server (${opcuaServerConfiguration.endPoint}), ${e.message}")
            }
        }

        return errorResult ?: SourceReadSuccess(values, serverTimestamp)
    }


    private fun createMetrics(
        protocolAdapterID: String,
        readDurationInMillis: Double,
        values: MutableMap<String, ChannelReadValue>
    ) {
        metricsCollector?.put(
            protocolAdapterID,
            metricsCollector.buildValueDataPoint(protocolAdapterID, MetricsCollector.METRICS_READS, 1.0, MetricUnits.COUNT, dimensions),
            metricsCollector.buildValueDataPoint(
                protocolAdapterID,
                MetricsCollector.METRICS_READ_DURATION,
                readDurationInMillis,
                MetricUnits.MILLISECONDS,
                dimensions
            ),
            metricsCollector.buildValueDataPoint(
                protocolAdapterID,
                MetricsCollector.METRICS_VALUES_READ,
                values.size.toDouble(),
                MetricUnits.COUNT,
                dimensions
            ),
            metricsCollector.buildValueDataPoint(protocolAdapterID, MetricsCollector.METRICS_READ_SUCCESS, 1.0, MetricUnits.COUNT, dimensions)
        )
    }

    private fun serverReadsInSubscriptionMode(channels: List<String>?): List<Pair<String, ChannelReadValue>> {
        var values: List<Pair<String, ChannelReadValue>>
        val duration = measureTime {
            values = dataValueChangesStore?.read(channels)?.map { it.first to it.second as ChannelReadValue } ?: emptyList()
        }
        if (values.isNotEmpty()) logger.getCtxTraceLog(className, "read")("Reading ${values.size} from store took $duration")
        return values

    }

    private fun serverReadsInPollingMode(channels: List<String>?): List<Pair<String, ChannelReadValue>> {

        if (client == null) return emptyList()

        val log = logger.getCtxLoggers(className, "read")

        // partition nodes in smaller batches
        return sequence {


            val opcuaDataTypesConverter = OpcuaDataTypesConverter(client?.staticEncodingContext)

            nodesToReadInPollingModeBatches(channels).forEach { batchOfNodes ->

                // read from the server and wait for result
                try {
                    val response: ReadResponse = client!!.read(0.0, TimestampsToReturn.Both, batchOfNodes.values.toMutableList())

                    if (!response.responseHeader.serviceResult.isGood) {
                        resetClient(0)
                        return@sequence
                    }

                    // map the read values to the nodes
                    batchOfNodes.keys.mapIndexed { i, s ->
                        val value = response.results!![i]
                        if (value.statusCode.isGood) {
                            val nativeValue = opcuaDataTypesConverter.asNativeValue(response.results!![i].value)
                            if (nativeValue != null) {
                                yield(s to ChannelReadValue(nativeValue, value.sourceTime?.javaInstant))
                            } else {
                                log.trace("Value for channel \"$s\" from source \"$sourceID\" has status ${value.statusCode} but was not converted, variant value is ${response.results!![i].value.value?.let { "${it::class.java.name}: $it" } ?: "null"}")
                            }
                        } else {
                            log.error("Error reading value for channel \"$s\" from source \"$sourceID\", ${value.statusCode}")
                        }
                    }

                } catch (e: Exception) {
                    throw ProtocolAdapterException("Error reading from source \"$sourceID\", $e")
                }
            }
        }.toList()
    }

    companion object {
        val DEFAULT_INTERVAL = 1.toDuration(DurationUnit.SECONDS)
    }

}

