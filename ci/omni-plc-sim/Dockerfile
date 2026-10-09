# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Builds omni-plc-sim in AWS, in the CodeBuild project sfc-integration-test-plc-sim: compile from source,
# run every test (golden frames of all protocols), export the binary. The musl target makes it a static
# binary, so it runs on the suite's Ubuntu image (or any Linux) with no glibc coupling.
#
#   docker build -f ci/omni-plc-sim/Dockerfile --target export --output type=local,dest=out ci/omni-plc-sim
#
# The Rust version matches the toolchain used for local development (Cargo.toml rust-version).
FROM public.ecr.aws/docker/library/rust:1.98-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY . .
RUN cargo build --release --locked \
 && cargo test --release --locked \
 && target/release/omni-plc-sim --version

FROM scratch AS export
COPY --from=build /src/target/release/omni-plc-sim /omni-plc-sim
