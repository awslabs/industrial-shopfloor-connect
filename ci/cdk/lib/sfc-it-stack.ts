// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  Aws, CfnOutput, CustomResource, Duration, RemovalPolicy, Size, Stack, StackProps, Tags,
} from 'aws-cdk-lib';
import * as codebuild from 'aws-cdk-lib/aws-codebuild';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as sitewise from 'aws-cdk-lib/aws-iotsitewise';
import * as kinesis from 'aws-cdk-lib/aws-kinesis';
import * as firehose from 'aws-cdk-lib/aws-kinesisfirehose';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as msk from 'aws-cdk-lib/aws-msk';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3tables from 'aws-cdk-lib/aws-s3tables';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subs from 'aws-cdk-lib/aws-sns-subscriptions';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import * as path from 'path';
import { buildSpec } from './buildspec';

export interface SfcItStackProps extends StackProps {
  /** `owner/repo`; scopes the GitHub OIDC trust policy. */
  readonly githubRepo: string;
  /**
   * ARN of an existing GitHub OIDC provider. A provider is account-global, so creating a second one fails
   * with EntityAlreadyExists. Pass the ARN when one exists; leave unset to have the stack create it.
   */
  readonly oidcProviderArn?: string;
  /**
   * CIDRs allowed to reach the MSK cluster's public IAM listener (9198). The default, anywhere, is what
   * CodeBuild outside a VPC and a developer laptop need; access is still IAM-authenticated over TLS.
   */
  readonly mskIngressCidrs?: string[];
}

/** Names the suite relies on. Kept together because the runner, the janitor and the cases all use them. */
const NAMES = {
  project: 'sfc-integration-test',
  imageProject: 'sfc-integration-test-image',
  imageRepo: 'sfc-it-ci-image',
  plcSimProject: 'sfc-integration-test-plc-sim',
  plcSimPrefix: 'plc-sim',
  msk: 'sfc-it-msk',
  tableBucketPrefix: 'sfc-it-fixture',
  namespace: 'sfc_it',
  tableA: 'sim_a',
  tableB: 'sim_b',
  assetModel: 'sfc-it-fixture-model',
  roleAlias: 'sfc-it-role-alias',
  cwNamespace: 'SFC-IT',
  secret: 'sfc-it/secret',
};

/**
 * Everything the SFC integration suite needs, ready right after `cdk deploy`:
 * a destination for every target except SiteWise Edge, a CodeBuild project that builds the working tree
 * and runs the suite in all three deployment modes, and the teardown that removes what each run created.
 */
export class SfcItStack extends Stack {
  constructor(scope: Construct, id: string, props: SfcItStackProps) {
    super(scope, id, props);
    Tags.of(this).add('sfc:purpose', 'integration-test');

    // ------------------------------------------------------------------------------------- storage
    // One bucket, one prefix per purpose, each with its own retention.
    const artifacts = new s3.Bucket(this, 'Artifacts', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      // DESTROY + autoDelete, so a teardown does not strand a randomly named bucket holding a Gradle cache.
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        { id: 'src', prefix: 'src/', expiration: Duration.days(3) },
        { id: 'evidence', prefix: 'evidence/', expiration: Duration.days(14) },
        { id: 'cache', prefix: 'cache/', expiration: Duration.days(30) },
        // Built PLC simulator binaries, one per crate hash; an expired one is simply rebuilt.
        { id: 'plc-sim', prefix: `${NAMES.plcSimPrefix}/`, expiration: Duration.days(90) },
        { id: 's3-target', prefix: 's3-target/', expiration: Duration.days(2) },
        { id: 'firehose', prefix: 'firehose/', expiration: Duration.days(2) },
        { id: 'lambda-evidence', prefix: 'lambda-evidence/', expiration: Duration.days(2) },
        { id: 'abort-multipart', abortIncompleteMultipartUploadAfter: Duration.days(1) },
      ],
    });

    // ---------------------------------------------------------------------------------- network + MSK
    // MSK Provisioned with public access, the endpoint SFC's MSK target uses from outside AWS
    // (docs/targets/aws-msk.md: BootstrapBrokerStringPublicSaslIam). Public access needs public subnets,
    // IAM (or SCRAM/mTLS) auth, encryption in the cluster and no plaintext
    // (https://docs.aws.amazon.com/msk/latest/developerguide/public-access.html). The VPC holds only the
    // brokers: no NAT, and the build runs outside it.
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [{ name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 }],
    });
    const mskSg = new ec2.SecurityGroup(this, 'MskSg', { vpc, description: 'SFC integration-test MSK, public IAM listener' });
    for (const cidr of props.mskIngressCidrs ?? ['0.0.0.0/0']) {
      // 9198: public access with IAM authentication (MSK port information).
      mskSg.addIngressRule(ec2.Peer.ipv4(cidr), ec2.Port.tcp(9198), 'Kafka over IAM, public');
    }

    const mskCluster = new msk.CfnCluster(this, 'Msk', {
      clusterName: NAMES.msk,
      kafkaVersion: '3.6.0',
      numberOfBrokerNodes: 2,
      brokerNodeGroupInfo: {
        instanceType: 'kafka.m5.large',
        clientSubnets: vpc.publicSubnets.map((sn) => sn.subnetId),
        securityGroups: [mskSg.securityGroupId],
        storageInfo: { ebsStorageInfo: { volumeSize: 10 } },
      },
      clientAuthentication: { sasl: { iam: { enabled: true } }, unauthenticated: { enabled: false } },
      encryptionInfo: { encryptionInTransit: { clientBroker: 'TLS', inCluster: true } },
    });

    // AWS does not allow public access at creation time; this resource turns it on afterwards and returns
    // the public bootstrap string. UpdateConnectivity takes many minutes, hence the polling provider.
    const mskPublicHandler = (handler: string) => new lambda.Function(this, `MskPublic${handler}`, {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: `msk_public.${handler === 'Event' ? 'on_event' : 'is_complete'}`,
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda'), { exclude: ['__pycache__', '*.pyc'] }),
      timeout: Duration.minutes(1),
      logGroup: new logs.LogGroup(this, `MskPublic${handler}Logs`, { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY }),
    });
    const onEvent = mskPublicHandler('Event');
    const isComplete = mskPublicHandler('Complete');
    for (const fn of [onEvent, isComplete]) {
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ['kafka:DescribeClusterV2', 'kafka:UpdateConnectivity', 'kafka:GetBootstrapBrokers'],
        resources: [mskCluster.attrArn],
      }));
      // The EC2 validation calls MSK makes on the caller's behalf (AWS managed policy AmazonMSKFullAccess);
      // the public IPs themselves are allocated by MSK's service-linked role.
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ['ec2:DescribeSubnets', 'ec2:DescribeVpcs', 'ec2:DescribeSecurityGroups', 'ec2:DescribeRouteTables',
          'ec2:DescribeVpcEndpoints', 'ec2:DescribeVpcAttribute'],
        resources: ['*'],
      }));
    }
    const mskPublic = new CustomResource(this, 'MskPublicAccess', {
      serviceToken: new cr.Provider(this, 'MskPublicProvider', {
        onEventHandler: onEvent,
        isCompleteHandler: isComplete,
        queryInterval: Duration.minutes(1),
        totalTimeout: Duration.hours(2),
      }).serviceToken,
      properties: { ClusterArn: mskCluster.attrArn },
    });

    // ----------------------------------------------------------------------------- AWS destinations
    // One queue per observation path. A queue shared by the SQS target and the SNS fan-out would make the
    // SNS check unfalsifiable: with raw delivery the bodies are identical, so the SNS case would pass even
    // with SNS broken.
    const queue = (qid: string, extra: Partial<sqs.QueueProps> = {}) => new sqs.Queue(this, qid, {
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      retentionPeriod: Duration.hours(1),
      visibilityTimeout: Duration.seconds(10),
      ...extra,
    });
    // The SQS target writes to a queue of each case run's own, sfc-it-<marker>, which the sqs sink creates
    // and deletes (ci/e2e/lib/sinks/aws.py): a standard queue keeps no order, so it is read to the end, and
    // that only works for a queue nothing else reads.
    const runQueues = `arn:${Aws.PARTITION}:sqs:${Aws.REGION}:${Aws.ACCOUNT_ID}:sfc-it-b_*`;
    const snsSink = queue('SnsSinkQueue');
    const iotSink = queue('IotSinkQueue');
    const iotErrors = queue('IotRuleErrorQueue');

    const topic = new sns.Topic(this, 'SnsTargetTopic');
    topic.addSubscription(new subs.SqsSubscription(snsSink, { rawMessageDelivery: true }));

    const iotRuleRole = new iam.Role(this, 'IotRuleRole', { assumedBy: new iam.ServicePrincipal('iot.amazonaws.com') });
    iotSink.grantSendMessages(iotRuleRole);
    iotErrors.grantSendMessages(iotRuleRole);
    new iot.CfnTopicRule(this, 'IotToSqs', {
      topicRulePayload: {
        awsIotSqlVersion: '2016-03-23',
        // base64 so an arbitrary payload survives the rule unchanged.
        sql: "SELECT encode(*, 'base64') AS payload, topic() AS topic, timestamp() AS ts FROM 'sfc/it/#'",
        actions: [{ sqs: { queueUrl: iotSink.queueUrl, roleArn: iotRuleRole.roleArn, useBase64: false } }],
        errorAction: { sqs: { queueUrl: iotErrors.queueUrl, roleArn: iotRuleRole.roleArn, useBase64: false } },
        ruleDisabled: false,
      },
    });

    const stream = new kinesis.Stream(this, 'KinesisTargetStream', {
      streamMode: kinesis.StreamMode.PROVISIONED,
      shardCount: 1,
      retentionPeriod: Duration.hours(24),
      encryption: kinesis.StreamEncryption.MANAGED,
      removalPolicy: RemovalPolicy.DESTROY, // the default is RETAIN
    });

    const deliveryStream = new firehose.DeliveryStream(this, 'FirehoseTargetStream', {
      // No source: DirectPut, the only stream type that accepts PutRecordBatch.
      destination: new firehose.S3Bucket(artifacts, {
        dataOutputPrefix: 'firehose/data/',
        errorOutputPrefix: 'firehose/err/!{firehose:error-output-type}/',
        // 0 s: CDK and the service accept zero buffering without dynamic partitioning, which turns a
        // 60 s+ wait per case into seconds.
        bufferingInterval: Duration.seconds(0),
        bufferingSize: Size.mebibytes(1),
      }),
    });

    // The Lambda target invokes asynchronously; a side effect is the only observable.
    const evidenceFn = new lambda.Function(this, 'EvidenceFn', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'evidence.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda'), { exclude: ['__pycache__', '*.pyc'] }),
      memorySize: 256,
      timeout: Duration.seconds(15),
      environment: { EVIDENCE_BUCKET: artifacts.bucketName, EVIDENCE_PREFIX: 'lambda-evidence/' },
      logGroup: new logs.LogGroup(this, 'EvidenceFnLogs', { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY }),
    });
    artifacts.grantPut(evidenceFn, 'lambda-evidence/*');

    // S3 Tables fixture: one bucket, one namespace, two tables with primitive-only schemas. SFC validates an
    // existing table's schema strictly, and its nested-field ids come from a JVM-global counter, so nested
    // fixture types would never match.
    const tableBucketName = `${NAMES.tableBucketPrefix}-${Aws.ACCOUNT_ID}`;
    const tableBucket = new s3tables.CfnTableBucket(this, 'TableBucket', { tableBucketName });
    const namespace = new s3tables.CfnNamespace(this, 'TableNamespace', {
      tableBucketArn: tableBucket.attrTableBucketArn,
      namespace: NAMES.namespace,
    });
    const schemaFieldList = [
      { id: 1, name: 'event_time', type: 'timestamptz', required: true },
      { id: 2, name: 'counter', type: 'int', required: true },
      { id: 3, name: 'value', type: 'double', required: true },
      { id: 4, name: 'label', type: 'string', required: true },
      { id: 5, name: 'ok', type: 'boolean', required: true },
    ];
    const fixtureTable = (tid: string, tableName: string, partitioned: boolean) => {
      const t = new s3tables.CfnTable(this, tid, {
        tableBucketArn: tableBucket.attrTableBucketArn,
        namespace: NAMES.namespace,
        tableName,
        openTableFormat: 'ICEBERG',
        icebergMetadata: {
          icebergSchema: { schemaFieldList },
          ...(partitioned ? { icebergPartitionSpec: { fields: [{ sourceId: 1, transform: 'day', name: 'event_time_day' }] } } : {}),
        },
      });
      // namespace is passed as a literal string, so there is no implicit dependency on the namespace resource.
      t.addResourceDependency(namespace);
      return t;
    };
    fixtureTable('TableSimA', NAMES.tableA, false);
    fixtureTable('TableSimB', NAMES.tableB, true);

    // SiteWise fixture: one model, two assets whose measurements carry aliases. Tests write by alias.
    // One definition of the alias prefix, used for the assets and for the environment the cases read.
    const swAliasBase = (n: number) => `/sfc-it/fixture/a${n}`;
    const props4 = [
      { logicalId: 'counter', name: 'counter', dataType: 'INTEGER' },
      { logicalId: 'value', name: 'value', dataType: 'DOUBLE' },
      { logicalId: 'label', name: 'label', dataType: 'STRING' },
      { logicalId: 'ok', name: 'ok', dataType: 'BOOLEAN' },
    ];
    const model = new sitewise.CfnAssetModel(this, 'SiteWiseModel', {
      assetModelName: NAMES.assetModel,
      assetModelProperties: props4.map((p) => ({ ...p, type: { typeName: 'Measurement' } })),
    });
    const assets = [1, 2].map((n) => new sitewise.CfnAsset(this, `SiteWiseAsset${n}`, {
      assetName: `sfc-it-fixture-asset-${n}`,
      assetModelId: model.attrAssetModelId,
      assetProperties: props4.map((p) => ({ logicalId: p.logicalId, alias: `${swAliasBase(n)}/${p.name}` })),
    }));

    const secret = new secretsmanager.Secret(this, 'Secret', {
      secretName: NAMES.secret,
      generateSecretString: { excludePunctuation: true, passwordLength: 32 },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // AWS IoT credential provider: a role the IoT credentials endpoint can vend, behind a role alias. The
    // per-run device certificate is created by the case and deleted afterwards.
    const iotCredRole = new iam.Role(this, 'IotCredentialRole', { assumedBy: new iam.ServicePrincipal('credentials.iot.amazonaws.com') });
    iotCredRole.addToPolicy(new iam.PolicyStatement({ actions: ['sqs:SendMessage'], resources: [runQueues] }));
    const roleAlias = new iot.CfnRoleAlias(this, 'RoleAlias', {
      roleAlias: NAMES.roleAlias, roleArn: iotCredRole.roleArn, credentialDurationSeconds: 900,
    });
    const devicePolicyName = `sfc-it-device-${Aws.REGION}`;
    new iot.CfnPolicy(this, 'DevicePolicy', {
      policyName: devicePolicyName,
      policyDocument: {
        Version: '2012-10-17',
        Statement: [{ Effect: 'Allow', Action: ['iot:AssumeRoleWithCertificate'], Resource: [roleAlias.attrRoleAliasArn] }],
      },
    });

    // ------------------------------------------------------------------------------- environment
    // One dictionary, used twice: as the CodeBuild environment and as the E2eEnvironment output that a
    // laptop run reads from `cdk deploy --outputs-file ci/cdk/outputs.json`.
    const e2eEnv: Record<string, string> = {
      SFC_E2E_BUCKET: artifacts.bucketName,
      SFC_E2E_REGION: Aws.REGION,
      SFC_E2E_ACCOUNT: Aws.ACCOUNT_ID,
      SFC_E2E_SNS_TOPIC_ARN: topic.topicArn,
      SFC_E2E_SNS_SINK_QUEUE_URL: snsSink.queueUrl,
      SFC_E2E_IOT_SINK_QUEUE_URL: iotSink.queueUrl,
      SFC_E2E_IOT_ERROR_QUEUE_URL: iotErrors.queueUrl,
      SFC_E2E_KINESIS_STREAM: stream.streamName,
      SFC_E2E_FIREHOSE_STREAM: deliveryStream.deliveryStreamName,
      SFC_E2E_LAMBDA_FUNCTION: evidenceFn.functionName,
      SFC_E2E_S3T_BUCKET: tableBucketName,
      SFC_E2E_S3T_BUCKET_ARN: tableBucket.attrTableBucketArn,
      SFC_E2E_S3T_NAMESPACE: NAMES.namespace,
      SFC_E2E_S3T_TABLE_A: NAMES.tableA,
      SFC_E2E_S3T_TABLE_B: NAMES.tableB,
      SFC_E2E_SW_MODEL_ID: model.attrAssetModelId,
      SFC_E2E_SW_ASSET_A1_ID: assets[0].attrAssetId,
      SFC_E2E_SW_ASSET_A2_ID: assets[1].attrAssetId,
      SFC_E2E_SW_ALIAS_A1: swAliasBase(1),
      SFC_E2E_SW_ALIAS_A2: swAliasBase(2),
      // The cluster's name only, fixed at synth time: the harness looks up the ARN and the public bootstrap
      // brokers when it runs, so the build project does not wait for MSK to be created.
      SFC_E2E_MSK_CLUSTER_NAME: NAMES.msk,
      SFC_E2E_SECRET_NAME: NAMES.secret,
      SFC_E2E_SECRET_ARN: secret.secretArn,
      SFC_E2E_IOT_ROLE_ALIAS: NAMES.roleAlias,
      SFC_E2E_IOT_DEVICE_POLICY: devicePolicyName,
      SFC_E2E_CW_NAMESPACE: NAMES.cwNamespace,
    };

    // ------------------------------------------------------------------------------------- build
    const projectLogs = new logs.LogGroup(this, 'ProjectLogs', { retention: logs.RetentionDays.TWO_WEEKS, removalPolicy: RemovalPolicy.DESTROY });
    const reportGroup = new codebuild.ReportGroup(this, 'ReportGroup', {
      reportGroupName: `${NAMES.project}-e2e`,
      removalPolicy: RemovalPolicy.DESTROY,
      deleteReports: true,
    });

    // The build image (ci/cdk/image/Dockerfile): every tool and counterpart preinstalled, so a test build
    // spends its time building and testing. It is built in AWS by its own CodeBuild project, from the same
    // uploaded working tree; ci/start-build.sh runs that build first whenever ECR has no image for the
    // current Dockerfile and its inputs (tagged by their hash), then runs the test build on exactly that tag.
    const imageRepo = new ecr.Repository(this, 'CiImageRepo', {
      repositoryName: NAMES.imageRepo,
      removalPolicy: RemovalPolicy.DESTROY,
      emptyOnDelete: true,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
    const imageProject = new codebuild.Project(this, 'CiImageBuild', {
      projectName: NAMES.imageProject,
      source: codebuild.Source.s3({ bucket: artifacts, path: 'src/seed.zip' }),
      environment: {
        buildImage: codebuild.LinuxBuildImage.STANDARD_7_0,
        computeType: codebuild.ComputeType.MEDIUM,
        privileged: true, // docker build
        environmentVariables: { REPO_URI: { value: imageRepo.repositoryUri }, IMAGE_TAG: { value: 'latest' } },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: '0.2',
        env: { shell: 'bash' },
        phases: {
          pre_build: {
            commands: [
              'set -euo pipefail',
              'aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}"',
            ],
          },
          build: {
            commands: [
              'set -euo pipefail',
              'docker build -f ci/cdk/image/Dockerfile -t "$REPO_URI:$IMAGE_TAG" -t "$REPO_URI:latest" ci',
              'docker push "$REPO_URI:$IMAGE_TAG"',
              'docker push "$REPO_URI:latest"',
            ],
          },
        },
      }),
      timeout: Duration.minutes(60),
      logging: { cloudWatch: { logGroup: projectLogs } },
    });
    artifacts.grantRead(imageProject, 'src/*');
    imageRepo.grantPullPush(imageProject);

    // The PLC simulator (ci/omni-plc-sim), the counterpart of the S7, ADS, PCCC, SLMP and Modbus cases. It
    // is built here in AWS from the uploaded working tree - compiled and tested in the crate's Dockerfile -
    // and stored as a static binary under plc-sim/<hash>/. ci/start-build.sh builds it only when S3 has no
    // binary for the crate's current hash, and the test build downloads exactly that one.
    const plcSimProject = new codebuild.Project(this, 'PlcSimBuild', {
      projectName: NAMES.plcSimProject,
      source: codebuild.Source.s3({ bucket: artifacts, path: 'src/seed.zip' }),
      environment: {
        buildImage: codebuild.LinuxBuildImage.STANDARD_7_0,
        computeType: codebuild.ComputeType.MEDIUM,
        privileged: true, // docker build
        environmentVariables: { BUCKET: { value: artifacts.bucketName }, SIM_TAG: { value: 'unset' } },
      },
      buildSpec: codebuild.BuildSpec.fromObject({
        version: '0.2',
        env: { shell: 'bash' },
        phases: {
          build: {
            commands: [
              'set -euo pipefail',
              'DOCKER_BUILDKIT=1 docker build -f ci/omni-plc-sim/Dockerfile --target export --output type=local,dest=out ci/omni-plc-sim',
              'out/omni-plc-sim --version',
              `aws s3 cp out/omni-plc-sim "s3://$BUCKET/${NAMES.plcSimPrefix}/$SIM_TAG/omni-plc-sim" --only-show-errors`,
            ],
          },
        },
      }),
      timeout: Duration.minutes(30),
      logging: { cloudWatch: { logGroup: projectLogs } },
    });
    artifacts.grantRead(plcSimProject, 'src/*');
    artifacts.grantPut(plcSimProject, `${NAMES.plcSimPrefix}/*`);

    const project = new codebuild.Project(this, 'SfcIt', {
      projectName: NAMES.project,
      // Overridden per build with the zip of the working tree; this is only the default. See the explicit
      // grantRead below - it is load-bearing.
      source: codebuild.Source.s3({ bucket: artifacts, path: 'src/seed.zip' }),
      environment: {
        // The default only: ci/start-build.sh overrides it with the tag that matches the tree under test.
        buildImage: codebuild.LinuxBuildImage.fromEcrRepository(imageRepo, 'latest'),
        // LARGE: gradle.properties asks for a 4 GB Gradle JVM plus a 2 GB Kotlin daemon, and the suite runs
        // up to eight SFC JVMs in parallel.
        computeType: codebuild.ComputeType.LARGE,
        environmentVariables: Object.fromEntries(Object.entries(e2eEnv).map(([k, v]) => [k, { value: v }])),
      },
      buildSpec: buildSpec({ artifactsBucket: artifacts.bucketName, reportGroupArn: reportGroup.reportGroupArn }),
      cache: codebuild.Cache.bucket(artifacts, { prefix: 'cache' }),
      timeout: Duration.hours(5),
      queuedTimeout: Duration.minutes(10),
      concurrentBuildLimit: 4,
      logging: { cloudWatch: { logGroup: projectLogs } },
    });
    reportGroup.grantWrite(project);

    // ------------------------------------------------------------------------------------- IAM
    // Everything sits on the project role: SFC processes inherit the container credentials (the default
    // chain), so a separate runtime role would have to be assumed and plumbed into every process - the
    // previous version had one that nothing assumed, and every AWS target write was denied.
    // MANDATORY: Source.s3() scopes GetObject to the literal 'src/seed.zip'; every real build overrides
    // the location to a per-run key.
    artifacts.grantRead(project, 'src/*');
    artifacts.grantRead(project, `${NAMES.plcSimPrefix}/*`); // the simulator binary, fetched in the install phase
    artifacts.grantReadWrite(project, 'evidence/*');
    artifacts.grantReadWrite(project, 'cache/*');
    artifacts.grantReadWrite(project, 's3-target/*');
    artifacts.grantRead(project, 'firehose/*');
    artifacts.grantRead(project, 'lambda-evidence/*');

    for (const q of [snsSink, iotSink, iotErrors]) {
      q.grantConsumeMessages(project);
    }
    topic.grantPublish(project);
    evidenceFn.grantInvoke(project);
    stream.grantReadWrite(project);
    deliveryStream.grantPutRecords(project);
    secret.grantRead(project);

    const role = project.role!;
    // AWS-S3-NEG-01: one prefix the project role must not write. Cache.bucket() grants read/write on the whole
    // bucket (bucket.grantReadWrite(project)), so only an explicit Deny can close a prefix.
    role.addToPrincipalPolicy(new iam.PolicyStatement({
      effect: iam.Effect.DENY, actions: ['s3:PutObject'], resources: [artifacts.arnForObjects('s3-target/*/denied/*')],
    }));
    const allow = (actions: string[], resources: string[], conditions?: Record<string, unknown>) =>
      role.addToPrincipalPolicy(new iam.PolicyStatement({ actions, resources, conditions }));
    const arn = (service: string, resource: string) => `arn:${Aws.PARTITION}:${service}:${Aws.REGION}:${Aws.ACCOUNT_ID}:${resource}`;

    // SQS target: the per-run queues (sfc-it-b_<run>_<case>_<mode>) the sqs sink creates, reads and deletes.
    allow(['sqs:CreateQueue', 'sqs:DeleteQueue', 'sqs:GetQueueAttributes', 'sqs:GetQueueUrl', 'sqs:SendMessage',
      'sqs:ReceiveMessage', 'sqs:DeleteMessage', 'sqs:ChangeMessageVisibility'], [runQueues]);

    // IoT Core target (HTTP data plane, endpoint from DescribeEndpoint) and its retained-message cleanup.
    // A retained message is deleted by a zero-byte retained publish; there is no DeleteRetainedMessage action.
    allow(['iot:Publish', 'iot:RetainPublish', 'iot:GetRetainedMessage'], [arn('iot', 'topic/sfc/it/*')]);
    allow(['iot:DescribeEndpoint', 'iot:ListRetainedMessages'], ['*']);
    // IoT credential provider case: a per-run certificate.
    allow(['iot:CreateKeysAndCertificate', 'iot:UpdateCertificate', 'iot:DeleteCertificate', 'iot:ListAttachedPolicies'], ['*']);
    allow(['iot:AttachPolicy', 'iot:DetachPolicy'], [arn('iot', `policy/${devicePolicyName}`)]);

    // S3 Tables: fixture bucket plus per-run buckets named sfc-it-b-*.
    const fixtureBucketArn = tableBucket.attrTableBucketArn;
    const runBucketArn = arn('s3tables', 'bucket/sfc-it-b-*');
    allow(['s3tables:ListTableBuckets'], ['*']);
    allow(['s3tables:GetTableBucket', 's3tables:ListNamespaces', 's3tables:GetNamespace', 's3tables:ListTables',
      's3tables:CreateNamespace', 's3tables:DeleteNamespace', 's3tables:CreateTable'], [fixtureBucketArn, runBucketArn]);
    allow(['s3tables:CreateTableBucket', 's3tables:DeleteTableBucket'], [runBucketArn]);
    allow(['s3tables:GetTable', 's3tables:GetTableMetadataLocation', 's3tables:GetTableData', 's3tables:PutTableData',
      's3tables:UpdateTableMetadataLocation', 's3tables:CreateTable', 's3tables:DeleteTable'],
    [`${fixtureBucketArn}/table/*`, `${runBucketArn}/table/*`]);

    // SiteWise: alias writes, AssetCreation (the helper scans the whole account, so List/Describe need '*'),
    // verification and cleanup.
    allow(['iotsitewise:BatchPutAssetPropertyValue', 'iotsitewise:GetAssetPropertyValue', 'iotsitewise:GetAssetPropertyValueHistory',
      'iotsitewise:DescribeTimeSeries', 'iotsitewise:ListTimeSeries', 'iotsitewise:DeleteTimeSeries',
      'iotsitewise:ListAssetModels', 'iotsitewise:ListAssets', 'iotsitewise:DescribeAssetModel', 'iotsitewise:DescribeAsset',
      'iotsitewise:CreateAssetModel', 'iotsitewise:CreateAsset', 'iotsitewise:UpdateAssetModel', 'iotsitewise:UpdateAssetProperty',
      'iotsitewise:TagResource', 'iotsitewise:ListTagsForResource', 'iotsitewise:DeleteAsset', 'iotsitewise:DeleteAssetModel'], ['*']);

    // MSK over IAM. The cluster uuid is not known at synth time, hence the wildcard segment.
    // By name, not by the cluster's ARN, for the same reason: nothing here depends on MSK being created.
    const mskClusterArns = arn('kafka', `cluster/${NAMES.msk}/*`);
    allow(['kafka:ListClustersV2'], ['*']);
    allow(['kafka:GetBootstrapBrokers', 'kafka:DescribeClusterV2'], [mskClusterArns]);
    allow(['kafka-cluster:Connect', 'kafka-cluster:DescribeCluster', 'kafka-cluster:WriteDataIdempotently'], [mskClusterArns]);
    allow(['kafka-cluster:CreateTopic', 'kafka-cluster:DescribeTopic', 'kafka-cluster:WriteData', 'kafka-cluster:ReadData',
      'kafka-cluster:DeleteTopic', 'kafka-cluster:DescribeTopicDynamicConfiguration'], [arn('kafka', `topic/${NAMES.msk}/*/sfc_it_*`)]);

    // CloudWatch metrics writer case, confined to the suite's namespace.
    allow(['cloudwatch:PutMetricData'], ['*'], { StringEquals: { 'cloudwatch:namespace': NAMES.cwNamespace } });
    allow(['cloudwatch:GetMetricData', 'cloudwatch:ListMetrics'], ['*']);

    // ------------------------------------------------------------------------------------ teardown
    // The authoritative cleanup: post_build is skipped on TIMED_OUT and on a stopped build, which are the
    // runs that leak.
    const janitor = new lambda.Function(this, 'Janitor', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'janitor.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda'), { exclude: ['__pycache__', '*.pyc'] }),
      timeout: Duration.minutes(10),
      environment: {
        FIXTURE_TABLE_BUCKET_ARN: fixtureBucketArn,
        FIXTURE_NAMESPACE: NAMES.namespace,
        DEVICE_POLICY: devicePolicyName,
        MAX_AGE_SECONDS: '7200',
        // Certificates carry no run id, so they are only ever removed once older than any build could be.
        CERT_MIN_AGE_SECONDS: '19200',  // 5 h 20 min: the 5 h build timeout plus its 10 min queue
      },
      logGroup: new logs.LogGroup(this, 'JanitorLogs', { retention: logs.RetentionDays.ONE_WEEK, removalPolicy: RemovalPolicy.DESTROY }),
    });
    const jallow = (actions: string[], resources: string[]) => janitor.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    jallow(['s3tables:ListTableBuckets'], ['*']);
    jallow(['s3tables:ListNamespaces', 's3tables:ListTables', 's3tables:DeleteNamespace'], [fixtureBucketArn, runBucketArn]);
    jallow(['s3tables:DeleteTableBucket'], [runBucketArn]);
    jallow(['s3tables:DeleteTable'], [`${fixtureBucketArn}/table/*`, `${runBucketArn}/table/*`]);
    jallow(['iotsitewise:ListAssetModels', 'iotsitewise:ListAssets', 'iotsitewise:DescribeAssetModel', 'iotsitewise:DescribeAsset',
      'iotsitewise:DeleteAsset', 'iotsitewise:DeleteAssetModel', 'iotsitewise:ListTimeSeries', 'iotsitewise:DeleteTimeSeries'], ['*']);
    jallow(['iot:ListRetainedMessages', 'iot:ListCertificates', 'iot:ListAttachedPolicies', 'iot:UpdateCertificate', 'iot:DeleteCertificate'], ['*']);
    jallow(['iot:Publish', 'iot:RetainPublish'], [arn('iot', 'topic/sfc/it/*')]);  // zero-byte retained publish = delete
    jallow(['iot:DetachPolicy'], [arn('iot', `policy/${devicePolicyName}`)]);
    jallow(['sqs:ListQueues'], ['*']);
    jallow(['sqs:GetQueueAttributes', 'sqs:DeleteQueue'], [runQueues]);
    jallow(['cloudwatch:PutMetricData'], ['*']);

    new events.Rule(this, 'OnBuildTerminal', {
      eventPattern: {
        source: ['aws.codebuild'],
        detailType: ['CodeBuild Build State Change'],
        detail: { 'project-name': [NAMES.project], 'build-status': ['SUCCEEDED', 'FAILED', 'STOPPED', 'FAULT', 'TIMED_OUT'] },
      },
      targets: [new targets.LambdaFunction(janitor)],
    });
    new events.Rule(this, 'HourlySweep', {
      schedule: events.Schedule.rate(Duration.hours(1)),
      targets: [new targets.LambdaFunction(janitor, { event: events.RuleTargetInput.fromObject({ mode: 'age' }) })],
    });

    // --------------------------------------------------------------------------------- GitHub OIDC
    const oidcArn = props.oidcProviderArn ?? new iam.OidcProviderNative(this, 'GithubOidc', {
      // OidcProviderNative emits a plain AWS::IAM::OIDCProvider; the older OpenIdConnectProvider L2 is a
      // custom resource backed by a bundled Lambda.
      url: 'https://token.actions.githubusercontent.com',
      clientIds: ['sts.amazonaws.com'],
    }).oidcProviderArn;

    const ciRole = new iam.Role(this, 'SfcItCiRole', {
      assumedBy: new iam.WebIdentityPrincipal(oidcArn, {
        StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
        // Any branch of this repository: every push is tested.
        StringLike: { 'token.actions.githubusercontent.com:sub': `repo:${props.githubRepo}:*` },
      }),
      description: 'Assumed from GitHub Actions to upload source, start a build and fetch its evidence',
      // A build can queue for 10 minutes and run for 5 hours; the session must outlive both.
      maxSessionDuration: Duration.hours(6),
    });
    artifacts.grantPut(ciRole, 'src/*');
    artifacts.grantRead(ciRole, 'evidence/*');
    // start-build.sh asks whether the simulator for the current crate hash exists (head-object needs GetObject).
    artifacts.grantRead(ciRole, `${NAMES.plcSimPrefix}/*`);
    ciRole.addToPolicy(new iam.PolicyStatement({
      // StopBuild matters: without it a cancelled job orphans a running build.
      actions: ['codebuild:StartBuild', 'codebuild:BatchGetBuilds', 'codebuild:StopBuild'],
      resources: [project.projectArn, imageProject.projectArn, plcSimProject.projectArn],
    }));
    ciRole.addToPolicy(new iam.PolicyStatement({
      // start-build.sh asks whether the image for the current Dockerfile exists, and where the repository is.
      actions: ['ecr:DescribeImages', 'ecr:DescribeRepositories'],
      resources: [imageRepo.repositoryArn],
    }));
    ciRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:GetLogEvents', 'logs:DescribeLogStreams'],
      resources: [projectLogs.logGroupArn, `${projectLogs.logGroupArn}:*`],
    }));

    // ------------------------------------------------------------------------------------ outputs
    new CfnOutput(this, 'E2eEnvironment', { value: Stack.of(this).toJsonString(e2eEnv) });
    new CfnOutput(this, 'ArtifactsBucket', { value: artifacts.bucketName });
    new CfnOutput(this, 'ProjectName', { value: project.projectName });
    new CfnOutput(this, 'ImageProjectName', { value: imageProject.projectName });
    new CfnOutput(this, 'ImageRepositoryUri', { value: imageRepo.repositoryUri });
    new CfnOutput(this, 'PlcSimProjectName', { value: plcSimProject.projectName });
    new CfnOutput(this, 'MskBootstrapPublic', { value: mskPublic.getAttString('BootstrapPublicSaslIam') });
    new CfnOutput(this, 'CiRoleArn', { value: ciRole.roleArn });
    new CfnOutput(this, 'LogGroupName', { value: projectLogs.logGroupName });
    new CfnOutput(this, 'JanitorFunctionName', { value: janitor.functionName });
  }
}
