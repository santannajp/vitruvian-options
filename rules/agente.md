---
# Regras para agentes/LLMs no projeto. Carrega ao tocar código de agentes, orchestration,
# comandos que usem LLM, ou integrações futuras de AI sobre a camada de dados.
paths:
  - "src/**/agent/**"
  - "src/**/agents/**"
  - "src/**/llm/**"
  - "src/**/ai/**"
  - "src/**/orchestration/**"
  - "tests/**/agent/**"
  - "tests/**/agents/**"
  - ".opencode/**"
---

# Agentes — Consumidores Da Camada De Dados, Nunca Núcleo Do Dado

Agentes de IA são uma possibilidade de longo prazo do projeto. Eles não fazem parte do MVP da camada de dados. Quando existirem, devem ser consumidores da infraestrutura de dados, não responsáveis pela integridade do pipeline.

O MVP atual é data first: Hyperliquid → BTC perpetual → Historical OHLCV + Realtime OHLCV → Raw Data → Normalization → Canonical OHLCV → SQLite Storage → consulta interna.

## Regra Central

O agente pode ajudar a interpretar, resumir, investigar ou operar a camada de dados. Ele não pode substituir código determinístico nas decisões que garantem qualidade, identidade, normalização, storage ou idempotência.

Quebrar essa regra é bug arquitetural.

## Fora Do MVP

No MVP, não implemente agentes de IA como requisito funcional.

Não introduza LangChain, LangGraph, Deep Agents, tool-calling autônomo, memória de agente, chat UI ou workflows LLM se a fatia for de ingestão, normalização, storage, validação ou CLI do MVP.

Se uma issue futura pedir agentes explicitamente, primeiro valide o escopo contra o PRD e registre a decisão arquitetural antes de acoplar agentes ao produto.

## Data First

- Agentes não consultam Hyperliquid, Deribit, Interactive Brokers, Kalshi ou qualquer provider diretamente.
- Agentes consomem apenas dados canônicos ou APIs internas construídas sobre dados canônicos.
- Agentes não leem payload raw como fonte primária de produto, exceto em ferramentas explícitas de auditoria/debug.
- Agentes não escrevem em `CanonicalOhlcv`, `Instrument`, `RawMarketData`, `IngestionRun` ou `DataQualityIssue` como parte de raciocínio livre.
- Qualquer escrita em storage deve passar por serviços determinísticos, schemas e validações do domínio.

## Sem LLM No Caminho Crítico Do Dado

Estas decisões devem ser código determinístico, não decisão de LLM:

- identidade de instrumento;
- mapeamento provider → canonical;
- normalização de timestamps para UTC;
- cálculo de candle fechado vs candle parcial;
- deduplicação por `instrument_id + timeframe + timestamp`;
- overlap de retomada;
- validação de gaps, duplicatas, ordenação temporal e consistência OHLC;
- decisão de persistir ou rejeitar dado canônico.

LLM pode explicar um problema detectado. Não pode decidir sozinho se um dado é válido.

## Provider Independence

- O agente nunca deve depender de campos específicos da Hyperliquid, como `t`, `T`, `o`, `h`, `l`, `c`, `v`, `s` e `i`.
- Se precisar falar de dados de mercado, use a linguagem canônica: `instrument_id`, `timestamp`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `source`, `ingested_at`.
- Se precisar citar a origem, diferencie claramente `provider`, `venue`, `source`, `provider_symbol` e `instrument_id`.

## Grounding Em Dados

Toda resposta analítica de agente deve declarar de onde vieram os dados usados:

- instrumento;
- timeframe;
- período consultado;
- fonte/camada consultada;
- timestamp ou versão da consulta quando aplicável.

Se não houver dados suficientes, o agente deve dizer isso. Não invente candles, períodos, indicadores, sinais, probabilidades ou conclusões quantitativas.

## Sem Trading Disfarçado

Agentes não devem emitir recomendação de compra/venda, estratégia operacional, sizing, alavancagem ou execução como se fosse funcionalidade do MVP.

O projeto está construindo infraestrutura de dados. Estudos, modelos, estratégias, backtesting e alertas ficam fora da primeira versão.

## Tools E Permissões

- Tools de agente devem ser pequenas, explícitas e orientadas ao domínio.
- Prefira ferramentas de consulta local sobre dados canônicos a ferramentas genéricas de acesso externo.
- Nenhuma tool de agente deve executar mutação destrutiva por padrão.
- Nenhuma tool deve receber segredo hardcoded.
- Model IDs, API keys, endpoints privados e credenciais devem vir de configuração, nunca do prompt ou do código.

## Observabilidade

Toda ação de agente que consultar dados deve ser rastreável:

- comando ou tool chamada;
- parâmetros relevantes;
- período consultado;
- quantidade de registros retornados;
- erros ou dados ausentes.

Falha silenciosa é bug. Resposta confiante sem evidência é bug.

## Quando Usar Frameworks De Agente

Não adicione framework de agente por antecipação.

Se uma funcionalidade futura realmente exigir LangChain, LangGraph, Deep Agents ou equivalente:

- use a skill `ecosystem-primer` antes de escrever código;
- mantenha o fluxo crítico de dados fora do LLM;
- documente por que um workflow de agente é necessário;
- mantenha o agente como camada consumidora da `Canonical Market Data` ou da futura API interna.

## Revisão Obrigatória

Mudanças envolvendo agentes devem ser revisadas contra estes pontos:

- O agente ficou fora do caminho crítico de ingestão/normalização/storage?
- O agente consome dados canônicos em vez de payloads de provider?
- O agente declara instrumento, timeframe, período e fonte dos dados?
- Não há recomendação financeira/trading introduzida sem escopo explícito?
- Não há segredo, endpoint privado ou model id hardcoded?
- Há testes ou fakes suficientes para tool behavior sem depender de rede externa?
