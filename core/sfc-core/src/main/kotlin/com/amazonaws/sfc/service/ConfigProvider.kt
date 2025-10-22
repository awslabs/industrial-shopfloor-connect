
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.service

import kotlinx.coroutines.channels.Channel

interface ConfigProvider {
    val configuration: Channel<String>?
}