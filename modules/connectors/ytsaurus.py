import pandas as pd
import streamlit as st
from .base import BaseConnector

class YTsaurusConnector(BaseConnector):
    @staticmethod
    def get_meta():
        return {
            "id": "ytsaurus",
            "name": "YTsaurus (YT)",
            "icon": "🦖"
        }

    @staticmethod
    def get_fields():
        return [
            {
                "key": "proxy", 
                "label": "YT Proxy (Cluster)", 
                "type": "text", 
                "placeholder": "jupiter.yt.idzn.ru", # Обновил пример
                "default": "jupiter.yt.idzn.ru"
            },
            {
                "key": "token", 
                "label": "YT Token", 
                "type": "password",
                "help": "Ваш OAuth токен. Можно взять в ~/.yt/token или Web UI"
            },
            {
                "key": "path", 
                "label": "Путь к таблице", 
                "type": "text", 
                "placeholder": "//home/..."
            },
            {
                "key": "limit", 
                "label": "Лимит строк (0 = все)", 
                "type": "number", 
                "default": 1000
            }
        ]

    def load_data(self, config) -> pd.DataFrame:
        try:
            import yt.wrapper as yt
        except ImportError:
            raise ImportError("Библиотека 'ytsaurus-client' не установлена. Выполните: pip install ytsaurus-client")

        proxy = config.get("proxy")
        token = config.get("token")
        path = config.get("path")
        limit = int(config.get("limit", 0))

        if not token: raise ValueError("Не указан YT Token")
        if not path: raise ValueError("Не указан путь к таблице")

        # --- НАСТРОЙКА КЛИЕНТА ---
        yt_config = {
            "proxy": {
                "url": proxy,
                "enable_proxy_discovery": False
            },
            "token": token
        }

        client = yt.YtClient(config=yt_config)

        try:
            if not client.exists(path):
                raise FileNotFoundError(f"Путь не найден в YT: {path}")

            # --- ИСПРАВЛЕНИЕ ОШИБКИ С RANGES ---
            if limit > 0:
                # Вместо строки "lower_limit=..." передаем словарь с ключами
                # Это формат, который жестко требует сервер, ожидая "map"
                read_ranges = [
                    {
                        "lower_limit": {"row_index": 0},
                        "upper_limit": {"row_index": limit}
                    }
                ]
                table_path = yt.TablePath(path, ranges=read_ranges)
            else:
                table_path = path
            # -----------------------------------

            rows_iterator = client.read_table(table_path, format="json")
            rows = list(rows_iterator)
            
            df = pd.DataFrame(rows)
            return df

        except Exception as e:
            raise Exception(f"YT Error: {e}")