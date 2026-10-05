# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# CodeBuild image for the SFC integration suite. Everything a build needs is installed here once, so a
# build spends its time building and testing. Built in AWS by the image project (sfc-integration-test-image)
# from the uploaded working tree, build context ci/, and pushed to ECR tagged with the hash of this file
# and the two files it copies; ci/start-build.sh rebuilds it whenever one of them changes.
FROM public.ecr.aws/docker/library/ubuntu:24.04

ARG NATS_VERSION=2.10.24
ARG NATS_SHA256=ee6500f364e3a741b496ae0296c04f2a9d53bbaabac457104ac74596b4a59d85
ARG KAFKA_VERSION=3.9.0
ARG KAFKA_SCALA=2.13
ARG MSK_IAM_VERSION=2.3.8

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    JAVA_HOME=/usr/lib/jvm/java-17-amazon-corretto \
    KAFKA_HOME=/opt/kafka \
    PATH=/opt/venv/bin:/usr/lib/jvm/java-17-amazon-corretto/bin:$PATH

# Base tools; the counterparts mosquitto, snmpd and PostgreSQL (never started here: a container has no
# init, the suite starts them itself); Amazon Corretto 17; the AWS CLI v2.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg unzip zip jq procps openssl \
      python3 python3-venv mosquitto mosquitto-clients snmpd snmp postgresql \
 && curl -fsSL https://apt.corretto.aws/corretto.key | gpg --dearmor -o /usr/share/keyrings/corretto.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/corretto.gpg] https://apt.corretto.aws stable main" > /etc/apt/sources.list.d/corretto.list \
 && apt-get update && apt-get install -y --no-install-recommends java-17-amazon-corretto-jdk \
 && curl -fsSL -o /tmp/awscli.zip https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip \
 && unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip \
 && rm -rf /var/lib/apt/lists/*

# nats-server, pinned and verified against the release's SHA256SUMS.
RUN curl -fsSL -o /tmp/nats.tgz https://github.com/nats-io/nats-server/releases/download/v${NATS_VERSION}/nats-server-v${NATS_VERSION}-linux-amd64.tar.gz \
 && echo "${NATS_SHA256}  /tmp/nats.tgz" | sha256sum -c - \
 && tar xzf /tmp/nats.tgz -C /tmp && mv /tmp/nats-server-v${NATS_VERSION}-linux-amd64/nats-server /usr/local/bin/ \
 && rm -rf /tmp/nats*

# The harness's Python packages, in a venv (Ubuntu's system Python is externally managed).
COPY e2e/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Kafka CLI tools and the MSK IAM jar, for topic setup and read-back in the MSK cases; checksum-verified.
COPY e2e/lib/install_kafka.py /tmp/install_kafka.py
RUN python3 /tmp/install_kafka.py --home /opt/kafka --version ${KAFKA_VERSION} --scala ${KAFKA_SCALA} --msk-iam ${MSK_IAM_VERSION} \
 && rm /tmp/install_kafka.py
