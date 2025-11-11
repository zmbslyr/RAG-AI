from app.core.db import client_openai

def create_embedding(text: str, model: str = "text-embedding-3-large"):
    return client_openai.embeddings.create(model=model, input=text).data[0].embedding

def chat_completion(messages, model: str = "gpt-4o", tools=None, tool_choice=None):
    return client_openai.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
    )
