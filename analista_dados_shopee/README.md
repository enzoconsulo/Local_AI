# 📊 Estúdio Shopee DW & Cérebro IA

**Data Warehouse + Conselho de IA Autônomo** para Fazendas de Impressão 3D que vendem na Shopee.

O sistema extrai os seus dados da Shopee, calcula o custo real de fabricação (filamento, energia, refugo), audita a sua loja com um "Conselho de Administração" de IA (CFO, CMO, COO), sugere e aplica promoções de forma autônoma, e deixa você conversar com os seus próprios dados em linguagem natural.

---

## ✅ Pré-requisitos

Antes de começar, confirme que você tem instalado:

- **Docker Desktop** (aberto e rodando)
- **Python 3.10+**
- Uma chave grátis da **[Groq](https://console.groq.com/keys)** (para o chat rápido)
- *(Opcional)* Uma conta na **RunPod** e credenciais da **Shopee Open API v2**, se quiser usar o Cérebro IA pesado e a sincronização real

---

## 🚀 Guia Rápido: Como Rodar o Sistema (Primeira Instalação)

Abra o terminal **na pasta raiz do projeto** (a pasta onde está o `docker-compose.yml`) e siga os passos na ordem exata.

### Passo 0 — Configurar as chaves
Crie um arquivo chamado **`CHAVES_DADOS.env`** na raiz do projeto. O modelo completo, com todas as variáveis explicadas, está na seção [⚙️ Variáveis de Ambiente](#️-variáveis-de-ambiente-chaves_dadosenv) mais abaixo.

### Passo 1 — Subir o banco de dados (Docker)
```bash
docker compose --env-file CHAVES_DADOS.env up -d
docker compose --env-file CHAVES_DADOS.env ps

```

Espere o `cofre_shopee` aparecer com status **healthy**.

> ⚠️ **Use sempre a flag `--env-file CHAVES_DADOS.env**` nos comandos do Docker Compose deste projeto — sem ela, variáveis como `DB_PORT` e `TZ` não chegam ao `docker-compose.yml` corretamente. Veja o motivo no item 1 de [Pontos de Atenção](https://www.google.com/search?q=%23%EF%B8%8F-pontos-de-aten%C3%A7%C3%A3o--erros-conhecidos).

### Passo 2 — Preparar o Python (ambiente virtual)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt

```

### Passo 3 — Validar o coração do sistema

```bash
python test_db.py

```

Se aparecerem **15 itens** listados (14 tabelas + a view `vw_saude_produto`), o seu banco nasceu perfeitamente com as 3 migrations aplicadas.

### Passo 4 — *(Opcional)* Painel visual do banco — pgAdmin

1. Acesse `http://localhost:5050`
2. Login: o e-mail/senha que você definiu em `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` (no modelo abaixo: `admin@estudio.com` / `admin`)
3. **Add New Server** → aba *General* → Name: `Shopee DW`
4. Aba *Connection*:
* Host name/address: `postgres_cofre`
* Port: `5432`
* Username / Password: os mesmos valores do `CHAVES_DADOS.env`
* Marque **Save password**



### Passo 5 — Ligar a aplicação

```bash
streamlit run data_app.py

```

O sistema abre no navegador, liga o motor de IA (`llm.py`) em segundo plano automaticamente, e o painel fica pronto para uso.

> ⚠️ Se aparecer **"Falha no Boot da IA (Timeout)"**, veja o item 2 e 3 de [Pontos de Atenção](https://www.google.com/search?q=%23%EF%B8%8F-pontos-de-aten%C3%A7%C3%A3o--erros-conhecidos) — há dois detalhes para revisar antes do `llm.py` subir corretamente.

---

## 🔄 Como Reiniciar o Sistema (Uso Diário)

Se você já fez a instalação inicial acima e apenas desligou o computador, o processo para ligar o sistema no dia a dia é muito mais rápido. Abra o terminal na raiz do projeto e rode:

**1. Ligar o Banco de Dados (Apenas se o Docker não iniciar sozinho)**

```bash
docker compose --env-file CHAVES_DADOS.env start

```

*(Nota: O comando `start` apenas "acorda" o banco de dados que você já havia criado. Se preferir, basta abrir o aplicativo do Docker Desktop e dar "Play" no container lá dentro).*

**2. Ativar o Python e iniciar a aplicação**

```bash
# No Windows:
.venv\Scripts\activate

# Inicie o painel visual
streamlit run data_app.py

```

---

## 🏗️ Arquitetura do Projeto

```
estudio-shopee-dw/                  ← pasta raiz (abra o terminal aqui)
├── CHAVES_DADOS.env                ← suas chaves e senhas (Passo 0)
├── docker-compose.yml
├── requirements.txt
├── test_db.py
├── llm.py                          ← roteador de IA (ver item 3 dos Pontos de Atenção)
├── data_app.py                     ← ponto de entrada do Streamlit
├── init_db/
│   ├── 01_schema.sql
│   ├── 02_atualizacao_ia_avancada.sql
│   └── 03_migration_performance.sql
├── utils/
│   ├── db_pool.py                  ← pool de conexões compartilhado
│   └── shopee_core.py              ← cliente assinado da Shopee API v2
├── workers/
│   ├── sync_catalogo.py
│   ├── sync_pedidos.py
│   └── sync_trafego_ads.py
└── pages/
    ├── 1_🏭_Engenharia_de_Fabrica.py
    ├── 2_🔄_Sincronizacao.py
    ├── 3_🧠_Cerebro_IA.py
    └── 4_💬_Chat_Assistente.py

```

> 💡 Os nomes em `pages/` seguem a convenção do Streamlit: o número define a ordem no menu lateral, e o texto após o emoji é o rótulo exibido.

### 🧠 O Roteador de IA — `llm.py`

Atua como o coração inteligente da máquina, rodando localmente na porta `8000` via **LiteLLM**. A aplicação nunca fala diretamente com os provedores de nuvem — ela fala com a porta 8000, que roteia para dois "cérebros":

* **`chat-rapido`** — Groq (Llama 3.3 70B). Respostas em milissegundos; é o agente Text-to-SQL da aba de Chat.
* **`cerebro-dados`** — Qwen 2.5 32B (AWQ), hospedado numa GPU RunPod de 24GB VRAM. Ativado só para as auditorias preditivas pesadas do Cérebro IA.

### 🗄️ O Banco de Dados (PostgreSQL + Migrations)

A pasta `init_db/` define a base como um Data Warehouse relacional de E-commerce + Indústria:

| Arquivo | O que faz |
| --- | --- |
| `01_schema.sql` | Cria as 13 tabelas base: materiais, máquinas, catálogo, pedidos, escrow, tráfego, ads, controle de sync e log de ações. |
| `02_atualizacao_ia_avancada.sql` | Adiciona estrelas, likes, prazo de envio, estoque de variação, taxa de refugo, estoque físico de material, motivo de cancelamento, custo de frete reverso, e cria a tabela `fato_promocoes_ativas` (14ª tabela). |
| `03_migration_performance.sql` | Rastreamento de ações por variação (`model_id`), índices de performance para o dossiê da IA, e a view `vw_saude_produto` (KPIs em tempo real por variação). |

**Numa instalação nova**, o Docker executa os 3 arquivos automaticamente, em ordem, na primeira vez que o container sobe (volume vazio). **Se você já tinha um banco rodando** e está só atualizando o projeto, as migrations `02` e `03` precisam ser aplicadas manualmente — instruções de como fazer isso estão no topo do próprio `03_migration_performance.sql` (é seguro rodá-lo mais de uma vez).

### 🤖 Os Workers (`workers/`)

Scripts isolados que batem na Shopee Open API v2 para extrair dados sem travar a interface:

* `sync_catalogo.py` — anúncios, variações, reputação (likes/estrelas) e estoque virtual.
* `sync_pedidos.py` — histórico de vendas e lucro líquido real do módulo de Repasse (Escrow).
* `sync_trafego_ads.py` — jornada do cliente, abandono de carrinho, impressões e cliques patrocinados.

### 🔌 Código Compartilhado (`utils/`)

* `db_pool.py` — pool de conexões PostgreSQL thread-safe (evita abrir/fechar uma conexão a cada interação do Streamlit), com helpers prontos (`query_df`, `query_one`, `execute`, `bulk_insert`).
* `shopee_core.py` — assinatura HMAC das chamadas à Shopee API v2, e as funções atuadoras (`atualizar_preco_shopee`, `criar_promocao_shopee`, `criar_combo_shopee`) usadas pelo Cérebro IA.

> 📝 Nota: as páginas mais novas (Cérebro IA) já usam o pool compartilhado de `utils/db_pool.py`. A página de Engenharia de Fábrica ainda abre/fecha uma conexão direta por requisição — funciona, mas é menos eficiente; migrar para o pool é uma melhoria futura simples.

---

## 🕹️ Manual do Usuário

A interface é dividida em 4 setores, acessíveis pelo menu lateral:

### 1️⃣ Engenharia de Fábrica (`1_🏭_Engenharia_de_Fabrica.py`)

Onde o mundo físico se conecta ao digital.

* **Filamentos & Embalagens:** cadastre o material, custo por KG/unidade e o estoque físico atual — a IA usa isso para prever rupturas.
* **Máquinas 3D:** custo da tarifa de energia por hora.
* **Mapeamento de Peças:** associe cada anúncio/variação da Shopee à máquina e ao material, com peso (g), tempo de impressão (min) e a **Taxa de Refugo (%)**. O sistema calcula o custo de fabricação real, já absorvendo as falhas de impressão.

### 2️⃣ Sincronização (`2_🔄_Sincronizacao.py`)

Um único botão faz uma varredura **Delta** automática: o sistema sabe exatamente onde parou da última vez e busca apenas o que falta, fatiando a pesquisa em blocos de 14 dias para não estourar os limites da API da Shopee.

### 3️⃣ Cérebro IA & Atuador (`3_🧠_Cerebro_IA.py`)

O motor preditivo e de atuação — onde as decisões financeiras são tomadas.

* **Pré-análise sem LLM:** antes de gastar uma chamada de IA, o sistema calcula um **score de urgência (0–100)** por variação (ROAS<1×, material acabando em <7 dias, lucro negativo, queda de vendas >30%...) e dispara **alertas críticos automáticos** para os casos óbvios.
* **Processamento em lotes:** os produtos mais urgentes são enviados primeiro ao Qwen 32B (RunPod), em lotes de até 8 — se a RunPod der timeout, os críticos já foram analisados.
* **Conselho de Administração:** cada produto recebe um relatório em 3 abas — **CFO** (margem e lucro real), **CMO** (tráfego, conversão, ROAS, abandono de carrinho) e **COO** (capacidade de fábrica e autonomia de estoque em dias).
* **Camada de segurança:** antes de mostrar o botão de aprovação, o sistema bloqueia sugestões absurdas em código Python (ex: variação de preço acima de 80%, ou previsão de vendas maior do que a fábrica consegue produzir) — sem depender só do LLM "obedecer" o prompt.
* **Feedback Loop:** compara a projeção feita na última decisão aprovada com o resultado real 7 dias depois, por variação (não mais por produto inteiro — ações de uma cor não "vazam" para a cor irmã).
* **Atuador:** ao aprovar, o Python chama a Shopee API de verdade (`atualizar_preco_shopee`, `criar_promocao_shopee` ou `criar_combo_shopee`) e grava a decisão no Diário de Bordo (`log_acoes_shopee`).

### 4️⃣ Assistente de Chat (`4_💬_Chat_Assistente.py`)

Sua ferramenta de consulta diária (Text-to-SQL) usando o modelo `chat-rapido` (Groq/Llama 3.3 70B).

* Botões de Análise Rápida: lucratividade dos últimos 7 dias, palavras-chave de Ads que mais consomem orçamento, ranking de reputação, e resumo das últimas ações aprovadas.
* Pergunte livremente, ex: *"Quais variações tiveram mais de 100 visitas e nenhuma venda?"* — o LLM escreve o SQL, o sistema executa (limitado a 50 linhas por segurança) e devolve a resposta já mastigada.

---

## ⚙️ Variáveis de Ambiente (`CHAVES_DADOS.env`)

Crie este arquivo na raiz do projeto com a seguinte estrutura:

```env
# ==========================================
# POSTGRESQL (BANCO DE DADOS)
# ==========================================
POSTGRES_USER=admin_shopee
POSTGRES_PASSWORD=sua_senha_blindada
POSTGRES_DB=estudio_shopee
DB_HOST=localhost
DB_PORT=5433
TZ=America/Sao_Paulo

# ==========================================
# PGADMIN (PAINEL VISUAL — OPCIONAL)
# ==========================================
PGADMIN_DEFAULT_EMAIL=admin@estudio.com
PGADMIN_DEFAULT_PASSWORD=admin

# ==========================================
# SHOPEE OPEN API V2
# ==========================================
SHOPEE_PARTNER_ID=seu_partner_id
SHOPEE_PARTNER_KEY=sua_partner_key
SHOPEE_SHOP_ID=seu_shop_id
SHOPEE_REFRESH_TOKEN=seu_token_de_acesso

# ==========================================
# INTELIGÊNCIAS ARTIFICIAIS
# ==========================================
GROQ_API_KEY=gsk_sua_chave_groq
RUNPOD_API_KEY=sua_chave_runpod
ENDPOINT_ID_RUNPOD_DADOS=id_da_sua_maquina_qwen_32b_no_runpod
ENDPOINT_ID_RUNPOD_vLLM=id_de_outra_maquina_se_existir

```

| Variável | Obrigatória? | Para quê serve |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | Credenciais do banco — usadas pelo Docker e por todos os scripts Python. |
| `DB_HOST` | ✅ | `localhost`, já que o Postgres roda no Docker com a porta exposta. |
| `DB_PORT` | ✅ | Porta exposta no host. Use `5433` (ou outra livre) se você já tiver um PostgreSQL local na porta `5432` padrão. |
| `TZ` | ✅ | Fuso horário do container Postgres. |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | ⬜ só se for usar o pgAdmin | Login do painel visual em `localhost:5050`. |
| `SHOPEE_PARTNER_ID/KEY`, `SHOPEE_SHOP_ID`, `SHOPEE_REFRESH_TOKEN` | ✅ para sincronizar | Credenciais da Shopee Open API v2, usadas em `utils/shopee_core.py`. |
| `GROQ_API_KEY` | ✅ | Chave do Groq, usada pelo `chat-rapido`. |
| `RUNPOD_API_KEY` | ✅ para o Cérebro IA | Chave da RunPod. |
| `ENDPOINT_ID_RUNPOD_DADOS` | ✅ para o Cérebro IA | ID do endpoint Qwen 2.5 32B usado pela página 3. |
| `ENDPOINT_ID_RUNPOD_vLLM` | ⬜ opcional | Reservado para outro modelo/app que compartilhe o mesmo `llm.py`; não é usado pelas páginas deste projeto. |

---

## ⚠️ Pontos de Atenção / Erros Conhecidos

Revisando os arquivos do projeto, encontrei os pontos abaixo que vale corrigir ou ter em mente antes de rodar tudo:

1. **Docker Compose não lê variáveis de `CHAVES_DADOS.env` para o próprio `docker-compose.yml`.**
O `env_file:` dentro de cada serviço só injeta variáveis **dentro do container** — mas o `${DB_PORT}`, `${TZ}`, `${POSTGRES_USER}` e `${POSTGRES_DB}` usados em `ports:`, `environment:` e `healthcheck:` são substituídos pelo *próprio Compose*, que por padrão só lê um arquivo chamado exatamente `.env`. Como o projeto usa `CHAVES_DADOS.env`, essas substituições ficam vazias.
**Solução:** sempre rodar `docker compose --env-file CHAVES_DADOS.env <comando>` (já aplicado no Guia Rápido acima).
2. **`data_app.py` procura o `llm.py` uma pasta acima do que deveria.**
`data_app.py` calcula `ROOT_DIR = CURRENT_DIR.parent`, assumindo que ele mesmo vive uma pasta abaixo da raiz. Mas `test_db.py`, as páginas em `pages/` e os scripts em `utils/`/`workers/` todos assumem uma estrutura **plana**, com `data_app.py`, `llm.py` e `CHAVES_DADOS.env` na mesma pasta raiz.
**Solução:** mantenha `data_app.py` e `llm.py` na mesma pasta (estrutura sugerida na árvore acima) e troque, em `data_app.py`:
```python
ROOT_DIR = CURRENT_DIR.parent

```


por:
```python
ROOT_DIR = CURRENT_DIR

```


3. **O arquivo `llm.py` ainda não existe — só um rascunho pendente de mesclagem.**
O arquivo `mesclar_esse_arquivo_com_o_llmpy.txt` (o próprio nome já diz: "mesclar esse arquivo com o llm.py") é a base para o roteador de IA, mas antes de salvá-lo como `llm.py` na raiz, ajuste duas coisas para alinhar com o restante do projeto:
* Ele lê um arquivo chamado **`CHAVES.env`** — troque para **`CHAVES_DADOS.env`**.
* Ele exige as variáveis **`GROQ`** e **`RUNPOD_KEY`** — troque para **`GROQ_API_KEY`** e **`RUNPOD_API_KEY`**, que são os nomes usados em `CHAVES_DADOS.env` e em todo o resto do código.
* O arquivo `to_add_MAIN_CHAVES.txt` é só um lembrete avulso (`ENDPOINT_ID_RUNPOD_DADOS=...`) — essa variável já está no modelo de `CHAVES_DADOS.env` acima, então esse `.txt` pode ser apagado.


4. **Falta a dependência `tabulate` no `requirements.txt`.**
A página de Chat (`4_💬_Chat_Assistente.py`) usa `df_resultado.to_markdown()`, que exige o pacote `tabulate` — ele não está listado em `requirements.txt` e a página vai quebrar na primeira pergunta que retornar uma tabela.
**Solução:** adicione `tabulate` ao `requirements.txt` (ou instale manualmente, como já indicado no Passo 2).
5. **Contagem de tabelas do `test_db.py` estava desatualizada.**
O README anterior dizia "13 tabelas". Depois das migrations `02` (que cria `fato_promocoes_ativas`) e `03` (que cria a view `vw_saude_produto`), o total correto é **14 tabelas + 1 view = 15 itens**, já corrigido no Guia Rápido acima.
6. **Nome do modelo Groq no README anterior estava errado.**
O README antigo chamava o modelo leve de `chat-leve` — o nome real configurado e usado pelo código (em `4_💬_Chat_Assistente.py` e no roteador) é **`chat-rapido`**, já corrigido acima.
7. **`uf_destino` pode não estar recebendo a sigla do estado.**
Em `sync_pedidos.py`, `uf_destino` é preenchido com `order.get("region", "BR")`. O campo `region` da Shopee normalmente devolve o **código do país** (`BR`), não a sigla do estado (`SP`, `RJ`...). Se quiser granularidade por estado, verifique no payload de `get_order_detail` se existe um campo como `recipient_address.state` e ajuste a extração.
8. **`DATABASE_URL`, `LOG_LEVEL` e `STREAMLIT_SERVER_PORT` no `CHAVES_DADOS.env` não são lidos por nenhum script atualmente.** Não fazem mal nenhum mantidos ali, só não têm efeito — `STREAMLIT_SERVER_PORT`, em especial, só funcionaria se fosse exportada no terminal antes do `streamlit run`, e não apenas guardada no `.env`.

---

## 🧯 Problemas Comuns

| Sintoma | Causa provável |
| --- | --- |
| `docker compose ps` nunca fica `healthy` | Porta `DB_PORT` já em uso por outro Postgres local — troque para `5433` ou outra porta livre. |
| `Falha no Boot da IA (Timeout)` no Streamlit | `llm.py` não existe ainda na raiz, ou as chaves do Groq/RunPod estão erradas/vazias — veja os itens 2 e 3 acima. |
| Erro `ModuleNotFoundError: tabulate` no Chat | Falta instalar o pacote — veja o item 4 acima. |
| `Falha ao conectar no PostgreSQL` nas páginas do Streamlit | Confirme que o Docker está rodando (`docker compose ps`) e que `DB_PORT`/`DB_HOST` no `CHAVES_DADOS.env` batem com o que está exposto no `docker-compose.yml`. |

---

Desenvolvido para automatizar o sucesso. 🏭📈