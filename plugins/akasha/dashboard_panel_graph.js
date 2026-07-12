// plugins/akasha/dashboard_panel_graph.ts
function ghEscape(value) {
  return escapeHtml(String(value || ""));
}
function ghEdges(edges) {
  return edges.map((edge) => [edge.s, edge.t, edge.w, edge.cc, edge.sim]);
}
function renderAkashaGraph(container) {
  const previous = container.__agDispose;
  if (previous) previous();
  container.innerHTML = `
    <div class="ag-html">
      <canvas id="c"></canvas>
      <div id="hud">
        <b>Akasha \u771F\u5B9E\u8BB0\u5FC6\u56FE</b><br>telegram \u5B50\u56FE \xB7 \u6570\u636E\u900F\u660E\u7248<br>
        <span id="stat">\u5E03\u5C40\u8BA1\u7B97\u4E2D...</span>
        <div style="position:relative;">
          <input id="search" placeholder="\u641C\u7D22\u8BB0\u5FC6\u6B63\u6587\u2026">
          <div id="search_results"></div>
        </div>
        <div id="slider-container">
          <input type="range" id="cc_slider" min="1" max="10" value="2">
          <span style="font-size:11px">\u5171\u73B0\u9891\u6B21 &ge; <span id="cc_val" style="color:#fff;font-weight:bold;font-size:13px">2</span></span>
        </div>
        <div class="hint">\u8FDC\u666F\u770B\u5927\u5C9B \xB7 \u4E2D\u666F\u770B\u5B50\u5C9B \xB7 \u8FD1\u666F\u770B\u8054\u60F3\u6839\u7CFB</div>
      </div>
      <div id="leg"></div>
      <div id="loading_card" class="ag-loading-card">
        <div class="ag-loading-kicker">Akasha Graph</div>
        <div class="ag-loading-title">\u6B63\u5728\u751F\u6210\u5168\u91CF\u8BB0\u5FC6\u56FE</div>
        <div class="ag-loading-copy">\u7B2C\u4E00\u6B21\u8FDB\u5165\u9700\u8981\u6784\u5EFA snapshot\uFF0C\u4E4B\u540E\u4F1A\u76F4\u63A5\u8BFB\u53D6\u7F13\u5B58\u3002</div>
        <div class="ag-loading-track"><div id="loading_bar"></div></div>
        <div id="loading_note" class="ag-loading-note">\u542F\u52A8\u540E\u53F0\u5E03\u5C40\u4EFB\u52A1...</div>
      </div>
      <div id="tip"></div>
      <div id="node_detail"></div>
    </div>
  `;
  let disposed = false;
  container.__agDispose = () => {
    disposed = true;
    if (pollTimer !== void 0) window.clearInterval(pollTimer);
    if (tweenFrame !== void 0) cancelAnimationFrame(tweenFrame);
    window.removeEventListener("resize", resize);
    window.removeEventListener("mouseup", onMouseUp);
    document.removeEventListener("click", onDocumentClick);
  };
  const root = container.querySelector(".ag-html");
  const cv = root.querySelector("#c");
  const ctx = cv.getContext("2d");
  const tip = root.querySelector("#tip");
  const stat = root.querySelector("#stat");
  const legEl = root.querySelector("#leg");
  const loadingCard = root.querySelector("#loading_card");
  const loadingBar = root.querySelector("#loading_bar");
  const loadingNote = root.querySelector("#loading_note");
  const detailPanel = root.querySelector("#node_detail");
  const searchEl = root.querySelector("#search");
  const resEl = root.querySelector("#search_results");
  const slider = root.querySelector("#cc_slider");
  const ccVal = root.querySelector("#cc_val");
  let NODES = [];
  let EDGES = [];
  let LEG = [];
  let COMMUNITIES = [];
  let SUB_ISLANDS = [];
  let childByNode = [];
  let nodeIsRepresentative = [];
  let parentLinks = [];
  let childLinks = [];
  let W = 1;
  let H = 1;
  let DPR = 1;
  let scale = 0.6;
  let tx = 0;
  let ty = 0;
  let ccThreshold = 2;
  let adj = [];
  let adjEdges = [];
  let hover = -1;
  let pinned = -1;
  let filter = "";
  let drag = false;
  let lx = 0;
  let ly = 0;
  let moved = false;
  let hlColor = null;
  let currentVersion = "";
  let pollTimer;
  let tweenFrame;
  let lockedColor = null;
  let hlInternalPath = new Path2D();
  let hlCrossPath = new Path2D();
  const globalEdgeScaleLimit = 1.2;
  const loadingStartedAt = Date.now();
  let loadingTick = 0;
  function updateHlPaths() {
    hlInternalPath = new Path2D();
    hlCrossPath = new Path2D();
    if (!hlColor) return;
    for (const [a, b, , cc] of EDGES) {
      if (cc < ccThreshold) continue;
      const nA = NODES[a], nB = NODES[b];
      const aOn = nA.c === hlColor;
      const bOn = nB.c === hlColor;
      if (!aOn && !bOn) continue;
      if (aOn !== bOn) {
        hlCrossPath.moveTo(nA.x, nA.y);
        hlCrossPath.lineTo(nB.x, nB.y);
      } else {
        hlInternalPath.moveTo(nA.x, nA.y);
        hlInternalPath.lineTo(nB.x, nB.y);
      }
    }
  }
  function flyTo(targetScale, targetTx, targetTy) {
    if (tweenFrame) cancelAnimationFrame(tweenFrame);
    const startScale = scale, startTx = tx, startTy = ty;
    let progress = 0;
    function step() {
      progress += 0.08;
      if (progress >= 1) {
        scale = targetScale;
        tx = targetTx;
        ty = targetTy;
        draw();
        return;
      }
      const ease = 1 - Math.pow(1 - progress, 3);
      scale = startScale + (targetScale - startScale) * ease;
      tx = startTx + (targetTx - startTx) * ease;
      ty = startTy + (targetTy - startTy) * ease;
      draw();
      tweenFrame = requestAnimationFrame(step);
    }
    step();
  }
  function flyToCommunity(c) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of NODES) {
      if (n.c === c) {
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
      }
    }
    if (minX === Infinity) return;
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const w = maxX - minX;
    const h = maxY - minY;
    const targetScale = w > 0 && h > 0 ? Math.max(0.2, Math.min(Math.min((W - 120) / w, (H - 120) / h), 2.5)) : Math.max(scale, 1.2);
    const targetTx = W / 2 - cx * targetScale;
    const targetTy = H / 2 - cy * targetScale;
    flyTo(targetScale, targetTx, targetTy);
  }
  function resize() {
    if (disposed) return;
    const rect = root.getBoundingClientRect();
    W = Math.max(320, rect.width);
    H = Math.max(320, rect.height);
    DPR = window.devicePixelRatio || 1;
    cv.width = W * DPR;
    cv.height = H * DPR;
    cv.style.width = `${W}px`;
    cv.style.height = `${H}px`;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    draw();
  }
  function fit() {
    const m = 60;
    const s = Math.min(W - 2 * m, H - 2 * m) / 1e3;
    scale = Math.max(0.2, s);
    tx = (W - 1e3 * scale) / 2;
    ty = (H - 1e3 * scale) / 2;
  }
  function X(x) {
    return x * scale + tx;
  }
  function Y(y) {
    return y * scale + ty;
  }
  function invX(px) {
    return (px - tx) / scale;
  }
  function invY(py) {
    return (py - ty) / scale;
  }
  function activeId() {
    return pinned;
  }
  function colorAlpha(color, alpha) {
    const safeAlpha = Math.max(0, Math.min(1, alpha));
    if (color.startsWith("hsl(")) return color.replace("hsl(", "hsla(").replace(")", `,${safeAlpha})`);
    const hex = color.startsWith("#") ? color.slice(1) : "";
    if (hex.length === 6) {
      const r = parseInt(hex.slice(0, 2), 16);
      const g = parseInt(hex.slice(2, 4), 16);
      const b = parseInt(hex.slice(4, 6), 16);
      return `rgba(${r},${g},${b},${safeAlpha})`;
    }
    return color;
  }
  function rebalanceFractalSpacing() {
    const groups = /* @__PURE__ */ new Map();
    for (const n of NODES) {
      const old = groups.get(n.g);
      if (old) {
        old.count += 1;
        old.sx += n.x;
        old.sy += n.y;
      } else {
        groups.set(n.g, { count: 1, sx: n.x, sy: n.y });
      }
    }
    const centers = /* @__PURE__ */ new Map();
    for (const [g, item] of groups.entries()) {
      centers.set(g, {
        x: item.sx / item.count,
        y: item.sy / item.count,
        spread: item.count >= 180 ? 1.55 : item.count >= 70 ? 1.42 : 1.26
      });
    }
    const world = { x: 500, y: 500 };
    NODES = NODES.map((node) => {
      const center = centers.get(node.g);
      if (!center) return node;
      const cx = world.x + (center.x - world.x) * 0.74;
      const cy = world.y + (center.y - world.y) * 0.74;
      return {
        ...node,
        x: cx + (node.x - center.x) * center.spread,
        y: cy + (node.y - center.y) * center.spread
      };
    });
  }
  function recomputeAdj() {
    adj = NODES.map(() => []);
    adjEdges = NODES.map(() => []);
    for (const edge of EDGES) {
      const [a, b, , cc] = edge;
      if (cc >= ccThreshold) {
        adj[a].push(b);
        adj[b].push(a);
        adjEdges[a].push(edge);
        adjEdges[b].push(edge);
      }
    }
    recomputeLinks();
  }
  function recomputeCommunities() {
    const groups = /* @__PURE__ */ new Map();
    const nodesByGroup = /* @__PURE__ */ new Map();
    for (let i = 0; i < NODES.length; i += 1) {
      const n = NODES[i];
      const bucket = nodesByGroup.get(n.g);
      if (bucket) bucket.push(i);
      else nodesByGroup.set(n.g, [i]);
      const old = groups.get(n.g);
      const label = LEG[n.g]?.label || `\u793E\u533A ${n.g}`;
      if (!old) {
        groups.set(n.g, {
          c: n.c,
          label,
          count: 1,
          sx: n.x,
          sy: n.y,
          minX: n.x,
          minY: n.y,
          maxX: n.x,
          maxY: n.y
        });
        continue;
      }
      old.count += 1;
      old.sx += n.x;
      old.sy += n.y;
      old.minX = Math.min(old.minX, n.x);
      old.minY = Math.min(old.minY, n.y);
      old.maxX = Math.max(old.maxX, n.x);
      old.maxY = Math.max(old.maxY, n.y);
    }
    COMMUNITIES = [...groups.entries()].map(([g, item]) => {
      const x = item.sx / item.count;
      const y = item.sy / item.count;
      const dx = Math.max(x - item.minX, item.maxX - x);
      const dy = Math.max(y - item.minY, item.maxY - y);
      return {
        g,
        c: item.c,
        size: item.count,
        label: item.label,
        x,
        y,
        r: Math.max(18, Math.hypot(dx, dy) + 10 + Math.sqrt(item.count) * 1.8)
      };
    }).sort((a, b) => b.size - a.size);
    recomputeSubIslands(nodesByGroup);
  }
  function recomputeSubIslands(nodesByGroup) {
    SUB_ISLANDS = [];
    childByNode = NODES.map(() => -1);
    nodeIsRepresentative = NODES.map(() => false);
    for (const comm of COMMUNITIES) {
      const indexes = nodesByGroup.get(comm.g) || [];
      const parts = splitSubIslands(indexes, comm);
      for (const part of parts) {
        const id = SUB_ISLANDS.length;
        let sx = 0, sy = 0;
        for (const nodeIndex of part) {
          sx += NODES[nodeIndex].x;
          sy += NODES[nodeIndex].y;
        }
        const x = sx / part.length;
        const y = sy / part.length;
        let far = 0;
        for (const nodeIndex of part) {
          const n = NODES[nodeIndex];
          far = Math.max(far, Math.hypot(n.x - x, n.y - y));
          childByNode[nodeIndex] = id;
        }
        const sub = {
          id,
          parent: comm.g,
          c: comm.c,
          size: part.length,
          x,
          y,
          r: Math.max(7, far + 4 + Math.sqrt(part.length) * 0.9)
        };
        SUB_ISLANDS.push(sub);
        markRepresentatives(part, sub);
      }
    }
  }
  function splitSubIslands(indexes, comm) {
    if (indexes.length < 32) return [indexes];
    const k = Math.max(2, Math.min(8, Math.round(Math.sqrt(indexes.length) / 2.7)));
    const centers = [];
    let first = indexes[0];
    let far = -1;
    for (const nodeIndex of indexes) {
      const n = NODES[nodeIndex];
      const d = Math.hypot(n.x - comm.x, n.y - comm.y);
      if (d > far) {
        far = d;
        first = nodeIndex;
      }
    }
    centers.push({ x: NODES[first].x, y: NODES[first].y });
    while (centers.length < k) {
      let next = indexes[0];
      let best = -1;
      for (const nodeIndex of indexes) {
        const n = NODES[nodeIndex];
        let nearest = Infinity;
        for (const c of centers) nearest = Math.min(nearest, Math.hypot(n.x - c.x, n.y - c.y));
        if (nearest > best) {
          best = nearest;
          next = nodeIndex;
        }
      }
      centers.push({ x: NODES[next].x, y: NODES[next].y });
    }
    let buckets = [];
    for (let iter = 0; iter < 5; iter += 1) {
      buckets = Array.from({ length: centers.length }, () => []);
      for (const nodeIndex of indexes) {
        const n = NODES[nodeIndex];
        let pick2 = 0;
        let best = Infinity;
        for (let i = 0; i < centers.length; i += 1) {
          const c = centers[i];
          const d = Math.hypot(n.x - c.x, n.y - c.y);
          if (d < best) {
            best = d;
            pick2 = i;
          }
        }
        buckets[pick2].push(nodeIndex);
      }
      for (let i = 0; i < buckets.length; i += 1) {
        if (!buckets[i].length) continue;
        let sx = 0, sy = 0;
        for (const nodeIndex of buckets[i]) {
          sx += NODES[nodeIndex].x;
          sy += NODES[nodeIndex].y;
        }
        centers[i] = { x: sx / buckets[i].length, y: sy / buckets[i].length };
      }
    }
    return buckets.filter((bucket) => bucket.length > 0);
  }
  function markRepresentatives(indexes, sub) {
    const limit = Math.min(5, Math.max(1, Math.round(Math.sqrt(indexes.length) / 3)));
    const ranked = [...indexes].sort((a, b) => {
      const na = NODES[a], nb = NODES[b];
      return Math.hypot(na.x - sub.x, na.y - sub.y) - Math.hypot(nb.x - sub.x, nb.y - sub.y);
    });
    for (const nodeIndex of ranked.slice(0, limit)) nodeIsRepresentative[nodeIndex] = true;
  }
  function recomputeLinks() {
    const commByGroup = new Map(COMMUNITIES.map((comm) => [comm.g, comm]));
    const parentAgg = /* @__PURE__ */ new Map();
    const childAgg = /* @__PURE__ */ new Map();
    for (const [a, b, w, cc] of EDGES) {
      if (cc < ccThreshold) continue;
      const na = NODES[a], nb = NODES[b];
      if (na.g !== nb.g && cc >= 5) {
        addAgg(parentAgg, na.g, nb.g, cc, w);
      }
      const ca = childByNode[a], cb = childByNode[b];
      if (ca >= 0 && cb >= 0 && ca !== cb && cc >= 3) {
        const sameParent = SUB_ISLANDS[ca]?.parent === SUB_ISLANDS[cb]?.parent;
        if (sameParent || cc >= 8) addAgg(childAgg, ca, cb, cc, w);
      }
    }
    parentLinks = [...parentAgg.values()].map((item) => {
      const a = commByGroup.get(item.a);
      const b = commByGroup.get(item.b);
      if (!a || !b) return null;
      return linkFrom(a, b, item.cc, item.w, true);
    }).filter((item) => item !== null).sort((a, b) => b.strength - a.strength).slice(0, 240);
    childLinks = [...childAgg.values()].map((item) => {
      const a = SUB_ISLANDS[item.a];
      const b = SUB_ISLANDS[item.b];
      if (!a || !b) return null;
      return linkFrom(a, b, item.cc, item.w, a.parent !== b.parent);
    }).filter((item) => item !== null).sort((a, b) => b.strength - a.strength).slice(0, 1100);
  }
  function addAgg(map, a, b, cc, w) {
    const x = Math.min(a, b);
    const y = Math.max(a, b);
    const key = `${x}:${y}`;
    const old = map.get(key);
    if (old) {
      old.cc += cc;
      old.w = Math.max(old.w, w);
    } else {
      map.set(key, { a: x, b: y, cc, w });
    }
  }
  function linkFrom(a, b, cc, w, cross) {
    return {
      ax: a.x,
      ay: a.y,
      bx: b.x,
      by: b.y,
      color: cross ? "#d7e4ff" : a.c,
      strength: Math.sqrt(cc) * Math.max(0.04, w),
      cross
    };
  }
  function drawIslands(act) {
    ctx.save();
    ctx.translate(tx, ty);
    ctx.scale(scale, scale);
    for (let i = COMMUNITIES.length - 1; i >= 0; i -= 1) {
      const comm = COMMUNITIES[i];
      const active = act >= 0 && NODES[act]?.g === comm.g;
      const alpha = active ? 0.22 : scale < 0.9 ? 0.12 : 0.06;
      const radius = comm.r + (scale < 0.9 ? 10 : 4);
      const gradient = ctx.createRadialGradient(
        comm.x,
        comm.y,
        Math.max(4, radius * 0.12),
        comm.x,
        comm.y,
        radius
      );
      gradient.addColorStop(0, colorAlpha(comm.c, alpha));
      gradient.addColorStop(0.72, colorAlpha(comm.c, alpha * 0.32));
      gradient.addColorStop(1, colorAlpha(comm.c, 0));
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(comm.x, comm.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    if (scale > 0.68) {
      for (const sub of SUB_ISLANDS) {
        const active = act >= 0 && childByNode[act] === sub.id;
        const alpha = active ? 0.28 : scale < 1.18 ? 0.15 : 0.08;
        const radius = sub.r + (scale < 1.1 ? 3 : 1.5);
        const gradient = ctx.createRadialGradient(sub.x, sub.y, 1, sub.x, sub.y, radius);
        gradient.addColorStop(0, colorAlpha(sub.c, alpha));
        gradient.addColorStop(0.68, colorAlpha(sub.c, alpha * 0.28));
        gradient.addColorStop(1, colorAlpha(sub.c, 0));
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(sub.x, sub.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    if (scale < 0.95) {
      ctx.textBaseline = "middle";
      ctx.font = `${Math.max(9 / scale, 7)}px sans-serif`;
      for (const comm of COMMUNITIES) {
        if (comm.size < 60) continue;
        const label = comm.label.split(" \xB7 ")[0] || `\u793E\u533A ${comm.g}`;
        ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--color-muted");
        ctx.fillText(`[${comm.size}] ${label.slice(0, 16)}`, comm.x - comm.r * 0.32, comm.y - comm.r - 8 / scale);
      }
    }
    ctx.restore();
  }
  function drawGlobalEdges() {
    drawIslandLinks(parentLinks, scale < 0.75 ? 0.42 : 0.24, 1.35);
    if (scale > 0.72) drawIslandLinks(childLinks, scale < 1.08 ? 0.22 : 0.13, 0.78);
  }
  function drawIslandLinks(links, alphaBase, widthBase) {
    ctx.save();
    ctx.translate(tx, ty);
    ctx.scale(scale, scale);
    for (const link of links) {
      const dx = link.bx - link.ax;
      const dy = link.by - link.ay;
      const len = Math.max(1, Math.hypot(dx, dy));
      const bend = Math.min(60, len * 0.12) * (link.cross ? 1 : -0.5);
      const cx = (link.ax + link.bx) / 2 - dy / len * bend;
      const cy = (link.ay + link.by) / 2 + dx / len * bend;
      const alpha = Math.min(0.62, alphaBase * (0.65 + Math.log1p(link.strength) * 0.42));
      ctx.strokeStyle = link.cross ? `rgba(210,224,255,${alpha})` : colorAlpha(link.color, alpha);
      ctx.lineWidth = Math.max(0.45 / scale, widthBase * (0.55 + Math.log1p(link.strength) * 0.34) / scale);
      ctx.beginPath();
      ctx.moveTo(link.ax, link.ay);
      ctx.quadraticCurveTo(cx, cy, link.bx, link.by);
      ctx.stroke();
    }
    ctx.restore();
  }
  function drawActiveEdges(act) {
    const n0 = NODES[act];
    const items = [...adjEdges[act] || []].sort((a, b) => b[3] - a[3] || b[2] - a[2]).slice(0, 180);
    for (let i = 0; i < items.length; i += 1) {
      const [a, b, w, cc] = items[i];
      const target = a === act ? b : a;
      const n1 = NODES[target];
      const dx = n1.x - n0.x;
      const dy = n1.y - n0.y;
      const len = Math.max(1, Math.hypot(dx, dy));
      const sign = (a * 31 + b * 17 + i) % 2 === 0 ? 1 : -1;
      const bend = Math.min(38, Math.max(8, len * 0.1)) * sign;
      const cx = (n0.x + n1.x) / 2 - dy / len * bend;
      const cy = (n0.y + n1.y) / 2 + dx / len * bend;
      const cross = n0.g !== n1.g;
      const alpha = Math.min(0.9, 0.26 + cc / 32 + w * 0.24);
      ctx.strokeStyle = cross ? `rgba(255,99,130,${alpha})` : `rgba(142,205,255,${alpha * 0.82})`;
      ctx.lineWidth = cross ? Math.max(1.3, 1.8 * scale) : Math.max(0.65, 0.95 * scale);
      ctx.beginPath();
      ctx.moveTo(X(n0.x), Y(n0.y));
      ctx.quadraticCurveTo(X(cx), Y(cy), X(n1.x), Y(n1.y));
      ctx.stroke();
    }
  }
  function shouldDrawNode(index, act, match) {
    if (match) return match.has(index) || scale >= 1.35;
    if (act >= 0) return index === act || (adj[act] || []).includes(index);
    if (scale < 0.9) return false;
    if (scale < 1.35) return nodeIsRepresentative[index] || (adj[index]?.length || 0) >= 40;
    return true;
  }
  function representativeForColor(color) {
    const comm = COMMUNITIES.find((item) => item.c === color);
    let best = -1;
    let bestScore = -Infinity;
    for (let i = 0; i < NODES.length; i += 1) {
      const n = NODES[i];
      if (n.c !== color) continue;
      const degree = adj[i]?.length || 0;
      if (degree <= 0) continue;
      const distScore = comm ? 1 - Math.min(1, Math.hypot(n.x - comm.x, n.y - comm.y) / Math.max(comm.r, 1)) : 0;
      const degreeScore = Math.min(degree, 24) / 24;
      const score = distScore * 2 + degreeScore + (nodeIsRepresentative[i] ? 1 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = i;
      }
    }
    return best;
  }
  function drawActiveNode(index) {
    const n = NODES[index];
    const r = n.r * Math.max(0.6, Math.sqrt(scale)) * 1.65;
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.shadowBlur = Math.min(64, Math.max(24, r * 3.1));
    ctx.shadowColor = "rgba(255,220,128,0.95)";
    ctx.fillStyle = "rgba(255,194,92,0.96)";
    ctx.beginPath();
    ctx.arc(X(n.x), Y(n.y), r, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = Math.min(26, Math.max(10, r * 1.3));
    ctx.shadowColor = "rgba(255,255,255,0.9)";
    ctx.lineWidth = Math.max(2.5, 1.4 * scale);
    ctx.strokeStyle = "rgba(255,255,255,0.96)";
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.lineWidth = Math.max(1.2, 0.8 * scale);
    ctx.strokeStyle = "rgba(255,126,80,0.95)";
    ctx.stroke();
    ctx.restore();
  }
  function drawBase() {
    ctx.clearRect(0, 0, W, H);
    const viewLeft = -tx / scale;
    const viewRight = (W - tx) / scale;
    const viewTop = -ty / scale;
    const viewBottom = (H - ty) / scale;
    function inView(x, y, r) {
      return x + r >= viewLeft && x - r <= viewRight && y + r >= viewTop && y - r <= viewBottom;
    }
    const act = activeId();
    const hl = /* @__PURE__ */ new Set();
    if (act >= 0) {
      hl.add(act);
      for (const n of adj[act] || []) hl.add(n);
    }
    const fil = filter.trim().toLowerCase();
    const match = fil ? new Set(NODES.map((n, i) => n.t.toLowerCase().includes(fil) ? i : -1).filter((i) => i >= 0)) : null;
    drawIslands(act);
    if (act < 0 && !match && scale <= globalEdgeScaleLimit) {
      drawGlobalEdges();
    } else if (act >= 0) {
      drawActiveEdges(act);
    }
    for (let i = 0; i < NODES.length; i += 1) {
      const n = NODES[i];
      let r = n.r * Math.max(0.6, Math.sqrt(scale));
      if (!shouldDrawNode(i, act, match)) continue;
      if (!inView(n.x, n.y, r * 1.5)) continue;
      if (act === i) continue;
      let alpha = 1;
      if ((adj[i]?.length || 0) === 0 && ccThreshold > 1 && !match) alpha = 0.08;
      if (act >= 0 && !hl.has(i)) alpha = 0.05;
      if (match && !match.has(i)) alpha = 0.06;
      const isActive = act === i;
      const isNeighbor = act >= 0 && hl.has(i) && !isActive;
      const isMatch = match && match.has(i);
      if (act < 0 && !match && scale < 1.35) {
        alpha *= 0.82;
        r *= 0.82;
      }
      if (isMatch) r *= 1.5;
      if (isNeighbor) r *= 1.1;
      ctx.globalAlpha = alpha;
      ctx.fillStyle = n.c;
      if (isMatch) {
        ctx.shadowBlur = Math.min(40, Math.max(12, r * 2.5));
        ctx.shadowColor = n.c;
      } else if (isNeighbor) {
        ctx.shadowBlur = Math.min(20, Math.max(4, r * 1));
        ctx.shadowColor = n.c;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.beginPath();
      ctx.arc(X(n.x), Y(n.y), r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      if (isMatch || isNeighbor) {
        ctx.globalAlpha = 1;
        if (isMatch) {
          ctx.lineWidth = 2;
          ctx.strokeStyle = "#fff";
        } else {
          ctx.lineWidth = 1;
          ctx.strokeStyle = NODES[i].g !== NODES[act].g ? "#ff5a78" : "rgba(255, 255, 255, 0.6)";
        }
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    if (act >= 0) {
      const n = NODES[act];
      drawActiveNode(act);
      ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--color-muted");
      ctx.font = "bold 14px sans-serif";
      ctx.shadowBlur = 4;
      ctx.shadowColor = "rgba(0,0,0,0.8)";
      const text = n.t.length > 25 ? `${n.t.slice(0, 25)}...` : n.t;
      ctx.fillText(text, X(n.x) + 12, Y(n.y) - 12);
      ctx.shadowBlur = 0;
    }
  }
  function draw() {
    if (hlColor) {
      let inView2 = function(x, y, r) {
        return x + r >= viewLeft && x - r <= viewRight && y + r >= viewTop && y - r <= viewBottom;
      };
      var inView = inView2;
      ctx.clearRect(0, 0, W, H);
      const viewLeft = -tx / scale;
      const viewRight = (W - tx) / scale;
      const viewTop = -ty / scale;
      const viewBottom = (H - ty) / scale;
      drawIslands(-1);
      for (let i = 0; i < NODES.length; i += 1) {
        const n = NODES[i];
        let r = n.r * Math.max(0.6, Math.sqrt(scale));
        const on = n.c === hlColor;
        if (!on && scale < 1.2) continue;
        if (on && scale < 1.05 && !nodeIsRepresentative[i] && (adj[i]?.length || 0) < 40) continue;
        if (on) r *= 1.3;
        if (!inView2(n.x, n.y, r * 1.5)) continue;
        ctx.globalAlpha = on ? 1 : (adj[i]?.length || 0) === 0 ? 0.03 : 0.05;
        ctx.fillStyle = n.c;
        if (on) {
          ctx.shadowBlur = Math.min(30, r * 2);
          ctx.shadowColor = n.c;
        } else {
          ctx.shadowBlur = 0;
        }
        ctx.beginPath();
        ctx.arc(X(n.x), Y(n.y), r, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
      ctx.globalAlpha = 1;
      return;
    }
    drawBase();
  }
  function badgeHTML(t) {
    const simClass = t.sim > 0.65 ? "ag-badge-success" : t.sim > 0.45 ? "ag-badge-warning" : "ag-badge-danger";
    const simText = t.sim > 0.65 ? "\u540C\u4E49" : t.sim > 0.45 ? "\u76F8\u5173" : "\u6F5C\u610F\u8BC6\u8DF3\u8DC3";
    const simPct = `${(t.sim * 100).toFixed(0)}%`;
    return `<div style="display:flex;flex-wrap:wrap;margin-top:2px;">
      <span class="ag-badge ag-badge-outline">\u540C\u6846:${t.cc}\u6B21</span>
      <span class="ag-badge ag-badge-outline">\u5F15\u529B:${t.w.toFixed(2)}</span>
      <span class="ag-badge ${simClass}">\u8BED\u4E49:${simPct} (${simText})</span>
    </div>`;
  }
  function updateDetailPanel() {
    if (pinned < 0) {
      detailPanel.style.display = "none";
      return;
    }
    const n = NODES[pinned];
    const neighbors = [];
    for (const [a, b, w, cc, sim] of EDGES) {
      if (cc < ccThreshold) continue;
      if (a === pinned) neighbors.push({ id: b, w, cc, sim });
      if (b === pinned) neighbors.push({ id: a, w, cc, sim });
    }
    neighbors.sort((x, y) => y.w - x.w);
    const internal = [];
    const external = [];
    for (const nb of neighbors) {
      const target = { ...NODES[nb.id], nodeIndex: nb.id, w: nb.w, cc: nb.cc, sim: nb.sim };
      if (target.g === n.g) internal.push(target);
      else external.push(target);
    }
    let html = '<div style="font-size:13px;color:#8b9eb5;margin-bottom:6px;">\u9009\u4E2D\u8BB0\u5FC6\u5207\u7247</div>';
    html += `<div style="font-size:14px;padding:12px;background:linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%); border: 1px solid rgba(255,255,255,0.05); border-radius:8px; margin-bottom:16px;">${ghEscape(n.t)}</div>`;
    if (external.length > 0) {
      html += `<div style="color:#ff5a78;font-weight:bold;margin-bottom:4px;border-bottom:1px solid rgba(255,90,120,0.3);padding-bottom:6px;">\u601D\u60F3\u8DF3\u8DC3 / \u8DE8\u754C\u8D70\u795E (${external.length})</div>`;
      html += '<div style="font-size:11px;color:#737a88;margin-bottom:12px;line-height:1.4;">\u6EAF\u6E90\uFF1A\u5206\u5C5E\u4E0D\u540C\u7684\u8BDD\u9898\u5C9B\u5C7F\uFF0C\u4F46\u5728\u7279\u5B9A\u65F6\u95F4\u70B9\u88AB\u4F60\u8DE8\u754C\u5173\u8054\u3002</div>';
      for (const t of external) {
        html += `<div class="detail-item" data-node="${t.nodeIndex}" title="\u9501\u5B9A\u8FD9\u4E2A\u8BB0\u5FC6\u5207\u7247" style="display:flex;gap:8px;align-items:flex-start;background:linear-gradient(90deg, rgba(255,255,255,0.05) 0%, transparent 100%); border-left: 2px solid ${t.c}; padding: 8px; margin-bottom: 8px; cursor:pointer;">
          <div style="display:flex;flex-direction:column;flex:1;"><span style="opacity:0.95">${ghEscape(t.t)}</span>${badgeHTML(t)}</div>
        </div>`;
      }
    }
    if (internal.length > 0) {
      html += `<div style="color:#96c8ff;font-weight:bold;margin-bottom:4px;margin-top:20px;border-bottom:1px solid rgba(150,200,255,0.3);padding-bottom:6px;">\u6838\u5FC3\u5708\u5C42 (${internal.length})</div>`;
      html += '<div style="font-size:11px;color:#737a88;margin-bottom:12px;line-height:1.4;">\u6EAF\u6E90\uFF1A\u57FA\u4E8E\u6A21\u5757\u5EA6\u7B97\u6CD5\uFF0C\u8FD9\u4E9B\u8BDD\u9898\u5F62\u6210\u4E86\u9AD8\u9891\u540C\u6846\u7684\u5185\u805A\u5B64\u5C9B\u3002</div>';
      for (const t of internal) {
        html += `<div class="detail-item" data-node="${t.nodeIndex}" title="\u9501\u5B9A\u8FD9\u4E2A\u8BB0\u5FC6\u5207\u7247" style="display:flex;gap:8px;align-items:flex-start;background:linear-gradient(90deg, rgba(255,255,255,0.05) 0%, transparent 100%); border-left: 2px solid ${t.c}; padding: 8px; margin-bottom: 8px; cursor:pointer;">
          <div style="display:flex;flex-direction:column;flex:1;"><span>${ghEscape(t.t)}</span>${badgeHTML(t)}</div>
        </div>`;
      }
    }
    detailPanel.innerHTML = html;
    detailPanel.style.display = "block";
  }
  function pick(px, py) {
    let best = -1;
    let bd = Number.POSITIVE_INFINITY;
    const match = filter ? new Set(NODES.map((n, i) => n.t.toLowerCase().includes(filter) ? i : -1).filter((i) => i >= 0)) : null;
    for (let i = 0; i < NODES.length; i += 1) {
      if ((adj[i]?.length || 0) === 0 && !filter) continue;
      if (!shouldDrawNode(i, pinned, match)) continue;
      const dx = X(NODES[i].x) - px;
      const dy = Y(NODES[i].y) - py;
      const d = dx * dx + dy * dy;
      const rr = Math.max(6, NODES[i].r * Math.sqrt(scale) + 4);
      if (d < rr * rr && d < bd) {
        bd = d;
        best = i;
      }
    }
    return best;
  }
  function onMouseUp() {
    drag = false;
    cv.classList.remove("drag");
  }
  function onDocumentClick(event) {
    const target = event.target;
    if (!searchEl.contains(target) && !resEl.contains(target)) {
      resEl.style.display = "none";
    }
  }
  detailPanel.addEventListener("click", (event) => {
    const target = event.target.closest(".detail-item[data-node]");
    if (!target) return;
    event.stopPropagation();
    const next = Number(target.dataset.node);
    if (Number.isInteger(next) && next >= 0 && next < NODES.length) selectNode(next);
  });
  cv.addEventListener("mousedown", (event) => {
    if (tweenFrame) cancelAnimationFrame(tweenFrame);
    drag = true;
    moved = false;
    hover = -1;
    lx = event.clientX;
    ly = event.clientY;
    cv.classList.add("drag");
  });
  window.addEventListener("mouseup", onMouseUp);
  cv.addEventListener("mousemove", (event) => {
    const rect = cv.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const my = event.clientY - rect.top;
    if (drag) {
      tx += event.clientX - lx;
      ty += event.clientY - ly;
      lx = event.clientX;
      ly = event.clientY;
      moved = true;
      draw();
      tip.style.display = "none";
      return;
    }
    const h = pick(mx, my);
    if (h !== hover) {
      hover = h;
    }
    if (h >= 0) {
      tip.style.display = "block";
      tip.style.left = `${mx + 14}px`;
      tip.style.top = `${my + 14}px`;
      tip.textContent = NODES[h].t.length > 40 ? `${NODES[h].t.slice(0, 40)}...` : NODES[h].t;
    } else {
      tip.style.display = "none";
    }
  });
  cv.addEventListener("click", (event) => {
    if (moved) return;
    if (lockedColor) {
      lockedColor = null;
      hlColor = null;
      updateHlPaths();
      legEl.querySelectorAll(".row").forEach((r) => r.classList.remove("selected"));
    }
    const rect = cv.getBoundingClientRect();
    const h = pick(event.clientX - rect.left, event.clientY - rect.top);
    pinned = h === pinned ? -1 : h;
    if (pinned >= 0) {
      const n = NODES[pinned];
      const targetScale = Math.max(scale, 1.2);
      const targetTx = W / 2 - n.x * targetScale;
      const targetTy = H / 2 - n.y * targetScale;
      flyTo(targetScale, targetTx, targetTy);
    } else {
      draw();
    }
    updateDetailPanel();
  });
  cv.addEventListener("wheel", (event) => {
    if (tweenFrame) cancelAnimationFrame(tweenFrame);
    event.preventDefault();
    const rect = cv.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const my = event.clientY - rect.top;
    const f = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    const wx = invX(mx);
    const wy = invY(my);
    scale *= f;
    tx = mx - wx * scale;
    ty = my - wy * scale;
    draw();
  }, { passive: false });
  slider.addEventListener("input", () => {
    ccThreshold = Number(slider.value);
    ccVal.textContent = String(ccThreshold);
    recomputeAdj();
    updateHlPaths();
    draw();
    updateDetailPanel();
  });
  searchEl.addEventListener("input", () => {
    filter = searchEl.value.trim().toLowerCase();
    if (!filter) {
      resEl.style.display = "none";
      draw();
      return;
    }
    const matches = [];
    for (let i = 0; i < NODES.length; i += 1) {
      if (NODES[i].t.toLowerCase().includes(filter)) matches.push(i);
    }
    if (matches.length > 0) {
      resEl.innerHTML = matches.slice(0, 30).map((i) => {
        const txt = NODES[i].t.length > 30 ? `${NODES[i].t.slice(0, 30)}...` : NODES[i].t;
        return `<div class="res-item" data-node="${i}">${ghEscape(txt)}</div>`;
      }).join("");
      resEl.querySelectorAll(".res-item").forEach((item) => {
        item.onclick = () => selectNode(Number(item.dataset.node));
      });
      resEl.style.display = "block";
    } else {
      resEl.innerHTML = '<div style="padding:8px 10px;color:#737a88;">\u65E0\u5339\u914D\u9879</div>';
      resEl.style.display = "block";
    }
    draw();
  });
  document.addEventListener("click", onDocumentClick);
  function selectNode(i) {
    if (lockedColor) {
      lockedColor = null;
      hlColor = null;
      updateHlPaths();
      legEl.querySelectorAll(".row").forEach((r) => r.classList.remove("selected"));
    }
    pinned = i;
    hover = -1;
    const n = NODES[i];
    const targetScale = Math.max(scale, 1.2);
    const targetTx = W / 2 - n.x * targetScale;
    const targetTy = H / 2 - n.y * targetScale;
    flyTo(targetScale, targetTx, targetTy);
    searchEl.value = "";
    filter = "";
    resEl.style.display = "none";
    updateDetailPanel();
  }
  function renderLegend() {
    legEl.innerHTML = '<div class="grab">\u5C9B\u5C7F</div><div class="content" style="padding-top:4px;"><div style="margin-bottom:12px;"><b style="color:#fff;font-size:13px;">\u8BB0\u5FC6\u5C9B\u5C7F</b> <span style="color:#737a88;">(\u60AC\u505C\u9884\u89C8 \xB7 \u70B9\u51FB\u9009\u4EE3\u8868\u8BB0\u5FC6)</span></div>' + LEG.map((l) => `<div class="row" data-c="${ghEscape(l.c)}"><span class="dot" style="background:${ghEscape(l.c)}"></span><span><span style="color:#9aa3b5">[${l.size}]</span> ${ghEscape(l.label)}</span></div>`).join("") + "</div>";
    legEl.querySelectorAll(".row").forEach((row) => {
      row.addEventListener("mouseenter", () => {
        if (!lockedColor) {
          filter = "";
          hlColor = row.dataset.c || null;
          updateHlPaths();
          draw();
        }
      });
      row.addEventListener("mouseleave", () => {
        if (!lockedColor) {
          hlColor = null;
          updateHlPaths();
          draw();
        }
      });
      row.addEventListener("click", () => {
        const c = row.dataset.c || null;
        if (!c) return;
        lockedColor = null;
        hlColor = null;
        filter = "";
        searchEl.value = "";
        resEl.style.display = "none";
        updateHlPaths();
        const target = representativeForColor(c);
        if (target >= 0) {
          selectNode(target);
        } else {
          pinned = -1;
          updateDetailPanel();
          flyToCommunity(c);
        }
        legEl.querySelectorAll(".row").forEach((r) => r.classList.remove("selected"));
        row.classList.add("selected");
        draw();
      });
    });
  }
  function setLoadingCard(visible, payload) {
    loadingCard.classList.toggle("visible", visible);
    if (!visible) return;
    loadingTick += 1;
    const elapsed = Math.max(0, Math.round((Date.now() - loadingStartedAt) / 1e3));
    const progress = Math.min(92, 18 + loadingTick * 7 + elapsed * 2);
    loadingBar.style.width = `${progress}%`;
    const state = payload?.meta?.rebuilding ? "\u540E\u53F0\u5E03\u5C40\u8BA1\u7B97\u4E2D" : "\u7B49\u5F85\u5E03\u5C40\u4EFB\u52A1\u542F\u52A8";
    loadingNote.textContent = `${state} \xB7 ${elapsed}s`;
  }
  function applyPayload(payload, refit) {
    if (payload.meta?.missing) {
      stat.textContent = payload.meta.rebuilding ? "\u5FEB\u7167\u540E\u53F0\u751F\u6210\u4E2D..." : "\u7B49\u5F85\u5FEB\u7167\u751F\u6210...";
      setLoadingCard(NODES.length === 0, payload);
      return;
    }
    const nextVersion = payload.meta?.version || "";
    if (!refit && nextVersion && nextVersion === currentVersion) {
      stat.textContent = `${NODES.length} \u8282\u70B9 \xB7 \u5171 ${EDGES.length} \u5019\u9009\u8FB9${payload.meta?.stale ? " \xB7 \u540E\u53F0\u5237\u65B0\u4E2D" : ""}`;
      return;
    }
    currentVersion = nextVersion;
    NODES = payload.nodes || [];
    EDGES = ghEdges(payload.edges || []);
    LEG = payload.legend || [];
    setLoadingCard(false);
    rebalanceFractalSpacing();
    recomputeCommunities();
    ccThreshold = 2;
    slider.value = "2";
    ccVal.textContent = "2";
    recomputeAdj();
    renderLegend();
    stat.textContent = `${NODES.length} \u8282\u70B9 \xB7 \u5171 ${EDGES.length} \u5019\u9009\u8FB9${payload.meta?.stale ? " \xB7 \u540E\u53F0\u5237\u65B0\u4E2D" : ""}`;
    if (refit) fit();
    resize();
  }
  async function load(refit) {
    if (refit) {
      stat.textContent = "\u52A0\u8F7D\u5168\u666F\u5FEB\u7167...";
      setLoadingCard(NODES.length === 0);
    }
    const payload = await api("/api/dashboard/akasha-graph/global");
    if (disposed) return;
    applyPayload(payload, refit);
  }
  window.addEventListener("resize", resize);
  resize();
  void load(true).catch((error) => {
    stat.textContent = error instanceof Error ? error.message : String(error);
  });
  pollTimer = window.setInterval(() => {
    void load(false).catch(() => void 0);
  }, 5e3);
}
window.AkashicDashboard.registerPlugin({
  id: "akasha_graph",
  label: "Akasha Graph",
  viewLabel: "akasha graph",
  layout: "workbench",
  pageSize: 1,
  rowKey: "id",
  columns: [{ key: "id", label: "Graph", flex: true }],
  async getCount() {
    try {
      const data = await api("/api/dashboard/akasha-graph/global");
      return data.nodes.length;
    } catch {
      return null;
    }
  },
  async fetchPage() {
    return { items: [], total: 0 };
  },
  renderMain(container) {
    renderAkashaGraph(container);
  }
});
