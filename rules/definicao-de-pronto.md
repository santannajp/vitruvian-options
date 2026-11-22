---
# Regra transversal: define o que conta como entregue no projeto.
paths:
  - "**"
---

# Definição De Pronto — MVP Da Camada De Dados

Esta regra define quando uma fatia pode ser considerada entregue. Ela torna a execução mensurável: `/validar` verifica o estado local e `/scorecard` mede aderência ao PRD, arquitetura, qualidade de dados e prontidão do MVP.

O projeto não considera uma entrega pronta só porque o código roda no caminho feliz. A entrega precisa preservar os invariantes da plataforma unificada de dados financeiros.

## Toda Issue Deve Ter Critérios De Aceite

Toda issue implementável deve declarar critérios de aceite testáveis.

Critério bom:

- `backfill` persiste raw e canonical OHLCV para BTC perpetual no timeframe `1m` em SQLite temporário.
- `query` retorna candles canônicos ordenados por timestamp sem chamar Hyperliquid.
- Reexecutar backfill no mesmo período não aumenta a quantidade de candles canônicos duplicados.

Critério ruim:

- melhorar a ingestão;
- deixar a arquitetura mais robusta;
- suportar mercado cripto;
- preparar para o futuro.

O que não é verificável não é critério de aceite.

## Uma Fatia Só Está Pronta Quando

Todos os itens aplicáveis abaixo devem estar satisfeitos.

1. Critérios de aceite atendidos com evidência.
2. `/validar` retorna `verde`, ou `amarelo` apenas quando a lacuna é de setup já documentada e não afeta a fatia.
3. `revisor-codigo` não encontra bloqueantes abertos.
4. Invariantes do PRD e das rules foram respeitados.
5. Testes essenciais da fatia existem e rodam sem depender de rede externa.
6. Decisões arquiteturais contestáveis foram registradas em documentação ou ADR antes de virar precedente.
7. Nenhum segredo, credencial, token ou endpoint privado foi hardcoded ou commitado.
8. O escopo não cresceu para itens fora do MVP sem issue/PRD explícito.

## Invariantes Que Bloqueiam Entrega

Qualquer violação abaixo deixa a fatia não pronta:

- Provider independence quebrado: código fora do adapter/normalizer depende do formato bruto da Hyperliquid.
- Canonical first quebrado: consumidor interno usa payload raw como modelo de produto.
- Raw before transformation quebrado: ingestão transforma ou descarta dado sem preservar payload original quando deveria preservar.
- Instrument identity quebrado: `BTC` ou outro símbolo é usado como identificador universal.
- UTC quebrado: timestamp interno fica sem normalização clara para UTC.
- Historical/realtime acoplados: backfill e stream não conseguem evoluir ou ser testados separadamente.
- Idempotência quebrada: reexecução cria duplicatas em `instrument_id + timeframe + timestamp`.
- Query local quebrada: consulta interna chama provider externo.
- Data quality mínima ausente em fatia que deveria validá-la.
- Estudos, indicadores, modelos, estratégias, API HTTP ou UI entram no MVP sem escopo explícito.

## Gates Técnicos

O gate técnico é o que existir de fato no projeto.

Use `/validar` como comando operacional. Ele deve:

- checar estado do git;
- ler `pyproject.toml`;
- rodar `ruff`, `mypy` e `pytest` apenas quando estiverem configurados ou disponíveis;
- reportar lacunas de setup sem fingir que o projeto tem CI/gate completo;
- nunca exigir teste real de Hyperliquid como parte do CI comum.

Quando o projeto amadurecer e ferramentas forem configuradas, o padrão esperado passa a ser:

- lint sem erros;
- typecheck sem erros relevantes;
- testes automatizados passando;
- testes de integração real marcados como opcionais/manual quando dependerem de rede.

Não feche fatia vermelha. Não esconda teste quebrado como lacuna de setup.

## Evidência De Aceite

Cada critério de aceite deve apontar para pelo menos uma evidência:

- teste automatizado;
- comando local com saída relevante;
- fixture/dataset que demonstra o caso;
- consulta em SQLite temporário;
- screenshot/log somente quando não houver forma melhor;
- explicação explícita de por que algo é `N/A`.

Para o MVP, evidências fortes incluem:

- testes de normalização com payloads da Hyperliquid;
- testes de storage com SQLite temporário;
- teste de idempotência de backfill/overlap;
- teste de realtime com eventos simulados;
- teste de `query` sem chamada externa;
- teste de `validate` com duplicatas, gaps, timestamps fora de ordem e OHLC inconsistente.

## Definição De Pronto Por Tipo De Fatia

### Modelo Canônico

- Entidade representa linguagem do domínio, não formato de provider.
- Timestamps são UTC.
- Identidade de instrumento não depende de símbolo universal.
- Tipos preservam precisão de preço e volume.
- Testes cobrem construção, serialização ou persistência relevante.

### Provider / Adapter

- Isola detalhes do provider.
- Não vaza campos brutos para consumidores internos.
- Tem fake ou fixture para teste sem rede.
- Trata erro de provider de forma explícita.
- Respeita limites documentados do provider.

### Raw Data / Normalização

- Payload original é preservado.
- Normalização gera canonical independente do provider.
- Falhas de normalização não corrompem canonical data.
- Testes cobrem payload válido, payload inválido e campos inesperados quando relevante.

### Storage

- Usa SQLite local no MVP.
- Escritas canônicas são idempotentes.
- Chaves únicas protegem contra duplicata.
- Consultas retornam ordenação determinística.
- Testes usam SQLite temporário.

### Realtime / Backfill

- Fluxos continuam separáveis.
- Retomada com overlap não duplica dados.
- Canonical persiste apenas candles fechados.
- Long timeframes são testados por simulação quando a espera real for impraticável.

### Data Quality

- Detecta duplicatas, gaps, ordem temporal e inconsistência OHLC.
- Reporta problemas de forma legível.
- Não promete reconciliação avançada fora do MVP.

### CLI / Interface Programática

- Comando roteia entrada, chama serviço e formata saída.
- Não concentra regra de negócio no parsing de argumentos.
- Reporta progresso, contagens e erros.
- `query` lê storage local.

## ADRs E Decisões

Registre ADR quando uma decisão for difícil de mudar depois ou tiver alternativas plausíveis, por exemplo:

- trocar SQLite por outro storage primário;
- adicionar API HTTP ao MVP;
- mudar contrato de adapter;
- alterar chave única de OHLCV;
- permitir múltiplos providers no MVP;
- colocar LLM/agente no fluxo de dados;
- mudar semântica de candle fechado/parcial.

Não crie ADR para detalhe trivial de implementação.

## Delivery Record

Se existir estrutura de métricas do projeto, registre uma linha por issue entregue com:

- issue;
- critérios de aceite;
- comandos de validação rodados;
- resultado do revisor;
- lacunas conhecidas;
- decisão de pronto.

Enquanto `metrics/` ou schema equivalente não existir, não invente arquivo. Declare a ausência como lacuna no `/scorecard` quando relevante.

## Sinais Lagging

Sinais medidos depois da entrega devem ser registrados, não escondidos:

- issue reaberta;
- bug aberto contra issue já entregue;
- mudança pedida em review humano;
- teste flakey ou integração real quebrada;
- provider mudou schema/limite e quebrou ingestão.

Esses sinais servem para melhorar harness, rules, testes e critérios de aceite. Não otimize para vaidade como número de commits, linhas de código ou volume de arquivos.

## Regra De Fechamento

Se uma fatia não tem evidência, ela não está pronta.

Se uma fatia passa no caminho feliz mas viola arquitetura, ela não está pronta.

Se uma fatia depende de rede externa para provar comportamento básico, ela não está pronta.

Se uma fatia amplia o escopo do MVP sem decisão explícita, ela não está pronta.
