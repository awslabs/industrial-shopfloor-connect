// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Amazon Cognito authorization-code + PKCE for a plain browser app. No SDK, no build step.
 *
 * Exposes window.SfcAuth:
 *   init()          load config.json and complete a pending redirect; resolves to a session or null
 *   signIn()        redirect to Cognito managed login
 *   signOut()       clear tokens and redirect to Cognito /logout
 *   idToken()       current ID token, refreshed if it is close to expiry
 *   subjectName()   display name for the signed-in user
 *   config
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'sfc.session';
  const VERIFIER_KEY = 'sfc.pkce.verifier';
  const STATE_KEY = 'sfc.pkce.state';
  // Refresh this far ahead of expiry so an in-flight request never races the clock.
  const REFRESH_SKEW_SECONDS = 120;

  let config = null;
  let session = null;

  function base64UrlEncode(bytes) {
    let binary = '';
    for (const b of new Uint8Array(bytes)) binary += String.fromCharCode(b);
    // Cognito requires base64url. Plain btoa() output is rejected -- the PKCE documentation says
    // "base64" but its own example strips the padding and swaps the two URL-unsafe characters.
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function randomString(byteLength) {
    return base64UrlEncode(crypto.getRandomValues(new Uint8Array(byteLength)));
  }

  async function challengeFor(verifier) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return base64UrlEncode(digest);
  }

  /** Decode a JWT payload for display only. Never a substitute for server-side verification. */
  function decodeJwtPayload(token) {
    try {
      const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = part + '='.repeat((4 - (part.length % 4)) % 4);
      return JSON.parse(decodeURIComponent(escape(atob(padded))));
    } catch (err) {
      return null;
    }
  }

  function loadSession() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }

  function saveSession(next) {
    session = next;
    if (next) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else sessionStorage.removeItem(STORAGE_KEY);
  }

  function sessionFromTokenResponse(payload, existingRefreshToken) {
    const claims = decodeJwtPayload(payload.id_token) || {};
    return {
      idToken: payload.id_token,
      // The token endpoint does not return a new refresh token unless rotation is enabled, so keep
      // the one we already have.
      refreshToken: payload.refresh_token || existingRefreshToken || null,
      expiresAt: claims.exp ? claims.exp * 1000 : Date.now() + (payload.expires_in || 3600) * 1000,
      claims,
    };
  }

  async function exchange(params) {
    const response = await fetch(`${config.cognitoDomain}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      // No credentials: 'include'. The token endpoint answers with
      // Access-Control-Allow-Origin: * and Cognito does not support a custom CORS origin policy on
      // it, so a credentialed request would be rejected by the browser.
      body: new URLSearchParams(params).toString(),
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = JSON.parse(text);
    } catch (err) {
      throw new Error(`Cognito token endpoint returned a non-JSON response: ${text.slice(0, 200)}`);
    }
    if (!response.ok) {
      const err = new Error(payload.error_description || payload.error || 'Token exchange failed');
      err.code = payload.error;
      throw err;
    }
    return payload;
  }

  async function signIn() {
    const verifier = randomString(48);
    const state = randomString(16);
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    sessionStorage.setItem(STATE_KEY, state);

    const url = new URL(`${config.cognitoDomain}/oauth2/authorize`);
    url.searchParams.set('client_id', config.clientId);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('scope', 'openid email profile');
    url.searchParams.set('redirect_uri', redirectUri());
    url.searchParams.set('state', state);
    url.searchParams.set('code_challenge', await challengeFor(verifier));
    // S256 only. Omitting the method, or sending `plain`, fails with a bare
    // ?error=invalid_request redirect rather than a readable message.
    url.searchParams.set('code_challenge_method', 'S256');
    window.location.assign(url.toString());
  }

  /**
   * Where Cognito sends the browser back to, for both sign-in and sign-out.
   *
   * Derived from the origin actually serving this page rather than read from config.json, so one
   * uploaded bundle works behind CloudFront and on a dev server. Cognito compares this against the
   * app client's registered callback URLs as an exact string -- including the trailing slash -- so
   * check it here and say which origin is wrong, rather than letting Cognito answer with a
   * redirect_mismatch that names no URL.
   */
  function redirectUri() {
    const uri = `${window.location.origin}/`;
    const registered = config.callbackUrls || [];
    if (registered.length && !registered.includes(uri)) {
      throw new Error(
        `This app is being served from ${uri}, which is not a registered Cognito callback URL ` +
          `(registered: ${registered.join(', ')}). Redeploy with ` +
          `-c devOrigins=${window.location.origin} to add it.`,
      );
    }
    return uri;
  }

  async function completeRedirect() {
    const url = new URL(window.location.href);
    const error = url.searchParams.get('error');
    if (error) {
      const description = url.searchParams.get('error_description') || error;
      window.history.replaceState({}, '', url.pathname);
      throw new Error(description);
    }

    const code = url.searchParams.get('code');
    if (!code) return null;

    const returnedState = url.searchParams.get('state');
    const expectedState = sessionStorage.getItem(STATE_KEY);
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    // Always clear the URL, so a reload cannot replay a consumed code.
    window.history.replaceState({}, '', url.pathname);
    sessionStorage.removeItem(STATE_KEY);
    sessionStorage.removeItem(VERIFIER_KEY);

    if (!verifier) throw new Error('Sign-in could not be completed: the PKCE verifier was lost.');
    if (!returnedState || returnedState !== expectedState) {
      throw new Error('Sign-in could not be completed: the state parameter did not match.');
    }

    const payload = await exchange({
      grant_type: 'authorization_code',
      client_id: config.clientId,
      code,
      code_verifier: verifier,
      redirect_uri: redirectUri(),
    });
    const next = sessionFromTokenResponse(payload, null);
    saveSession(next);
    return next;
  }

  async function refresh() {
    if (!session || !session.refreshToken) return null;
    try {
      const payload = await exchange({
        grant_type: 'refresh_token',
        client_id: config.clientId,
        refresh_token: session.refreshToken,
      });
      const next = sessionFromTokenResponse(payload, session.refreshToken);
      saveSession(next);
      return next;
    } catch (err) {
      // invalid_grant means the refresh token is spent or revoked; the session is over.
      if (err.code === 'invalid_grant') saveSession(null);
      return null;
    }
  }

  async function idToken() {
    if (!session) return null;
    if (session.expiresAt - Date.now() > REFRESH_SKEW_SECONDS * 1000) return session.idToken;
    const refreshed = await refresh();
    return refreshed ? refreshed.idToken : null;
  }

  function signOut() {
    const url = new URL(`${config.cognitoDomain}/logout`);
    url.searchParams.set('client_id', config.clientId);
    // logout_uri must appear in the app client's logoutUrls -- a separate list from callbackUrls.
    url.searchParams.set('logout_uri', redirectUri());
    saveSession(null);
    window.location.assign(url.toString());
  }

  function subjectName() {
    const claims = (session && session.claims) || {};
    return claims.email || claims['cognito:username'] || claims.sub || 'signed in';
  }

  async function init() {
    config = await fetch('config.json', { cache: 'no-store' }).then((r) => r.json());

    // Fail here, with the offending value, rather than at Cognito. A stale or half-written
    // config.json sends the browser to the hosted UI with a client id that does not exist or is not
    // OAuth-enabled, and Cognito answers with a bare "Invalid input: Client is not enabled for
    // OAuth2.0 flows." page that says nothing about which client it means.
    for (const key of ['cognitoDomain', 'clientId', 'userPoolId']) {
      if (!config[key]) {
        throw new Error(
          `config.json is missing "${key}". Redeploy the stack; if that does not fix it, compare ` +
            'config.json against the UserPoolClientId and UserPoolId stack outputs.',
        );
      }
    }
    session = loadSession();
    const completed = await completeRedirect();
    if (completed) return completed;
    if (session && session.expiresAt - Date.now() <= REFRESH_SKEW_SECONDS * 1000) {
      return refresh();
    }
    return session;
  }

  window.SfcAuth = {
    init,
    signIn,
    signOut,
    idToken,
    subjectName,
    get config() {
      return config;
    },
    get session() {
      return session;
    },
  };
})();
