// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  Aws, CfnOutput, Duration, RemovalPolicy, Stack, StackProps, Tags,
} from 'aws-cdk-lib';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subs from 'aws-cdk-lib/aws-sns-subscriptions';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import * as path from 'path';
import { buildSpec } from './buildspec';

export interface SfcItStackProps extends StackProps {
  /** `owner/repo`, used to scope the GitHub OIDC trust policy. */
  readonly githubRepo: string;
  /**
   * ARN of an existing GitHub OIDC provider. An OIDC provider is account-global, so creating one in a
   * test stack fails with EntityAlreadyExists in any account that has one. Pass the ARN when it exists;
   * leave unset to have the stack create it.
   */
  readonly oidcProviderArn?: string;
  /** Deployment modes the project exercises. */
  readonly modes?: string[];
  /** Tiers the project runs. */
  readonly tiers?: string[];
}

export class SfcItStack extends Stack {
  constructor(scope: Construct, id: string, props: SfcItStackProps) {
    super(scope, id, props);

    const modes = props.modes ?? ['inprocess', 'ipc', 'uberjar'];
    const tiers = props.tiers ?? ['core', 'aws'];

    // Everything is tagged so a cost report can attribute the whole environment, and so a sweep can
    // find strays that escaped the janitor.
    Tags.of(this).add('sfc:purpose', 'integration-test');

    // ------------------------------------------------------------------ storage

    // One bucket, four prefixes. Separate buckets would add IAM surface and deploy time for no benefit,
    // and lifecycle rules give each prefix its own retention.
    const artifacts = new s3.Bucket(this, 'Artifacts', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      // DESTROY, with autoDelete, so tearing the stack down does not strand a randomly-named bucket
      // holding a Gradle cache. The custom resource that autoDelete adds is worth it on a stack that is
      // deployed approximately never.
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        // Source zips: every push uploads one, so these must expire aggressively.
        { id: 'src', prefix: 'src/', expiration: Duration.days(3) },
        { id: 'evidence', prefix: 'evidence/', expiration: Duration.days(14) },
        { id: 'cache', prefix: 'cache/', expiration: Duration.days(30) },
        // The S3 target under test writes here.
        { id: 'run', prefix: 'run/', expiration: Duration.days(2) },
        { id: 'firehose', prefix: 'firehose/', expiration: Duration.days(2) },
        { id: 'abort-multipart', abortIncompleteMultipartUploadAfter: Duration.days(1) },
      ],
    });

    // ------------------------------------------------------------------ AWS-tier sinks
    //
    // One queue per observation path. Sharing a single queue between the SQS target and the SNS
    // fan-out sink would make the SNS assertion unfalsifiable: with rawMessageDelivery the bodies are
    // byte-identical, so nothing distinguishes "arrived via SendMessageBatch" from "arrived via
    // Publish -> fan-out", and the SNS case would pass even with SNS completely broken.

    const sqsTargetQueue = new sqs.Queue(this, 'SqsTargetQueue', {
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.hours(1),
      visibilityTimeout: Duration.seconds(10),
      // 1 MiB. SFC's SQS_MAX_BATCH_MSG_SIZE is 1024*1024 (AwsSqsTargetWriter.kt:416), which matches the
      // limit AWS raised SQS to in August 2025 - see RELEASE NOTES.md for v1.10.1. aws-cdk-lib validates
      // this prop at 1024..1048576, so 1 MiB is legal and the SFC constant is correct.
      maxMessageSizeBytes: 1024 * 1024,
    });

    const snsSinkQueue = new sqs.Queue(this, 'SnsSinkQueue', {
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.hours(1),
      visibilityTimeout: Duration.seconds(10),
    });

    const snsTopic = new sns.Topic(this, 'SnsTargetTopic');
    snsTopic.addSubscription(new subs.SqsSubscription(snsSinkQueue, {
      // Without raw delivery every body is wrapped in an SNS envelope, and the assertion helper would
      // need a second code path purely to unwrap it.
      rawMessageDelivery: true,
    }));

    const iotSinkQueue = new sqs.Queue(this, 'IotSinkQueue', {
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.hours(1),
      visibilityTimeout: Duration.seconds(10),
    });
    const iotErrorQueue = new sqs.Queue(this, 'IotRuleErrorQueue', {
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.hours(1),
    });

    const iotRuleRole = new iam.Role(this, 'IotRuleRole', {
      assumedBy: new iam.ServicePrincipal('iot.amazonaws.com'),
    });
    sqsTargetQueue.grantSendMessages(iotRuleRole);
    iotSinkQueue.grantSendMessages(iotRuleRole);
    iotErrorQueue.grantSendMessages(iotRuleRole);

    // L1 on purpose: the L2 topic-rule construct lives in an alpha module.
    new iot.CfnTopicRule(this, 'IotToSqs', {
      topicRulePayload: {
        awsIotSqlVersion: '2016-03-23',
        // base64 so an arbitrary JSON payload survives the rule intact.
        sql: "SELECT encode(*, 'base64') AS payload, topic() AS topic, timestamp() AS ts FROM 'sfc/it/+/#'",
        actions: [{ sqs: { queueUrl: iotSinkQueue.queueUrl, roleArn: iotRuleRole.roleArn, useBase64: false } }],
        errorAction: { sqs: { queueUrl: iotErrorQueue.queueUrl, roleArn: iotRuleRole.roleArn, useBase64: false } },
        ruleDisabled: false,
      },
    });

    // Long-lived policy; only the certificate is per-run, created and deleted by the harness.
    new iot.CfnPolicy(this, 'SfcItDevicePolicy', {
      policyName: `sfc-it-device-${Aws.REGION}`,
      policyDocument: {
        Version: '2012-10-17',
        Statement: [
          { Effect: 'Allow', Action: ['iot:Connect'], Resource: [`arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:client/sfc_it_*`] },
          { Effect: 'Allow', Action: ['iot:Publish'], Resource: [`arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:topic/sfc/it/*`] },
        ],
      },
    });

    // The Lambda target invokes asynchronously, so the response is never visible to the caller. The only
    // observable is a side effect: this function records what it received.
    const evidenceFn = new lambda.Function(this, 'EvidenceFn', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'evidence.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda')),
      memorySize: 256,
      timeout: Duration.seconds(15),
      // Caps the blast radius if a test ever loops.
      reservedConcurrentExecutions: 10,
      environment: { EVIDENCE_BUCKET: artifacts.bucketName, EVIDENCE_PREFIX: 'evidence-lambda/' },
      logGroup: new logs.LogGroup(this, 'EvidenceFnLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    artifacts.grantPut(evidenceFn, 'evidence-lambda/*');

    // ------------------------------------------------------------------ the runtime role
    //
    // Split from the build role: this one holds only what the adapters and targets actually call at
    // runtime, so a bug in a verifier cannot write to a destination and a bug in a target cannot read
    // the evidence it is about to be judged against.

    const runRole = new iam.Role(this, 'SfcRunRole', {
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      maxSessionDuration: Duration.hours(1),
      description: 'Runtime permissions for the SFC targets under test',
    });
    artifacts.grantPut(runRole, 'run/*');
    sqsTargetQueue.grantSendMessages(runRole);
    snsTopic.grantPublish(runRole);
    evidenceFn.grantInvoke(runRole);
    runRole.addToPolicy(new iam.PolicyStatement({
      actions: ['iot:Publish', 'iot:Connect'],
      resources: [
        `arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:topic/sfc/it/*`,
        `arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:client/sfc_it_*`,
      ],
    }));
    runRole.addToPolicy(new iam.PolicyStatement({
      // DescribeEndpoint has no resource type and must be granted on '*'.
      actions: ['iot:DescribeEndpoint'],
      resources: ['*'],
    }));

    // ------------------------------------------------------------------ CodeBuild

    const projectLogs = new logs.LogGroup(this, 'ProjectLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const project = new codebuild.Project(this, 'SfcIt', {
      projectName: 'sfc-integration-test',
      // The source location is overridden per build with the zip of the working tree, so this is only
      // the default. See the explicit grantRead below - it is load-bearing.
      source: codebuild.Source.s3({ bucket: artifacts, path: 'src/seed.zip' }),
      environment: {
        buildImage: codebuild.LinuxBuildImage.STANDARD_7_0,
        // LARGE, not MEDIUM. gradle.properties asks for a 4 GB Gradle JVM plus a separate 2 GB Kotlin
        // daemon; with 39 modules and a 228 MB shadowJar, 7 GB is not enough headroom.
        computeType: codebuild.ComputeType.LARGE,
      },
      buildSpec: buildSpec({ artifactsBucket: artifacts.bucketName, modes, tiers }),
      cache: codebuild.Cache.bucket(artifacts, { prefix: 'cache' }),
      timeout: Duration.minutes(45),
      queuedTimeout: Duration.minutes(30),
      // Enough that a burst of pushes does not serialise into a queue longer than the timeout, while
      // still bounding spend.
      concurrentBuildLimit: 4,
      logging: { cloudWatch: { logGroup: projectLogs } },
    });

    // MANDATORY. `codebuild.Source.s3()` calls `bucket.grantRead(project, this.path)`, which scopes the
    // role's s3:GetObject to the literal key 'src/seed.zip'. Without this, every build started with
    // --source-location-override fails at DOWNLOAD_SOURCE with AccessDenied.
    artifacts.grantRead(project, 'src/*');
    artifacts.grantReadWrite(project, 'evidence/*');
    artifacts.grantReadWrite(project, 'cache/*');

    project.addToRolePolicy(new iam.PolicyStatement({
      // Needed for the `reports` block in the buildspec to publish per-case results.
      actions: [
        'codebuild:CreateReportGroup', 'codebuild:CreateReport',
        'codebuild:UpdateReport', 'codebuild:BatchPutTestCases', 'codebuild:BatchPutCodeCoverages',
      ],
      resources: [`arn:aws:codebuild:${Aws.REGION}:${Aws.ACCOUNT_ID}:report-group/sfc-integration-test-*`],
    }));
    // The build assumes the narrower runtime role for the target processes.
    runRole.grantAssumeRole(project.grantPrincipal);

    // Verification permissions: reading destinations to prove data arrived, and per-run provisioning.
    project.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'sqs:ReceiveMessage', 'sqs:DeleteMessage', 'sqs:DeleteMessageBatch', 'sqs:GetQueueAttributes',
      ],
      resources: [sqsTargetQueue.queueArn, snsSinkQueue.queueArn, iotSinkQueue.queueArn, iotErrorQueue.queueArn],
    }));
    artifacts.grantRead(project, 'run/*');
    artifacts.grantRead(project, 'firehose/*');
    artifacts.grantRead(project, 'evidence-lambda/*');
    project.addToRolePolicy(new iam.PolicyStatement({
      // Per-run IoT certificate for the SiteWise Edge / IoT Core cases.
      actions: [
        'iot:CreateKeysAndCertificate', 'iot:AttachPolicy', 'iot:DetachPolicy',
        'iot:UpdateCertificate', 'iot:DeleteCertificate', 'iot:DescribeEndpoint',
        'iot:ListRetainedMessages',
      ],
      resources: ['*'],
    }));
    project.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iot:DeleteRetainedMessage'],
      resources: [`arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:topic/sfc/it/*`],
    }));

    // ------------------------------------------------------------------ teardown

    // The authoritative teardown. post_build is skipped on TIMED_OUT and on a stopped build, which are
    // precisely the cases that leak, so cleanup is driven by the build's terminal state instead.
    const janitor = new lambda.Function(this, 'Janitor', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'janitor.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda')),
      timeout: Duration.minutes(5),
      environment: { PROJECT_NAME: project.projectName, MAX_AGE_SECONDS: '7200' },
      logGroup: new logs.LogGroup(this, 'JanitorLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    janitor.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'iot:ListRetainedMessages', 'iot:ListCertificates', 'iot:DetachPolicy',
        'iot:UpdateCertificate', 'iot:DeleteCertificate',
      ],
      resources: ['*'],
    }));
    janitor.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iot:DeleteRetainedMessage'],
      resources: [`arn:aws:iot:${Aws.REGION}:${Aws.ACCOUNT_ID}:topic/sfc/it/*`],
    }));
    janitor.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cloudwatch:PutMetricData'],
      resources: ['*'],
    }));

    new events.Rule(this, 'OnBuildTerminal', {
      eventPattern: {
        source: ['aws.codebuild'],
        detailType: ['CodeBuild Build State Change'],
        detail: {
          'project-name': [project.projectName],
          'build-status': ['SUCCEEDED', 'FAILED', 'STOPPED', 'FAULT', 'TIMED_OUT'],
        },
      },
      targets: [new targets.LambdaFunction(janitor)],
    });

    // Backstop for anything the event-driven path missed.
    new events.Rule(this, 'HourlySweep', {
      schedule: events.Schedule.rate(Duration.hours(1)),
      targets: [new targets.LambdaFunction(janitor, {
        event: events.RuleTargetInput.fromObject({ mode: 'age' }),
      })],
    });

    // ------------------------------------------------------------------ GitHub OIDC

    const oidcArn = props.oidcProviderArn
      ?? new iam.OidcProviderNative(this, 'GithubOidc', {
        // OidcProviderNative emits a plain AWS::IAM::OIDCProvider. The older
        // iam.OpenIdConnectProvider L2 is implemented as a custom resource
        // (Custom::AWSCDKOpenIdConnectProvider) backed by a bundled Lambda, which this stack has no
        // reason to carry.
        url: 'https://token.actions.githubusercontent.com',
        clientIds: ['sts.amazonaws.com'],
      }).oidcProviderArn;

    const ciRole = new iam.Role(this, 'SfcItCiRole', {
      // WebIdentityPrincipal with the ARN directly, so this works identically whether the provider was
      // created here or passed in.
      assumedBy: new iam.WebIdentityPrincipal(oidcArn, {
        StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
        // Any branch of this repository, deliberately: the requirement is that every push is tested.
        StringLike: { 'token.actions.githubusercontent.com:sub': `repo:${props.githubRepo}:*` },
      }),
      description: 'Assumed from GitHub Actions to upload source and start a build',
      maxSessionDuration: Duration.hours(1),
    });
    artifacts.grantPut(ciRole, 'src/*');
    artifacts.grantRead(ciRole, 'evidence/*');
    ciRole.addToPolicy(new iam.PolicyStatement({
      // StopBuild matters: without it, cancelling the Actions job orphans a build that keeps running
      // and collides with the build the next push starts.
      actions: ['codebuild:StartBuild', 'codebuild:BatchGetBuilds', 'codebuild:StopBuild'],
      resources: [project.projectArn],
    }));
    ciRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:GetLogEvents', 'logs:DescribeLogStreams'],
      resources: [projectLogs.logGroupArn, `${projectLogs.logGroupArn}:*`],
    }));

    // ------------------------------------------------------------------ outputs

    new CfnOutput(this, 'ArtifactsBucket', { value: artifacts.bucketName });
    new CfnOutput(this, 'ProjectName', { value: project.projectName });
    new CfnOutput(this, 'CiRoleArn', { value: ciRole.roleArn });
    new CfnOutput(this, 'RunRoleArn', { value: runRole.roleArn });
    new CfnOutput(this, 'SqsTargetQueueUrl', { value: sqsTargetQueue.queueUrl });
    new CfnOutput(this, 'SnsTargetTopicArn', { value: snsTopic.topicArn });
    new CfnOutput(this, 'SnsSinkQueueUrl', { value: snsSinkQueue.queueUrl });
    new CfnOutput(this, 'IotSinkQueueUrl', { value: iotSinkQueue.queueUrl });
    new CfnOutput(this, 'EvidenceFunctionName', { value: evidenceFn.functionName });
    new CfnOutput(this, 'LogGroupName', { value: projectLogs.logGroupName });
  }
}
