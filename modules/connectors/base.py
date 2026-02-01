import pandas as pd

class BaseConnector:
    """
    Базовый класс для всех источников данных.
    """
    @staticmethod
    def get_meta():
        """Возвращает метаданные коннектора."""
        return {
            "id": "base",
            "name": "Base Connector",
            "icon": "🔌"
        }

    @staticmethod
    def get_fields():
        """
        Возвращает список полей, которые нужно заполнить пользователю.
        Пример: [{"key": "token", "label": "API Token", "type": "password"}]
        """
        return []

    def validate(self, config):
        """Проверяет подключение (по желанию)."""
        return True, "OK"

    def load_data(self, config) -> pd.DataFrame:
        """
        Основной метод загрузки. Должен вернуть Pandas DataFrame.
        """
        raise NotImplementedError("Метод load_data должен быть реализован")