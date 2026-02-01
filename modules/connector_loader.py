import os
import importlib.util
import inspect
from modules.settings import BASE_DIR

# Путь к папке с плагинами
CONNECTORS_DIR = os.path.join(BASE_DIR, "modules", "connectors")

def load_connectors():
    """
    Сканирует папку modules/connectors и возвращает словарь доступных классов коннекторов.
    Ключ = connector_id, Значение = Класс.
    """
    connectors = {}
    
    if not os.path.exists(CONNECTORS_DIR):
        return connectors

    # Перебираем все .py файлы в папке
    for filename in os.listdir(CONNECTORS_DIR):
        if filename.endswith(".py") and filename != "__init__.py" and filename != "base.py":
            module_name = filename[:-3]
            file_path = os.path.join(CONNECTORS_DIR, filename)
            
            try:
                # Динамический импорт модуля
                spec = importlib.util.spec_from_file_location(f"modules.connectors.{module_name}", file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Ищем классы, которые наследуются от BaseConnector
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    # Проверяем наличие обязательных методов
                    if hasattr(obj, 'get_meta') and hasattr(obj, 'get_fields'):
                        meta = obj.get_meta()
                        # Исключаем сам базовый класс, если он вдруг импортировался
                        if meta['id'] != 'base':
                            connectors[meta['id']] = obj
            except Exception as e:
                print(f"Ошибка загрузки коннектора {filename}: {e}")
                
    return connectors