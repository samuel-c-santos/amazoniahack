# Dados de entrada — fontes e reprodução

O repositório não redistribui os dados do pacote do organizador nem os artefatos
derivados (regras "do not redistribute" e "do not publish exact coordinates" do
desafio). Este arquivo documenta onde obter cada entrada para rodar
`desafio3_grafo_base.py` do zero.

## O que já está no repositório

| Arquivo | Fonte | Licença |
|---|---|---|
| `osm_bridges_paragominas.json` | OpenStreetMap via Overpass (287 vias com `bridge`) | ODbL — © contribuidores OpenStreetMap |

## O que é baixado/regenerado localmente

### 1. Pacote do organizador (não redistribuído)

- `roads-osm-paragominas.geojson`
- `roads-previsia-2025-paragominas.geojson`
- `test-pairs.csv`

Fornecidos no pacote do participante do AmazôniaHack 4.0. Mantenha a estrutura
original em `participant-package/participant-package/challenge-3/`.

### 2. Malha viária IBGE/SICAR — WFS público (`vw_sicar_rodovias/`)

```
https://geoserverdw.apps.geoapplications.net/geoserver/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=workspace_sicar:vw_sicar_rodovias&propertyName=id_rodovia,tx_nome_municipio,tx_sigla_municipio,tx_tipo,tx_orgao_resp,data_carga,geom&outputFormat=shape-zip&CQL_FILTER=BBOX(geom%2C%20-48.8914633%2C-3.837308%2C-46.4191382%2C-2.410546)&format_options=CHARSET:UTF-8
```

### 3. Drenagem SIGERH-PA — WFS público (`vw_trecho_drenagem/`)

```
https://geoserverdw.apps.geoapplications.net/geoserver/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=workspace_sigerh:vw_trecho_drenagem&propertyName=cobacia,tx_nome_original,geom&outputFormat=shape-zip&CQL_FILTER=BBOX(geom%2C%20-48.8914633%2C-3.837308%2C-46.4191382%2C-2.410546)&format_options=CHARSET:UTF-8
```

### 4. Infraestrutura declarada no CAR — WFS público (`vw_area_infraestrutura_publica_cp/`)

```
https://geoserverdw.apps.geoapplications.net/geoserver/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=workspace_sicar:vw_area_infraestrutura_publica_cp&propertyName=id_area_infraestrutura_publica,tx_cod_imovel,tx_cod_protocolo,nu_area,tx_orgao_resp,data_carga,geom&outputFormat=shape-zip&CQL_FILTER=BBOX(geom%2C%20-48.8914633%2C-3.837308%2C-46.4191382%2C-2.410546)&format_options=CHARSET:UTF-8
```

### 5. Pontes — Overpass/OSM

Regenerável com esta query Overpass sobre o município (south, west, north, east):

```
[out:json][timeout:60];
way["bridge"](-3.837308,-48.8914633,-2.410546,-46.4191382);
out geom;
```

Ou use o arquivo já versionado `osm_bridges_paragominas.json`.

## Artefatos derivados (gerados pelo pipeline, não versionados)

- `paragominas.graph` / `paragominas_gps.graph` — grafo binário (embute a malha
  derivada do PrevisIA; regra "do not redistribute").
- `rotas_desafio3.geojson` — rotas (embute as coordenadas dos alvos; regra "do not
  publish exact coordinates").

## Atribuição

OpenStreetMap © contribuidores OpenStreetMap, licença ODbL. Dados WFS: SEMAS-PA,
SICAR e SIGERH-PA (dados abertos, sem autenticação).
