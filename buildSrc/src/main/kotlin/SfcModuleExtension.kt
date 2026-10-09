// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import org.gradle.api.provider.MapProperty
import org.gradle.api.provider.Property

/**
 * The only parts of a module's BuildConfig that are genuinely module-specific.
 */
interface SfcModuleExtension {

    /**
     * Sub-package of com.amazonaws.sfc that BuildConfig is generated into. Deliberately has no
     * convention: for 14 of the modules it differs from the project name (aws-kinesis-firehose-target
     * -> awsfirehose, store-forward-target -> storeforward, ...) and it has to match the package of
     * the class that reads it.
     */
    val buildConfigPackage: Property<String>

    /** Name of the generated version constant. Defaults to VERSION. */
    val versionConstant: Property<String>

    /** Extra NAME=value pairs appended to BuildConfig.toString(). */
    val extraVersions: MapProperty<String, String>
}
