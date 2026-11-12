"""Utilidades compartilhadas pelas tools."""

from datetime import date

from google.adk.tools import ToolContext

# Chave do state da sessão gravada uma única vez em POST /sessoes.
CHAVE_APARTAMENTO = "apartamento"


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    """Garantia 2: o apartamento usado pelas tools vem SEMPRE do state da sessão.

    Nenhuma tool aceita apartamento como parâmetro; o modelo não tem como
    escolher outro apartamento, diga o morador o que disser.
    """
    apartamento = tool_context.state.get(CHAVE_APARTAMENTO)
    if not apartamento:
        raise ValueError("Sessão sem apartamento associado.")
    return str(apartamento)


def validar_data(data: str) -> str | None:
    """Devolve a data normalizada (AAAA-MM-DD) ou None se inválida."""
    try:
        return date.fromisoformat(data.strip()).isoformat()
    except (ValueError, AttributeError):
        return None


def pedir_ou_ler_confirmacao(
    tool_context: ToolContext, acao: str, detalhes: dict, hint: str
) -> str:
    """Garantia 1: pede confirmação ao sistema (não à conversa).

    Retorna:
      "pendente"  -> confirmação solicitada; a tool deve parar sem gravar.
      "aprovada"  -> o morador aprovou pela rota de confirmações.
      "negada"    -> o morador negou; a tool não grava nada.

    A aprovação só existe quando o ADK reexecuta a tool com
    `tool_context.tool_confirmation` preenchido, o que acontece apenas quando a
    API envia o FunctionResponse de `adk_request_confirmation`. Nada que o
    morador escreva no chat preenche esse campo.
    """
    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        tool_context.request_confirmation(
            hint=hint, payload={"acao": acao, "detalhes": detalhes}
        )
        return "pendente"
    return "aprovada" if confirmacao.confirmed else "negada"
