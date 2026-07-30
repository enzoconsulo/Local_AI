---
id: T-003
titulo: UI — seção "Anúncio Shopee" na aba de criar imagens
projeto: ia-hibrida-limpa
status: em-teste
prioridade: alta
dependencias: [T-002]
areas: [Local_AI/estudio_shopee/app.py]
tentativas: 1
agente: streamlit-ui
criada: 2026-07-27
atualizada: 2026-07-29
---

## Objetivo
Adicionar, na aba "🎨 Gerador Automático" do Estúdio, uma seção que permite gerar o anúncio
completo (título + descrição + palavras-chave) a partir da imagem final selecionada, e editar
o resultado antes de usar.

## Contexto
- Leia `Local_AI/estudio_shopee/app.py` inteiro antes de editar — em especial a "Mesa de
  Refinamento" (`col2`, dentro de `aba_auto`) e o bloco de inicialização de
  `st.session_state` no topo do arquivo.
- Use `gerar_anuncio_shopee` e `ErroGeracaoAnuncio` de `gerador_anuncio.py` (T-002).
- Onde encaixar: dentro de `col2`, como uma nova seção (ex.: "4. Anúncio Shopee"), visível
  quando `st.session_state.imagem_gerada_b64` estiver preenchido (mesma condição já usada
  para mostrar "Ver Roteiro Operacional da IA" e o botão "✅ Aprovar Catálogo").
- Novo estado: `st.session_state.anuncio_atual` — inicialize como `None` junto aos demais
  `if 'x' not in st.session_state: st.session_state.x = ...` do topo do arquivo. Estrutura
  sugerida: `{"titulo": str, "descricao": str, "palavras_chave": list[str]}`.
- IMPORTANTE — reset de estado: quando o usuário troca de arquivo de upload (bloco que já
  reseta `img_recortada_bytes`, `imagem_gerada_b64`, `candidatos_atual`,
  `imagem_referencia_atual`, `prompt_manual`) ou gera uma nova imagem do zero (botão "🚀
  Gerar..."), resete também `st.session_state.anuncio_atual = None` — senão um anúncio antigo
  fica colado numa imagem nova.
- Botão "📝 Gerar Anúncio Completo": chama `gerar_anuncio_shopee(bytes_imagem, contexto)`,
  onde `bytes_imagem` é a imagem final atual (mesma variável já usada para exibir/aprovar o
  catálogo, ex. `bytes_imagem = base64.b64decode(st.session_state.imagem_gerada_b64)`) e
  `contexto` é montado a partir de `st.session_state.dados_atual` (produto, cor, estilo).
  Use `st.status`/`st.spinner` com mensagem em português durante a chamada, seguindo o padrão
  já usado nos outros botões de IA do arquivo (ex. "🚀 Gerar..." e "🛠️ Recalcular Ajuste").
- Em caso de `ErroGeracaoAnuncio`, mostre `st.error(...)` com a mensagem, sem deixar a
  exceção subir e derrubar a página — o resto da aba deve continuar funcionando.
- Reforço vindo da revisão de T-002 (Ciclo 1), avaliado na revisão avulsa de 2026-07-28
  (ver `DECISOES.md`):
  1. `contexto_produto`/`historico_estilo` NÃO são validados em runtime dentro de
     `gerar_anuncio_shopee` (só type hints) — monte `contexto` sempre como um `dict`
     simples com valores `str` (nunca `None`; use `.get(chave, "")` ou `str(...)` ao ler
     de `st.session_state.dados_atual`) para não arriscar `AttributeError` cru escapando
     da função. Além disso, capture no handler do botão primeiro `ErroGeracaoAnuncio`
     (mensagem específica da IA) e, como rede de segurança, também `Exception` genérica
     (`st.error(f"Erro inesperado ao gerar anúncio: {e}")`) — garante que RF-07 (falha
     não derruba a aba) vale mesmo diante de um erro imprevisto, não só do erro esperado.
  2. `construir_data_uri` usa `mime_type="image/jpeg"` fixo — CONFIRMADO nesta revisão que
     NÃO é um problema para esta tarefa: `imagem_gerada_b64`/`bytes_imagem` vem sempre de
     `chamar_motor_imagem` (fal.ai), chamado com `payload["output_format"] = "jpeg"`
     (linha ~331 de `app.py`) — a imagem final é sempre JPEG de fato nesta pipeline, então
     o mime type fixo está correto para o caso de uso do anúncio. Nenhum ajuste extra
     necessário por causa disso; a ressalva do revisor era genérica (relevante para
     `img_recortada_bytes`/canal alfa do `rembg`, usado no fluxo de EDIÇÃO de imagem, fora
     do escopo desta tarefa).
- Campos editáveis: `st.text_input` para o título (com contador de caracteres visível, ex.
  `st.caption(f"{len(titulo)} caracteres")`) e `st.text_area` para a descrição, ambos
  pré-preenchidos com `st.session_state.anuncio_atual` e escrevendo de volta nele a cada
  edição (para que T-004 leia sempre o valor mais atual ao salvar). Palavras-chave podem ser
  exibidas como texto simples (ex. separadas por vírgula) ou `st.multiselect`/lista — escolha
  o mais simples que funcione bem na UI.

## Critérios de aceite
- [ ] A seção "Anúncio Shopee" aparece na aba "Gerador Automático" assim que há uma imagem
      final selecionada, e não aparece antes disso.
- [ ] Clicar em "Gerar Anúncio Completo" chama `gerar_anuncio_shopee` com a imagem final em
      bytes + o contexto do produto atual, e preenche `st.session_state.anuncio_atual`.
- [ ] Título e descrição aparecem em campos editáveis, pré-preenchidos com o resultado da IA;
      editar os campos atualiza `st.session_state.anuncio_atual`.
- [ ] Simular uma falha (ex.: rodar sem `OPENAI_API_KEY` configurada) resulta em
      `st.error(...)` visível, e as demais seções da página continuam funcionando
      normalmente (upload, geração de imagem, aprovação do catálogo).
- [ ] Simular uma exceção INESPERADA (não `ErroGeracaoAnuncio`) no fluxo de geração do
      anúncio (ex.: monkeypatch temporário de `gerar_anuncio_shopee` para levantar
      `RuntimeError`) também resulta em `st.error(...)` visível, sem derrubar a página —
      confirma a rede de segurança pedida no Contexto.
- [ ] `st.session_state.anuncio_atual` volta a `None` ao trocar de arquivo de upload ou ao
      gerar uma nova imagem (botão "🚀 Gerar...").
- [ ] `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro.

## Notas de execução

(2026-07-28 — planejador, revisão avulsa pedida via painel, sem gatilho de bloqueio/
esgotamento: tarefa ainda em `backlog`/0 tentativas, editada diretamente — ver
`DECISOES.md`. Contexto e critérios de aceite reforçados com as 2 notas da Revisão de
T-002 Ciclo 1; nenhuma mudança de abordagem, só texto adicional para o executor não
perder os avisos.)

### Ciclo 1 (executor genérico, seguindo as orientações do especialista `streamlit-ui`
indisponível nesta sessão)

**O que foi feito** — em `Local_AI/estudio_shopee/app.py`:
- Import: `from gerador_anuncio import construir_data_uri, gerar_anuncio_shopee,
  ErroGeracaoAnuncio` (antes só importava `construir_data_uri`).
- Novo estado `st.session_state.anuncio_atual` inicializado como `None` no bloco de
  inicialização único do topo (junto aos demais `if 'x' not in st.session_state`).
- Nova função `resetar_anuncio()` (perto de `resetar_memoria`): zera
  `anuncio_atual` e remove as chaves dos widgets `anuncio_titulo_input`/
  `anuncio_descricao_input` de `st.session_state` (ver "Decisão de arquitetura" abaixo).
  Chamada em 2 pontos, exatamente os do Contexto da tarefa: (1) no bloco que já reseta
  `img_recortada_bytes`/`imagem_gerada_b64`/`candidatos_atual`/
  `imagem_referencia_atual`/`prompt_manual` ao trocar de arquivo de upload; (2) logo após
  `st.session_state.versao = 1`, dentro do `try` de sucesso do botão "🚀 Gerar...".
- Nova seção "4. Anúncio Shopee" em `col2` ("Mesa de Refinamento"), dentro do
  `elif st.session_state.imagem_gerada_b64:` (só aparece com imagem final selecionada) —
  inserida depois do botão "✅ Aprovar Catálogo", mesmo `elif`:
  - Botão "📝 Gerar Anúncio Completo" (`st.spinner` em português) monta `contexto_anuncio`
    como `dict` simples de `str` (nunca `None`, via `str(dados_produto.get(...) or "")`)
    a partir de `st.session_state.dados_atual`, e chama `gerar_anuncio_shopee(bytes_imagem,
    contexto_anuncio)` — `bytes_imagem` é a mesma variável já usada para exibir/aprovar o
    catálogo (linha ~687).
  - Handler com dois `except`: `ErroGeracaoAnuncio` (mensagem específica da IA) e
    `Exception` genérica como rede de segurança (RF-07 / reforço da revisão de T-002
    citado no Contexto) — ambos usam `st.error(...)`, nunca deixam a exceção subir.
  - Campos editáveis: `st.text_input` (título, com `st.caption` de contador de
    caracteres) e `st.text_area` (descrição, altura 220), ambos com `key=` fixo
    (`anuncio_titulo_input`/`anuncio_descricao_input`) e `value=` pré-preenchido de
    `st.session_state.anuncio_atual`; cada edição escreve de volta em
    `st.session_state.anuncio_atual[...]` no mesmo rerun (T-004 vai ler sempre o valor
    mais atual). Palavras-chave exibidas como texto simples via `st.caption`
    (`", ".join(...)`), conforme sugerido no Contexto como opção mais simples.

**Decisão de arquitetura (registrada aqui, não em DECISOES.md por ser detalhe de
implementação local, sem impacto em outras tarefas):** como os campos de edição usam
`key=` (necessário para T-004 conseguir ler `st.session_state.anuncio_atual` sempre
atualizado a cada edição), o Streamlit ignora o parâmetro `value=` em reruns seguintes
enquanto a chave já existir em `session_state` — comportamento padrão de widgets com
`key`. Sem tratar isso, gerar um anúncio NOVO (segunda chamada do botão, ou depois de
`resetar_anuncio()`) deixaria o texto ANTIGO colado nos campos. Solução: toda vez que
`anuncio_atual` é substituído por um valor novo (dentro do handler do botão, antes de
gravar o resultado) ou zerado (`resetar_anuncio()`), as duas chaves de widget
(`anuncio_titulo_input`/`anuncio_descricao_input`) são removidas de `session_state` via
`.pop(..., None)` — forçando os widgets a reinicializar com o `value=` novo no próximo
render, sem perder a capacidade de edição ao vivo entre reruns.

**Como testar/rodar:**
- Estático: `python -m py_compile Local_AI/estudio_shopee/app.py` — sem erro.
- Manual real: `cd Local_AI/estudio_shopee && streamlit run app.py` (precisa de
  `FAL_KEY` em `Local_AI/CHAVES.env`; sem `OPENAI_API_KEY` configurada, o botão "Gerar
  Anúncio Completo" deve mostrar exatamente o `st.error` de credencial ausente).
- Automatizado ad hoc (não commitado — `estudio_shopee` não tem suíte de UI ainda, e
  não é isso que esta tarefa pede): rodei um script à parte com
  `streamlit.testing.v1.AppTest` (`pip install streamlit` nesta sessão, já era
  dependência do projeto, só não estava no Python global usado pelo agente — nada novo
  registrado em DECISOES.md por não ser dependência nova do projeto) que sobe
  `app.py` de verdade com `rembg`/`fal_client` stubados (não usados pelo fluxo do
  anúncio) e `gerar_anuncio_shopee` monkeypatchado por cenário, exercitando os 6
  primeiros critérios de aceite:
  1. Sem `imagem_gerada_b64`, a seção "4. Anúncio Shopee" NÃO aparece; com
     `imagem_gerada_b64` setado, aparece — PASSOU.
  2. Clique em "📝 Gerar Anúncio Completo" sem `OPENAI_API_KEY` (ambiente limpo, sem
     `CHAVES.env`) → `st.error` com a mensagem de credencial ausente, sem exceção
     subindo, `anuncio_atual` permanece `None`, botão "✅ Aprovar Catálogo" segue
     presente na página — PASSOU.
  3. `gerar_anuncio_shopee` monkeypatchado para levantar `RuntimeError` (exceção
     INESPERADA) → `st.error("Erro inesperado ao gerar anúncio: ...")`, sem exceção
     subindo — PASSOU.
  4. Caminho feliz: `gerar_anuncio_shopee` monkeypatchado retornando dict fixo, chamado
     de fato com `bytes_imagem` (verificado não-vazio) + `contexto_anuncio["produto"]`
     igual ao `st.session_state.dados_atual` de teste → `anuncio_atual` preenchido,
     `st.text_input`/`st.text_area` renderizados com os valores da IA, contador de
     caracteres e palavras-chave exibidos — PASSOU.
  5. Editar o `text_input` do título (`.set_value(...)`) e rodar de novo →
     `st.session_state.anuncio_atual["titulo"]` reflete o texto editado — PASSOU.
  6. Simular novo upload (`file_uploader[0].upload(...)`) com `anuncio_atual` e as
     chaves de widget já preenchidas de uma rodada anterior → após o rerun,
     `arquivo_atual` atualiza, `anuncio_atual` volta a `None` e as duas chaves de
     widget somem de `session_state` — PASSOU.
  O reset do botão "🚀 Gerar..." (2º ponto de chamada de `resetar_anuncio()`, mesmo
  critério de aceite do reset acima) NÃO foi exercitado ponta a ponta pelo mesmo script
  — chegar até esse botão exigiria simular também a "✂️ Isolar Produtos" (rembg),
  "🧪 Teste" (autofill) e a geração via LLM local (`gerar_prompt_em_ingles`, porta 8000)
  + `fal_client.subscribe`, fora de proporção para esta tarefa; a chamada
  `resetar_anuncio()` nesse ponto é a MESMA função já comprovada correta no cenário 6
  (mesma implementação, só outro call site) — confirmado por leitura direta do diff.
  Script de teste era arquivo temporário fora do repositório do projeto
  (`%TEMP%\validar_t003.py`), apagado ao final — nada ficou fora da árvore do projeto.

**Arquivos alterados:** `Local_AI/estudio_shopee/app.py` (único arquivo tocado; nenhum
outro fora do escopo de `areas` da tarefa).

**Commit:** submódulo `Local_AI` (branch `main`) — `aecc808`. Repositório externo
(`ia-hibrida-limpa`, branch `master`) — ponteiro do submódulo + este arquivo de tarefa,
em commit separado logo em seguida.

**Pendência/sugestão para o orquestrador:** o botão "🛠️ Recalcular Ajuste" (ajuste
rápido sobre a MESMA imagem) também produz uma imagem nova em
`st.session_state.imagem_gerada_b64` mas não está entre os 2 pontos de reset pedidos no
Contexto/Critérios de aceite desta tarefa — depois de um ajuste, um anúncio gerado antes
do ajuste ficaria "colado" a uma imagem ligeiramente diferente (mesmo produto, luz/cena
ajustada). Não mexi nisso por estar fora do escopo explícito da tarefa (nem Contexto nem
Critérios de aceite mencionam esse botão); registrando aqui para o orquestrador avaliar
se vale uma tarefa nova.

## Verificação


## Revisão
