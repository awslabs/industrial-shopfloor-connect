
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.data

@FunctionalInterface
interface TargetResultHandler {
    fun handleResult(targetResult: TargetResult)
    val returnedData: ResulHandlerReturnedData?

}