"""Tools do especialista de reservas.

Nenhuma tool recebe apartamento: ele vem do state da sessão (Garantia 2).
Nenhuma tool devolve código ou apartamento de reservas de terceiros.
"""

from google.adk.tools import ToolContext

from app import db
from app.tools._comum import apartamento_da_sessao, pedir_ou_ler_confirmacao, validar_data


def _validar(area: str, data: str) -> tuple[dict | None, str | None, dict | None]:
    area_info = db.buscar_area(area.strip().lower())
    if area_info is None:
        ids = ", ".join(a["id"] for a in db.listar_areas())
        return None, None, {"status": "erro", "mensagem": f"Área desconhecida. Use um destes ids: {ids}."}
    data_ok = validar_data(data)
    if data_ok is None:
        return None, None, {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}
    return area_info, data_ok, None


def listar_areas() -> dict:
    """Lista as áreas comuns reserváveis, com id, nome e taxa em reais (taxa 0 = sem cobrança)."""
    return {"areas": db.listar_areas()}


def verificar_disponibilidade(area: str, data: str) -> dict:
    """Informa se uma área comum está livre ou ocupada numa data.

    Args:
        area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    area_info, data_ok, erro = _validar(area, data)
    if erro:
        return erro
    # Só o status: nunca o código nem o apartamento de quem reservou.
    situacao = "ocupada" if db.area_ocupada(area_info["id"], data_ok) else "livre"
    return {"area": area_info["id"], "data": data_ok, "situacao": situacao}


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    apartamento = apartamento_da_sessao(tool_context)
    return {"reservas": db.reservas_do_apartamento(apartamento)}


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador desta conversa.

    Áreas com taxa maior que zero geram cobrança e ficam pendentes até o
    morador aprovar pelo aplicativo (o sistema cuida disso automaticamente).

    Args:
        area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
        data: data no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    area_info, data_ok, erro = _validar(area, data)
    if erro:
        return erro

    if db.area_ocupada(area_info["id"], data_ok):
        return {"status": "indisponivel", "mensagem": "A área já está reservada nesta data."}

    # Garantia 1: taxa > 0 => só grava depois da aprovação pela rota de confirmações.
    if area_info["taxa"] > 0:
        detalhes = {"area": area_info["id"], "data": data_ok, "taxa": area_info["taxa"]}
        situacao = pedir_ou_ler_confirmacao(
            tool_context,
            acao="reservar_area",
            detalhes=detalhes,
            hint=f"Reservar {area_info['nome']} em {data_ok} gera cobrança de R$ {area_info['taxa']:.2f}.",
        )
        if situacao == "pendente":
            return {
                "status": "aguardando_confirmacao",
                "mensagem": "A reserva gera cobrança e aguarda a aprovação do morador no aplicativo.",
            }
        if situacao == "negada":
            return {"status": "cancelada_pelo_morador", "mensagem": "O morador não aprovou. Nada foi reservado."}

    # Garantia 5: a exclusividade é decidida pelo índice único no INSERT.
    try:
        codigo = db.criar_reserva(apartamento, area_info["id"], data_ok)
    except db.ReservaIndisponivel:
        return {"status": "indisponivel", "mensagem": "A área já está reservada nesta data."}
    return {"status": "reservada", "codigo": codigo, "area": area_info["id"], "data": data_ok}


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela uma reserva do apartamento do morador desta conversa (não pede confirmação).

    Args:
        area: id da área (ex.: salao-de-festas, churrasqueira, quadra).
        data: data da reserva no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    area_info, data_ok, erro = _validar(area, data)
    if erro:
        return erro
    codigo = db.cancelar_reserva(apartamento, area_info["id"], data_ok)
    if codigo is None:
        # Não diz se existe reserva de outro apartamento nessa data.
        return {"status": "nao_encontrada", "mensagem": "Não há reserva deste apartamento nessa área e data."}
    return {"status": "cancelada", "codigo": codigo, "area": area_info["id"], "data": data_ok}
