#!/usr/bin/env bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Create a sign-in for the deployed query app.
#
# The user pool has self sign-up disabled, so `cdk deploy` leaves you with no way to log in. This
# reads the stack outputs, creates a confirmed user and sets a permanent password, so the first
# sign-in goes straight through without a FORCE_CHANGE_PASSWORD challenge.
#
# Usage:
#   ./scripts/create-user.sh you@example.com [password]
#   STACK_NAME=MyStack AWS_PROFILE=dev AWS_REGION=eu-west-1 ./scripts/create-user.sh you@example.com

set -euo pipefail

STACK_NAME="${STACK_NAME:-SfcS3TablesDuckDbQueryApp}"
EMAIL="${1:-}"
PASSWORD="${2:-}"

if [[ -z "$EMAIL" ]]; then
  echo "usage: $0 <email> [password]" >&2
  echo "       STACK_NAME defaults to ${STACK_NAME}" >&2
  exit 2
fi

AWS_ARGS=()
[[ -n "${AWS_PROFILE:-}" ]] && AWS_ARGS+=(--profile "$AWS_PROFILE")
[[ -n "${AWS_REGION:-}" ]] && AWS_ARGS+=(--region "$AWS_REGION")

output() {
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

echo "Reading outputs from stack ${STACK_NAME}…"
POOL_ID="$(output UserPoolId)"
SITE_URL="$(output SiteUrl)"

if [[ -z "$POOL_ID" || "$POOL_ID" == "None" ]]; then
  echo "Could not read UserPoolId from stack ${STACK_NAME}. Is it deployed in this account and region?" >&2
  exit 1
fi

if [[ -z "$PASSWORD" ]]; then
  # The pool requires 12+ characters with upper, lower and digits.
  PASSWORD="Sfc-$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)1"
  GENERATED=1
fi

if aws "${AWS_ARGS[@]}" cognito-idp admin-get-user \
  --user-pool-id "$POOL_ID" --username "$EMAIL" >/dev/null 2>&1; then
  echo "User ${EMAIL} already exists; resetting the password."
else
  echo "Creating ${EMAIL}…"
  # --message-action SUPPRESS: no invitation email, since the password is set below anyway.
  aws "${AWS_ARGS[@]}" cognito-idp admin-create-user \
    --user-pool-id "$POOL_ID" \
    --username "$EMAIL" \
    --user-attributes "Name=email,Value=${EMAIL}" "Name=email_verified,Value=true" \
    --message-action SUPPRESS >/dev/null
fi

# --permanent moves the user straight to CONFIRMED, skipping the new-password challenge that the
# managed login flow would otherwise present.
aws "${AWS_ARGS[@]}" cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username "$EMAIL" \
  --password "$PASSWORD" \
  --permanent

echo
echo "Ready. Open ${SITE_URL} and sign in:"
echo "  user pool : ${POOL_ID}"
echo "  username  : ${EMAIL}"
if [[ -n "${GENERATED:-}" ]]; then
  echo "  password  : ${PASSWORD}"
  echo
  echo "That password was generated here and is not stored anywhere else."
else
  echo "  password  : (the one you supplied)"
fi
echo
echo "A freshly created Cognito prefix domain can take up to a minute to start resolving, so give"
echo "it a moment if the sign-in page 404s on the first attempt."
