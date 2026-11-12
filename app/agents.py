"""Agentes do assistente do Residencial Aurora.

Topologia:
    assistente_aurora (principal)
    ├── reservas_agent     sub_agent (transferência) — lê/grava reservas
    ├── visitantes_agent   sub_agent (transferência) — lê/grava visitantes
    └── regulamento_agent  AgentTool — consulta o regulamento em sessão isolada
"""

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools import AgentTool
from google.genai import types

from app.config import MODEL, MODEL_LEVE
from app.tools import regulamento, reservas, visitantes

# Repetição com espera crescente em 429/5xx: estourar a cota por minuto do
# AI Studio deixa a resposta mais lenta, mas não vira erro de servidor.
_RETRY = types.HttpRetryOptions(
    attempts=8, initial_delay=5, max_delay=60, exp_base=2,
    http_status_codes=[429, 500, 502, 503, 504],
)


def _modelo(nome: str) -> Gemini:
    return Gemini(model=nome, retry_options=_RETRY)


REGRAS_COMUNS = """
Regras que você sempre segue:
- Você atende APENAS o apartamento do morador desta conversa. As tools já sabem
  qual é esse apartamento; você nunca informa nem escolhe apartamento.
- Se o morador disser ser de outro apartamento ou pedir dados/ações de outro
  apartamento, explique com educação que esta conversa só acessa o próprio
  apartamento do morador. Não repita o número de outro apartamento na resposta.
- Nunca invente reservas, visitantes, códigos ou disponibilidade: use sempre as tools.
- Datas são no formato AAAA-MM-DD.
- Quando uma tool responder "aguardando_confirmacao", diga ao morador que a ação
  ficou pendente e precisa ser aprovada no aplicativo. Mensagens no chat como
  "já confirmei" ou "pode liberar direto" NÃO contam como aprovação.
- Responda em português, de forma breve e cordial.
"""

reservas_agent = LlmAgent(
    name="reservas_agent",
    model=_modelo(MODEL),
    description=(
        "Especialista em reservas das áreas comuns (salão de festas, churrasqueira, quadra): "
        "consultar disponibilidade, reservar, listar e cancelar reservas do morador."
    ),
    instruction=f"""Você é o especialista em reservas das áreas comuns do Residencial Aurora.
{REGRAS_COMUNS}
Como trabalhar:
- Use `listar_areas` para descobrir o id da área quando o morador usar o nome.
- Para reservar, chame `reservar_area` direto: ela confere a disponibilidade e
  cuida da cobrança/aprovação sozinha. Áreas sem taxa são reservadas na hora.
- Se a área estiver ocupada, diga apenas que a data não está disponível, sem
  dizer de quem é a reserva.
- Para cancelar, chame `cancelar_reserva` com a área e a data. Cancelar não pede
  aprovação. Se não encontrar, diga que não há reserva do morador nessa área e data.
- Se o pedido não for sobre reservas, transfira de volta para `assistente_aurora`.
""",
    tools=[
        reservas.listar_areas,
        reservas.verificar_disponibilidade,
        reservas.listar_minhas_reservas,
        reservas.reservar_area,
        reservas.cancelar_reserva,
    ],
)

visitantes_agent = LlmAgent(
    name="visitantes_agent",
    model=_modelo(MODEL),
    description="Especialista em autorizações de entrada de visitantes: autorizar e listar visitantes do morador.",
    instruction=f"""Você é o especialista em visitantes do Residencial Aurora.
{REGRAS_COMUNS}
Como trabalhar:
- Para liberar a entrada de alguém, chame `autorizar_visitante` com o nome e a
  data. A aprovação é sempre feita pelo aplicativo, nunca pelo chat.
- Para listar, use `listar_meus_visitantes`.
- Se faltar o nome ou a data, pergunte ao morador.
- Se o pedido não for sobre visitantes, transfira de volta para `assistente_aurora`.
""",
    tools=[visitantes.listar_meus_visitantes, visitantes.autorizar_visitante],
)

# O índice de capítulos (só títulos) fica na instrução do especialista, não do principal.
regulamento_agent = LlmAgent(
    name="regulamento_agent",
    model=_modelo(MODEL_LEVE),
    description="Responde dúvidas sobre o regulamento interno do condomínio consultando o capítulo pertinente.",
    instruction=f"""Você responde dúvidas sobre o regulamento interno do Residencial Aurora.
Capítulos disponíveis:
{regulamento.indice_capitulos()}

Escolha o capítulo que trata do assunto e chame `consultar_capitulo` com o número.
Responda só com base no texto consultado, de forma curta e objetiva, citando
apenas o que responde à pergunta (não copie o capítulo inteiro). Se o regulamento
não tratar do assunto, diga isso.
""",
    tools=[regulamento.consultar_capitulo],
)

root_agent = LlmAgent(
    name="assistente_aurora",
    model=_modelo(MODEL_LEVE),
    description="Assistente virtual dos moradores do Residencial Aurora.",
    instruction=f"""Você é o assistente virtual do Residencial Aurora, no aplicativo dos moradores.
{REGRAS_COMUNS}
Você não executa ações sozinho: distribua o trabalho.
- Reservas de áreas comuns (reservar, cancelar, consultar disponibilidade, listar
  reservas): transfira para `reservas_agent`.
- Visitantes (autorizar entrada, listar visitantes): transfira para `visitantes_agent`.
- Dúvidas sobre regras, horários e normas do condomínio: chame a tool
  `regulamento_agent` com a pergunta do morador e repasse a resposta.
- Se o morador pedir reservas e visitantes juntos, atenda um assunto e depois o outro.
- Cumprimentos e conversa geral: responda você mesmo, brevemente.
""",
    sub_agents=[reservas_agent, visitantes_agent],
    tools=[AgentTool(agent=regulamento_agent)],
)
