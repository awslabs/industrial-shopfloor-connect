// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//

package com.amazonaws.sfc.opcuatarget

import org.eclipse.milo.opcua.stack.core.NodeIds
import org.eclipse.milo.opcua.stack.core.StatusCodes
import org.eclipse.milo.opcua.stack.core.UaException
import org.eclipse.milo.opcua.stack.core.security.CertificateFactory
import org.eclipse.milo.opcua.stack.core.security.CertificateGroup
import org.eclipse.milo.opcua.stack.core.security.CertificateValidator
import org.eclipse.milo.opcua.stack.core.security.TrustListManager
import org.eclipse.milo.opcua.stack.core.types.builtin.ByteString
import org.eclipse.milo.opcua.stack.core.types.builtin.NodeId
import org.bouncycastle.asn1.x500.X500Name
import java.security.KeyPair
import java.security.cert.X509Certificate
import java.util.Optional

/**
 * Adapts SFC's existing certificate handling onto milo 1.1.7's [CertificateGroup] interface.
 *
 * Up to milo 0.6.x the server was configured by handing the trust list manager, certificate
 * validator and key pair directly to `OpcUaServerConfigBuilder`. Those setters are gone in 1.1.7:
 * the server now reaches all of it through `CertificateManager` -> `CertificateGroup`, and milo
 * ships no default implementation of the latter.
 *
 * SFC provisions certificates out of band (from configured files, watched directories), so the
 * server-side certificate *management* operations - issuing key pairs, generating CSRs, replacing
 * the certificate at runtime via the OPC UA ServerConfiguration object - are deliberately not
 * supported and report Bad_NotSupported rather than silently doing nothing.
 */
class SfcServerCertificateGroup(
    private val trustListManager: TrustListManager,
    private val certificateValidator: CertificateValidator,
    private val keyPair: KeyPair?,
    private val certificateChain: Array<X509Certificate>?
) : CertificateGroup {

    private val groupId: NodeId = NodeIds.ServerConfiguration_CertificateGroups_DefaultApplicationGroup
    private val certificateTypeId: NodeId = NodeIds.RsaSha256ApplicationCertificateType

    override fun getCertificateGroupId(): NodeId = groupId

    override fun getSupportedCertificateTypeIds(): List<NodeId> = listOf(certificateTypeId)

    override fun getTrustListManager(): TrustListManager = trustListManager

    override fun getCertificateValidator(): CertificateValidator = certificateValidator

    override fun getCertificateEntries(): List<CertificateGroup.Entry> =
        if (certificateChain == null) emptyList()
        else listOf(CertificateGroup.Entry(groupId, certificateTypeId, certificateChain))

    override fun getKeyPair(certificateTypeId: NodeId): Optional<KeyPair> =
        if (certificateTypeId == this.certificateTypeId) Optional.ofNullable(keyPair) else Optional.empty()

    override fun getCertificateChain(certificateTypeId: NodeId): Optional<Array<X509Certificate>> =
        if (certificateTypeId == this.certificateTypeId) Optional.ofNullable(certificateChain) else Optional.empty()

    // SFC certificates are provisioned outside the server; runtime replacement is not offered.
    override fun updateCertificate(
        certificateTypeId: NodeId,
        keyPair: KeyPair,
        certificateChain: Array<X509Certificate>
    ) {
        throw UaException(StatusCodes.Bad_NotSupported, "SFC manages OPC UA server certificates through its configuration, not through the server's ServerConfiguration object")
    }

    override fun getCertificateFactory(): CertificateFactory = UnsupportedCertificateFactory

    private object UnsupportedCertificateFactory : CertificateFactory {
        private fun unsupported(what: String): Nothing =
            throw UaException(StatusCodes.Bad_NotSupported, "SFC does not support $what; provision certificates through the SFC configuration instead")

        override fun createKeyPair(certificateTypeId: NodeId): KeyPair = unsupported("server-side key pair generation")

        override fun createCertificateChain(certificateTypeId: NodeId, keyPair: KeyPair): Array<X509Certificate> =
            unsupported("server-side certificate generation")

        override fun createSigningRequest(
            certificateTypeId: NodeId,
            keyPair: KeyPair,
            subjectName: X500Name,
            applicationUri: String,
            domainNames: List<String>,
            ipAddresses: List<String>
        ): ByteString = unsupported("certificate signing requests")
    }
}
