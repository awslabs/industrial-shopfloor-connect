// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//

package com.amazonaws.sfc.opcuatarget

import com.amazonaws.sfc.log.Logger
import org.eclipse.milo.opcua.stack.core.UaException
import org.eclipse.milo.opcua.stack.core.security.CertificateQuarantine
import org.eclipse.milo.opcua.stack.core.security.DefaultServerCertificateValidator
import org.eclipse.milo.opcua.stack.core.security.TrustListManager
import org.eclipse.milo.opcua.stack.core.util.validation.CertificateValidationUtil
import org.eclipse.milo.opcua.stack.core.util.validation.ValidationCheck
import java.security.cert.X509Certificate

class ServerCertificateValidator(
    trustListManager: TrustListManager,
    private val validationChecks: Set<ValidationCheck>,
    certificateQuarantine: CertificateQuarantine,
    private val logger: Logger
) : DefaultServerCertificateValidator(trustListManager, validationChecks, certificateQuarantine) {

    private val className = this::class.java.name

    // milo 1.1.7 signature: validateCertificateChain(chain, applicationUri, validHostnames)
    override fun validateCertificateChain(
        certificateChain: MutableList<X509Certificate>,
        applicationUri: String?,
        validHostNames: Array<out String?>
    ) {
        super.validateCertificateChain(certificateChain, applicationUri, validHostNames)

        val certificate = certificateChain[0]
        try {
            if (validationChecks.contains(ValidationCheck.APPLICATION_URI)) {
                CertificateValidationUtil.checkApplicationUri(certificate, applicationUri)
            }
        } catch (e: UaException) {
            logger.getCtxWarningLog(className, "validateCertificateChain")("Application URI check failed: $applicationUri != ${CertificateValidationUtil.getSubjectAltNameUri(certificate)}, UAException : ${e.message}")
            throw e
        }
    }
}
