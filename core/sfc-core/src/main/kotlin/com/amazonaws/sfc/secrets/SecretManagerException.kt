
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.secrets

open class SecretManagerException : Exception {
    constructor(err: String?) : super(err)
    constructor(err: Exception?) : super(err)
    constructor(err: String?, e: Exception?) : super(err, e)
}