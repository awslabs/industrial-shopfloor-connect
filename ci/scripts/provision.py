#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Prepares the AWS tier for one run.

Two jobs:

1. Publish the stack's outputs as ``SFC_E2E_*`` environment variables, which is how a case configuration
   reaches its queue URL, topic ARN or bucket name. SFC substitutes those placeholders itself and
   **errors on an unresolved one**, so a missing output is a loud startup failure rather than a case that
   quietly wrote nowhere.
2. Create the handful of resources that genuinely must be per-run, and only those.

The design rule is that almost nothing is created per run. Long-lived, free-at-rest sinks - queues, the
topic, the IoT rule, the bucket - are owned by the CDK stack, so a run creates no quota-bound resource
and a crashed run leaks nothing that a lifecycle rule will not remove on its own. What remains per-run is
here.

CodeBuild phases do not share shell state, so the variables are written to a file for the build phase to
source rather than exported.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    print("boto3 is required: pip3 install boto3", file=sys.stderr)
    raise

STACK = os.environ.get("SFC_IT_STACK", "SfcIntegrationTest")
ENV_FILE = pathlib.Path(os.environ.get("SFC_E2E_ENV_FILE", "/codebuild/e2e-env.sh"))

# Stack output -> the SFC_E2E_* name a case configuration refers to.
OUTPUT_MAP = {
    "ArtifactsBucket": "SFC_E2E_BUCKET",
    "SqsTargetQueueUrl": "SFC_E2E_QUEUE_URL",
    "SnsTargetTopicArn": "SFC_E2E_TOPIC_ARN",
    "SnsSinkQueueUrl": "SFC_E2E_SNS_SINK_QUEUE_URL",
    "IotSinkQueueUrl": "SFC_E2E_IOT_SINK_QUEUE_URL",
    "EvidenceFunctionName": "SFC_E2E_LAMBDA_NAME",
    "RunRoleArn": "SFC_E2E_RUN_ROLE_ARN",
}


def run_id() -> str:
    """Must match the janitor's derivation exactly - see ci/cdk/lambda/janitor.py.

    ``$CODEBUILD_BUILD_ID`` is ``project:uuid``; splitting on the LAST colon is what makes this agree
    with the EventBridge path, where the same build appears as a full ARN.
    """
    build_id = os.environ.get("CODEBUILD_BUILD_ID", "local:000000000000")
    return "b_" + build_id.rsplit(":", 1)[-1].replace("-", "")[:12]


def stack_outputs(stack: str) -> dict[str, str]:
    cfn = boto3.client("cloudformation")
    stacks = cfn.describe_stacks(StackName=stack)["Stacks"]
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def main() -> int:
    rid = run_id()
    print(f"provisioning run {rid} from stack {STACK}")

    outputs = stack_outputs(STACK)
    env: dict[str, str] = {"SFC_E2E_RUN_ID": rid}

    missing = [k for k in OUTPUT_MAP if k not in outputs]
    if missing:
        print(f"stack {STACK} is missing outputs: {missing}", file=sys.stderr)
        print("Deploy ci/cdk, or update OUTPUT_MAP if the stack changed.", file=sys.stderr)
        return 1
    for output_key, env_name in OUTPUT_MAP.items():
        env[env_name] = outputs[output_key]

    region = boto3.session.Session().region_name or os.environ.get("AWS_REGION", "us-east-1")
    env["AWS_REGION"] = region

    # The IoT data endpoint is account- and region-specific and cannot be a stack output, because it is
    # returned by a data-plane call rather than declared.
    try:
        endpoint = boto3.client("iot").describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]
        env["SFC_E2E_IOT_ENDPOINT"] = endpoint
    except Exception as e:  # noqa: BLE001
        print(f"warning: could not resolve the IoT data endpoint: {e}", file=sys.stderr)

    # Per-run Kinesis stream. Deliberately NOT a stack resource: one provisioned shard idles at roughly
    # $11/month, which is absurd for a test that runs for a few seconds. Creating it here costs about a
    # minute of wall clock and the janitor removes it.
    if os.environ.get("SFC_E2E_WITH_KINESIS", "0") == "1":
        stream = f"sfc-it-{rid}"
        kinesis = boto3.client("kinesis")
        try:
            kinesis.create_stream(StreamName=stream, ShardCount=1)
            kinesis.get_waiter("stream_exists").wait(StreamName=stream)
            env["SFC_E2E_KINESIS_STREAM"] = stream
            print(f"created kinesis stream {stream}")
        except kinesis.exceptions.ResourceInUseException:
            env["SFC_E2E_KINESIS_STREAM"] = stream
            print(f"kinesis stream {stream} already exists")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Single-quoted with any embedded quote escaped, so a value containing shell metacharacters cannot
    # be re-interpreted when the build phase sources this.
    lines = [f"export {k}='{v.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for k, v in sorted(env.items())]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(env)} variable(s) to {ENV_FILE}")
    print(json.dumps({k: v for k, v in env.items() if "ROLE" not in k}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
