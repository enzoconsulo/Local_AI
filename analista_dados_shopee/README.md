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
| `OPENAI_MODEL_7D` / `OPENAI_MODEL_30D` | ✅ | Modelos por horizonte (padrão `gpt-5.6-luna` / `gpt-5.6-terra` — melhor custo/qualidade em jul/2026). |
| `GROQ_API_KEY` | ⬜ | Legado do chat antigo; não é mais necessária para o fluxo principal. |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | ⬜ | Só se for usar o pgAdmin em `localhost:5050`. |
| `TUNEL_SSH_HOST` / `TUNEL_SSH_USUARIO` / `TUNEL_SSH_CHAVE` / `TUNEL_PORTA_LOCAL` | ⬜ (recomendado) | Túnel SSH até a VM de IP fixo, o IP cadastrado na whitelist da Shopee. Vazio = chamada direta pelo IP da sua internet. |
| `TOKEN_VIA_PI` | ⬜ (recomendado se o BTT Pi roda o auto-boost) | `biqu@<ip-do-pi>`: o token da loja é do serviço 24/7 do Pi e este app só pega emprestado por SSH. Vazio = este app tem autorização própria. |

---

## 🔑 Conexão com a Shopee: IP fixo e token automáticos

A Shopee só aceita chamadas de IPs cadastrados em **Open Platform Console > App list > IP Address Whitelist**, e o IP da internet de casa muda sozinho. Com `TUNEL_SSH_HOST` preenchido, **toda** chamada à Shopee sai por um túnel SSH (SOCKS5 em `127.0.0.1:1080`) até a VM Oracle de IP fixo — a mesma solução do auto-boost do BTT Pi. Só o IP da VM precisa estar na whitelist.

- **O túnel se gerencia sozinho:** qualquer chamada à Shopee (app, worker ou tarefa agendada) sobe o `ssh` em segundo plano se ele não estiver de pé, e sobe de novo se cair. O `run_local.ps1` confere o IP de saída a cada início. Log do ssh: `tunel_shopee.log`.
- **Chave SSH:** precisa estar acessível só pelo seu usuário, senão o OpenSSH do Windows a ignora (`bad permissions`). Padrão: `~/.ssh/id_shopee_tunnel`.
- **Token emprestado pelo Pi (`TOKEN_VIA_PI`, recomendado):** o serviço 24/7 do auto-boost no BTT Pi é o único dono da autorização da loja e renova a cada 4h. Este app, que roda de vez em quando, pede por SSH um access_token válido por 1h+ (`scripts/emprestar_token.py` no Pi) e nunca renova sozinho. Pode ficar meses sem rodar, existe uma autorização só e os dois apps não se atrapalham. Requisitos: Pi ligado e alcançável, e a chave SSH deste PC autorizada no Pi. Nesse modo o `pegar_token.py` se recusa a rodar; se a autorização morrer, reautorize no Pi (`bash scripts/atalhos/gerar_token.sh`).
- **Token próprio (`TOKEN_VIA_PI` vazio):** o `refresh_token` vence em 30 dias sem uso. O app renova a cada uso e a tarefa agendada **"Shopee - manter token vivo"** (registrada pelo `run_local.ps1`) renova uma vez por dia com o app fechado (log: `manter_token.log`). Se a autorização morrer, rode `.\.venv\Scripts\python.exe pegar_token.py`: você faz login no navegador, cola a URL do Google, e ele grava o token no `CHAVES_DADOS.env` e testa a conexão sozinho.

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
| Log `Your refresh_token expired` | A autorização da loja morreu. Token próprio: rode `.\.venv\Scripts\python.exe pegar_token.py`. Com `TOKEN_VIA_PI`: reautorize no Pi (`bash scripts/atalhos/gerar_token.sh`). |
| Log `O Pi (...) não emprestou o token` / `Não consegui pedir o token ao Pi` | `Permission denied` = chave SSH deste PC não autorizada no Pi; `timed out` = Pi desligado ou com outro IP na rede (fixe o IP no roteador ou use o IP do Tailscale). |
| Log `Request Source IP (...) is undeclared` | A chamada saiu por um IP fora da whitelist. Preencha `TUNEL_SSH_HOST`; se já está preenchido, confira se o IP da VM está na whitelist. |
| Log `Túnel de IP fixo não subiu` | Veja `tunel_shopee.log`: `Permission denied` = chave errada ou não autorizada na VM; `bad permissions` = chave acessível por outros usuários; `timed out` = VM desligada ou porta 22 bloqueada. |

---

## 🏗️ Estrutura do projeto

```text
analista_dados_shopee/
├── run_local.ps1              # UM script: primeira vez + rotina (detecção automática)
├── pegar_token.py             # autoriza a loja (login no navegador) e grava o token no env
├── manter_token.py            # renovação diária do token (tarefa agendada do Windows)
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
├── utils/                     # pool de conexões, motor da Shopee API v2, túnel de IP fixo
├── init_db/                   # migrações 01..15 + aplicar_migrations.py (idempotente)
└── requirements.txt
```

---

Desenvolvido para transformar dados de e-commerce em decisões inteligentes e automatizadas. 🏭📈
