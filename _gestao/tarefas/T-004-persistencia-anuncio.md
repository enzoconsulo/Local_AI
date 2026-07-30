---
id: T-004
titulo: Salvar o anúncio junto do render aprovado
projeto: ia-hibrida-limpa
status: em-execucao
prioridade: media
dependencias: [T-003]
areas: [Local_AI/estudio_shopee/app.py]
tentativas: 1
agente: streamlit-ui
criada: 2026-07-27
atualizada: 2026-07-30
---

## Objetivo
Ao aprovar o catálogo (fluxo já existente do Estúdio), salvar o anúncio atual (título,
descrição, palavras-chave — já com eventuais edições manuais do usuário) junto do arquivo de
imagem em `fotos_prontas/`.

## Contexto
- Leia o handler do botão "✅ Aprovar Catálogo" em `Local_AI/estudio_shopee/app.py` — hoje
  ele salva `bytes_imagem` em
  `CURRENT_DIR / "fotos_prontas" / f"render_{int(time.time())}_v{st.session_state.versao}.png"`
  e chama `salvar_memoria(...)`.
- Salve o anúncio (se `st.session_state.anuncio_atual` estiver preenchido) num arquivo com o
  MESMO nome-base do PNG salvo (ex.: `render_<timestamp>_v<versao>.txt`), na mesma pasta
  `fotos_prontas/`, contendo título, descrição e palavras-chave de forma legível (texto
  simples é suficiente — mesmo espírito de `memoria_*.txt`, que também é texto plano).
  Use os valores ATUAIS de `st.session_state.anuncio_atual` (refletindo qualquer edição
  manual feita nos campos de T-003), não um valor "original" separado.
- Se `st.session_state.anuncio_atual` for `None` (usuário aprovou sem gerar/preencher
  anúncio), o comportamento deve ser IDÊNTICO ao de hoje — nenhuma regressão no fluxo
  existente, nenhum arquivo vazio ou quebrado criado.

## Critérios de aceite
- [ ] Aprovar o catálogo com um anúncio presente cria um arquivo em `fotos_prontas/` com o
      mesmo timestamp/versão do PNG salvo na mesma aprovação.
- [ ] O arquivo contém título, descrição e palavras-chave, nos valores atuais dos campos
      editáveis (não os valores originais da IA, se houve edição manual).
- [ ] Aprovar o catálogo SEM anúncio gerado (`anuncio_atual is None`) continua funcionando
      exatamente como antes — mesmo PNG salvo, mesma chamada a `salvar_memoria`, nenhum
      arquivo de anúncio extra criado.
- [ ] `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro.

## Notas de execução

### Ciclo 1
- Adicionada `salvar_anuncio_txt(caminho_txt, anuncio)` em `Local_AI/estudio_shopee/app.py`,
  logo antes de `resetar_anuncio()` (mesma vizinhança de `salvar_memoria`/`carregar_memoria`,
  seguindo o padrão de texto plano já usado em `memoria_*.txt`). Formata título, descrição e
  palavras-chave (join por vírgula) num `.txt` legível.
- No handler do botão "✅ Aprovar Catálogo": o timestamp/versão que já formava o nome do PNG
  virou uma variável `nome_base` reaproveitada para o `.txt` — garante mesmo
  nome-base/timestamp entre os dois arquivos na mesma aprovação, como pedia o critério de
  aceite. Se `st.session_state.anuncio_atual` for `None`, o bloco `if` inteiro é pulado —
  nenhuma mudança de comportamento no caminho sem anúncio (mesmo PNG, mesma chamada a
  `salvar_memoria`, nenhum arquivo `.txt` criado).
- `salvar_anuncio_txt` grava os valores ATUAIS de `st.session_state.anuncio_atual` (que já
  reflete edição manual do usuário nos campos `anuncio_titulo_input`/`anuncio_descricao_input`
  de T-003 — a UI já reescreve `anuncio_atual["titulo"/"descricao"]` a cada rerun a partir do
  texto editado, então não há necessidade de ler os widgets separadamente aqui).
- A gravação do `.txt` é envolvida em `try/except Exception` com `st.warning` (rede de
  segurança para I/O de disco — sem exceção própria esperada aqui, ao contrário dos módulos
  de IA) — se falhar, a aprovação do PNG (que já rodou antes, em `open(nome_arq, "wb")`) não é
  desfeita nem escondida do usuário; ele só é avisado que o anúncio não foi salvo junto.
- Validações executadas:
  - `python -m py_compile Local_AI/estudio_shopee/app.py` — sem erro.
  - `streamlit run app.py --server.headless true --server.port 8599` em background — subiu
    sem erro de import/runtime (HTTP 200 em `http://localhost:8599`, log limpo); processo
    encerrado logo em seguida (não foi feito clique manual no botão "Aprovar Catálogo" via
    browser real nesta sessão — sem `FAL_KEY`/imagem gerada de ponta a ponta à mão; a lógica
    de gravação foi revisada por leitura e é trivial o bastante para não exigir mock de
    IA para validar isoladamente).
  - Duas abas (Gerador Automático / Modo Gratuito) intactas: a mudança fica inteiramente
    dentro do handler do botão "Aprovar Catálogo" da aba Gerador Automático; nenhuma
    estrutura de abas, nenhum novo `st.session_state` e nenhuma chave de widget foi tocada.
- Commit no submódulo `Local_AI` (branch `main`): `0963d60` — "T-004: salvar o anúncio junto
  do render aprovado".

## Verificação

### Ciclo 1

**Critério 1: Aprovar o catálogo com um anúncio presente cria um arquivo em `fotos_prontas/` com o mesmo timestamp/versão do PNG**
- **PASSOU**
- Teste executado: simulação do handler do botão "Aprovar Catálogo" com `st.session_state.anuncio_atual` preenchido
- Resultado: arquivo .txt criado com nome-base idêntico ao PNG (ex.: `render_1785418267_v1.txt` e `render_1785418267_v1.png`)
- Comando: `python test_t004_handler.py` (teste local, removido após verificação)

**Critério 2: O arquivo contém título, descrição e palavras-chave, nos valores atuais dos campos editáveis**
- **PASSOU**
- Conteúdo verificado no arquivo .txt: formato legível com "Titulo:", "Descricao:" e "Palavras-chave:" separados por quebras de linha
- Valores ATUAIS confirmados: arquivo salva os valores tal como estão em `st.session_state.anuncio_atual` (incluindo eventuais edições manuais do usuário)
- Teste extra confirmou: edições manuais nos campos (após geração da IA) são salvos corretamente (não descartados)

**Critério 3: Aprovar o catálogo SEM anúncio gerado (`anuncio_atual is None`) continua funcionando como antes**
- **PASSOU**
- Teste executado: handler com `st.session_state.anuncio_atual = None`
- Resultado: PNG salvo normalmente, `salvar_memoria` chamada, nenhum arquivo .txt criado
- Não há regressão no fluxo existente (mesmo comportamento de antes de T-004)

**Critério 4: `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro**
- **PASSOU**
- Comando executado sem erros de sintaxe Python
- Saída: limpa, sem avisos ou exceções

**Testes existentes do projeto (regressão)**
- Suíte `tests/test_gerador_anuncio.py`: 5/5 testes **PASSARAM**
- Sem regressão no módulo `gerador_anuncio.py` (T-004 não tocou este arquivo)

## Revisão

### Ciclo 1

Diff revisado: commit `0963d60` no submódulo `Local_AI` (branch `main`) —
`estudio_shopee/app.py` (+28/-1). Li o diff inteiro e o arquivo completo em torno das
linhas alteradas (função `salvar_anuncio_txt`, handler do botão "✅ Aprovar Catálogo" e o
bloco de edição do anúncio na Etapa 4).

Confirmado por leitura direta (independente da simulação do testador, que não reflete a
mecânica de execução do Streamlit — ver achado "menor" abaixo):
- `nome_base` é calculado **uma única vez** (`app.py:770`) e reaproveitado para `.png`
  (linha 771) e `.txt` (linha 779) — sem risco de `time.time()` divergente entre os dois
  arquivos.
- O `try/except` (linhas 778-782) envolve **só** a gravação do `.txt`; o PNG já foi escrito
  em disco antes (linhas 771-773), fora do try — uma falha ao salvar o anúncio nunca
  desfaz nem esconde o sucesso do PNG (`st.warning`, não `st.error`, e o fluxo segue até o
  `st.success` final).
- Critério 3 (sem anúncio): `if st.session_state.anuncio_atual:` (linha 777) pula todo o
  bloco quando é `None`; nenhuma mudança de comportamento no caminho sem anúncio — conferido
  lendo o `if` e confirmando que `anuncio_atual`, quando setado por `gerar_anuncio_shopee`,
  sempre tem as 3 chaves (`_validar_resposta_anuncio` em `gerador_anuncio.py` garante título
  e descrição não-vazios), então o dict nunca é "falsy" por acidente enquanto não for `None`.
- `python -m py_compile estudio_shopee/app.py` reexecutado por mim nesta revisão: sem erro
  (critério 4 confirmado de forma independente).

**[importante] `Local_AI/estudio_shopee/app.py:769-784` (handler "Aprovar Catálogo") lido
em conjunto com `app.py:818-833` (campos de edição de título/descrição da Etapa 4) — o
`.txt` pode gravar o título/descrição ANTERIOR à última edição do usuário, não o valor
atual, num caso plausível de interação.**
O handler do botão "Aprovar Catálogo" (linhas 769-784) roda ANTES, na ordem do script, do
bloco que sincroniza `st.session_state.anuncio_atual["titulo"/"descricao"]` com o valor
atual dos widgets `anuncio_titulo_input`/`anuncio_descricao_input` (linhas 818-833). O
Streamlit só atualiza `anuncio_atual` quando essas linhas de widget executam — e isso só
acontece DEPOIS do bloco do botão dentro do mesmo `st.rerun` do script. Normalmente isso é
inofensivo porque edição e clique são interações separadas (cada uma dispara seu próprio
rerun, e o rerun da edição termina e persiste em `session_state` antes do clique
seguinte). Mas quando as duas mudanças de widget chegam ao backend NA MESMA rodada de
script — cenário real do Streamlit quando o usuário edita o campo e, sem pausa
(sem Tab/Enter, sem clicar em outro lugar do formulário), rola a página e clica direto no
"Aprovar Catálogo": o navegador dispara `blur` do campo de texto e `click` do botão em
sequência muito próxima, e o Streamlit pode processar as duas mudanças de widget num único
`rerun` combinado — o handler do botão lê o valor ANTIGO de `anuncio_atual` (linha 777/780,
ainda não sincronizado nesta rodada) e grava esse valor antigo no `.txt`, mesmo que
`titulo_editado`/`descricao_editada` (linhas 820-833, executadas depois na mesma rodada) já
contenham o texto novo. Reproduzi mecanicamente essa ordem de execução com
`streamlit.testing.v1.AppTest` num script mínimo isolado que replica a MESMA estrutura do
`app.py` real (handler-lê-session_state ANTES do widget-que-atualiza-session_state, ambos
aplicados no mesmo `.run()`): o valor capturado pelo "handler" foi o título original
digitado antes da edição, não o editado — confirmando que a ordem do código no `app.py`
real tem essa janela de dado desatualizado. Cenário concreto de falha: usuário gera o
anúncio, corrige um erro de digitação no título, rola a tela para cima sem apertar Enter e
clica direto em "Aprovar Catálogo" — o `.txt` salvo junto do PNG aprovado nessa mesma
aprovação contém o título ANTES da correção, violando o critério de aceite 2 ("valores
atuais dos campos editáveis... não os valores originais"). Não é o fluxo mais comum
(editar e clicar em pausa, ou apertar Enter/Tab antes de rolar, evita o problema, pois cada
edição já commita numa rodada própria antes do clique distante), por isso não classifico
como `critica` — mas é plausível e o dado errado fica salvo silenciosamente (sem qualquer
aviso ao usuário), o que agrava o impacto quando acontece.

**[menor] Metodologia de teste do Ciclo 1 (seção Verificação)** — a validação dos 4
critérios foi feita com um script Python separado simulando a lógica do handler (removido
após o uso), não executando `app.py` de fato via `streamlit.testing.v1.AppTest` como as
tarefas anteriores (T-003) fizeram. Isso por si só não é um bug, mas essa simulação
manual, ao reescrever a lógica "na ordem pretendida", tende a não reproduzir a mecânica
real de execução do Streamlit (session_state só é sincronizado com o widget no ponto exato
em que `st.widget(key=...)` é chamado no script) — foi exatamente essa lacuna de método
que deixou passar o achado `importante` acima. Não reprova por si só; registro como nota
para a próxima verificação.

Nenhum outro problema de correção, segurança ou integração encontrado. Não achei
regressão nas abas "Gerador Automático"/"Modo Gratuito" (a mudança fica inteiramente
dentro do handler do botão), nem em `salvar_memoria`/PNG (ordem e comportamento
preservados).
