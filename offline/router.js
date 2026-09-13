'use strict';
/*
 * Roterador offline sobre paragominas.graph (CSR binario).
 *
 * Node:  node offline/router.js
 * Browser: a parte de parse + Dijkstra e' pura (DataView/TextDecoder nativos);
 *          troque o fs.readFileSync por fetch(...).arrayBuffer().
 *
 * Custo de roteamento = weight * tier_multipliers[tier] (mesmo criterio do
 * desafio3_grafo_base.py). A distancia reportada e' a soma dos pesos reais
 * (metros), e a composicao por tier e' por distancia, nao por contagem.
 */

const fs = require('fs');
const path = require('path');

const GRAPH_PATH = path.join(__dirname, '..', 'paragominas.graph');

// ---------------------------------------------------------------------------
// Parse do binario (formato em desafio3_grafo_schema.md)
// ---------------------------------------------------------------------------
function loadGraph(filePath) {
  const ab = fs.readFileSync(filePath);
  const b = new Uint8Array(ab.buffer, ab.byteOffset, ab.byteLength);
  const view = new DataView(ab.buffer, ab.byteOffset, ab.byteLength);

  const magic = String.fromCharCode(b[0], b[1], b[2], b[3]);
  if (magic !== 'AHG3') throw new Error('magic invalido: ' + magic);

  const version = view.getUint32(4, true);
  const N = view.getUint32(8, true);   // num_nodes
  const M = view.getUint32(12, true);  // num_edges (dirigido)
  const metaLen = view.getUint32(16, true);

  const meta = JSON.parse(new TextDecoder().decode(b.subarray(20, 20 + metaLen)));

  let p = 20 + metaLen;
  const lon = new Float64Array(N);
  const lat = new Float64Array(N);
  for (let i = 0; i < N; i++) { lon[i] = view.getFloat64(p, true); p += 8; }
  for (let i = 0; i < N; i++) { lat[i] = view.getFloat64(p, true); p += 8; }

  const offset = new Uint32Array(N + 1);
  for (let i = 0; i <= N; i++) { offset[i] = view.getUint32(p, true); p += 4; }

  const neighbor = new Uint32Array(M);
  for (let i = 0; i < M; i++) { neighbor[i] = view.getUint32(p, true); p += 4; }

  const weight = new Float32Array(M);
  for (let i = 0; i < M; i++) { weight[i] = view.getFloat32(p, true); p += 4; }

  const tier = new Uint8Array(M);
  for (let i = 0; i < M; i++) { tier[i] = b[p++]; }

  // multiplicador por codigo numerico de tier
  const multByCode = new Float64Array(5);
  const nameByCode = new Array(5);
  for (const [name, code] of Object.entries(meta.tier_codes)) {
    multByCode[code] = meta.tier_multipliers[name];
    nameByCode[code] = name;
  }

  return { version, N, M, meta, lon, lat, offset, neighbor, weight, tier, multByCode, nameByCode };
}

// ---------------------------------------------------------------------------
// Geo (projecao UTM 22S, WGS84 — mesma do desafio3_grafo_base.py, EPSG:32722,
// para que o snap e as distancias batam exatamente com o Python)
// ---------------------------------------------------------------------------
const rad = (d) => (d * Math.PI) / 180;

function toUTM(lonDeg, latDeg) {
  const a = 6378137.0;
  const e2 = 0.00669437999014;
  const ep2 = e2 / (1 - e2);
  const k0 = 0.9996;
  const lon0 = -51; // zona 22 (Paragominas)
  const phi = rad(latDeg);
  const lam = rad(lonDeg - lon0);
  const N = a / Math.sqrt(1 - e2 * Math.sin(phi) * Math.sin(phi));
  const T = Math.tan(phi) * Math.tan(phi);
  const C = ep2 * Math.cos(phi) * Math.cos(phi);
  const A = lam * Math.cos(phi);
  const e4 = e2 * e2, e6 = e4 * e2;
  const M = a * (
    (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
    - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
    + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi)
    - (35 * e6 / 3072) * Math.sin(6 * phi)
  );
  const easting = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000;
  const northing = k0 * (M + N * Math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24 + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720)) + (latDeg < 0 ? 10000000 : 0);
  return [easting, northing];
}

function buildSpatialIndex(g) {
  const east = new Float64Array(g.N);
  const north = new Float64Array(g.N);
  for (let i = 0; i < g.N; i++) {
    const [e, n] = toUTM(g.lon[i], g.lat[i]);
    east[i] = e;
    north[i] = n;
  }
  return { east, north };
}

// No mais proximo por busca linear no plano UTM (764k nos -> ~ms). Para uso
// interativo no browser, troque por um grid/k-d tree; o resultado e' o mesmo.
function nearestNode(idx, lon, lat) {
  const [e, n] = toUTM(lon, lat);
  let best = -1;
  let bestD2 = Infinity;
  for (let i = 0; i < idx.east.length; i++) {
    const de = idx.east[i] - e;
    const dn = idx.north[i] - n;
    const d2 = de * de + dn * dn;
    if (d2 < bestD2) { bestD2 = d2; best = i; }
  }
  return { node: best, distM: Math.sqrt(bestD2) };
}

// ---------------------------------------------------------------------------
// Dijkstra com heap binario
// ---------------------------------------------------------------------------
function route(g, src, dst) {
  const { offset, neighbor, weight, tier, multByCode } = g;
  const dist = new Float64Array(g.N).fill(Infinity);
  const prev = new Int32Array(g.N).fill(-1);
  dist[src] = 0;

  // heap de [custo, no]
  const heap = [[0, src]];
  const push = (c, n) => {
    heap.push([c, n]);
    let i = heap.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (heap[p][0] <= heap[i][0]) break;
      [heap[p], heap[i]] = [heap[i], heap[p]];
      i = p;
    }
  };
  const pop = () => {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length > 0) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
        if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
        if (m === i) break;
        [heap[m], heap[i]] = [heap[i], heap[m]];
        i = m;
      }
    }
    return top;
  };

  let settled = 0;
  while (heap.length > 0) {
    const [c, u] = pop();
    if (c > dist[u]) continue;          // entrada obsoleta
    settled++;
    if (u === dst) break;               // chegou no destino
    for (let k = offset[u]; k < offset[u + 1]; k++) {
      const v = neighbor[k];
      const nd = c + weight[k] * multByCode[tier[k]];
      if (nd < dist[v]) {
        dist[v] = nd;
        prev[v] = u;
        push(nd, v);
      }
    }
  }

  if (dist[dst] === Infinity) return null;

  // reconstroi caminho (apenas ids de no)
  const path = [];
  for (let u = dst; u !== -1; u = prev[u]) path.push(u);
  path.reverse();

  // distancia real (metros) e composicao por tier (por distancia)
  let distM = 0;
  const tierM = {};
  for (let i = 0; i + 1 < path.length; i++) {
    const u = path[i], v = path[i + 1];
    // acha a aresta u->v no CSR
    for (let k = offset[u]; k < offset[u + 1]; k++) {
      if (neighbor[k] === v) {
        const w = weight[k];
        distM += w;
        const name = g.nameByCode[tier[k]];
        tierM[name] = (tierM[name] || 0) + w;
        break;
      }
    }
  }
  return { distM, tierM, path };
}

// ---------------------------------------------------------------------------
// Uso como CLI (Node):  node offline/router.js offline/test-pairs.json
//   test-pairs.json = [["id", olon, olat, dlon, dlat], ...]
// As coordenadas dos alvos nao sao publicadas: o arquivo de pares e' local
// (gitignored). A biblioteca (loadGraph/route/...) nao carrega nenhuma
// coordenada e pode ser usada no browser.
// ---------------------------------------------------------------------------
function main(pairsPath) {
  const pairs = JSON.parse(fs.readFileSync(pairsPath, 'utf-8'));
  const t0 = Date.now();
  const g = loadGraph(GRAPH_PATH);
  console.log(
    `grafo carregado: ${g.N} nos, ${g.M} arestas (dirigido) em ${Date.now() - t0} ms`
  );
  const idx = buildSpatialIndex(g);
  console.log(`indice espacial (UTM) construido em ${Date.now() - t0} ms\n`);

  let reachable = 0;
  for (const [id, olon, olat, dlon, dlat] of pairs) {
    const o = nearestNode(idx, olon, olat);
    const d = nearestNode(idx, dlon, dlat);
    const res = route(g, o.node, d.node);
    if (!res) {
      console.log(`${id}: sem rota (componentes diferentes)`);
      continue;
    }
    reachable++;
    const pct = {};
    for (const [name, m] of Object.entries(res.tierM)) {
      pct[name] = ((100 * m) / res.distM).toFixed(1);
    }
    console.log(
      `${id}: ${(res.distM / 1000).toFixed(1)} km | ` +
      `origem ${o.distM.toFixed(0)} m | destino ${d.distM.toFixed(0)} m | ` +
      `% por tier ${JSON.stringify(pct)}`
    );
  }
  console.log(`\n${reachable}/${pairs.length} pares roteados`);
}

if (require.main === module) {
  if (!process.argv[2]) {
    console.error('uso: node offline/router.js <pairs.json>');
    process.exit(1);
  }
  main(process.argv[2]);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { loadGraph, buildSpatialIndex, nearestNode, route, toUTM };
}
