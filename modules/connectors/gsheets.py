import pandas as pd
import streamlit as st
from .base import BaseConnector

try:
    import gspread
except ImportError:
    gspread = None


class GoogleSheetsConnector(BaseConnector):
    """Google Sheets connector backed by gspread.

    Authenticates via the ``google_creds`` session-state key (set by the
    OAuth flow) or an injected ``_injected_creds`` config value.
    """

    @staticmethod
    def get_meta():
        """Return connector metadata.

        Returns:
            dict: Keys ``id``, ``name``, and ``icon``.
        """
        return {
            "id": "google_sheets",
            "name": "Google Sheets (Личный)",
            "icon": "📄",
        }

    @staticmethod
    def get_fields():
        """Return the list of user-facing configuration fields.

        Returns:
            list[dict]: A single-field list asking for the sheet URL or ID.
        """
        return [
            {
                "key": "url",
                "label": "Ссылка на таблицу (или ID)",
                "type": "text",
                "placeholder": "https://docs.google.com/spreadsheets/d/...",
            }
        ]

    def validate(self, config):
        """Check whether the connector can authenticate.

        Args:
            config (dict): Connector configuration dictionary.

        Returns:
            tuple[bool, str]: A tuple of (is_valid, message).
        """
        if gspread is None:
            return False, "Нет библиотеки gspread"
        if config.get("_injected_creds"):
            return True, "OK"
        if 'google_creds' not in st.session_state:
            return False, "Сначала войдите через Google (в меню 🔐)"
        return True, "OK"

    def load_data(self, config) -> pd.DataFrame:
        """Load the first worksheet of a Google Sheet as a DataFrame.

        Args:
            config (dict): Must contain a ``url`` key with a sheet URL
                or spreadsheet ID.  Authentication is taken from
                ``_injected_creds`` or ``st.session_state.google_creds``.

        Returns:
            pd.DataFrame: All records from the first worksheet.

        Raises:
            ValueError: If the URL / ID field is empty.
            PermissionError: If no authentication token is available.
            Exception: On Google API errors, access failures, or
                spreadsheet-not-found.
        """
        url = config.get("url", "").strip()
        if not url:
            raise ValueError(
                "Поле 'Ссылка на таблицу' пустое! "
                "Зайдите в ⚙️ и укажите ссылку."
            )

        creds = config.get("_injected_creds")
        if not creds and 'google_creds' in st.session_state:
            creds = st.session_state.google_creds

        if not creds:
            raise PermissionError(
                "Нет токена авторизации. "
                "Попробуйте выйти и войти снова."
            )

        try:
            gc = gspread.authorize(creds)

            if url.startswith("https://") and "docs.google.com" in url:
                sh = gc.open_by_url(url)
            else:
                # Treat the value as a spreadsheet ID; a non-ID value
                # (e.g. a filename) will raise an error caught below.
                try:
                    sh = gc.open_by_key(url)
                except Exception:
                    raise Exception(
                        f"Некорректная ссылка или ID: '{url}'. "
                        "Скопируйте ссылку из браузера."
                    )

            ws = sh.get_worksheet(0)
            data = ws.get_all_records()
            return pd.DataFrame(data)

        except PermissionError:
            raise Exception(
                "Ошибка доступа. Попробуйте: "
                "1) Выйти и войти в Google (кнопка 🔐). "
                "2) Убедитесь, что у вас есть доступ к этой таблице."
            )

        except gspread.exceptions.APIError as e:
            import json
            msg = str(e)
            try:
                details = json.loads(e.response.text)
                msg = details['error']['message']
            except Exception:
                pass
            raise Exception(f"Ошибка Google API: {msg}")

        except gspread.exceptions.SpreadsheetNotFound:
            raise Exception("Таблица не найдена! Проверьте ссылку.")

        except Exception as e:
            raise Exception(f"Ошибка чтения: {type(e).__name__} - {e}")
