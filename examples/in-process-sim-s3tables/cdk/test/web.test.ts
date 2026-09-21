// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as fs from 'fs';
import * as path from 'path';

const WEB = path.join(__dirname, '..', 'web');
const read = (f: string) => fs.readFileSync(path.join(WEB, f), 'utf8');

describe('web app view switching', () => {
  const html = read('index.html');

  it('switches only elements that carry the hidden attribute', () => {
    // Any view app.js toggles must be declared hidden in the markup, or it renders before the
    // first switch and flashes.
    const toggled = ['login-view', 'app-view', 'shape-panel', 'schema-panel', 'dim-values-wrap'];
    for (const id of toggled) {
      const tag = html.match(new RegExp(`<[^>]*id="${id}"[^>]*>`));
      expect({ id, found: Boolean(tag) }).toEqual({ id, found: true });
      expect({ id, hidden: /\shidden(\s|>|=)/.test(tag![0]) }).toEqual({ id, hidden: true });
    }
  });

  it('loads Plotly and the app scripts locally, with no CDN origin', () => {
    // A third-party script host would have to be added to the Content-Security-Policy, and
    // cdn.plot.ly publishes no subresource-integrity hashes to pin.
    const srcs = [...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map((m) => m[1]);
    expect(srcs.length).toBeGreaterThan(0);
    for (const src of srcs) {
      expect({ src, remote: /^https?:\/\//.test(src) }).toEqual({ src, remote: false });
      expect(fs.existsSync(path.join(WEB, src))).toBe(true);
    }
  });
});
