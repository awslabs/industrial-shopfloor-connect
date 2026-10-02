#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Installs a single-broker Kafka into the build container, so the AWS-MSK target's write path can be
# exercised without an MSK cluster.
#
# Why this instead of real MSK: a provisioned cluster needs a VPC, takes 20-30 minutes to create and
# costs ~$100/month standing, all to cover one target. Kafka in the container covers the same code -
# the producer configuration, the serialisation and the aws-msk-iam-auth classpath - at zero cost and
# in seconds. What it does NOT cover is the SigV4 IAM handshake against the real service; that gap is
# stated explicitly in the test report rather than hidden.
#
# The aws-msk-iam-auth jar is still installed: SFC's MSK target names IAMLoginModule in its producer
# properties, so without it on the Kafka CLI classpath the tooling cannot even parse a config that
# mentions it.
set -euo pipefail

KAFKA_VERSION="${KAFKA_VERSION:-3.9.0}"
SCALA_VERSION="${SCALA_VERSION:-2.13}"
MSK_IAM_VERSION="${MSK_IAM_VERSION:-2.3.8}"
KAFKA_HOME="${KAFKA_HOME:-/opt/kafka}"

if [ -x "$KAFKA_HOME/bin/kafka-server-start.sh" ]; then
  echo "kafka already present at $KAFKA_HOME (restored from the build cache)"
else
  echo "installing kafka ${KAFKA_VERSION} ..."
  mkdir -p "$KAFKA_HOME"
  curl -fsSL "https://archive.apache.org/dist/kafka/${KAFKA_VERSION}/kafka_${SCALA_VERSION}-${KAFKA_VERSION}.tgz" \
    | tar xz -C "$KAFKA_HOME" --strip-components=1
fi

IAM_JAR="$KAFKA_HOME/libs/aws-msk-iam-auth-${MSK_IAM_VERSION}-all.jar"
if [ ! -f "$IAM_JAR" ]; then
  echo "installing aws-msk-iam-auth ${MSK_IAM_VERSION} ..."
  curl -fsSL -o "$IAM_JAR" \
    "https://github.com/aws/aws-msk-iam-auth/releases/download/v${MSK_IAM_VERSION}/aws-msk-iam-auth-${MSK_IAM_VERSION}-all.jar"
fi

# KRaft mode: no ZooKeeper process to manage.
DATA_DIR="${KAFKA_DATA_DIR:-/tmp/kraft-combined-logs}"
CONFIG="$KAFKA_HOME/config/kraft/server.properties"
[ -f "$CONFIG" ] || CONFIG="$KAFKA_HOME/config/server.properties"

if ! nc -z 127.0.0.1 9092 2>/dev/null; then
  echo "formatting and starting kafka ..."
  CLUSTER_ID=$("$KAFKA_HOME/bin/kafka-storage.sh" random-uuid)
  "$KAFKA_HOME/bin/kafka-storage.sh" format -t "$CLUSTER_ID" -c "$CONFIG" --ignore-formatted
  nohup "$KAFKA_HOME/bin/kafka-server-start.sh" "$CONFIG" \
    --override log.dirs="$DATA_DIR" \
    --override auto.create.topics.enable=true \
    > /tmp/kafka.log 2>&1 &
  # Poll rather than sleep: the broker is ready when it accepts a connection, not after a fixed wait.
  for _ in $(seq 1 60); do
    nc -z 127.0.0.1 9092 && break
    sleep 1
  done
fi

nc -z 127.0.0.1 9092 || { echo "kafka did not come up; see /tmp/kafka.log" >&2; tail -30 /tmp/kafka.log >&2; exit 1; }
"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server 127.0.0.1:9092 --list >/dev/null
echo "kafka is listening on 127.0.0.1:9092"
