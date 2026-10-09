# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Custom resource: turn on public access to the MSK Provisioned cluster and return its public bootstrap
string (``BootstrapBrokerStringPublicSaslIam``, IAM over TLS on 9198), the endpoint SFC's MSK target
uses from outside AWS (docs/targets/aws-msk.md).

AWS does not allow public access while a cluster is being created
(https://docs.aws.amazon.com/msk/latest/developerguide/public-access.html), so the cluster is created
with it off and this resource switches it on afterwards. ``UpdateConnectivity`` runs for many minutes:
``on_event`` starts it, ``is_complete`` is polled by the CDK Provider until the cluster is ACTIVE with
public access on, then returns the bootstrap string as ``BootstrapPublicSaslIam``.
"""

from __future__ import annotations

import boto3

PUBLIC = "SERVICE_PROVIDED_EIPS"


def _client():
    return boto3.client("kafka")


def _provisioned(kafka, arn: str) -> dict:
    return kafka.describe_cluster_v2(ClusterArn=arn)["ClusterInfo"]


def _public_type(info: dict) -> str:
    return (((info.get("Provisioned") or {}).get("BrokerNodeGroupInfo") or {}).get("ConnectivityInfo") or {}) \
        .get("PublicAccess", {}).get("Type", "DISABLED")


def on_event(event, _context):  # noqa: ANN001
    arn = event["ResourceProperties"]["ClusterArn"]
    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": event.get("PhysicalResourceId", arn)}  # the cluster goes with the stack
    kafka = _client()
    info = _provisioned(kafka, arn)
    if _public_type(info) != PUBLIC:
        # CloudFormation creates this resource after the cluster reached CREATE_COMPLETE, i.e. ACTIVE.
        if info["State"] != "ACTIVE":
            raise RuntimeError(f"cluster {arn} is {info['State']}, expected ACTIVE before turning on public access")
        kafka.update_connectivity(ClusterArn=arn, CurrentVersion=info["CurrentVersion"],
                                  ConnectivityInfo={"PublicAccess": {"Type": PUBLIC}})
        print(f"public access requested for {arn}")
    return {"PhysicalResourceId": f"{arn}/public-access"}


def is_complete(event, _context):  # noqa: ANN001
    if event["RequestType"] == "Delete":
        return {"IsComplete": True}
    arn = event["ResourceProperties"]["ClusterArn"]
    kafka = _client()
    info = _provisioned(kafka, arn)
    if info["State"] != "ACTIVE" or _public_type(info) != PUBLIC:
        print(f"waiting: state {info['State']}, public access {_public_type(info)}")
        return {"IsComplete": False}
    brokers = kafka.get_bootstrap_brokers(ClusterArn=arn).get("BootstrapBrokerStringPublicSaslIam")
    if not brokers:
        return {"IsComplete": False}
    return {"IsComplete": True, "Data": {"BootstrapPublicSaslIam": brokers}}
