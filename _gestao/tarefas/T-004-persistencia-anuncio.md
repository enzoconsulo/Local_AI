---
id: T-004
titulo: Salvar o anúncio junto do render aprovado
projeto: ia-hibrida-limpa
status: em-revisao
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
