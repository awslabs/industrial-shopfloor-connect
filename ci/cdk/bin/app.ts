#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from 'aws-cdk-lib';
import { SfcItStack } from '../lib/sfc-it-stack';

const app = new cdk.App();

// githubRepo scopes the OIDC trust policy, so it has no safe default.
const githubRepo = app.node.tryGetContext('githubRepo') ?? process.env.SFC_IT_GITHUB_REPO;
if (!githubRepo) {
  throw new Error(
    'githubRepo is required: -c githubRepo=owner/repo (or set SFC_IT_GITHUB_REPO).\n' +
    'It is what restricts the CI role to this repository.',
  );
}

// An OIDC provider is account-global. Pass the ARN of the existing one rather than letting the stack
// create a second, which fails with EntityAlreadyExists.
const oidcProviderArn = app.node.tryGetContext('oidcProviderArn') ?? process.env.SFC_IT_OIDC_ARN;

new SfcItStack(app, 'SfcIntegrationTest', {
  githubRepo,
  oidcProviderArn,
  modes: (app.node.tryGetContext('modes') ?? 'inprocess,ipc,uberjar').split(','),
  tiers: (app.node.tryGetContext('tiers') ?? 'core,aws').split(','),
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  description: 'SFC integration test environment: CodeBuild project, target sinks and teardown',
});
