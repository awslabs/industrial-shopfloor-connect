
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.system

fun isWindowsSystem() = System.getProperty("os.name").startsWith("Windows")