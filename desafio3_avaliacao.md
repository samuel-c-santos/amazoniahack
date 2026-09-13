# AmazôniaHack 4.0 — Desafio 3: roteamento em estradas não mapeadas
### Página de avaliação — Paragominas, Pará

## O que atacamos

O PrevisIA já entrega uma malha de estradas não oficiais extraída por sensoriamento remoto — o trabalho de detecção está feito. O que falta, e é onde miramos, é o problema que o próprio enunciado nomeia: **um traço extraído não é um grafo**. Construímos a topologia, medimos a conectividade de forma objetiva, atribuímos confiança por trecho e roteamos em cima disso — sem usar nenhum modelo de linguagem ou de visão computacional em nenhuma etapa.

## Método

**Fontes de dados** (todas abertas, nenhuma exclusiva do pacote do desafio):

| Fonte | O que é | Volume |
|---|---|---|
| `roads-osm-paragominas.geojson` | OpenStreetMap, ODbL | 7.095 linhas |
| `roads-previsia-2025-paragominas.geojson` | Traços Imazon/Sentinel-2, sem data por trecho | 35.791 linhas |
| SICAR/IBGE (`vw_sicar_rodovias`, WFS) | Malha viária oficial do IBGE | 24.346 linhas |
| SICAR (`vw_area_infraestrutura_publica_cp`, WFS) | Infraestrutura declarada em 1.030 imóveis do CAR | 2.799 polígonos |
| SIGERH-PA (`vw_trecho_drenagem`, WFS) | Hidrografia oficial do estado | 57.559 trechos |
| OpenStreetMap via Overpass | Pontes já mapeadas | 287 vias |

**Construção do grafo.** Unimos as três camadas viárias no mesmo espaço de nós. A malha PrevisIA crua se parte em 1.874 componentes desconexos (maior com 2,6% dos nós) — reproduzimos esse número do README do desafio como checagem de sanidade antes de prosseguir. Conectamos apenas extremidades de grau 1 (pontas soltas) dentro de uma tolerância geométrica, nunca vértices internos — a primeira versão deste script fazia snap em qualquer nó próximo e gerou mais de 4 milhões de arestas espúrias antes de travar por memória; documentamos o erro porque é o mesmo efeito que o enunciado chama de "inventar pontes que não existem". Na rodada final, o snap a 300 m acrescentou 8.876 arestas — 1.098 confirmadas por infraestrutura do CAR, 1.168 cruzando curso d'água sem ponte conhecida (excluídas do roteamento) e 2.845 rejeitadas por envolver ponta do IBGE além de 100 m — levando a união de 2.263 para 704 componentes, o maior com 88,6% dos nós.

**Confiança por trecho.** Cada aresta recebe uma camada de origem (OSM, IBGE, PrevisIA ou "ponte") e um multiplicador de custo de roteamento. Medimos o deslocamento posicional do IBGE contra o OSM nas vias principais (mediana 34 m, mas p95 = 424 m e p99 = 2,5 km) e, por isso, tratamos suas pontas com tolerância de snap reduzida (100 m em vez de 300 m) e confiança igual à do PrevisIA, não à do OSM. Cada ponte (snap) é ainda classificada em três níveis: confirmada por infraestrutura declarada no CAR, sem confirmação, ou cruzando um curso d'água da drenagem oficial sem ponte conhecida a menos de 40 m — esse último tipo é **excluído do grafo de roteamento**, não apenas penalizado: uma versão anterior permitia essas travessias quando representavam menos de 0,2% da distância de uma rota, o que reintroduzia silenciosamente o erro que o filtro deveria prevenir. Ressalva de qualidade dos dados: o shapefile de infraestrutura do CAR (`vw_area_infraestrutura_publica_cp`) carrega polígonos com orientação de anel inválida, que o `pyogrio` autocorrige na leitura — como esse teste de "ponte confirmada" depende de um buffer sobre esses polígonos, registramos a correção em vez de escondê-la.

**Roteamento.** Dijkstra (NetworkX) ponderado por distância real × multiplicador de confiança, sobre o grafo já sem as pontes de risco hídrico.

## O que medimos, e em que dado

Usamos os 16 pares de `test-pairs.csv`, fornecidos pelo próprio desafio.

| Métrica | Resultado |
|---|---|
| Mesmo componente (origem–destino), malha completa | **11 / 16** |
| Mesmo componente, removendo pontes que cruzam rio sem passagem | **11 / 16** (sem perda) |
| Mesmo componente, só pontes confirmadas por infraestrutura do CAR | **1 / 16** |
| Pares sem rota sob qualquer configuração | par-03, par-06, par-07, par-12, par-15 |

Os 11 pares alcançáveis foram efetivamente roteados. Nenhuma rota final depende de travessia de rio sem passagem conhecida (exclusão categórica, não estatística). A composição típica por distância: 60–90% em via OSM ou IBGE, o restante em PrevisIA, e ≤0,5% em ponte não confirmada — o "salto" de baixa confiança é sempre um trecho residual pequeno, nunca o corpo da rota. A perna final a pé, do nó mais próximo até o destino real, varia de 298 m a 1.937 m e é declarada por rota, não usada como critério de aprovação — conforme a orientação do próprio enunciado. Para os pares site-to-site, a perna de origem é igualmente relevante (111 m a 1.444 m até o nó mais próximo) e também é declarada por rota; nenhuma das duas pernas é desenhada no GeoJSON — a linha termina no último nó da malha, e a distância restante fica explícita nas propriedades `origin_snap_m` e `final_leg_on_foot_m`, junto das coordenadas reais de origem e destino (`origin_lon/lat`, `dest_lon/lat`).

Nenhuma das 11 rotas atinge o rótulo "alta": todas dependem de ao menos uma ponte não confirmada (0,2–0,5% da distância), então saem como confiança "media". Isso é uma descoberta em si, não um artefato de escala — nenhum par alcançável se resolve 100% sobre vias confirmadas — e é o motivo de mantermos o breakdown percentual por tier ao lado do rótulo, em vez de esconder o salto atrás de uma média agregada.

O teto de 9–10/16 relatado no README do desafio (só OSM + PrevisIA) subiu para 11/16 ao incorporar a malha do IBGE e validar contra hidrografia oficial — mas apenas 1 desses 11 tem confirmação independente por infraestrutura declarada no CAR. Essa lacuna entre "geometricamente plausível" e "confirmado por segunda fonte" é, na nossa avaliação, o número mais honesto que temos para descrever a confiabilidade da malha nessa área.

## O que ficou de fora

- **Perfil de elevação/declividade.** Usamos a drenagem oficial só para o teste binário de cruzamento; não chegamos a baixar Copernicus DEM/SRTM para modelar declividade ou passabilidade sazonal.
- **Os 5 pares sem rota** não foram investigados caso a caso — não sabemos se são isolamento real ou limite do método de snap.
- **Empacotamento offline/mobile.** A entrega é um script Python (CLI), não um app Android nem um pacote Valhalla pré-computado.
- **Marco bônus (mapa que melhora com o uso).** Não implementamos map-matching de traços de GPS.
- **Idade real da malha PrevisIA.** O atributo não existe nos dados (só `cat` e `fonte`); declaramos essa ausência em vez de estimar uma data.

## Custo

Custo marginal por rota: **essencialmente zero**. Todo o pipeline é geoprocessamento clássico (NetworkX, Shapely, GeoPandas, SciPy, PyProj) — nenhuma chamada a modelo de linguagem ou de visão em nenhuma etapa, nem para a extração viária (já dada) nem para o roteamento. O custo real está na preparação, feita uma única vez: três downloads WFS públicos (SICAR/SEMAS-PA, SIGERH-PA) e duas consultas Overpass, ambos gratuitos e sem autenticação. O grafo unificado (≈764 mil nós) constrói e roteia os 16 pares em poucos minutos, sem GPU, num notebook comum.
