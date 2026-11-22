from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from .config import settings


@lru_cache
def get_llm() -> BaseChatModel:
    cfg = settings.llm
    if cfg.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model_name=cfg.model, temperature=cfg.temperature)  # type: ignore[call-arg]
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=cfg.model, temperature=cfg.temperature)
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=cfg.model,
        base_url=cfg.base_url or "http://localhost:11434",
        temperature=cfg.temperature,
    )
