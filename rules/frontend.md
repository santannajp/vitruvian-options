---
# Convencoes de frontend. Carrega ao tocar UI/web app futura.
paths:
  - "frontend/**"
  - "web/**"
  - "app/**"
  - "src/**/*.tsx"
  - "src/**/*.ts"
  - "*.tsx"
---

# Frontend — Consumidor Da Camada Canonica

Frontend, dashboards, charts, TradingView datafeed e UI ficam fora do MVP da camada de dados. Nao crie frontend por antecipacao enquanto o PRD atual ainda estiver focado em Hyperliquid → raw data → normalizacao → canonical OHLCV → SQLite → consulta interna.

Se uma issue futura pedir frontend explicitamente, a UI deve ser uma camada consumidora da aplicacao, nunca uma fonte primaria de dados nem uma camada de normalizacao.

## Regra Central

Frontend nao fala diretamente com Hyperliquid, Deribit, Interactive Brokers, Kalshi ou qualquer provider externo.

A UI consome API interna ou interface local construida sobre dados canonicos. Se precisar exibir informacao de mercado, ela vem de `CanonicalOhlcv`, instrumentos internos e metadados de qualidade/proveniencia.

## Stack Esperada

- Use React + Vite + TypeScript se o projeto adotar frontend web.
- Componentes funcionais e hooks; sem class components.
- Tipos explicitos para props, respostas de API e estados de UI.
- Nada de `any` em contratos de API ou dados financeiros.
- Chamadas externas ficam isoladas em uma camada de API/client, nao espalhadas em componentes.

## Estados De UI

Toda tela que consulta dados deve tratar estados explicitamente:

- carregando;
- erro;
- vazio;
- sucesso;
- dados parciais ou desatualizados, quando aplicavel;
- qualidade degradada, quando houver issues de data quality.

Nao deixe tela silenciosa durante requisicao, stream, erro de provider propagado pela API ou ausencia de dados.

## Dados Financeiros Na UI

Ao exibir OHLCV ou derivados de market data, mostre contexto suficiente:

- instrumento ou `instrument_id`;
- simbolo visivel;
- provider/source quando relevante;
- timeframe;
- periodo consultado;
- timestamp em UTC ou timezone explicitamente convertido na apresentacao;
- `ingested_at` ou indicacao de atualizacao quando relevante;
- alertas de gaps, duplicatas ou qualidade quando a API expuser isso.

Nao esconda proveniencia dos dados. Um grafico bonito sem fonte, periodo e timeframe claros e enganoso.

## Canonical First

- Componentes nao devem conhecer payload bruto da Hyperliquid.
- Campos como `t`, `T`, `o`, `h`, `l`, `c`, `v`, `s` e `i` nao devem aparecer no frontend, exceto em telas explicitas de debug/raw payload.
- Use nomes de dominio canônico: `instrumentId`, `timestamp`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `source`, `ingestedAt`.
- Conversoes para labels, formatos numericos e timezone pertencem a camada de apresentacao, nao ao modelo canonico.

## Realtime E Streaming

Nao assuma SSE, WebSocket ou polling sem contrato de API definido.

Se a UI consumir realtime futuramente:

- renderize estado incremental sem bloquear a tela;
- diferencie candle parcial de candle fechado;
- nao persista nem normalize dados no browser;
- trate reconnect, erro e dados atrasados;
- mostre quando o dado exibido ainda esta em formacao;
- preserve ordenacao temporal e nao duplique pontos no grafico.

## Charts

Charts sao consumidores de dados canonicos.

- Nao monte OHLCV a partir de trades ou payload raw no frontend.
- Nao corrija gaps ou duplicatas silenciosamente na UI.
- Se houver gap, mostre ou respeite a lacuna.
- Nao invente candles para deixar o grafico visualmente continuo.
- Use formatacao numerica adequada para preco e volume.

## Seguranca E Configuracao

- Nenhum segredo no bundle.
- Nao exponha API keys, tokens ou headers privados no frontend.
- A UI deve chamar apenas endpoints publicos/seguros da propria aplicacao.
- Nao aponte browser para servicos internos, bancos, providers ou endpoints administrativos.
- Variaveis publicas de build devem conter somente configuracao segura para cliente.

## Organizacao

- I/O de API em camada dedicada.
- Componentes exibem estado e delegam fetch/transformacao leve.
- Tipos compartilhados devem refletir contrato publico da API, nao tabelas internas por acidente.
- Evite duplicar regra de negocio no frontend.
- Validacoes de dominio criticas continuam no backend.

## Acessibilidade E UX

- Estados de erro devem explicar a acao possivel: tentar novamente, alterar periodo, escolher outro timeframe ou aguardar dados.
- Tabelas e graficos devem ter labels compreensiveis.
- Numeros financeiros devem ser legiveis em desktop e mobile.
- Nao use cor como unico indicador de alta/baixa, erro ou qualidade degradada.
- Loading skeleton e mensagens vazias devem preservar layout sem saltos excessivos.

## Fora Do Escopo Do MVP

Nao implemente por antecipacao:

- dashboard;
- charts;
- TradingView datafeed;
- screener;
- UI de estrategia;
- backtesting visual;
- alertas;
- autenticacao;
- multiusuario;
- painel administrativo.

Se uma fatia futura pedir frontend, ela deve declarar criterio de aceite proprio e nao pode alterar o contrato da camada de dados sem decisao explicita.
