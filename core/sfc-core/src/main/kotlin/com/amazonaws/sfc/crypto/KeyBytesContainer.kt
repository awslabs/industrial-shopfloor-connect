
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.crypto

class KeyBytesContainer(private val privateKeyBytes: ByteArray) : KeyContainer() {
    override val scheme: String = SecurityService.DefaultCryptoKeyProvider.SUPPORT_KEY_TYPE
    override val keyBytes: ByteArray = privateKeyBytes
    override fun toString(): String = "${privateKeyBytes.size} secret bytes"
}