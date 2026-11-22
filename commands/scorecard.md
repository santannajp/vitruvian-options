---
description: Gera um scorecard honesto de aderência ao PRD, arquitetura, qualidade de dados e prontidão do MVP.
---

# /scorecard — Scorecard do MVP de Dados Financeiros

Você vai gerar um scorecard do estado atual do projeto contra o PRD do MVP e a visão arquitetural da plataforma unificada de dados financeiros.

Entrada opcional do usuário: `$ARGUMENTS`

Use os argumentos para filtrar período, issue, PR, branch, fatia ou área quando isso estiver claro. Se os argumentos forem ambíguos, explique a interpretação adotada e siga com a análise mais útil.

## Objetivo

Avaliar, com evidência verificável, quão pronta está a entrega em relação ao MVP:

```text
Hyperliquid
    ↓
BTC Perpetual
    ↓
Historical OHLCV + Realtime OHLCV
    ↓
Raw Data
    ↓
Normalization
    ↓
Canonical OHLCV
    ↓
SQLite Storage
    ↓
Consulta interna via CLI/programática
```

Este comando mede aderência de implementação e risco de entrega. Ele não mede performance financeira, qualidade de estratégia, alpha, backtesting, UI ou valor preditivo.

## Fontes de Verdade

Use evidência do repositório. Não invente números.

- `idea.md`: PRD concreto do MVP.
- `ideia.md`: visão de longo prazo, princípios e linguagem do domínio.
- Issue tracker via `gh`, quando disponível.
- Git local: `git status --short`, `git log --oneline`, `git diff --stat`, `git diff` e `git diff --staged`.
- Testes e gates disponíveis no projeto, como `uv run ruff check .`, `uv run mypy .` e `uv run pytest`, quando apropriado.
- Artefatos locais de métricas somente se existirem; não assuma `metrics/entregas.jsonl` ou qualquer arquivo equivalente.

Se `gh` não estiver autenticado, se não houver testes, se o projeto ainda estiver em skeleton ou se uma fonte não existir, declare explicitamente a lacuna.

## Como Coletar Dados

1. Leia `idea.md` e `ideia.md` o suficiente para identificar escopo, entidades, fluxos e fora de escopo.
2. Inspecione o estado do git para separar código já versionado, mudanças locais e arquivos não rastreados.
3. Se houver issue ou PR nos argumentos, consulte o GitHub com `gh` e relacione a análise a esse artefato.
4. Identifique módulos ou áreas existentes: provider/adapter, historical acquisition, realtime acquisition, raw data, normalizer, canonical model, storage, CLI, data quality e tests.
5. Rode somente comandos de verificação razoáveis para o tamanho atual do projeto. Não rode testes de integração real com Hyperliquid sem necessidade clara.
6. Anote cada pontuação como evidenciada, parcial, ausente ou sem dado.

## Dimensões do Scorecard

Pontue de 0 a 5 cada dimensão. Use `N/A` quando não houver base honesta para medir. Depois calcule o total ponderado apenas com dimensões avaliáveis.

### 1. Escopo do MVP — Peso 20

Avalie se a entrega cobre o que o PRD exige agora:

- Hyperliquid como único provider real.
- BTC perpetual como aceite obrigatório.
- OHLCV histórico e realtime.
- Todos os timeframes da Hyperliquid: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M`.
- CLI ou interface programática com `backfill`, `stream`, `validate` e `query`.
- Consulta local sem chamar a Hyperliquid.

### 2. Arquitetura e Invariantes — Peso 20

Avalie se a implementação respeita os princípios do projeto:

- Provider independence.
- Canonical first.
- Raw before transformation.
- Instrument identity sem tratar símbolo como ID universal.
- UTC internamente.
- Historical e realtime como fluxos separados.
- Data first: estudos, indicadores, modelos, estratégias e UI fora da aquisição.
- Replaceable providers sem framework genérica prematura.

### 3. Modelo de Dados e Storage — Peso 15

Avalie se o storage e as entidades sustentam o MVP:

- SQLite local como storage primário do MVP.
- `Instrument` ou equivalente.
- `RawMarketData` ou equivalente com payload original.
- `CanonicalOhlcv` ou equivalente.
- `IngestionRun` ou equivalente.
- `DataQualityIssue` ou equivalente.
- Chave única de canonical OHLCV por `instrument_id + timeframe + timestamp`.
- Preservação de precisão em preços e volumes.

### 4. Confiabilidade da Ingestão — Peso 15

Avalie robustez operacional do pipeline:

- Backfill respeita limite da Hyperliquid de até 5000 candles por consulta/timeframe.
- Realtime persiste raw events e canonical apenas para candles fechados.
- Retomada com overlap.
- Idempotência em backfill e overlap.
- Falhas de provider, rede, parsing e normalização não corrompem canonical data.
- Timeframes longos não exigem espera real para aceite; usam pipeline compartilhado e simulação.

### 5. Data Quality — Peso 10

Avalie validação mínima de qualidade:

- Duplicatas.
- Gaps no range ingerido.
- Timestamps fora de ordem.
- Consistência OHLC.
- Registro de problemas detectados.
- Saída compreensível para CLI/operador.

### 6. Testes e Gates — Peso 15

Avalie confiança técnica:

- Testes de normalização com payloads da Hyperliquid.
- Testes de storage com SQLite temporário.
- Testes de idempotência.
- Testes de validação com dados semeados.
- Testes de realtime com adapter fake/eventos simulados.
- Testes de `query` por instrumento/timeframe/período.
- Integração real com Hyperliquid opcional ou marcada, não obrigatória no CI comum.
- Ruff, mypy e pytest quando existirem e forem relevantes.

### 7. Operabilidade e Observabilidade — Peso 5

Avalie uso local e depuração:

- Comandos informam progresso, contagens e erros.
- Execuções de ingestão registram status e contadores.
- Erros são acionáveis.
- Não há segredos hardcoded.
- O usuário consegue reproduzir localmente sem Postgres, cloud, Docker ou UI.

## Escala

Use esta escala para cada dimensão:

- `0`: inexistente ou contradiz o PRD.
- `1`: rascunho sem caminho funcional demonstrável.
- `2`: parcial, com lacunas importantes ou risco alto.
- `3`: funcional no caminho principal, mas com lacunas de confiabilidade/testes.
- `4`: atende o PRD com riscos residuais claros.
- `5`: atende o PRD com testes, gates e evidência forte.
- `N/A`: sem base honesta para avaliar.

## Fora do Escopo Não Deve Virar Débito

Não reduza nota por ausência de:

- Deribit, Interactive Brokers, Kalshi ou mercado brasileiro.
- Trades, quotes, order book, funding rate, open interest, mark price ou index/oracle price.
- Opções, Greeks, prediction markets ou volatility analytics.
- Feature engine, indicadores, estudos, modelos, estratégias, backtesting ou alertas.
- Dashboards, charts, TradingView datafeed ou API HTTP.
- Autenticação, multiusuário, permissões, cloud, Postgres ou DuckDB/Parquet como storage primário.

Reduza nota se a implementação cria acoplamento ou decisões que dificultam adicionar esses itens depois.

## Formato da Resposta

Produza Markdown pronto para colar em issue, PR ou board.

```markdown
# Scorecard — <escopo/período>

## Veredito
<verde | amarelo | vermelho> — <1 frase objetiva>

## Score Agregado
| Dimensão | Peso | Nota | Evidência | Risco principal |
|---|---:|---:|---|---|
| Escopo do MVP | 20 | 0-5/N/A | arquivo:linha, issue, teste ou comando | risco |
| Arquitetura e invariantes | 20 | 0-5/N/A | evidência | risco |
| Modelo de dados e storage | 15 | 0-5/N/A | evidência | risco |
| Confiabilidade da ingestão | 15 | 0-5/N/A | evidência | risco |
| Data quality | 10 | 0-5/N/A | evidência | risco |
| Testes e gates | 15 | 0-5/N/A | evidência | risco |
| Operabilidade e observabilidade | 5 | 0-5/N/A | evidência | risco |

Total ponderado: <0-100 ou "sem dado suficiente">

## Principais Achados
- <arquivo:linha ou fonte> — <achado e impacto>

## Lacunas Para Fechar o MVP
- <lacuna concreta ligada ao PRD>

## O Que Está Sólido
- <ponto específico evidenciado>

## Evidências Consultadas
- <comandos rodados, arquivos lidos, issues/PRs consultados>

## Limitações da Medição
- <dados ausentes, gh indisponível, testes não rodados, integração real não verificada>
```

Se o projeto ainda não tiver implementação suficiente, o scorecard deve dizer isso claramente. Um scorecard honesto com `sem dado` é melhor que uma pontuação fabricada.
