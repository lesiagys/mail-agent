import os
from typing import Optional, List

from langchain_openrouter import ChatOpenRouter
from langchain_core.callbacks import BaseCallbackHandler


MODEL_ALIASES = {
    "qwen-235b": "qwen/qwen3-235b-a22b",
    "qwen3.5": "qwen/qwen3.5-397b-a17b",
    "qwen3.6": "qwen/qwen3.6-27b"
}

def get_model(model='qwen3.6', temperature=0.0, top_p=None, top_k=None, callbacks: Optional[List[BaseCallbackHandler]] = None, reasoning: bool = True, provider='alibaba'):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY не задан в переменных окружения")
    kwargs = dict(model=MODEL_ALIASES.get(model, model), temperature=temperature, api_key=api_key, callbacks=callbacks)
    if not reasoning:  # отключаем thinking-режим (для простых роутеров вроде showcase)
        kwargs["reasoning"] = {"effort": "none"}
    if provider:  # жёстко закрепляем провайдера OpenRouter (без фолбэка на других)
        kwargs["openrouter_provider"] = {"order": [provider], "allow_fallbacks": False}
    return ChatOpenRouter(**kwargs)