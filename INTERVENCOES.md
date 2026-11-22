# Intervenções humanas pendentes

Registro consolidado do que ainda exige decisões, credenciais ou conferência do operador antes de conectar a aplicação a contas reais. O produto implementado neste marco é de consulta e execução simulada; não envia ordens autenticadas nem movimenta fundos.

## Antes de habilitar acesso privado às exchanges

- Criar chaves/API keys separadas por exchange e subconta, com permissões mínimas de leitura e negociação. Não habilitar saque/transferência. Guardar os segredos em um gerenciador de segredos e fornecer ao serviço por configuração segura; nunca commitar chaves no repositório.
- Definir quais subcontas Derive e Deribit serão consultadas e negociadas e validar autenticação, limites, expiração/revogação e política de rotação das chaves.
- Conferir com pequenas posições de teste os multiplicadores, moeda de prêmio, fees, margem, settlement e regra de quantidade mínima para cada instrumento/listagem. Particular cuidado com opções inversas liquidadas em BTC na Deribit e contratos perpétuos.

## Antes de operar a estratégia Aave com opções

- Informar/validar os mercados, redes, endereços e fatores de colateral dos tokens usados (WBTC, LBTC, cbBTC, cirBTC e demais), além da stablecoin de dívida e respectivos decimals. Símbolos iguais não bastam para identificar ativos on-chain.
- Aprovar os limites operacionais próprios: health factor mínimo e alvo, reserva de caixa, orçamento por estratégia, perda máxima e regras de pausa em falha de preço, API ou liquidez.
- Revisar o modelo de proteção contra liquidação usando o preço/valor efetivamente realizável do colateral e da dívida, custos de fechamento/liquidação da Aave, fees de opções e eventual diferença entre settlement teórico e a exchange. A cobertura simulada não é garantia de preservar BTC.

## Antes de automatizar ordens reais

- Revisar explicitamente permissões de cada estratégia, limites de exposição, slippage, tamanho máximo, confirmação manual e botão de interrupção.
- Validar o fluxo em testnet/paper trading e depois com valores mínimos, incluindo ordens parciais, reconnect, duplicidade/idempotência, cancelamentos, settlement, funding e contingência quando uma exchange estiver indisponível.
- Configurar monitoramento e alertas fora da aplicação para falha do processo, saldo/margem, ordens sem hedge e health factor. Confirmar responsável e canal de alerta.

Esses itens são intervenções registradas para uma revisão consolidada; nenhum deles bloqueia o desenvolvimento do simulador offline.
