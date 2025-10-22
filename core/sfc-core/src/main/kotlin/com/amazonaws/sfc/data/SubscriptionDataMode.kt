
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.data

import com.google.gson.annotations.SerializedName

enum class SubscriptionDataMode {
    @SerializedName("ChangedData")
    CHANGES_ONLY,

    @SerializedName("AllData")
    ALL_DATA
}