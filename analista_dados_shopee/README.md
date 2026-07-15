# 📊 Estúdio Shopee DW & Cérebro IA

Data Warehouse + análise local + IA para lojas Shopee de impressão 3D. O sistema
sincroniza catálogo, pedidos e repasse (escrow) pela API oficial, importa as
planilhas do Seller Center (tráfego, ads, visão geral), calcula lucro real por
produto (material + taxas) e recomenda/executa ações na loja — boost grátis,
voucher, promoção, combo e preço — com previsões e consequências explícitas.

---

## 🚀 Como rodar (1 comando — serve para a 1ª vez E para o dia a dia)

Pré-requisitos: **Docker Desktop** aberto e **Python 3.10+** instalado.

No PowerShell, dentro da pasta `analista_dados_shopee`:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

O script detecta sozinho em qual cenário você está:

| Cenário | O que ele faz |
|---|---|
| **Primeira vez** | Cria o `CHAVES_DADOS.env` a partir do exemplo e o abre no Bloco de Notas para você preencher (rode o script de novo depois de salvar). Na segunda chamada: cria o venv, instala as dependências, sobe o banco no Docker, aplica **todas** as migrações e abre a aplicação. |
| **Rotina** | Sobe o Docker (se estiver parado), pula a instalação (só reinstala se o `requirements.txt` mudou), confere migrações pendentes em ~1s e abre a aplicação. |

A aplicação abre em **http://localhost:8501** (pgAdmin opcional em `localhost:5050`).
Para encerrar: `Ctrl+C` no terminal. O banco continua de pé no Docker (não perde nada).

> Também funciona a partir da raiz do repositório: `powershell -ExecutionPolicy Bypass -File .\run_local.ps1`
> (o script da raiz delega para este).

---

## 🔐 O que preencher no `CHAVES_DADOS.env`

| Variável | Obrigatória | Para quê |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | Banco local (qualquer valor seu — é criado do zero). |
| `DB_HOST=localhost` / `DB_PORT=5433` | ✅ | Onde o app encontra o banco do Docker. |
| `SHOPEE_PARTNER_ID` / `SHOPEE_PARTNER_KEY` / `SHOPEE_SHOP_ID` / `SHOPEE_REFRESH_TOKEN` | ✅ | Shopee Open API v2 (app *seller in-house* em open.shopee.com). O refresh token é renovado e regravado automaticamente. |
| `OPENAI_API_KEY` | ✅ para Cérebro e Chat | Análise estratégica (pág. 3) e assistente de dados (pág. 4). |
| `OPENAI_MODEL_7D` / `OPENAI_MODEL_30D` | ✅ | Modelos por horizonte (padrão `gpt-5.4` / `gpt-5.5`). |
| `GROQ_API_KEY` | ⬜ | Legado do chat antigo; não é mais necessária para o fluxo principal. |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | ⬜ | Só se for usar o pgAdmin em `localhost:5050`. |

---

## 🗺️ As páginas (menu lateral)

| Página | O que faz | Custo de IA |
|---|---|---|
| **📊 Visão Central** | Tudo num lugar: KPIs (bruto vs líquido real), funil com gargalo, saúde da conta (API), **boost grátis** (5 itens/4h), **voucher de checkout**, radar de views/curtidas e plano de ação com consequências e previsões. | **R$ 0** (100% local) |
| **🏭 Engenharia de Fábrica** | Cadastro fino de materiais, máquinas, tempo de impressão e refugo (opcional — o mapeamento rápido fica na pág. 💰). | R$ 0 |
| **🔄 Sincronização** | API (catálogo + pedidos + escrow) e upload das planilhas do Seller Center, com proteção contra arquivo repetido e períodos sobrepostos. | R$ 0 |
| **🧠 Cérebro IA** | Auditoria estratégica via OpenAI com cache semântico (só paga pelo produto que MUDOU), previsões determinísticas como âncora e execução de ações aprovadas. | Pago por uso |
| **💬 Chat Assistente** | Perguntas livres sobre seus dados (text-to-SQL read-only via OpenAI). | Pago por uso |
| **🧵 Mapeamento Insumos** | Vínculo detalhado insumo ↔ produto. | R$ 0 |
| **💰 Lucro Real** | Mapeie custo em 2 passos (filamentos com preço do kg + peso por produto, com foto) e veja o lucro líquido real de cada produto com 1 botão de sync. | R$ 0 |

---

## 📅 Rotina semanal recomendada (10 minutos)

1. Rode o `run_local.ps1` e abra a **📊 Visão Central** — a seção 1 mostra o que está desatualizado (semáforo) e o passo a passo exato de cada exportação.
2. Exporte as 3 planilhas do Seller Center (links prontos na própria página):
   - **Visão Geral** (Dados → Painel → Exportar, 30 dias) → página 2;
   - **Tráfego orgânico** (Dados → Produtos → Performance → Exportar) → página 2, com o mesmo período do filtro;
   - **Ads** (Central de Anúncios → Dados Gerais → Exportar; + GMV Max Detail se usar; nunca o arquivo *Ad Group*) → página 2.
3. Clique nos botões de API da Visão Central: **saúde da conta** e **snapshot do radar** (1 clique cada).
4. Confira o plano de ação (seção 8) e o boost (seção 5) — ambos grátis.
5. Quando quiser o parecer estratégico completo: página 🧠.

**Períodos:** exporte sempre janelas fechadas e consistentes (ex.: 7 dias, seg→dom).
A página 2 avisa se o período novo cruzar um antigo.

---

## 🧯 Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| Script para em "Banco nao ficou saudavel" | Porta 5433 ocupada ou Docker sem recursos. Diagnóstico: `docker logs cofre_shopee`. |
| `Falha ao conectar no PostgreSQL` nas páginas | Docker parado (`docker compose ps`) ou `DB_PORT`/senha do env não batem com o container. |
| Páginas 3/4 pedem chave | Preencha `OPENAI_API_KEY` no `CHAVES_DADOS.env` e reinicie o script. |
| "As views de pré-agregação não existem" | Rode `python init_db/aplicar_migrations.py` (o `run_local.ps1` já faz isso a cada início). |
| Sync da Shopee falha na hora | Refresh token expirado de vez — gere um novo na Open Platform e atualize o env (renovações normais são automáticas). |

---

## 🏗️ Estrutura do projeto

```text
analista_dados_shopee/
├── run_local.ps1              # UM script: primeira vez + rotina (detecção automática)
├── data_app.py                # home do Streamlit
├── pages/
│   ├── 0_📊_Visao_Central.py  # painel central + ações (boost, voucher, saúde)
│   ├── 1_🏭_Engenharia_de_Fabrica.py
│   ├── 2_🔄_Sincronizacao.py
│   ├── 3_🧠_Cerebro_IA.py
│   ├── 4_💬_Chat_Assistente.py
│   ├── 5_🧵_Mapeamento_Insumos.py
│   └── 6_💰_Lucro_Real.py     # mapeamento de custo em 2 passos + lucro por produto
├── cerebro/                   # núcleo analítico (sem Streamlit): dossiê, heurísticas,
│   │                          # motor OpenAI, cache semântico, atuador, consultor SQL
├── workers/
│   ├── sync_catalogo.py       # catálogo + fotos via API
│   ├── sync_pedidos.py        # pedidos + escrow (lucro real)
│   ├── sync_saude_conta.py    # saúde da conta + views/curtidas via API
│   └── importar_planilhas.py  # processadores das planilhas do Seller Center
├── utils/                     # pool de conexões, motor da Shopee API v2
├── init_db/                   # migrações 01..15 + aplicar_migrations.py (idempotente)
└── requirements.txt
```

---

Desenvolvido para transformar dados de e-commerce em decisões inteligentes e automatizadas. 🏭📈
