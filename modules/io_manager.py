import os
import json
import zipfile
import io
import time
import re
import random
from datetime import datetime

from modules.settings import CHARTS_FOLDER, DATA_FOLDER, CONFIG_FILE, TITLES_CONFIG_FILE, PAGES_CONFIG_FILE
from modules.utils import load_json, save_json

class BundleManager:
    
    @staticmethod
    def _randomize_widget_keys(code_str):
        """
        Ищет жестко заданные ключи (key="...") и добавляет к ним случайный хвост.
        Это предотвращает конфликты виджетов при импорте.
        """
        # Генерируем уникальный суффикс
        suffix = f"{int(time.time())}_{random.randint(100, 999)}"
        
        # 1. Regex для поиска параметров key="value" или key='value'
        # Группы: 1=(key=), 2=(кавычка), 3=(значение)
        pattern_keys = r'(key\s*=\s*)(["\'])(.*?)\2'
        
        def key_replacer(match):
            prefix = match.group(1)
            quote = match.group(2)
            old_key = match.group(3)
            # Если ключ выглядит как f-строка или переменная - не трогаем (рискованно)
            # Меняем только явные строки
            return f"{prefix}{quote}{old_key}_{suffix}{quote}"
            
        try:
            # Заменяем все вхождения
            new_code = re.sub(pattern_keys, key_replacer, code_str)
            return new_code
        except Exception as e:
            print(f"Regex Error: {e}")
            return code_str

    @staticmethod
    def export_chart(filename):
        """Упаковка графика в .geb (ZIP архив)"""
        charts_conf = load_json(CONFIG_FILE, {})
        titles_conf = load_json(TITLES_CONFIG_FILE, {})
        
        display_name = titles_conf.get(filename, filename)
        linked_data = charts_conf.get(filename, [])
        
        manifest = {
            "version": "1.1",
            "type": "chart",
            "exported_at": datetime.now().isoformat(),
            "items": [
                {
                    "filename": filename,
                    "display_name": display_name,
                    "data_files": linked_data
                }
            ]
        }

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            
            src_path = os.path.join(CHARTS_FOLDER, filename)
            if os.path.exists(src_path):
                zf.write(src_path, arcname=f"source/{filename}")
            
            for df_name in linked_data:
                d_path = os.path.join(DATA_FOLDER, df_name)
                if os.path.exists(d_path):
                    zf.write(d_path, arcname=f"data/{df_name}")
        
        buffer.seek(0)
        return buffer

    @staticmethod
    def import_bundle(uploaded_file, target_page=None):
        """Распаковка + Уникализация ключей + Добавление на страницу"""
        log_messages = []
        new_charts_list = [] 

        try:
            with zipfile.ZipFile(uploaded_file, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    return False, "❌ Нет manifest.json"
                
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                charts_conf = load_json(CONFIG_FILE, {})
                titles_conf = load_json(TITLES_CONFIG_FILE, {})
                
                for item in manifest["items"]:
                    orig_fname = item["filename"]
                    display_name = item["display_name"]
                    data_files = item["data_files"]
                    
                    # --- 1. ОБРАБОТКА КОДА ---
                    final_chart_name = orig_fname
                    target_chart_path = os.path.join(CHARTS_FOLDER, final_chart_name)
                    
                    # Если файл существует - создаем копию с новым именем
                    if os.path.exists(target_chart_path):
                        timestamp = int(time.time())
                        final_chart_name = f"{orig_fname[:-3]}_imp_{timestamp}.py"
                        log_messages.append(f"⚠️ Файл переименован: {final_chart_name}")
                    
                    try:
                        code_bytes = zf.read(f"source/{orig_fname}")
                        code_str = code_bytes.decode("utf-8")
                        
                        # [ВАЖНО] Уникализируем ключи в коде ПЕРЕД сохранением
                        code_fixed = BundleManager._randomize_widget_keys(code_str)
                        
                        with open(os.path.join(CHARTS_FOLDER, final_chart_name), "w", encoding="utf-8") as f:
                            f.write(code_fixed)
                        
                        new_charts_list.append(final_chart_name)

                    except KeyError:
                        log_messages.append(f"❌ Код {orig_fname} не найден.")
                        continue

                    # --- 2. ОБРАБОТКА ДАННЫХ ---
                    final_data_list = []
                    for df_name in data_files:
                        try:
                            data_bytes = zf.read(f"data/{df_name}")
                            final_df_name = df_name
                            target_data_path = os.path.join(DATA_FOLDER, final_df_name)
                            
                            # Если файл данных существует
                            if os.path.exists(target_data_path):
                                # Если размер отличается - сохраняем копию
                                if os.path.getsize(target_data_path) != len(data_bytes):
                                    root, ext = os.path.splitext(df_name)
                                    ts = int(time.time())
                                    final_df_name = f"{root}_imp_{ts}{ext}"
                                    log_messages.append(f"📦 Данные: сохранен как {final_df_name}")
                                else:
                                    log_messages.append(f"✅ Данные: используется существующий {df_name}")
                            
                            if not os.path.exists(os.path.join(DATA_FOLDER, final_df_name)):
                                with open(os.path.join(DATA_FOLDER, final_df_name), "wb") as f:
                                    f.write(data_bytes)
                            
                            final_data_list.append(final_df_name)
                        except KeyError:
                            pass

                    # --- 3. ОБНОВЛЕНИЕ КОНФИГОВ ---
                    charts_conf[final_chart_name] = final_data_list
                    titles_conf[final_chart_name] = f"{display_name} (Imported)"
                
                save_json(CONFIG_FILE, charts_conf)
                save_json(TITLES_CONFIG_FILE, titles_conf)
                
                # --- 4. ДОБАВЛЕНИЕ НА СТРАНИЦУ ---
                if target_page and new_charts_list:
                    p_conf = load_json(PAGES_CONFIG_FILE, {})
                    if target_page not in p_conf: p_conf[target_page] = []
                    
                    for ch in new_charts_list:
                        if ch not in p_conf[target_page]:
                            p_conf[target_page].insert(0, ch)
                            
                    save_json(PAGES_CONFIG_FILE, p_conf)
                    log_messages.append(f"📌 Добавлено на страницу '{target_page}'")

                return True, "\n".join(log_messages)

        except Exception as e:
            return False, f"Ошибка: {str(e)}"