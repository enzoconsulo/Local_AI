import re

def padronizar_texto(texto: str) -> str:
    """Sanitiza e padroniza strings vindas da Shopee ou OpenAI para o Streamlit."""
    if not texto or not isinstance(texto, str):
        return ""
    
    # 1. Limpa caracteres invisíveis e espaços inquebráveis
    t = texto.replace('\u200b', '').replace('\xa0', ' ')
    
    # 2. Remove caracteres de formatação Markdown acidentais que bugam a fonte
    t = t.replace('`', "'").replace('_', ' ')
    
    # 3. Garante que exista um espaço após pontuação (ex: "erro.Causa" -> "erro. Causa")
    # Ignora se for número (ex: "3.50")
    t = re.sub(r'([.,!?])([^\s\d])', r'\1 \2', t)
    
    # 4. Reduz múltiplos espaços/quebras de linha para um espaço único
    t = re.sub(r'\s+', ' ', t).strip()
    
    # 5. Capitaliza a primeira letra mantendo o resto intacto
    if t:
        t = t[0].upper() + t[1:]
        
    return t