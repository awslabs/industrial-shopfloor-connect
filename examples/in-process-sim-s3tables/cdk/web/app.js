// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Iceberg timeseries explorer.
 *
 * The app knows nothing about the table's schema in advance. It asks /api/schema which columns
 * exist and what role each plays, then offers those columns as chart inputs. That is what lets the
 * same UI handle a wide table (one column per machine tag) and a narrow one (one row per tag
 * reading, pivoted with "Split by").
 *
 * Drill-down is server-side: zooming re-queries /api/series for the visible window at a finer
 * bucket width, rather than resampling points the browser already has.
 */
(function () {
  'use strict';

  const BUCKET_LADDER = [
    1, 2, 5, 10, 20, 50, 100, 200, 250, 500,
    1000, 2000, 5000, 10000, 15000, 30000,
    60000, 120000, 300000, 600000, 900000, 1800000,
    3600000, 7200000, 21600000, 43200000,
    86400000, 604800000,
  ];
  const TARGET_POINTS = 1200;
  const RELAYOUT_DEBOUNCE_MS = 300;
  const REQUEST_TIMEOUT_MS = 25000;

  const el = (id) => document.getElementById(id);

  const state = {
    config: null,
    columns: [],
    extent: null,
    window: null,
    lastRequestSeq: 0,
    inFlight: null,
    applyingLayout: false,
  };

  // ------------------------------------------------------------------------------------------
  // API
  // ------------------------------------------------------------------------------------------

  /**
   * One place that talks to the API.
   *
   * Always branches on content-type instead of calling response.json() blindly: CloudFront's own
   * 502/503/504 pages are HTML, and 413 REQUEST_TOO_LARGE is the one API Gateway response whose
   * body cannot be customised into the JSON error envelope.
   */
  async function callApi(route, body, options) {
    const token = await window.SfcAuth.idToken();
    if (!token) {
      showLogin('Your session expired. Sign in again.');
      throw new Error('Not signed in');
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    if (options && options.signal) {
      options.signal.addEventListener('abort', () => controller.abort());
    }

    let response;
    try {
      // route already starts with /api/, matching the OpenAPI paths. apiBase is an optional ORIGIN
      // prefix, empty for the same-origin CloudFront path.
      response = await fetch(`${state.config.apiBase || ''}${route}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token },
        body: JSON.stringify(body || {}),
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') {
        throw new Error(
          'The request was cancelled after 25 seconds. A cold start can take several seconds; ' +
            'if this persists, narrow the time window.',
        );
      }
      throw err;
    }
    clearTimeout(timer);

    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      const text = await response.text();
      throw new Error(
        `Unexpected ${response.status} response from ${route}: ${text.slice(0, 200) || '(empty)'}`,
      );
    }
    const payload = await response.json();
    if (!response.ok) {
      const error = payload.error || {};
      if (response.status === 401 || error.code === 'EXPIRED_TOKEN') {
        showLogin('Your session expired. Sign in again.');
      }
      const err = new Error(error.message || `${route} failed with ${response.status}`);
      err.code = error.code;
      err.requestId = error.requestId;
      throw err;
    }
    return payload;
  }

  // ------------------------------------------------------------------------------------------
  // Chrome
  // ------------------------------------------------------------------------------------------

  function setStatus(text, kind) {
    const node = el('status');
    node.textContent = text || '';
    node.className = `status${kind ? ' ' + kind : ''}`;
  }

  function setMeta(text) {
    el('meta').textContent = text || '';
  }

  function showLogin(message) {
    el('app-view').hidden = true;
    el('login-view').hidden = false;
    const error = el('login-error');
    error.textContent = message || '';
    error.hidden = !message;

    // Cognito's own error pages never name the client they rejected, so surface it here.
    const client = el('login-client');
    const cfg = window.SfcAuth.config;
    if (cfg && cfg.clientId) {
      client.textContent = `App client ${cfg.clientId} · user pool ${cfg.userPoolId}`;
      client.hidden = false;
    }
  }

  function showApp() {
    el('login-view').hidden = true;
    el('app-view').hidden = false;
    el('user-name').textContent = window.SfcAuth.subjectName();
  }

  function fillSelect(select, values, selected) {
    select.innerHTML = '';
    for (const value of values) {
      const option = document.createElement('option');
      option.value = typeof value === 'string' ? value : value.value;
      option.textContent = typeof value === 'string' ? value : value.label;
      if (option.value === selected) option.selected = true;
      select.appendChild(option);
    }
  }

  function selectedValues(select) {
    return Array.from(select.selectedOptions).map((o) => o.value);
  }

  // ------------------------------------------------------------------------------------------
  // Discovery
  // ------------------------------------------------------------------------------------------

  async function loadBuckets() {
    const { tableBuckets, allowAny } = await callApi('/api/buckets', {});
    const datalist = el('table-bucket-options');
    datalist.innerHTML = '';
    for (const name of tableBuckets) {
      const option = document.createElement('option');
      option.value = name;
      datalist.appendChild(option);
    }
    if (!el('table-bucket').value) {
      el('table-bucket').value = tableBuckets[0] || state.config.tableBucketNames[0] || '';
    }
    el('bucket-hint').textContent = allowAny
      ? `${tableBuckets.length} table bucket(s) discovered in this account. Any of them may be queried.`
      : 'Only the buckets this stack was deployed with may be queried. Others return 403.';
  }

  async function loadCatalog() {
    const tableBucket = el('table-bucket').value.trim();
    if (!tableBucket) throw new Error('Enter a table bucket name.');
    setStatus('Reading the Iceberg catalog…', 'busy');
    const { namespaces } = await callApi('/api/catalog', { tableBucket });
    if (!namespaces.length) {
      throw new Error(
        `No namespaces in ${tableBucket}. If the SFC simulator has not written yet, start it ` +
          'first -- it creates the namespace and table on its first flush.',
      );
    }
    state.namespaces = namespaces;
    const preferred = namespaces.find((n) => n.namespace === state.config.defaultNamespace);
    fillSelect(
      el('namespace'),
      namespaces.map((n) => n.namespace),
      (preferred || namespaces[0]).namespace,
    );
    onNamespaceChange();
    setStatus(`${namespaces.length} namespace(s) in ${tableBucket}.`, 'ok');
  }

  function onNamespaceChange() {
    const ns = state.namespaces.find((n) => n.namespace === el('namespace').value);
    const tables = (ns && ns.tables) || [];
    fillSelect(el('table'), tables, state.config.defaultTable);
  }

  async function loadTable() {
    const ref = currentRef();
    setStatus('Describing the table…', 'busy');
    const { columns } = await callApi('/api/schema', ref);
    state.columns = columns;
    renderSchema(columns);

    const timeColumns = columns.filter((c) => c.role === 'time').map((c) => c.name);
    const numericColumns = columns.filter((c) => c.role === 'numeric').map((c) => c.name);
    const dimensionColumns = columns.filter((c) => c.role === 'dimension').map((c) => c.name);

    if (!timeColumns.length) throw new Error('This table has no timestamp column to chart against.');
    if (!numericColumns.length) throw new Error('This table has no numeric column to chart.');

    fillSelect(el('time-column'), timeColumns, timeColumns[0]);
    fillSelect(el('value-columns'), numericColumns);
    // Preselect the first few so "Draw" works immediately.
    Array.from(el('value-columns').options)
      .slice(0, Math.min(3, numericColumns.length))
      .forEach((o) => (o.selected = true));

    fillSelect(el('dim-column'), ['', ...dimensionColumns]);
    el('dim-column').options[0].textContent = '— none —';
    el('dim-values-wrap').hidden = true;

    el('shape-panel').hidden = false;
    el('schema-panel').hidden = false;

    const extent = await callApi('/api/extent', { ...ref, timeColumn: timeColumns[0] });
    if (extent.rowCount === 0 || extent.minMs === null) {
      throw new Error('The table exists but holds no rows yet. Let the simulator flush once.');
    }
    state.extent = extent;
    state.window = { t0: extent.minMs, t1: extent.maxMs + 1 };
    setStatus(
      `${extent.rowCount.toLocaleString()} rows, ${new Date(extent.minMs).toISOString()} → ` +
        `${new Date(extent.maxMs).toISOString()}.`,
      'ok',
    );
  }

  function renderSchema(columns) {
    const tbody = el('schema-table').querySelector('tbody');
    tbody.innerHTML = '';
    for (const col of columns) {
      const tr = document.createElement('tr');
      for (const value of [col.name, col.type, col.role]) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }
      tr.className = `role-${col.role}`;
      tbody.appendChild(tr);
    }
  }

  async function onDimColumnChange() {
    const column = el('dim-column').value;
    const wrap = el('dim-values-wrap');
    if (!column) {
      wrap.hidden = true;
      return;
    }
    setStatus(`Reading distinct values of ${column}…`, 'busy');
    const { values, truncated } = await callApi('/api/distinct', {
      ...currentRef(),
      dimensionColumn: column,
      limit: 200,
    });
    fillSelect(el('dim-values'), values);
    Array.from(el('dim-values').options)
      .slice(0, Math.min(4, values.length))
      .forEach((o) => (o.selected = true));
    wrap.hidden = false;
    setStatus(
      `${values.length} distinct value(s)${truncated ? ' (truncated)' : ''} for ${column}.`,
      'ok',
    );
  }

  function currentRef() {
    return {
      tableBucket: el('table-bucket').value.trim(),
      namespace: el('namespace').value,
      table: el('table').value,
    };
  }

  // ------------------------------------------------------------------------------------------
  // Charting
  // ------------------------------------------------------------------------------------------

  function pickBucketMs(spanMs) {
    const target = Math.max(1, Math.floor(spanMs / TARGET_POINTS));
    return BUCKET_LADDER.find((b) => b >= target) || BUCKET_LADDER[BUCKET_LADDER.length - 1];
  }

  function seriesRequest() {
    const request = {
      ...currentRef(),
      timeColumn: el('time-column').value,
      valueColumns: selectedValues(el('value-columns')),
      t0Ms: state.window.t0,
      t1Ms: state.window.t1,
      bucketMs: pickBucketMs(state.window.t1 - state.window.t0),
      maxPoints: TARGET_POINTS,
    };
    const dim = el('dim-column').value;
    if (dim) {
      request.dimensionColumn = dim;
      request.dimensionValues = selectedValues(el('dim-values'));
    }
    return request;
  }

  async function draw() {
    if (!state.window) return;
    const request = seriesRequest();
    if (!request.valueColumns.length) throw new Error('Select at least one numeric column.');
    if (request.dimensionColumn && !request.dimensionValues.length) {
      throw new Error('Select at least one value to split by.');
    }

    // Cancel any query the user has already superseded, and tag this one so a late reply from an
    // earlier zoom cannot overwrite a newer view.
    if (state.inFlight) state.inFlight.abort();
    const controller = new AbortController();
    state.inFlight = controller;
    const seq = ++state.lastRequestSeq;

    setStatus('Querying…', 'busy');
    const [series, trend] = await Promise.all([
      callApi('/api/series', request, { signal: controller.signal }),
      el('show-trend').checked
        ? callApi('/api/trend', trendRequestFrom(request), { signal: controller.signal })
        : Promise.resolve(null),
    ]);
    if (seq !== state.lastRequestSeq) return;
    state.inFlight = null;

    render(series, trend);
    const points = series.series.reduce((sum, s) => sum + s.points.length, 0);
    setMeta(
      `bucket ${formatDuration(series.bucketMs)} · ${series.series.length} series · ` +
        `${points.toLocaleString()} points${series.truncated ? ' · truncated' : ''}`,
    );
    setStatus('', 'ok');
    void loadRowPreview();
  }

  function trendRequestFrom(request) {
    const { bucketMs, maxPoints, ...rest } = request;
    return rest;
  }

  function formatDuration(ms) {
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${ms / 1000} s`;
    if (ms < 3600000) return `${ms / 60000} min`;
    if (ms < 86400000) return `${ms / 3600000} h`;
    return `${ms / 86400000} d`;
  }

  function render(series, trend) {
    const traces = [];
    const showBand = el('show-band').checked;

    series.series.forEach((entry, index) => {
      const colour = `hsl(${(index * 47) % 360} 65% 45%)`;
      const x = entry.points.map((p) => new Date(p[0]).toISOString());

      if (showBand) {
        // fill: 'tonexty' fills toward the PREVIOUS trace, so the upper bound must be added first,
        // then the lower bound carrying the fill, then the average line on top.
        traces.push({
          x,
          y: entry.points.map((p) => p[3]),
          name: `${entry.key} max`,
          type: 'scatter',
          mode: 'lines',
          line: { width: 0, color: colour },
          hoverinfo: 'skip',
          showlegend: false,
          legendgroup: entry.key,
        });
        traces.push({
          x,
          y: entry.points.map((p) => p[2]),
          name: `${entry.key} min`,
          type: 'scatter',
          mode: 'lines',
          line: { width: 0, color: colour },
          fill: 'tonexty',
          fillcolor: `hsl(${(index * 47) % 360} 65% 45% / 0.15)`,
          hoverinfo: 'skip',
          showlegend: false,
          legendgroup: entry.key,
        });
      }

      traces.push({
        x,
        y: entry.points.map((p) => p[1]),
        name: entry.key,
        type: 'scatter',
        mode: 'lines',
        line: { width: 1.6, color: colour },
        legendgroup: entry.key,
        hovertemplate: `%{x}<br>${entry.key}: %{y:.4g}<extra></extra>`,
      });
    });

    if (trend) {
      renderTrend(trend, traces);
    } else {
      el('trend-badges').innerHTML = '';
    }

    const layout = {
      margin: { l: 56, r: 16, t: 12, b: 40 },
      height: 520,
      hovermode: 'x unified',
      showlegend: true,
      legend: { orientation: 'h', y: -0.28 },
      xaxis: {
        type: 'date',
        range: [new Date(state.window.t0).toISOString(), new Date(state.window.t1).toISOString()],
        rangeslider: {
          // Pin the overview to the table's full history. The slider previews whatever data its
          // trace holds, so without this it would collapse to the zoomed subset after the first
          // drill-down.
          range: [
            new Date(state.extent.minMs).toISOString(),
            new Date(state.extent.maxMs + 1).toISOString(),
          ],
          thickness: 0.08,
        },
        rangeselector: {
          buttons: [
            { step: 'minute', stepmode: 'backward', count: 5, label: '5m' },
            { step: 'minute', stepmode: 'backward', count: 30, label: '30m' },
            { step: 'hour', stepmode: 'backward', count: 1, label: '1h' },
            { step: 'hour', stepmode: 'backward', count: 6, label: '6h' },
            { step: 'day', stepmode: 'backward', count: 1, label: '1d' },
            { step: 'all', label: 'all' },
          ],
        },
      },
      yaxis: { fixedrange: false, zeroline: false },
    };

    const chart = el('chart');
    // applyingLayout suppresses the relayout our own render triggers, which would otherwise loop.
    state.applyingLayout = true;
    Plotly.react(chart, traces, layout, {
      displaylogo: false,
      responsive: true,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    }).then(() => {
      state.applyingLayout = false;
      if (!chart.dataset.bound) {
        chart.dataset.bound = '1';
        chart.on('plotly_relayout', onRelayout);
      }
    });
  }

  function renderTrend(trend, traces) {
    const badges = el('trend-badges');
    badges.innerHTML = '';
    for (const fit of trend.fits) {
      if (fit.slopePerSecond === null || fit.slopePerSecond === undefined) continue;
      const t0 = trend.xOriginMs;
      const t1 = state.window.t1;
      const y0 = fit.intercept;
      const y1 = fit.intercept + fit.slopePerSecond * ((t1 - t0) / 1000);
      traces.push({
        x: [new Date(t0).toISOString(), new Date(t1).toISOString()],
        y: [y0, y1],
        name: `${fit.key} trend`,
        type: 'scatter',
        mode: 'lines',
        line: { width: 1.4, dash: 'dash', color: '#444' },
        hovertemplate: `trend ${fit.key}: %{y:.4g}<extra></extra>`,
      });

      const badge = document.createElement('span');
      badge.className = 'badge';
      const r2 = fit.r2 === null || fit.r2 === undefined ? '—' : Number(fit.r2).toFixed(3);
      badge.innerHTML =
        `<strong>${fit.key}</strong> ${Number(fit.slopePerSecond).toPrecision(3)} /s ` +
        `<span class="dim">R²&nbsp;${r2} · n&nbsp;${Number(fit.n).toLocaleString()}</span>`;
      badge.title =
        'Least-squares fit over the visible window. n counts only rows where both the value and ' +
        'the timestamp are non-null, so it can be lower than the row count.';
      badges.appendChild(badge);
    }
  }

  /**
   * Re-query on zoom or pan.
   *
   * The event payload is only used as a trigger. The authoritative range is read from the graph's
   * own layout, because one logical x-range change arrives in four different payload shapes
   * (plotly.js#1877): 'xaxis.range[0]'/'[1]' from a plot zoom, 'xaxis.range' as a two-element array
   * from a range-slider drag, a bare 'xaxis.autorange: true' from a double-click, and a full nested
   * object on window resize.
   */
  const onRelayout = debounce(function (eventData) {
    if (state.applyingLayout || !state.extent) return;

    const keys = Object.keys(eventData || {});
    const relevant = keys.some((k) => k.startsWith('xaxis'));
    if (!relevant) return;

    const layout = el('chart').layout || {};
    const axis = layout.xaxis || {};

    let t0;
    let t1;
    if (axis.autorange || eventData['xaxis.autorange']) {
      // A reset carries no range values, so fall back to the extent fetched at load.
      t0 = state.extent.minMs;
      t1 = state.extent.maxMs + 1;
    } else if (Array.isArray(axis.range) && axis.range.length === 2) {
      t0 = toEpochMs(axis.range[0]);
      t1 = toEpochMs(axis.range[1]);
    } else {
      return;
    }
    if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 <= t0) return;

    // Clamp to the data we actually have, so panning past the edges does not query empty space.
    t0 = Math.max(t0, state.extent.minMs);
    t1 = Math.min(t1, state.extent.maxMs + 1);
    if (t1 - t0 < 1) return;

    state.window = { t0: Math.round(t0), t1: Math.round(t1) };
    run(draw);
  }, RELAYOUT_DEBOUNCE_MS);

  /**
   * Plotly's date-axis range values are zone-less UTC strings, truncated by window width: over
   * 90 days it yields a bare 'YYYY-MM-DD', under 5 minutes it yields four fractional digits. It also
   * discards any timezone suffix on input. Normalise to epoch ms before anything reaches SQL.
   */
  function toEpochMs(value) {
    if (typeof value === 'number') return value;
    if (value instanceof Date) return value.getTime();
    const text = String(value).trim();
    const iso = text.includes('T') ? text : text.replace(' ', 'T');
    const withZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
    const parsed = Date.parse(withZone);
    return Number.isNaN(parsed) ? NaN : parsed;
  }

  function debounce(fn, waitMs) {
    let timer = null;
    return function (...args) {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        fn.apply(this, args);
      }, waitMs);
    };
  }

  async function loadRowPreview() {
    if (!el('rows-details').open) return;
    const payload = await callApi('/api/rows', {
      ...currentRef(),
      timeColumn: el('time-column').value,
      t0Ms: state.window.t0,
      t1Ms: state.window.t1,
      limit: 50,
    });
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    for (const name of payload.columns) {
      const th = document.createElement('th');
      th.textContent = name;
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const row of payload.rows) {
      const tr = document.createElement('tr');
      // Rows are positional arrays aligned to `columns`; never assume a column order.
      row.forEach((value) => {
        const td = document.createElement('td');
        td.textContent = value === null ? '∅' : String(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    const host = el('rows');
    host.innerHTML = '';
    host.appendChild(table);
  }

  // ------------------------------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------------------------------

  /** Run an async handler, surfacing any failure in the status bar rather than the console. */
  function run(fn) {
    Promise.resolve()
      .then(fn)
      .catch((err) => {
        if (err && err.name === 'AbortError') return;
        const suffix = err && err.requestId ? ` (request ${err.requestId})` : '';
        setStatus(`${err.message}${suffix}`, 'error');
      });
  }

  async function start() {
    el('sign-in').addEventListener('click', () => run(() => window.SfcAuth.signIn()));
    el('sign-out').addEventListener('click', () => window.SfcAuth.signOut());

    let session = null;
    try {
      session = await window.SfcAuth.init();
    } catch (err) {
      showLogin(err.message);
      return;
    }
    state.config = window.SfcAuth.config;

    if (!session) {
      showLogin();
      return;
    }
    showApp();

    el('namespace').addEventListener('change', onNamespaceChange);
    el('table-bucket').addEventListener('change', () => run(loadCatalog));
    el('load-table').addEventListener('click', () => run(async () => {
      await loadTable();
      await draw();
    }));
    el('dim-column').addEventListener('change', () => run(onDimColumnChange));
    el('draw').addEventListener('click', () => run(draw));
    el('show-band').addEventListener('change', () => run(draw));
    el('show-trend').addEventListener('change', () => run(draw));
    el('rows-details').addEventListener('toggle', () => run(loadRowPreview));

    run(async () => {
      await loadBuckets();
      await loadCatalog();
    });
  }

  window.addEventListener('DOMContentLoaded', () => run(start));
})();
