import pandas as pd
import requests
from .base import BaseConnector

class SupersetConnector(BaseConnector):
    @staticmethod
    def get_meta():
        return {
            "id": "superset",
            "name": "Apache Superset (SQL)",
            "icon": "📊"
        }

    @staticmethod
    def get_fields():
        return [
            {
                "key": "host", 
                "label": "Superset URL", 
                "type": "text", 
                "placeholder": "http://superset.mycompany.com:8088",
                "default": "http://localhost:8088"
            },
            {
                "key": "username", 
                "label": "Username", 
                "type": "text"
            },
            {
                "key": "password", 
                "label": "Password", 
                "type": "password"
            },
            {
                "key": "database_id", 
                "label": "Database ID (число)", 
                "type": "number", 
                "help": "ID базы данных внутри Superset. Можно найти в URL при редактировании БД или в SQL Lab.",
                "default": 1
            },
            {
                "key": "query", 
                "label": "SQL Query", 
                "type": "text", 
                "placeholder": "SELECT * FROM my_table LIMIT 1000",
                "help": "SQL запрос, который выполнится на стороне Superset"
            }
        ]

    def load_data(self, config) -> pd.DataFrame:
        host = config.get("host", "").rstrip("/")
        username = config.get("username")
        password = config.get("password")
        database_id = config.get("database_id")
        query = config.get("query")

        if not host or not username or not password:
            raise ValueError("Не заполнены параметры подключения (Host, User, Pass)")
        
        if not query:
            raise ValueError("Пустой SQL запрос")

        # 1. Авторизация (получение JWT токена)
        login_url = f"{host}/api/v1/security/login"
        try:
            auth_resp = requests.post(login_url, json={
                "username": username,
                "password": password,
                "provider": "db"
            }, timeout=10)
            
            if auth_resp.status_code != 200:
                raise Exception(f"Ошибка входа: {auth_resp.status_code} {auth_resp.text}")
                
            access_token = auth_resp.json().get("access_token")
            if not access_token:
                raise Exception("Не удалось получить access_token")
                
        except Exception as e:
            raise Exception(f"Ошибка соединения с Superset: {e}")

        # 2. Выполнение запроса через SQL Lab API
        execute_url = f"{host}/api/v1/sqllab/execute/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "database_id": int(database_id),
            "sql": query,
            "runAsync": False,   # Хотим синхронный ответ
            "json": True         # Формат ответа
        }

        try:
            resp = requests.post(execute_url, json=payload, headers=headers, timeout=60)
            
            if resp.status_code != 200:
                raise Exception(f"Ошибка выполнения SQL: {resp.status_code} {resp.text}")
            
            data_json = resp.json()
            
            # Разбор ответа (структура может отличаться в разных версиях, но обычно это 'data')
            if "data" in data_json:
                rows = data_json["data"]
            elif "results" in data_json:
                 # Иногда вложенность другая
                 rows = data_json["results"][0]["data"]
            else:
                # Пытаемся найти список словарей
                rows = data_json
                
            # Если вернулась ошибка внутри JSON (бывает при 200 OK)
            if isinstance(data_json, dict) and data_json.get("errors"):
                 raise Exception(f"Superset Error: {data_json['errors']}")

            return pd.DataFrame(rows)

        except Exception as e:
            raise Exception(f"Ошибка запроса данных: {e}")