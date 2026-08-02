# MAPA — ia-hibrida-limpa

<!-- GERADO por _sistema/ferramentas/mapa.mjs. NÃO editar à mão — a próxima geração sobrescreve. HEAD: b3efd02 · 2026-08-02 -->

Índice denso deste projeto: o que existe, onde, e a assinatura de cada símbolo
público. **Existe para você não precisar varrer o projeto para se orientar** — ler o
código inteiro custa ~20× mais que ler isto, e é pago em toda tarefa por todo agente.

Como usar: leia este arquivo primeiro; depois abra na íntegra **só** os arquivos que
você vai modificar ou cujo comportamento interno você precisa conferir.

## Árvore

```
(raiz)  CLAUDE.md, README.md
Local_AI/  .gitignore, CHAVES.env, CHAVES.env.example, Dados+Gerais+de+Anúncios+Shopee-05_07_2026-11_07_2026.csv, PASSO_A_PASSO.md, README.md, Shop+GMV+MAX-Detail-Data-05_07_2026-11_07_2026.csv, Shopee-Ads-Ad-Group-Data-05_07_2026-11_07_2026.csv, config.yaml, enzocesarcs.shopee-shop-stats.20260614-20260713.xlsx, llm.py, llm_boot.log … (+2)
Local_AI/analista_dados_shopee/  CHAVES_DADOS.env, CHAVES_DADOS.env.example, README.md, data_app.py, docker-compose.yml, pegar_token.py, requirements.txt, run_local.ps1, test_db.py, testar_shopee.py, ultima_auditoria.json, ultima_auditoria_30d.json … (+1)
Local_AI/analista_dados_shopee/cerebro/  __init__.py, atuador.py, config.py, consultor.py, dossie.py, heuristicas.py, memoria.py, motor_ia.py, orquestrador.py
Local_AI/analista_dados_shopee/init_db/  01_schema.sql, 02_atualizacao_ia_avancada.sql, 03_migration_performance.sql, 04_migration_global_metrics.sql, 05_migration_ads_avancado.sql, 06_migration_topo_funil_organico.sql, 07_migration_trava_idempotencia.sql, 08_migration_memoria_analitica.sql, 09_migration_granularidade_importacao.sql, 10_migration_cache_semantico_ia.sql, 11_migration_checkpoint_execucao_ia.sql, 12_migration_sync_lotes_e_views.sql … (+6)
Local_AI/analista_dados_shopee/pages/  0_📊_Visao_Central.py, 1_🏭_Engenharia_de_Fabrica.py, 2_🔄_Sincronizacao.py, 3_🧠_Cerebro_IA.py, 4_💬_Chat_Assistente.py, 5_🧵_Mapeamento_Insumos.py, 6_💰_Lucro_Real.py
Local_AI/analista_dados_shopee/tests/  test_cerebro_correlacoes.py, test_importacao_csv.py
Local_AI/analista_dados_shopee/utils/  db_pool.py, padronizar_texto.py, shopee_core.py, ui.py
Local_AI/analista_dados_shopee/workers/  importar_planilhas.py, sync_catalogo.py, sync_pedidos.py, sync_pos_venda.py, sync_saude_conta.py
Local_AI/dados_teste/  Dados+Gerais+de+Anúncios+Shopee-18_04_2026-18_07_2026.csv, Shop+GMV+MAX-Detail-Data-18_04_2026-18_07_2026.csv, enzocesarcs.shopee-shop-stats.20260618-20260717.xlsx, parentskudetail.20260618_20260717.xlsx
Local_AI/estudio_shopee/  app.py, gerador_anuncio.py, how_to_use.md, requirements.txt
Local_AI/estudio_shopee/backup/  estudio_terminal_backup.py
Local_AI/estudio_shopee/tests/  test_gerador_anuncio.py
Local_AI/image/proximos_passos/  1784073301368.png
_gestao/  ANALISE.md, DECISOES.md, ESPECIFICACAO.md, MAPA.md, PLANO.md, PROGRESSO.md, equipe.json
_gestao/pesquisas/  2026-07-28-limites-anuncio-shopee.md
_gestao/tarefas/  T-001-cliente-openai-visao.md, T-002-prompt-copywriting-anuncio.md, T-003-ui-anuncio-shopee.md, T-004-persistencia-anuncio.md, T-005-testes-gerador-anuncio.md, T-006-documentacao-anuncio.md
```

## Símbolos públicos por arquivo

### `Local_AI/analista_dados_shopee/cerebro/atuador.py`
- `salvar_log_acao(item_id: int, model_id: int, tipo_acao: str, detalhe: str, impacto_json: dict, status: st…)`
- `processar_acao_api(acao: str, dados_var: dict, analise_var: dict, novo_preco: float, id_execucao_origem: str…)`

### `Local_AI/analista_dados_shopee/cerebro/config.py`
- `MigracaoPendenteError` *(classe)*
- `memoizar_ttl(ttl_segundos: int, reavaliar_falsos: bool = True)`
- `modelo_para(horizonte: str)`
- `reasoning_para(horizonte: str)`
- `horizonte_em_dias(horizonte: str)`
- `classificar_modo_execucao(acao: str)`
- `rotulo_acao(acao: str)`
- `explicar_acao(acao: str)`

### `Local_AI/analista_dados_shopee/cerebro/consultor.py`
- `validar_sql_somente_leitura(query: str)` — ══════════════════════════════════════════════════════════════════════════════ SQL SOMENTE LEITURA ══════════════════════════════════════════════════…
- `executar_sql_leitura(query: str, max_linhas: int = 50)`
- `obter_contexto_estrategico()` — ══════════════════════════════════════════════════════════════════════════════ CONTEXTO ESTRATÉGICO E PROMPT DE SISTEMA ═════════════════════════════…
- `construir_prompt_sistema()`
- `chamar_chat(mensagens: list[dict], telemetria: dict | None = None)`
- `extrair_sql(texto: str)`
- `_tabela_para_modelo(df: pd.DataFrame)`
- `executar_turno(historico: list[dict], ao_evento=None, telemetria: dict | None = None)`

### `Local_AI/analista_dados_shopee/cerebro/dossie.py`
- `_schema_dossie_disponivel()`
- `garantir_tabela_historico_variacoes()`
- `_peso_rateio_variacao(vendas_30d_var: int, vendas_30d_item: int, qtd_variacoes: int)`
- `_ratear_int(valor, peso: float)`
- `_ratear_float(valor, peso: float)`
- `alocar_inteiro_por_peso(total: int, pesos: list[float])`
- `_alocar_rateios_por_item(registros)`
- `classificar_curva_abc(dossie: list[dict])`
- `gerar_dossie_produtos_com_memoria()`
- `_montar_dados_variacao(r, alocacoes: dict | None = None)`

### `Local_AI/analista_dados_shopee/cerebro/heuristicas.py`
- `calcular_score_urgencia(d: dict)` — ══════════════════════════════════════════════════════════════════════════════ PRIORIZAÇÃO ══════════════════════════════════════════════════════════…
- `calcular_dias_estoque(d: dict)`
- `calcular_elasticidade_preco_volume(preco_hoje: float, preco_7d: float, vendas_7d: int, vendas_antes: int)` — ══════════════════════════════════════════════════════════════════════════════ ELASTICIDADE E PREVISÃO DETERMINÍSTICA ═══════════════════════════════…
- `calcular_previsao_demanda_7d(d: dict)`
- `calcular_previsao_demanda_30d(d: dict)`
- `gerar_recomendacao_executiva(d: dict)` — ══════════════════════════════════════════════════════════════════════════════ RECOMENDAÇÃO E CLASSIFICAÇÃO ═════════════════════════════════════════…
- `classificar_cluster(d: dict)`
- `classificar_confianca_evidencia(dados: dict)`
- `intervalo_demanda_exploratorio(dados: dict, previsao: float)`
- `gerar_alertas_criticos(dossie: list[dict])` — ══════════════════════════════════════════════════════════════════════════════ ALERTAS DE REGRA DE NEGÓCIO ══════════════════════════════════════════…
- `sugerir_alavancas_vendas(d: dict)` — ══════════════════════════════════════════════════════════════════════════════ ALAVANCAS DE CRESCIMENTO (correlações medidas → ação; custo zero de IA…

### `Local_AI/analista_dados_shopee/cerebro/memoria.py`
- `_memoria_analitica_disponivel()`
- `_cache_semantico_disponivel()`
- `_checkpoint_analitico_disponivel()`
- `enriquecer_dossie_com_memoria(dossie: list[dict])` — ══════════════════════════════════════════════════════════════════════════════ ENRIQUECIMENTO DO DOSSIÊ COM A MEMÓRIA ═══════════════════════════════…
- `calcular_fingerprint_entrada(dados: dict, horizonte: str)`
- `_montar_snapshots_analiticos(horizonte: str, resultados: list[dict])`
- `_resumo_execucao(horizonte: str, resultados: list[dict], checkpoint: bool = False)`
- `persistir_auditoria_analitica(horizonte: str, resultados: list[dict], extras: dict | None = None)`
- `iniciar_ou_retomar_checkpoint(horizonte: str, total_variacoes: int, cobertura: dict,)` — ══════════════════════════════════════════════════════════════════════════════ CHECKPOINT DURÁVEL (retomada de auditoria) ═══════════════════════════…
- `persistir_lote_no_checkpoint(id_execucao: str, horizonte: str, resultados: list[dict])`
- `_resultado_de_snapshot(anterior, dados: dict, horizonte: str, retomado: bool)`
- `separar_resultados_do_checkpoint(id_execucao: str, horizonte: str, dossie: list[dict], aceitar_analise_local: bool = True,)`
- `finalizar_checkpoint(id_execucao: str, horizonte: str, resultados: list[dict], total_esperado: int, extras: di…)`
- `separar_resultados_reutilizaveis(horizonte: str, dossie: list[dict], aceitar_analise_local: bool = True,)` — ══════════════════════════════════════════════════════════════════════════════ CACHE SEMÂNTICO ENTRE EXECUÇÕES ══════════════════════════════════════…
- `avaliar_acoes_maduras(dossie_atual: list[dict])` — ══════════════════════════════════════════════════════════════════════════════ AVALIAÇÃO DE AÇÕES MADURAS (previsto vs.

### `Local_AI/analista_dados_shopee/cerebro/motor_ia.py`
- `validar_sugestao_ia(dados: dict, analise: dict)` — ══════════════════════════════════════════════════════════════════════════════ VALIDAÇÃO E CONFIGURAÇÃO ═════════════════════════════════════════════…
- `configuracao_openai_valida()`
- `resumir_memoria_para_prompt(memoria: dict | None)` — ══════════════════════════════════════════════════════════════════════════════ COMPACTAÇÃO DO PAYLOAD (menos tokens de entrada por lote) ════════════…
- `compactar_lote_por_horizonte(lote_json: list[dict], horizonte: str)`
- `construir_prompt_otimizado(horizonte: str)` — ══════════════════════════════════════════════════════════════════════════════ PROMPT ═══════════════════════════════════════════════════════════════…
- `extrair_array_json_resposta(texto: str)` — ══════════════════════════════════════════════════════════════════════════════ PARSE, FALLBACK E NORMALIZAÇÃO DA SAÍDA ══════════════════════════════…
- `gerar_fallback_lote(lote_json: list[dict], horizonte: str, motivo: str)`
- `normalizar_saida_modelo(recomendacao: dict, dados: dict)`
- `_limite_tokens_saida(horizonte: str, total_variacoes: int)` — ══════════════════════════════════════════════════════════════════════════════ CHAMADA À API OPENAI ═════════════════════════════════════════════════…
- `chamar_cerebro_openai_preditivo(lote_json: list[dict], horizonte: str = "7d", max_tentativas: int = 2, telemetria: dict |…)`
- `_variacao_para_payload(var: dict)` — ══════════════════════════════════════════════════════════════════════════════ AGRUPAMENTO, GATEKEEPER E LOTES ══════════════════════════════════════…
- `_agrupar_por_produto(dossie_completo: list[dict])`
- `_resolver_fantasma_local(p: dict, originais_por_chave: dict)`
- `_resultado_deterministico_local(p: dict, var: dict, original: dict)`
- `_dividir_lote(lote: list[dict])`
- `_executar_lote_adaptativo(lote: list[dict], horizonte: str, telemetria: dict | None, profundidade: int = 0,)`
- `_fatiar_em_lotes(produtos_ativos: list[dict], max_vars_por_lote: int)`
- `processar_em_lotes(dossie_completo: list[dict], horizonte: str, ao_concluir_lote=None, modo_economico: bool …)`

### `Local_AI/analista_dados_shopee/cerebro/orquestrador.py`
- `verificar_frescor_dados(status_boot)`
- `executar_auditoria_por_horizonte(horizonte: str, status_boot, modo_economico: bool = True)`
- `executar_analise_7_dias(status_boot)`
- `executar_analise_30_dias(status_boot)`
- `salvar_cache_em_disco(horizonte: str, resultados: list[dict])` — ══════════════════════════════════════════════════════════════════════════════ CACHE EM DISCO (sobrevive a F5 e reinício do app) ════════════════════…
- `carregar_ultima_auditoria()`

### `Local_AI/analista_dados_shopee/data_app.py`
- `_status_banco()`

### `Local_AI/analista_dados_shopee/init_db/aplicar_migrations.py`
- `_sonda_coluna(tabela: str, coluna: str)`
- `_sonda_objeto(*nomes: str)`
- `conectar()`
- `garantir_tabela_controle(cur)`
- `listar_migrations()`
- `registradas(cur)`
- `sentinela_existe(cur, arquivo: str)`
- `main()`

### `Local_AI/analista_dados_shopee/pages/0_📊_Visao_Central.py`
- `carregar_kpis_macro(dias: int = 7)`
- `carregar_funil(dias: int)`
- `carregar_frescor()`
- `carregar_saude_historico()`
- `carregar_radar_api()`
- `carregar_economia_real()`
- `carregar_fotos()`
- `carregar_dossie()`
- `_fmt_moeda(v)`
- `_fmt_moeda_md(v)`
- `_delta(atual, anterior)`
- `_consequencia(d: dict)`

### `Local_AI/analista_dados_shopee/pages/1_🏭_Engenharia_de_Fabrica.py`
- `run_query(query, params=None)` — ============================================================================== ACESSO AO POSTGRESQL — via pool compartilhado (utils/db_pool) Era a ún…
- `run_insert(query, params)`
- `run_delete(query, params)`
- `cor_hex_do_nome(nome: str)`
- `badge(texto: str, cor: str)`

### `Local_AI/analista_dados_shopee/pages/3_🧠_Cerebro_IA.py`
- `_serie_numerica(df: pd.DataFrame, coluna: str)` — ══════════════════════════════════════════════════════════════════════════════ HELPERS DE INTERFACE ═════════════════════════════════════════════════…
- `_expandir_dados_atuais(df: pd.DataFrame)`
- `_soma_com_escudo(variacoes: list[dict], campo: str)`
- `_fmt_qtd(valor)`
- `_float_ou_none(valor)`
- `_badge_urgencia(score: float)`
- `_selo_confianca(confianca: str)`
- `_situacao_simples(cluster: str)`
- `_fmt_milhar(numero: int)`
- `_consultar_ultima_execucao_db(horizonte_dias: int)`
- `_ultima_sincronizacao_dw()`
- `_composicao_cache_horizonte(horizonte: str)`
- `_painel_status_horizonte(horizonte: str, ultima_sync: datetime | None)`
- `_render_parecer_variacao(analise_var: dict)`
- `_render_cartao_acao(analise_var: dict, h: str, analises_do_horizonte: list[dict])`
- `_carregar_cache_horizonte(horizonte: str)` — ══════════════════════════════════════════════════════════════════════════════ VISÃO COMPLETA DE UM HORIZONTE (7d ou 30d) — mesma apresentação para o…
- `_render_visao_horizonte(h: str, analises_todas: list[dict], filtros: dict)`

### `Local_AI/analista_dados_shopee/pages/5_🧵_Mapeamento_Insumos.py`
- `carregar_backup_json(uploaded_file)` — ============================================================================== SEÇÃO 1 — LEITURA E NORMALIZAÇÃO DO BACKUP ===========================…
- `normalizar_texto(txt: str)`
- `score_similaridade(a: str, b: str)`
- `montar_lookup_filamentos(backup: dict)`
- `extrair_materiais_backup(backup: dict)`
- `extrair_maquinas_backup(backup: dict)`
- `determinar_material_por_produto_e_variante(backup: dict, lookup_fil: dict)`
- `montar_itens_engenharia(backup: dict)`
- `buscar_produtos_dw()`
- `buscar_materiais_dw()`
- `buscar_maquinas_dw()`
- `melhor_match_produto(nome_local: str, df_produtos: pd.DataFrame)`
- `melhor_match_variacao(variante_label: str, item_id, df_produtos: pd.DataFrame)`
- `obter_ou_criar_material(cur, id_material_existente, nome, tipo, custo_por_unidade, unidade_medida, estoque_atual,…)` — ============================================================================== SEÇÃO 3 — GRAVAÇÃO (SELECT-then-INSERT/UPDATE, sem depender de UNIQUE/…
- `obter_ou_criar_maquina(cur, id_maquina_existente, novo_nome, custo_energia_hora)`
- `salvar_engenharia(cur, model_id, id_material, id_maquina, peso_gramas, tempo_impressao_minutos, custo_embal…)`
- `renderizar_item_engenharia(m, incluir_padrao: bool, exigir_selecao_manual: bool = False)`

### `Local_AI/analista_dados_shopee/pages/6_💰_Lucro_Real.py`
- `_fmt_moeda(v)`
- `carregar_materiais()`
- `carregar_mapeamento_itens()`
- `carregar_dossie()`
- `limpar_caches()`

### `Local_AI/analista_dados_shopee/pegar_token.py` — Extrai o código do Shopee Open API v2 e o Refresh Token python pegar_token.py
- `gerar_link_autorizacao()`

### `Local_AI/analista_dados_shopee/testar_shopee.py`
- `testar_conexao()`

### `Local_AI/analista_dados_shopee/tests/test_cerebro_correlacoes.py`
- `_linha_base(**overrides)`
- `test_derivados_de_correlacao_profunda()`
- `test_pos_venda_sem_dados_fica_none()`
- `test_escudo_api_com_um_snapshot()`
- `test_item_sem_correlacoes_fica_none()`
- `test_curva_abc_por_lucro()`
- `test_alavancas_de_crescimento()`
- `test_payload_7d_compacto_com_sinais()`

### `Local_AI/analista_dados_shopee/utils/db_pool.py`
- `_build_pool()`
- `_get_pool()`
- `get_connection()`
- `query_df(sql: str, params: tuple | None = None, max_rows: int = 500)` — ── Helpers de alto nível ─────────────────────────────────────────────────────
- `query_one(sql: str, params: tuple | None = None)`
- `query_all(sql: str, params: tuple | None = None)`
- `execute(sql: str, params: tuple | None = None)`
- `bulk_insert(sql: str, rows: list[tuple], page_size: int = 1000)`
- `pool_status()` — ── Diagnóstico (útil no test_db.py e no pgAdmin) ────────────────────────────

### `Local_AI/analista_dados_shopee/utils/padronizar_texto.py`
- `padronizar_texto(texto: str)`

### `Local_AI/analista_dados_shopee/utils/shopee_core.py`
- `_trava_renovacao_entre_processos()`
- `obter_access_token()`
- `gerar_assinatura(path, access_token)`
- `_espera_retry(response, tentativa)`
- `chamar_shopee_api(path, params=None, method="GET", payload=None, max_tentativas=3)`
- `atualizar_preco_shopee(item_id, model_id, novo_preco)` — ============================================================================== FUNÇÕES ATUADORAS (Usadas pelo Cérebro IA para manipular a loja) =====…
- `criar_promocao_shopee(item_id, model_id, preco_promocional, horas_duracao=24)`
- `verificar_status_promocao(discount_id)`
- `criar_combo_shopee(item_id, percentual_desconto=10, limite_compras=100)`
- `obter_saude_conta()` — ============================================================================== SAÚDE DA CONTA (v2.account_health) — o que decide o ALCANCE orgânico d…
- `listar_boost_ativo()` — ============================================================================== BOOST DE PRODUTOS (v2.product.boost_item) — alcance GRÁTIS, 5 itens / …
- `impulsionar_itens(item_ids)`
- `_gerar_codigo_voucher()` — ============================================================================== VOUCHER DA LOJA (v2.voucher) — incentivo de checkout contra carrinho a…
- `criar_voucher_loja(nome, desconto_reais, min_gasto, usos, dias_duracao=7, codigo=None)`
- `listar_vouchers(status="ongoing")`
- `encerrar_voucher(voucher_id, ja_iniciado=True)`
- `obter_info_extra_itens(item_ids)` — ============================================================================== MÉTRICAS EXTRAS POR ITEM (v2.product.get_item_extra_info) views/curtid…
- `_promo_status_derivado(inicio, fim)` — ============================================================================== PÓS-VENDA E PROMOÇÕES (sondados ao vivo em 18/07/2026 — todos FUNCIONA…
- `_itens_de_promocao(tipo, id_promocao)`
- `listar_promocoes_loja(incluir_itens=True)`
- `listar_devolucoes(time_from=None, time_to=None)`
- `obter_rastreio_pedido(order_sn)`

### `Local_AI/analista_dados_shopee/utils/ui.py`
- `aplicar_estilo()`
- `cabecalho(icone: str, titulo: str, subtitulo: str = "")`
- `secao(numero, titulo: str, descricao: str = "")`
- `badge(texto: str, cor: str = "cinza")`
- `nota(texto: str, titulo: str = "")`

### `Local_AI/analista_dados_shopee/workers/importar_planilhas.py`
- `ArquivoLocal` *(classe)*
- `obter_ultima_sincronizacao(modulo)` — ============================================================================== CONTROLE DE SINCRONIZAÇÃO E LOTES (sys_controle_sync / sys_lotes_impor…
- `registrar_sincronizacao(modulo, data_inicio, data_fim, status, registros)`
- `fatiar_periodo(start_date, end_date, max_dias=14)`
- `calcular_hash_arquivo(uploaded_file)`
- `lote_ja_importado(modulo, hash_arquivo, periodo_inicio, periodo_fim)`
- `registrar_lote_importacao(modulo, nome_arquivo, hash_arquivo, periodo_inicio, periodo_fim, registros)`
- `buscar_importacoes_sobrepostas(modulo, periodo_inicio, periodo_fim)`
- `limpar_valor(val)` — ============================================================================== LIMPEZA E RATEIO DE VALORES ==========================================…
- `limpar_valor_opcional(val)`
- `distribuir_inteiro(total: int | None, dias: int, indice: int)`
- `distribuir_monetario(valor: float, dias: int, indice: int)`
- `granularidade_do_periodo(dias_no_periodo: int)`
- `_como_date(valor)`
- `carregar_dataframe_limpo(uploaded_file)`
- `normalizar_nome_metric(coluna)`
- `_nome_arquivo_normalizado(nome: str)`
- `processar_arquivo_global(arquivo_global)`
- `processar_trafego_organico(arquivo_trafego, data_inicio, data_fim)` — ============================================================================== PROCESSADOR: TRÁFEGO ORGÂNICO (Performance do Produto) ===============…
- `_localizar_coluna_investimento(cols: dict)` — ============================================================================== PROCESSADOR: SHOPEE ADS AVANÇADO (GMV Max + Padrão, múltiplos arquivos…
- `_e_arquivo_gmv_max_detail(nome: str)`
- `decidir_linha_gmv_max(e_arquivo_detail: bool, lote_tem_detail: bool, e_linha_loja: bool)`
- `_item_por_nome_anuncio(nome_anuncio: str, produtos_db)`
- `processar_relatorio_ads_avancado(arquivos_ads, data_inicio, data_fim)`

### `Local_AI/analista_dados_shopee/workers/sync_catalogo.py`
- `obter_lista_itens()`
- `obter_detalhes_e_variacoes(item_ids)`
- `garantir_tabela_historico_variacoes(conn)`
- `salvar_no_banco(produtos, variacoes)`
- `marcar_produtos_fora_do_ar(item_ids_ativos)`
- `sincronizar_catalogo()` — ============================================================================== FUNÇÃO EXPORTADA PARA O STREAMLIT ====================================…

### `Local_AI/analista_dados_shopee/workers/sync_pedidos.py`
- `_uf_do_pedido(order: dict)`
- `obter_pedidos_por_periodo(time_from, time_to)`
- `_ts(valor)`
- `_pedido_do_detalhe(order: dict)`
- `obter_detalhes_pedidos(order_sns)`
- `filtrar_pedidos_sem_escrow(order_sns_concluidos)`
- `obter_dados_repasse(order_sns_concluidos)`
- `salvar_transacoes_no_banco(pedidos, itens, repasses)`
- `sincronizar_pedidos(data_inicio: datetime, data_fim: datetime)` — ============================================================================== FUNÇÃO EXPORTADA PARA O STREAMLIT ====================================…

### `Local_AI/analista_dados_shopee/workers/sync_pos_venda.py`
- `_ts(epoch)`
- `enriquecer_pedidos_existentes()` — ══════════════════════════════════════════════════════════════════════════════ 1.
- `sincronizar_rastreio()` — ══════════════════════════════════════════════════════════════════════════════ 2.
- `sincronizar_devolucoes()` — ══════════════════════════════════════════════════════════════════════════════ 3.
- `sincronizar_promocoes()` — ══════════════════════════════════════════════════════════════════════════════ 4.
- `sincronizar_pos_venda(ao_progresso=None)` — ══════════════════════════════════════════════════════════════════════════════ ORQUESTRAÇÃO (função exportada para a página 2) ══════════════════════…

### `Local_AI/analista_dados_shopee/workers/sync_saude_conta.py`
- `_gravar_metricas_loja(metricas: list[tuple])`
- `sincronizar_saude_conta()`
- `sincronizar_metricas_api_produtos()`

### `Local_AI/estudio_shopee/app.py`
- `obter_sessao_rembg()`
- `_criar_sessao_http()`
- `preparar_canvas_perfeito(lista_bytes_imagens, estilo, neutralizar_cor=False)` — ================= 3. ENGENHARIA DE CANVAS (MULTI-UPLOAD MODIFICADO) =================
- `carregar_memoria(tipo)`
- `salvar_memoria(tipo, prompt)`
- `resetar_memoria(tipo)`
- `salvar_anuncio_txt(caminho_txt, anuncio)`
- `resetar_anuncio()`
- `checar_porta_8000()`
- `montar_instrucao_estilo(estilo, cenario_custom)`
- `contem_portugues(texto)`
- `gerar_prompt(historico)`
- `gerar_prompt_em_ingles(historico, max_tentativas=2)`
- `chamar_motor_imagem(endpoint, nome_motor, imagens_referencia_data_uris, prompt, console_preview, num_imagens=…)`

### `Local_AI/estudio_shopee/backup/estudio_terminal_backup.py`
- `verificar_porta(porta=8000)` — ================= INFRAESTRUTURA DE BACKGROUND =================
- `iniciar_litellm_background()`
- `salvar_sucesso(prompt_aprovado)` — ================= MEMÓRIA DE ESTILO (IN-CONTEXT LEARNING) =================
- `carregar_memoria_recente()`
- `chamar_diretor_de_arte(historico_mensagens)`
- `renderizar_imagem(imagem_b64, prompt_visual)` — ================= RENDERIZADOR (RUNPOD - CONFIG SHOPEE) =================
- `limpar_tela()` — ================= INTERFACE PRINCIPAL =================
- `main()`

### `Local_AI/estudio_shopee/gerador_anuncio.py`
- `ErroGeracaoAnuncio` *(classe)*
- `_validar_credencial()`
- `chamar_openai_visao(mensagens: list[dict], timeout: int = 60)`
- `construir_data_uri(imagem_bytes: bytes, mime_type: str = "image/jpeg")` — ── Data URI (compartilhado com app.py — não duplicar) ──────────────────────
- `_montar_texto_contexto_produto(contexto_produto: dict, historico_estilo: str)`
- `_construir_mensagens_anuncio(imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str)`
- `_validar_resposta_anuncio(resultado: dict)`
- `gerar_anuncio_shopee(imagem_bytes: bytes, contexto_produto: dict, historico_estilo: str = "")`

### `Local_AI/estudio_shopee/tests/test_gerador_anuncio.py`
- `_RespostaFake` *(classe)*
- `_resposta_openai_com_content(content, status_code=200)`
- `_mock_post_nunca_deve_ser_chamado(monkeypatch)`
- `test_chave_ausente_nao_tenta_rede(monkeypatch)`
- `test_resposta_http_de_erro(monkeypatch)`
- `test_content_nao_e_json_valido(monkeypatch)`
- `test_json_valido_faltando_chave_esperada(monkeypatch)`
- `test_caminho_feliz_retorna_anuncio_completo(monkeypatch)`

### `Local_AI/llm.py`
- `carregar_env()`
- `validar_chaves()`
- `gerar_config_yaml()`
- `iniciar_litellm()`
- `main()`

## Limites deste mapa

- Extração por padrão de linha, não por AST: declaração exportada em forma incomum
  pode não aparecer aqui. Se algo que você espera não está listado, o arquivo existe
  na árvore acima — abra e leia.
- Só símbolos de TOPO e públicos. Função interna, helper e detalhe de implementação
  ficam de fora de propósito: eles são o que você lê no arquivo quando for mexer nele.
- Descrição é a primeira frase da documentação do símbolo. O resto (parâmetros,
  casos de borda, contratos) está no arquivo.
