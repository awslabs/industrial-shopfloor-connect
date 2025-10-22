// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//

package com.amazonaws.sfc.opcuatarget.config


interface ParentNode {
    val path: String
    val folders : FolderNodesConfigurationMap?
    val variables : VariableNodeMap?
}