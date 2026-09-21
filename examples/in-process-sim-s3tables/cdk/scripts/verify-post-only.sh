#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Assert that the DEPLOYED API surface is POST-only.
#
# test/openapi.test.ts checks the committed document; this checks the live API, which is what the
# requirement is actually about. Two things can diverge from the file: a method added through the
# console, and a path deleted from openapi.yaml that API Gateway did not remove on import.
#
# Every data path must expose exactly one POST (Cognito-authorized) and one OPTIONS (no authorizer,
# for the CORS preflight). Anything else is a failure.
#
# Usage:
#   ./scripts/verify-post-only.sh
#   STACK_NAME=MyStack AWS_PROFILE=dev ./scripts/verify-post-only.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-SfcS3TablesDuckDbQueryApp}"

AWS_ARGS=()
[[ -n "${AWS_PROFILE:-}" ]] && AWS_ARGS+=(--profile "$AWS_PROFILE")
[[ -n "${AWS_REGION:-}" ]] && AWS_ARGS+=(--region "$AWS_REGION")

API_URL="$(aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiExecuteUrl'].OutputValue" \
  --output text)"

if [[ -z "$API_URL" || "$API_URL" == "None" ]]; then
  echo "Could not read ApiExecuteUrl from stack ${STACK_NAME}." >&2
  exit 1
fi

# https://<id>.execute-api.<region>.amazonaws.com/<stage>/
API_ID="$(printf '%s' "$API_URL" | sed -E 's#^https://([^.]+)\..*#\1#')"
echo "Inspecting REST API ${API_ID} from stack ${STACK_NAME}…"

RESOURCES="$(aws "${AWS_ARGS[@]}" apigateway get-resources \
  --rest-api-id "$API_ID" --embed methods --output json)"

FAILURES=0

while IFS=$'\t' read -r path methods authorizers; do
  # Container resources (/ and /api) legitimately carry no methods.
  if [[ -z "$methods" || "$methods" == "None" ]]; then
    if [[ "$path" == "/" || "$path" == "/api" ]]; then
      echo "  ok    ${path} (container, no methods)"
    else
      echo "  FAIL  ${path} has no methods"
      FAILURES=$((FAILURES + 1))
    fi
    continue
  fi

  sorted="$(printf '%s' "$methods" | tr ' ' '\n' | sort | tr '\n' ' ' | sed 's/ $//')"
  if [[ "$sorted" != "OPTIONS POST" ]]; then
    echo "  FAIL  ${path} exposes [${sorted}]; expected exactly [OPTIONS POST]"
    FAILURES=$((FAILURES + 1))
    continue
  fi
  if [[ "$authorizers" != *COGNITO_USER_POOLS* ]]; then
    echo "  FAIL  ${path} POST is not guarded by a Cognito user pool authorizer"
    FAILURES=$((FAILURES + 1))
    continue
  fi
  echo "  ok    ${path} POST (COGNITO_USER_POOLS) + OPTIONS (preflight)"
done < <(
  printf '%s' "$RESOURCES" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for item in sorted(data.get("items", []), key=lambda r: r["path"]):
    methods = item.get("resourceMethods") or {}
    parts = []
    for verb in sorted(methods):
        parts.append(verb + ":" + str(methods[verb].get("authorizationType", "?")))
    print("\t".join([item["path"], " ".join(sorted(methods)), ",".join(parts)]))
'
)

echo
if (( FAILURES > 0 )); then
  echo "POST-only invariant VIOLATED: ${FAILURES} problem(s)." >&2
  exit 1
fi
echo "POST-only invariant holds: every data path is one Cognito-authorized POST plus one preflight."
