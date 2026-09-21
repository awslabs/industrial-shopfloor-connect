// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { QueryAppStack } from '../lib/query-app-stack';

const ENV = { account: '111122223333', region: 'us-west-2' };

// Synthesize with the same context `cdk deploy` uses. Without it the feature flags differ from a
// real deployment -- notably enablePartitionLiterals, which decides whether an ARN renders as a
// literal string or an Fn::Join over AWS::Partition -- and the assertions here would be testing a
// configuration nobody deploys.
const CDK_JSON_CONTEXT = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'cdk.json'), 'utf8'),
).context as Record<string, unknown>;

function synth(props: Record<string, unknown> = {}) {
  const app = new cdk.App({ context: CDK_JSON_CONTEXT });
  const stack = new QueryAppStack(app, 'TestStack', { env: ENV, ...props });
  return Template.fromStack(stack);
}

describe('QueryAppStack', () => {
  const template = synth();

  it('scopes S3 Tables access to the allowlisted bucket, read-only', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: 'ReadTableBucketCatalog',
            Action: [
              's3tables:GetNamespace',
              's3tables:GetTableBucket',
              's3tables:ListNamespaces',
              's3tables:ListTables',
            ],
            Resource: 'arn:aws:s3tables:us-west-2:111122223333:bucket/sfc-industrial-data-bucket',
          }),
          Match.objectLike({
            Sid: 'ReadTableData',
            Action: [
              's3tables:GetTable',
              's3tables:GetTableData',
              's3tables:GetTableMetadataLocation',
            ],
            Resource:
              'arn:aws:s3tables:us-west-2:111122223333:bucket/sfc-industrial-data-bucket/table/*',
          }),
        ]),
      }),
    });
  });

  it('grants no write or delete action on S3 Tables', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const actions = Object.values(policies)
      .flatMap((p: any) => p.Properties.PolicyDocument.Statement)
      .flatMap((s: any) => (Array.isArray(s.Action) ? s.Action : [s.Action]))
      .filter((a: unknown) => typeof a === 'string' && a.startsWith('s3tables:'));
    expect(actions.length).toBeGreaterThan(0);
    for (const action of actions) {
      expect(action).toMatch(/^s3tables:(Get|List)/);
    }
  });

  it('does not grant ListTableBuckets unless any bucket is allowed', () => {
    const rendered = JSON.stringify(template.toJSON());
    expect(rendered).not.toContain('s3tables:ListTableBuckets');

    const wide = JSON.stringify(synth({ allowAnyTableBucket: true }).toJSON());
    expect(wide).toContain('s3tables:ListTableBuckets');
    // The action has no resource type, so it must sit in its own statement on "*".
    expect(wide).toContain('arn:aws:s3tables:us-west-2:111122223333:bucket/*');
  });

  it('gives API Gateway permission to invoke the query function', () => {
    // SpecRestApi creates no Lambda permission of its own; without this every route returns 500
    // with zero Lambda invocations.
    template.hasResourceProperties('AWS::Lambda::Permission', {
      Action: 'lambda:InvokeFunction',
      Principal: 'apigateway.amazonaws.com',
    });
  });

  it('keeps the Lambda timeout under the API Gateway integration ceiling', () => {
    // At 29 s or more, a slow query would always surface as API Gateway's INTEGRATION_TIMEOUT
    // instead of the function's own QUERY_TIMEOUT envelope.
    const fns = template.findResources('AWS::Lambda::Function', {
      Properties: { PackageType: 'Image' },
    });
    const timeouts = Object.values(fns).map((f: any) => f.Properties.Timeout);
    expect(timeouts).toHaveLength(1);
    expect(timeouts[0]).toBeLessThan(29);
  });

  it('caps query function concurrency', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      PackageType: 'Image',
      ReservedConcurrentExecutions: 5,
    });
  });

  it('imports the API from an inline OpenAPI body with warnings fatal', () => {
    template.hasResourceProperties('AWS::ApiGateway::RestApi', {
      FailOnWarnings: true,
      Name: 'SFC S3 Tables DuckDB Query API',
      EndpointConfiguration: { Types: ['REGIONAL'] },
      Parameters: { endpointConfigurationTypes: 'REGIONAL' },
      Body: Match.anyValue(),
    });
  });

  it('leaves every placeholder substituted in the deployed body', () => {
    expect(JSON.stringify(template.toJSON())).not.toMatch(/\{\{[A-Z0-9_]+\}\}/);
  });

  it('ships no distribution-wide custom error responses', () => {
    // errorResponses is per-distribution, not per-behavior, so an SPA 403 -> /index.html mapping
    // would also rewrite the Cognito authorizer's 403 on /api/* into 200 text/html and make token
    // expiry undetectable. A CloudFront Function on the default behavior does the job instead.
    const distributions = template.findResources('AWS::CloudFront::Distribution');
    for (const dist of Object.values(distributions)) {
      expect((dist as any).Properties.DistributionConfig).not.toHaveProperty(
        'CustomErrorResponses',
      );
    }
    template.resourceCountIs('AWS::CloudFront::Function', 1);
  });

  it('routes /api/* to the REST API with POST allowed and Authorization forwarded', () => {
    const dist: any = Object.values(
      template.findResources('AWS::CloudFront::Distribution'),
    )[0];
    const behaviors = dist.Properties.DistributionConfig.CacheBehaviors;
    expect(behaviors).toHaveLength(1);
    const api = behaviors[0];
    expect(api.PathPattern).toBe('/api/*');
    expect(api.AllowedMethods).toEqual(
      expect.arrayContaining(['POST', 'GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE']),
    );
    // CACHING_DISABLED
    expect(api.CachePolicyId).toBe('4135ea2d-6df8-44a3-9df3-4b5a84be39ad');
    // ALL_VIEWER_EXCEPT_HOST_HEADER -- mandatory, since ALL_VIEWER would forward the viewer Host
    // header to execute-api and break routing, and this policy still forwards Authorization.
    expect(api.OriginRequestPolicyId).toBe('b689b0a8-53d0-40ab-baf2-68738e2966ac');
  });

  it('serves the site bucket through Origin Access Control only', () => {
    template.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
    // The policy the CloudFront OAC guide prescribes: s3:GetObject for the CloudFront service
    // principal, conditioned on this distribution's ARN.
    template.hasResourceProperties('AWS::S3::BucketPolicy', {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 's3:GetObject',
            Principal: { Service: 'cloudfront.amazonaws.com' },
            Condition: { StringEquals: { 'AWS:SourceArn': Match.anyValue() } },
          }),
        ]),
      }),
    });
  });

  it('configures Cognito so a demo can be torn down and redeployed', () => {
    // The CDK default is RETAIN, which leaves the pool and its globally unique domain prefix behind
    // and blocks the next deploy.
    template.hasResource('AWS::Cognito::UserPool', {
      DeletionPolicy: 'Delete',
      Properties: Match.objectLike({
        AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
      }),
    });
    template.hasResource('AWS::Cognito::UserPoolDomain', { DeletionPolicy: 'Delete' });
    // Mandatory with managed login: CloudFormation creates the client through
    // CreateUserPoolClient, which creates no branding style.
    template.resourceCountIs('AWS::Cognito::ManagedLoginBranding', 1);
  });

  it('binds the managed login branding to the app client, not just the pool', () => {
    // Branding is per app client. Omitting ClientId deploys fine at synth but fails at create with
    // "Value null at 'clientId' failed to satisfy constraint: Member must not be null".
    template.hasResourceProperties('AWS::Cognito::ManagedLoginBranding', {
      ClientId: Match.anyValue(),
      UserPoolId: Match.anyValue(),
      UseCognitoProvidedValues: true,
    });
  });

  it('keeps the branding out of the API dependency chain', () => {
    // branding -> client -> distribution -> api, so an api -> branding edge would be a cycle.
    const api: any = Object.values(template.findResources('AWS::ApiGateway::RestApi'))[0];
    const brandingIds = Object.keys(
      template.findResources('AWS::Cognito::ManagedLoginBranding'),
    );
    for (const id of brandingIds) {
      expect(api.DependsOn ?? []).not.toContain(id);
    }
  });

  it('uses the authorization code flow without the implicit grant or admin scope', () => {
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      AllowedOAuthFlows: ['code'],
      AllowedOAuthScopes: Match.arrayWith(['openid', 'email', 'profile']),
      GenerateSecret: false,
    });
    const client: any = Object.values(
      template.findResources('AWS::Cognito::UserPoolClient'),
    )[0];
    expect(client.Properties.AllowedOAuthFlows).not.toContain('implicit');
    // aws.cognito.signin.user.admin would let a leaked browser token call Cognito's self-service
    // APIs.
    expect(client.Properties.AllowedOAuthScopes).not.toContain('aws.cognito.signin.user.admin');
  });

  it('registers callback URLs in the exact form the app sends', () => {
    // Cognito compares redirect_uri against the registered callback URLs as an exact string, and the
    // app redirects to `window.location.origin + '/'`. Registering the bare origin instead yields a
    // redirect_mismatch after an otherwise successful login.
    const client: any = Object.values(
      template.findResources('AWS::Cognito::UserPoolClient'),
    )[0];
    const urls = [
      ...client.Properties.CallbackURLs,
      ...client.Properties.LogoutURLs,
    ];
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      // A token resolves to an Fn::Join whose last element carries the trailing slash.
      const tail = typeof url === 'string' ? url : url['Fn::Join'][1].slice(-1)[0];
      expect(tail.endsWith('/')).toBe(true);
    }
    // Sign-out reuses the sign-in URL, so the two lists must agree.
    expect(client.Properties.LogoutURLs).toEqual(client.Properties.CallbackURLs);
  });

  it('never enables Cognito threat protection, which would force the paid feature plan', () => {
    const rendered = JSON.stringify(template.toJSON());
    expect(rendered).not.toContain('UserPoolAddOns');
    expect(rendered).not.toContain('AdvancedSecurityMode');
  });

  it('retains the account-level API Gateway CloudWatch role on destroy', () => {
    // AWS::ApiGateway::Account is an account-wide singleton; deleting the role would disable
    // logging for unrelated APIs in the same account.
    template.hasResource('AWS::ApiGateway::Account', { DeletionPolicy: 'Retain' });
  });

  it('logs the Cognito subject on every API call', () => {
    const stage: any = Object.values(template.findResources('AWS::ApiGateway::Stage'))[0];
    expect(stage.Properties.AccessLogSetting.Format).toContain(
      '$context.authorizer.claims.sub',
    );
    expect(stage.Properties.MethodSettings[0].DataTraceEnabled).toBe(false);
  });

  it('throttles with a burst at least as large as the rate', () => {
    const stage: any = Object.values(template.findResources('AWS::ApiGateway::Stage'))[0];
    const settings = stage.Properties.MethodSettings[0];
    expect(settings.ThrottlingBurstLimit).toBeGreaterThanOrEqual(settings.ThrottlingRateLimit);
  });

  it('passes the table bucket allowlist to the function', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      PackageType: 'Image',
      Environment: {
        Variables: Match.objectLike({
          ALLOWED_TABLE_BUCKETS: 'sfc-industrial-data-bucket',
          ALLOW_ANY_TABLE_BUCKET: 'false',
          ALLOW_FREE_SQL: 'false',
          TABLE_BUCKET_REGION: 'us-west-2',
        }),
      },
    });
  });

  it('honours a table bucket region that differs from the stack region', () => {
    // run.sh writes to us-west-2 unless AWS_REGION says otherwise, and DuckDB derives the S3 Tables
    // endpoint from the ARN's region rather than the stack's.
    const other = synth({ tableBucketRegion: 'eu-west-1' });
    other.hasResourceProperties('AWS::Lambda::Function', {
      PackageType: 'Image',
      Environment: { Variables: Match.objectLike({ TABLE_BUCKET_REGION: 'eu-west-1' }) },
    });
    expect(JSON.stringify(other.toJSON())).toContain('arn:aws:s3tables:eu-west-1:');
  });

  it('adds a preflight invoke permission only when several origins are allowed', () => {
    expect(
      Object.keys(template.findResources('AWS::Lambda::Permission')),
    ).toHaveLength(1);
    const multi = synth({ siteOrigin: 'https://example.cloudfront.net' });
    expect(
      Object.keys(multi.findResources('AWS::Lambda::Permission')),
    ).toHaveLength(2);
  });

  it('publishes the outputs the helper scripts read', () => {
    const outputs = Object.keys(template.toJSON().Outputs ?? {});
    for (const key of ['SiteUrl', 'UserPoolId', 'ApiExecuteUrl', 'HostedUiUrl']) {
      expect(outputs).toContain(key);
    }
  });
});
