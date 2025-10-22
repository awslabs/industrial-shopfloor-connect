// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

package com.amazonaws.sfc.awssitewise.config

import com.google.gson.annotations.SerializedName

enum class AssetTimestamp {


    @SerializedName("System")
    SYSTEM,

    @SerializedName("Source")
    SOURCE,

    @SerializedName("Channel")
    CHANNEL,

    @SerializedName("Schedule")
    SCHEDULE;
}
