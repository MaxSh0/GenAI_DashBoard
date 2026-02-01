import streamlit as st
import pandas as pd
import os
import time

# --- ИМПОРТЫ ДЛЯ AI ---
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
from modules.settings import THEMES_CONFIG_FILE # Импорт пути конфига
from modules.settings import DATA_FOLDER, CHARTS_FOLDER, CONFIG_FILE, SOURCES_CONFIG_FILE, HANDLERS_FOLDER, PAGES_CONFIG_FILE, TITLES_CONFIG_FILE
from modules.utils import sanitize_filename, load_json, save_json
from modules.auth import is_authenticated

# --- HELPER: ОЧИСТКА КОДА ОТ AI ---
def clean_gemini_code(text):
    """Убирает маркдаун обертки ```python ... ``` если они есть."""
    if "```python" in text:
        text = text.split("```python")[1]
        if "```" in text:
            text = text.split("```")[0]
    elif "```" in text:
        text = text.split("```")[1] # Если просто ``` без python
        if "```" in text:
            text = text.split("```")[0]
    return text.strip()

# --- CALLBACKS ---
def add_source_callback():
    if "wiz_sources" in st.session_state:
        st.session_state.wiz_sources.append({"active": True, "type": "Google Sheets", "filename": "", "url": "", "handler": "None"})

def remove_source_callback(index):
    if "wiz_sources" in st.session_state:
        if 0 <= index < len(st.session_state.wiz_sources): del st.session_state.wiz_sources[index]


# --- WIZARD: CREATE CHART (DUAL MODE) ---
@st.dialog("✨ Новый график")
def wizard_create_chart():
    st.write("Заполните параметры задачи.")
    
    # 1. Настройки файла
    st.write("### 1. Настройка файла")
    display_title = st.text_input("Название графика (видит пользователь)", placeholder="Динамика Выручки 2024")
    filename_base = st.text_input("Техническое ID файла (латиница)", placeholder="revenue_2024")
    file = st.file_uploader("Данные", type=["csv", "xlsx"])
    
    # 2. Формирование задачи
    st.write("### 2. Формирование задачи")

    # --- УПРАВЛЕНИЕ ПАЛИТРАМИ (FRAGMENT) ---
    @st.fragment
    def theme_manager_fragment():
        # 1. Загрузка тем
        # Палитры для графиков (Брендовые и Природные)
        themes = load_json(THEMES_CONFIG_FILE, {
            "Лес (Nature)": {
                "colors": ["#2D6A4F", "#52B788", "#D8F3DC"], # Темно-зеленый, Мятный, Бледно-зеленый
                "dark_mode": True
            },
            "Океан (Blue)": {
                "colors": ["#0077B6", "#00B4D8", "#90E0EF"], # Глубокий синий, Голубой, Светло-голубой
                "dark_mode": True
            },
            "Закат (Vibes)": {
                "colors": ["#7209B7", "#F72585", "#FFCC00"], # Фиолетовый, Розовый, Желтый
                "dark_mode": True
            },
            "ВсеИнструменты": {
                "colors": ["#EE1C25", "#231F20", "#eae7e7"], # Красный, Черный, Серый
                "dark_mode": False
            },
            "VK": {
                "colors": ["#0035ff", "#000000", "#99A2AD"], # VK Синий, Черный, Серый
                "dark_mode": False
            },
            "Сбер": {
                "colors": ["#21A038", "#1A1A1A", "#85C441"], # СберЗеленый, Черный, Светло-зеленый
                "dark_mode": False
            },
            "Яндекс": {
                "colors": ["#FC3F1D", "#FFCC00", "#000000"], # Красный, Желтый, Черный
                "dark_mode": False
            },
            "Т-Банк": {
                "colors": ["#FFDD2D", "#FFFFFF", "#000000"], # Желтый, Белый, Серый (для темной темы)
                "dark_mode": True
            }
        })

        theme_names = list(themes.keys())
        
        # Синхронизация имени
        def on_theme_change():
            st.session_state.theme_edit_name = st.session_state.theme_selector

        # Выбор темы
        idx = 0
        if "last_theme" in st.session_state and st.session_state.last_theme in theme_names:
            idx = theme_names.index(st.session_state.last_theme)

        sel_name = st.selectbox(
            "🎨 Цветовая палитра:", 
            theme_names, 
            index=idx, 
            key="theme_selector", 
            on_change=on_theme_change
        )
        st.session_state.last_theme = sel_name
        
        # Получаем данные текущей темы
        t_data = themes[sel_name]
        c_colors = t_data.get("colors") if isinstance(t_data, dict) else t_data
        c_dark = t_data.get("dark_mode", False) if isinstance(t_data, dict) else False

        # !!! ВАЖНО: СОХРАНЯЕМ В СЕССИЮ ДЛЯ ИСПОЛЬЗОВАНИЯ СНАРУЖИ !!!
        st.session_state.wiz_active_colors = c_colors
        st.session_state.wiz_active_dark = c_dark
        # -------------------------------------------------------------

        # Визуализация
        cols = st.columns(len(c_colors))
        for i, color in enumerate(c_colors):
            with cols[i]:
                st.markdown(f'<div style="background-color:{color};width:100%;height:40px;border-radius:6px;border:1px solid rgba(128,128,128,0.2);"></div>', unsafe_allow_html=True)
                st.caption(f"`{color}`")

        # Настройки
        with st.expander("⚙️ Настроить палитры"):
            edit_name = st.text_input("Название темы:", value=sel_name, key=f"edit_name_{sel_name}")
            is_dark = st.checkbox("Адаптировать для Dark Mode", value=c_dark, key=f"dark_mode_{sel_name}")
            
            ce1, ce2, ce3 = st.columns(3)
            nc1 = ce1.color_picker("1", value=c_colors[0], key=f"cp1_{sel_name}")
            nc2 = ce2.color_picker("2", value=c_colors[1], key=f"cp2_{sel_name}")
            nc3 = ce3.color_picker("3", value=c_colors[2], key=f"cp3_{sel_name}")
            
            bc1, bc2 = st.columns(2)
            if bc1.button("💾 Сохранить", type="primary", use_container_width=True, key=f"save_btn_{sel_name}"):
                themes[edit_name] = {"colors": [nc1, nc2, nc3], "dark_mode": is_dark}
                save_json(THEMES_CONFIG_FILE, themes)
                st.session_state.last_theme = edit_name
                st.toast("Тема сохранена!")
                st.rerun(scope="fragment") 

            if bc2.button("🗑️ Удалить", use_container_width=True, key=f"del_btn_{sel_name}"):
                if edit_name in themes and len(themes) > 1:
                    del themes[edit_name]
                    save_json(THEMES_CONFIG_FILE, themes)
                    st.session_state.last_theme = theme_names[0]
                    st.rerun(scope="fragment")

    # Вызываем фрагмент
    theme_manager_fragment()

    # Поля задачи
    goal = st.text_area("Цель графика / Задача", placeholder="Показать динамику оттока клиентов по месяцам.")
    chart_format = st.text_area("Пожелания к виду", placeholder="Столбчатая диаграмма, красный цвет.")
    chart_controls = st.text_area("Элементы управления (опционально)", placeholder="Добавить селектор выбора года.")

    # --- ВЫБОР AI ПРОВАЙДЕРА ---
    st.write("### 3. Выбор Интеллекта")
    from modules.llm_manager import get_providers, ask_llm
    providers = get_providers()
    
    llm_ready = False
    sel_prov = None
    sel_model = None

    if not providers:
        st.warning("⚠️ Нет настроенных AI интеграций. Добавьте их в настройках.")
    else:
        llm_ready = True
        c_prov, c_mod = st.columns(2)
        prov_names = list(providers.keys())
        sel_prov = c_prov.selectbox("Интеграция", prov_names, key="wiz_prov_sel")
        avail_models = providers[sel_prov]["models"]
        sel_model = c_mod.selectbox("Модель", avail_models, key="wiz_mod_sel")

    st.divider()
    
    c_auto, c_manual = st.columns([0.6, 0.4])
    btn_auto = c_auto.button("🤖 Сгенерировать код (AI)", type="primary")
    btn_manual = c_manual.button("📋 Только промпт")

    if btn_auto or btn_manual:
        if not (display_title and filename_base and file and goal):
            st.error("Заполните основные поля (Название, ID, Файл, Цель)!")
        else:
            # !!! ИСПРАВЛЕНИЕ ОШИБКИ NameError !!!
            # Читаем значения, которые сохранил фрагмент в сессию
            current_colors = st.session_state.get("wiz_active_colors", ["#000", "#000", "#000"])
            current_dark_mode = st.session_state.get("wiz_active_dark", False)
            colors_prompt_str = ", ".join(current_colors)
            # ----------------------------------------------------

            # 1. Сохраняем файл
            path = os.path.join(DATA_FOLDER, file.name)
            with open(path, "wb") as f: f.write(file.getbuffer())

            # 2. Регистрируем
            py_name = sanitize_filename(filename_base)
            
            conf = load_json(CONFIG_FILE, {})
            conf[py_name] = [file.name]
            save_json(CONFIG_FILE, conf)
            
            titles = load_json(TITLES_CONFIG_FILE, {})
            titles[py_name] = display_title
            save_json(TITLES_CONFIG_FILE, titles)
            
            p_conf = load_json(PAGES_CONFIG_FILE, {"B2B Дашборд": []})
            first_page = list(p_conf.keys())[0] if p_conf else "B2B Дашборд"
            if first_page not in p_conf: p_conf[first_page] = []
            if py_name not in p_conf[first_page]:
                p_conf[first_page].append(py_name)
                save_json(PAGES_CONFIG_FILE, p_conf)

            # 3. Промпт (Анализ колонок)
            try:
                if path.endswith('.csv'): df_preview = pd.read_csv(path, nrows=5)
                else: df_preview = pd.read_excel(path, nrows=5)
                cols_info = "\n".join([f"- `{c}` ({t})" for c, t in zip(df_preview.columns, df_preview.dtypes)])
            except Exception as e:
                cols_info = f"Error reading cols: {e}"

            # --- ФОРМИРОВАНИЕ ИНСТРУКЦИИ ПО СТИЛЮ ---
            # Теперь current_dark_mode определен выше!
            theme_mode_instruction = ""
            if current_dark_mode:
                theme_mode_instruction = (
                    "ВАЖНО: График будет отображаться на ТЕМНОМ фоне (Streamlit Dark Mode).\n"
                    "- Используй `template='plotly_dark'`.\n"
                    "- Убедись, что цвета линий/баров контрастны к темному фону.\n"
                    "- Сетку делай полупрозрачной белой или серой.\n"
                )
            else:
                theme_mode_instruction = (
                    "График будет на СВЕТЛОМ фоне.\n"
                    "- Используй `template='plotly_white'` или 'plotly'.\n"
                )

            style_instruction = (
                f"\n\n### ДИЗАЙН И ЦВЕТА:\n"
                f"{theme_mode_instruction}"
                f"Используй СТРОГО следующую цветовую палитру: {colors_prompt_str}.\n"
                f"Первый цвет ({current_colors[0]}) используй для основных данных/линий.\n"
                f"Второй цвет ({current_colors[1]}) для второстепенных элементов.\n"
                f"Третий цвет ({current_colors[2]}) для фона или акцентов.\n"
                "График должен быть стильным, минималистичным и корпоративным.\n"
            )

            controls_instruction = ""
            if chart_controls:
                controls_instruction = f"ЭЛЕМЕНТЫ УПРАВЛЕНИЯ: {chart_controls}. Используй st.selectbox/slider внутри render."

            final_prompt = (
                "Ты Senior Python Developer. Напиши модуль для Streamlit/Plotly.\n"
                f"ЗАДАЧА: {goal}\n"
                f"ВИД: {chart_format}\n{style_instruction}\n{controls_instruction}\n"
                f"КОНТЕКСТ ДАННЫХ: Придет список путей к файлам `files`. Структура колонок (на основе первого файла):\n{cols_info}\n"
                "!!! КРИТИЧЕСКИ ВАЖНО !!!\n"
                "1. Аргумент `files` - это ВСЕГДА список.\n"
                "2. Используй `for file in files` для чтения.\n"
                "3. `pd.concat` для объединения.\n"
                "4. Верни ТОЛЬКО код функции `render`.\n"
                "ШАБЛОН КОДА:\n"
                "```python\n"
                "import streamlit as st\nimport plotly.express as px\nimport pandas as pd\n\n"
                "def render(files):\n"
                "    if not files: return\n"
                "    dfs = []\n"
                "    for f_path in files:\n"
                "        try:\n"
                "             if f_path.endswith('.xlsx'): dfs.append(pd.read_excel(f_path))\n"
                "             else: dfs.append(pd.read_csv(f_path))\n"
                "        except: pass\n"
                "    if not dfs: return\n"
                "    df = pd.concat(dfs, ignore_index=True)\n"
                "    # ... Логика ...\n"
                "    fig = px.bar(df, ...)\n"
                "    st.plotly_chart(fig, use_container_width=True)\n"
                "```"
            )

            # --- РАЗВИЛКА: АВТО ИЛИ РУЧНОЙ ---
            if btn_manual:
                safe_prompt = final_prompt.replace('"""', "'''")
                file_content = (
                    f'"""\n--- MANUAL MODE ---\nЗАДАЧА:\n{safe_prompt}\n"""\n\n'
                    "import streamlit as st\ndef render(files):\n    st.info('График создан (Ручной режим).')"
                )
                with open(os.path.join(CHARTS_FOLDER, py_name), "w", encoding="utf-8") as f:
                    f.write(file_content)
                st.session_state.gen_prompt = final_prompt
                st.success("✅ Заготовка создана!")
                st.rerun()

            elif btn_auto:
                if not llm_ready:
                    st.error("Сначала настройте AI интеграцию!")
                else:
                    with st.spinner(f"🤖 {sel_prov} ({sel_model}) пишет код..."):
                        # Генерируем
                        system_msg = (
                        "Ты Senior Python Developer. Ты меняешь код Streamlit/Plotly по запросу. "
                        "Верни ТОЛЬКО валидный Python код всего модуля. Без маркдауна.\n"
                        "ВАЖНО ПО PLOTLY 5.X:\n"
                        "1. НИКОГДА не используй устаревшие параметры: 'titlefont', 'tickfont' внутри осей.\n"
                        "2. Правильный синтаксис шрифтов: dict(title=dict(text='Name', font=dict(size=14))).\n"
                        "3. Вместо 'margin' в layout используй update_layout(margin=dict(l=..., r=...))."
                    )
                        success, result_text = ask_llm(sel_prov, sel_model, system_msg, final_prompt)
                        
                        if success:
                            # Очистка кода
                            if "```python" in result_text: 
                                code_text = result_text.split("```python")[1].split("```")[0].strip()
                            elif "```" in result_text:
                                code_text = result_text.split("```")[1].strip()
                            else:
                                code_text = result_text.strip()
                            
                            # Сохранение файла
                            safe_prompt = final_prompt.replace('"""', "'''")
                            file_content = f'"""\n--- GENERATED BY {sel_prov} ({sel_model}) ---\nPROMPT:\n{safe_prompt}\n"""\n\n{code_text}'
                            
                            with open(os.path.join(CHARTS_FOLDER, py_name), "w", encoding="utf-8") as f:
                                f.write(file_content)
                            
                            st.success(f"✅ График сгенерирован через {sel_prov}!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"Ошибка генерации: {result_text}")
                            st.session_state.gen_prompt = final_prompt
                        
# --- WIZARD: MANAGE SOURCES (FIXED: NO RERUN) ---
@st.dialog("⚙️ Пайплайн данных", width="large")
def wizard_manage_sources():
    from modules.connector_loader import load_connectors
    
    # 1. Загружаем плагины
    available_connectors = load_connectors()
    
    # 2. Инициализация сессии (если еще нет)
    if "wiz_sources" not in st.session_state:
        conf = load_json(SOURCES_CONFIG_FILE, {})
        safe_sources = []
        for s in conf.get("sources", []):
            if "config" not in s:
                s["connector_id"] = "google_sheets" if s.get("type") == "Google Sheets" else "base"
                s["config"] = {"url": s.get("url", "")}
            safe_sources.append(s)
        st.session_state.wiz_sources = safe_sources

    # --- CALLBACKS ---
    def add_source_callback():
        default_id = list(available_connectors.keys())[0] if available_connectors else "base"
        st.session_state.wiz_sources.append({
            "active": True, 
            "connector_id": default_id, 
            "filename": "", 
            "config": {}, 
            "handler": "None"
        })

    def remove_source_callback(idx):
        if 0 <= idx < len(st.session_state.wiz_sources):
            st.session_state.wiz_sources.pop(idx)

    # --- UI ---
    if is_authenticated():
        st.success("✅ Google Auth активен", icon="🔐")
    
    st.divider()
    
    handlers_list = ["None"] + [f for f in os.listdir(HANDLERS_FOLDER) if f.endswith(".py") and f != "__init__.py"]
    
    c_head, c_add = st.columns([0.7, 0.3])
    c_head.write("### 🔗 Источники данных")
    c_add.button("➕ Добавить", use_container_width=True, on_click=add_source_callback)
    
    if not st.session_state.wiz_sources: 
        st.info("Список пуст.")

    # --- СПИСОК ИСТОЧНИКОВ ---
    # Важно: работаем с session_state напрямую
    sources = st.session_state.wiz_sources
    
    # Используем while loop или копию, чтобы избежать проблем при удалении, 
    # но так как удаление через callback, for loop + enumerate безопасен для рендеринга
    for i, src in enumerate(sources):
        # Определяем метаданные
        conn_id = src.get("connector_id", "base")
        connector_class = available_connectors.get(conn_id)
        conn_name = connector_class.get_meta().get("name", conn_id) if connector_class else "Unknown"

        # Заголовок карточки
        title = src.get("filename") if src.get("filename") else "Новый источник"
        icon = "✅" if src.get("active", True) else "zzZ"
        
        with st.expander(f"{icon} {title} ({conn_name})", expanded=(not src.get("filename"))):
            
            # Верхняя панель: Активность и Удаление
            c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
            # Пишем значение напрямую в словарь src
            src["active"] = c1.checkbox("Активен", value=src.get("active", True), key=f"act_{i}")
            
            # Кнопка удаления (Callback безопасен)
            c3.button("🗑️ Удалить", key=f"del_{i}", type="secondary", use_container_width=True, 
                      on_click=remove_source_callback, args=(i,))

            st.markdown("---")
            
            # 1. Выбор типа
            conn_options = list(available_connectors.keys())
            try: cur_idx = conn_options.index(conn_id)
            except: cur_idx = 0
            
            c_type, c_file = st.columns([0.4, 0.6])
            
            # !!! ВАЖНО: Selectbox сам вызывает перезагрузку при смене !!!
            new_conn_id = c_type.selectbox(
                "Тип", conn_options, index=cur_idx, 
                format_func=lambda x: available_connectors[x].get_meta()['name'],
                key=f"type_sel_{i}"
            )
            
            # ЛОГИКА СМЕНЫ ТИПА (БЕЗ ST.RERUN)
            if new_conn_id != src.get("connector_id"):
                # Мы просто обновляем словарь.
                # Streamlit продолжит выполнение кода ниже уже с новыми значениями!
                src["connector_id"] = new_conn_id
                src["config"] = {} # Сбрасываем конфиг при смене типа
                conn_id = new_conn_id # Обновляем локальную переменную для отрисовки полей ниже

            # 2. Имя файла
            src["filename"] = c_file.text_input("Имя файла", value=src.get("filename", ""), placeholder="data.csv", key=f"fn_{i}")

            # 3. Динамические поля (рисуются сразу для НОВОГО типа)
            if conn_id in available_connectors:
                st.write(f"**Настройки {available_connectors[conn_id].get_meta()['name']}:**")
                fields = available_connectors[conn_id].get_fields()
                
                if "config" not in src: src["config"] = {}

                for f in fields:
                    k, lbl = f['key'], f['label']
                    val = src["config"].get(k, f.get('default', ""))
                    
                    w_key = f"cfg_{i}_{conn_id}_{k}"
                    
                    if f.get('type') == 'password':
                        src["config"][k] = st.text_input(lbl, value=str(val), type="password", key=w_key)
                    elif f.get('type') == 'number':
                        src["config"][k] = st.number_input(lbl, value=int(val) if val else 0, key=w_key)
                    else:
                        src["config"][k] = st.text_input(lbl, value=str(val), placeholder=f.get('placeholder', ''), key=w_key)
            
            st.markdown("---")
            # 4. ETL Handler
            try: h_idx = handlers_list.index(src.get("handler", "None"))
            except: h_idx = 0
            src["handler"] = st.selectbox("ETL Обработчик", handlers_list, index=h_idx, key=f"h_{i}")

    st.divider()

    # --- КНОПКА СОХРАНЕНИЯ ---
    if st.button("💾 Сохранить изменения", type="primary", use_container_width=True):
        # 1. Валидация
        valid_sources = []
        for s in st.session_state.wiz_sources:
            if s["filename"]:
                # Авто-добавление расширения
                if not any(s["filename"].endswith(ext) for ext in [".csv", ".xlsx", ".json"]):
                    s["filename"] += ".csv"
                valid_sources.append(s)
        
        # 2. Сохранение в файл
        full_conf = load_json(SOURCES_CONFIG_FILE, {})
        full_conf["sources"] = valid_sources
        save_json(SOURCES_CONFIG_FILE, full_conf)
        
        st.success("✅ Настройки успешно сохранены!")
        # Rerun не нужен, пользователь видит успех и может закрыть окно сам
        time.sleep(2)
        st.rerun()
        
# --- WIZARD: MANAGE PAGES (КРАСИВЫЕ ИМЕНА) ---
@st.dialog("📑 Управление дашбордами", width="large")
def wizard_manage_pages():
    st.write("Создавайте страницы и распределяйте графики.")
    
    pages_conf = load_json(PAGES_CONFIG_FILE, {"B2B Дашборд": []})
    titles_conf = load_json(TITLES_CONFIG_FILE, {}) 
    all_charts = sorted([f for f in os.listdir(CHARTS_FOLDER) if f.endswith(".py")])

    # --- НОВЫЙ БЛОК: РЕДАКТИРОВАНИЕ ЗАГОЛОВКА ---
    with st.expander("🏷️ Название приложения (Заголовок)", expanded=False):
        cur_title = titles_conf.get("app_title", "B2B Отчетность")
        new_title = st.text_input("Введите новое название:", value=cur_title)
        
        if st.button("💾 Обновить название"):
            if new_title and new_title != cur_title:
                titles_conf["app_title"] = new_title
                save_json(TITLES_CONFIG_FILE, titles_conf)
                st.success("Название сохранено!")
                time.sleep(1)
                st.rerun()
    # --------------------------------------------

    if "wiz_pages" not in st.session_state:
        st.session_state.wiz_pages = pages_conf.copy()
        
    c1, c2 = st.columns([0.7, 0.3], vertical_alignment="bottom")
    new_page = c1.text_input("Название новой страницы", placeholder="Логистика")
    if c2.button("➕ Создать страницу", use_container_width=True):
        if new_page and new_page not in st.session_state.wiz_pages:
            st.session_state.wiz_pages[new_page] = []
            save_json(PAGES_CONFIG_FILE, st.session_state.wiz_pages)
            st.rerun()

    st.divider()

    page_names = sorted(st.session_state.wiz_pages.keys())
    if "B2B Дашборд" in page_names:
        page_names.remove("B2B Дашборд")
        page_names.insert(0, "B2B Дашборд")

    def format_chart_name(filename):
        return titles_conf.get(filename, filename)

    for p_name in page_names:
        with st.expander(f"📄 {p_name}", expanded=True):
            current_charts = st.session_state.wiz_pages[p_name]
            current_charts = [c for c in current_charts if c in all_charts]
            
            selected = st.multiselect(
                f"Графики для '{p_name}'", 
                all_charts, 
                default=current_charts,
                key=f"sel_{p_name}",
                format_func=format_chart_name
            )
            
            if selected != st.session_state.wiz_pages[p_name]:
                st.session_state.wiz_pages[p_name] = selected
            
            if p_name != "B2B Дашборд":
                with st.popover(f"🗑️ Удалить страницу '{p_name}'", use_container_width=True):
                    st.caption(f"Вы точно хотите удалить страницу **{p_name}**?")
                    if st.button("🔥 Да, удалить навсегда", key=f"confirm_del_{p_name}", type="primary", use_container_width=True):
                        del st.session_state.wiz_pages[p_name]
                        save_json(PAGES_CONFIG_FILE, st.session_state.wiz_pages)
                        st.rerun()

    st.divider()

    if st.button("💾 Сохранить структуру", type="primary", use_container_width=True, key="save_pages_btn"):
        save_json(PAGES_CONFIG_FILE, st.session_state.wiz_pages)
        del st.session_state.wiz_pages
        if "confirm_delete_page" in st.session_state: del st.session_state.confirm_delete_page
        st.success("Структура обновлена!")
        time.sleep(1)
        st.rerun()


# --- WIZARD: MANAGE LLM INTEGRATIONS ---
@st.dialog("🤖 Интеграции с AI", width="large")
def wizard_manage_llm():
    from modules.llm_manager import get_providers, save_provider, delete_provider
    
    st.write("Настройте подключения к ChatGPT, DeepSeek или другим моделям.")
    
    # Вкладки: Список и Создание
    tab_list, tab_new = st.tabs(["📋 Мои интеграции", "➕ Добавить новую"])
    
    # 1. СПИСОК СУЩЕСТВУЮЩИХ
    with tab_list:
        providers = get_providers()
        if not providers:
            st.info("Нет настроенных интеграций.")
        else:
            for name, data in providers.items():
                with st.expander(f"🔌 {name} ({data['type']})"):
                    st.write(f"**Models:** {', '.join(data['models'])}")
                    st.write(f"**Base URL:** {data['base_url'] if data['base_url'] else 'Default'}")
                    
                    c1, c2 = st.columns([0.8, 0.2])
                    if c2.button("🗑️ Удалить", key=f"del_prov_{name}"):
                        delete_provider(name)
                        st.rerun()

    # 2. СОЗДАНИЕ НОВОЙ
    with tab_new:
        st.write("### Новое подключение")
        
        # Основные поля
        new_name = st.text_input("Название интеграции", placeholder="Например: Corporate DeepSeek")
        
        col_type, col_url = st.columns(2)
        p_type = col_type.selectbox("Тип API", ["openai", "deepseek", "gemini", "other"], help="DeepSeek и 'other' используют формат OpenAI")
        base_url = col_url.text_input("Base URL (Прокси)", placeholder="https://api.openai.com/v1", help="Оставьте пустым для стандарта")
        
        api_key = st.text_input("API Key", type="password")
        
        # Модели
        st.write("### Доступные модели")
        st.caption("Перечислите через запятую названия моделей, которые вы хотите использовать.")
        models_str = st.text_area("Список моделей", placeholder="gpt-4o, gpt-3.5-turbo, deepseek-coder", height=100)
        
        if st.button("💾 Сохранить интеграцию", type="primary"):
            if new_name and api_key and models_str:
                save_provider(new_name, p_type, api_key, base_url, models_str)
                st.success(f"Интеграция '{new_name}' сохранена!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Заполните Название, API Key и список моделей.")