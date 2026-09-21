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

  /** The window the chart opens on: the most recent minute of the table. */
  const DEFAULT_WINDOW_MS = 60000;
  const RELAYOUT_DEBOUNCE_MS = 300;
  const REQUEST_TIMEOUT_MS = 25000;
  const LATEST_AUTO_MS = 5000;
  /** Extra rows rendered above and below the viewport, so scrolling does not flash. */
  const ROWS_OVERSCAN = 12;
  /** Only mention progress once a load is big enough to be worth narrating. */
  const ROWS_PROGRESS_AFTER = 5000;
  /** Rows per /api/rows call while paging a window out with the beforeMs cursor. */
  const ROWS_PAGE_SIZE = 5000;
  /** Safety ceiling for a single window, shared by the table and the CSV export. */
  const ROWS_MAX = 500000;

  /**
   * Series colour slots, read from the stylesheet so light and dark stay in one place.
   *
   * Assigned in fixed order and never cycled: the palette was validated as an ordered set, so
   * slot 9 is not a generated hue -- MAX_SERIES caps what the UI will draw instead.
   */
  const SERIES_SLOTS = 8;
  const MAX_SERIES = SERIES_SLOTS;

  /** Sample markers are only legible below this density; above it the line alone is honest. */
  const MARKER_POINT_LIMIT = 220;

  const el = (id) => document.getElementById(id);

  const state = {
    config: null,
    columns: [],
    extent: null,
    window: null,
    valueColumns: [],
    dimValues: [],
    lastRequestSeq: 0,
    inFlight: null,
    applyingLayout: false,
    lastSeries: null,
    lastTrend: null,
    latestTimer: null,
    latest: null,
  };

  // ------------------------------------------------------------------------------------------
  // Theme
  // ------------------------------------------------------------------------------------------

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function seriesColour(index) {
    return cssVar(`--series-${(index % SERIES_SLOTS) + 1}`);
  }

  /**
   * Wired before authentication, and on both toggles: the signed-out page has its own, because the
   * top bar does not exist until the app view is shown.
   */
  function initTheme() {
    const stored = localStorage.getItem('sfc.theme');
    if (stored === 'light' || stored === 'dark') {
      document.documentElement.dataset.theme = stored;
    }
    const toggle = () => {
      const dark =
        document.documentElement.dataset.theme === 'dark' ||
        (!document.documentElement.dataset.theme &&
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      const next = dark ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('sfc.theme', next);
      // Plotly bakes colours into the traces, so the chart has to be repainted from the new tokens.
      if (state.lastSeries) render(state.lastSeries, state.lastTrend);
      refreshValueChips();
    };
    for (const id of ['theme-toggle', 'theme-toggle-login']) {
      const button = el(id);
      if (button) button.addEventListener('click', toggle);
    }
  }

  // ------------------------------------------------------------------------------------------
  // Formatting
  // ------------------------------------------------------------------------------------------

  /** `2026-09-21 09:52:14.937 UTC` -- unambiguous, sortable, and explicitly zoned. */
  function formatUtc(ms, { millis = true } = {}) {
    if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—';
    const d = new Date(Number(ms));
    const p = (n, w = 2) => String(n).padStart(w, '0');
    const base =
      `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
      `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
    return millis ? `${base}.${p(d.getUTCMilliseconds(), 3)}` : base;
  }

  function formatAgo(ms) {
    const delta = Date.now() - Number(ms);
    if (!Number.isFinite(delta)) return '';
    const s = Math.round(delta / 1000);
    if (s < 0) return 'in the future';
    if (s < 60) return `${s}s ago`;
    const m = Math.round(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 48) return `${h}h ago`;
    return `${Math.round(h / 24)}d ago`;
  }

  function formatDuration(ms) {
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60000) return `${+(ms / 1000).toFixed(ms % 1000 ? 2 : 0)} s`;
    if (ms < 3600000) return `${+(ms / 60000).toFixed(1)} min`;
    if (ms < 86400000) return `${+(ms / 3600000).toFixed(1)} h`;
    return `${+(ms / 86400000).toFixed(1)} d`;
  }

  function formatCount(n) {
    return Number(n).toLocaleString('en-US');
  }

  function formatNumber(v) {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    return Number.isInteger(n) ? formatCount(n) : n.toPrecision(6).replace(/\.?0+$/, '');
  }

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

  function setTile(id, value, note) {
    el(id).textContent = value;
    const noteEl = el(`${id}-note`);
    if (noteEl) noteEl.textContent = note || '';
  }

  function showLogin(message) {
    el('app-view').hidden = true;
    el('login-view').hidden = false;
    const error = el('login-error');
    error.textContent = message || '';
    error.hidden = !message;

    // Cognito's own error pages never name the client they rejected, so pair it with the message.
    const client = el('login-client');
    const cfg = window.SfcAuth.config;
    if (message && cfg && cfg.clientId) {
      client.textContent = `App client ${cfg.clientId} · user pool ${cfg.userPoolId}`;
      client.hidden = false;
    } else {
      client.hidden = true;
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
      option.value = value;
      option.textContent = value === '' ? '— none —' : value;
      if (value === selected) option.selected = true;
      select.appendChild(option);
    }
  }

  /**
   * Toggle chips, used instead of a multi-select so the chosen series are visible without opening
   * anything. Each selected chip shows its own series colour, matching the chart.
   */
  function renderChips(container, values, selected, onChange, colourBySelectionOrder) {
    container.innerHTML = '';
    values.forEach((value) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip';
      const on = selected.includes(value);
      chip.setAttribute('aria-pressed', String(on));
      if (on && colourBySelectionOrder) {
        chip.style.setProperty('--chip-colour', seriesColour(selected.indexOf(value)));
      }
      const swatch = document.createElement('span');
      swatch.className = 'chip-swatch';
      chip.append(swatch, document.createTextNode(value));
      chip.addEventListener('click', () => onChange(value));
      container.appendChild(chip);
    });
  }

  function refreshValueChips() {
    const numeric = state.columns.filter((c) => c.role === 'numeric').map((c) => c.name);
    renderChips(
      el('value-columns'),
      numeric,
      state.valueColumns,
      (name) => {
        const at = state.valueColumns.indexOf(name);
        if (at >= 0) state.valueColumns.splice(at, 1);
        else if (state.valueColumns.length < MAX_SERIES) state.valueColumns.push(name);
        else {
          setStatus(`At most ${MAX_SERIES} series at once. Deselect one first.`, 'error');
          return;
        }
        refreshValueChips();
        run(draw);
      },
      true,
    );
  }

  function refreshDimChips(values) {
    renderChips(
      el('dim-values'),
      values,
      state.dimValues,
      (value) => {
        const at = state.dimValues.indexOf(value);
        if (at >= 0) state.dimValues.splice(at, 1);
        else state.dimValues.push(value);
        refreshDimChips(values);
        run(draw);
      },
      false,
    );
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
      : 'Only the buckets this stack was deployed with may be queried; others return 403.';
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
    setStatus('', 'ok');
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
    state.valueColumns = numericColumns.slice(0, Math.min(3, numericColumns.length));
    refreshValueChips();

    fillSelect(el('dim-column'), ['', ...dimensionColumns]);
    state.dimValues = [];
    el('dim-values-wrap').hidden = true;

    el('shape-panel').hidden = false;
    el('schema-panel').hidden = false;
    el('latest-card').hidden = false;
    el('tiles').hidden = false;
    el('chart-title').textContent = `${ref.namespace}.${ref.table}`;
    el('schema-meta').textContent = `${columns.length} columns`;

    const extent = await callApi('/api/extent', { ...ref, timeColumn: timeColumns[0] });
    if (extent.rowCount === 0 || extent.minMs === null) {
      throw new Error('The table exists but holds no rows yet. Let the simulator flush once.');
    }
    state.extent = extent;
    // Start on the newest minute rather than the whole history: at a 250 ms schedule the full extent
    // is far more than a screen's worth, and this is the view an operator wants first.
    const head = extent.maxMs + 1;
    state.window = { t0: Math.max(extent.minMs, head - DEFAULT_WINDOW_MS), t1: head };

    setTile(
      'stat-rows',
      formatCount(extent.rowCount),
      `${formatUtc(extent.minMs, { millis: false })} → ${formatUtc(extent.maxMs, { millis: false })}`,
    );
    setStatus('', 'ok');
  }

  function renderSchema(columns) {
    const tbody = el('schema-table').querySelector('tbody');
    tbody.innerHTML = '';
    for (const col of columns) {
      const tr = document.createElement('tr');
      tr.className = `role-${col.role}`;

      const name = document.createElement('td');
      name.textContent = col.name;
      const type = document.createElement('td');
      type.textContent = col.type;
      const role = document.createElement('td');
      const pill = document.createElement('span');
      pill.className = `role-pill role-${col.role}`;
      pill.textContent = col.role;
      role.appendChild(pill);

      tr.append(name, type, role);
      tbody.appendChild(tr);
    }
  }

  async function onDimColumnChange() {
    const column = el('dim-column').value;
    const wrap = el('dim-values-wrap');
    if (!column) {
      wrap.hidden = true;
      state.dimValues = [];
      return;
    }
    setStatus(`Reading distinct values of ${column}…`, 'busy');
    const { values, truncated } = await callApi('/api/distinct', {
      ...currentRef(),
      dimensionColumn: column,
      limit: 200,
    });
    state.dimValues = values.slice(0, Math.min(4, values.length));
    refreshDimChips(values);
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
  // Latest readings
  // ------------------------------------------------------------------------------------------

  /**
   * Every row in the chart's window, so the table and the curve are strictly coupled.
   *
   * Two things make "every row" workable. The window is paged out with the same beforeMs keyset
   * cursor the CSV export uses, because one response is capped server-side. And the rows are rendered
   * virtually -- only the visible slice exists in the DOM -- since a minute of 250 ms data is 240 rows
   * but the `all` button can be six figures, which no amount of DOM would survive.
   */
  async function loadLatest() {
    if (!state.columns.length || !state.window) return;
    const timeColumn = el('time-column').value;
    const { t0, t1 } = state.window;

    const { columns, rows, timeIdx } = await fetchRawRows(
      currentRef(),
      timeColumn,
      t0,
      t1,
      (n) => {
        if (n > ROWS_PROGRESS_AFTER) el('latest-note').textContent = `Loading rows… ${formatCount(n)}`;
      },
    );

    state.latest = { columns, rows, timeIdx, timeColumn };
    renderLatest();

    const capped = rows.length >= ROWS_MAX;
    const span =
      `${formatUtc(t0, { millis: false })} → ${formatUtc(t1 - 1, { millis: false })} UTC`;
    el('latest-note').textContent = rows.length
      ? `All ${formatCount(rows.length)} rows in the charted window (${span})` +
        (capped ? ` — stopped at the ${formatCount(ROWS_MAX)} row cap` : '')
      : `No rows in the charted window (${span}).`;
  }

  /**
   * Virtualised table body: filler rows above and below carry the scroll height, and only the slice
   * on screen is built. Keeps a sticky header and normal table layout, unlike an absolute-positioned
   * list.
   */
  function renderLatest() {
    const host = el('latest');
    const data = state.latest;
    if (!data) return;

    const roleOf = new Map(state.columns.map((c) => [c.name, c.role]));

    const table = document.createElement('table');
    table.className = 'data-table';
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    data.columns.forEach((name, i) => {
      const th = document.createElement('th');
      th.textContent = i === data.timeIdx ? `${name} (UTC)` : name;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    const tbody = document.createElement('tbody');
    table.append(thead, tbody);
    host.innerHTML = '';
    host.appendChild(table);

    const buildRow = (row) => {
      const tr = document.createElement('tr');
      // Rows are positional arrays aligned to `columns`; never assume a column order.
      row.forEach((value, i) => {
        const td = document.createElement('td');
        const role = roleOf.get(data.columns[i]);
        if (i === data.timeIdx) {
          td.className = 'time';
          td.textContent = formatUtc(value);
        } else if (value === null) {
          td.className = 'null';
          td.textContent = '∅';
        } else if (role === 'numeric') {
          td.className = 'num';
          td.textContent = formatNumber(value);
        } else {
          td.textContent = String(value);
        }
        tr.appendChild(td);
      });
      return tr;
    };

    // Row height is measured rather than assumed, so a font or padding change cannot desync the
    // filler heights from the real rows.
    const probe = buildRow(data.rows[0] || []);
    tbody.appendChild(probe);
    const rowHeight = probe.getBoundingClientRect().height || 27;
    tbody.innerHTML = '';

    // Classed so the hover, striping and last-child border rules can skip them.
    const topFiller = document.createElement('tr');
    topFiller.className = 'filler';
    topFiller.setAttribute('aria-hidden', 'true');
    const bottomFiller = document.createElement('tr');
    bottomFiller.className = 'filler';
    bottomFiller.setAttribute('aria-hidden', 'true');
    let firstRendered = -1;

    const paint = () => {
      const viewRows = Math.ceil(host.clientHeight / rowHeight) + ROWS_OVERSCAN * 2;
      const first = Math.max(0, Math.floor(host.scrollTop / rowHeight) - ROWS_OVERSCAN);
      if (first === firstRendered) return;
      firstRendered = first;
      const last = Math.min(data.rows.length, first + viewRows);

      const frag = document.createDocumentFragment();
      topFiller.style.height = `${first * rowHeight}px`;
      frag.appendChild(topFiller);
      for (let i = first; i < last; i++) frag.appendChild(buildRow(data.rows[i]));
      bottomFiller.style.height = `${Math.max(0, data.rows.length - last) * rowHeight}px`;
      frag.appendChild(bottomFiller);

      tbody.innerHTML = '';
      tbody.appendChild(frag);
    };

    host.onscroll = paint;
    paint();
  }

  /**
   * Pull in data written since the last query: the table's extent, the curve, and the rows.
   *
   * The chart needs the extent re-read, not just a redraw. state.extent is captured when the table
   * loads and bounds both the range slider and the "all" button, so rows written after that instant
   * sit outside every window the UI can ask for -- which is why the table showed new samples while
   * the curve stayed still.
   *
   * Whether to move the view is decided from where it already was. If the window ended at the old
   * head, the user was watching live and the window advances to the new head, keeping its span. If
   * they had zoomed into history, the window is left exactly where they put it. draw() reloads the
   * row table itself, so this does not fetch rows separately.
   */
  async function refreshAll() {
    if (!state.columns.length || !state.extent) return;
    const timeColumn = el('time-column').value;
    const previous = state.extent;

    const extent = await callApi('/api/extent', { ...currentRef(), timeColumn });
    if (extent.rowCount === 0 || extent.minMs === null) return;

    // One bucket of tolerance, so a window that merely rounds short of the head still counts.
    const tolerance = Math.max(state.lastSeries ? state.lastSeries.bucketMs : 0, 1000);
    const wasAtHead = state.window && state.window.t1 >= previous.maxMs + 1 - tolerance;

    state.extent = extent;
    setTile(
      'stat-rows',
      formatCount(extent.rowCount),
      `${formatUtc(extent.minMs, { millis: false })} → ${formatUtc(extent.maxMs, { millis: false })}`,
    );

    if (wasAtHead && state.window) {
      const span = state.window.t1 - state.window.t0;
      const t1 = extent.maxMs + 1;
      // Keep the span unless the view covered everything, in which case keep covering everything.
      const coveredAll = state.window.t0 <= previous.minMs;
      state.window = { t0: coveredAll ? extent.minMs : Math.max(extent.minMs, t1 - span), t1 };
    }

    const added = extent.rowCount - previous.rowCount;
    await draw();
    setStatus(
      added > 0
        ? `${formatCount(added)} new row(s) · latest ${formatUtc(extent.maxMs)} UTC`
        : `No new rows · latest ${formatUtc(extent.maxMs)} UTC`,
      'ok',
    );
  }

  function setLatestAuto(on) {
    if (state.latestTimer) {
      clearInterval(state.latestTimer);
      state.latestTimer = null;
    }
    if (on) state.latestTimer = setInterval(() => run(refreshAll), LATEST_AUTO_MS);
  }


  // ------------------------------------------------------------------------------------------
  // CSV export
  // ------------------------------------------------------------------------------------------

  /** RFC 4180: quote any field containing a comma, quote or newline, and double inner quotes. */
  function csvField(value) {
    if (value === null || value === undefined) return '';
    const text = String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }


  /**
   * Export the raw stored rows for the visible window, newest first.
   *
   * plotly.js has no CSV export of its own -- its modebar only offers a PNG (`toImage`) -- so this is
   * registered as a custom modebar button. It deliberately exports the SAMPLES rather than the
   * aggregates behind the curve: the chart is downsampled to stay drawable, and a file that inherited
   * that thinning would be useless for anything you actually want a CSV for.
   *
   * /api/rows caps a single response, so the window is walked with the beforeMs keyset cursor. That
   * cursor is inclusive, so the trailing rows sharing the last timestamp are dropped here and
   * re-fetched on the next page -- otherwise a page boundary landing inside one timestamp would skip
   * the rest of its rows, which is the normal case for a narrow table carrying a row per tag.
   */
  async function fetchRawRows(ref, timeColumn, t0, t1, onProgress) {
    const rows = [];
    let columns = null;
    let beforeMs = null;
    let timeIdx = -1;

    for (;;) {
      const page = await callApi('/api/rows', {
        ...ref,
        timeColumn,
        t0Ms: t0,
        t1Ms: t1,
        limit: ROWS_PAGE_SIZE,
        ...(beforeMs === null ? {} : { beforeMs }),
      });
      if (!columns) {
        columns = page.columns;
        timeIdx = columns.indexOf(timeColumn);
        if (timeIdx < 0) throw new Error(`The rows do not include ${timeColumn}.`);
      }
      if (!page.rows.length) break;

      let batch = page.rows;
      if (page.truncated) {
        const oldest = batch[batch.length - 1][timeIdx];
        // Trim the whole trailing timestamp, then resume at it.
        let cut = batch.length;
        while (cut > 0 && batch[cut - 1][timeIdx] === oldest) cut--;
        if (cut === 0) {
          // A page entirely of one timestamp: emit it and step strictly past, or we would loop.
          rows.push(...batch);
          beforeMs = oldest - 1;
          onProgress(rows.length);
          if (rows.length >= ROWS_MAX) break;
          continue;
        }
        batch = batch.slice(0, cut);
        // Resume AT the trimmed timestamp, not at the last kept row: the cursor is inclusive, so
        // pointing it at a row we already emitted would return that row again on the next page.
        beforeMs = oldest;
      }
      rows.push(...batch);
      onProgress(rows.length);

      if (!page.truncated || rows.length >= ROWS_MAX) break;
    }
    return { columns, rows, timeIdx };
  }

  async function downloadCsv() {
    if (!state.window || !state.columns.length) {
      setStatus('Nothing to export yet — load a table first.', 'error');
      return;
    }
    const ref = currentRef();
    const timeColumn = el('time-column').value;
    const { t0, t1 } = state.window;

    setStatus('Exporting raw rows…', 'busy');
    const { columns, rows, timeIdx } = await fetchRawRows(ref, timeColumn, t0, t1, (n) =>
      setStatus(`Exporting raw rows… ${formatCount(n)}`, 'busy'),
    );
    if (!rows.length) {
      setStatus('No rows in the visible window.', 'error');
      return;
    }

    // A readable UTC timestamp first, then the raw epoch millis, then every stored column.
    const header = [`${timeColumn}_utc`, ...columns];
    const lines = [header.map(csvField).join(',')];
    for (const row of rows) {
      lines.push([formatUtc(row[timeIdx]), ...row].map(csvField).join(','));
    }
    // CRLF per RFC 4180, and a trailing newline so the file ends on a record boundary.
    const csv = lines.join('\r\n') + '\r\n';

    const stamp = formatUtc(t0, { millis: false }).replace(/[: ]/g, '-');
    const name = `${ref.namespace}.${ref.table}-${stamp}-raw.csv`;

    // A Blob download works under the deployed Content-Security-Policy: an anchor with `download`
    // is not a navigation or a fetch, so none of the default-src/connect-src directives apply.
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoked on the next tick so the download has already been handed off.
    setTimeout(() => URL.revokeObjectURL(url), 0);

    const capped = rows.length >= ROWS_MAX;
    setStatus(
      `Exported ${formatCount(rows.length)} raw row(s) to ${name}` +
        (capped ? ` — stopped at the ${formatCount(ROWS_MAX)} row cap` : ''),
      capped ? 'error' : 'ok',
    );
  }

  // ------------------------------------------------------------------------------------------
  // Charting
  // ------------------------------------------------------------------------------------------

  /** Resolution follows the visible window, so zooming in refines the curve. */
  function pickBucketMs(spanMs) {
    const target = Math.max(1, Math.floor(spanMs / TARGET_POINTS));
    return BUCKET_LADDER.find((b) => b >= target) || BUCKET_LADDER[BUCKET_LADDER.length - 1];
  }

  function seriesRequest() {
    const request = {
      ...currentRef(),
      timeColumn: el('time-column').value,
      valueColumns: state.valueColumns.slice(),
      t0Ms: state.window.t0,
      t1Ms: state.window.t1,
      bucketMs: pickBucketMs(state.window.t1 - state.window.t0),
      maxPoints: TARGET_POINTS,
    };
    const dim = el('dim-column').value;
    if (dim) {
      request.dimensionColumn = dim;
      request.dimensionValues = state.dimValues.slice();
    }
    return request;
  }

  async function draw() {
    if (!state.window) return;
    const request = seriesRequest();
    if (!request.valueColumns.length) throw new Error('Select at least one series.');
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
    const span = series.t1Ms - series.t0Ms;
    setMeta(`${series.series.length} series · ${formatCount(points)} points`);
    setTile('stat-window', formatDuration(span), `${formatUtc(series.t0Ms, { millis: false })} UTC`);
    setTile(
      'stat-bucket',
      formatDuration(series.bucketMs),
      `${formatCount(Math.round(span / series.bucketMs))} buckets`,
    );
    setTile(
      'stat-points',
      formatCount(points),
      series.truncated ? 'truncated' : `${series.series.length} series`,
    );
    // Keeps the table on exactly the window the chart just drew.
    await loadLatest();
    setStatus('', 'ok');
  }

  function trendRequestFrom(request) {
    const { bucketMs, maxPoints, ...rest } = request;
    return rest;
  }

  function render(series, trend) {
    state.lastSeries = series;
    state.lastTrend = trend;

    const traces = [];
    const showBand = el('show-band').checked;
    const ink = cssVar('--ink');
    const inkMuted = cssVar('--ink-muted');
    const grid = cssVar('--grid');
    const surface = cssVar('--surface');

    series.series.forEach((entry, index) => {
      const colour = seriesColour(index);
      const x = entry.points.map((p) => new Date(p[0]).toISOString());
      // Markers mark the actual returned samples. Past this density they merge into a smear, so the
      // line carries it alone and they reappear as you zoom in.
      const withMarkers = entry.points.length <= MARKER_POINT_LIMIT;

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
          fillcolor: hexToRgba(colour, 0.14),
          hoverinfo: 'skip',
          showlegend: false,
          legendgroup: entry.key,
        });
      }

      const line = {
        x,
        y: entry.points.map((p) => p[1]),
        name: entry.key,
        type: 'scatter',
        mode: withMarkers ? 'lines+markers' : 'lines',
        line: { width: 2, color: colour, shape: 'linear' },
        legendgroup: entry.key,
        customdata: entry.points.map((p) => [p[2], p[3], p[4]]),
        hovertemplate:
          `<b>${entry.key}</b>  %{y:.6g}` +
          '<br>min %{customdata[0]:.6g} · max %{customdata[1]:.6g} · n %{customdata[2]}' +
          '<extra></extra>',
      };
      if (withMarkers) {
        // Open markers: a surface-filled dot ringed in the series colour stays legible where the
        // line doubles back on itself. Set only when used -- a `marker: undefined` key makes Plotly
        // throw "Cannot use 'in' operator to search for 'line' in undefined".
        line.marker = { size: 8, color: surface, line: { width: 2, color: colour } };
      }
      traces.push(line);
    });

    if (trend) renderTrend(trend, traces);
    else el('trend-badges').innerHTML = '';

    const axis = {
      gridcolor: grid,
      zeroline: false,
      linecolor: grid,
      tickfont: { color: inkMuted, size: 11 },
    };

    const layout = {
      margin: { l: 58, r: 18, t: 10, b: 40 },
      height: 460,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: ink, size: 12 },
      hovermode: 'x unified',
      hoverlabel: {
        bgcolor: surface,
        bordercolor: cssVar('--line-strong'),
        font: { color: ink, size: 12 },
      },
      // A legend is always present for two or more series; one series is named by the card title.
      showlegend: series.series.length > 1 || Boolean(trend),
      legend: { orientation: 'h', y: -0.26, font: { color: cssVar('--ink-2'), size: 11 } },
      xaxis: {
        ...axis,
        type: 'date',
        range: [new Date(state.window.t0).toISOString(), new Date(state.window.t1).toISOString()],
        showspikes: true,
        spikemode: 'across',
        spikethickness: 1,
        spikedash: 'dot',
        spikecolor: cssVar('--line-strong'),
        rangeslider: {
          // Pin the overview to the table's full history. The slider previews whatever data its
          // trace holds, so without this it would collapse to the zoomed subset after the first
          // drill-down.
          range: [
            new Date(state.extent.minMs).toISOString(),
            new Date(state.extent.maxMs + 1).toISOString(),
          ],
          thickness: 0.07,
          bgcolor: cssVar('--plane'),
          bordercolor: grid,
        },
        rangeselector: {
          // Each button sets the visible window; the bucket width then follows from it, so a
          // narrower window is also a finer query.
          buttons: [
            { step: 'second', stepmode: 'backward', count: 10, label: '10s' },
            { step: 'second', stepmode: 'backward', count: 30, label: '30s' },
            { step: 'minute', stepmode: 'backward', count: 1, label: '1min' },
            { step: 'minute', stepmode: 'backward', count: 5, label: '5m' },
            { step: 'minute', stepmode: 'backward', count: 30, label: '30m' },
            { step: 'hour', stepmode: 'backward', count: 1, label: '1h' },
            { step: 'hour', stepmode: 'backward', count: 6, label: '6h' },
            { step: 'day', stepmode: 'backward', count: 1, label: '1d' },
            { step: 'all', label: 'all' },
          ],
          bgcolor: cssVar('--plane'),
          activecolor: cssVar('--accent-soft'),
          bordercolor: cssVar('--line-strong'),
          borderwidth: 1,
          font: { color: cssVar('--ink-2'), size: 11 },
          x: 0,
          y: 1.06,
        },
      },
      yaxis: { ...axis, fixedrange: false },
    };

    const chart = el('chart');
    // applyingLayout suppresses the relayout our own render triggers, which would otherwise loop.
    state.applyingLayout = true;
    Plotly.react(chart, traces, layout, {
      displaylogo: false,
      responsive: true,
      // sendDataToCloud POSTs the plotted data to Plotly's servers -- never wanted here, and the
      // Content-Security-Policy would block it anyway.
      modeBarButtonsToRemove: ['lasso2d', 'select2d', 'toggleSpikelines', 'sendDataToCloud'],
      // plotly.js ships no CSV export, so add one next to its PNG button.
      modeBarButtonsToAdd: [
        {
          name: 'Download CSV',
          title: 'Download the raw rows for the visible window as CSV',
          icon: Plotly.Icons.disk,
          click: () => run(downloadCsv),
        },
      ],
    })
      .then(() => {
        state.applyingLayout = false;
        if (!chart.dataset.bound) {
          chart.dataset.bound = '1';
          chart.on('plotly_relayout', onRelayout);
        }
      })
      .catch((err) => {
        // Without this the chart fails to an empty div and the status bar still reads "ok".
        state.applyingLayout = false;
        setStatus(`Could not draw the chart: ${err && err.message ? err.message : err}`, 'error');
      });
  }

  /** Plotly needs a concrete rgba() for fills; the tokens are hex. */
  function hexToRgba(hex, alpha) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
    if (!m) return hex;
    const n = parseInt(m[1], 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }

  function renderTrend(trend, traces) {
    const badges = el('trend-badges');
    badges.innerHTML = '';
    trend.fits.forEach((fit, index) => {
      if (fit.slopePerSecond === null || fit.slopePerSecond === undefined) return;
      const colour = seriesColour(index);
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
        line: { width: 2, dash: 'dash', color: colour },
        hovertemplate: `trend ${fit.key}: %{y:.6g}<extra></extra>`,
      });

      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.style.setProperty('--badge-colour', colour);
      const r2 = fit.r2 === null || fit.r2 === undefined ? '—' : Number(fit.r2).toFixed(3);
      badge.innerHTML =
        `<strong>${fit.key}</strong> ${Number(fit.slopePerSecond).toPrecision(3)} /s ` +
        `<span class="dim">R² ${r2} · n ${formatCount(fit.n)}</span>`;
      badge.title =
        'Least-squares fit over the visible window. n counts only rows where both the value and ' +
        'the timestamp are non-null, so it can be lower than the row count.';
      badges.appendChild(badge);
    });
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
    if (!keys.some((k) => k.startsWith('xaxis'))) return;

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
    initTheme();
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
    el('load-table').addEventListener('click', () =>
      run(async () => {
        await loadTable();
        await draw();
      }),
    );
    el('dim-column').addEventListener('change', () => run(onDimColumnChange));
    el('draw').addEventListener('click', () => run(draw));
    el('show-band').addEventListener('change', () => run(draw));
    el('show-trend').addEventListener('change', () => run(draw));
    el('latest-refresh').addEventListener('click', () => run(refreshAll));
    el('chart-refresh').addEventListener('click', () => run(refreshAll));
    el('latest-auto').addEventListener('change', (e) => setLatestAuto(e.target.checked));

    run(async () => {
      await loadBuckets();
      await loadCatalog();
    });
  }

  window.addEventListener('DOMContentLoaded', () => run(start));
})();
