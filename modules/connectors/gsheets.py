import pandas as pd
import streamlit as st
import traceback
from .base import BaseConnector

try:
    import gspread
except ImportError:
    gspread = None

class GoogleSheetsConnector(BaseConnector):
    @staticmethod
    def get_meta():
        return {
            "id": "google_sheets",
            "name": "Google Sheets (Личный)",
            "icon": "📄"
        }

    @staticmethod
    def get_fields():
        return [
            {
                "key": "url", 
                "label": "Ссылка на таблицу (или ID)", 
                "type": "text", 
                "placeholder": "https://docs.google.com/spreadsheets/d/..."
            }
        ]
        
    def validate(self, config):
        if gspread is None:
            return False, "Нет библиотеки gspread"
        if config.get("_injected_creds"):
            return True, "OK"
        if 'google_creds' not in st.session_state:
            return False, "Сначала войдите через Google (в меню 🔐)"
        return True, "OK"

    def load_data(self, config) -> pd.DataFrame:
        url = config.get("url", "").strip()
        if not url: 
            raise ValueError("Поле 'Ссылка на таблицу' пустое! Зайдите в ⚙️ и укажите ссылку.")

        # Получаем креды
        creds = config.get("_injected_creds")
        if not creds and 'google_creds' in st.session_state:
            creds = st.session_state.google_creds
            
        if not creds:
            raise PermissionError("Нет токена авторизации. Попробуйте выйти и войти снова.")

        try:
            gc = gspread.authorize(creds)
            
            # Логика открытия
            if url.startswith("https://") and "docs.google.com" in url:
                sh = gc.open_by_url(url)
            else:
                # Если это не ссылка, пробуем как ID
                # Но если это имя файла ("test.csv"), это вызовет ошибку
                try:
                    sh = gc.open_by_key(url)
                except:
                    # Если не вышло открыть как ключ, скорее всего это мусор в поле
                    raise Exception(f"Некорректная ссылка или ID: '{url}'. Скопируйте ссылку из браузера.")
            
            ws = sh.get_worksheet(0)
            data = ws.get_all_records()
            return pd.DataFrame(data)

        except PermissionError:
             # Вот эта ошибка, которую вы видели
             raise Exception("Ошибка доступа. Попробуйте: 1) Выйти и войти в Google (кнопка 🔐). 2) Убедитесь, что у вас есть доступ к этой таблице.")

        except gspread.exceptions.APIError as e:
            import json
            try:
                details = json.loads(e.response.text)
                msg = details['error']['message']
            except:
                msg = str(e)
            raise Exception(f"Ошибка Google API: {msg}")
            
        except gspread.exceptions.SpreadsheetNotFound:
            raise Exception(f"Таблица не найдена! Проверьте ссылку.")
            
        except Exception as e:
            raise Exception(f"Ошибка чтения: {type(e).__name__} - {e}")