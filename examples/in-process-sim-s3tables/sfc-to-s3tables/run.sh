#!/usr/bin/env bash
set -euo pipefail

export AWS_REGION="${AWS_REGION:-us-west-2}"
echo "Using AWS_REGION=${AWS_REGION}"

export SFC_MODULES_DIR="${SFC_MODULES_DIR:-$(pwd)/modules}"
######################################
# If you built modules from source:  #
# --> Extract tar.gz modules first!! #
######################################
# export SFC_MODULES_DIR="../../build/distribution"
"$SFC_MODULES_DIR/sfc-main/bin/sfc-main" -config simulator-to-s3tables.json
