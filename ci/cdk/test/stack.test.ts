// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { SfcItStack } from '../lib/sfc-it-stack';

/**
 * These are regression tests for specific mistakes that are invisible until a real build fails, and
 * expensive to diagnose then. Each one corresponds to a defect that was found by reading the CDK source
 * rather than by deploying.
 */
function synth(props: Partial<ConstructorParameters<typeof SfcItStack>[2]> = {}) {
  const app = new cdk.App();
  const stack = new SfcItStack(app, 'TestStack', {
    githubRepo: 'awslabs/industrial-shopfloor-connect',
    env: { account: '123456789012', region: 'us-east-1' },
    ...props,
  } as ConstructorParameters<typeof SfcItStack>[2]);
  return Template.fromStack(stack);
}

/**
 * The rendered buildspec as plain text.
 *
 * It does not synthesise to a string: because the artifacts bucket name is a token, CDK emits an
 * `Fn::Join` whose parts interleave literal text with `Ref`s. Flattening the literals is enough to
 * assert on the commands, and treating the value as a string silently yields "[object Object]" - which
 * makes every `toContain` assertion pass vacuously and every `not.toContain` assertion pass for the
 * wrong reason.
 */
function buildSpecText(template: Template): string {
  const project = Object.values(template.findResources('AWS::CodeBuild::Project'))[0];
  const spec = project.Properties.Source.BuildSpec;
  if (typeof spec === 'string') return spec;
  const parts = spec['Fn::Join'][1] as unknown[];
  return parts.map((p) => (typeof p === 'string' ? p : '')).join('');
}

describe('SfcItStack', () => {
  test('the project role can read any source key, not just the seed zip', () => {
    // codebuild.Source.s3() calls bucket.grantRead(project, this.path), which scopes s3:GetObject to the
    // literal key. Every build is started with --source-location-override pointing at a per-run key, so
    // without an explicit src/* grant every build fails at DOWNLOAD_SOURCE with AccessDenied.
    const template = synth();
    const policies = template.findResources('AWS::IAM::Policy');
    const rendered = JSON.stringify(policies);
    expect(rendered).toContain('src/*');
  });

  test('no OIDC custom resource is created', () => {
    // iam.OpenIdConnectProvider is implemented as Custom::AWSCDKOpenIdConnectProvider backed by a
    // bundled Lambda. OidcProviderNative emits a plain AWS::IAM::OIDCProvider instead.
    const template = synth();
    template.resourceCountIs('Custom::AWSCDKOpenIdConnectProvider', 0);
    template.resourceCountIs('AWS::IAM::OIDCProvider', 1);
  });

  test('an existing OIDC provider ARN suppresses creating one', () => {
    // An OIDC provider is account-global; creating a second fails with EntityAlreadyExists.
    const template = synth({
      oidcProviderArn: 'arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com',
    });
    template.resourceCountIs('AWS::IAM::OIDCProvider', 0);
  });

  test('the CI role may stop a build', () => {
    // Without StopBuild, cancelling the Actions job orphans a running build that then collides with the
    // build started by the next push.
    const rendered = JSON.stringify(synth().findResources('AWS::IAM::Policy'));
    expect(rendered).toContain('codebuild:StopBuild');
  });

  test('the build role may publish a test report group', () => {
    // The buildspec declares a `reports` block; without these actions it fails to publish and the
    // per-case results never reach the console.
    const rendered = JSON.stringify(synth().findResources('AWS::IAM::Policy'));
    expect(rendered).toContain('codebuild:BatchPutTestCases');
  });

  test('the project uses LARGE compute', () => {
    // gradle.properties asks for a 4 GB Gradle JVM plus a separate 2 GB Kotlin daemon. SMALL (3 GB) and
    // MEDIUM (7 GB) leave no headroom for a 39-module build producing a 228 MB shadowJar.
    synth().hasResourceProperties('AWS::CodeBuild::Project', {
      Environment: Match.objectLike({ ComputeType: 'BUILD_GENERAL1_LARGE' }),
    });
  });

  test('the buildspec declares cache paths', () => {
    // codebuild.Cache.bucket() only sets where the cache lives. With no top-level `cache.paths` block in
    // the buildspec nothing is ever archived, and every build is a cold build.
    const spec = buildSpecText(synth());
    expect(spec).toContain('build-cache-1');
    expect(spec).toContain('modules-2');
  });

  test('the buildspec never runs gradle clean', () => {
    // The root build wires clean -> finalizedBy("cleanAll"), which deletes the whole root build/
    // directory - including build/distribution, which the tests read.
    const spec = buildSpecText(synth());
    expect(spec).toContain('./gradlew');
    expect(spec).not.toMatch(/gradlew[^\n]*\bclean\b/);
  });

  test('GRADLE_OPTS carries no Gradle CLI flags', () => {
    // gradlew splices $GRADLE_OPTS into the JVM argument list, so --no-daemon there kills the wrapper.
    const spec = buildSpecText(synth());
    const gradleOpts = /"GRADLE_OPTS":\s*"([^"]*)"/.exec(spec)?.[1];
    expect(gradleOpts).toBeDefined();
    expect(gradleOpts).not.toContain('--');
  });

  test('the SNS sink and the SQS target use separate queues', () => {
    // Sharing one queue with rawMessageDelivery makes the SNS assertion unfalsifiable: the bodies are
    // byte-identical, so an SNS case would pass even with SNS entirely broken.
    synth().resourceCountIs('AWS::SQS::Queue', 4);
  });

  test('the teardown rule covers non-success terminal states', () => {
    // post_build does not run on TIMED_OUT or on a stopped build, which are the runs that leak.
    const rules = Object.values(synth().findResources('AWS::Events::Rule'))
      .map((r) => r.Properties?.EventPattern)
      .filter((p) => p?.detail?.['build-status']);
    expect(rules).toHaveLength(1);
    expect(rules[0].detail['build-status']).toEqual(
      expect.arrayContaining(['SUCCEEDED', 'FAILED', 'STOPPED', 'FAULT', 'TIMED_OUT']),
    );
  });
});
