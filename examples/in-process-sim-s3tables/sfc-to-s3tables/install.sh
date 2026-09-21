#!/usr/bin/env bash
# The wget URL below uses brace expansion, which is a bash feature -- under /bin/sh it would fetch
# one literal brace-laden URL and fail.
export VERSION=$(curl -s "https://api.github.com/repos/awslabs/industrial-shopfloor-connect/tags" | jq -r '.[0].name')
export SFC_MODULES_DIR=$(pwd)/modules

if [ ! -d "$SFC_MODULES_DIR" ]; then
  mkdir -p $SFC_MODULES_DIR
  cd $SFC_MODULES_DIR
  wget https://github.com/awslabs/industrial-shopfloor-connect/releases/download/$VERSION/{aws-s3-tables-target,simulator,debug-target,sfc-main}.tar.gz
  for file in *.tar.gz; do
    tar -xf "$file"
    rm "$file"
  done
  cd -
fi
echo "SFC Modules installed..."
