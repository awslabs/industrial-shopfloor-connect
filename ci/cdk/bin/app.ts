#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from 'aws-cdk-lib';
import { SfcItStack } from '../lib/sfc-it-stack';

const app = new cdk.App();

// githubRepo scopes the OIDC trust policy of the CI role to this repository (any branch). Override with
// -c githubRepo=owner/repo or SFC_IT_GITHUB_REPO, e.g. for a fork.
const githubRepo: string = app.node.tryGetContext('githubRepo')
  ?? process.env.SFC_IT_GITHUB_REPO
  ?? 'awslabs/industrial-shopfloor-connect';

// An OIDC provider is account-global. Pass the ARN of the existing one rather than letting the stack
// create a second, which fails with EntityAlreadyExists.
const oidcProviderArn = app.node.tryGetContext('oidcProviderArn') ?? process.env.SFC_IT_OIDC_ARN;

// Optional: restrict the MSK public IAM listener to these CIDRs (comma-separated). Default: anywhere.
const mskIngressCidrs = (app.node.tryGetContext('mskIngressCidrs') ?? process.env.SFC_IT_MSK_INGRESS_CIDRS ?? '')
  .split(',').map((c: string) => c.trim()).filter(Boolean);

new SfcItStack(app, 'SfcIntegrationTest', {
  githubRepo,
  oidcProviderArn,
  mskIngressCidrs: mskIngressCidrs.length ? mskIngressCidrs : undefined,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  description: 'SFC integration test environment: CodeBuild project, target sinks and teardown',
});
