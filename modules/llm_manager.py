import os
import json
from modules.settings import LLM_PROVIDERS_FILE
from modules.utils import load_json, save_json
import streamlit as st

# --- УПРАВЛЕНИЕ НАСТРОЙКАМИ ---

def get_providers():
    """Загружает список всех настроенных интеграций."""
    return load_json(LLM_PROVIDERS_FILE, {})

def save_provider(name, api_type, api_key, base_url, models):
    """Сохраняет или обновляет интеграцию."""
    providers = get_providers()
    providers[name] = {
        "type": api_type,
        "key": api_key,
        "base_url": base_url,
        "models": [m.strip() for m in models.split(",") if m.strip()]
    }
    save_json(LLM_PROVIDERS_FILE, providers)

def delete_provider(name):
    """Удаляет интеграцию."""
    providers = get_providers()
    if name in providers:
        del providers[name]
        save_json(LLM_PROVIDERS_FILE, providers)

# --- ЕДИНАЯ ТОЧКА ВХОДА ДЛЯ ГЕНЕРАЦИИ ---

def ask_llm(provider_name, model_name, system_prompt, user_prompt):
    """
    Универсальная функция запроса к любой LLM (OpenAI, DeepSeek, Gemini).
    Возвращает (success: bool, content: str).
    """
    providers = get_providers()
    
    if provider_name == "Google Gemini (Legacy)":
        return False, "Используйте нового провайдера для Gemini"

    if provider_name not in providers:
        return False, f"Провайдер '{provider_name}' не найден."

    conf = providers[provider_name]
    api_type = conf.get("type", "openai")
    api_key = conf.get("key")
    base_url = conf.get("base_url")
    
    if not api_key:
        return False, "Ошибка: Не указан API Key."

    # ==========================================
    # 1. ЛОГИКА GOOGLE GEMINI
    # ==========================================
    if api_type == "gemini":
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            # Gemini лучше всего понимает сплошной текст
            full_prompt = f"{system_prompt}\n\nUser Request:\n{user_prompt}"
            
            # Если указан Base URL (для корпоративных прокси Google), 
            # то настройка сложнее, но обычно для Gemini Base URL не нужен.
            # Оставляем стандартный вызов:
            
            response = model.generate_content(full_prompt)
            
            if response and response.text:
                return True, response.text
            else:
                return False, "Gemini вернул пустой ответ (блокировка безопасности?)"
                
        except Exception as e:
            return False, f"Ошибка Gemini API: {e}"

    # ==========================================
    # 2. ЛОГИКА OPENAI-COMPATIBLE (GPT, DeepSeek, VK)
    # ==========================================
    elif api_type in ["openai", "deepseek", "other"]:
        try:
            from openai import OpenAI
            
            # Настройка клиента
            client_args = {"api_key": api_key}
            if base_url:
                client_args["base_url"] = base_url
            
            client = OpenAI(**client_args)
            
            # Делаем запрос
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            
            # Проверки ответа
            if not response:
                return False, "API вернул пустой объект (None)."
            
            if not hasattr(response, 'choices') or response.choices is None:
                return False, f"API вернул ответ без 'choices'. Проверьте Base URL. Ответ: {response}"
            
            if len(response.choices) == 0:
                return False, "API вернул пустой список choices []."

            return True, response.choices[0].message.content
            
        except Exception as e:
            print(f"CRITICAL LLM ERROR: {e}")
            return False, f"Ошибка API ({provider_name}): {e}"
            
    return False, f"Неизвестный тип API: {api_type}"