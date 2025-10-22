
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.service

enum class ServerConnectionType {
    Unknown,
    PlainText,
    ServerSideTLS,
    MutualTLS;

    companion object {
        val validValues
            get() = ServerConnectionType.entries.toTypedArray().copyOfRange(1, 4).map { it.toString() }
    }
}