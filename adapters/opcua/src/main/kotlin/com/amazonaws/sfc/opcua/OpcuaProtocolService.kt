
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0


package com.amazonaws.sfc.opcua

import com.amazonaws.sfc.config.ConfigReader
import com.amazonaws.sfc.ipc.IpcAdapterService
import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.service.Service
import com.amazonaws.sfc.service.ServiceMain
import kotlinx.coroutines.runBlocking


class OpcuaProtocolService : ServiceMain() {

    override fun createServiceInstance(args: Array<String>, configuration: String, logger: Logger): Service? {
        return IpcAdapterService.createProtocolAdapterService(args, configuration, logger) { a: String, c: ConfigReader, l: Logger ->
            OpcuaAdapter.createOpcuaAdapter(adapterID = a, configReader = c, logger = l)

        }
    }

    companion object {
        @JvmStatic
        @JvmName("main")
        fun main(args: Array<String>) = runBlocking {
            OpcuaProtocolService().run(args)
        }
    }
}