// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from 'fs';
import * as YAML from 'yaml';
import { assertInvariants, DATA_PATHS, FREE_SQL_PATH, loadOpenApi, SPEC_PATH } from '../lib/openapi';

const SUBS = {
  lambdaInvokeUri:
    'arn:aws:apigateway:us-west-2:lambda:path/2015-03-31/functions/arn:aws:lambda:us-west-2:111122223333:function:fn/invocations',
  userPoolArn: 'arn:aws:cognito-idp:us-west-2:111122223333:userpool/us-west-2_abc123',
  corsAllowOrigin: 'http://localhost:5173',
  corsAllowHeaders: 'Authorization,Content-Type',
  corsAllowMethods: 'POST,OPTIONS',
  corsMaxAge: '600',
  serverHost: 'example.cloudfront.net',
  allowFreeSql: false,
  dynamicCorsOrigin: false,
};

describe('api/openapi.yaml as committed', () => {
  const raw = YAML.parse(fs.readFileSync(SPEC_PATH, 'utf8'));

  it('is a parseable OpenAPI 3.0 document', () => {
    expect(raw.openapi).toMatch(/^3\.0/);
    expect(raw.info.title).toBe('SFC S3 Tables DuckDB Query API');
  });

  it('declares no root-level security', () => {
    // API Gateway IGNORES root-level security on REST import. Declaring the authorizer once at the
    // root would deploy every endpoint publicly, with no error, warning or rollback.
    expect(raw.security).toBeUndefined();
  });

  it('declares every data path plus the opt-in SQL path', () => {
    expect(Object.keys(raw.paths).sort()).toEqual([...DATA_PATHS, FREE_SQL_PATH].sort());
  });

  it('exposes only post and options on every path', () => {
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      const methods = Object.keys(item)
        .filter((k) => !k.startsWith('x-'))
        .sort();
      expect({ path, methods }).toEqual({ path, methods: ['options', 'post'] });
    }
  });

  it('secures every post with the Cognito authorizer and an empty scope array', () => {
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      // A non-empty scope array switches API Gateway to access-token mode, and the web app sends an
      // ID token, so every request would 401.
      expect({ path, security: item.post.security }).toEqual({
        path,
        security: [{ CognitoUserPool: [] }],
      });
    }
  });

  it('leaves every options preflight unauthenticated', () => {
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      expect({ path, security: item.options.security }).toEqual({ path, security: undefined });
    }
  });

  it('uses aws_proxy over POST for every post integration, within the API Gateway timeout', () => {
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      const integration = item.post['x-amazon-apigateway-integration'];
      expect({ path, type: integration.type }).toEqual({ path, type: 'aws_proxy' });
      // AWS_PROXY always invokes Lambda over POST, whatever verb the method itself uses.
      expect({ path, httpMethod: integration.httpMethod }).toEqual({ path, httpMethod: 'POST' });
      expect(integration.timeoutInMillis).toBeLessThanOrEqual(29000);
      // payloadFormatVersion is HTTP-API-only; its absence is why the proxy event carries
      // `resource`, which the handler routes on.
      expect(integration).not.toHaveProperty('payloadFormatVersion');
    }
  });

  it('declares no `default` method response', () => {
    // API Gateway's importer rejects Swagger's `default` method response, and the stack sets
    // failOnWarnings: true, so one of these fails the whole deploy with
    // "API Gateway does not support Swagger's 'default' method response".
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      for (const [verb, op] of Object.entries<any>(item)) {
        if (verb.startsWith('x-')) continue;
        expect({ op: `${verb} ${path}`, codes: Object.keys(op.responses ?? {}) }).toEqual({
          op: `${verb} ${path}`,
          codes: expect.not.arrayContaining(['default']),
        });
      }
    }
  });

  it('avoids every OpenAPI keyword API Gateway warns about', () => {
    // With failOnWarnings: true a warning is a rollback, and these are the keywords the importer
    // warns on. Swagger-editor output routinely contains several of them.
    const serialised = JSON.stringify(raw.paths) + JSON.stringify(raw.components.schemas);
    for (const keyword of [
      'example',
      'nullable',
      'readOnly',
      'writeOnly',
      'discriminator',
      'exclusiveMinimum',
      'exclusiveMaximum',
      'deprecated',
      'multipleOf',
      'uniqueItems',
    ]) {
      expect({ keyword, found: serialised.includes(`"${keyword}"`) }).toEqual({
        keyword,
        found: false,
      });
    }
  });

  it('declares the CORS headers on each preflight method response', () => {
    // Not documentation: a MOCK integration's responseParameters map onto the METHOD response's
    // declared headers, so an absent header here means the preflight returns it stripped.
    for (const [path, item] of Object.entries<any>(raw.paths)) {
      expect({ path, headers: Object.keys(item.options.responses['204'].headers).sort() }).toEqual({
        path,
        headers: [
          'Access-Control-Allow-Headers',
          'Access-Control-Allow-Methods',
          'Access-Control-Allow-Origin',
          'Access-Control-Max-Age',
          'Vary',
        ],
      });
    }
  });

  it('declares the Cognito authorizer the way API Gateway requires', () => {
    const scheme = raw.components.securitySchemes.CognitoUserPool;
    // `apiKey` is an API Gateway import requirement here, not an API key.
    expect(scheme.type).toBe('apiKey');
    expect(scheme.name).toBe('Authorization');
    expect(scheme.in).toBe('header');
    expect(scheme['x-amazon-apigateway-authtype']).toBe('cognito_user_pools');
    expect(scheme['x-amazon-apigateway-authorizer'].type).toBe('cognito_user_pools');
  });

  it('validates request bodies and not parameters', () => {
    // There are no path, query or header parameters anywhere, so parameter validation is dead weight.
    expect(raw['x-amazon-apigateway-request-validators']['body-only']).toEqual({
      validateRequestBody: true,
      validateRequestParameters: false,
    });
    expect(raw['x-amazon-apigateway-request-validator']).toBe('body-only');
  });

  it('never sets statusCode on the DEFAULT gateway responses', () => {
    // Setting statusCode on a DEFAULT rewrites the status code of every sibling response.
    const responses = raw['x-amazon-apigateway-gateway-responses'];
    expect(responses.DEFAULT_4XX).not.toHaveProperty('statusCode');
    expect(responses.DEFAULT_5XX).not.toHaveProperty('statusCode');
  });

  it('declares UNAUTHORIZED explicitly rather than relying on DEFAULT_4XX', () => {
    // UNAUTHORIZED is the one customisable 4XX whose docs omit the DEFAULT_4XX fallback.
    expect(raw['x-amazon-apigateway-gateway-responses'].UNAUTHORIZED.statusCode).toBe(401);
  });

  it('never interpolates the unquoted validation error string', () => {
    // $context.error.validationErrorString is not quoted and can itself contain double quotes, and
    // gateway response templates have no escape function, so embedding it yields invalid JSON.
    const serialised = JSON.stringify(raw['x-amazon-apigateway-gateway-responses']);
    expect(serialised).not.toContain('validationErrorString');
  });

  it('carries CORS headers on every gateway response', () => {
    // Without these, an expired token surfaces in a cross-origin browser as an opaque CORS failure
    // rather than a 401.
    for (const [name, spec] of Object.entries<any>(raw['x-amazon-apigateway-gateway-responses'])) {
      expect({
        name,
        origin: spec.responseParameters['gatewayresponse.header.Access-Control-Allow-Origin'],
      }).toEqual({ name, origin: "'{{CORS_ALLOW_ORIGIN}}'" });
    }
  });

  it('sets no server base path', () => {
    // API Gateway derives basePath from a server URL path; with basepath=prepend that would produce
    // /api/api/....
    for (const server of raw.servers) {
      expect(new URL(server.url.replace('{host}', 'example.com')).pathname).toBe('/');
    }
  });

  it('keeps the duplicated identifier constraints identical across request schemas', () => {
    // The constraints are repeated per schema rather than shared through a property-level $ref,
    // because API Gateway rewrites refs on import and does not reliably preserve a nested one --
    // which would silently drop these pattern checks.
    const schemas = Object.entries<any>(raw.components.schemas).filter(([name]) =>
      name.endsWith('Request'),
    );
    const withBucket = schemas.filter(
      ([, schema]) => schema.properties && schema.properties.tableBucket,
    );
    expect(withBucket.length).toBeGreaterThan(4);
    const [, first] = withBucket[0];
    for (const [name, schema] of withBucket) {
      expect({ name, tableBucket: pickConstraints(schema.properties.tableBucket) }).toEqual({
        name,
        tableBucket: pickConstraints(first.properties.tableBucket),
      });
    }

    const withNamespace = schemas.filter(
      ([, schema]) => schema.properties && schema.properties.namespace,
    );
    const [, firstNs] = withNamespace[0];
    for (const [name, schema] of withNamespace) {
      expect({ name, namespace: pickConstraints(schema.properties.namespace) }).toEqual({
        name,
        namespace: pickConstraints(firstNs.properties.namespace),
      });
      expect({ name, table: pickConstraints(schema.properties.table) }).toEqual({
        name,
        table: pickConstraints(firstNs.properties.table),
      });
    }
  });

  it('rejects unknown request properties', () => {
    for (const [name, schema] of Object.entries<any>(raw.components.schemas)) {
      if (name.endsWith('Request')) {
        expect({ name, additionalProperties: schema.additionalProperties }).toEqual({
          name,
          additionalProperties: false,
        });
      }
    }
  });
});

function pickConstraints(schema: any) {
  return {
    type: schema.type,
    minLength: schema.minLength,
    maxLength: schema.maxLength,
    pattern: schema.pattern,
  };
}

describe('loadOpenApi', () => {
  it('substitutes every placeholder', () => {
    const spec = loadOpenApi(SUBS);
    expect(JSON.stringify(spec)).not.toMatch(/\{\{[A-Z0-9_]+\}\}/);
    expect(spec.paths['/api/series'].post['x-amazon-apigateway-integration'].uri).toBe(
      SUBS.lambdaInvokeUri,
    );
    expect(
      spec.components.securitySchemes.CognitoUserPool['x-amazon-apigateway-authorizer'].providerARNs,
    ).toEqual([SUBS.userPoolArn]);
  });

  it('removes the SQL path unless free SQL is enabled', () => {
    expect(loadOpenApi(SUBS).paths[FREE_SQL_PATH]).toBeUndefined();
    expect(loadOpenApi({ ...SUBS, allowFreeSql: true }).paths[FREE_SQL_PATH]).toBeDefined();
  });

  it('keeps the preflight on a MOCK integration for a single origin', () => {
    const spec = loadOpenApi(SUBS);
    for (const item of Object.values<any>(spec.paths)) {
      expect(item.options['x-amazon-apigateway-integration'].type).toBe('mock');
    }
  });

  it('switches the preflight to the Lambda when several origins are allowed', () => {
    // A MOCK integration's responseParameters are static strings, so it can only advertise one
    // origin; the Lambda echoes whichever allowed origin matched.
    const spec = loadOpenApi({ ...SUBS, dynamicCorsOrigin: true });
    for (const item of Object.values<any>(spec.paths)) {
      const integration = item.options['x-amazon-apigateway-integration'];
      expect(integration.type).toBe('aws_proxy');
      expect(integration.uri).toBe(SUBS.lambdaInvokeUri);
      // Still unauthenticated: a CORS preflight cannot carry credentials.
      expect(item.options.security).toBeUndefined();
    }
  });

  it('fails when a post loses its authorizer', () => {
    const spec = loadOpenApi(SUBS);
    delete spec.paths['/api/series'].post.security;
    expect(() => assertInvariants(spec, { allowFreeSql: false })).toThrow(
      /must declare exactly one security requirement/,
    );
  });

  it('fails when a post declares a non-empty scope array', () => {
    const spec = loadOpenApi(SUBS);
    spec.paths['/api/series'].post.security = [{ CognitoUserPool: ['openid'] }];
    expect(() => assertInvariants(spec, { allowFreeSql: false })).toThrow(/scopes must be empty/);
  });

  it('fails when root-level security appears', () => {
    const spec = loadOpenApi(SUBS);
    spec.security = [{ CognitoUserPool: [] }];
    expect(() => assertInvariants(spec, { allowFreeSql: false })).toThrow(/API Gateway ignores it/);
  });

  it('fails when a non-POST method is added', () => {
    const spec = loadOpenApi(SUBS);
    spec.paths['/api/series'].get = { operationId: 'sneaky', responses: {} };
    expect(() => assertInvariants(spec, { allowFreeSql: false })).toThrow(
      /declares get; only post and options allowed/,
    );
  });

  it('fails when an integration is missing', () => {
    const spec = loadOpenApi(SUBS);
    delete spec.paths['/api/series'].post['x-amazon-apigateway-integration'];
    expect(() => assertInvariants(spec, { allowFreeSql: false })).toThrow(/has no x-amazon/);
  });

  it('fails on an unknown placeholder', () => {
    const path = `${SPEC_PATH}.tmp-unknown-placeholder.yaml`;
    fs.writeFileSync(
      path,
      // Global: the first occurrence is in the header comment, which YAML.parse discards.
      fs.readFileSync(SPEC_PATH, 'utf8').replace(/\{\{USER_POOL_ARN\}\}/g, '{{NOT_A_REAL_TOKEN}}'),
    );
    try {
      expect(() => loadOpenApi(SUBS, path)).toThrow(/unknown placeholder/);
    } finally {
      fs.unlinkSync(path);
    }
  });
});
