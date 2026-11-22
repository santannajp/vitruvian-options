# Vitruvian Options

## Ideia e decisões de produto

Uma aplicação para operar minhas estratégias de opções de Bitcoin em um só lugar. Quero abrir o radar, entender por que uma estrutura apareceu, ver quanto custaria montá-la na Derive ou na Deribit e acompanhar o que acontece depois da entrada. A mesma posição reúne suas pernas, resultado, regras de rolagem e, quando houver um perpétuo vinculado, a proteção contratada.

**Primeira versão.** Será de uso pessoal. O radar parte do BTC depositado como garantia na Aave e respeita três objetivos, nesta ordem: proteger o colateral, buscar rendimento líquido e reservar espaço para apostas direcionais. As primeiras travas que quero encontrar são de alta e de baixa em BTC, tanto a débito quanto a crédito. Derive e Deribit entram desde o início como fontes de mercado ao vivo. Entradas, ajustes e saídas acontecem em uma carteira simulada. O saldo inicial é virtual e configurável.

**Evolução.** A visão inclui montagem manual ou assistida, monitoramento contínuo, rolagem automática e seguro dinâmico para perpétuos de BTC. Caso o produto ganhe planos comerciais, o radar estará incluído em todos eles.

## A experiência começa no radar

### Minha carteira e a ordem das decisões

Compro BTC e uso diferentes tokens que o representam como garantia na Aave. Meu caso mais frequente é WBTC na rede Ethereum. Também posso usar ativos como L-BTC, cirBTC e cbBTC. Tomo os empréstimos sempre em stablecoins, entre elas USDC, USDT e frxUSD. Costumo operar com health factor (HF) entre 1,98 e 2,04. Uma parte do empréstimo financia o grid e outra financia as opções. Se os depósitos que escolhi proteger representam juntos 1 BTC, uso esse 1 BTC inteiro como referência para avaliar a proteção. O orçamento disponível para comprar a proteção é uma variável separada.

**1. Proteger o colateral.** Se houver liquidação na Aave durante a vigência do seguro, quero terminar com a mesma quantidade de BTC equivalente que tinha em garantia imediatamente antes do evento. As opções devem cobrir a diferença entre essa quantidade e o que consigo conservar ou recomprar com o saldo restante, já considerados prêmios e custos. O preço de liquidação estimado na compra serve para simular o seguro. A quantidade de BTC perdida e o custo de reposição dependem do que acontecer no evento.

**Conta de reposição.** Apurar o BTC equivalente que permaneceu em garantia e o caixa livre restante que destinei à recompra. Converter esse caixa em BTC pelo preço de compra disponível para o tamanho necessário. A meta líquida das opções, em BTC, é `máx(0, BTC protegido antes da liquidação − BTC que permaneceu − BTC comprável com o caixa destinado à reposição)`. Para chegar ao recebimento bruto necessário, incluir prêmio líquido de eventuais rolagens, taxas e custos de conversão ainda não refletidos nos saldos ou no preço usado. Registrar cada custo uma única vez. Mostrar a dívida remanescente em stablecoins e o HF após o evento. A métrica principal mede BTC recomposto, incluindo a parte que segue empenhada. Para simular a retirada de todo o BTC livre de dívida, calcular também o desembolso para quitar o empréstimo restante.

**Exemplo ilustrativo.** Havia 1 BTC protegido. Após a liquidação, restaram 0,45 BTC em garantia, e o caixa livre destinado à reposição compra mais 0,05 BTC. Faltam **0,50 BTC líquidos** das opções. Se o prêmio e os custos equivalerem a 0,02 BTC e ainda não estiverem refletidos nesses valores, o recebimento bruto necessário é **0,52 BTC**. O bônus de liquidação já está refletido nos 0,45 BTC que sobraram. A dívida abatida pelo liquidante reduz o passivo e não entra como caixa disponível para comprar BTC.

Para cotar o seguro, estimar o saldo remanescente com os parâmetros da versão e do mercado da Aave, os ativos envolvidos e a dívida amortizada em cada cenário. O protocolo pode permitir a liquidação de até toda a dívida em determinadas condições. A parcela da dívida liquidada e a quantidade de colateral retirada são grandezas distintas. Após uma liquidação observada, reconciliar os saldos efetivos de garantia e dívida. Se houver liquidações sucessivas, acumular as perdas e recompras da mesma posição protegida e atualizar quanto falta para a meta original, ajustada por depósitos e retiradas voluntários. [Liquidações na Aave](https://aave.com/help/borrowing/liquidations) · [Mecanismo da Aave V4](https://aave.com/docs/aave-v4)

Para a primeira simulação, cada conta, rede e mercado da Aave terá sua própria lista de garantias e dívidas. Identificar cada token pela rede e pelo endereço do contrato e conferir sua disponibilidade e função no mercado selecionado. Para cada garantia, guardar a quantidade depositada, o valor equivalente em BTC, o preço do oráculo e o limite de liquidação aplicável. Para cada dívida, guardar a stablecoin, o saldo com juros acumulados e seu preço de referência. Registrar à parte o caixa livre e os valores comprometidos no grid, no prêmio e na margem das opções. Mostrar origem e horário dos dados e identificar estimativas manuais.

O painel pode somar a exposição em BTC dos depósitos escolhidos para o seguro. Calcular um HF para o conjunto de garantias e dívidas que a Aave avalia em conjunto naquela conta e mercado. Quando vários ativos compõem a posição, estimar o preço-alvo do BTC no qual o HF atinge 1 sob premissas explícitas para cada cotação token/BTC e stablecoin/USD. Salvar essas premissas junto ao alvo do seguro. Assim, posso conferir o que muda se um dos colaterais perder valor frente ao BTC ou se uma moeda da dívida se afastar de US$ 1. [Como a Aave avalia posições com vários ativos](https://aave.com/faq)

Exemplo de estresse para dimensionar a reserva: com um único colateral que acompanhe o BTC, dívida estável em dólares, HF inicial de 2,00 e parâmetros constantes, uma queda imediata de 20% leva o HF a 1,60. Nesse cenário, amortizar 20% do saldo devedor o traria de volta a 2,00. A simulação também deve admitir que a cotação da opção e o oráculo da Aave divirjam, que a dívida acumule juros e que uma transferência atrase. O caixa já acessível na rede tem valor operacional diferente de um ganho ainda aberto na exchange. [Cálculo do HF na Aave](https://aave.com/faq)

Para medir o hedge econômico, comparar a carteira sem opções com duas alternativas sobre o mesmo nominal e vencimento. Uma **put comprada** compensa, no vencimento, a queda abaixo do strike sobre a quantidade coberta, conforme o contrato. O custo inclui prêmio, taxas e futuras renovações. Uma **trava de baixa a débito** vende uma put de strike inferior para reduzir o prêmio. A compensação adicional termina nesse segundo strike e o colateral continua perdendo valor numa queda mais profunda. Mostrar cenários abaixo das duas pontas, inclusive antes do vencimento, usando ofertas disponíveis para simular uma saída antecipada. Informar moeda de liquidação, índice e eventual diferença entre o token em garantia e o BTC de referência. [Put protetora](https://www.optionseducation.org/strategies/all-strategies/protective-put-married-put) · [Trava de baixa com puts](https://www.optionseducation.org/strategies/all-strategies/bear-put-spread) · [Exemplo de liquidação em USDC na Deribit](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)

**Como dimensionar a compra.** Para cada cenário de liquidação, projetar o BTC que faltará para a reposição. Testar quantidades de contratos permitidas pela exchange e calcular quanto cada estrutura entrega depois dos custos para aquele tamanho. Na Deribit, uma put inversa sobre 1 BTC tem recebimento bruto no vencimento de `máx(strike − preço de liquidação da opção, 0) / preço de liquidação da opção` em BTC. Antes do vencimento, usar uma estimativa de venda antecipada. O cartão mostra o prêmio exigido, quanto BTC o seguro consegue repor e a eventual insuficiência de cobertura. [Especificação das opções inversas da Deribit](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)

**Se o preço apenas tocar o alvo.** O toque aciona uma atualização da simulação e das ofertas disponíveis. A apuração do BTC a repor depende de uma liquidação na Aave. Uma put europeia pode ser vendida antes do vencimento pelo preço disponível no livro. Simular a venda para o tamanho inteiro, os custos e a conversão em BTC quando o contrato pagar em outra moeda. Exibir a diferença entre o valor projetado do seguro e o valor realizável para recompra naquele momento. [Exercício e saída antecipada na Deribit](https://support.deribit.com/hc/en-us/articles/31424939096093-Inverse-Options)

**2. Rentabilizar.** Comparar manter a carteira protegida com acrescentar uma trava. Medir o resultado incremental depois de custos e o retorno da carteira depois de juros do empréstimo, taxas, prêmio e renovações, contabilizando cada fluxo uma vez. Identificar onde a operação também perde quando o BTC cai, como na trava de alta a crédito com puts. O BTC empenhado na Aave permanece indisponível como margem na exchange. Prêmio de venda entra no caixa acompanhado da obrigação da opção até seu encerramento.

**3. Fazer apostas mais arriscadas.** Reservar um orçamento próprio de perda máxima para teses de alta ou baixa. Como proposta, o radar só disponibiliza esse saldo após reservar o caixa de amortização e o custo de proteção escolhidos. Lucros projetados do grid ficam fora do saldo disponível. Se o grid acumular BTC durante a queda, mostrar essa exposição adicional ao lado do 1 BTC em garantia, para que eu possa decidir se também quero cobri-la. Se uma aposta competir com a proteção, o radar mostra a insuficiência em moeda e o cenário que a revelou.

### Da carteira à entrada simulada

1. Posso ver todas as travas ou combinar dois filtros independentes. Um seleciona a direção (alta ou baixa) e o outro, a forma de entrada (débito ou crédito). Escolho o tamanho que pretendo operar, os vencimentos de interesse e meu limite de risco. Posso ver as duas exchanges lado a lado ou filtrar por uma delas.
2. O radar busca combinações nos instrumentos disponíveis. Cada sugestão identifica a exchange, os contratos e seus lados, o horário da cotação, o débito ou crédito líquido estimado e o score de 0 a 100. Posso abrir a composição da nota.
3. No detalhe da trava, vejo os dois strikes, o livro de ofertas para o meu tamanho, as taxas estimadas e o capital necessário. Posso indicar um preço-alvo para o BTC e ver o resultado estimado no vencimento se o preço de liquidação atingir esse alvo, ficar entre os strikes ou terminar fora deles.
4. Ao escolher **Simular entrada**, o sistema consulta novamente as ofertas. Se o preço piorar além do limite que defini, a proposta expira e o diário guarda o motivo. Se houver execução simulada, acompanho a estratégia até a saída ou o vencimento.
5. Depois, comparo o preço sugerido com o preço simulado, a evolução do PnL e o efeito das rolagens. O histórico conserva também as oportunidades que deixei passar, com o score e os dados conhecidos naquele instante.

### Primeiras entradas — travas direcionais de BTC

Cada trava reúne duas opções de BTC do mesmo tipo, vencimento e especificação contratual, na mesma exchange. As pernas têm strikes diferentes e quantidades iguais, uma comprada e outra vendida. Desde a estreia, o radar procura as quatro combinações descritas abaixo.

| Direção | Variante de débito (pago para entrar) | Variante de crédito (recebo para entrar) |
| --- | --- | --- |
| Alta | Comprar a call de strike menor e vender a call de strike maior. | Vender a put de strike maior e comprar a put de strike menor. |
| Baixa | Comprar a put de strike maior e vender a put de strike menor. | Vender a call de strike menor e comprar a call de strike maior. |

O cartão de cada trava mostra o valor líquido de entrada para o tamanho escolhido, o ponto de equilíbrio no vencimento e o ganho e a perda máximos quando definidos na moeda de referência indicada. Para comparar Derive e Deribit, o radar usa o mesmo tamanho de exposição em BTC e identifica diferenças de strike, vencimento e liquidação que afetam a comparação. A nota classifica a qualidade da entrada para a direção selecionada.

### Como interpretar o score

O score mede a adequação de uma estrutura ao objetivo escolhido. Para proteção, o primeiro critério é quanto a estrutura reduz a perda da carteira nos cenários definidos, com ênfase em quanto falta para recompor o BTC anterior à liquidação após custos e no risco residual abaixo do strike inferior de uma trava. Para rendimento, é o resultado incremental líquido frente à carteira já protegida. Para apostas, é a aderência à tese dentro do orçamento de perda. O ranking compara candidatas do mesmo objetivo, tamanho e horizonte, e mantém a prioridade da proteção mesmo quando uma aposta recebe nota superior. Posso consultar os fatores, pesos e versão da fórmula. O OpsRadar da Opsbit é a referência para o fluxo de descoberta. [Descrição do OpsRadar](https://www.opsbit.app/opsradar/)

Antes de pontuar, verificar se existem ofertas recentes no lado necessário de cada perna, profundidade para o tamanho solicitado e margem simulada suficiente. Um candidato excluído permanece consultável com seu motivo. Entre os elegíveis, a nota combina três fatores normalizados de 0 a 100, com pesos cuja soma é 100%.

| Fator | O que o operador consegue conferir |
| --- | --- |
| Liquidez | Diferença entre compra e venda, profundidade disponível e impacto de executar o tamanho escolhido. |
| Custo e retorno potencial | Prêmio líquido de taxas e resultado nos cenários da estratégia em relação ao capital comprometido. |
| Aderência ao perfil | Distância dos strikes, prazo, exposição direcional e perda nos cenários escolhidos em relação aos limites configurados. |

Exemplo fictício de leitura do ranking, com pesos ilustrativos de 40%, 35% e 25% respectivamente. Uma estrutura com notas 90, 70 e 80 recebe **80,5/100**. Se desaparecer a oferta de uma das pernas, o cartão passa a indicar qual cotação falta e deixa o ranking de entradas disponíveis. Pesos, escalas e cortes serão calibrados com o histórico das simulações.

## Catálogo de estratégias

O catálogo de referência tem dez estratégias. As travas de alta e de baixa estreiam no radar. A tabela descreve também as demais estruturas previstas para o montador. [Funcionalidades da Opsbit](https://www.opsbit.app/features/)

| Estratégia | O que montar ou acompanhar |
| --- | --- |
| Trava calendário | Opções do mesmo tipo e strike, com vencimentos diferentes e lados opostos. Identificar qual perna vence primeiro. |
| Trava calendário diagonal | Opções do mesmo tipo com strikes e vencimentos diferentes. Avaliar a exposição restante ao rolar a perna curta. |
| Call a seco | Compra isolada de call para exposição à alta. Mostrar prêmio, vencimento e ponto de equilíbrio na liquidação. |
| Put a seco | Compra isolada de put para exposição à queda. Mostrar prêmio, vencimento e ponto de equilíbrio na liquidação. |
| Seguro | Opção vinculada a um perpétuo de BTC. Dimensionar a cobertura a partir do sentido e do tamanho da posição. |
| Iron Condor | Combinar uma trava de puts e outra de calls no mesmo vencimento. Na variante de crédito, vender os strikes internos e comprar as pontas de proteção. |
| Trava de alta | Duas opções do mesmo tipo e vencimento, com strikes distintos, montadas para exposição à alta. Indicar se a entrada exige débito ou gera crédito. |
| Trava de baixa | Duas opções do mesmo tipo e vencimento, com strikes distintos, montadas para exposição à queda. Exibir os limites de ganho e perda na moeda de liquidação aplicável. |
| Straddle | Call e put de mesmo strike e vencimento. A variante comprada usa a amplitude do movimento para tentar superar o prêmio total. |
| Strangle | Call e put com strikes distintos no mesmo vencimento. Exibir a faixa entre strikes e o custo da combinação. |

A página também lista Butterfly, Collar e Condor como estratégias em implementação na Opsbit. Ficam como possibilidades futuras. Para call e put a seco, a interpretação inicial proposta é compra simples. Variantes vendidas exigem parametrização própria de exposição e margem.

## Rolagens que posso auditar

Cada estratégia tem uma regra legível antes da entrada. Nela defino o preço de referência, a distância ao alvo, os dias até o vencimento, quais pernas podem mudar, como escolher a substituta e qual crédito líquido mínimo aceito. Também defino teto de capital, perda acumulada e quantidade máxima de rolagens.

**Exemplo ilustrativo para uma perna vendida.** Avaliar a rolagem quando faltarem até três dias para o vencimento **ou** quando o índice de BTC estiver a até 2% do strike vendido. Recomprar a perna atual e vender a substituta somente se o crédito final atingir o mínimo configurado e os limites de margem e risco continuarem atendidos. Um gatilho torna a posição candidata à rolagem. A cotação determina se ela pode prosseguir.

Se a recompra custar 120, a nova venda render 145 e as taxas somarem 8, o crédito estimado é 17, todos na mesma moeda. Com mínimo de 20, a carteira mantém a posição e registra a diferença. O histórico guarda regra e versão, valores observados, ordens simuladas, quantidades efetivamente preenchidas e posição resultante. Uma reconexão não pode duplicar a rolagem.

## Seguro dinâmico para o BTC perpétuo

Seleciono um perpétuo simulado, o percentual da posição a proteger, o horizonte e o orçamento de prêmio. Para um perpétuo comprado, o sistema cota puts de proteção. Para um vendido, cota calls. O tamanho leva em conta a exposição em BTC e o multiplicador de cada contrato. A primeira proposta mantém proteção e perpétuo na mesma exchange e subconta simulada.

| Modo | Regra proposta para cotar o seguro |
| --- | --- |
| Próximo ao preço | Buscar o strike disponível mais próximo do índice de referência. |
| Sensibilidade fixa | Buscar a opção cujo delta absoluto mais se aproxima do alvo escolhido. |
| Distância percentual | Buscar um strike à distância percentual escolhida, abaixo do índice para a put ou acima para a call. |

O painel mostra o prêmio de entrada, o custo líquido de renovar, a cobertura em BTC e o resultado combinado em cenários de preço, com e sem a opção. Recalcula a cobertura ao mudar o tamanho do perpétuo, ao sair da faixa de tolerância ou ao se aproximar o vencimento. Se o orçamento impedir a renovação, exibe quanto segue protegido e até quando. O risco de liquidação do perpétuo continua visível, inclusive antes do vencimento da opção.

## Mercado ao vivo e carteira simulada

- **Derive.** Ler instrumentos de BTC, livros e atualizações por WebSocket. Para uma futura execução, a integração deverá respeitar a assinatura de ordens e os escopos da chave de sessão. [Negociação na Derive](https://docs.derive.xyz/trading/order-types) · [Escopos de acesso](https://docs.derive.xyz/authentication/access-scopes)
- **Deribit.** Carregar os instrumentos listados e acompanhar livros, preços de marcação e gregas pelos canais públicos. A documentação distingue tamanhos das opções e dos perpétuos. Cada cálculo deve usar a especificação do instrumento. [Dados de opções](https://docs.deribit.com/articles/options-data-collection-best-practices) · [API da Deribit](https://docs.deribit.com/)
- **Comparação.** Conservar moeda de cotação, multiplicador, colateral, liquidação e taxas de cada contrato. Exibir valores nativos e conversão em USD com horário de referência. Cada estrutura usa as pernas e a margem de uma única exchange.
- **Simulação.** Consumir ofertas de venda para uma compra e ofertas de compra para uma venda, até o tamanho disponível. Registrar taxa, preço médio e preenchimentos por perna. Se apenas parte da estrutura preencher, exibir a exposição residual e suspender novas rolagens até reconciliá-la. A marcação serve para acompanhar o valor da posição. O custo estimado de saída vem do livro.
- **Acompanhamento.** Atualizar sem recarregar a tela os preços, as posições e o PnL realizado e em aberto, discriminando taxas e pagamentos de funding do perpétuo. Manter uma visão por estratégia, rolagem e exchange. Mostrar a hora da última atualização de cada fonte.
- **Interrupções.** Se o fluxo de uma exchange ficar desatualizado, sinalizar o último valor conhecido e suspender as entradas e rolagens afetadas. Retomar após reconstruir o livro e conferir o estado da carteira simulada. A outra exchange continua disponível.

## Como validar a primeira versão

Começar pelo caso habitual de WBTC no Ethereum e dívida em stablecoin. Repetir com duas garantias que somem 1 BTC equivalente e duas dívidas em moedas diferentes no mesmo mercado simulado. Alterar apenas a cotação de uma stablecoin e conferir que o saldo em unidades dessa moeda permanece igual, enquanto o valor da dívida, o HF e o preço de liquidação projetado mudam. O alvo salvo na compra do seguro continua disponível para comparação.

Com um depósito simulado equivalente a 1 BTC, lançar a dívida e a divisão de caixa entre grid e opções uma única vez. Comparar três carteiras no mesmo cenário de queda: sem hedge, com put comprada e com trava de baixa a débito. A tela deve mostrar o valor econômico de cada carteira e o mesmo HF nas três enquanto o saldo da Aave for idêntico. Depois de simular uma amortização, conferir o novo HF e a redução correspondente de caixa. Repetir com o BTC abaixo do strike inferior da trava para verificar a perda que segue descoberta. Testar uma trajetória que toca o preço-alvo e se recupera antes do vencimento e outra que vence nesse preço. Distinguir toque sem liquidação, liquidação parcial e cenário em que toda a dívida é liquidada. Em cada evento, conferir o BTC conservado, o BTC recomprável com o caixa disponível, a dívida restante e o valor líquido das opções. No exemplo de 1 BTC com 0,45 BTC conservado e caixa para mais 0,05 BTC, o simulador deve exigir 0,50 BTC líquidos e contar cada custo apenas uma vez.

O primeiro marco deve completar um ciclo em carteira simulada para cada uma das quatro entradas previstas na tabela acima. Em cada ciclo, consigo comparar as sugestões da Derive e da Deribit quando houver ofertas elegíveis, abrir a memória de cálculo do score, simular as duas pernas e acompanhar o resultado até o encerramento. Quando nenhuma trava atende aos filtros, consigo identificar se faltou uma oferta, se o custo ultrapassou meu limite ou se outra regra eliminou a candidata.

Para avaliar se o radar merece orientar minha rotina, o diário mede quantas sugestões ainda eram executáveis ao abrir o cartão, a diferença entre preço indicado e simulado e o resultado líquido por família e faixa de score. A amostra inclui perdas, propostas expiradas e saídas no vencimento. Depois desse primeiro ciclo, entram os demais modelos do catálogo, as regras de rolagem por família e a comparação do perpétuo com e sem seguro. Alertas de vencimento, falha de cobertura e rolagem podem ganhar Telegram ou e-mail conforme o uso.

Antes de transformar o simulador em executor com capital real, será preciso decidir quais ações exigem confirmação e quais podem ser delegadas por estratégia. Essa evolução terá validação separada para cada exchange.
