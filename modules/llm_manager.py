import streamlit as st
from cryptography.fernet import Fernet
from modules.db_manager import SessionLocal
from modules.models import User, LLMProvider
from modules.settings import ENCRYPTION_KEY # ВАЖНО: Добавь это в settings.py!

# --- ШИФРОВАНИЕ API КЛЮЧЕЙ ---
# Создаем объект шифратора один раз при импорте модуля
try:
    cipher_suite = Fernet(ENCRYPTION_KEY)
except ValueError:
    # На случай, если ключ в настройках кривой
    print("ВНИМАНИЕ: Ошибка инициализации Fernet. Проверьте ENCRYPTION_KEY в settings.py")
    cipher_suite = None

def encrypt_token(plain_text_token: str) -> str:
    """Шифрует API ключ перед сохранением в БД"""
    if not plain_text_token or not cipher_suite:
        return plain_text_token
    # Шифруем строку (превращая её в байты и обратно)
    return cipher_suite.encrypt(plain_text_token.encode('utf-8')).decode('utf-8')

def decrypt_token(encrypted_token: str) -> str:
    """Расшифровывает API ключ для отправки запроса к LLM"""
    if not encrypted_token or not cipher_suite:
        return encrypted_token
    try:
        # Пытаемся расшифровать
        return cipher_suite.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
    except Exception:
        # Если расшифровать не вышло (например, в БД лежит старый открытый ключ)
        # Просто возвращаем его как есть, чтобы не сломать старые интеграции
        return encrypted_token


# --- HELPER ДЛЯ ПОЛУЧЕНИЯ ID ПОЛЬЗОВАТЕЛЯ ---
def _get_current_user_id(db):
    if "username" not in st.session_state:
        return None
    user = db.query(User).filter(User.username == st.session_state["username"]).first() #
    return user.id if user else None

# --- УПРАВЛЕНИЕ НАСТРОЙКАМИ (ТЕПЕРЬ ЧЕРЕЗ БД) ---

def get_providers():
    """Загружает список интеграций пользователя из БД."""
    db = SessionLocal() #
    try:
        user_id = _get_current_user_id(db)
        if not user_id: return {}
        
        providers_db = db.query(LLMProvider).filter(LLMProvider.user_id == user_id).all()
        
        # Формируем словарь в том же формате, в каком он был раньше (чтобы не ломать UI)
        return {
            p.name: {
                "type": p.api_type,
                # ВАЖНО: Мы НЕ расшифровываем ключ для UI, чтобы он не светился на фронте!
                # Он нужен только в момент отправки запроса в ask_llm.
                "key": p.api_key, 
                "base_url": p.base_url,
                "models": [m.strip() for m in p.models.split(",") if m.strip()]
            } for p in providers_db
        }
    finally:
        db.close()

def save_provider(name, api_type, api_key, base_url, models_str):
    """Сохраняет или обновляет интеграцию в БД."""
    db = SessionLocal() #
    try:
        user_id = _get_current_user_id(db)
        if not user_id: return

        # 1. ШИФРУЕМ КЛЮЧ ПЕРЕД СОХРАНЕНИЕМ
        safe_api_key = encrypt_token(api_key)

        # Ищем, есть ли уже провайдер с таким именем у этого юзера
        prov = db.query(LLMProvider).filter(LLMProvider.user_id == user_id, LLMProvider.name == name).first()
        
        if prov:
            # Обновляем существующий
            prov.api_type = api_type
            prov.api_key = safe_api_key # Сохраняем зашифрованную версию
            prov.base_url = base_url
            prov.models = models_str
        else:
            # Создаем новый
            new_prov = LLMProvider(
                user_id=user_id,
                name=name,
                api_type=api_type,
                api_key=safe_api_key, # Сохраняем зашифрованную версию
                base_url=base_url,
                models=models_str
            )
            db.add(new_prov)
            
        db.commit()
    except Exception as e:
        print(f"Ошибка сохранения провайдера: {e}")
        db.rollback()
    finally:
        db.close()

def delete_provider(name):
    """Удаляет интеграцию из БД."""
    db = SessionLocal() #
    try:
        user_id = _get_current_user_id(db)
        if not user_id: return
        
        prov = db.query(LLMProvider).filter(LLMProvider.user_id == user_id, LLMProvider.name == name).first()
        if prov:
            db.delete(prov)
            db.commit()
    except Exception as e:
        print(f"Ошибка удаления провайдера: {e}")
        db.rollback()
    finally:
        db.close()


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
    
    # 2. РАСШИФРОВЫВАЕМ КЛЮЧ ПЕРЕД ИСПОЛЬЗОВАНИЕМ
    encrypted_key = conf.get("key")
    api_key = decrypt_token(encrypted_key)
    
    base_url = conf.get("base_url")
    
    if not api_key:
        return False, "Ошибка: Не указан API Key."

    # ==========================================
    # 1. ЛОГИКА GOOGLE GEMINI
    # ==========================================
    if api_type == "gemini":
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=api_key) # Передаем чистый расшифрованный ключ
            model = genai.GenerativeModel(model_name)
            
            full_prompt = f"{system_prompt}\n\nUser Request:\n{user_prompt}"
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
            
            client_args = {"api_key": api_key} # Передаем чистый расшифрованный ключ
            if base_url:
                client_args["base_url"] = base_url
            
            client = OpenAI(**client_args)
            
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            
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