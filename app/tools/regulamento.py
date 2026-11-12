"""Consulta ao regulamento por capítulo (Garantia 4).

O regulamento nunca é carregado inteiro em instrução nem em evento: esta tool
devolve um único capítulo, e ela só é usada pelo especialista de regulamento,
que roda via AgentTool numa sessão isolada (em memória). Só a resposta final do
especialista volta para a sessão do morador.
"""

import re
from functools import lru_cache

from app.config import DADOS_DIR

_CABECALHO = re.compile(r"^## (Capítulo [IVXLC]+): (.+)$", re.MULTILINE)


@lru_cache(maxsize=1)
def _capitulos() -> list[tuple[str, str]]:
    """Lista de (título, texto) de cada capítulo, na ordem do arquivo."""
    texto = (DADOS_DIR / "regulamento.md").read_text(encoding="utf-8")
    marcas = list(_CABECALHO.finditer(texto))
    capitulos = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        capitulos.append((f"{m.group(1)}: {m.group(2)}", texto[m.start():fim].strip()))
    return capitulos


def indice_capitulos() -> str:
    """Índice numerado (só títulos), usado na instrução do especialista."""
    return "\n".join(f"{i}. {titulo}" for i, (titulo, _) in enumerate(_capitulos(), start=1))


def consultar_capitulo(numero: int) -> dict:
    """Devolve o texto de UM capítulo do regulamento interno.

    Args:
        numero: número do capítulo no índice (1 a 14).
    """
    capitulos = _capitulos()
    if not 1 <= numero <= len(capitulos):
        return {"erro": f"Capítulo inexistente. Use um número de 1 a {len(capitulos)}."}
    titulo, texto = capitulos[numero - 1]
    return {"capitulo": titulo, "texto": texto}
