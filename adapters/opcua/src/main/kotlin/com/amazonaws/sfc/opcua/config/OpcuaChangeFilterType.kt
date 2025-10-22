
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.opcua.config

import com.google.gson.annotations.SerializedName

enum class OpcuaChangeFilterType {

    @SerializedName("Absolute")
    ABSOLUTE,

    @SerializedName("Percent")
    PERCENT,

}