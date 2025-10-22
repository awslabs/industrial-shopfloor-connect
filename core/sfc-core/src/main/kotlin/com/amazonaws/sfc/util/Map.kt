
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

package com.amazonaws.sfc.util

import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentMap

public fun <K, V> List<Pair<K, V>>.toConcurrentMap(): ConcurrentMap<K, V> {
        val theMap = ConcurrentHashMap<K, V>(size)
        this.forEach {(k,v) ->
            theMap[k] = v
        }
        return theMap
    }
