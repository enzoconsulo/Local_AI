### **Nome do Projeto: Ecossistema Inteligente de E-commerce & Automação 3D**

**Visão Geral**
Este projeto é uma solução completa de **Data Warehouse e Conselho de Administração IA** projetada para otimizar fazendas de impressão 3D com vendas na Shopee. O sistema integra inteligência analítica profunda com agentes autônomos para gestão de estoque, precificação dinâmica e auditoria financeira.

**Principais Pilares do Ecossistema:**

* **Data Warehouse Shopee (DW):** Um pipeline robusto que extrai dados em tempo real da Shopee (pedidos, tráfego, anúncios) e os consolida em um banco PostgreSQL, permitindo uma análise clara da lucratividade real (margem, refugo de impressão e custos operacionais).
* **Conselho de Administração IA:** Uma arquitetura de agentes (CFO, CMO, COO) que utiliza modelos locais (via LiteLLM e RunPod) para realizar auditorias preditivas, sugerindo estratégias de precificação, criação de combos e promoções automáticas.
* **Assistente de Código (Local & Copilot-like):** Integração de LLM local configurada para atuar como um *pair programmer* no VS Code (via extensão **Continue**), permitindo suporte ao desenvolvimento, refatoração de código e automação de tarefas com total privacidade e velocidade.
* **Motor Multimodal (Generativo):** Módulo de geração de imagens integrando **fal.ai**, focado em criar artes promocionais, protótipos de produtos e materiais de marketing personalizados de forma automatizada para os anúncios da sua loja.
* **Engenharia de Fábrica Digital:** Sistema que vincula a realidade física ao digital, calculando o custo exato de produção (tempo de máquina, consumo de filamento e taxa de falha) para que a IA tome decisões baseadas na viabilidade real da sua linha de montagem.

---

## ▶️ Execução local a partir da pasta raiz

Use estes comandos no diretório base do projeto: [README.md](README.md)

### 1) Primeira vez

No PowerShell, a partir da pasta raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Verifique se os arquivos abaixo existem:
- [CHAVES.env](CHAVES.env) com as chaves de GROQ e RunPod
- [analista_dados_shopee/CHAVES_DADOS.env](analista_dados_shopee/CHAVES_DADOS.env) com as credenciais da Shopee e do PostgreSQL

Se o arquivo de dados da Shopee não existir, ele será criado automaticamente ao executar o script abaixo:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

Este script faz tudo para você:
- cria o ambiente virtual, se necessário
- instala as dependências
- sobe o PostgreSQL e o pgAdmin com Docker
- valida a conexão com o banco
- inicia o motor de IA

### 2) Próximas vezes

```powershell
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

### 3) Rodar os módulos separadamente

Em terminais diferentes:

```powershell
python llm.py
```

```powershell
streamlit run analista_dados_shopee/data_app.py
```

Para o módulo de imagens:

```powershell
cd estudio_shopee
streamlit run app.py
```

---

## 🧱 Requisitos

- Docker Desktop instalado e rodando
- Python 3.10+
- Acesso às chaves da Shopee Open API
- Chaves de GROQ e RunPod preenchidas em [CHAVES.env](CHAVES.env)
- Arquivo [analista_dados_shopee/CHAVES_DADOS.env](analista_dados_shopee/CHAVES_DADOS.env) preenchido corretamente

---

## ✅ Validação rápida

Depois de subir tudo, rode:

```powershell
python analista_dados_shopee/test_db.py
```

Se a conexão estiver boa, o sistema já está preparado para a análise e sincronização.

---

**Por que este projeto é único?**
Diferente de sistemas de gerenciamento comuns, este ecossistema não apenas organiza dados, ele **atua sobre eles**. Ao conectar a precisão do SQL com o raciocínio do modelo de linguagem, o sistema bloqueia decisões de risco (camada de segurança em Python) e executa alterações na loja automaticamente através da API v2 da Shopee, criando um ciclo de melhoria contínua (Feedback Loop).