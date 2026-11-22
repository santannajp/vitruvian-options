---
description: Roda o gate local de validação do projeto e reporta lacunas sem inventar ferramentas ausentes.
---

# /validar — Gate Local do MVP

Valide o estado atual do projeto antes de considerar uma fatia pronta.

Entrada opcional do usuário: `$ARGUMENTS`

Use os argumentos para limitar a validação a uma issue, PR, branch, arquivo, módulo ou fatia quando isso estiver claro. Se nada for informado, valide o estado local completo que for razoável para o tamanho atual do repo.

## Fontes de Verdade

Antes de validar, considere:

- `idea.md`: PRD do MVP da camada de dados financeiros.
- `ideia.md`: visão arquitetural e princípios de longo prazo.
- `pyproject.toml`: ferramentas Python realmente configuradas.
- Estado do git: mudanças staged, unstaged e arquivos não rastreados.

Não assuma que existem `backend/`, hooks, ruff, mypy, pytest, CI ou diretórios de código. Este repositório ainda pode estar em skeleton.

## Sequência de Validação

1. Rode `git status --short` para identificar o que está sendo validado.
2. Leia `pyproject.toml` para descobrir dependências e ferramentas configuradas.
3. Se houver código Python, localize a estrutura real do projeto e os testes existentes.
4. Rode apenas comandos que façam sentido para o estado atual:
   - `uv run ruff check .` se `ruff` estiver configurado ou instalado no ambiente do projeto.
   - `uv run mypy .` se `mypy` estiver configurado ou instalado no ambiente do projeto.
   - `uv run pytest -q` se houver testes e `pytest` estiver configurado ou instalado.
   - Comandos específicos do projeto se existirem scripts/documentação indicando o gate correto.
5. Se uma ferramenta esperada não existir, não trate como falha de código; reporte como lacuna de setup.
6. Se uma validação falhar por problema real da mudança, corrija quando for seguro e dentro do escopo. Se a correção exigir decisão de produto/arquitetura, pare e explique o bloqueio.
7. Nunca rode testes de integração real com Hyperliquid por padrão. Eles devem ser opcionais ou explicitamente solicitados.

## Checks de MVP

Além dos gates técnicos, verifique se a fatia tocada não viola os invariantes do projeto:

- Provider independence: formato bruto da Hyperliquid deve ficar isolado no adapter/normalizer.
- Canonical first: consumidores internos devem depender de OHLCV canônico, não de payload raw.
- Raw before transformation: eventos/candles do provider devem ser preservados antes de normalizar.
- Instrument identity: não tratar `BTC` como identificador universal.
- UTC internamente: timestamps internos em UTC.
- Historical e realtime separados: backfill e stream não devem ficar acoplados de forma rígida.
- Idempotência: reexecução de backfill/overlap não pode duplicar `instrument_id + timeframe + timestamp`.
- Data quality mínima: duplicatas, gaps, ordem temporal e consistência OHLC devem ser validáveis.
- Query local: consulta interna não deve chamar Hyperliquid.
- Fora do escopo: não exigir Deribit, IBKR, Kalshi, UI, API HTTP, indicadores, modelos ou estratégias no MVP.

## Resultado Esperado

Responda em português com um relatório curto:

```text
Veredito: verde | amarelo | vermelho

Comandos rodados
- <comando> — passou/falhou/não aplicável

Problemas encontrados
- <arquivo:linha, se houver> — <problema e correção feita ou necessária>

Lacunas de setup
- <ferramenta/teste/configuração ausente, se houver>

Checks de MVP
- <invariante relevante> — ok/risco/não aplicável

Próximo passo
- <ação mínima para deixar a fatia pronta>
```

Critério de prontidão:

- `verde`: gates aplicáveis passaram e não há violação relevante do PRD.
- `amarelo`: não há falha concreta, mas faltam ferramentas, testes ou evidência.
- `vermelho`: gate aplicável falhou ou há violação de invariante do MVP.

Não declare a tarefa pronta se os testes essenciais da fatia não existem ou não foram rodados por falta de setup. Nesse caso, use `amarelo` ou `vermelho` conforme o risco.
