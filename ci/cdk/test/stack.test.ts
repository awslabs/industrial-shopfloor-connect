// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { SfcItStack } from '../lib/sfc-it-stack';

/**
 * Regression tests for mistakes that are invisible until a real build fails - each one was found by reading
 * CDK or SFC source, and several shipped in the first version of this stack.
 */
function synth(props: Partial<ConstructorParameters<typeof SfcItStack>[2]> = {}): Template {
  const app = new cdk.App();
  const stack = new SfcItStack(app, 'TestStack', {
    githubRepo: 'awslabs/industrial-shopfloor-connect',
    env: { account: '123456789012', region: 'us-east-1' },
    ...props,
  } as ConstructorParameters<typeof SfcItStack>[2]);
  return Template.fromStack(stack);
}

const T = synth();
// Inline AND managed: a large role policy overflows into AWS::IAM::ManagedPolicy resources when the
// app is not minimizing policies (jest does not load cdk.json's context), so both must be searched.
const policies = JSON.stringify([T.findResources('AWS::IAM::Policy'), T.findResources('AWS::IAM::ManagedPolicy')]);

/** The rendered buildspec. It is an Fn::Join (the bucket name is a token), not a string; treating it as a
 *  string yields "[object Object]" and every toContain() passes vacuously. */
function buildSpecText(template: Template): string {
  const project = Object.values(template.findResources('AWS::CodeBuild::Project'))
    .find((p: any) => p.Properties.Name === 'sfc-integration-test')!;
  const spec = project.Properties.Source.BuildSpec;
  if (typeof spec === 'string') return spec;
  return (spec['Fn::Join'][1] as unknown[]).map((p) => (typeof p === 'string' ? p : '')).join('');
}

describe('destinations: every target except SiteWise Edge is testable right after deploy', () => {
  test('three stack queues: SNS sink, IoT sink, IoT rule errors - the SQS target gets one per case run', () => {
    // A shared target queue keeps no order and every concurrent case run read it: sinks starved.
    T.resourceCountIs('AWS::SQS::Queue', 3);
  });
  test('the project role creates, reads and deletes the per-run queues, and only those', () => {
    expect(policies).toContain('sqs:CreateQueue');
    expect(policies).toContain(':sfc-it-b_*');
    const env = JSON.stringify(T.findResources('AWS::CodeBuild::Project'));
    expect(env).not.toContain('SFC_E2E_SQS_QUEUE_URL');
  });
  test('the janitor deletes leaked per-run queues', () => {
    expect(policies).toContain('sqs:DeleteQueue');
    expect(policies).toContain('sqs:ListQueues');
  });
  test('a provisioned one-shard Kinesis stream exists and is destroyed with the stack', () => {
    T.hasResourceProperties('AWS::Kinesis::Stream', { ShardCount: 1, StreamModeDetails: { StreamMode: 'PROVISIONED' } });
    T.hasResource('AWS::Kinesis::Stream', { DeletionPolicy: 'Delete' });
  });
  test('Firehose is DirectPut with zero buffering', () => {
    T.hasResourceProperties('AWS::KinesisFirehose::DeliveryStream', Match.objectLike({
      DeliveryStreamType: 'DirectPut',
      ExtendedS3DestinationConfiguration: Match.objectLike({ BufferingHints: { IntervalInSeconds: 0, SizeInMBs: 1 } }),
    }));
  });
  test('S3 Tables fixture: one bucket, the sfc_it namespace and two primitive-schema tables', () => {
    T.resourceCountIs('AWS::S3Tables::TableBucket', 1);
    T.hasResourceProperties('AWS::S3Tables::Namespace', { Namespace: 'sfc_it' });
    T.resourceCountIs('AWS::S3Tables::Table', 2);
    T.hasResourceProperties('AWS::S3Tables::Table', Match.objectLike({ TableName: 'sim_b',
      IcebergMetadata: Match.objectLike({ IcebergPartitionSpec: Match.anyValue() }) }));
  });
  test('SiteWise fixture: one model and two assets whose properties carry aliases', () => {
    T.resourceCountIs('AWS::IoTSiteWise::AssetModel', 1);
    T.resourceCountIs('AWS::IoTSiteWise::Asset', 2);
    // Every model property is bound by LogicalId on both assets, under the prefix the cases are given.
    const model = Object.values(T.findResources('AWS::IoTSiteWise::AssetModel'))[0].Properties;
    const project = Object.values(T.findResources('AWS::CodeBuild::Project'))
      .find((p: any) => p.Properties.Name === 'sfc-integration-test')!;
    const env = Object.fromEntries(project.Properties.Environment.EnvironmentVariables.map((v: any) => [v.Name, v.Value]));
    for (const n of [1, 2]) {
      const asset = Object.values(T.findResources('AWS::IoTSiteWise::Asset'))
        .find((a: any) => a.Properties.AssetName === `sfc-it-fixture-asset-${n}`)!;
      expect(asset.Properties.AssetProperties).toEqual(model.AssetModelProperties.map((p: any) =>
        ({ LogicalId: p.LogicalId, Alias: `${env[`SFC_E2E_SW_ALIAS_A${n}`]}/${p.Name}` })));
    }
  });
  test('MSK Provisioned: IAM auth only, TLS, in-cluster encryption, 2 brokers in the 2 public subnets', () => {
    T.resourceCountIs('AWS::MSK::ServerlessCluster', 0);
    const cluster = Object.values(T.findResources('AWS::MSK::Cluster'))[0].Properties;
    expect(cluster.ClientAuthentication).toEqual({ Sasl: { Iam: { Enabled: true } }, Unauthenticated: { Enabled: false } });
    expect(cluster.EncryptionInfo).toEqual({ EncryptionInTransit: { ClientBroker: 'TLS', InCluster: true } });
    expect(cluster.NumberOfBrokerNodes).toBe(2);
    expect(cluster.BrokerNodeGroupInfo.InstanceType).toBe('kafka.m5.large');
    expect(cluster.BrokerNodeGroupInfo.ClientSubnets).toHaveLength(2);
    // Public access cannot be set at creation; the custom resource turns it on afterwards.
    expect(cluster.BrokerNodeGroupInfo.ConnectivityInfo).toBeUndefined();
  });
  test('public access is turned on after creation, and its bootstrap string is a stack output', () => {
    T.resourceCountIs('AWS::CloudFormation::CustomResource', 1);
    T.hasOutput('MskBootstrapPublic', Match.anyValue());
  });
  test('the build project does not wait for MSK: no reference to the cluster or the public-access resource', () => {
    const resources = T.toJSON().Resources;
    const ids = Object.keys(resources).filter((id) => ['AWS::MSK::Cluster', 'AWS::CloudFormation::CustomResource']
      .includes(resources[id].Type));
    const project = Object.values(T.findResources('AWS::CodeBuild::Project')).find((p: any) => p.Properties.Name === 'sfc-integration-test')!;
    const policies = Object.values(T.findResources('AWS::IAM::Policy'))
      .filter((p: any) => JSON.stringify(p.Properties.Roles).includes('SfcItRole'));
    for (const id of ids) {
      expect(JSON.stringify(project)).not.toContain(id);
      for (const p of policies) expect(JSON.stringify(p)).not.toContain(id);
    }
  });
  test('no NAT gateway, no private subnets, and only the public IAM listener 9198 is open', () => {
    T.resourceCountIs('AWS::EC2::NatGateway', 0);
    const sg = Object.values(T.findResources('AWS::EC2::SecurityGroup'))
      .find((r: any) => String(r.Properties.GroupDescription).includes('MSK'))!.Properties;
    expect(sg.SecurityGroupIngress).toEqual([expect.objectContaining({ FromPort: 9198, ToPort: 9198, CidrIp: '0.0.0.0/0' })]);
  });
  test('secret, IoT role alias and device policy exist', () => {
    T.resourceCountIs('AWS::SecretsManager::Secret', 1);
    T.hasResourceProperties('AWS::IoT::RoleAlias', { RoleAlias: 'sfc-it-role-alias', CredentialDurationSeconds: 900 });
  });
});

describe('the build image', () => {
  test('an ECR repository and a privileged image project that builds ci/cdk/image/Dockerfile in AWS', () => {
    T.hasResourceProperties('AWS::ECR::Repository', { RepositoryName: 'sfc-it-ci-image' });
    const image = Object.values(T.findResources('AWS::CodeBuild::Project'))
      .find((p: any) => p.Properties.Name === 'sfc-integration-test-image')!.Properties;
    expect(image.Environment.PrivilegedMode).toBe(true);
    expect(image.Source.BuildSpec).toContain('docker build -f ci/cdk/image/Dockerfile');
  });
  test('the test project runs on the image from that repository, pulled with its service role', () => {
    const test = Object.values(T.findResources('AWS::CodeBuild::Project'))
      .find((p: any) => p.Properties.Name === 'sfc-integration-test')!.Properties;
    expect(test.Environment.ImagePullCredentialsType).toBe('SERVICE_ROLE');
    expect(JSON.stringify(test.Environment.Image)).toContain('CiImageRepo');
    expect(buildSpecText(T)).not.toContain('runtime-versions');
  });
});

describe('the build project', () => {
  test('runs outside any VPC on LARGE compute', () => {
    const project = Object.values(T.findResources('AWS::CodeBuild::Project')).find((p: any) => p.Properties.Name === 'sfc-integration-test')!.Properties;
    expect(project.Environment.ComputeType).toBe('BUILD_GENERAL1_LARGE');
    expect(project.VpcConfig).toBeUndefined();
  });
  test('stack values are baked into its environment', () => {
    T.hasResourceProperties('AWS::CodeBuild::Project', Match.objectLike({
      Environment: Match.objectLike({ EnvironmentVariables: Match.anyValue() }),
    }));
    // arrayWith() is order-sensitive, so each name is checked on its own.
    const env = Object.values(T.findResources('AWS::CodeBuild::Project')).find((p: any) => p.Properties.Name === 'sfc-integration-test')!.Properties.Environment.EnvironmentVariables
      .map((e: { Name: string }) => e.Name);
    for (const name of ['SFC_E2E_BUCKET', 'SFC_E2E_MSK_CLUSTER_NAME', 'SFC_E2E_KINESIS_STREAM', 'SFC_E2E_S3T_BUCKET_ARN',
      'SFC_E2E_FIREHOSE_STREAM', 'SFC_E2E_SW_ALIAS_A1', 'SFC_E2E_SECRET_NAME', 'SFC_E2E_IOT_ROLE_ALIAS']) {
      expect(env).toContain(name);
    }
  });
  test('the same values are exported as the E2eEnvironment output for laptop runs', () => {
    T.hasOutput('E2eEnvironment', Match.anyValue());
  });
  test('an explicit report group exists', () => {
    T.resourceCountIs('AWS::CodeBuild::ReportGroup', 1);
  });
  test('the buildspec has no configuration cache, no clean, cache paths and no CLI flags in GRADLE_OPTS', () => {
    const spec = buildSpecText(T);
    expect(spec).not.toContain('--configuration-cache');
    expect(spec).not.toMatch(/gradlew[^\n"]*\bclean\b/);
    expect(spec).toContain('build-cache-1');
    expect(/"GRADLE_OPTS":\s*"([^"]*)"/.exec(spec)?.[1]).not.toContain('--');
    expect(spec).toContain('chmod +x gradlew');
  });
});

describe('IAM: SFC runs as the project role, so the project role holds the target permissions', () => {
  test('no separate runtime role (the old one was never assumed, so every write was denied)', () => {
    const roles = Object.keys(T.findResources('AWS::IAM::Role'));
    expect(roles.some((r) => r.startsWith('SfcRunRole'))).toBe(false);
  });
  test.each([
    'sqs:SendMessage', 'sns:Publish', 'lambda:InvokeFunction', 'kinesis:PutRecords', 'firehose:PutRecordBatch',
    's3tables:PutTableData', 's3tables:CreateTable', 'iotsitewise:BatchPutAssetPropertyValue', 'iotsitewise:CreateAsset',
    'kafka-cluster:WriteData', 'kafka-cluster:CreateTopic', 'iot:Publish', 'iot:RetainPublish', 'secretsmanager:GetSecretValue',
  ])('grants %s', (action) => {
    expect(policies).toContain(action);
  });
  test('the project role can read any source key, not just the seed zip', () => {
    // Source.s3() grants GetObject on the literal key only; per-run overrides would fail at DOWNLOAD_SOURCE.
    expect(policies).toContain('src/*');
  });
});

describe('teardown and access', () => {
  test('the teardown rule covers every terminal state', () => {
    const patterns = Object.values(T.findResources('AWS::Events::Rule'))
      .map((r) => r.Properties?.EventPattern).filter((p) => p?.detail?.['build-status']);
    expect(patterns).toHaveLength(1);
    expect(patterns[0].detail['build-status']).toEqual(expect.arrayContaining(['SUCCEEDED', 'FAILED', 'STOPPED', 'FAULT', 'TIMED_OUT']));
  });
  test('no OIDC custom resource; an existing provider ARN suppresses creating one', () => {
    T.resourceCountIs('Custom::AWSCDKOpenIdConnectProvider', 0);
    T.resourceCountIs('AWS::IAM::OIDCProvider', 1);
    synth({ oidcProviderArn: 'arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com' })
      .resourceCountIs('AWS::IAM::OIDCProvider', 0);
  });
  test('the CI role may stop a build and its session outlives a queued plus running build', () => {
    expect(policies).toContain('codebuild:StopBuild');
    T.hasResourceProperties('AWS::IAM::Role', Match.objectLike({ MaxSessionDuration: 7200 }));
  });
});
