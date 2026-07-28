# Pesquisa — Limites reais de título/descrição/palavras-chave na Shopee BR e restrição do schema do gerador de anúncio

Data: 2026-07-28

## Recomendação

**Não tente fixar um número "exato" de limite no prompt (ele já está razoável) — em vez disso,
adicione em `gerador_anuncio.py` um guardrail de tamanho NÃO FATAL (avisos, não exceção) em
`_validar_resposta_anuncio`/`gerar_anuncio_shopee`, com teto de segurança em 255 caracteres para
`titulo`, 5.000 caracteres para `descricao` (o menor entre os dois valores conflitantes
encontrados para descrição — nunca o maior) e um teto de contagem (não de plataforma, apenas de
usabilidade) de ~20 itens para `palavras_chave`. Não lance `ErroGeracaoAnuncio` por estouro de
tamanho: anexe um aviso e deixe passar, porque os campos já são editáveis pelo usuário antes de
usar (RF-04) e porque os limites reais da Shopee não puderam ser confirmados com certeza em uma
fonte primária única — descartar uma resposta paga da IA por um número que talvez nem esteja
certo é o pior dos dois mundos.**

Trade-off explícito: isso é mais frouxo do que "confiar cegamente" no número que a especificação
já assumia (256/~5.000) e mais seguro do que continuar sem NENHUM guardrail de código (situação
atual — ver abaixo). O custo é uma pequena complexidade extra (um campo `avisos` novo no dict de
retorno); o ganho é blindar o usuário contra um título/descrição absurdamente longo saído de uma
resposta de IA fora do padrão, sem arriscar jogar fora uma chamada paga por um limite que a
pesquisa não conseguiu confirmar com 100% de certeza.

## O que o código faz HOJE (ponto de partida)

Lido em `Local_AI/estudio_shopee/gerador_anuncio.py`:

- `PROMPT_SISTEMA_ANUNCIO` já orienta a IA por texto: título "120 a 150 caracteres" (cita
  "limite técnico da Shopee de ~256"), descrição "BEM abaixo do limite de ~5.000 caracteres",
  no máximo 1 emoji no título. Isso já está alinhado com a pesquisa (ver abaixo) — não precisa
  mudar o *conteúdo* da orientação de tamanho.
- `_validar_resposta_anuncio` (o schema de fato, em código) valida SOMENTE: `titulo` é string não
  vazia, `descricao` é string não vazia, `palavras_chave` é lista não vazia de strings não
  vazias. **Não há nenhum teto de tamanho nem de contagem em código** — se a IA devolver um
  título de 900 caracteres ou 80 palavras-chave, a validação atual aceita normalmente. O único
  guardrail de tamanho hoje é o texto do prompt, que a IA pode ignorar.
- `ESPECIFICACAO.md` (seção Riscos) já registra a mesma incerteza que esta pesquisa confirma:
  "pesquisa feita nesta rodada indica título até 256 caracteres e descrição até ~5.000 (...) a
  validação final de aceitação pelo Seller Center continua sendo responsabilidade do usuário".

## Pesquisa: o que dá para confirmar, e com que confiança

Aviso importante, como pedido: a Shopee BR **não publica um schema formal e estável de limites de
campo** em um lugar único e fácil de raspar — o Seller Education Hub e o Help Center oficiais
(`seller.shopee.com.br`, `help.shopee.com.br`) são SPAs renderizados em JS, então até ferramentas
de fetch automatizado só conseguem ver o `<title>` da página, não o conteúdo. O e-book oficial da
própria Shopee ("Boas práticas para criação de anúncios na Shopee", hospedado no CDN da Shopee em
`deo.shopeemobile.com`) existe e claramente é a fonte primária citada por quase todo mundo, mas é
um PDF majoritariamente vetorial/imagem que também não deu para extrair em texto com as
ferramentas disponíveis aqui. Por isso os números abaixo vêm de **integradores/ERPs brasileiros
com integração real via API Shopee** (Mainô, Anymarket) e de blogs de e-commerce BR que citam
literalmente o texto do e-book/Help Center oficial — não da doc oficial lida diretamente. Trate
os números como "convergência de fontes secundárias confiáveis", não como certeza absoluta.

### Título — confiança ALTA (convergência de 4 fontes independentes)
- **~255–256 caracteres** é o número que aparece repetido e consistente em: guia de integração
  Mainô (256), guia Anymarket/Freshdesk (256), codigoshop.com.br citando o texto oficial
  ("O limite é de 256 caracteres") e blog Destrave Escale (255) — a variação de 1 caractere entre
  as fontes é irrelevante na prática.
- Achado extra útil para o PROMPT (não é limite, é orientação de SEO): os **primeiros ~65
  caracteres** são os que aparecem "acima da dobra" nos resultados de busca da Shopee antes do
  "..." — 3 fontes independentes repetem esse número. Vale considerar orientar a IA a colocar o
  termo de busca mais importante nos primeiros 65 caracteres do título, não só respeitar o teto
  de 256. Isso é uma melhoria de qualidade de copy, não uma correção de bug — cito aqui só para
  registro, não faz parte da recomendação principal.

### Descrição — confiança MÉDIA, fontes conflitam de verdade
- Mainô (integrador com API real): **10.000 caracteres**.
- Anymarket/Freshdesk (outro integrador com API real): **5.000 caracteres**.
- Um blog não-BR citando "outra região" da Shopee: 3.000 caracteres (provavelmente Shopee
  SG/ID/PH/TH, que têm formulários e limites diferentes do BR — descartei como não aplicável).
- **Não há como resolver esse conflito com as fontes disponíveis aqui.** Como a ESPECIFICACAO.md
  já assumia ~5.000, e como usar o número MENOR entre dois confiáveis é a escolha mais segura
  (se o teto real for 5.000 e o código permitir até 10.000, o usuário só descobre o problema ao
  colar no Seller Center; se o teto real for 10.000 e o código avisar em 5.000, o pior caso é um
  aviso falso-positivo que o usuário ignora), mantenha 5.000 como teto de aviso.

### Palavras-chave — não é um campo do cadastro de produto (achado estrutural, não numérico)
- Em nenhuma fonte (Mainô, Anymarket, blogs de boas práticas, Help Center) aparece um campo
  "palavras-chave" no formulário de cadastro/edição de produto da Shopee BR — o formulário real
  tem nome, categoria, descrição, imagens/vídeo, preço, estoque, variações, peso/dimensões.
  "Palavras-chave" como conceito formal da Shopee vive em **Shopee Ads** (`ads.shopee.com.br`,
  busca paga) — a ferramenta de sugestão de palavras-chave dos Anúncios de Busca mostra até 30
  termos mais buscados por categoria.
- Implicação para o schema: `palavras_chave` no `gerador_anuncio.py` é uma lista **auxiliar** que
  o usuário deve usar manualmente (tecer no título/descrição, ou colar em uma campanha de Shopee
  Ads) — não existe um limite de caracteres/contagem "oficial" para validar contra. O teto de ~20
  itens sugerido na recomendação é só usabilidade (uma lista legível para o usuário revisar), sem
  pretensão de espelhar um limite de plataforma que não existe para esse uso.

### Caracteres especiais/emoji — confiança MÉDIA (fonte secundária, mas cita o guia oficial de violação)
- O artigo da Ideris "Orientações para caracteres especiais e palavras não permitidos" (que cita
  o "Guia de Violação de Anúncio" oficial da Shopee, `help.shopee.com.br/portal/4/article/76225`)
  lista como proibidos em anúncios: `} ~ ^ { < * @ ; >`, emoticons/símbolos em geral, hashtags ou
  pontos de exclamação repetidos consecutivamente.
- **Isso destoa do prompt atual**, que permite "no máximo 1 emoji" no título. Se a lista da Ideris
  estiver certa, qualquer emoji é risco de o anúncio ser marcado como violação (não é uma questão
  de tamanho de schema, é conteúdo) — não é o foco desta pergunta (que é sobre limites de
  tamanho), mas registro aqui porque apareceu na mesma pesquisa e é acionável: considerar trocar
  "no máximo 1 emoji" por "nenhum emoji" no `PROMPT_SISTEMA_ANUNCIO` em uma tarefa separada.

## Comparativo das 3 estratégias de enforcement (a decisão real desta pergunta)

| Estratégia | Prós | Contras |
|---|---|---|
| **A. Manter como está** (só orientação em texto no prompt, zero validação de tamanho em código) | Zero esforço; já é o que existe hoje | Nenhuma rede de segurança — uma resposta de IA fora do padrão (ex.: título de 500 caracteres) passa direto pro campo editável sem nenhum sinal de alerta pro usuário; ele só descobre ao colar no Seller Center e levar erro |
| **B. Validação FATAL** (`ErroGeracaoAnuncio` se `titulo`/`descricao` passarem do teto) | Mais parecido com o resto do módulo, que já é rígido em schema (`titulo`/`descricao`/`palavras_chave` ausentes hoje já são fatais) | Descarta uma chamada PAGA de IA por causa de um número que a própria pesquisa não confirma com certeza (5.000 vs 10.000 pra descrição); pune o usuário duas vezes (perdeu o custo da chamada E não tem texto nenhum pra editar), quando o campo é editável mesmo (RF-04) — o dado "ruim" nem precisava ser descartado, só sinalizado |
| **C. Validação NÃO FATAL — avisos** (recomendada) | Blinda o usuário sem descartar a resposta paga; caso o número real da Shopee seja diferente do assumido, o pior caso é um aviso impreciso, não uma perda de dinheiro; combina com RF-07 ("falha não derruba a aba") e com o espírito de resiliência do resto do projeto | Precisa de uma mudança pequena de contrato de retorno (`gerar_anuncio_shopee` passa a poder incluir uma chave extra `avisos`), e o `app.py` (T-003/T-004, ainda backlog) precisa saber exibir esse aviso — mas como a integração com a UI ainda não foi feita, este é o momento mais barato para incluir isso no contrato |

## Armadilhas para quem for implementar

- Não trate 256/5.000 como constantes "de plataforma" confirmadas — documente no código (comentário
  perto do guardrail) que são **tetos de segurança de UX**, baseados em fontes secundárias
  convergentes mas não em uma leitura direta da doc oficial da Shopee, e que a validação final de
  verdade é o próprio Seller Center ao colar o texto (isso já está dito em `ESPECIFICACAO.md`,
  mantenha a mesma linguagem de cautela).
- Não crie um teto de caracteres por item de `palavras_chave` alegando que é "limite da Shopee" —
  não existe um campo desse tipo no cadastro de produto; é puramente usabilidade do app.
- Se decidir mexer no prompt (achado do emoji), trate como tarefa separada — está fora do escopo
  desta pergunta (que é sobre limites de tamanho/schema), mas registre a decisão em `DECISOES.md`
  quando for feita, citando esta pesquisa.
- Ecossistema de e-commerce muda sem aviso: se esta feature virar prioridade maior no futuro, vale
  a pena reservar tempo para tentar renderizar o e-book oficial da Shopee
  (`deo.shopeemobile.com/shopee/cms_cdn_bucket/aaf8761cae2f4dd292e2440c635ed836_E-book...pdf`) com
  uma ferramenta de OCR/PDF real (aqui faltou `poppler-utils` para renderizar as páginas) — é a
  fonte mais primária encontrada nesta pesquisa e pode resolver o conflito de 5.000 vs 10.000 na
  descrição.

## Fontes

- [Mainô — Guia de Cadastros de produtos para o MarketPlace, integração Shopee](https://ajuda.maino.com.br/pt-BR/articles/5228864-guia-de-cadastros-de-produtos-para-o-marketplace-integracao-com-shopee) — título 256, descrição 10.000, título de variação 30
- [Anymarket/Freshdesk — Exigências e Particularidades Shopee](https://suporteanymarket.freshdesk.com/pt-BR/support/solutions/articles/19000129897-exig%C3%AAncias-e-particularidades-shopee) — título 256, descrição 5.000
- [Código Shop — Boas práticas para criar anúncios na Shopee](https://www.codigoshop.com.br/post/boas-pr%C3%A1ticas-para-criar-an%C3%BAncios-na-shopee-o-que-voc%C3%AA-precisa-fazer-para-aparecer-e-vender) — título "limite é de 256 caracteres", até 9 imagens
- [Blog Destrave Escale — Faça isso no Título do seu Anúncio](https://blog.destraveescale.com.br/faca-isso-no-titulo-do-seu-anuncio-para-vender-mais-na-shopee/) — título 255, primeiros 65 caracteres "antes da dobra"
- [Ideris — Orientações para caracteres especiais e palavras não permitidos em anúncios na Shopee](https://atendimento.ideris.com.br/hc/pt-br/articles/27799079282839-Orienta%C3%A7%C3%B5es-para-caracteres-especiais-e-palavras-n%C3%A3o-permitidos-em-an%C3%BAncios-na-Shopee) — cita o guia oficial de violação; lista de símbolos proibidos, sem emoticons
- [Shopee Brasil (oficial) — Guia de Violação de Anúncio](https://help.shopee.com.br/portal/4/article/76225-Guia-de-Viola%C3%A7%C3%A3o-de-An%C3%BAncio) — fonte primária, mas SPA em JS; conteúdo só confirmável via snippets de busca (spam, links externos, informação enganosa)
- [Shopee Brasil (oficial) — E-book "Boas práticas para criação de anúncios na Shopee" (PDF, CDN Shopee)](https://deo.shopeemobile.com/shopee/cms_cdn_bucket/aaf8761cae2f4dd292e2440c635ed836_E-book%20Boas%20pr%C3%A1ticas%20para%20cria%C3%A7%C3%A3o%20de%20an%C3%BAncios%20na%20Shopee%20(4).pdf) — fonte primária confirmada existir, conteúdo não extraível com as ferramentas disponíveis nesta pesquisa (PDF vetorial/imagem, sem `poppler-utils` no ambiente)
- [Shopee Ads Brasil — O que são as palavras-chave?](https://ads.shopee.com.br/learn/faq/323/1466) — confirma que "palavras-chave" é conceito de Shopee Ads, não campo de cadastro de produto
- `Local_AI/estudio_shopee/gerador_anuncio.py` e `_gestao/ESPECIFICACAO.md` deste projeto (lidos para não repetir contexto que a fábrica já registrou)
