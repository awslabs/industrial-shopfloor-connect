// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from 'fs';
import * as path from 'path';
import * as YAML from 'yaml';

/**
 * Loads api/openapi.yaml, substitutes the {{PLACEHOLDER}} tokens, and asserts the invariants the
 * deployed API depends on.
 *
 * Why the document is loaded and substituted here rather than handed to API Gateway as a file:
 *
 *   * `ApiDefinition.fromInline(obj)` is the ONLY factory that resolves CDK tokens. The object
 *     lands in the CloudFormation `Body` property, which is typed Json, so `Stack.resolve` walks it
 *     and turns a Lambda ARN into Fn::GetAtt.
 *   * `fromAsset` / `fromBucket` upload the bytes verbatim and set `BodyS3Location`. Neither CDK
 *     nor CloudFormation ever parses the document, so `Fn::Sub` inside it is inert and a
 *     CDK-generated ARN cannot be expressed.
 *
 * API Gateway does resolve ${AWS::Region}, ${AWS::AccountId} and ${AWS::Partition} on import, but
 * that is documented for put-rest-api rather than for the CloudFormation Body path, and the failure
 * mode if it did not apply is the worst possible one: the URI stays literal text, the import
 * succeeds, and every endpoint returns 500 with no synth or deploy error. So nothing here depends
 * on API Gateway-side substitution -- CDK injects partition, region and account too.
 */

export interface OpenApiSubstitutions {
  /** Full apigateway:lambda:path integration URI of the query function. */
  readonly lambdaInvokeUri: string;
  /** ARN of the Cognito user pool backing the authorizer. */
  readonly userPoolArn: string;
  /** Primary allowed CORS origin, used by the MOCK preflight and the gateway responses. */
  readonly corsAllowOrigin: string;
  readonly corsAllowHeaders: string;
  readonly corsAllowMethods: string;
  readonly corsMaxAge: string;
  /** CloudFront distribution domain without a scheme -- documentation only, never a base path. */
  readonly serverHost: string;
  /** When false the /api/sql path is removed from the document entirely. */
  readonly allowFreeSql: boolean;
  /**
   * When true, the preflight integration is switched from MOCK to aws_proxy so the Lambda can echo
   * whichever of several allowed origins matched and add `Vary: Origin`. A MOCK integration's
   * responseParameters are static strings and cannot do that.
   */
  readonly dynamicCorsOrigin: boolean;
}

/** Paths whose `post` operations must be structurally identical apart from path and schema. */
export const DATA_PATHS = [
  '/api/buckets',
  '/api/catalog',
  '/api/schema',
  '/api/extent',
  '/api/distinct',
  '/api/series',
  '/api/trend',
  '/api/rows',
] as const;

export const FREE_SQL_PATH = '/api/sql';

export const SPEC_PATH = path.join(__dirname, '..', 'api', 'openapi.yaml');

export function loadOpenApi(subs: OpenApiSubstitutions, specPath: string = SPEC_PATH): any {
  const raw = fs.readFileSync(specPath, 'utf8');

  const replacements: Record<string, string> = {
    LAMBDA_INVOKE_URI: subs.lambdaInvokeUri,
    USER_POOL_ARN: subs.userPoolArn,
    CORS_ALLOW_ORIGIN: subs.corsAllowOrigin,
    CORS_ALLOW_HEADERS: subs.corsAllowHeaders,
    CORS_ALLOW_METHODS: subs.corsAllowMethods,
    CORS_MAX_AGE: subs.corsMaxAge,
    SERVER_HOST: subs.serverHost,
  };

  // Substitute on the parsed object rather than on the text, so a token that resolves to a
  // CloudFormation intrinsic survives as an object instead of being stringified into YAML.
  const spec = YAML.parse(raw);
  const substituted = substitute(spec, replacements);

  if (!subs.allowFreeSql) {
    delete substituted.paths[FREE_SQL_PATH];
  }

  if (subs.dynamicCorsOrigin) {
    useLambdaPreflight(substituted, subs.lambdaInvokeUri);
  }

  assertInvariants(substituted, { allowFreeSql: subs.allowFreeSql });
  return substituted;
}

/** Replace every `{{NAME}}` occurrence inside string values, recursively. */
function substitute(node: any, replacements: Record<string, string>): any {
  if (typeof node === 'string') {
    return node.replace(/\{\{([A-Z0-9_]+)\}\}/g, (match, name: string) => {
      const value = replacements[name];
      if (value === undefined) {
        throw new Error(`openapi.yaml references unknown placeholder ${match}`);
      }
      return value;
    });
  }
  if (Array.isArray(node)) {
    return node.map((item) => substitute(item, replacements));
  }
  if (node && typeof node === 'object') {
    const out: Record<string, any> = {};
    for (const [key, value] of Object.entries(node)) {
      out[key] = substitute(value, replacements);
    }
    return out;
  }
  return node;
}

/**
 * Swap every MOCK preflight for an aws_proxy one.
 *
 * Used when more than one origin is allowed: the Lambda inspects the request Origin, echoes it if
 * it is on the list, and adds `Vary: Origin`. The OPTIONS method still carries no `security`, so
 * the preflight remains unauthenticated as CORS requires.
 */
function useLambdaPreflight(spec: any, lambdaInvokeUri: string): void {
  for (const pathItem of Object.values<any>(spec.paths)) {
    if (!pathItem.options) continue;
    pathItem.options['x-amazon-apigateway-integration'] = {
      type: 'aws_proxy',
      httpMethod: 'POST',
      uri: lambdaInvokeUri,
      passthroughBehavior: 'when_no_match',
      timeoutInMillis: 29000,
    };
  }
}

/**
 * Enforce, at synth time, the guarantees API Gateway will not enforce for us.
 *
 * The most consequential one is per-operation `security`. Root-level `security:` is IGNORED by
 * REST API import -- declaring the authorizer once at the document root deploys an API where every
 * endpoint is public, with no error, no warning and no rollback.
 */
export function assertInvariants(spec: any, opts: { allowFreeSql: boolean }): void {
  const problems: string[] = [];

  if (spec.security !== undefined) {
    problems.push(
      'root-level `security:` is present. API Gateway ignores it on REST import, which would ' +
        'deploy every endpoint with no authorizer. Declare security per operation instead.',
    );
  }

  const expected = new Set<string>(DATA_PATHS);
  if (opts.allowFreeSql) expected.add(FREE_SQL_PATH);

  const actual = new Set(Object.keys(spec.paths ?? {}));
  for (const p of expected) {
    if (!actual.has(p)) problems.push(`expected path ${p} is missing`);
  }
  for (const p of actual) {
    if (!expected.has(p)) problems.push(`unexpected path ${p}`);
  }

  for (const [pathName, pathItem] of Object.entries<any>(spec.paths ?? {})) {
    const methods = Object.keys(pathItem).filter((k) => !k.startsWith('x-'));
    const unexpected = methods.filter((m) => m !== 'post' && m !== 'options');
    if (unexpected.length) {
      problems.push(`${pathName} declares ${unexpected.join(', ')}; only post and options allowed`);
    }
    if (!pathItem.post) {
      problems.push(`${pathName} has no post operation`);
      continue;
    }

    const security = pathItem.post.security;
    if (!Array.isArray(security) || security.length !== 1) {
      problems.push(`${pathName} post must declare exactly one security requirement`);
    } else {
      const scopes = security[0]?.CognitoUserPool;
      if (!Array.isArray(scopes)) {
        problems.push(`${pathName} post security must reference CognitoUserPool`);
      } else if (scopes.length !== 0) {
        // A non-empty scope array switches API Gateway to access-token mode, and the SPA sends an
        // ID token, so every request would 401.
        problems.push(`${pathName} post security scopes must be empty, found ${scopes.length}`);
      }
    }

    const integration = pathItem.post['x-amazon-apigateway-integration'];
    if (!integration) {
      // Only a warning to API Gateway; with failOnWarnings it rolls the stack back, without it the
      // method deploys and returns 500.
      problems.push(`${pathName} post has no x-amazon-apigateway-integration`);
    } else {
      if (integration.type !== 'aws_proxy') {
        problems.push(`${pathName} post integration type must be aws_proxy`);
      }
      if (integration.httpMethod !== 'POST') {
        // AWS_PROXY always invokes Lambda over POST, whatever the method's own verb.
        problems.push(`${pathName} post integration httpMethod must be POST`);
      }
      if (!(integration.timeoutInMillis <= 29000)) {
        problems.push(`${pathName} post integration timeoutInMillis must be <= 29000`);
      }
      if ('payloadFormatVersion' in integration) {
        // HTTP-API-only. Its absence is why the proxy event carries `resource` for routing.
        problems.push(`${pathName} post integration must not set payloadFormatVersion`);
      }
      if (typeof integration.uri !== 'string' || integration.uri.includes('{{')) {
        problems.push(`${pathName} post integration uri was not substituted`);
      }
    }

    if (pathItem.options?.security !== undefined) {
      problems.push(`${pathName} options must not declare security; a CORS preflight cannot ` +
        'carry credentials');
    }
  }

  const leftover = JSON.stringify(spec).match(/\{\{[A-Z0-9_]+\}\}/g);
  if (leftover) {
    problems.push(`unsubstituted placeholders remain: ${[...new Set(leftover)].join(', ')}`);
  }

  if (problems.length) {
    throw new Error(`api/openapi.yaml failed its invariants:\n  - ${problems.join('\n  - ')}`);
  }
}
