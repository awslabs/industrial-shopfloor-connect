// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//

package com.amazonaws.sfc.opcuawritetarget


import com.amazonaws.sfc.config.ChannelConfiguration.Companion.CONFIG_TRANSFORMATION
import com.amazonaws.sfc.log.Logger
import com.amazonaws.sfc.opcuawritetarget.OpcuaDataTypes.Companion.asType
import org.eclipse.milo.opcua.stack.core.NodeIds
import org.eclipse.milo.opcua.stack.core.types.builtin.*
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.UByte
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.UInteger
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.ULong
import org.eclipse.milo.opcua.stack.core.types.builtin.unsigned.UShort

enum class OpcuaDataType {

    BOOLEAN {
        override val identifier: NodeId
            get() = NodeIds.Boolean
    },
    BYTE {
        override val identifier: NodeId
            get() = NodeIds.SByte
    },
    SBYTE {
        override val identifier: NodeId
            get() = NodeIds.SByte
    },
    BYTESTRING {
        override val identifier: NodeId
            get() = NodeIds.ByteString
    },
    DATETIME {
        override val identifier: NodeId
            get() = NodeIds.DateTime
    },
    DOUBLE {
        override val identifier: NodeId
            get() = NodeIds.Double
    },
    EXPANDEDNODEID {
        override val identifier: NodeId
            get() = NodeIds.ExpandedNodeId
    },

    FLOAT {
        override val identifier: NodeId
            get() = NodeIds.Float
    },
    INT {
        override val identifier: NodeId
            get() = NodeIds.Int32
    },
    INTEGER {
        override val identifier: NodeId
            get() = NodeIds.Int32
    },
    INT32 {
        override val identifier: NodeId
            get() = NodeIds.Int32
    },
    LOCALIZEDTEXT {
        override val identifier: NodeId
            get() = NodeIds.LocalizedText
    },
    LONG {
        override val identifier: NodeId
            get() = NodeIds.Int64
    },
    INT64 {
        override val identifier: NodeId
            get() = NodeIds.Int64
    },
    NODEID {
        override val identifier: NodeId
            get() = NodeIds.NodeId
    },
    QUALIFIEDNAME {
        override val identifier: NodeId
            get() = NodeIds.QualifiedName
    },
    REAL {
        override val identifier: NodeId
            get() = NodeIds.Float
    },
    SHORT {
        override val identifier: NodeId
            get() = NodeIds.Int16
    },
    INT16 {
        override val identifier: NodeId
            get() = NodeIds.Int16
    },
    STRING {
        override val identifier: NodeId
            get() = NodeIds.String
    },
    UINT {
        override val identifier: NodeId
            get() = NodeIds.UInt32
    },
    UINT32 {
        override val identifier: NodeId
            get() = NodeIds.UInt32
    },
    UINTEGER {
        override val identifier: NodeId
            get() = NodeIds.UInt32
    },
    UUID {
        override val identifier: NodeId
            get() = NodeIds.Guid
    },
    XML_ELEMENT {
        override val identifier: NodeId
            get() = NodeIds.XmlElement
    },
    UBYTE {
        override val identifier: NodeId
            get() = NodeIds.Byte
    },
    ULONG {
        override val identifier: NodeId
            get() = NodeIds.UInt64
    },
    UINT64 {
        override val identifier: NodeId
            get() = NodeIds.UInt64
    },
    USHORT {
        override val identifier: NodeId
            get() = NodeIds.UInt16
    },
    UINT16 {
        override val identifier: NodeId
            get() = NodeIds.UInt16
    },
    STRUCT {
        override val identifier: NodeId
            get() = NodeIds.Structure
    },
    VARIANT {
        override val identifier: NodeId
            get() = NodeIds.BaseDataVariableType
    },
    UNDEFINED {
        override val identifier: NodeId
            get() = NodeIds.BaseDataVariableType
    };

    abstract val identifier: NodeId

    companion object {

        val className = this::class.simpleName.toString()

        fun fromString(value: String): OpcuaDataType {
            val s = value.uppercase().trim().replace("_", "")
            return entries.find { it.name == s } ?: UNDEFINED
        }

        fun fromIdentifier(value: ExpandedNodeId): OpcuaDataType {
            return entries.find { it.identifier.identifier == value.identifier && it.identifier.namespaceIndex == value.namespaceIndex } ?: UNDEFINED
        }

        fun fromIdentifier(value: NodeId): OpcuaDataType {
            return entries.find { it.identifier.identifier == value.identifier && it.identifier.namespaceIndex == value.namespaceIndex } ?: UNDEFINED
        }

        private fun convert(value: Any?, dataTypeIdentifier: NodeId?, dimensions: List<Int>?, logger: Logger): Any? {
            var v = value
            try {
                if (v is List<*> && dimensions != null) {

                    v = when (dataTypeIdentifier) {
                        NodeIds.Boolean -> deepCast<Boolean>(dimensions, v) {asType(it, NodeIds.Boolean) as Boolean }
                        NodeIds.SByte -> deepCast<Byte>(dimensions, v) { asType(it, NodeIds.SByte) as Byte }
                        NodeIds.ByteString -> deepCast<ByteString>(dimensions, v) { asType(it, NodeIds.ByteString) as ByteString  }
                        NodeIds.String -> deepCast<String>(dimensions, v) { asType(it, NodeIds.String) as String }
                        NodeIds.Structure -> deepCast<String>(dimensions, v) { asType(it, NodeIds.Structure) as String}
                        NodeIds.DateTime -> deepCast<DateTime>(dimensions, v) { asType(it, NodeIds.DateTime) as DateTime }
                        NodeIds.Double -> deepCast<Double>(dimensions, v) { asType(it, NodeIds.Double) as Double }
                        NodeIds.ExpandedNodeId -> deepCast<ExpandedNodeId>(dimensions, v) { asType(it, NodeIds.ExpandedNodeId) as ExpandedNodeId }
                        NodeIds.Float -> deepCast<Float>(dimensions, v) { asType(it, NodeIds.Float) as Float }
                        NodeIds.Int16 -> deepCast<Short>(dimensions, v) { asType(it, NodeIds.Int16) as Short }
                        NodeIds.Int32 -> deepCast<Int>(dimensions, v) { asType(it, NodeIds.Int32) as Int }
                        NodeIds.Int64 -> deepCast<Long>(dimensions, v) { asType(it, NodeIds.Int64) as Long }
                        NodeIds.Byte -> deepCast<UByte>(dimensions, v) { UByte.valueOf(asType(it, NodeIds.Int16) as Short) }
                        NodeIds.UInt16 -> deepCast<UShort>(dimensions, v) { UShort.valueOf(asType(it, NodeIds.Int32) as Int) }
                        NodeIds.UInt32 -> deepCast<UInteger>(dimensions, v) { UInteger.valueOf(asType(it, NodeIds.Int64) as Long) }
                        NodeIds.UInt64 -> deepCast<ULong>(dimensions, v) { asType(it, NodeIds.Int64) as ULong }
                        NodeIds.NodeId -> deepCast<NodeId>(dimensions, v) { NodeId.parse(it.toString()) }
                        NodeIds.XmlElement -> deepCast<XmlElement>(dimensions, v) { asType(it, NodeIds.XmlElement) as XmlElement }
                        else -> v
                    }
                } else {
                    v = if (v != null) {
                        asType(v, dataTypeIdentifier!!)
                    } else v
                }
            } catch (_: Exception) {
                logger.getCtxErrorLog(
                    className,
                    "convert")("Error converting value $value:${value!!::class.simpleName} to OPCUA data type ${fromIdentifier(dataTypeIdentifier!!)}, set the $CONFIG_TRANSFORMATION property of the node configuration to convert to the required type")
                return null
            }
            return v
        }

        private inline fun <reified T> deepCast(dimensions: List<Int>, value: Any?, fn: (Any) -> T): Any? {

            return when (value) {
                null -> null
                is List<*> -> when (dimensions.size) {

                    1 -> Array(dimensions[0]) { i0 -> value[i0]?.let { fn(it) } }

                    2 -> Array(dimensions[0]) { i0 ->
                        Array(dimensions[1]) { i1 ->
                            val l1 = (value[i0]) as List<*>
                            l1[i1]?.let { fn(it) }
                        }
                    }

                    3 -> Array(dimensions[0]) { i0 ->
                        Array(dimensions[1]) { i1 ->
                            val l1 = (value[i0]) as List<*>
                            Array(dimensions[2]) { i2 ->
                                val l2 = (l1[i1]) as List<*>
                                l2[i2]?.let { fn(it) }
                            }
                        }
                    }

                    else -> {
                        value
                    }
                }

                else -> {
                    fn(value)
                }
            }
        }

        fun Any?.toVariant(dataTypeIdentifier: NodeId?, dimensions: List<Int>?, logger: Logger): Variant = Variant(convert(this, dataTypeIdentifier, dimensions, logger))
    }

}