
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.ipc

import kotlin.time.Duration

// Interface for IPC client for reading metrics
interface IpcMetricsReaderClient : IpcClient {
    suspend fun readMetrics(interval: Duration): kotlinx.coroutines.flow.Flow<Metrics.MetricsDataMessage>
}