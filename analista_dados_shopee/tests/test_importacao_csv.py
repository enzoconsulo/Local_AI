import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1]
page_path = root / "pages" / "2_🔄_Sincronizacao.py"

spec = importlib.util.spec_from_file_location("sincronizacao", page_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

assert hasattr(module, "carregar_dataframe_limpo")
assert hasattr(module, "processar_arquivos_marketing")
print("Importação do módulo de sincronização OK")
