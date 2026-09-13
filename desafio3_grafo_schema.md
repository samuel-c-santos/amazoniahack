# Schema do grafo serializado (`paragominas.graph`)

Formato binário compacto (CSR) do grafo roteável de Paragominas, gerado por
`desafio3_grafo_base.py` (`serialize_graph`) para uso offline. Números atuais:
**763.856 nós**, **1.559.340 arestas dirigidas**, **29,3 MB**.

Tudo é little-endian. Layout sequencial do arquivo:

| Offset | Campo | Tipo | Bytes |
|---|---|---|---|
| 0 | `magic` | `"AHG3"` (4 bytes) | 4 |
| 4 | `version` | `u32` = 1 | 4 |
| 8 | `num_nodes` | `u32` | 4 |
| 12 | `num_edges` | `u32` (dirigido = 2 × não-dirigido) | 4 |
| 16 | `meta_len` | `u32` | 4 |
| 20 | `meta` | UTF-8 JSON (`meta_len` bytes) | `meta_len` |
| … | `lon` | `f64` × `num_nodes` | `8·N` |
| … | `lat` | `f64` × `num_nodes` | `8·N` |
| … | `offset` | `u32` × (`num_nodes` + 1) | `4·(N+1)` |
| … | `neighbor` | `u32` × `num_edges` | `4·M` |
| … | `weight` | `f32` × `num_edges` (metros) | `4·M` |
| … | `tier` | `u8` × `num_edges` | `M` |

## Semântica do CSR

- O nó `i` tem coordenadas `(lon[i], lat[i])`, em WGS84 (`EPSG:4326`).
- Os vizinhos do nó `i` são `neighbor[offset[i] : offset[i+1]]`, com peso
  `weight[k]` e tier `tier[k]` para cada índice `k` nesse intervalo.
- O grafo é não-dirigido: cada aresta entra duas vezes (`i→j` e `j→i`).
- Custo de roteamento = `weight[k] * tier_multipliers[tier[k]]` (Dijkstra).

## Tier (código) e multiplicador

| Código | Tier | Multiplicador |
|---|---|---|
| 0 | `osm` | 1.0 |
| 1 | `ibge` | 1.2 |
| 2 | `previsia` | 1.2 |
| 3 | `confirmed_bridge` | 1.5 |
| 4 | `unconfirmed_bridge` | 4.0 |

(`risky_bridge` = 20.0 não aparece: essas arestas são removidas antes da
serialização.)

## `meta` (JSON)

```json
{
  "crs": "EPSG:4326",
  "tier_codes": { "osm": 0, "ibge": 1, "previsia": 2, "confirmed_bridge": 3, "unconfirmed_bridge": 4 },
  "tier_multipliers": { "osm": 1.0, "ibge": 1.2, "previsia": 1.2, "confirmed_bridge": 1.5, "unconfirmed_bridge": 4.0, "risky_bridge": 20.0 },
  "layers": {
    "osm":     { "fonte": "OpenStreetMap", "licenca": "ODbL", "data": null },
    "ibge":    { "fonte": "SICAR/IBGE vw_sicar_rodovias", "licenca": "dados abertos SICAR", "data": "data_carga (ver atributo de origem)" },
    "previsia":{ "fonte": "Imazon/Sentinel-2", "licenca": "consultar Imazon", "data": null }
  }
}
```

A data do PrevisIA é `null` de propósito: o atributo não existe nos dados de
origem (o README do desafio confirma), e o requisito "rotas devem indicar a data
dos dados subjacentes" é atendido declarando a ausência em vez de estimar.

## Leitura de referência (pseudocódigo)

```
header   = unpack("<4sIIII", bytes[0:20])   # magic, version, N, M, meta_len
meta     = json(bytes[20 : 20+meta_len])
p        = 20 + meta_len
lon      = f64[N] @ p;  p += 8*N
lat      = f64[N] @ p;  p += 8*N
offset   = u32[N+1] @ p; p += 4*(N+1)
neighbor = u32[M] @ p;  p += 4*M
weight   = f32[M] @ p;  p += 4*M
tier     = u8[M]  @ p
```

## Snap origem/destino

Para achar o nó mais próximo de um ponto (a "perna a pé"), o consumidor constrói
um índice espacial (grid ou k-d tree) sobre `(lon, lat)` ao carregar — 764 mil
pontos em 2D é barato. Não há índice embutido no binário para manter o formato
mínimo.

## Por que não GeoJSON

O GeoJSON só das 11 rotas já ocupa 1,9 MB; o grafo inteiro nele passaria das
centenas de MB. O CSR em binário deixa o mesmo grafo em ~29 MB, adequado a um
smartphone intermediário e carregável sem rede.
