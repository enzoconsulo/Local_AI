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

## ▶️ Como rodar (1 comando — primeira vez e rotina)

Pré-requisitos: **Docker Desktop** aberto e **Python 3.10+** instalado.

No PowerShell, na pasta raiz do projeto:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_local.ps1
```

O script detecta sozinho o cenário:

- **Primeira vez** — cria o `analista_dados_shopee/CHAVES_DADOS.env` a partir do
  exemplo e abre para você preencher (Shopee, OpenAI, senha do banco); rode o
  script de novo depois de salvar e ele faz o resto: venv, dependências, banco
  no Docker, todas as migrações e abre a aplicação.
- **Rotina** — sobe o Docker se preciso, pula instalações (só reinstala se o
  `requirements.txt` mudou) e abre a aplicação em segundos.

A aplicação abre em **http://localhost:8501**. Instruções completas, páginas e
solução de problemas: [analista_dados_shopee/README.md](analista_dados_shopee/README.md).

Para o módulo de imagens (opcional, separado):

```powershell
cd estudio_shopee
streamlit run app.py
```

---

**Por que este projeto é único?**
Diferente de sistemas de gerenciamento comuns, este ecossistema não apenas organiza dados, ele **atua sobre eles**. Ao conectar a precisão do SQL com o raciocínio do modelo de linguagem, o sistema bloqueia decisões de risco (camada de segurança em Python) e executa alterações na loja automaticamente através da API v2 da Shopee, criando um ciclo de melhoria contínua (Feedback Loop).