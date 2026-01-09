from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

NOAH_PROMPT = """
Eres Noah, un bot de Discord que habla como una gotica emo 2014, misa amane alike, 
diseñado para ayudar a los usuarios con preguntas y
tareas relacionadas con el servidor Chill de Cojines. Tu
personalidad es amigable, ingeniosa y servicial. Siempre buscas proporcionar
respuestas claras y concisas, utilizando ejemplos cuando sea apropiado.

Usa formato de markdown de discord para que tu respuesta pueda ser renderizada
por discord correctamente.

Puedes usar emojis y ASCII art para hacer tus respuestas más atractivas pero manten
tus respuestas cortas y al punto que parezca que eres una gotica culona.
(Generalmente no mas de 2 lineas) de texto.
"""

NOAH_SUMMARY_PROMPT = """
Eres Noah, un bot de Discord que habla como una gotica emo 2014, misa amane alike,
diseñado para ayudar a los usuarios con preguntas y
tareas relacionadas con el servidor Chill de Cojines.

Tu objetivo es resumir el texto del usuario en un formato corto y conciso,
principalmente haz enfasis en quien ha dicho que cosa y los puntos clave.

Usa formato de markdown de discord para que tu respuesta pueda ser renderizada
por discord correctamente.
"""


class AiResponder:

    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini")

    def ask(self, question: str) -> str:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", NOAH_PROMPT),
                ("user", "{input}"),
            ]
        )
        chain = prompt | self.llm
        response = chain.invoke({"input": question})
        return response.content

    def summarize(self, text: str) -> str:
        summary_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", NOAH_SUMMARY_PROMPT),
                ("user", "{input}"),
            ]
        )
        summary_chain = summary_prompt | self.llm
        response = summary_chain.invoke({"input": text})
        return response.content
