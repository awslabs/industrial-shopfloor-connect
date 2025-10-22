
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//


package com.amazonaws.sfc.crypto

import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.util.DirectoryEntryChange
import com.amazonaws.sfc.util.DirectoryWatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.launch
import java.io.Closeable
import java.nio.file.Path

abstract class TypedDirectoryWatcher<T>(
    private val watchedDirectory: Path,
    scope: CoroutineScope,
    logger: Logger,
    onUpdate: () -> Set<T>
) : Closeable {

    private val className = this::class.java.simpleName.toString()

    private var watcher: DirectoryWatcher? = null


    @OptIn(FlowPreview::class)
    private val watchJob = scope.launch {
        watcher = DirectoryWatcher(watchedDirectory.toAbsolutePath().toString())
        watcher?.changes?.debounce(watcher!!.pollInterval)?.collect { _: DirectoryEntryChange ->
            val info = logger.getCtxInfoLog(className, "com.amazonaws.sfc.util.DirectoryEntryChange")
            info("File changes detected in directory $watchedDirectory")
            entries = onUpdate()
        }
    }

    override fun close() {
        watcher?.close()
        watchJob.cancel()
    }

    var entries: Set<T> = setOf()
}