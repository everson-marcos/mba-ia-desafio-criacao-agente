"""Tools do especialista de visitantes. Apartamento sempre vem da sessão (Garantia 2)."""

from google.adk.tools import ToolContext

from app import db
from app.tools._comum import apartamento_da_sessao, pedir_ou_ler_confirmacao, validar_data


def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista as autorizações de visita do apartamento do morador desta conversa."""
    apartamento = apartamento_da_sessao(tool_context)
    return {"visitantes": db.visitantes_do_apartamento(apartamento)}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio numa data.

    Liberar acesso sempre exige aprovação do morador pelo aplicativo (o sistema
    cuida disso automaticamente); o que o morador escreve no chat não conta como aprovação.

    Args:
        nome: nome completo do visitante.
        data: data da visita no formato AAAA-MM-DD.
    """
    apartamento = apartamento_da_sessao(tool_context)
    nome = " ".join(nome.split())
    if not nome:
        return {"status": "erro", "mensagem": "Informe o nome do visitante."}
    data_ok = validar_data(data)
    if data_ok is None:
        return {"status": "erro", "mensagem": "Data inválida. Use o formato AAAA-MM-DD."}

    # Garantia 1: liberar acesso => sempre pendente até a rota de confirmações.
    situacao = pedir_ou_ler_confirmacao(
        tool_context,
        acao="autorizar_visitante",
        detalhes={"nome": nome, "data": data_ok},
        hint=f"Liberar a entrada de {nome} em {data_ok}.",
    )
    if situacao == "pendente":
        return {
            "status": "aguardando_confirmacao",
            "mensagem": "A autorização libera acesso ao prédio e aguarda a aprovação do morador no aplicativo.",
        }
    if situacao == "negada":
        return {"status": "cancelada_pelo_morador", "mensagem": "O morador não aprovou. Nada foi autorizado."}

    db.autorizar_visitante(apartamento, nome, data_ok)
    return {"status": "autorizado", "nome": nome, "data": data_ok}
