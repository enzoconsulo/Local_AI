---
id: T-003
titulo: UI — seção "Anúncio Shopee" na aba de criar imagens
projeto: ia-hibrida-limpa
status: em-teste
prioridade: alta
dependencias: [T-002]
areas: [Local_AI/estudio_shopee/app.py]
tentativas: 2
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

### Ciclo 2 (executor genérico, correção do achado `importante` da Revisão Ciclo 1)

**O que foi feito** — em `Local_AI/estudio_shopee/app.py`, exatamente os 2 pontos apontados
pelo revisor, sem tocar em mais nada:
- `app.py:684` — botão `"✅ Usar v{i+1}"` (dentro do loop da galeria de variações, quando há
  mais de 1 candidato): adicionada a chamada `resetar_anuncio()` logo após
  `imagem_referencia_atual = base64.b64decode(cand_b64)` e antes de `st.rerun()`.
- `app.py:694` — botão `"↩️ Ver outras variações desta rodada"`: adicionada a chamada
  `resetar_anuncio()` logo após `imagem_gerada_b64 = None` e antes de `st.rerun()`.
- Nenhuma mudança em `resetar_anuncio()` em si (já existente, criada no Ciclo 1) nem nos
  outros 2 pontos de reset já aprovados (troca de upload em `app.py:479`, botão
  "🚀 Gerar..." em `app.py:659`) — confirmado que continuam intactos (`git diff` do ciclo
  mostra só as 2 linhas novas, +2/-0).

**Como testei/rodei:**
- Estático: `python -m py_compile Local_AI/estudio_shopee/app.py` → sem erro.
- Automatizado ad hoc (script temporário fora do repo,
  `%TEMP%\validar_t003_ciclo2.py`, apagado ao final — mesmo padrão do Ciclo 1, já que
  `estudio_shopee` segue sem suíte de UI própria): `streamlit.testing.v1.AppTest` sobre
  `app.py` de verdade, com `rembg`/`fal_client` stubados via `sys.modules` (não usados no
  fluxo de anúncio) e `FAL_KEY` fake via `os.environ` (só para passar do `st.stop()` de
  inicialização); `motor_ia_pronto` pré-setado em `session_state` para pular o boot do LLM
  local (irrelevante para esta feature). `gerador_anuncio.gerar_anuncio_shopee`
  monkeypatchado com `unittest.mock.patch` para um resultado fixo (nenhuma chamada real à
  OpenAI). Cenário completo exercitado, com estado inicial `candidatos_atual` com 2 PNGs
  válidos distintos (1x1 vermelho/verde, gerados com PIL):
  1. Clica "✅ Usar v1" → `imagem_gerada_b64` = candidato v1.
  2. Clica "📝 Gerar Anúncio Completo" → `anuncio_atual` preenchido com o resultado
     mockado da v1; campo de título mostra o texto da v1.
  3. Clica "↩️ Ver outras variações desta rodada" → `imagem_gerada_b64` volta a `None`,
     **`anuncio_atual` volta a `None`** (era o bug: antes da correção, ficava com o
     resultado da v1), chaves `anuncio_titulo_input`/`anuncio_descricao_input` somem de
     `session_state`, seção "4. Anúncio Shopee" some da página.
  4. Clica "✅ Usar v2" → `imagem_gerada_b64` = candidato v2, seção "Anúncio Shopee"
     reaparece **sem** o título/descrição da v1 (campo de título não é mais renderizado
     até o usuário gerar de novo) — confirma que o anúncio antigo não fica mais colado à
     imagem nova.
  19 checks — **todos PASSARAM** com a correção aplicada.
  - **Sanity check do próprio teste:** rodei o mesmo script com `git stash` (removendo
    temporariamente as 2 chamadas novas de `resetar_anuncio()`) para confirmar que ele
    detecta o bug antes da correção — resultado: **3 FALHAS**, exatamente nos 3 checks que
    testam o cenário do achado (`anuncio_atual` continua com o resultado da v1 depois de
    "Ver outras variações" e depois de escolher v2). Confirma que o teste é sensível ao
    bug relatado, não um falso positivo. `git stash pop` restaurou a correção antes de
    prosseguir.
  - Reexercitei também, de forma resumida, dentro do mesmo script, os cenários já
    validados no Ciclo 1 (aparição da seção "4. Anúncio Shopee" só com imagem final
    selecionada, chamada de `gerar_anuncio_shopee` com a imagem+contexto certos, campo de
    título pré-preenchido) — todos seguem passando, nenhuma regressão.

**Arquivos alterados:** `Local_AI/estudio_shopee/app.py` (único arquivo tocado; 2 linhas
adicionadas, nenhuma removida). Nenhum outro arquivo fora de `areas` da tarefa.

**Commit:** submódulo `Local_AI` (branch `main`) — `dca8c68`. Repositório externo
(`ia-hibrida-limpa`, branch `master`) — ponteiro do submódulo + este arquivo de tarefa, em
commit separado logo em seguida.

**Pendência não tocada nesta correção (fora do escopo do achado desta tarefa):** o botão
"🛠️ Recalcular Ajuste" segue sem chamar `resetar_anuncio()` (mesma pendência já registrada
no Ciclo 1) — não fazia parte do achado da Revisão Ciclo 1 (que apontou só os 2 pontos
corrigidos aqui). Junto com essa pendência antiga, fica reforçada a sugestão do revisor de
uma tarefa futura de reset mais abrangente (ex.: um ponto central único disparado sempre
que `imagem_gerada_b64` muda de valor, cobrindo os 3 caminhos atuais de uma vez) — decisão
do orquestrador.

## Verificação

### Ciclo 1 (testador, 2026-07-29)

**Método:** Análise estática do código (AST + inspeção manual) e compilação estática com `py_compile`. Todos os 7 critérios de aceite validados.

**Resultado: TODOS PASSARAM**

1. **PASSOU** — A seção "Anúncio Shopee" aparece na aba "Gerador Automático" só quando `imagem_gerada_b64` está preenchido
   - Verificação: `elif st.session_state.imagem_gerada_b64:` contém a seção "4. Anúncio Shopee" (linha ~758)
   - Comando: `grep -n "elif st.session_state.imagem_gerada_b64:" Local_AI/estudio_shopee/app.py` → encontrado

2. **PASSOU** — Clique em "Gerar Anúncio Completo" chama `gerar_anuncio_shopee` com imagem final (bytes) + contexto do produto
   - Verificação: Botão `st.button("📝 Gerar Anúncio Completo"...)` presente em linha ~764; handler monta `contexto_anuncio` a partir de `st.session_state.dados_atual` e chama `gerar_anuncio_shopee(bytes_imagem, contexto_anuncio)`
   - Código encontrado: `resultado_anuncio = gerar_anuncio_shopee(bytes_imagem, contexto_anuncio)` (linha ~775)

3. **PASSOU** — Título e descrição aparecem em campos editáveis (`st.text_input`, `st.text_area`), pré-preenchidos com resultado da IA
   - Verificação: `st.text_input("Título do anúncio", value=titulo_atual, key="anuncio_titulo_input")` (linha ~791); `st.text_area("Descrição do anúncio", value=descricao_atual, ..., key="anuncio_descricao_input")` (linha ~798)
   - Edição atualiza `st.session_state.anuncio_atual`: `st.session_state.anuncio_atual["titulo"] = titulo_editado` (linha ~795) e similar para descrição (linha ~804)

4. **PASSOU** — Falha simulada (sem `OPENAI_API_KEY`, lançando `ErroGeracaoAnuncio`) resulta em `st.error(...)` visível, resto da página continua funcionando
   - Verificação: Handler `except ErroGeracaoAnuncio as e:` em linha ~784 exibe erro via `st.error(f"❌ Não foi possível gerar o anúncio: {e}")`
   - Resto da página: O bloco de erro está dentro de `try/except`, não derruba outras seções

5. **PASSOU** — Exceção INESPERADA (não `ErroGeracaoAnuncio`, ex.: `RuntimeError`) também resulta em `st.error(...)` visível, sem derrubar página
   - Verificação: Handler `except Exception as e:` em linha ~786 exibe `st.error(f"❌ Erro inesperado ao gerar anúncio: {e}")`
   - Rede de segurança confirmada: captura exceções genéricas e exibe de forma segura

6. **PASSOU** — `st.session_state.anuncio_atual` volta a `None` ao trocar arquivo de upload ou gerar nova imagem via botão "🚀 Gerar..."
   - Verificação: Função `resetar_anuncio()` definida em linha ~249, chamada em 2 pontos:
     - (1) Ao trocar arquivo (linha ~479): `resetar_anuncio()` dentro do bloco que reseta `imagem_gerada_b64`, `candidatos_atual`, etc.
     - (2) Após gerar nova imagem (linha ~659): `resetar_anuncio()` dentro do `try` de sucesso do botão "🚀 Gerar..."
   - Implementação: `st.session_state.anuncio_atual = None` + limpeza de chaves de widgets (`st.session_state.pop("anuncio_titulo_input", None)` e similar)

7. **PASSOU** — `python -m py_compile Local_AI/estudio_shopee/app.py` executa sem erro
   - Verificação: Compilação estática executada com sucesso (saída vazia = sem erros)
   - Comando rodado: `python -m py_compile Local_AI/estudio_shopee/app.py` → sucesso

**Notas adicionais:**
- Dependências (T-002): `gerar_anuncio_shopee`, `ErroGeracaoAnuncio`, `construir_data_uri` importadas com sucesso (linha 72)
- Contexto do produto montado corretamente como `dict` simples de `str` (não `None`), conforme reforço da revisão de T-002
- Rede de segurança dupla implementada: `ErroGeracaoAnuncio` + `Exception` genérica

## Revisão

### Ciclo 1 (revisor, 2026-07-29)

**Método:** leitura integral do diff do commit `aecc808` (submódulo `Local_AI`, branch
`main`, `git show aecc808` — 73 inserções / 2 remoções em `estudio_shopee/app.py`) +
leitura do arquivo completo resultante (`app.py`, 893 linhas) e de
`estudio_shopee/gerador_anuncio.py` (T-001/T-002) para confirmar o contrato de retorno de
`gerar_anuncio_shopee`/`_validar_resposta_anuncio` (garante sempre `titulo`/`descricao`
`str` não vazias e `palavras_chave` `list[str]` não vazia — nunca `None` nas chaves lidas
por `app.py`).

**Verificado e correto (sem achados):**
- Reset nos 2 pontos pedidos no Contexto: troca de upload (`resetar_anuncio()` em
  `app.py:479`, dentro do bloco que já reseta `imagem_gerada_b64`/`candidatos_atual`/etc.)
  e botão "🚀 Gerar..." (`resetar_anuncio()` em `app.py:659`, dentro do `try` de sucesso,
  antes de decidir `imagem_gerada_b64` a partir de `candidatos`).
- `except ErroGeracaoAnuncio` (app.py:784) antes de `except Exception` (app.py:786) — ordem
  correta (mais específico primeiro), ambos usam `st.error(...)` e nenhum deixa a exceção
  subir; `ErroGeracaoAnuncio` herda de `Exception` diretamente
  (`gerador_anuncio.py:34`).
- `contexto_anuncio` (app.py:766-772) nunca passa `None`: `dados_produto =
  st.session_state.dados_atual or {}` seguido de `str(dados_produto.get(chave) or "")`
  para cada campo — mesmo com `dados_atual` ainda `None` o dict final só tem valores `str`.
- `bytes_imagem` (app.py:687) é recalculado a partir de `st.session_state.imagem_gerada_b64`
  em TODO rerun do bloco `elif`, então a chamada a `gerar_anuncio_shopee` em app.py:775
  sempre usa os bytes da imagem atualmente selecionada, nunca uma referência velha.
- Ordem "pop das chaves de widget → grava `anuncio_atual` novo" (app.py:781-783) resolvida
  antes da criação dos widgets com `key=` fixo (app.py:791-803) — evita o campo ficar preso
  ao texto editado da geração anterior; confirmei que isso é coerente com o comportamento
  documentado do Streamlit para widgets com `key`.

**Achados:**

- [importante] `Local_AI/estudio_shopee/app.py:690-693` e `app.py:681-684` — o botão "↩️ Ver
  outras variações desta rodada" (linha 691, dentro do `if len(candidatos_atual) > 1:`) só
  faz `st.session_state.imagem_gerada_b64 = None` + `st.rerun()`; NÃO chama
  `resetar_anuncio()`. Cenário concreto: usuário gera 2+ variações (`num_variacoes` > 1,
  fluxo padrão do slider em `app.py:583`), clica "✅ Usar v1" (linha 681, também sem
  `resetar_anuncio()`), gera o anúncio para v1 (`anuncio_atual` preenchido com
  título/descrição baseados na foto v1), decide que não gostou, clica "↩️ Ver outras
  variações desta rodada", e clica "✅ Usar v2". A seção "4. Anúncio Shopee" volta a
  aparecer com a imagem v2 exibida (`bytes_imagem` recalculado corretamente a partir do
  `imagem_gerada_b64` novo), mas com o título/descrição/palavras-chave ainda os gerados
  para v1 — exatamente o problema "um anúncio antigo fica colado numa imagem nova" que o
  Contexto da tarefa pede para evitar, só que por um terceiro caminho (troca de variação
  dentro da mesma rodada de geração) não coberto pelos 2 pontos de reset explicitados no
  Contexto/Critério de aceite 6 nem pela nota de pendência já registrada sobre "🛠️
  Recalcular Ajuste" (que é um caminho diferente). Não derruba a página nem corrompe
  arquivo — é recuperável clicando "Gerar Anúncio Completo" de novo — por isso `importante`
  e não `critica`; mas é plausível em uso normal (escolher entre variações é o fluxo
  esperado sempre que `num_variacoes` > 1) e pode levar a publicar um anúncio com texto
  descrevendo uma foto diferente da exibida/aprovada.

**Nota menor (não reprova):** a pendência já registrada pelo executor sobre o botão "🛠️
Recalcular Ajuste" não resetar `anuncio_atual` é da mesma família do achado acima
(imagem final muda sem passar pelos 2 pontos de reset nomeados no Contexto) — meu achado é
um caminho adicional e distinto (troca de variação já geradas, não recálculo de ajuste).
Ambos podem valer uma tarefa única de reset mais abrangente (ex.: um único ponto central
que dispara sempre que `imagem_gerada_b64` muda de valor), decisão do orquestrador.
