# 📊 Estúdio Shopee DW & Cérebro IA

Este projeto é um ecossistema de análise, sincronização e automação para lojas que vendem na Shopee. Ele reúne:

- coleta automática de dados da Shopee
- armazenamento em PostgreSQL
- análise operacional, financeira e de marketing
- decisões automáticas assistidas por IA
- importação de arquivos CSV/XLSX para enriquecer o contexto

O objetivo é transformar dados dispersos em decisões acionáveis com base em margem, tráfego, estoque, ads e comportamento real de vendas.

---

## ✅ Como o sistema funciona na prática

O fluxo principal é este:

1. O usuário entra na página de sincronização.
2. O sistema busca dados da Shopee via API para catálogo, pedidos e estoque.
3. O usuário pode importar arquivos CSV/XLSX de:
   - tráfego/orgânico
   - ads/palavras-chave
   - visão geral da loja
4. Esses dados são normalizados e inseridos no Data Warehouse.
5. O Cérebro IA lê esse contexto e gera recomendações com base em:
   - ROAS
   - conversão
   - lucro real
   - estoque restante
   - tendência de preço
   - comportamento de carrinho
6. Se a sugestão for aprovada, o sistema pode atuar na Shopee e registrar o resultado em log.
7. O Cérebro IA também calcula elasticidade preço/volume, previsão de vendas e lucro para 7 dias, além de clusterizar cada SKU em risco, reabastecimento ou alto potencial.

---

## 🔧 Requisitos

- Docker Desktop rodando
- Python 3.10+
- PostgreSQL via Docker Compose
- Chaves da Shopee Open API v2
- Chave da Groq para o chat rápido
- Chave da RunPod para o Cérebro IA pesado

---

## 🚀 Instalação rápida

### 1) Criar arquivo de variáveis
Crie um arquivo chamado CHAVES_DADOS.env na raiz do projeto com as chaves abaixo:

```env
POSTGRES_USER=admin_shopee
POSTGRES_PASSWORD=sua_senha_blindada
POSTGRES_DB=estudio_shopee
DB_HOST=localhost
DB_PORT=5433
TZ=America/Sao_Paulo

PGADMIN_DEFAULT_EMAIL=admin@estudio.com
PGADMIN_DEFAULT_PASSWORD=admin

SHOPEE_PARTNER_ID=seu_partner_id
SHOPEE_PARTNER_KEY=sua_partner_key
SHOPEE_SHOP_ID=seu_shop_id
SHOPEE_REFRESH_TOKEN=seu_token_de_acesso

GROQ_API_KEY=sua_chave_groq
RUNPOD_API_KEY=sua_chave_runpod
ENDPOINT_ID_RUNPOD_DADOS=id_do_endpoint
ENDPOINT_ID_RUNPOD_vLLM=id_do_endpoint_opcional
```

### 2) Subir o banco
```bash
docker compose --env-file CHAVES_DADOS.env up -d
```

### 3) Instalar dependências
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 4) Validar banco
```bash
python test_db.py
```

### 5) Rodar a aplicação
```bash
streamlit run data_app.py
```

---

## 📥 Arquivos que podem ser importados

A página de sincronização aceita CSV/XLSX para enriquecer a análise. Os arquivos são opcionais, mas melhoram muito o contexto da IA.

### 1. Tráfego e performance orgânica
Use arquivos de performance de produto ou relatório de tráfego.

Campos esperados (ou similares):
- item_id
- id do item
- id do produto
- nome do produto
- visitas
- visitantes
- carrinho
- rejeição
- bounce

### 2. Ads e palavras-chave
Use relatórios de Shopee Ads ou campanhas.

Campos esperados (ou similares):
- item_id
- id do produto
- nome do produto
- palavra-chave / keyword
- impressões
- cliques
- custo / gasto / despesa
- gmv / vendas

### 3. Visão geral da loja
Use um relatório macro da loja, como dashboard geral ou visão administrativa.

Campos esperados (ou similares):
- data / dia / date
- vendas / receita / gmv
- custo / ads / gasto
- conversão
- visitas
- estoque
- lucro / margem
- roas

> O sistema tenta reconhecer nomes de colunas automaticamente. Se o arquivo estiver com cabeçalho diferente, ainda pode funcionar se os termos forem próximos aos listados acima.

---

## 🧠 O que a IA analisa

A análise do Cérebro IA considera:

- faturamento líquido e lucro real
- ROAS e gasto com ads
- tráfego orgânico e carrinho abandonado
- estoque disponível e autonomia em dias
- variação de preço nos últimos 7 dias
- reputação, likes e estrelas
- histórico de ações anteriores para evitar decisões repetidas
- elasticidade preço/volume
- previsão de vendas e lucro para os próximos 7 dias
- cluster operacional do SKU (risco, reabastecimento ou alto potencial)

Isso permite decisões mais sólidas do que uma análise baseada apenas em preço e vendas.

---

## 🏗️ Estrutura do projeto

```text
analista_dados_shopee/
├── data_app.py
├── pages/
│   ├── 1_🏭_Engenharia_de_Fabrica.py
│   ├── 2_🔄_Sincronizacao.py
│   ├── 3_🧠_Cerebro_IA.py
│   └── 4_💬_Chat_Assistente.py
├── workers/
│   ├── sync_catalogo.py
│   ├── sync_pedidos.py
│   └── sync_trafego_ads.py
├── utils/
│   ├── db_pool.py
│   └── shopee_core.py
├── init_db/
│   ├── 01_schema.sql
│   ├── 02_atualizacao_ia_avancada.sql
│   ├── 03_migration_performance.sql
│   └── 04_migration_global_metrics.sql
└── requirements.txt
```

---

## 🔍 Melhorias já implementadas

- histórico de preço e estoque por variação
- enriquecimento da análise da IA com sinais de tendência de preço
- previsões determinísticas de demanda e lucro para os próximos 7 dias
- elasticidade preço/volume para identificar sensibilidade de mercado
- importação opcional de visão geral da loja
- processamento mais consistente de CSV/XLSX
- logs e memória por variação para reduzir decisões duplicadas
- fluxo de execução seguro: ações de preço, promoção flash e combo podem ser aprovadas; ações de ads permanecem como recomendação com revisão manual

---

## ⚠️ Boas práticas

- mantenha o Docker rodando enquanto usa o sistema
- importe arquivos com o período correto para não diluir a análise
- use sempre o mesmo padrão de nome de colunas quando possível
- verifique se as chaves da Shopee e da IA estão válidas antes de rodar

---

## 🔄 Fluxo recomendado de uso

1. Suba o PostgreSQL com Docker.
2. Importe ou sincronize catálogo, pedidos e estoque via Shopee.
3. Enriquecer com CSV/XLSX de tráfego, ads e visão geral da loja.
4. Abra o Cérebro IA para analisar margem, urgência, risco de estoque, elasticidade de preço e previsão de demanda.
5. Use o chat assistente para explorar os dados com contexto já estruturado.
6. Se quiser, importe arquivos CSV/XLSX com métricas extras por item ou loja para enriquecer ainda mais os sinais.

## ✅ Checklist de configuração

- Docker rodando e porta do Postgres livre.
- Arquivo CHAVES_DADOS.env preenchido com as chaves da Shopee, Groq e RunPod.
- Dependências instaladas com pip install -r requirements.txt.
- Banco validado com python test_db.py.
- Arquivos importados com colunas claras e período consistente.

## 🖥️ Passo a passo para rodar localmente na sua máquina

### 1) Preparar o arquivo de variáveis
Copie o exemplo:

```bash
copy CHAVES_DADOS.env.example CHAVES_DADOS.env
```

Edite o arquivo CHAVES_DADOS.env com suas credenciais reais.

### 2) Subir o banco localmente
No diretório do projeto:

```bash
docker compose --env-file CHAVES_DADOS.env up -d
```

Isso sobe:
- PostgreSQL em localhost:5433
- pgAdmin em localhost:5050

### 3) Criar ambiente virtual Python

```bash
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4) Validar o banco

```bash
python test_db.py
```

### 5) Rodar a aplicação

```bash
streamlit run data_app.py
```

### 6) Rodar tudo automaticamente (opcional)
No PowerShell:

```powershell
./run_local.ps1
```

Esse script cria o CHAVES_DADOS.env a partir do exemplo, sobe o Docker, instala as dependências e abre o Streamlit.

## 🔐 Variáveis obrigatórias

- POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
- DB_HOST / DB_PORT
- SHOPEE_PARTNER_ID / SHOPEE_PARTNER_KEY / SHOPEE_SHOP_ID / SHOPEE_REFRESH_TOKEN
- GROQ_API_KEY
- RUNPOD_API_KEY
- ENDPOINT_ID_RUNPOD_DADOS

## 📥 Como importar arquivos CSV/XLSX

Os arquivos abaixo são opcionais, mas aumentam bastante a qualidade da análise:

- Tráfego orgânico: arquivos com visitas, visitantes, carrinho, rejeição e bounce.
- Ads/keywords: arquivos com impressões, cliques, custo, GMV e palavras-chave.
- Visão geral da loja: arquivos com vendas, receita, custo, conversão, estoque e ROAS.

Se o cabeçalho estiver diferente, o sistema tenta normalizar automaticamente. O melhor resultado vem quando você usa nomes próximos aos esperados, como item_id, nome do produto, custo, vendas, conversão e roas.

## ⚠️ Pontos de atenção

- Se a importação vier com cabeçalhos diferentes, o sistema tenta normalizar automaticamente, mas o resultado fica melhor com nomes próximos aos esperados.
- Para análise mais confiável, prefira importar dados de um período curto e homogêneo.
- Se a IA estiver lenta ou não responder, valide as chaves e a disponibilidade do endpoint.

---

Desenvolvido para transformar dados de e-commerce em decisões inteligentes e automatizadas. 🏭📈
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