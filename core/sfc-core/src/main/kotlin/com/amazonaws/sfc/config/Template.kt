// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

package com.amazonaws.sfc.config

typealias TemplatesConfiguration = Map<String, Any>

class Template(val name: String, val values: Map<String, String>) {

    override fun toString(): String {
        return "Template(name='$name', values=$values)"
    }
}