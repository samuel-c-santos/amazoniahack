"""
AmazoniaHack 4.0 - Desafio 3
Passo 1: unir roads-osm-paragominas.geojson + roads-previsia-2025-paragominas.geojson
num grafo unico, medir conectividade e checar quantos dos 16 pares de teste
ficam alcancaveis - reproduzindo a metrica que o proprio README do desafio usa
(9/16 com snap de 150m e' o teto que eles relatam).

Requisitos: networkx, scipy, pyproj, shapely, geopandas
(pip install networkx scipy pyproj shapely geopandas)
"""
import json
import csv
import math
import struct
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from pyproj import Transformer
import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.ops import transform
from shapely.strtree import STRtree

DATA_DIR = Path("participant-package/participant-package/challenge-3")
OSM_PATH = DATA_DIR / "roads-osm-paragominas.geojson"
PREVISIA_PATH = DATA_DIR / "roads-previsia-2025-paragominas.geojson"
PAIRS_PATH = DATA_DIR / "test-pairs.csv"
CAR_INFRA_PATH = Path("vw_area_infraestrutura_publica_cp/vw_area_infraestrutura_publica_cpPolygon.shp")
IBGE_RODOVIAS_PATH = Path("vw_sicar_rodovias/vw_sicar_rodoviasLine.shp")
DRENAGEM_PATH = Path("vw_trecho_drenagem/vw_trecho_drenagem.shp")
BRIDGES_PATH = Path("osm_bridges_paragominas.json")  # pontes conhecidas continuam vindo do OSM
GRAPH_OUT_PATH = Path("paragominas.graph")  # grafo serializado (CSR binario) p/ uso offline

# NAO usamos mais isto como corte de pass/fail: o README e' explicito que a
# perna final a pe' nao e' erro, e' informacao que a rota precisa declarar.
# "Alcancavel" aqui significa apenas "origem e destino caem no mesmo
# componente do grafo" - a distancia da ultima perna e' sempre reportada,
# nunca usada pra reprovar silenciosamente um par.

# Raio em que um snap (ponte entre duas pontas soltas) e' considerado
# "confirmado" por ter uma area de infraestrutura do CAR por perto.
CAR_CONFIRM_BUFFER_M = 60

# UTM 22S cobre Paragominas/PA - projecao metrica para medir distancias/tolerancias em metros
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32722", always_xy=True)


def node_key(lon, lat, precision=6):
    """Chave de no por arredondamento de coordenada (mesmo truque usado para
    validar os 1874 componentes do README: linhas que se cruzam na tela nao
    necessariamente compartilham vertice exato)."""
    return (round(lon, precision), round(lat, precision))


def load_lines(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lines = []
    for feat in data["features"]:
        geom = feat["geometry"]
        if geom["type"] == "LineString":
            lines.append(geom["coordinates"])
        elif geom["type"] == "MultiLineString":
            lines.extend(geom["coordinates"])
    return lines


def build_raw_graph(lines, source):
    G = nx.Graph()
    for coords in lines:
        for a, b in zip(coords, coords[1:]):
            ka, kb = node_key(*a), node_key(*b)
            dist_m = utm_dist(a, b)
            G.add_edge(ka, kb, weight=dist_m, source=source)
    return G


def utm_dist(a, b):
    ax, ay = to_utm.transform(a[0], a[1])
    bx, by = to_utm.transform(b[0], b[1])
    return math.hypot(ax - bx, ay - by)


def load_lines_from_shp(path):
    """Le linhas de um shapefile (usado para a malha IBGE/SICAR), devolvendo
    no mesmo formato [[ (lon,lat), ... ], ...] que load_lines usa pros
    GeoJSON do desafio."""
    gdf = gpd.read_file(path)
    lines = []
    for geom in gdf.geometry:
        if geom is None:
            continue
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        for g in parts:
            lines.append(list(g.coords))
    return lines


def load_car_infra_union(path, buffer_m):
    """Carrega os poligonos de infraestrutura publica do CAR e devolve uma
    unica geometria (em UTM) com um buffer, pronta pra teste de intersecao
    rapido contra os segmentos de snap."""
    infra = gpd.read_file(path).to_crs(32722)
    return infra.geometry.buffer(buffer_m).union_all()


def load_hydrography_union(drenagem_path, bridges_path, bridge_clear_m=40):
    """Carrega a drenagem oficial (SIGERH-PA, via CAR) e devolve:
    - uma STRtree das linhas de rio/corrego, em UTM (57 mil trechos - um
      unico union_all() nisso e' caro demais; STRtree faz a consulta pontual
      rapido sem precisar unir tudo numa geometria so')
    - a uniao de um buffer em torno de pontes JA mapeadas no OSM (poucas
      centenas de linhas, unir e' barato)

    Uma ponte candidata (snap) que cruza a hidrografia LONGE de qualquer
    ponte OSM conhecida e' o cenario que o enunciado chama de "erro mais caro
    possivel": rota que atravessa rio sem passagem."""
    gdf = gpd.read_file(drenagem_path).to_crs(32722)
    water_lines = [g for g in gdf.geometry if g is not None]
    water_tree = STRtree(water_lines) if water_lines else None

    def bridges_from_overpass(path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        lines = []
        for el in data["elements"]:
            if el.get("type") == "way" and "geometry" in el:
                coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
                if len(coords) >= 2:
                    lines.append(transform(to_utm.transform, LineString(coords)))
        return lines

    bridge_lines = bridges_from_overpass(bridges_path)
    bridge_buffer = (
        gpd.GeoSeries(bridge_lines, crs=32722).buffer(bridge_clear_m).union_all()
        if bridge_lines
        else None
    )
    print(f"  hidrografia (SIGERH/CAR): {len(water_lines)} trechos | pontes OSM conhecidas: {len(bridge_lines)}")
    return water_tree, water_lines, bridge_buffer


def crosses_unbridged_water(seg, water_tree, water_lines, bridge_buffer):
    """True se o segmento cruza um curso d'agua e esse ponto de cruzamento
    NAO esta perto de uma ponte ja conhecida no OSM. Usa a STRtree pra achar
    so' os trechos de drenagem proximos, em vez de testar contra os 57 mil
    de uma vez."""
    if water_tree is None:
        return False
    idxs = water_tree.query(seg)
    for idx in idxs:
        candidate = water_lines[idx]
        if seg.intersects(candidate):
            crossing = seg.intersection(candidate)
            if bridge_buffer is not None and crossing.within(bridge_buffer):
                continue
            return True
    return False


def snap_components(G, tolerance_m, car_infra_buffer=None, hydro=None):
    """Conecta APENAS extremidades soltas (grau 1 = fim de linha, nao vertice
    interno) que estao a menos de `tolerance_m` metros uma da outra.

    A primeira versao deste script snapava QUALQUER no dentro da tolerancia,
    incluindo vertices internos de linhas quase paralelas - isso "colou"
    milhoes de arestas espurias, estourou memoria e teria inflado a
    conectividade de forma irreal (o proprio README chama esse efeito de
    "inventar pontes que nao existem"). Restringir a candidatos de grau 1 e'
    o que corresponde de fato a "unir a ponta de uma via com a ponta de
    outra".

    car_infra_buffer: cada ponte criada e' marcada como car_confirmed=True
    quando o segmento passa perto de uma area de infraestrutura do CAR.

    hydro: tupla (water_tree, water_lines, bridge_buffer) do load_hydrography_union.
    Cada ponte que cruza um curso d'agua longe de qualquer ponte OSM
    conhecida vira crosses_unbridged_water=True - o erro mais caro possivel
    segundo o proprio enunciado."""
    dangling = [n for n, deg in G.degree() if deg == 1]
    dangling_source = {n: next(iter(G[n].values()))["source"] for n in dangling}
    utm_coords = [to_utm.transform(lon, lat) for lon, lat in dangling]
    tree = cKDTree(utm_coords)
    pairs = tree.query_pairs(r=tolerance_m)
    added = 0
    confirmed = 0
    risky = 0
    ibge_rejected = 0
    water_tree, water_lines, bridge_buffer = hydro if hydro else (None, None, None)
    for i, j in pairs:
        u, v = dangling[i], dangling[j]
        if u == v or G.has_edge(u, v):
            continue
        seg = LineString([utm_coords[i], utm_coords[j]])
        # tolerancia efetiva menor se alguma das pontas vem do IBGE (precisao
        # posicional pior - ver TIER_MULTIPLIER)
        if dangling_source[u] == "ibge" or dangling_source[v] == "ibge":
            if seg.length > IBGE_SNAP_TOLERANCE_M:
                ibge_rejected += 1
                continue
        is_confirmed = False
        if car_infra_buffer is not None:
            is_confirmed = seg.intersects(car_infra_buffer)
            confirmed += is_confirmed
        crosses_water = crosses_unbridged_water(seg, water_tree, water_lines, bridge_buffer)
        risky += crosses_water
        G.add_edge(
            u, v,
            weight=seg.length,
            source="snap",
            snapped=True,
            car_confirmed=is_confirmed,
            crosses_unbridged_water=crosses_water,
        )
        added += 1
    if car_infra_buffer is not None:
        print(f"  pontes confirmadas por infraestrutura do CAR: {confirmed}/{added}")
    if water_tree is not None:
        print(f"  pontes que cruzam rio sem ponte conhecida: {risky}/{added}")
    print(f"  pontes rejeitadas por precisao do IBGE (>{IBGE_SNAP_TOLERANCE_M}m): {ibge_rejected}")
    return added


TIER_MULTIPLIER = {
    "osm": 1.0,               # via oficial conhecida (OpenStreetMap)
    "ibge": 1.2,              # via oficial (IBGE/SICAR), mas com precisao
                              # posicional pior: medimos deslocamento mediano
                              # de 34m contra o OSM nas vias principais, e uma
                              # cauda real onde passa de 300m-2km em ~5-10%
                              # dos pontos - tratado como PrevisIA, nao como OSM
    "previsia": 1.2,          # traco detectado, sem data conhecida
    "confirmed_bridge": 1.5,  # ponte (snap) confirmada por infraestrutura do CAR
    "unconfirmed_bridge": 4.0,  # ponte por proximidade geometrica, sem 2a fonte
    "risky_bridge": 20.0,     # ponte que cruza rio sem passagem conhecida - evitar
}

# Codigos numericos dos tiers no binario serializado (risky_bridge nao aparece:
# essas arestas sao removidas antes da serializacao).
TIER_CODES = {
    "osm": 0,
    "ibge": 1,
    "previsia": 2,
    "confirmed_bridge": 3,
    "unconfirmed_bridge": 4,
}

# Tolerancia de snap reduzida quando uma das pontas vem do IBGE - a camada
# tem precisao posicional pior que OSM/PrevisIA (cauda de erro > 300m em
# ~5-10% dos pontos, medido contra vias principais do OSM), entao usar a
# mesma tolerancia geral inflaria conexoes por coincidencia de erro, nao por
# proximidade real.
IBGE_SNAP_TOLERANCE_M = 100


def edge_tier(data):
    if not data.get("snapped"):
        return data.get("source", "osm")
    if data.get("crosses_unbridged_water"):
        return "risky_bridge"
    if data.get("car_confirmed"):
        return "confirmed_bridge"
    return "unconfirmed_bridge"


def assign_costs(G):
    """Custo de roteamento = distancia real * multiplicador de confianca.
    O Dijkstra vai preferir vias conhecidas e so' usar uma ponte fraca quando
    for a unica forma de fechar a rota - mas nao proibe, porque o enunciado
    pede honestidade sobre o que foi usado, nao esconder a rota atras de uma
    regra rigida demais."""
    for u, v, d in G.edges(data=True):
        tier = edge_tier(d)
        d["tier"] = tier
        d["cost"] = d["weight"] * TIER_MULTIPLIER[tier]


def strip_risky_bridges(G):
    """Remove do grafo as pontes que cruzam rio sem passagem conhecida antes
    de rotear. Um multiplicador de custo alto (20x) desestimula mas nao
    proibe esse tipo de aresta - e' pouco quando ela representa so' uma
    fatia minuscula da distancia total, o Dijkstra pode preferi-la mesmo
    existindo caminho seguro. Isso e' exatamente o erro mais caro que o
    enunciado pede pra evitar, entao aqui a exclusao e' categorica, nao por
    peso."""
    G = G.copy()
    risky_edges = [
        (u, v) for u, v, d in G.edges(data=True)
        if d.get("snapped") and d.get("crosses_unbridged_water")
    ]
    G.remove_edges_from(risky_edges)
    return G


def serialize_graph(G, out_path):
    """Serializa o grafo roteavel (ja' sem pontes de risco e com tier/custo
    atribuidos) num binario compacto em CSR, para roteamento offline no
    aparelho. Formato (tudo little-endian):

        magic      4b   "AHG3"
        version    u32  = 1
        num_nodes  u32
        num_edges  u32  (dirigido = 2 * arestas nao-dirigidas)
        meta_len   u32
        meta       meta_len bytes (JSON UTF-8: tiers, multiplicadores, datas)
        lon        f64 * num_nodes
        lat        f64 * num_nodes
        offset     u32 * (num_nodes + 1)
        neighbor   u32 * num_edges
        weight     f32 * num_edges   (metros)
        tier       u8  * num_edges   (codigo de TIER_CODES)

    O grafo e' nao-dirigido; cada aresta entra duas vezes (i->j e j->i), e o
    custo de roteamento se recompoe no aparelho como weight * TIER_MULTIPLIER.
    """
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)

    adj = [[] for _ in range(n)]
    for u, v, d in G.edges(data=True):
        i, j = idx[u], idx[v]
        tier = TIER_CODES[d.get("tier", d.get("source", "osm"))]
        w = float(d["weight"])
        adj[i].append((j, w, tier))
        adj[j].append((i, w, tier))

    offset = [0] * (n + 1)
    neighbor = []
    weight = []
    tier = []
    for i in range(n):
        offset[i] = len(neighbor)
        for j, w, t in adj[i]:
            neighbor.append(j)
            weight.append(w)
            tier.append(t)
    offset[n] = len(neighbor)
    m = len(neighbor)

    meta = {
        "crs": "EPSG:4326",
        "tier_codes": TIER_CODES,
        "tier_multipliers": TIER_MULTIPLIER,
        "layers": {
            "osm": {"fonte": "OpenStreetMap", "licenca": "ODbL", "data": None},
            "ibge": {"fonte": "SICAR/IBGE vw_sicar_rodovias", "licenca": "dados abertos SICAR", "data": "data_carga (ver atributo de origem)"},
            "previsia": {"fonte": "Imazon/Sentinel-2", "licenca": "consultar Imazon", "data": None},
        },
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")

    header = struct.pack("<4sIIII", b"AHG3", 1, n, m, len(meta_bytes))

    lon = np.array([lon for lon, _ in nodes], dtype="<f8")
    lat = np.array([lat for _, lat in nodes], dtype="<f8")
    offset = np.array(offset, dtype="<u4")
    neighbor = np.array(neighbor, dtype="<u4")
    weight = np.array(weight, dtype="<f4")
    tier = np.array(tier, dtype="u1")

    blob = b"".join([
        header,
        meta_bytes,
        lon.tobytes(),
        lat.tobytes(),
        offset.tobytes(),
        neighbor.tobytes(),
        weight.tobytes(),
        tier.tobytes(),
    ])
    Path(out_path).write_bytes(blob)
    print(f"  grafo serializado em {out_path}: {n} nos, {m} arestas (dirigido), {len(blob)/1e6:.1f} MB")


def route_test_pairs(G, pairs_path, out_path):
    nodes = list(G.nodes())
    utm_coords = [to_utm.transform(lon, lat) for lon, lat in nodes]
    tree = cKDTree(utm_coords)
    comps = list(nx.connected_components(G))
    comp_of = {}
    for i, c in enumerate(comps):
        for n in c:
            comp_of[n] = i

    features = []
    with open(pairs_path) as f:
        for row in csv.DictReader(f):
            o_node, o_dist = nearest_node_in_graph(
                float(row["origin_lon"]), float(row["origin_lat"]), nodes, tree
            )
            d_node, d_dist = nearest_node_in_graph(
                float(row["dest_lon"]), float(row["dest_lat"]), nodes, tree
            )
            if comp_of.get(o_node) != comp_of.get(d_node):
                print(f"  {row['id']}: sem rota (componentes diferentes)")
                continue

            try:
                path = nx.shortest_path(G, o_node, d_node, weight="cost")
            except nx.NetworkXNoPath:
                print(f"  {row['id']}: sem rota (mesmo componente, mas sem caminho sem risco hidrografico)")
                continue
            edges = list(zip(path, path[1:]))
            tiers = [G[u][v]["tier"] for u, v in edges]
            dist_m = sum(G[u][v]["weight"] for u, v in edges)
            # Composicao por DISTANCIA (m), nao por contagem de arestas - o
            # PrevisIA tem vertices bem mais densos que o OSM, entao contar
            # arestas superestima a fatia do PrevisIA na rota.
            tier_dist = {}
            for u, v in edges:
                t = G[u][v]["tier"]
                tier_dist[t] = tier_dist.get(t, 0.0) + G[u][v]["weight"]
            tier_pct = {t: round(100 * d / dist_m, 1) for t, d in tier_dist.items()}

            if tier_dist.get("risky_bridge"):
                confidence = "baixa"
            elif tier_dist.get("unconfirmed_bridge"):
                confidence = "media"
            else:
                confidence = "alta"

            print(
                f"  {row['id']}: {dist_m/1000:.1f} km na malha | "
                f"origem a {o_dist:.0f} m do no | destino a {d_dist:.0f} m do no | "
                f"confianca {confidence} | % da distancia por tier: {tier_pct}"
            )

            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [list(p) for p in path]},
                "properties": {
                    "id": row["id"],
                    "route_distance_m": round(dist_m, 1),
                    "final_leg_on_foot_m": round(d_dist, 1),
                    "origin_snap_m": round(o_dist, 1),
                    "confidence": confidence,
                    "origin_lon": row["origin_lon"],
                    "origin_lat": row["origin_lat"],
                    "dest_lon": row["dest_lon"],
                    "dest_lat": row["dest_lat"],
                    **{f"pct_{t}": p for t, p in tier_pct.items()},
                },
            })

    Path(out_path).write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
    print(f"\n{len(features)} rotas exportadas em {out_path}")


def component_report(G, label):
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    total = G.number_of_nodes()
    print(f"\n[{label}] nos: {total} | componentes: {len(comps)}")
    if comps:
        print(f"  maior componente: {len(comps[0])} nos ({100*len(comps[0])/total:.2f}%)")
    return comps


def nearest_node_in_graph(lon, lat, node_index, tree, max_dist_m=None):
    x, y = to_utm.transform(lon, lat)
    dist, idx = tree.query([x, y])
    if max_dist_m is not None and dist > max_dist_m:
        return None, dist
    return node_index[idx], dist


def check_reachability(G, pairs_path, filter_mode="all"):
    """Para cada par origem/destino do test-pairs.csv, acha o no mais proximo
    no grafo unificado e verifica se origem e destino caem no mesmo
    componente. "Alcancavel" = mesmo componente, ponto. A distancia ate' o no
    mais proximo (a perna final a pe) e' sempre reportada ao lado, nunca usada
    pra reprovar um par silenciosamente - e' informacao pro leitor do
    relatorio decidir se aquela perna e' razoavel ou nao.

    filter_mode:
      "all"            - usa todas as pontes (snap), do jeito que a busca geometrica criou
      "no_water_risk"  - remove so' as pontes que cruzam rio sem ponte OSM conhecida
                         (o erro mais caro do enunciado), mantem as demais
      "car_confirmed"  - versao conservadora: mantem so' pontes confirmadas por
                         infraestrutura do CAR
    """
    if filter_mode == "no_water_risk":
        edges_to_drop = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("snapped") and d.get("crosses_unbridged_water")
        ]
        G = G.copy()
        G.remove_edges_from(edges_to_drop)
    elif filter_mode == "car_confirmed":
        edges_to_drop = [
            (u, v) for u, v, d in G.edges(data=True)
            if d.get("snapped") and not d.get("car_confirmed")
        ]
        G = G.copy()
        G.remove_edges_from(edges_to_drop)

    comps = list(nx.connected_components(G))
    comp_of = {}
    for i, c in enumerate(comps):
        for n in c:
            comp_of[n] = i

    nodes = list(G.nodes())
    utm_coords = [to_utm.transform(lon, lat) for lon, lat in nodes]
    tree = cKDTree(utm_coords)

    reachable = 0
    rows = []
    with open(pairs_path) as f:
        for row in csv.DictReader(f):
            o_node, o_dist = nearest_node_in_graph(
                float(row["origin_lon"]), float(row["origin_lat"]), nodes, tree
            )
            d_node, d_dist = nearest_node_in_graph(
                float(row["dest_lon"]), float(row["dest_lat"]), nodes, tree
            )
            ok = (
                comp_of.get(o_node) is not None
                and comp_of.get(o_node) == comp_of.get(d_node)
            )
            if ok:
                reachable += 1
            rows.append(
                {
                    "id": row["id"],
                    "reachable": ok,
                    "origin_snap_m": round(o_dist, 1),
                    "dest_snap_m": round(d_dist, 1),
                }
            )
    label = {
        "all": "TODAS AS PONTES (proximidade geometrica pura)",
        "no_water_risk": "SEM RISCO HIDROGRAFICO (remove pontes que cruzam rio sem passagem)",
        "car_confirmed": "CONSERVADOR (so pontes confirmadas pelo CAR)",
    }[filter_mode]
    print(f"\n[{label}] Mesmo componente (origem-destino): {reachable}/{len(rows)}")
    for r in rows:
        flag = "OK" if r["reachable"] else "--"
        print(
            f"  [{flag}] {r['id']:8s} ultima perna origem={r['origin_snap_m']:8.1f}m "
            f"destino={r['dest_snap_m']:8.1f}m"
        )
    return rows


if __name__ == "__main__":
    print("Carregando camadas...")
    osm_lines = load_lines(OSM_PATH)
    previsia_lines = load_lines(PREVISIA_PATH)
    print(f"  OSM: {len(osm_lines)} linhas | PrevisIA: {len(previsia_lines)} linhas")

    G_previsia = build_raw_graph(previsia_lines, source="previsia")
    component_report(G_previsia, "PrevisIA cru (sem snap)")

    print("Carregando malha IBGE/SICAR...")
    ibge_lines = load_lines_from_shp(IBGE_RODOVIAS_PATH)
    print(f"  IBGE: {len(ibge_lines)} linhas")

    # Grafo unificado: OSM + PrevisIA + IBGE no mesmo espaco de nos
    # (compose: em aresta duplicada exata entre camadas, a ultima passada
    # prevalece - caso raro dado que sao fontes independentes)
    G_osm = build_raw_graph(osm_lines, source="osm")
    G_ibge = build_raw_graph(ibge_lines, source="ibge")
    G = nx.compose(nx.compose(G_osm, G_ibge), G_previsia)
    component_report(G, "Uniao OSM+IBGE+PrevisIA (sem snap)")

    print("\nCarregando infraestrutura do CAR...")
    car_buffer = load_car_infra_union(CAR_INFRA_PATH, buffer_m=CAR_CONFIRM_BUFFER_M)

    print("Carregando hidrografia oficial (SIGERH/CAR) + pontes conhecidas (OSM)...")
    hydro = load_hydrography_union(DRENAGEM_PATH, BRIDGES_PATH)

    for tol in (300,):  # so' 300m nesta rodada, pra caber no tempo de execucao
        Gt = G.copy()
        added = snap_components(Gt, tolerance_m=tol, car_infra_buffer=car_buffer, hydro=hydro)
        component_report(Gt, f"Uniao com snap {tol}m (+{added} arestas)")
        check_reachability(Gt, PAIRS_PATH, filter_mode="all")
        check_reachability(Gt, PAIRS_PATH, filter_mode="no_water_risk")
        check_reachability(Gt, PAIRS_PATH, filter_mode="car_confirmed")

    print(f"\n=== Roteamento ponderado por confianca (snap {tol}m, pontes de risco proibidas) ===")
    assign_costs(Gt)
    safe_G = strip_risky_bridges(Gt)
    route_test_pairs(safe_G, PAIRS_PATH, "rotas_desafio3.geojson")
    serialize_graph(safe_G, GRAPH_OUT_PATH)
