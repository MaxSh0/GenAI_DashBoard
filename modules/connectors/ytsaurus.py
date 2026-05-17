import pandas as pd
from .base import BaseConnector


class YTsaurusConnector(BaseConnector):
    """YTsaurus connector that reads tables via YQL / YT client.

    Uses ``yt.wrapper`` to connect to a cluster and read table rows
    into a DataFrame.
    """

    @staticmethod
    def get_meta():
        """Return connector metadata.

        Returns:
            dict: Keys ``id``, ``name``, and ``icon``.
        """
        return {
            "id": "ytsaurus",
            "name": "YTsaurus (YT)",
            "icon": "🦖",
        }

    @staticmethod
    def get_fields():
        """Return the list of user-facing configuration fields.

        Returns:
            list[dict]: Fields for proxy, token, path, and limit.
        """
        return [
            {
                "key": "proxy",
                "label": "YT Proxy (Cluster)",
                "type": "text",
                "placeholder": "jupiter.yt.idzn.ru",
                "default": "jupiter.yt.idzn.ru",
            },
            {
                "key": "token",
                "label": "YT Token",
                "type": "password",
                "help": (
                    "Ваш OAuth токен. "
                    "Можно взять в ~/.yt/token или Web UI"
                ),
            },
            {
                "key": "path",
                "label": "Путь к таблице",
                "type": "text",
                "placeholder": "//home/...",
            },
            {
                "key": "limit",
                "label": "Лимит строк (0 = все)",
                "type": "number",
                "default": 1000,
            },
        ]

    def load_data(self, config) -> pd.DataFrame:
        """Connect to a YTsaurus cluster and read a table.

        Args:
            config (dict): Must contain ``proxy``, ``token``, and
                ``path``.  ``limit`` (int) caps the row count; 0 means
                no limit.

        Returns:
            pd.DataFrame: The table rows.

        Raises:
            ImportError: If ``ytsaurus-client`` is not installed.
            ValueError: If ``token`` or ``path`` is missing.
            FileNotFoundError: If the table path does not exist.
            Exception: On any other YT client error.
        """
        try:
            import yt.wrapper as yt
        except ImportError:
            raise ImportError(
                "Библиотека 'ytsaurus-client' не установлена. "
                "Выполните: pip install ytsaurus-client"
            )

        proxy = config.get("proxy")
        token = config.get("token")
        path = config.get("path")
        limit = int(config.get("limit", 0))

        if not token:
            raise ValueError("Не указан YT Token")
        if not path:
            raise ValueError("Не указан путь к таблице")

        yt_config = {
            "proxy": {
                "url": proxy,
                "enable_proxy_discovery": False,
            },
            "token": token,
        }

        client = yt.YtClient(config=yt_config)

        try:
            if not client.exists(path):
                raise FileNotFoundError(
                    f"Путь не найден в YT: {path}"
                )

            # When a row limit is requested, supply an explicit ranges
            # dictionary rather than a plain string so the server
            # receives the ``map``-typed structure it expects.
            if limit > 0:
                read_ranges = [
                    {
                        "lower_limit": {"row_index": 0},
                        "upper_limit": {"row_index": limit},
                    }
                ]
                table_path = yt.TablePath(path, ranges=read_ranges)
            else:
                table_path = path

            rows_iterator = client.read_table(table_path, format="json")
            rows = list(rows_iterator)

            df = pd.DataFrame(rows)
            return df

        except Exception as e:
            raise Exception(f"YT Error: {e}")
