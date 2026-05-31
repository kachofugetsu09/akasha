"use strict";
(() => {
  function ai_fmt2(v) {
    if (v == null) return "-";
    return v.toFixed(2);
  }
  function ai_fmtScore(v) {
    if (v == null) return "-";
    const n = Number(v);
    const cls = n >= 0.5 ? "ai-score-hi" : n >= 0.25 ? "ai-score-mid" : "ai-score-lo";
    return `<span class="ai-score ${cls}">${n.toFixed(3)}</span>`;
  }
  function ai_sourceTag(source) {
    const cls = {
      Dense: "ai-src-dense",
      "Dense(FB)": "ai-src-densefb",
      FTS: "ai-src-fts",
      BlackHole: "ai-src-blackhole",
      Bridge: "ai-src-bridge"
    }[source] ?? "ai-src-other";
    return `<span class="ai-tag ${cls}">${escapeHtml(source)}</span>`;
  }
  function ai_pathTag(pt) {
    const cls = {
      direct: "ai-path-direct",
      "1hop": "ai-path-1hop",
      "2hop": "ai-path-2hop",
      bridge: "ai-path-bridge"
    }[pt] ?? "";
    return `<span class="ai-tag ${cls}">${escapeHtml(pt)}</span>`;
  }
  function ai_suppressedTag(s) {
    if (!s) return "";
    return `<span class="ai-tag ai-suppressed">${escapeHtml(s)}</span>`;
  }
  function ai_shortKey(key) {
    const parts = key.split(":");
    if (parts.length >= 2) {
      const seq = parts[parts.length - 1];
      const sk = parts.slice(0, -1).join(":");
      const short = sk.length > 20 ? "\u2026" + sk.slice(-18) : sk;
      return `${short}:${seq}`;
    }
    return key;
  }
  function ai_shortTs(value) {
    if (!value) return "-";
    const d = new Date(String(value));
    if (isNaN(d.getTime())) return String(value);
    return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  function ai_renderActivationTable(items) {
    if (!items.length) {
      return '<div class="ai-empty">\u65E0\u6FC0\u6D3B\u8282\u70B9</div>';
    }
    const rows = items.map((item) => `
    <tr class="${item.suppressed ? "ai-row-suppressed" : ""}">
      <td class="ai-cell-msg" title="${escapeHtml(item.user_message)}">${escapeHtml(item.user_message || "-")}</td>
      <td class="ai-cell-preview" title="${escapeHtml(item.assistant_preview)}">${escapeHtml(item.assistant_preview || "-")}</td>
      <td class="ai-cell-num">${ai_fmtScore(item.score)}</td>
      <td>${ai_sourceTag(item.source)}</td>
      <td>${ai_pathTag(item.path_type)}${ai_suppressedTag(item.suppressed)}</td>
      <td class="ai-cell-num mono">${item.fan}</td>
      <td class="ai-cell-num mono">${ai_fmt2(item.direct)}</td>
      <td class="ai-cell-num mono">${ai_fmt2(item.state)}</td>
      <td class="ai-cell-num mono">${ai_fmt2(item.edge)}</td>
      <td class="ai-cell-num mono">${ai_fmt2(item.long)}</td>
      <td class="ai-cell-num mono">${ai_fmt2(item.resource)}</td>
    </tr>
  `).join("");
    return `
    <div class="ai-table-wrap">
      <table class="ai-table ai-table-cards">
        <thead>
          <tr>
            <th class="ai-th-msg">user</th>
            <th class="ai-th-preview">assistant</th>
            <th>score</th><th>source</th><th>path</th>
            <th>fan</th><th>direct</th><th>state</th><th>edge</th><th>long</th><th>resource</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
  }
  function ai_renderCardTable(items, showPath) {
    if (!items.length) {
      return '<div class="ai-empty">\u65E0\u8BB0\u5F55</div>';
    }
    const extraHeaders = showPath ? "<th>path</th><th>seed</th><th>bridge</th>" : "";
    const rows = items.map((item) => {
      const srcRefIds = (() => {
        try {
          return JSON.parse(item.source_ref);
        } catch {
          return [];
        }
      })();
      const srcRefLink = srcRefIds.length ? `<span class="ai-source-ref" title="${escapeHtml(item.source_ref)}">${srcRefIds.length} msg</span>` : "-";
      const extraCells = showPath ? `<td>${ai_pathTag(item.path_type)}${ai_suppressedTag(item.suppressed)}</td>
         <td class="mono ai-cell-key" title="${escapeHtml(item.seed_key)}">${escapeHtml(ai_shortKey(item.seed_key))}</td>
         <td class="mono ai-cell-key" title="${escapeHtml(item.bridge_key)}">${escapeHtml(ai_shortKey(item.bridge_key))}</td>` : "";
      return `
      <tr>
        <td class="ai-cell-msg">${escapeHtml(item.user_message)}</td>
        <td class="ai-cell-preview">${escapeHtml(item.assistant_preview)}</td>
        <td class="ai-cell-num">${ai_fmtScore(item.score)}</td>
        <td>${ai_sourceTag(item.source)}</td>
        ${extraCells}
        <td>${srcRefLink}</td>
      </tr>
    `;
    }).join("");
    return `
    <div class="ai-table-wrap">
      <table class="ai-table ai-table-cards">
        <thead>
          <tr>
            <th class="ai-th-msg">user</th>
            <th class="ai-th-preview">assistant</th>
            <th>score</th>
            <th>source</th>
            ${extraHeaders}
            <th>ref</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
  }
  function ai_renderEmpty() {
    return `
    <div class="detail-empty">
      <div class="detail-empty-title">Akasha Inspector</div>
      <div class="detail-empty-text">\u70B9\u5F00\u4E00\u8F6E\u68C0\u7D22\u8BB0\u5F55\uFF0C\u8FD9\u91CC\u4F1A\u663E\u793A\u6FC0\u6D3B\u56FE\u3001Dense \u7CBE\u786E\u547D\u4E2D\u3001Ripple \u8054\u60F3\u547D\u4E2D\u548C\u6CE8\u5165\u9884\u89C8\u3002</div>
    </div>
  `;
  }
  function ai_renderDetail(item) {
    const threshold = (item.activation_threshold ?? 0).toFixed(3);
    return `
    <div class="detail-wrap ai-inspector">
      <div class="detail-toolbar">
        <div>
          <div class="detail-title">Akasha \u68C0\u7D22\u8BB0\u5F55</div>
          <div class="detail-subtext mono">${escapeHtml(item.session_key)} \xB7 seq ${item.seq}</div>
        </div>
      </div>

      <!-- 1. User Query -->
      <div class="detail-block">
        <div class="detail-label">User Query</div>
        <div class="ai-query-text">${escapeHtml(item.query_text)}</div>
        <div class="ai-meta-row">
          <span class="ai-meta-kv"><span class="ai-meta-k">intent</span><span class="ai-meta-v">${escapeHtml(item.intent)}</span></span>
          <span class="ai-meta-kv"><span class="ai-meta-k">ts</span><span class="ai-meta-v mono">${escapeHtml(ai_shortTs(item.ts))}</span></span>
        </div>
      </div>

      <!-- 2. Activation \u6FC0\u6D3B -->
      <div class="detail-block">
        <div class="detail-label">Activation \u6FC0\u6D3B</div>
        <div class="ai-stats-row">
          <div class="ai-stat"><span class="ai-stat-val">${item.seed_count}</span><span class="ai-stat-k">seeds</span></div>
          <div class="ai-stat-sep">\u2192</div>
          <div class="ai-stat"><span class="ai-stat-val">${item.pool_count}</span><span class="ai-stat-k">pool</span></div>
          <div class="ai-stat-sep">\u2192</div>
          <div class="ai-stat"><span class="ai-stat-val">${item.activated_count}</span><span class="ai-stat-k">activated</span></div>
          <div class="ai-stat-sep"> / </div>
          <div class="ai-stat"><span class="ai-stat-val ai-threshold">${threshold}</span><span class="ai-stat-k">threshold</span></div>
        </div>
        ${ai_renderActivationTable(item.activation_items || [])}
      </div>

      <!-- 3. Dense \u5DE6\u8111\u8BB0\u5FC6 -->
      <div class="detail-block">
        <div class="detail-label">\u5DE6\u8111\u8BB0\u5FC6\uFF1A\u7CBE\u786E\u56DE\u5FC6 <span class="ai-count-badge">${item.dense_count}</span></div>
        ${ai_renderCardTable(item.dense_items || [], false)}
      </div>

      <!-- 4. Ripple \u53F3\u8111\u8054\u60F3 -->
      <div class="detail-block">
        <div class="detail-label">\u53F3\u8111\u8054\u60F3\uFF1A\u6F5C\u610F\u8BC6\u7B2C\u4E00\u53CD\u5E94 <span class="ai-count-badge">${item.ripple_count}</span></div>
        ${ai_renderCardTable(item.ripple_items || [], true)}
      </div>

      <!-- 5. Prompt \u6CE8\u5165 -->
      <div class="detail-block">
        <div class="detail-label">Prompt \u6CE8\u5165</div>
        <div class="ai-stats-row">
          <div class="ai-stat"><span class="ai-stat-val">${item.dense_count}</span><span class="ai-stat-k">dense</span></div>
          <div class="ai-stat-sep">+</div>
          <div class="ai-stat"><span class="ai-stat-val">${item.ripple_count}</span><span class="ai-stat-k">ripple</span></div>
          <div class="ai-stat-sep">\xB7</div>
          <div class="ai-stat"><span class="ai-stat-val">${item.inject_chars}</span><span class="ai-stat-k">chars</span></div>
          <div class="ai-stat-sep">\xB7</div>
          <div class="ai-stat"><span class="ai-stat-val">${item.source_ref_count}</span><span class="ai-stat-k">refs</span></div>
        </div>
        ${item.text_block_preview ? `<details class="ai-preview-block"><summary>\u6CE8\u5165\u6587\u672C\u9884\u89C8</summary><pre class="ai-preview-pre">${escapeHtml(item.text_block_preview)}</pre></details>` : '<div class="ai-empty">\u672C\u8F6E\u65E0\u6CE8\u5165\uFF08\u975E context intent\uFF09</div>'}
      </div>
    </div>
  `;
  }
  window.AkashicDashboard.registerPlugin({
    id: "akasha_inspector",
    label: "Akasha Inspector",
    viewLabel: "akasha inspector",
    pageSize: 25,
    rowKey: "query_id",
    countTitle(total) {
      return `${total} \u8F6E\u68C0\u7D22`;
    },
    columns: [
      { key: "session_key", label: "Session", width: 108, fmt: "mono-session", cellClass: "mono cell-session", rawTitle: true },
      {
        key: "ts",
        label: "Time",
        width: 96,
        fmt: "mono-time",
        cellClass: "mono cell-time",
        rawTitle: true,
        renderCell(value) {
          return escapeHtml(ai_shortTs(value));
        }
      },
      { key: "query_text", label: "Query", flex: true, fmt: "text-preview", cellClass: "content-preview" },
      { key: "seed_count", label: "Seeds", width: 60, fmt: "metric", cellClass: "mono cell-metric", align: "right" },
      { key: "activated_count", label: "Active", width: 60, fmt: "metric", cellClass: "mono cell-metric", align: "right" },
      { key: "dense_count", label: "Dense", width: 60, fmt: "metric", cellClass: "mono cell-metric", align: "right" },
      { key: "ripple_count", label: "Ripple", width: 60, fmt: "metric", cellClass: "mono cell-metric", align: "right" },
      { key: "inject_chars", label: "Chars", width: 70, fmt: "metric", cellClass: "mono cell-metric", align: "right" }
    ],
    async getCount() {
      try {
        const r = await api("/api/dashboard/akasha-inspector/overview");
        return r.available ? r.total ?? 0 : null;
      } catch {
        return null;
      }
    },
    async fetchPage({ page, pageSize, filters }) {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (filters?.["session_key"]) params.set("session_key", filters["session_key"]);
      if (filters?.["q"]) params.set("q", filters["q"]);
      const data = await api(
        `/api/dashboard/akasha-inspector/turns?${params.toString()}`
      );
      return { items: data.items || [], total: data.total || 0 };
    },
    async fetchDetail(item) {
      const queryId = String(item["query_id"] ?? "");
      return api(`/api/dashboard/akasha-inspector/turns/${encodePath(queryId)}`);
    },
    renderDetail(item, container) {
      if (!item) {
        container.innerHTML = ai_renderEmpty();
        return;
      }
      container.innerHTML = ai_renderDetail(item);
    }
  });
})();
