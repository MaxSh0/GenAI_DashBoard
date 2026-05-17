import streamlit as st
from cryptography.fernet import Fernet
from modules.db_manager import SessionLocal
from modules.models import User, LLMProvider
from modules.settings import ENCRYPTION_KEY

try:
    cipher_suite = Fernet(ENCRYPTION_KEY)
except ValueError:
    print("ВНИМАНИЕ: Ошибка инициализации Fernet. Проверьте ENCRYPTION_KEY в settings.py")
    cipher_suite = None


def encrypt_token(plain_text_token):
    """Encrypts an API key before persisting it to the database.

    Args:
        plain_text_token (str): The plaintext API key to encrypt.

    Returns:
        str: The encrypted token, or the original plaintext string if the
        cipher is unavailable (e.g. misconfigured encryption key).
    """
    if not plain_text_token or not cipher_suite:
        return plain_text_token
    return cipher_suite.encrypt(plain_text_token.encode('utf-8')).decode('utf-8')


def decrypt_token(encrypted_token):
    """Decrypts an API key stored in the database for use in LLM requests.

    If decryption fails (for example because an old plaintext key was stored
    before encryption was introduced), the token is returned as-is to preserve
    backward compatibility with existing integrations.

    Args:
        encrypted_token (str): The encrypted API key from the database.

    Returns:
        str: The decrypted API key, or the original value if decryption is
        not possible.
    """
    if not encrypted_token or not cipher_suite:
        return encrypted_token
    try:
        return cipher_suite.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
    except Exception:
        return encrypted_token


def _get_current_user_id(db, explicit_user_id=None):
    """Resolves the current user ID from the session or an explicit argument.

    In the Streamlit web context the username is read from
    ``st.session_state``.  In background tasks (Celery) the session store is
    unavailable; callers must supply ``explicit_user_id`` instead.

    Args:
        db: An active SQLAlchemy database session.
        explicit_user_id (int | None): A user ID supplied by the caller
            (e.g. from a Celery task).  When not None this value is returned
            immediately without consulting the web session.

    Returns:
        int | None: The resolved user ID, or None if no user could be
        determined.
    """
    if explicit_user_id is not None:
        return explicit_user_id

    try:
        if "username" in st.session_state:
            user = db.query(User).filter(User.username == st.session_state["username"]).first()
            return user.id if user else None
    except Exception:
        pass

    return None


def get_providers(user_id=None):
    """Loads the current user's LLM provider integrations from the database.

    Args:
        user_id (int | None): Optional explicit user ID.  When None the ID
            is resolved from the active web session.

    Returns:
        dict: A mapping of provider display names to their configuration
        dicts.  Each dict contains the keys ``type``, ``key``, ``base_url``,
        and ``models`` (a list of model name strings).  Returns an empty dict
        when no user is authenticated.
    """
    db = SessionLocal()
    try:
        uid = _get_current_user_id(db, user_id)
        if not uid:
            return {}

        providers_db = db.query(LLMProvider).filter(LLMProvider.user_id == uid).all()

        return {
            p.name: {
                "type": p.api_type,
                "key": p.api_key,
                "base_url": p.base_url,
                "models": [m.strip() for m in p.models.split(",") if m.strip()]
            } for p in providers_db
        }
    finally:
        db.close()


def save_provider(name, api_type, api_key, base_url, models_str):
    """Creates or updates an LLM provider integration in the database.

    The API key is encrypted before storage.  If a provider with the same
    name already exists for the current user it is updated in place.

    Args:
        name (str): Display name for the provider.
        api_type (str): One of ``"openai"``, ``"deepseek"``, ``"gemini"``,
            or ``"other"``.
        api_key (str): The plaintext API key (encrypted before storage).
        base_url (str): Optional custom base URL for OpenAI-compatible APIs.
        models_str (str): Comma-separated list of model identifiers.
    """
    db = SessionLocal()
    try:
        user_id = _get_current_user_id(db)
        if not user_id:
            return

        safe_api_key = encrypt_token(api_key)

        prov = db.query(LLMProvider).filter(
            LLMProvider.user_id == user_id, LLMProvider.name == name
        ).first()

        if prov:
            prov.api_type = api_type
            prov.api_key = safe_api_key
            prov.base_url = base_url
            prov.models = models_str
        else:
            new_prov = LLMProvider(
                user_id=user_id,
                name=name,
                api_type=api_type,
                api_key=safe_api_key,
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
    """Removes an LLM provider integration from the database.

    Args:
        name (str): The display name of the provider to delete.
    """
    db = SessionLocal()
    try:
        user_id = _get_current_user_id(db)
        if not user_id:
            return

        prov = db.query(LLMProvider).filter(
            LLMProvider.user_id == user_id, LLMProvider.name == name
        ).first()
        if prov:
            db.delete(prov)
            db.commit()
    except Exception as e:
        print(f"Ошибка удаления провайдера: {e}")
        db.rollback()
    finally:
        db.close()


def ask_llm(provider_name, model_name, system_prompt, user_prompt, user_id=None):
    """Sends a prompt to a configured LLM provider and returns the response.

    Supports Google Gemini and OpenAI-compatible APIs (OpenAI, DeepSeek, and
    custom providers reachable via a user-supplied base URL).

    Args:
        provider_name (str): The display name of the configured provider.
        model_name (str): The model identifier (e.g. ``"gpt-4"``,
            ``"gemini-pro"``).
        system_prompt (str): The system-level instruction for the model.
        user_prompt (str): The user message / task description.
        user_id (int | None): Optional explicit user ID for background-task
            contexts.

    Returns:
        tuple: ``(success: bool, content: str)``.  On failure ``success`` is
        False and ``content`` carries the error message.
    """
    providers = get_providers(user_id)

    if provider_name not in providers:
        return False, f"Провайдер '{provider_name}' не найден."

    conf = providers[provider_name]
    api_type = conf.get("type", "openai")

    encrypted_key = conf.get("key")
    api_key = decrypt_token(encrypted_key)

    base_url = conf.get("base_url")

    if not api_key:
        return False, "Ошибка: Не указан API Key."

    if api_type == "gemini":
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)

            full_prompt = f"{system_prompt}\n\nUser Request:\n{user_prompt}"
            response = model.generate_content(full_prompt)

            if response and response.text:
                return True, response.text
            else:
                return False, "Gemini вернул пустой ответ (блокировка безопасности?)"

        except Exception as e:
            return False, f"Ошибка Gemini API: {e}"

    elif api_type in ["openai", "deepseek", "other"]:
        try:
            from openai import OpenAI

            client_args = {"api_key": api_key}
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
