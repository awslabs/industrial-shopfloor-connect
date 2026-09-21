#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from 'aws-cdk-lib';
import { QueryAppStack } from '../lib/query-app-stack';

const app = new cdk.App();

/** `-c name=a,b` or a JSON array in cdk.json. */
function listContext(key: string): string[] | undefined {
  const raw = app.node.tryGetContext(key);
  if (raw === undefined || raw === null || raw === '') return undefined;
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  return String(raw)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function boolContext(key: string): boolean | undefined {
  const raw = app.node.tryGetContext(key);
  if (raw === undefined || raw === null || raw === '') return undefined;
  return String(raw).toLowerCase() === 'true';
}

function stringContext(key: string): string | undefined {
  const raw = app.node.tryGetContext(key);
  return raw === undefined || raw === null || raw === '' ? undefined : String(raw);
}

const stackName = stringContext('stackName') ?? 'SfcS3TablesDuckDbQueryApp';

new QueryAppStack(app, stackName, {
  stackName,
  description:
    'Cognito-secured CloudFront web app and OpenAPI-defined REST API that query SFC industrial ' +
    'timeseries in Amazon S3 Tables with DuckDB in Lambda',
  env: {
    // The stack must be deployed into a concrete account and region: the OpenAPI document embeds
    // the Lambda invoke URI, and the S3 Tables ARNs are built from both.
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  tableBucketNames: listContext('tableBucketNames'),
  allowAnyTableBucket: boolContext('allowAnyTableBucket'),
  tableBucketRegion: stringContext('tableBucketRegion'),
  allowFreeSql: boolContext('allowFreeSql'),
  devOrigins: listContext('devOrigins'),
  siteOrigin: stringContext('siteOrigin'),
  cognitoDomainPrefix: stringContext('cognitoDomainPrefix'),
});

app.synth();
