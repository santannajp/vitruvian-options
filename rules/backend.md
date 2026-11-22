---
# Regras do backend da camada de dados financeiros. Carrega ao tocar codigo Python,
# testes ou modulos de ingestao, normalizacao, storage, CLI e validacao.
paths:
  - "src/**"
  - "tests/**"
  - "vitruvian_project/**"
  - "backend/**"
  - "*.py"
  - "pyproject.toml"
---

# Backend — Camada De Dados Financeiros

O backend deste projeto e, primeiro, uma camada de dados. No MVP nao existe requisito de API HTTP, UI, dashboard ou FastAPI. A responsabilidade central e fazer um dataset OHLCV de BTC perpetual na Hyperliquid atravessar a arquitetura corretamente: provider → raw data → normalizer → canonical OHLCV → SQLite storage → consulta interna.

## Regra Central

O backend deve ser deterministico, testavel e orientado ao modelo canonico. Provider externo conhece o proprio formato; o nucleo da aplicacao conhece apenas o formato interno padronizado.

Quebrar essa separacao e bug arquitetural.

## Camadas

- `providers` / `adapters`: falam com APIs externas e conhecem formatos especificos de provider.
- `historical acquisition`: executa backfill por REST ou mecanismo equivalente.
- `realtime acquisition`: consome stream/WebSocket ou mecanismo equivalente.
- `raw data`: preserva payload original e metadados de ingestao.
- `normalizer`: converte provider-specific data para modelo canonico.
- `canonical model`: representa entidades internas como `Instrument`, `CanonicalOhlcv` e datasets futuros.
- `storage`: persiste e consulta SQLite local no MVP.
- `data quality`: valida duplicatas, gaps, ordem temporal e consistencia OHLC.
- `cli` / interface programatica: expoe `backfill`, `stream`, `validate` e `query`.

Nao misture responsabilidades entre camadas para ganhar velocidade no curto prazo.

## Provider / Adapter

- A Hyperliquid e o unico provider real do MVP.
- O aceite obrigatorio e BTC perpetual.
- O simbolo pode ser configuravel, mas isso nao transforma multiplos ativos em requisito de aceite.
- Codigo fora do adapter/normalizer nao deve depender de campos brutos da Hyperliquid como `t`, `T`, `o`, `h`, `l`, `c`, `v`, `s` e `i`.
- O contrato minimo de adapter deve cobrir OHLCV historico e realtime sem virar framework generica multi-provider.
- Nao adicione Deribit, IBKR, Kalshi ou provider brasileiro sem issue/PRD explicito.

## Historical E Realtime

- Historico e realtime sao fluxos diferentes, mesmo quando geram o mesmo `CanonicalOhlcv`.
- Backfill deve respeitar o limite documentado da Hyperliquid de ate 5000 candles por consulta/timeframe.
- Realtime deve persistir raw events recebidos, mas canonical OHLCV deve gravar somente candles fechados.
- Retomada deve usar overlap recente e escrita idempotente.
- Timeframes longos (`1d`, `3d`, `1w`, `1M`) nao devem depender de espera real para aceite; use pipeline compartilhado e testes simulados.

## Raw Before Transformation

- Preserve payload original antes de normalizar sempre que a fatia fizer parte da ingestao.
- Raw data deve incluir metadados suficientes para auditoria: provider, instrumento, timeframe, tipo de dado, modo de ingestao, timestamp do provider, timestamp de recebimento e execucao de ingestao.
- Nao descarte campos brutos apenas porque a versao atual do canonical nao usa todos eles.
- Raw data serve para reprocessamento, investigacao de erro, mudanca de schema e validacao de transformacoes.

## Canonical First

- Consumidores internos devem usar modelos canonicos, nao payloads de provider.
- O modelo OHLCV canonico deve representar `instrument_id`, `timestamp`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `source` e `ingested_at` ou equivalentes claros.
- A chave unica de candle canonico deve ser `instrument_id + timeframe + timestamp` ou equivalente estrito.
- Timestamps internos devem ser UTC.
- Precos e volumes nao devem sofrer perda desnecessaria de precisao.

## Instrument Identity

- Nunca trate `BTC` como identificador universal.
- Use uma entidade interna de instrumento com `instrument_id`, `symbol`, `provider`, `provider_symbol`, `asset_class`, `market_type`, `venue`, `currency` e metadados equivalentes.
- O backend deve permitir diferenciar BTC perpetual da Hyperliquid de BTC spot, opcoes de BTC, instrumentos de outra venue ou contratos futuros.

## Storage

- SQLite local e o storage primario do MVP.
- Nao introduza Postgres, DuckDB/Parquet como storage primario, cloud ou Docker como requisito do MVP sem decisao explicita.
- Storage deve suportar pelo menos `Instrument`, `RawMarketData`, `CanonicalOhlcv`, `IngestionRun` e `DataQualityIssue` ou equivalentes.
- Escritas em canonical OHLCV devem ser idempotentes.
- Erros de provider, parsing, rede ou normalizacao nao podem corromper dados canonicos ja persistidos.

## Data Quality

- `validate` deve detectar no minimo duplicatas, gaps, timestamps fora de ordem e inconsistencia OHLC.
- Inconsistencia OHLC inclui `low` maior que `open`, `high` ou `close`, e `high` menor que `open`, `low` ou `close`.
- Problemas detectados devem ser registraveis e reportados de forma compreensivel.
- Nao confunda validacao minima do MVP com reconciliacao avancada entre providers; reconciliacao fica fora da primeira versao.

## CLI / Interface Programatica

- O MVP deve expor operacoes locais: `backfill`, `stream`, `validate` e `query`.
- Routers HTTP nao sao requisito do MVP.
- `query` deve consultar storage local e nao chamar Hyperliquid.
- Comandos devem reportar progresso, contagens, erros e resumo de validacao.
- Nao transforme CLI em camada de regra de negocio; CLI roteia argumentos, chama servicos e formata saida.

## API HTTP / FastAPI Futuro

Se uma API HTTP for adicionada em versao futura:

- handlers devem ser finos: validar entrada, chamar servico e formatar saida;
- regra de negocio continua em servicos da camada de dados;
- nenhuma interface deve consultar providers diretamente;
- erros de dominio devem virar respostas claras sem vazar stack trace, SQL bruto ou segredos;
- configuracao deve vir de settings/config, nunca de `os.environ` solto espalhado nem hardcode.

Enquanto API HTTP estiver fora do PRD do MVP, nao crie FastAPI por antecipacao.

## Configuracao E Segredos

- URLs, tokens, API keys, paths de banco e flags operacionais devem vir de configuracao.
- Nao hardcode segredo, endpoint privado ou credencial.
- `.env` local nao deve ser fonte de contrato da aplicacao nem ser assumido em testes.
- Tests devem conseguir rodar com fakes e SQLite temporario sem credenciais externas.

## Async E I/O

- Use async quando a dependencia e o fluxo justificarem I/O concorrente.
- Nao misture chamadas bloqueantes em event loop async.
- Nao introduza async por moda se o fluxo local/sincrono for mais simples e testavel.
- O criterio e clareza operacional, testabilidade e ausencia de bloqueio indevido.

## Testes Obrigatorios Para Fatias De Backend

- Normalizacao com payloads representativos da Hyperliquid.
- Storage com SQLite temporario.
- Idempotencia de backfill e overlap.
- Validacao de duplicatas, gaps, ordem temporal e OHLC inconsistente.
- Realtime com adapter fake ou eventos simulados.
- Query por instrumento, timeframe e periodo, ordenada por timestamp.
- Integracao real com Hyperliquid deve ser opcional/marcada, nunca obrigatoria no CI comum.

## Fora Do Escopo Do MVP

Nao cobre nem implemente por antecipacao:

- trades, quotes, order book, funding rate, open interest, mark price, index/oracle price;
- opcoes, Greeks, prediction markets, volatility analytics;
- feature engine, indicadores, estudos, modelos, estrategias, backtesting, alertas;
- dashboards, charts, TradingView datafeed, API HTTP;
- autenticacao, multiusuario, permissoes, cloud, Postgres, DuckDB/Parquet primario;
- reconciliacao entre providers ou correcao automatica avancada de dados.

Adicionar abstração para algo fora do escopo so e aceitavel se ela reduzir acoplamento agora sem aumentar o contrato do MVP.
