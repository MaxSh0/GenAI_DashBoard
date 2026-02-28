import pandas as pd
import os
import time
import importlib.util
from modules.settings import DATA_FOLDER, HANDLERS_FOLDER
from modules.connector_loader import load_connectors
from modules.s3_storage import s3_client

def sync_single_source(source_config):
    """
    Выполняет загрузку данных для одного источника и применяет ETL.
    """
    try:
        # 1. Определяем коннектор и имя файла
        connector_id = source_config.get("connector_id")
        filename = source_config.get("filename")
        
        # Обратная совместимость
        if not connector_id:
            if source_config.get("type") == "Google Sheets":
                connector_id = "google_sheets"
                if "config" not in source_config:
                    source_config["config"] = {"url": source_config.get("url")}
            else:
                connector_id = "base"

        # 2 & 3. Загружаем данные (Extract)
        if connector_id == "base":
            # --- ЛОГИКА ДЛЯ ЛОКАЛЬНЫХ ФАЙЛОВ ---
            if not filename:
                return False, "Для типа 'base' не указано имя файла (filename).", None
                
            file_path = os.path.join(DATA_FOLDER, filename)
            
            # Если файла нет локально, пробуем стянуть из S3
            if not os.path.exists(file_path):
                try:
                    s3_client.download_file("data-sources", filename, file_path)
                except Exception as e:
                    return False, f"Локальный файл не найден и ошибка скачивания из S3: {e}", None
                    
            # Читаем данные
            if filename.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
                
        else:
            # --- ЛОГИКА ДЛЯ ВНЕШНИХ КОННЕКТОРОВ (Google Sheets, YTsaurus) ---
            available_connectors = load_connectors()
            if connector_id not in available_connectors:
                return False, f"Коннектор '{connector_id}' не найден. Проверьте plugins.", None
                
            ConnectorClass = available_connectors[connector_id]
            connector = ConnectorClass()
            
            config_data = source_config.get("config", {})
            is_valid, err_msg = connector.validate(config_data)
            if not is_valid:
                return False, f"Ошибка конфигурации: {err_msg}", None

            df = connector.load_data(config_data)

        if df is None or df.empty:
            return False, "Источник вернул пустой DataFrame", None

        # 4. Применяем ETL обработчик (Transform)
        handler_name = source_config.get("handler", "None")
        if handler_name and handler_name != "None":
            h_path = os.path.join(HANDLERS_FOLDER, handler_name)
            
            # Если скрипта нет локально, скачиваем из S3
            if not os.path.exists(h_path):
                try:
                    s3_client.download_file("handlers", handler_name, h_path)
                except Exception as e:
                    return False, f"Ошибка скачивания ETL-скрипта из S3: {e}", None

            if os.path.exists(h_path):
                try:
                    spec = importlib.util.spec_from_file_location(f"etl_{int(time.time())}", h_path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    
                    if hasattr(mod, "handle"):
                        # Запускаем трансформацию!
                        df = mod.handle(df)
                    else:
                        return False, f"В скрипте {handler_name} нет функции handle(df)", None
                except Exception as e:
                    return False, f"Ошибка в ETL-скрипте: {e}", None
            else:
                return False, f"Скрипт {handler_name} не найден", None

        # 5. Сохраняем результат (Load)
        if not filename:
            filename = f"source_{int(time.time())}.csv"
            
        save_path = os.path.join(DATA_FOLDER, filename)
        
        if filename.endswith(".xlsx"):
            df.to_excel(save_path, index=False)
        else:
            df.to_csv(save_path, index=False)
            
        # ОТПРАВЛЯЕМ ФАЙЛ В S3
        try:
            s3_client.upload_file(save_path, "data-sources", filename)
        except Exception as e:
            return False, f"Данные обработаны, но ошибка загрузки в S3: {e}", None
            
        return True, "OK", df

    except Exception as e:
        return False, str(e), None