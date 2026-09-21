// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as ecrAssets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import { loadOpenApi } from './openapi';

export interface QueryAppStackProps extends cdk.StackProps {
  /**
   * S3 Tables table buckets this deployment may query. IAM is scoped to exactly these, the Lambda
   * rejects anything else, and the web app offers them as a dropdown.
   *
   * Defaults to the bucket the SFC example config creates.
   */
  readonly tableBucketNames?: string[];

  /**
   * Widen IAM to every table bucket in the account and grant s3tables:ListTableBuckets so the web
   * app can discover them.
   *
   * This lets any signed-in user read every Iceberg table in the account, so it is off by default.
   */
  readonly allowAnyTableBucket?: boolean;

  /**
   * Region of the table bucket. DuckDB derives the S3 Tables endpoint from the ARN's region field,
   * which is not necessarily the region this stack is deployed into -- the SFC example's run.sh
   * writes to us-west-2 unless AWS_REGION says otherwise.
   */
  readonly tableBucketRegion?: string;

  /**
   * Add POST /api/sql, which runs caller-supplied SQL.
   *
   * Off by default and unsafe to enable on an internet-facing deployment: see the security note in
   * README.md and the comment above /api/sql in api/openapi.yaml.
   */
  readonly allowFreeSql?: boolean;

  /**
   * Origins allowed to call the API cross-origin, for local development.
   *
   * Through CloudFront the web app and the API share one origin, so the browser sends no preflight
   * and CORS never applies. These entries exist for a local dev server, and for the CloudFront
   * domain itself if you choose to add it (see siteOrigin).
   */
  readonly devOrigins?: string[];

  /**
   * Optionally add the CloudFront domain to the CORS allowlist, as `https://dxxxx.cloudfront.net`.
   *
   * This cannot be wired automatically: the OpenAPI document needs the origin, the REST API needs
   * the document, the distribution needs the REST API, and the domain comes from the distribution.
   * That is a CloudFormation cycle. Take the value from the SiteUrl output after the first deploy
   * and pass it back in if you want it allowlisted -- the app itself does not need it.
   */
  readonly siteOrigin?: string;

  /** Cognito prefix domain label. Globally unique per region; defaults to include the account id. */
  readonly cognitoDomainPrefix?: string;
}

const DEFAULT_TABLE_BUCKET = 'sfc-industrial-data-bucket';
const CORS_ALLOW_HEADERS = 'Authorization,Content-Type';
const CORS_ALLOW_METHODS = 'POST,OPTIONS';
const CORS_MAX_AGE = '600';

export class QueryAppStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: QueryAppStackProps = {}) {
    super(scope, id, props);

    const tableBucketNames = props.tableBucketNames?.length
      ? props.tableBucketNames
      : [DEFAULT_TABLE_BUCKET];
    const allowAnyTableBucket = props.allowAnyTableBucket ?? false;
    const tableBucketRegion = props.tableBucketRegion ?? this.region;
    const allowFreeSql = props.allowFreeSql ?? false;
    const devOrigins = props.devOrigins ?? ['http://localhost:5173'];
    const corsOrigins = [...devOrigins, ...(props.siteOrigin ? [props.siteOrigin] : [])];

    // ----------------------------------------------------------------------------------------
    // Query function
    // ----------------------------------------------------------------------------------------

    const queryFnLogs = new logs.LogGroup(this, 'QueryFnLogs', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const queryFn = new lambda.DockerImageFunction(this, 'QueryFn', {
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '..', 'lambda'), {
        // Pinned so an Apple Silicon build still produces an x86_64 image. A mismatch between this
        // and `architecture` below surfaces as `exec format error` at runtime, not at build time.
        platform: ecrAssets.Platform.LINUX_AMD64,
      }),
      architecture: lambda.Architecture.X86_64,
      // Lambda allocates CPU in proportion to memory, and DuckDB is CPU-bound on Parquet decode.
      memorySize: 3008,
      // Must stay UNDER API Gateway's hard 29 s integration ceiling, so a slow query returns this
      // function's own QUERY_TIMEOUT envelope rather than API Gateway's INTEGRATION_TIMEOUT.
      timeout: cdk.Duration.seconds(25),
      ephemeralStorageSize: cdk.Size.gibibytes(2),
      // A runaway client loop would otherwise scale out to thousands of 3 GB functions scanning
      // Iceberg data.
      reservedConcurrentExecutions: 5,
      logGroup: queryFnLogs,
      environment: {
        TABLE_BUCKET_REGION: tableBucketRegion,
        ARN_PARTITION: this.partition,
        ACCOUNT_ID: this.account,
        ALLOWED_TABLE_BUCKETS: tableBucketNames.join(','),
        ALLOW_ANY_TABLE_BUCKET: String(allowAnyTableBucket),
        ALLOW_FREE_SQL: String(allowFreeSql),
        CORS_ALLOW_ORIGINS: corsOrigins.join(','),
        CORS_ALLOW_HEADERS,
        CORS_ALLOW_METHODS,
        CORS_MAX_AGE,
        QUERY_DEADLINE_SECONDS: '20',
      },
    });

    // Read-only S3 Tables access. Written out by hand rather than via the alpha L2's grantRead(),
    // which grants `s3tables:Get*` -- a wildcard that pulls in GetTableBucketPolicy,
    // GetTableBucketEncryption and every future Get action.
    // The region here must be the TABLE BUCKET's region, not the stack's. DuckDB derives the
    // S3 Tables endpoint from the ARN the function composes, so if these disagree the function asks
    // for a region its role does not permit and every query fails with AccessDenied.
    const tableBucketArn = (name: string) =>
      this.formatArn({
        service: 's3tables',
        region: tableBucketRegion,
        resource: 'bucket',
        resourceName: name,
      });
    const bucketArns = allowAnyTableBucket
      ? [tableBucketArn('*')]
      : tableBucketNames.map(tableBucketArn);

    queryFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ReadTableBucketCatalog',
        actions: [
          's3tables:GetTableBucket',
          's3tables:ListNamespaces',
          's3tables:GetNamespace',
          's3tables:ListTables',
        ],
        resources: bucketArns,
      }),
    );

    // A table ARN ends in an opaque table UUID rather than the table name, so `table/*` is
    // unavoidable. The namespace condition claws back some of what that wildcard gives away.
    queryFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ReadTableData',
        actions: [
          's3tables:GetTable',
          's3tables:GetTableMetadataLocation',
          's3tables:GetTableData',
        ],
        resources: bucketArns.map((arn) => `${arn}/table/*`),
      }),
    );

    if (allowAnyTableBucket) {
      // ListTableBuckets has no resource type in the service authorization reference, so it needs
      // Resource "*" in its own statement. AWS's own policy example scopes it to bucket/*, which
      // does not authorize the call.
      queryFn.addToRolePolicy(
        new iam.PolicyStatement({
          sid: 'DiscoverTableBuckets',
          actions: ['s3tables:ListTableBuckets'],
          resources: ['*'],
        }),
      );
    }

    // ----------------------------------------------------------------------------------------
    // Cognito
    // ----------------------------------------------------------------------------------------

    const userPool = new cognito.UserPool(this, 'UserPool', {
      // No self sign-up: this API reads industrial data, so users are created deliberately with
      // scripts/create-user.sh. The CDK default is true.
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      signInCaseSensitive: false,
      standardAttributes: { email: { required: true, mutable: true } },
      passwordPolicy: { minLength: 12, requireDigits: true, requireLowercase: true, requireUppercase: true },
      // Deliberately NOT setting standardThreatProtectionMode / customThreatProtectionMode: either
      // forces the pool onto the PLUS feature plan, which has no free tier.
      // The CDK default is RETAIN, which leaves the pool and its globally unique domain prefix
      // behind and blocks the next deploy.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const domainPrefix = props.cognitoDomainPrefix ?? `sfc-duckdb-${this.account}`;
    const userPoolDomain = userPool.addDomain('UserPoolDomain', {
      cognitoDomain: { domainPrefix },
      managedLoginVersion: cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
    });
    userPoolDomain.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // The managed login branding is created further down, once the app client exists: branding is
    // per app client, not per user pool.

    // ----------------------------------------------------------------------------------------
    // REST API, defined by api/openapi.yaml
    // ----------------------------------------------------------------------------------------

    const stageName = 'prod';

    // Built from CDK-injected values only. Never wrapped in Fn::Sub: CDK expands the token to an
    // object and CloudFormation rejects it (aws-cdk#17640).
    const lambdaInvokeUri =
      `arn:${this.partition}:apigateway:${this.region}:lambda:path/2015-03-31/functions/` +
      `${queryFn.functionArn}/invocations`;

    const openApiSpec = loadOpenApi({
      lambdaInvokeUri,
      userPoolArn: userPool.userPoolArn,
      // A MOCK integration's responseParameters are static strings, so the preflight can only
      // advertise one origin. The Lambda echoes whichever allowed origin actually matched on the
      // POST responses.
      corsAllowOrigin: corsOrigins[0] ?? 'null',
      corsAllowHeaders: CORS_ALLOW_HEADERS,
      corsAllowMethods: CORS_ALLOW_METHODS,
      corsMaxAge: CORS_MAX_AGE,
      // Documentation only, and a plain host rather than a token: the distribution's domain cannot
      // be used here without a CloudFormation cycle (spec -> API -> distribution -> spec). The
      // SiteUrl output carries the real value.
      serverHost: props.siteOrigin?.replace(/^https?:\/\//, '') ?? 'your-distribution.cloudfront.net',
      allowFreeSql,
      // With more than one allowed origin a static MOCK cannot echo the right one, so route the
      // preflight through the Lambda instead. It still declares no security.
      dynamicCorsOrigin: corsOrigins.length > 1,
    });

    const apiAccessLogs = new logs.LogGroup(this, 'ApiAccessLogs', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const api = new apigateway.SpecRestApi(this, 'QueryApi', {
      // CDK sets the CloudFormation Name from restApiName ?? construct id, overriding info.title,
      // so keep the two in step.
      restApiName: 'SFC S3 Tables DuckDB Query API',
      apiDefinition: apigateway.ApiDefinition.fromInline(openApiSpec),
      // Turn API Gateway's import warnings into deploy failures. Without this, an operation missing
      // its integration deploys as a method that returns 500.
      failOnWarnings: true,
      // `mode` left unset on purpose: MERGE would not delete a path removed from openapi.yaml,
      // silently breaking the POST-only invariant.
      endpointTypes: [apigateway.EndpointType.REGIONAL],
      parameters: { endpointConfigurationTypes: 'REGIONAL' },
      // Required to see authorizer and integration errors, but it writes an account-level
      // AWS::ApiGateway::Account singleton -- so retain it rather than deleting a role other APIs
      // in this account may depend on.
      cloudWatchRole: true,
      cloudWatchRoleRemovalPolicy: cdk.RemovalPolicy.RETAIN,
      deployOptions: {
        stageName,
        loggingLevel: apigateway.MethodLoggingLevel.ERROR,
        dataTraceEnabled: false,
        metricsEnabled: true,
        // Stage throttling is shared across all callers; there are no usage plans, so there is no
        // per-user limit. Burst >= rate so the token bucket is meaningful.
        throttlingRateLimit: 25,
        throttlingBurstLimit: 50,
        accessLogDestination: new apigateway.LogGroupLogDestination(apiAccessLogs),
        // The stock jsonWithStandardFields() format has no Cognito identity, and behind CloudFront
        // $context.identity.sourceIp is an edge IP -- so "which user ran this query against which
        // table bucket" would be unanswerable. Viewer IP comes from CloudFront's own logs.
        accessLogFormat: apigateway.AccessLogFormat.custom(
          JSON.stringify({
            requestId: '$context.requestId',
            resourcePath: '$context.resourcePath',
            httpMethod: '$context.httpMethod',
            status: '$context.status',
            sub: '$context.authorizer.claims.sub',
            email: '$context.authorizer.claims.email',
            integrationLatency: '$context.integrationLatency',
            responseLatency: '$context.responseLatency',
            errorResponseType: '$context.error.responseType',
          }),
        ),
        methodOptions: allowFreeSql
          ? {
              '/api/sql/POST': { throttlingRateLimit: 2, throttlingBurstLimit: 4 },
            }
          : undefined,
      },
    });

    // Deliberately NOT depending on the managed login branding here. Branding needs the app client,
    // the client needs the distribution domain for its callback URLs, and the distribution needs this
    // API -- so an api -> branding edge would close a CloudFormation cycle. The API does not care
    // whether the login page is styled.

    // SpecRestApi creates NO Lambda permission -- only LambdaIntegration does. Without this every
    // route returns 500 with zero Lambda invocations, and the real cause
    // ("Invalid permissions on Lambda function") appears only in the execution log.
    queryFn.addPermission('AllowApiGatewayInvoke', {
      principal: new iam.ServicePrincipal('apigateway.amazonaws.com'),
      action: 'lambda:InvokeFunction',
      sourceArn: api.arnForExecuteApi('POST', '/api/*', api.deploymentStage.stageName),
    });
    if (corsOrigins.length > 1) {
      // The preflight is Lambda-backed in this case, so it needs its own permission.
      queryFn.addPermission('AllowApiGatewayInvokePreflight', {
        principal: new iam.ServicePrincipal('apigateway.amazonaws.com'),
        action: 'lambda:InvokeFunction',
        sourceArn: api.arnForExecuteApi('OPTIONS', '/api/*', api.deploymentStage.stageName),
      });
    }

    // ----------------------------------------------------------------------------------------
    // Static site and CloudFront
    // ----------------------------------------------------------------------------------------

    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      // Without autoDeleteObjects, cdk destroy fails on a non-empty bucket.
      autoDeleteObjects: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Rewrites extension-less paths to /index.html. This replaces the usual `errorResponses`
    // 403/404 -> /index.html pattern, which CANNOT be used here: errorResponses is
    // distribution-wide rather than per-behavior, so it would also rewrite the Cognito authorizer's
    // 403 on /api/* into 200 text/html, making token expiry undetectable by the web app.
    const spaRouter = new cloudfront.Function(this, 'SpaRouter', {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(`
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri === '/' || uri.endsWith('/')) {
    request.uri = '/index.html';
    return request;
  }
  var lastSegment = uri.substring(uri.lastIndexOf('/') + 1);
  if (lastSegment.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
`),
    });

    const responseHeaders = new cloudfront.ResponseHeadersPolicy(this, 'SiteResponseHeaders', {
      securityHeadersBehavior: {
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: {
          referrerPolicy: cloudfront.HeadersReferrerPolicy.SAME_ORIGIN,
          override: true,
        },
        strictTransportSecurity: {
          accessControlMaxAge: cdk.Duration.days(365),
          includeSubdomains: true,
          override: true,
        },
        contentSecurityPolicy: {
          override: true,
          // Plotly is vendored, so script-src needs no CDN host. 'unsafe-eval' is not needed by the
          // plotly-basic bundle -- only the WebGL traces build kernels with the Function
          // constructor. style-src 'unsafe-inline' is unavoidable with any current Plotly bundle.
          // connect-src allows the API (same origin) and Cognito's token endpoint, which is not.
          contentSecurityPolicy: [
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            `connect-src 'self' https://${domainPrefix}.auth.${this.region}.amazoncognito.com`,
            "form-action 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
          ].join('; '),
        },
      },
    });

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: 'SFC S3 Tables DuckDB query app',
      defaultRootObject: 'index.html',
      // Origin Access Control, per
      // https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html
      // This generates the bucket policy the guide prescribes: s3:GetObject for
      // cloudfront.amazonaws.com, conditioned on AWS:SourceArn being this distribution.
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        responseHeadersPolicy: responseHeaders,
        functionAssociations: [
          {
            function: spaRouter,
            eventType: cloudfront.FunctionEventType.VIEWER_REQUEST,
          },
        ],
      },
      additionalBehaviors: {
        // Serving the API from the same distribution is what makes the web app same-origin with it,
        // so no preflight is sent and no CORS configuration is involved on this path.
        //
        // Note that '/api/*' does not match '/api' exactly -- a request to /api reaches the S3
        // origin instead.
        '/api/*': {
          origin: new origins.RestApiOrigin(api, {
            // API Gateway's own hard ceiling is 29 s; allow a little more so the client sees the
            // API's INTEGRATION_TIMEOUT envelope rather than a CloudFront HTML 504.
            readTimeout: cdk.Duration.seconds(31),
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          // The default is ALLOW_GET_HEAD, and even ALLOW_GET_HEAD_OPTIONS lacks POST. Omitting
          // this yields a CloudFront 403 that reads like a Cognito failure.
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          // Mandatory. ALL_VIEWER would forward the viewer Host header to execute-api and break
          // routing; this variant still forwards Authorization to the Cognito authorizer.
          originRequestPolicy:
            cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      // Deliberately NO errorResponses. See the SpaRouter comment above.
    });

    const siteUrl = `https://${distribution.distributionDomainName}`;
    const cognitoDomainUrl = `https://${domainPrefix}.auth.${this.region}.amazoncognito.com`;

    // Cognito matches redirect_uri against the registered callback URLs EXACTLY, so a trailing slash
    // is not cosmetic: 'https://d111.cloudfront.net' and 'https://d111.cloudfront.net/' are two
    // different URLs to it. The web app redirects to `window.location.origin + '/'` -- it has to be
    // the origin actually serving the page, so one uploaded bundle works both behind CloudFront and
    // on a dev server -- so register exactly that form here.
    const callbackUrls = [siteUrl, ...devOrigins].map((u) =>
      u.endsWith('/') ? u : `${u}/`,
    );

    const userPoolClient = userPool.addClient('WebClient', {
      generateSecret: false,
      authFlows: { userSrp: false, userPassword: false },
      oAuth: {
        // The CDK default leaves implicitCodeGrant ON, which would put tokens in the URL fragment
        // and in browser history.
        flows: { authorizationCodeGrant: true, implicitCodeGrant: false },
        // The CDK default includes COGNITO_ADMIN, which would let a leaked browser token call
        // Cognito's self-service APIs.
        scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
        callbackUrls,
        // A separate list from callbackUrls, and easy to leave mismatched: logout_uri must appear
        // here or Cognito rejects the sign-out redirect. The app sends the same URL for both.
        logoutUrls: callbackUrls,
      },
      enableTokenRevocation: true,
      preventUserExistenceErrors: true,
      idTokenValidity: cdk.Duration.hours(1),
      accessTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(1),
    });

    // Mandatory with NEWER_MANAGED_LOGIN, and it belongs here rather than next to the user pool:
    // branding is per APP CLIENT. CloudFormation creates the client through CreateUserPoolClient,
    // which creates no branding style, so managed login renders an error page for a client that has
    // none -- and omitting clientId fails at create time with
    // "Value null at 'clientId' failed to satisfy constraint: Member must not be null".
    const branding = new cognito.CfnManagedLoginBranding(this, 'ManagedLoginBranding', {
      userPoolId: userPool.userPoolId,
      clientId: userPoolClient.userPoolClientId,
      useCognitoProvidedValues: true,
    });
    branding.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // One deployment, two sources. BucketDeployment prunes the whole destination prefix by default,
    // so two deployments at the same root would delete each other's objects.
    new s3deploy.BucketDeployment(this, 'DeploySite', {
      destinationBucket: siteBucket,
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '..', 'web')),
        // jsonData resolves deploy-time tokens, which is how the web app learns the user pool
        // client id without a build step. Note it is NOT resolved in `cdk synth` output.
        s3deploy.Source.jsonData('config.json', {
          region: this.region,
          tableBucketRegion,
          // Origin prefix for API calls, not a path prefix: the route paths already start with
          // /api/. Empty means same origin, which is the whole point of serving the API from this
          // distribution. Set it to a full origin (https://…) to run the web app locally against a
          // deployed API -- that path is cross-origin, which is what devOrigins exists for.
          apiBase: '',
          cognitoDomain: cognitoDomainUrl,
          userPoolId: userPool.userPoolId,
          clientId: userPoolClient.userPoolClientId,
          // NOT the redirect URI to use -- the app derives that from the origin serving the page,
          // because it must match where the browser actually is. This is the REGISTERED list, so the
          // app can check its own origin against it and say "this origin is not registered" instead
          // of bouncing the user to a Cognito error page that names no URL.
          callbackUrls,
          tableBucketNames,
          allowAnyTableBucket,
          allowFreeSql,
          defaultNamespace: 'sfc',
          defaultTable: 'sim',
        }),
      ],
      distribution,
      distributionPaths: ['/*'],
    });

    // ----------------------------------------------------------------------------------------
    // Outputs
    // ----------------------------------------------------------------------------------------

    new cdk.CfnOutput(this, 'SiteUrl', {
      value: siteUrl,
      description: 'Open this. Serves the web app and, under /api/, the query API.',
    });
    new cdk.CfnOutput(this, 'UserPoolId', {
      value: userPool.userPoolId,
      description: 'Pass to scripts/create-user.sh to create a sign-in.',
    });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'HostedUiUrl', {
      value: cognitoDomainUrl,
      description: 'Cognito managed login. A new prefix domain can take up to 60 s to resolve.',
    });
    new cdk.CfnOutput(this, 'ApiExecuteUrl', {
      value: api.url,
      description:
        'Direct execute-api URL, which includes the stage. Through CloudFront omit the stage: ' +
        'POST <SiteUrl>/api/series.',
    });
    new cdk.CfnOutput(this, 'QueryFunctionName', { value: queryFn.functionName });
    new cdk.CfnOutput(this, 'QueryFunctionLogGroup', { value: queryFnLogs.logGroupName });
    new cdk.CfnOutput(this, 'AllowedTableBuckets', {
      value: allowAnyTableBucket ? '(any table bucket in this account)' : tableBucketNames.join(','),
    });
  }
}
