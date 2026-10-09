# J1939 DBC file

> **Platform:** the [J1939 adapter](../../docs/adapters/j1939.md) that uses this file runs on Linux only (SocketCAN).
> The DBC file itself is plain text and can be edited on any OS.

Open source version of [J1939 DBC file](./j1939.dbc).

Source: https://github.com/nberlette/canbus/blob/main/dbc/j1939.dbc

## Use it

Set the path of the file in the [DbcFile](../../docs/adapters/j1939.md#dbcfile) setting of the J1939 adapter, for
example `"DbcFile": "/opt/sfc/j1939.dbc"`. A relative path resolves against the directory the adapter's process is
started from. The channel examples on the adapter page, such as PGN `EEC1` (61444) with SPN `EngSpeed` (190), are
defined in this file.

Docs used: [J1939 adapter](../../docs/adapters/j1939.md#dbcfile) · [All examples](../../docs/examples/README.md)
