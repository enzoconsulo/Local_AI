# Especificação — ia-hibrida-limpa

## Objetivo
`ia-hibrida-limpa` é o ecossistema de Data Warehouse + "Conselho de Administração IA" que
Enzo usa para tocar sua loja Shopee de impressão 3D sob demanda. O app principal
(`Local_AI/analista_dados_shopee/`, Streamlit) sincroniza catálogo/pedidos/repasse da API
Shopee v2, importa planilhas do Seller Center, calcula lucro líquido real por variação e
roda auditorias de IA (CFO/CMO/COO via OpenAI) que recomendam e — para ações seguras —
executam mudanças na loja. Separado dele, `Local_AI/estudio_shopee/` é um módulo Streamlit
próprio para gerar fotos de produto com IA (remoção de fundo + edição via fal.ai).

Este documento registra a visão geral do sistema (baseada em `_gestao/ANALISE.md`, gerada
na importação do projeto) e detalha, com requisitos completos, a primeira função nova
planejada pela fábrica: **geração do anúncio completo (título + descrição + palavras-chave)
dentro do Estúdio**, a partir da foto final do produto.

## Usuários
Enzo — dono da loja e único usuário de todo o sistema. No Estúdio, ele sobe fotos/renders de
peças impressas em 3D, gera a imagem final tratada e hoje precisa sair da ferramenta para
escrever o título e a descrição do anúncio à mão (ou copiar a foto para outra IA de texto).
Quer terminar o fluxo do Estúdio já com um anúncio pronto para colar no Seller Center.

## Escopo
### Sistema (visão geral, já existente — não é objeto de tarefas desta rodada)
- Sincronização de catálogo, pedidos/escrow, saúde da conta e pós-venda via API Shopee v2;
  importação de planilhas do Seller Center (`workers/`).
- Cálculo de lucro líquido real por variação (material + taxas + refugo).
- Auditoria de IA por horizonte (7d/30d) com heurísticas determinísticas + OpenAI JSON mode,
  e execução de ações aprovadas (preço, promoção, combo) via `atuador.py`.
- Chat text-to-SQL somente-leitura sobre o Data Warehouse (`consultor.py`).
- Estúdio de imagens (`estudio_shopee/`): upload de foto(s), remoção de fundo (rembg/U2-Net),
  composição em canvas, geração de instrução de edição em inglês via LLM local
  (LiteLLM → Groq), edição da imagem via fal.ai, refinamento iterativo e aprovação/salvamento
  em `fotos_prontas/`. Tem também um "Modo Gratuito" (sem custo de API) que entrega a foto
  tratada + o prompt pronto para colar num app de IA de imagem grátis (Gemini/Meta AI/Copilot).

### Feature nova — Anúncio completo no Estúdio (objeto das tarefas desta rodada)
- Na aba "🎨 Gerador Automático" do Estúdio, assim que há uma imagem final selecionada
  (gerada pela IA e escolhida/aprovada pelo usuário), um botão dispara a geração do anúncio.
- A geração envia a IMAGEM FINAL (a mesma que será usada no anúncio) + o contexto textual do
  produto (nome, cor/material, estilo) para um modelo de IA com visão, que devolve:
  título otimizado para busca e conversão, descrição estruturada (abertura, benefícios,
  especificações visíveis, chamada para ação) e uma lista de palavras-chave sugeridas.
- Título e descrição aparecem em campos editáveis — o usuário pode ajustar antes de usar.
- Ao aprovar o catálogo (fluxo já existente), o anúncio (com eventuais edições manuais) é
  salvo junto do arquivo de imagem em `fotos_prontas/`.

## Fora de escopo
- Publicar o anúncio na Shopee via API (o `atuador.py` do app principal já executa ações de
  preço/promoção/combo, mas criar/editar o cadastro do anúncio em si é outra superfície da
  API Shopee, não coberta nesta rodada).
- Gerar anúncio a partir do fluxo "📋 Modo Gratuito" (ali a imagem final é gerada FORA do
  app, em outra ferramenta — não há imagem final disponível em bytes dentro do Estúdio para
  servir de entrada visual). Fica para uma iteração futura.
- Tradução do anúncio para outros idiomas.
- Geração de múltiplas variações de copy para teste A/B.
- Qualquer mudança no motor de geração/edição de IMAGEM já existente (fal.ai, rembg, canvas).
- Reescrever a especificação/arquitetura do sistema já existente (app principal) — coberto
  apenas na visão geral acima, com base em `_gestao/ANALISE.md`.

## Stack
Reaproveita a stack já em uso no Estúdio (`streamlit`, `Pillow`, `rembg`/U2-Net, `fal-client`,
`requests`, `python-dotenv`) e adiciona:

- **Cliente OpenAI REST direto via `requests`** (sem SDK), no mesmo padrão já usado pelo app
  principal em `Local_AI/analista_dados_shopee/cerebro/config.py`/`motor_ia.py` (JSON mode,
  parsing defensivo, sem dependências novas), mas com uma mensagem multimodal (texto +
  imagem em data URI base64) — formato nativo da API de chat completions que o projeto já
  fala.

Justificativa: o Estúdio já tem um LLM em uso (`chat-rapido`, via LiteLLM local apontando
para `groq/llama-3.3-70b-versatile`) para escrever a INSTRUÇÃO DE EDIÇÃO da imagem — mas esse
modelo só recebe TEXTO; ele nunca "vê" a foto, escreve a partir da descrição digitada pelo
usuário. O requisito desta feature é o oposto: o texto do anúncio precisa nascer OLHANDO para
a imagem final, então é obrigatório um modelo com entrada de imagem. Em vez de introduzir um
terceiro provedor/SDK só para isso, a opção mais simples é reusar o MESMO padrão de
integração que o app principal já usa e já paga (OpenAI REST direto, JSON mode) — só que
apontando para um modelo multimodal. Alternativa descartada: usar um modelo de visão hospedado
na Groq (mantendo tudo dentro do LiteLLM local já configurado no Estúdio) — descartada porque
não há precedente validado no projeto para modelos de visão na Groq via LiteLLM local, e a
oferta desses modelos muda com frequência; o padrão OpenAI REST direto já está provado em
produção no app principal.

Configuração nova: `OPENAI_API_KEY` (+ `OPENAI_MODEL_ANUNCIO` e `OPENAI_API_BASE_URL`,
opcionais) em `Local_AI/CHAVES.env` — arquivo PRÓPRIO do Estúdio (mesmo arquivo que já traz
`FAL_KEY`), mantendo o módulo independente do `analista_dados_shopee/CHAVES_DADOS.env` (cada
módulo com seu próprio arquivo de segredos, mesmo que a chave OpenAI copiada seja da mesma
conta nos dois — ver DECISOES.md).

## Requisitos funcionais
- RF-01: Com uma imagem final selecionada (`imagem_gerada_b64` setado) na aba "Gerador
  Automático", o usuário pode clicar em "Gerar Anúncio Completo" para disparar a geração.
- RF-02: A geração envia a imagem final (data URI base64, mesmo mecanismo já usado para a
  edição de imagem) + o contexto textual do produto (nome, cor/material, estilo escolhido) a
  um modelo de IA com capacidade de visão, via chamada HTTP direta (JSON mode).
- RF-03: O sistema recebe de volta, em JSON estruturado: `titulo` (otimizado para busca e
  conversão na Shopee), `descricao` (estruturada: abertura, benefícios, especificações
  visíveis, chamada para ação) e `palavras_chave` (lista de termos de busca sugeridos).
- RF-04: Título e descrição aparecem em campos editáveis, pré-preenchidos com o resultado da
  IA — o usuário pode ajustar manualmente antes de usar.
- RF-05: Título e descrição devem refletir o que a imagem mostra (produto, cor/material,
  estilo/cenário, ângulo) — não pode ser copy genérica desconectada da foto enviada.
- RF-06: Ao clicar em "✅ Aprovar Catálogo" (fluxo já existente), se houver um anúncio
  gerado, ele é salvo em `fotos_prontas/` junto da imagem (mesmo timestamp/versão), em um
  arquivo próprio — usando os valores ATUAIS dos campos editáveis (refletindo edição manual).
- RF-07: Falhas na chamada de IA (rede, chave ausente, resposta fora do schema esperado) são
  tratadas sem derrubar a aba — mensagem clara na UI; o resto do fluxo (edição/aprovação de
  imagem) continua funcionando normalmente.
- RF-08: A função de geração do anúncio (backend) é coberta por testes automatizados que NÃO
  dependem de uma chamada real e paga à API (mock/stub da chamada HTTP).

## Requisitos não-funcionais
- **Custo sob controle:** a chamada de geração de anúncio só acontece por ação explícita do
  usuário (botão) — nunca automática/silenciosa, no mesmo espírito do resto do Estúdio (que já
  mostra o custo estimado antes de gerar imagem).
- **Resiliência:** parsing de JSON tolerante e tratamento defensivo de erro, sem crash da UI
  Streamlit em caso de falha de rede/API — mesma linha do resto do projeto.
- **Independência de módulo:** a nova função não introduz dependência do `estudio_shopee` no
  `analista_dados_shopee` (nem vice-versa); cada módulo mantém seu próprio arquivo de
  segredos e suas próprias dependências.
- **Idioma:** título, descrição e palavras-chave são gerados em português (BR) — diferente do
  prompt de EDIÇÃO de imagem (que precisa ser em inglês para o motor fal.ai), o anúncio é
  para o comprador brasileiro na Shopee BR.

## Riscos
- Qualidade da copy depende do modelo configurado de fato suportar visão + seguir bem
  instruções em JSON mode; se `OPENAI_MODEL_ANUNCIO` apontar para um modelo sem entrada de
  imagem, a chamada falha — mitigado por RF-07 (tratamento de erro) e por deixar o modelo
  configurável via variável de ambiente.
- Limites de caracteres e caracteres especiais aceitos pela Shopee no título/descrição podem
  mudar; pesquisa feita nesta rodada indica título até 256 caracteres e descrição até ~5.000,
  mas o prompt deve pedir texto BEM abaixo desses limites (título ~120–150 caracteres,
  descrição objetiva) e evitar símbolos/emojis em excesso — a validação final de aceitação
  pelo Seller Center continua sendo responsabilidade do usuário ao colar o texto lá.
- Custo por chamada de visão pode ser maior que uma chamada de texto puro — mitigado por ser
  sob demanda (RNF acima) e por usar, por padrão, um modelo "leve" (mesma família de baixo
  custo/reasoning já usada no horizonte 7d do app principal).
