---
# Estilo de codigo Python. Carrega quando o agente toca codigo Python,
# testes ou configuracao de ferramentas Python.
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "vitruvian_project/**/*.py"
  - "backend/**/*.py"
  - "scripts/**/*.py"
  - "*.py"
  - "pyproject.toml"
---

# Estilo De Código — Python

O projeto usa Python 3.13 e deve priorizar código pequeno, tipado, testável e fiel à linguagem da camada de dados financeiros.

Estas regras valem para código de runtime e testes. Não assuma que hooks, ruff, mypy ou pytest já estão configurados; quando forem adicionados, o código deve passar limpo sem depender de autofix como muleta.

## Ferramentas

- Python alvo: `>=3.13`.
- Use `ruff` para format/lint quando estiver configurado.
- Use `mypy` para typecheck quando estiver configurado.
- Use `pytest` para testes quando estiver configurado.
- Não adicione configuração de ferramenta sem necessidade da fatia.
- Se configurar ruff/mypy/pytest, atualize `pyproject.toml` de forma explícita e mantenha `/validar` coerente.

## Tipagem

- Toda função pública deve ter type hints completos.
- Prefira tipos do domínio a `dict` solto quando a estrutura tem significado estável.
- Evite `Any`. Se for inevitável para payload bruto de provider, isole no adapter/raw boundary e documente o motivo.
- Prefira `X | None` a `Optional[X]`.
- Prefira coleções parametrizadas: `list[Candle]`, `dict[str, str]`, `Iterable[CanonicalOhlcv]`.
- Não use `type: ignore` sem justificativa local e específica.

## Imports E Módulos

- Use `from __future__ import annotations` no topo de módulos Python novos.
- Mantenha imports explícitos e sem efeitos colaterais de rede/storage no import.
- Evite inicializar cliente HTTP, WebSocket, banco ou config global pesada no import do módulo.
- Separe I/O de transformação pura para facilitar testes sem rede.

## Linguagem Do Domínio

Use nomes alinhados ao projeto. A linguagem principal do código pode ser inglês técnico, mas os conceitos de domínio devem ser consistentes.

Termos preferidos:

- `provider`
- `adapter`
- `raw_data`
- `normalizer`
- `canonical`
- `instrument`
- `instrument_id`
- `provider_symbol`
- `ohlcv`
- `timeframe`
- `historical`
- `realtime`
- `backfill`
- `overlap`
- `ingestion_run`
- `data_quality`

Evite sinônimos soltos para o mesmo conceito, como `ticker_id`, `asset_key`, `symbol_id`, `exchange_symbol` ou `market_blob`, salvo se houver decisão explícita.

## Provider Boundary

- Campos brutos da Hyperliquid (`t`, `T`, `o`, `h`, `l`, `c`, `v`, `s`, `i`) só devem aparecer no adapter, raw model, fixtures ou testes de normalização.
- Fora dessa fronteira, use nomes canônicos.
- Payload raw pode ser `dict[str, object]` ou tipo equivalente, mas não deve contaminar o modelo canônico.

## Precisão E Tempo

- Não use `float` para preço/volume se houver risco de perda de precisão relevante. Prefira `Decimal` ou representação explícita decidida pelo domínio.
- Timestamps internos devem ser timezone-aware ou normalizados de forma inequívoca para UTC.
- Não misture milissegundos epoch, segundos epoch e `datetime` sem conversão clara.
- Nomeie variáveis de tempo com unidade quando necessário: `timestamp_ms`, `start_time_ms`, `received_at`.

## Funções E Efeitos Colaterais

- Prefira funções pequenas e puras para normalização, validação e cálculo de chaves.
- I/O de rede, WebSocket, SQLite e filesystem deve ficar isolado e fácil de substituir por fake em teste.
- Não esconda chamada externa dentro de função que aparenta ser transformação pura.
- Não faça query ao provider em função chamada `query` da camada interna; query interna lê storage local.
- Erros esperados de provider, parsing e storage devem ser tratados explicitamente.

## Logging E Saída

- Em runtime, prefira `logging` a `print`.
- `print` é aceitável em CLI quando for a saída de usuário do comando.
- Logs devem ajudar depuração: provider, instrumento, timeframe, modo de ingestão, contagens e status.
- Logs não devem vazar segredos, tokens, headers sensíveis ou payloads grandes sem intenção explícita.

## Configuração E Segredos

- Não leia `os.environ` espalhado pela aplicação.
- Centralize configuração em módulo próprio quando a necessidade aparecer.
- Não hardcode API keys, tokens, credenciais, endpoints privados ou paths absolutos da máquina local.
- `.env` pode existir para desenvolvimento local, mas testes não devem depender dele.

## Testes

- Teste comportamento externo, não detalhes frágeis de implementação.
- Use fixtures pequenas e legíveis para payloads da Hyperliquid.
- Use SQLite temporário para storage.
- Use fakes/adapters simulados para realtime e backfill.
- Não faça teste unitário depender de rede externa.
- Marque testes de integração real com Hyperliquid como opcionais.
- Teste edge cases de tempo, duplicata, gap, candle parcial/fechado e OHLC inválido.

## Comentários E Docstrings

- Comentários devem explicar por que algo existe, não repetir o que o código faz.
- Docstrings curtas são úteis em funções públicas de domínio, adapters e validações.
- Não use comentário para justificar código confuso; simplifique o código quando possível.

## Simplicidade

- Não crie abstração genérica antes de haver necessidade concreta.
- Um contrato mínimo de adapter é desejado; uma framework multi-provider prematura não é.
- Não adicione compatibilidade retroativa sem dados persistidos, consumidores externos ou requisito explícito.
- Prefira a menor mudança correta que preserve os invariantes do PRD.
