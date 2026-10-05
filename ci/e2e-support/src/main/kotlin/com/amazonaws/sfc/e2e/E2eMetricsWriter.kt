// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

package com.amazonaws.sfc.e2e

import com.amazonaws.sfc.config.ConfigReader
import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.metrics.MetricsData
import com.amazonaws.sfc.metrics.MetricsStatistics
import com.amazonaws.sfc.metrics.MetricsValue
import com.amazonaws.sfc.metrics.MetricsValues
import com.amazonaws.sfc.metrics.MetricsWriter
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/**
 * An in-process [MetricsWriter] that appends every data point to a local JSONL file, one JSON object
 * per line.
 *
 * This exists because the end-to-end suite needs to assert on SFC's own view of what it did, not just
 * on what arrived at a destination. SFC already collects per-target `Writes`, `WriteErrors`,
 * `WriteDuration`, `Messages` and `BytesWritten`, but the only shipped writer sends them to CloudWatch
 * - which would make every assertion depend on a network round trip and on CloudWatch's own ingestion
 * delay. Writing them to a file instead makes them exact and immediately readable.
 *
 * It is what lets the suite catch the failure mode that matters most: a target that reports success
 * while silently dropping data. A case whose payload assertions pass but whose `WriteErrors` counter
 * is non-zero is a failure, and without these counters that is invisible.
 *
 * Configuration is by environment variable rather than by a configuration section, so no custom
 * config class has to be deserialised and a test case needs nothing but an env var:
 *
 *   SFC_E2E_METRICS   absolute path of the JSONL file to append to. Required; the writer fails fast
 *                     if it is unset, because silently writing nowhere would make every metrics
 *                     assertion vacuously pass.
 *
 * Wire it into a test configuration with:
 *
 *   "Metrics": {
 *     "Interval": 1,
 *     "Writer": {
 *       "MetricsWriter": {
 *         "FactoryClassName": "com.amazonaws.sfc.e2e.E2eMetricsWriter",
 *         "JarFiles": ["${SFC_E2E_SUPPORT_JAR}"]
 *       }
 *     }
 *   }
 *
 * In uberjar mode the JarFiles entry is omitted and the jar is placed on the classpath instead, which
 * is also what exercises InstanceFactory's Class.forName branch.
 */
class E2eMetricsWriter(private val outputFile: File, private val logger: Logger) : MetricsWriter {

    private val className = this::class.java.simpleName

    // writeMetricsData can be called concurrently from the metrics processor; a mutex keeps whole
    // lines intact. Without it, interleaved appends would produce torn JSON that the harness would
    // report as a parse error rather than as the concurrency problem it is.
    private val mutex = Mutex()

    // Compact, single-line, and with HTML escaping off - Gson escapes '=' and '<' by default, which
    // would mangle dimension values and make golden comparisons confusing.
    private val gson = GsonBuilder().disableHtmlEscaping().create()

    private var pointsWritten = 0L

    override suspend fun writeMetricsData(metricsData: MetricsData) {
        val log = logger.getCtxLoggers(className, "writeMetricsData")

        val lines = buildList {
            metricsData.dataPoints.forEach { point ->
                val o = JsonObject()
                o.addProperty("source", metricsData.source)
                o.addProperty("sourceType", metricsData.sourceType.name)
                o.addProperty("name", point.name)
                o.addProperty("units", point.units.name)
                o.addProperty("timestamp", point.timestamp.toString())

                // Dimensions decide which target a data point belongs to, so they are what the
                // harness keys on. commonDimensions first, then the point's own, so a point-level
                // dimension wins on conflict - the same precedence the CloudWatch writer applies.
                val dimensions = JsonObject()
                metricsData.commonDimensions?.forEach { (k, v) -> dimensions.addProperty(k, v) }
                point.dimensions?.forEach { (k, v) -> dimensions.addProperty(k, v) }
                o.add("dimensions", dimensions)

                // The three MetricsDataValue shapes are kept distinct rather than flattened to a
                // single number: collapsing MetricsValues to, say, its mean would hide exactly the
                // per-write distribution a latency or batch-size assertion is looking at.
                when (val value = point.value) {
                    is MetricsValue -> {
                        o.addProperty("valueType", "single")
                        o.addProperty("value", value.value)
                    }

                    is MetricsValues -> {
                        o.addProperty("valueType", "values")
                        o.add("values", JsonArray().apply { value.values.forEach { add(it) } })
                        value.counts?.let { counts ->
                            o.add("counts", JsonArray().apply { counts.forEach { add(it) } })
                        }
                    }

                    is MetricsStatistics -> {
                        o.addProperty("valueType", "statistics")
                        o.addProperty("minimum", value.minimum)
                        o.addProperty("maximum", value.maximum)
                        o.addProperty("sampleCount", value.sampleCount)
                        o.addProperty("sum", value.sum)
                    }
                }

                add(gson.toJson(o))
            }
        }

        if (lines.isEmpty()) return

        mutex.withLock {
            try {
                // Append, and create on first use. The harness pre-creates the parent directory.
                outputFile.appendText(lines.joinToString(separator = "\n", postfix = "\n"))
                pointsWritten += lines.size
            } catch (e: Exception) {
                // Never propagate: a failure to record metrics must not take down the pipeline being
                // measured, or a disk problem in the harness would look like an SFC bug.
                log.error("Error appending ${lines.size} metric data point(s) to $outputFile, $e")
            }
        }
    }

    override suspend fun close() {
        logger.getCtxLoggers(className, "close")
            .info("E2E metrics writer closing, wrote $pointsWritten data point(s) to $outputFile")
    }

    companion object {

        /** Name of the environment variable holding the output path. */
        const val ENV_OUTPUT_FILE = "SFC_E2E_METRICS"

        // InstanceFactory calls the vararg form reflectively; the typed overload exists for tests and
        // for direct use. This mirrors AwsCloudWatchMetricsWriter's contract exactly.
        @JvmStatic
        @Suppress("unused")
        fun newInstance(vararg createParameters: Any?): MetricsWriter =
            newInstance(createParameters[0] as ConfigReader, createParameters[1] as Logger)

        @JvmStatic
        @Suppress("UNUSED_PARAMETER")
        fun newInstance(configReader: ConfigReader, logger: Logger): MetricsWriter {
            val path = System.getenv(ENV_OUTPUT_FILE)?.trim()
            // Fail loudly. A writer that quietly discarded its output would make every metrics
            // assertion in the suite pass for the wrong reason.
            require(!path.isNullOrEmpty()) {
                "$ENV_OUTPUT_FILE is not set - E2eMetricsWriter has nowhere to write. " +
                        "Set it to an absolute file path."
            }
            val file = File(path)
            file.parentFile?.mkdirs()
            logger.getCtxLoggers(E2eMetricsWriter::class.java.simpleName, "newInstance")
                .info("E2E metrics writer appending to $file")
            return E2eMetricsWriter(file, logger)
        }
    }
}
