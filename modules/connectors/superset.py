import pandas as pd
import requests
from .base import BaseConnector


class SupersetConnector(BaseConnector):
    """Apache Superset connector that executes SQL via the REST API.

    Authenticates with username/password to obtain a JWT, then submits
    queries through the ``/api/v1/sqllab/execute/`` endpoint.
    """

    @staticmethod
    def get_meta():
        """Return connector metadata.

        Returns:
            dict: Keys ``id``, ``name``, and ``icon``.
        """
        return {
            "id": "superset",
            "name": "Apache Superset (SQL)",
            "icon": "📊",
        }

    @staticmethod
    def get_fields():
        """Return the list of user-facing configuration fields.

        Returns:
            list[dict]: Fields for host, username, password, database_id,
                and query.
        """
        return [
            {
                "key": "host",
                "label": "Superset URL",
                "type": "text",
                "placeholder": "http://superset.mycompany.com:8088",
                "default": "http://localhost:8088",
            },
            {
                "key": "username",
                "label": "Username",
                "type": "text",
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
            },
            {
                "key": "database_id",
                "label": "Database ID (число)",
                "type": "number",
                "help": (
                    "ID базы данных внутри Superset. Можно найти в URL "
                    "при редактировании БД или в SQL Lab."
                ),
                "default": 1,
            },
            {
                "key": "query",
                "label": "SQL Query",
                "type": "text",
                "placeholder": "SELECT * FROM my_table LIMIT 1000",
                "help": "SQL запрос, который выполнится на стороне Superset",
            },
        ]

    def load_data(self, config) -> pd.DataFrame:
        """Authenticate with Superset, execute a SQL query, and return the results.

        Args:
            config (dict): Must contain ``host``, ``username``,
                ``password``, ``database_id``, and ``query``.

        Returns:
            pd.DataFrame: The query result rows.

        Raises:
            ValueError: If required connection parameters or the query
                are missing.
            Exception: On authentication failure, SQL execution errors,
                or Superset-side errors.
        """
        host = config.get("host", "").rstrip("/")
        username = config.get("username")
        password = config.get("password")
        database_id = config.get("database_id")
        query = config.get("query")

        if not host or not username or not password:
            raise ValueError(
                "Не заполнены параметры подключения (Host, User, Pass)"
            )

        if not query:
            raise ValueError("Пустой SQL запрос")

        # 1. Authenticate and obtain a JWT access token.
        login_url = f"{host}/api/v1/security/login"
        try:
            auth_resp = requests.post(login_url, json={
                "username": username,
                "password": password,
                "provider": "db",
            }, timeout=10)

            if auth_resp.status_code != 200:
                raise Exception(
                    f"Ошибка входа: {auth_resp.status_code} "
                    f"{auth_resp.text}"
                )

            access_token = auth_resp.json().get("access_token")
            if not access_token:
                raise Exception("Не удалось получить access_token")

        except Exception as e:
            raise Exception(f"Ошибка соединения с Superset: {e}")

        # 2. Execute the query via the SQL Lab API.
        execute_url = f"{host}/api/v1/sqllab/execute/"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "database_id": int(database_id),
            "sql": query,
            "runAsync": False,
            "json": True,
        }

        try:
            resp = requests.post(
                execute_url, json=payload, headers=headers, timeout=60
            )

            if resp.status_code != 200:
                raise Exception(
                    f"Ошибка выполнения SQL: {resp.status_code} "
                    f"{resp.text}"
                )

            data_json = resp.json()

            # Response structure varies across Superset versions.
            if "data" in data_json:
                rows = data_json["data"]
            elif "results" in data_json:
                rows = data_json["results"][0]["data"]
            else:
                rows = data_json

            # Superset may return 200 OK with an errors payload.
            if isinstance(data_json, dict) and data_json.get("errors"):
                raise Exception(f"Superset Error: {data_json['errors']}")

            return pd.DataFrame(rows)

        except Exception as e:
            raise Exception(f"Ошибка запроса данных: {e}")
