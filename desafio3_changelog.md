# Desafio 3 — Registro de alterações, correções e melhorias

Este documento registra o que foi revisado e modificado nos entregáveis do Desafio 3
(`desafio3_grafo_base.py`, `desafio3_avaliacao.md` e `rotas_desafio3.geojson`) para
deixá-los reprodutíveis, consistentes com a execução real e honestos em relação ao
enunciado do AmazôniaHack 4.0.

## 1. Ambiente de execução

O pipeline depende de `networkx`, `scipy`, `pyproj`, `shapely` e `geopandas` (que puxam
`numpy` e `pandas`). As versões usadas estão pinadas em **`requirements.txt`** (Python
3.11). Para reproduzir em qualquer máquina:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python desafio3_grafo_base.py
```

O `pyproj` instalado via pip embute o `proj.db`, então **não** é necessário configurar
`PROJ_LIB`. O comando deve ser executado a partir da **raiz do projeto** (o `DATA_DIR`
do script é relativo), onde ficam `desafio3_grafo_base.py`, o `participant-package/` e
as pastas `vw_*` dos shapefiles.

## 2. Correções em `desafio3_grafo_base.py`

| # | O que | Antes | Depois | Por quê |
|---|---|---|---|---|
| 1 | Docstring de dependências | `pip install --break-system-packages` (só Linux/Mac) | `pip install networkx scipy pyproj shapely geopandas` | Instalação multi-plataforma e `geopandas` (que o script importa) estava ausente |
| 2 | Caminho da infraestrutura do CAR | `car_infra/vw_area_infraestrutura_publica_cpPolygon.shp` | `vw_area_infraestrutura_publica_cp/...` | As pastas reais dos shapefiles não eram `car_*` |
| 3 | Caminho da malha IBGE/SICAR | `car_rodovias/vw_sicar_rodoviasLine.shp` | `vw_sicar_rodovias/...` | idem |
| 4 | Caminho da drenagem SIGERH-PA | `car_drenagem/vw_trecho_drenagem.shp` | `vw_trecho_drenagem/...` | idem |
| 5 | Leitura dos GeoJSON | `Path(path).read_text()` | `read_text(encoding="utf-8")` | No Windows o default era cp1252; os GeoJSON são UTF-8 (`UnicodeDecodeError`) |
| 6 | Leitura das pontes Overpass | `read_text()` | `read_text(encoding="utf-8")` | idem |
| 7 | Escrita do GeoJSON de saída | `write_text(...)` | `write_text(..., encoding="utf-8")` | Consistência de codificação |
| 8 | Relatório de rota impresso | só a perna de destino | pernas de **origem e destino** | A perna de origem também é grande nos pares site-to-site |
| 9 | Properties do GeoJSON | sem coordenadas reais | `origin_lon/lat` e `dest_lon/lat` adicionados | Deixa explícita a distância fora da malha em cada ponta |

> O arquivo `osm_bridges_paragominas.json` foi mantido na raiz, que é onde o script já
> o referenciava. Validação: 287 ways, todos com `geometry` e `tags` (`bridge=yes`),
> parseados corretamente por `bridges_from_overpass`.

## 3. Correções em `desafio3_avaliacao.md`

Todos os números abaixo foram conferidos **rodando o pipeline** (não por inspeção):

| Campo | Antes | Depois | Observação |
|---|---|---|---|
| Volume da malha IBGE | 24.346 linhas | 24.346 linhas (mantido) | A `.dbf` tem 24.330 registros; o script divide multipartes → 24.346 linhas |
| Maior componente do PrevisIA | 2,6% do total | **2,6% dos nós** | Execução dá 2,58% (9.960 nós). README usa 2,3% por outra métrica |
| Perna final a pé (máx.) | 2.557 m | **1.937 m** | Máximo real na execução (par-01) |
| Perna de origem site-to-site | 724–1.444 m | **111–1.444 m** | Mínimo real (par-15 = 111 m) |
| Ponte não confirmada | "menos de 0,5%" | **"≤0,5%"** | O dado real chega a 0,5% |

### Novos trechos adicionados

1. **Transparência das pernas a pé** — parágrafo explicando que as linhas do GeoJSON
   terminam no último nó da malha (as pernas de origem/destino não são desenhadas), e
   que a distância restante fica nas properties `origin_snap_m` / `final_leg_on_foot_m`.

2. **Por que nenhuma rota é "alta"** — toda rota depende de ao menos uma ponte não
   confirmada (0,2–0,5% da distância), então todas saem como confiança "media". Isso é
   apresentado como descoberta, não defeito.

3. **Estatísticas de snap** — na rodada final, o snap a 300 m adicionou 8.876 arestas
   (1.098 confirmadas pelo CAR, 1.168 cruzando rio sem ponte, 2.845 rejeitadas por
   precisão do IBGE), levando a união de 2.263 para 704 componentes (maior com 88,6%).

4. **Ressalva de qualidade do CAR** — os polígonos de `vw_area_infraestrutura_publica_cp`
   têm orientação de anel inválida, auto-corrigida pelo `pyogrio`; registrado porque o
   teste de "ponte confirmada" depende desses polígonos.

## 4. Validação (execução completa)

Rodado com o ambiente acima, o pipeline produziu e confirmou:

- PrevisIA cru: **1.874 componentes** (maior = 2,58% dos nós) — bate com o README.
- União OSM + IBGE + PrevisIA: **763.856 nós** ("≈764 mil" do doc).
- Alcance: **11/16** (malha completa), **11/16** sem risco hídrico (sem perda),
  **1/16** só com pontes confirmadas pelo CAR (par-01).
- 11 rotas roteadas; composição 60–90% OSM/IBGE, ≤0,5% ponte não confirmada.
- Pares sem rota: par-03, par-06, par-07, par-12, par-15.

`rotas_desafio3.geojson` foi regenerado com as novas properties
(`origin_lon/lat`, `dest_lon/lat`) e permanece com 11 rotas.

## 5. O que ainda não foi resolvido (fora do escopo desta revisão)

- Os 5 pares sem rota não foram investigados caso a caso (isolamento real vs. limite do
  método de snap) — já declarado no próprio doc como pendência.
- Perfil de elevação/declividade (Copernicus DEM/SRTM) e passabilidade sazonal.
- Empacotamento offline/mobile e map-matching de GPS (marco bônus).
