---
# Padrao de testes. Carrega ao tocar a suite, fixtures ou configuracao de teste.
paths:
  - "tests/**"
  - "src/**/tests/**"
  - "backend/tests/**"
  - "test_*.py"
  - "*_test.py"
  - "pyproject.toml"
---

# Testes — Pytest Para Camada De Dados

A suite de testes deve provar comportamento externo do MVP sem depender de rede externa. Teste decorativo nao conta como evidencia de pronto.

O MVP precisa provar: Hyperliquid → BTC perpetual → historical/realtime OHLCV → raw data → normalizacao → canonical OHLCV → SQLite storage → consulta interna.

## Regra Central

Teste comportamento observavel e invariantes do dominio, nao detalhes internos frageis.

Um teste bom protege uma decisao do PRD: provider independence, raw before transformation, canonical first, instrument identity, UTC, idempotencia, data quality ou query local.

## Ferramentas

- Use `pytest` quando configurado.
- Use `pytest-asyncio` somente se houver codigo async real a testar.
- Arquivos devem seguir `test_*.py`.
- Funcoes devem seguir `test_*`.
- Testes devem ser deterministicos, rapidos e offline por padrao.
- Nao assuma hook de `Stop` ou CI ate eles existirem; `/validar` e a fonte operacional do gate local.

## Proibido

- `assert True` como teste.
- Teste comentado.
- `pytest.mark.skip` sem motivo claro, prazo/issue ou explicacao.
- Chamada real a Hyperliquid em teste unitario.
- Dependencia de `.env`, segredo, token, credencial ou rede externa.
- Teste que passa apenas por nao executar o comportamento importante.
- Teste que valida payload bruto como contrato fora da fronteira provider/adapter.

## Fakes E Fixtures

- Use adapter fake para backfill e realtime.
- Use fixtures pequenas com payloads representativos da Hyperliquid.
- Payload bruto da Hyperliquid deve aparecer em fixtures, adapter tests e normalizer tests, nao como contrato geral da aplicacao.
- Use SQLite temporario por teste ou por fixture isolada.
- Nao use banco real, arquivo persistente compartilhado ou estado da maquina do desenvolvedor.
- Controle tempo com timestamps fixos; nao dependa de `now()` quando o resultado precisa ser deterministico.

## Testes Obrigatorios Por Area

### Modelo Canonico

- `Instrument` diferencia `instrument_id`, `symbol`, `provider_symbol`, venue e market type.
- `CanonicalOhlcv` carrega `instrument_id`, `timestamp`, `timeframe`, OHLC, volume, source e `ingested_at`.
- Timestamps internos sao UTC.
- Precos e volumes preservam precisao esperada.

### Provider / Adapter Hyperliquid

- Backfill monta requisicao correta para candle snapshot.
- Limite de ate 5000 candles por consulta/timeframe e respeitado ou explicitamente modelado.
- Erros de provider sao propagados/registrados de forma clara.
- Campos brutos ficam isolados na fronteira do adapter.
- O teste nao chama Hyperliquid real.

### Raw Data

- Cada candle/evento bruto e persistido individualmente.
- Payload original e preservado.
- Metadados minimos existem: provider, instrumento, timeframe, data type, ingestion mode, provider timestamp, received timestamp e ingestion run.

### Normalizacao

- Payload valido da Hyperliquid vira `CanonicalOhlcv` correto.
- Campos `t`, `T`, `o`, `h`, `l`, `c`, `v`, `s`, `i` nao vazam para modelo canonico.
- Timestamp e convertido para UTC de forma inequívoca.
- Payload invalido falha de forma explicita sem gravar canonical corrompido.

### Storage

- SQLite temporario cria schema necessario.
- Escrita e leitura de `Instrument`, `RawMarketData`, `CanonicalOhlcv`, `IngestionRun` e `DataQualityIssue` ou equivalentes funcionam.
- Chave unica de canonical OHLCV impede duplicata por `instrument_id + timeframe + timestamp`.
- Upsert/idempotencia mantem contagem correta em reexecucao.
- Query retorna dados ordenados por timestamp.

### Backfill E Overlap

- Backfill grava raw e canonical.
- Reexecutar backfill no mesmo periodo nao duplica canonical.
- Retomada identifica ultimo candle salvo.
- Overlap recente nao duplica nem remove dados validos.

### Realtime

- Eventos simulados sao persistidos como raw.
- Candle parcial nao e gravado em canonical.
- Candle fechado e gravado em canonical.
- Eventos fora de ordem nao quebram idempotencia.
- Timeframes longos usam simulacao, nao espera real.

### Data Quality

- Detecta duplicatas.
- Detecta gaps no range ingerido.
- Detecta timestamps fora de ordem.
- Detecta OHLC inconsistente.
- Registra ou retorna issues com tipo, severidade, timestamp e detalhes suficientes.

### CLI / Interface Programatica

- `backfill` chama o fluxo historico e grava raw/canonical.
- `stream` usa fake/simulacao e grava canonical apenas para candles fechados.
- `validate` reporta problemas esperados.
- `query` le storage local e nao chama provider.
- Saida de comando inclui status suficiente para operador.

## Testes De Integracao Real

Integração real com Hyperliquid e permitida apenas como teste opcional/marcado.

Regras:

- nao roda no CI comum por padrao;
- nao exige segredo;
- usa range pequeno;
- documenta rate limits e dependencia de rede;
- falha de rede nao deve quebrar suite unitária;
- nao e a unica prova de normalizacao, storage ou idempotencia.

## Bugs Viram Regressao

Cada bug corrigido deve ganhar teste de regressao no nivel mais alto razoavel.

Exemplos:

- bug de timestamp vira teste de normalizacao ou storage;
- duplicata em retomada vira teste de overlap/idempotencia;
- query chamando provider vira teste de CLI/interface programatica com fake que falha se chamado;
- candle parcial salvo em canonical vira teste de realtime.

## Qualidade Da Suite

- Testes devem ter nomes que descrevem comportamento.
- Arrange/Act/Assert claro.
- Fixtures devem ser pequenas e intencionais.
- Evite snapshot gigante de payload se poucos campos bastam para provar o comportamento.
- Nao teste ordem interna de chamadas quando o comportamento final e o que importa.
- Prefira testar por storage/CLI/service seam a testar metodo privado.

## Prontidao

Uma fatia de backend sem teste pode ate ser prototipo, mas nao esta pronta.

Uma fatia que depende de Hyperliquid real para provar comportamento basico nao esta pronta.

Uma fatia com teste desligado em silencio nao esta pronta.
