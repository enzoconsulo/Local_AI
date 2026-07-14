"""
cerebro/
========
Núcleo do Conselho de Administração IA (CFO, CMO, COO) + Atuador Shopee.

Arquitetura em camadas — cada módulo tem uma responsabilidade única:

    config.py        Configuração OpenAI, constantes e classificação de ações.
    heuristicas.py   Camada determinística pura (sem banco, sem rede):
                     scores, previsões, elasticidade, clusters, evidência.
    dossie.py        Extração do Data Warehouse (views da migração 12) e
                     montagem do dossiê analítico por variação.
    memoria.py       Persistência analítica: fingerprint, cache semântico,
                     checkpoint retomável, avaliação de ações maduras.
    motor_ia.py      Comunicação com a API OpenAI: prompt, lotes, validação
                     e normalização da saída do modelo.
    atuador.py       Execução de ações aprovadas na API Shopee + diário de bordo.
    orquestrador.py  Fluxo completo de uma auditoria (7d ou 30d).

A página Streamlit (pages/3_🧠_Cerebro_IA.py) contém apenas interface.
"""
