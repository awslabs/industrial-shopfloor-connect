
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.config

import com.amazonaws.sfc.metrics.MetricsConfiguration
import com.google.gson.annotations.SerializedName

open class SourceAdapterBaseConfiguration : BaseConfiguration() {
    @SerializedName(MetricsConfiguration.CONFIG_METRICS)
    private val _metrics: MetricsConfiguration? = null

    val metrics: MetricsConfiguration?
        get() = _metrics

    val isCollectingMetrics: Boolean
        get() = ((_metrics != null) && (_metrics.isCollectingMetrics))
}