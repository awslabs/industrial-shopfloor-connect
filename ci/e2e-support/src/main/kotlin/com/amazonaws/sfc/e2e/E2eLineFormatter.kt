// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

package com.amazonaws.sfc.e2e

import com.amazonaws.sfc.data.TargetData
import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.targets.TargetFormatter

/**
 * A deterministic custom target formatter for the formatter extension-point cases.
 *
 * The example formatter in examples/custom-target-formatter prefixes every record with the current time,
 * which no assertion can predict. This one renders each record as one line whose content depends only on
 * the record:
 *
 *     E2E|<marker>|<schedule>|<source>.<channel>=<value>;...\n
 *
 * Channels are sorted by source and channel name so the line is stable across modes (channel maps cross a
 * protobuf map in IPC mode, whose iteration order is not guaranteed). The configured string is echoed as a
 * leading field when non-empty, which lets a case prove the configuration reaches the formatter.
 */
@Suppress("unused")
class E2eLineFormatter(configuration: String, logger: Logger) : TargetFormatter(configuration, logger) {

    override fun itemPayloadSize(targetData: TargetData): Int = line(targetData).toByteArray().size

    override fun apply(targetData: List<TargetData>): ByteArray =
        targetData.joinToString(separator = "") { line(it) }.toByteArray(Charsets.UTF_8)

    private fun line(t: TargetData): String {
        val values = t.sources.toSortedMap().flatMap { (source, data) ->
            data.channels.toSortedMap().map { (channel, out) -> "$source.$channel=${out.value}" }
        }.joinToString(";")
        val prefix = if (configuration.isNotBlank()) "E2E[$configuration]" else "E2E"
        return "$prefix|${t.metadata["marker"] ?: "-"}|${t.schedule}|$values\n"
    }

    companion object {
        @JvmStatic
        fun newInstance(vararg createParameters: Any): E2eLineFormatter =
            E2eLineFormatter(createParameters[0] as String, createParameters[1] as Logger)
    }
}
