from functools import lru_cache

from .config import settings


@lru_cache
def get_llm():
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.llm_model, temperature=0)
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=settings.llm_model, temperature=0)
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=settings.llm_model, base_url=settings.ollama_base_url, temperature=0)
    raise ValueError(f"unknown provider {settings.llm_provider}")
