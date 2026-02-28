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

from modules.settings import THEMES_CONFIG_FILE
from modules.settings import DATA_FOLDER, CHARTS_FOLDER, HANDLERS_FOLDER
from modules.utils import sanitize_filename, load_json, save_json
from modules.auth import is_authenticated
from modules.s3_storage import s3_client

# --- ИМПОРТЫ БД ---
from modules.db_manager import SessionLocal
from modules.models import User, Page, Chart, DataSource, ChartTheme, ETLHandler, Workspace

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


# --- WIZARD: CREATE CHART (DUAL MODE + POSTGRESQL) ---
@st.dialog("✨ Новый график")
def wizard_create_chart():
    current_user = st.session_state["username"]
    
    st.write("Заполните параметры задачи.")
    
    # 1. Настройки файла
    st.write("### 1. Настройка файла")
    display_title = st.text_input("Название графика (видит пользователь)", placeholder="Динамика Выручки 2024")
    # 🚨 ПОЛЕ ТЕХНИЧЕСКОГО ID УДАЛЕНО, ГЕНЕРИРУЕМ АВТОМАТИЧЕСКИ 🚨
    
    # --- ВЫБОР ДАННЫХ (ВКЛАДКИ) ---
    st.write("### Источник данных")
    db_sources = SessionLocal()
    try:
        active_ws_id = st.session_state.get("active_ws_id")
        available_sources = db_sources.query(DataSource).filter(DataSource.workspace_id == active_ws_id, DataSource.active == True).all()
    finally:
        db_sources.close()

    tab_db, tab_up = st.tabs(["🗄️ Выбрать из базы", "📤 Загрузить новый"])
    selected_db_sources = []
    up_file = None
    
    with tab_db:
        if available_sources:
            src_dict = {s.id: s for s in available_sources}
            sel_ids = st.multiselect(
                "Выберите готовые источники (можно несколько):", 
                options=list(src_dict.keys()), 
                format_func=lambda x: f"{'📄' if src_dict[x].connector_id == 'google_sheets' else '📁'} {src_dict[x].filename}"
            )
            selected_db_sources = [src_dict[i] for i in sel_ids]
        else:
            st.caption("В этом пространстве пока нет готовых данных.")
            
    with tab_up:
        up_file = st.file_uploader("Загрузить файл", type=["csv", "xlsx"], label_visibility="collapsed")
    
    # 2. Формирование задачи
    st.write("### 2. Формирование задачи")


    # --- УПРАВЛЕНИЕ ПАЛИТРАМИ (БАЗА ДАННЫХ) ---
    @st.fragment
    def theme_manager_fragment():
        # Используем SessionLocal для работы с БД
        db = SessionLocal() 
        try:
            user = db.query(User).filter(User.username == current_user).first()
            user_themes = db.query(ChartTheme).filter(ChartTheme.user_id == user.id).all()

            # 1. Если тем нет, создаем дефолтные
            if not user_themes:
                defaults = [
                    {"name":"Лес (Nature)", "colors": ["#2D6A4F", "#52B788", "#D8F3DC"], "dark": True},
                    {"name":"Океан (Blue)", "colors": ["#0077B6", "#00B4D8", "#90E0EF"], "dark": True},
                    {"name":"Закат (Vibes)", "colors": ["#7209B7", "#F72585", "#FFCC00"], "dark": True},
                    {"name":"ВсеИнструменты", "colors": ["#EE1C25", "#231F20", "#eae7e7"], "dark": True},
                    {"name":"VK", "colors": ["#0035ff", "#000000", "#99A2AD"], "dark": True},
                    {"name":"Сбер", "colors": ["#21A038", "#1A1A1A", "#85C441"], "dark": True},
                    {"name":"Яндекс", "colors": ["#FC3F1D", "#FFCC00", "#000000"], "dark": True},
                    {"name":"Т-Банк", "colors": ["#FFDD2D", "#FFFFFF", "#000000"], "dark": True}
                ]
                for d in defaults:
                    c_str = ",".join(d['colors']) if isinstance(d['colors'], list) else str(d['colors'])
                    
                    new_t = ChartTheme(
                        user_id=user.id, 
                        name=d['name'], 
                        colors=c_str, 
                        dark_mode=d['dark']
                    )
                    db.add(new_t)
                db.commit()
                user_themes = db.query(ChartTheme).filter(ChartTheme.user_id == user.id).all()

            theme_dict = {t.name: t for t in user_themes}
            theme_names = list(theme_dict.keys())

            # 2. Определяем индекс (сессия или дефолт в БД)
            default_idx = 0
            if "last_theme" in st.session_state and st.session_state.last_theme in theme_names:
                default_idx = theme_names.index(st.session_state.last_theme)
            elif user.default_theme_id:
                def_theme = db.query(ChartTheme).filter(ChartTheme.id == user.default_theme_id).first()
                if def_theme and def_theme.name in theme_names:
                    default_idx = theme_names.index(def_theme.name)

            # --- UI: СЕЛЕКТОР + ЗВЕЗДОЧКА ---
            st.write("") 
            col_sel, col_star = st.columns([0.88, 0.12], vertical_alignment="bottom")
            
            with col_sel:
                sel_name = st.selectbox("🎨 Цветовая палитра:", theme_names, index=default_idx, key="theme_selector")
            
            st.session_state.last_theme = sel_name
            current_theme_obj = theme_dict[sel_name]
            
            # Логика звезды
            is_default = (user.default_theme_id == current_theme_obj.id)
            star_icon = "⭐" if is_default else "☆"
            star_help = "Это ваша тема по умолчанию" if is_default else "Сделать темой по умолчанию"

            with col_star:
                # Кнопка-звездочка
                if st.button(star_icon, help=star_help, key=f"star_{current_theme_obj.id}", use_container_width=True):
                    if not is_default:
                        user.default_theme_id = current_theme_obj.id
                        db.commit()
                        st.toast(f"'{sel_name}' теперь по умолчанию!")
                        st.rerun(scope="fragment")

            # --- ОТОБРАЖЕНИЕ ЦВЕТОВ ---
            raw_colors = current_theme_obj.colors.replace("[", "").replace("]", "").replace("'", "").replace('"', "").replace(" ", "")
            c_colors = raw_colors.split(",")
            c_dark = current_theme_obj.dark_mode

            st.session_state.wiz_active_colors = c_colors
            st.session_state.wiz_active_dark = c_dark

            st.markdown("<div style='margin: 10px 0;'></div>", unsafe_allow_html=True) 
            cols = st.columns(len(c_colors))
            for i, color in enumerate(c_colors):
                with cols[i]:
                    st.markdown(f'<div style="background-color:{color};width:100%;height:35px;border-radius:6px;border:1px solid rgba(128,128,128,0.3);"></div>', unsafe_allow_html=True)

            # 4. Редактор тем (экспандер)
            st.write("") 
            with st.expander("⚙️ Настроить свои палитры"):
                edit_name = st.text_input("Название темы:", value=sel_name, key=f"ed_nm_{current_theme_obj.id}")
                is_dark = st.checkbox("Адаптировать для Dark Mode", value=c_dark, key=f"drk_{current_theme_obj.id}")
                
                ce1, ce2, ce3 = st.columns(3)
                nc1 = ce1.color_picker("1", value=c_colors[0], key=f"cp1_{current_theme_obj.id}")
                nc2 = ce2.color_picker("2", value=c_colors[1], key=f"cp2_{current_theme_obj.id}")
                nc3 = ce3.color_picker("3", value=c_colors[2], key=f"cp3_{current_theme_obj.id}")
                
                st.write("")
                bc1, bc2, bc3 = st.columns([0.4, 0.4, 0.2])
                
                if bc1.button("💾 Сохранить", use_container_width=True, key=f"upd_btn_{current_theme_obj.id}"):
                    current_theme_obj.name = edit_name
                    current_theme_obj.colors = f"{nc1},{nc2},{nc3}"
                    current_theme_obj.dark_mode = is_dark
                    db.commit()
                    st.toast("Палитра сохранена!")
                    st.rerun(scope="fragment")

                if bc2.button("➕ Как новую", use_container_width=True, key=f"new_btn_{current_theme_obj.id}"):
                    new_t = ChartTheme(user_id=user.id, name=f"{edit_name} (Copy)", colors=f"{nc1},{nc2},{nc3}", dark_mode=is_dark)
                    db.add(new_t)
                    db.commit()
                    st.session_state.last_theme = new_t.name
                    st.rerun(scope="fragment")

                if bc3.button("🗑️", use_container_width=True, key=f"del_btn_{current_theme_obj.id}"):
                    if len(user_themes) > 1:
                        db.delete(current_theme_obj)
                        db.commit()
                        st.session_state.last_theme = theme_names[0] if theme_names[0] != sel_name else theme_names[1]
                        st.rerun(scope="fragment")
        finally:
            db.close()
    
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
        # Убрана проверка filename_base
        if not (display_title and goal) or (not up_file and not selected_db_sources):
            st.error("Заполните основные поля (Название, Цель) и выберите/загрузите данные!")
            return

        current_colors = st.session_state.get("wiz_active_colors", ["#000", "#000", "#000"])
        current_dark_mode = st.session_state.get("wiz_active_dark", False)
        colors_prompt_str = ", ".join(current_colors)

        # 1. СОХРАНЯЕМ ИЛИ ИЩЕМ ФАЙЛ ДАННЫХ ДЛЯ АНАЛИЗА КОЛОНОК AI
        target_filename = up_file.name if up_file else selected_db_sources[0].filename
        path = os.path.join(DATA_FOLDER, target_filename)
        
        if up_file:
            with open(path, "wb") as f: f.write(up_file.getbuffer())
            s3_client.upload_file(path, "data-sources", target_filename)
        else:
            # Если файл из базы, но локально его нет (удалился кэш), скачиваем из S3
            if not os.path.exists(path):
                try: s3_client.download_file("data-sources", target_filename, path)
                except: pass

        # --- 2. УМНАЯ АВТОГЕНЕРАЦИЯ ИМЕНИ ФАЙЛА (py_name) ---
        import uuid
        db_check = SessionLocal()
        try:
            while True:
                # Генерируем chart_ + 8 случайных символов
                unique_hash = uuid.uuid4().hex[:8]
                py_name = f"chart_{unique_hash}.py"
                # Проверяем на дубликаты
                if not db_check.query(Chart).filter(Chart.technical_name == py_name).first():
                    break
        finally:
            db_check.close()
        # ---------------------------------------------------

        # 3. АНАЛИЗ КОЛОНОК
        try:
            df_preview = pd.read_csv(path, nrows=5) if path.endswith('.csv') else pd.read_excel(path, nrows=5)
            cols_info = "\n".join([f"- `{c}` ({t})" for c, t in zip(df_preview.columns, df_preview.dtypes)])
        except Exception as e:
            cols_info = f"Нет доступа к колонкам (AI напишет обобщенный код): {e}"

        # 4. ФОРМИРОВАНИЕ ПРОМПТА
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

        controls_instruction = f"ЭЛЕМЕНТЫ УПРАВЛЕНИЯ: {chart_controls}. Используй st.selectbox/slider внутри render." if chart_controls else ""

        final_prompt = (
            "РОЛЬ: Ты Senior Python Developer (Streamlit/Plotly). Твоя цель — писать чистый, читаемый код.\n"
            f"ЗАДАЧА: {goal}\n"
            f"ВИД: {chart_format}\n{style_instruction}\n"
            f"КОНТЕКСТ ДАННЫХ: Файлы `files`. Колонки:\n{cols_info}\n\n"
            f"{controls_instruction}\n"
            "--- ТЕХНИЧЕСКИЙ СТАНДАРТ ---\n"
            "1. СИГНАТУРА:\n"
            f"   `def render(files, chart_key='{py_name}'):`\n"
            "   (chart_key нужен для уникальности ключей виджетов).\n\n"
            "2. ЛОГИКА:\n"
            "   - Загрузи данные (pd.concat).\n"
            "   - Используй стандартные `st.selectbox` / `st.slider` для фильтрации.\n"
            "   - ОБЯЗАТЕЛЬНО: В каждом виджете используй `key=f'{chart_key}_name'`.\n"
            "   - Построй график `fig` через Plotly Express.\n"
            "   - Примени тему: `fig.update_layout(template='plotly_dark')` (или white).\n"
            "   - ВЕРНИ объект `fig` в конце функции.\n"
            "   - Также выведи его: `st.plotly_chart(fig, use_container_width=True)`.\n\n"
            "--- ПРИМЕР ЧИСТОГО КОДА ---\n"
            "```python\n"
            "import streamlit as st\nimport plotly.express as px\nimport pandas as pd\n\n"
            "def render(files, chart_key='unique_id'):\n"
            "    if not files: return\n"
            "    # 1. Load\n"
            "    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)\n"
            "    \n"
            "    # 2. Filter (Standard Streamlit)\n"
            "    years = sorted(df['Year'].unique())\n"
            "    sel_year = st.selectbox('Год', years, key=f'{chart_key}_year')\n"
            "    df_filtered = df[df['Year'] == sel_year]\n"
            "    \n"
            "    # 3. Plot\n"
            "    fig = px.bar(df_filtered, x='Month', y='Revenue')\n"
            "    fig.update_layout(template='plotly_dark', margin=dict(t=40, b=40))\n"
            "    \n"
            "    # 4. Render & Return\n"
            "    st.plotly_chart(fig, use_container_width=True)\n"
            "    return fig\n"
            "```\n"
            "ВЕРНИ ТОЛЬКО КОД."
        )

        file_content = ""

        # --- РАЗВИЛКА: АВТО ИЛИ РУЧНОЙ ---
        if btn_manual:
            safe_prompt = final_prompt.replace('"""', "'''")
            file_content = (
                f'"""\n--- MANUAL MODE ---\nЗАДАЧА:\n{safe_prompt}\n"""\n\n'
                "import streamlit as st\ndef render(files, chart_key='default_key'):\n    st.info('График создан (Ручной режим).')\n    return None\n"
            )
            st.session_state.gen_prompt = final_prompt
            
            # Сохраняем файл физически
            with open(os.path.join(CHARTS_FOLDER, py_name), "w", encoding="utf-8") as f: f.write(file_content)
            s3_client.put_text("charts", py_name, file_content)
            
            # Регистрируем в БД (Синхронно)
            db = SessionLocal()
            try:
                active_ws_id = st.session_state.get("active_ws_id")
                new_chart = Chart(workspace_id=active_ws_id, technical_name=py_name, display_name=display_title)
                db.add(new_chart)
                
                if up_file:
                    exist_ds = db.query(DataSource).filter(DataSource.filename == up_file.name, DataSource.workspace_id == active_ws_id).first()
                    if not exist_ds:
                        new_ds = DataSource(workspace_id=active_ws_id, connector_id="base", filename=up_file.name, active=True)
                        db.add(new_ds)
                        new_chart.data_sources.append(new_ds)
                    else:
                        new_chart.data_sources.append(exist_ds)
                
                for ds_obj in selected_db_sources:
                    local_ds = db.query(DataSource).get(ds_obj.id)
                    if local_ds and local_ds not in new_chart.data_sources:
                        new_chart.data_sources.append(local_ds)
                        
                current_page_name = st.query_params.get("page", "Главная страница")
                page = db.query(Page).filter(Page.workspace_id == active_ws_id, Page.name == current_page_name).first()
                if not page:
                    page = db.query(Page).filter(Page.workspace_id == active_ws_id).first()
                if page: page.charts.append(new_chart)
                    
                db.commit()
                st.success("✅ Заготовка создана!")
            finally:
                db.close()
            time.sleep(1)
            st.rerun()

        elif btn_auto:
            if not llm_ready:
                st.error("Сначала настройте AI интеграцию!")
                return
            
            # 👇 Добавляем тот самый крутящийся кружок!
            with st.spinner("🤖 Сохраняем данные и отправляем ИИ..."):
                
                # 1. Сохраняем новые файлы в БД СРАЗУ, чтобы передать их ID в Celery
                db = SessionLocal()
                ds_ids = []
                user_id_for_task = None  
                try:
                    user = db.query(User).filter(User.username == current_user).first()
                    if user:
                        user_id_for_task = user.id

                    active_ws_id = st.session_state.get("active_ws_id")
                    if up_file:
                        exist_ds = db.query(DataSource).filter(DataSource.filename == up_file.name, DataSource.workspace_id == active_ws_id).first()
                        if not exist_ds:
                            new_ds = DataSource(workspace_id=active_ws_id, connector_id="base", filename=up_file.name, active=True)
                            db.add(new_ds)
                            db.commit()
                            ds_ids.append(new_ds.id)
                        else:
                            ds_ids.append(exist_ds.id)
                            
                    for ds_obj in selected_db_sources:
                        ds_ids.append(ds_obj.id)
                finally:
                    db.close()
                
                # 2. Отправляем тяжелую задачу в REDIS! 🚀
                from modules.tasks import generate_chart_task
                current_page_name = st.query_params.get("page", "Главная страница")
                
                task = generate_chart_task.delay(
                    prompt=final_prompt,
                    py_name=py_name,
                    display_title=display_title,
                    sel_prov=sel_prov,
                    sel_model=sel_model,
                    active_ws_id=active_ws_id,
                    current_page_name=current_page_name,
                    ds_ids=ds_ids,
                    user_id=user_id_for_task
                )
                
                # Добавляем задачу в трекер на главном экране
                if "active_tasks" not in st.session_state:
                    st.session_state.active_tasks = {}
                st.session_state.active_tasks[task.id] = f"AI код для '{display_title}'"
                
                # 👇 Добавляем красивое уведомление об успехе
                st.toast("✅ Задача успешно отправлена в фон!")
                time.sleep(0.5) # Даем полсекунды, чтобы пользователь успел увидеть сообщение
                
                st.rerun() # Мгновенно закрываем визард!
# --- WIZARD: MANAGE SOURCES ---
@st.dialog("⚙️ Пайплайн данных", width="large")
def wizard_manage_sources():
    from modules.connector_loader import load_connectors
    
    current_username = st.session_state["username"]
    db = SessionLocal()
    available_connectors = load_connectors()
    
    try:
        active_ws_id = st.session_state.get("active_ws_id")
        sources_db = db.query(DataSource).filter(DataSource.workspace_id == active_ws_id).all()
        
        from modules.models import ETLHandler
        # Получаем красивые имена обработчиков из БД для текущего воркспейса
        db_handlers = db.query(ETLHandler).filter(ETLHandler.workspace_id == active_ws_id).all()
        handlers_dict = {h.name: h.id for h in db_handlers}
        handlers_id_to_name = {h.id: h.name for h in db_handlers} 
        
        handlers_list = ["Не выбран"] + list(handlers_dict.keys())

        st.write("### 🔗 Подключения к данным")
        
        if st.button("➕ Добавить новый источник (API)", use_container_width=True):
            new_ds = DataSource(
                workspace_id=active_ws_id,
                connector_id="google_sheets",
                filename="new_data.csv",
                config_json={},
                active=True
            )
            db.add(new_ds)
            db.commit()
            st.rerun(scope="fragment")

        st.divider()

        for src in sources_db:
            conn_id = src.connector_id
            
            # Определяем ИМЯ КОННЕКТОРА
            if conn_id == "base":
                conn_name = "📂 Локальный файл"
                connector_class = None
            else:
                connector_class = available_connectors.get(conn_id)
                conn_name = connector_class.get_meta().get("name", conn_id) if connector_class else "Unknown"

            handler_badge = f" ➔ 🛠️ {handlers_id_to_name[src.handler_id]}" if src.handler_id and src.handler_id in handlers_id_to_name else ""
            with st.expander(f"{'✅' if src.active else '⚪'} {src.filename} ({conn_name}){handler_badge}"):
                c1, c2 = st.columns([0.8, 0.2])
                
                src.active = c1.toggle("Активен", value=src.active, key=f"active_{src.id}")
                
                if c2.button("🗑️", key=f"del_src_{src.id}", help="Удалить источник"):
                    # Отвязываем от графиков и удаляем
                    linked_charts = db.query(Chart).filter(Chart.data_sources.contains(src)).all()
                    for chart in linked_charts:
                        chart.data_sources.remove(src)
                    db.delete(src)
                    db.commit()
                    st.rerun(scope="fragment")

                # --- РАЗВИЛКА ИНТЕРФЕЙСА: Локальный файл ИЛИ Коннектор ---
                if conn_id == "base":
                    # ИНТЕРФЕЙС ЛОКАЛЬНОГО ФАЙЛА
                    st.info("Это статичный файл, загруженный вручную.")
                    src.filename = st.text_input("Имя файла в системе", value=src.filename, key=f"fn_{src.id}")
                    
                    st.write("**Заменить данные:**")
                    new_file = st.file_uploader("Загрузить новую версию (заменит текущую)", type=["csv", "xlsx"], key=f"up_{src.id}", label_visibility="collapsed")
                    if new_file:
                        if st.button("🔄 Обновить файл", use_container_width=True, key=f"btn_up_{src.id}"):
                            # Перезаписываем физический файл под старым именем (чтобы не сломать графики)
                            path = os.path.join(DATA_FOLDER, src.filename)
                            with open(path, "wb") as f: 
                                f.write(new_file.getbuffer())
                            # Отправляем обновленный файл в S3
                            s3_client.upload_file(path, "data-sources", src.filename)
                            
                            st.success("✅ Данные успешно обновлены!")
                            time.sleep(1)
                            st.rerun(scope="fragment")

                else:
                    # ИНТЕРФЕЙС КОННЕКТОРА (API)
                    col_id, col_file = st.columns(2)
                    
                    # Защита от ошибки, если коннектор не найден
                    options = list(available_connectors.keys())
                    cur_idx = options.index(conn_id) if conn_id in options else 0
                    
                    new_cid = col_id.selectbox(
                        "Тип коннектора", 
                        options=options,
                        index=cur_idx,
                        format_func=lambda x: available_connectors[x].get_meta()['name'],
                        key=f"type_{src.id}"
                    )
                    
                    if new_cid != src.connector_id:
                        src.connector_id = new_cid
                        src.config_json = {}
                        db.commit()
                        st.rerun(scope="fragment")

                    src.filename = col_file.text_input("Имя файла в системе", value=src.filename, key=f"fn_{src.id}")

                    if connector_class:
                        fields = connector_class.get_fields()
                        st.write("**Настройки подключения:**")
                        
                        temp_config = src.config_json or {}
                        for f in fields:
                            k, lbl = f['key'], f['label']
                            val = temp_config.get(k, f.get('default', ""))
                            
                            if f.get('type') == 'password':
                                temp_config[k] = st.text_input(lbl, value=str(val), type="password", key=f"cfg_{src.id}_{k}")
                            else:
                                temp_config[k] = st.text_input(lbl, value=str(val), key=f"cfg_{src.id}_{k}")
                        
                        src.config_json = temp_config

                # --- ОБЩИЙ БЛОК: Выбор ETL обработчика ---
                st.markdown("---")
                current_h_name = "Не выбран"
                if src.handler_id:
                    h_obj = db.query(ETLHandler).filter(ETLHandler.id == src.handler_id).first()
                    if h_obj: current_h_name = h_obj.name

                try: h_idx = handlers_list.index(current_h_name)
                except: h_idx = 0
                    
                sel_h_name = st.selectbox("Скрипт обработки (ETL)", handlers_list, index=h_idx, key=f"h_{src.id}", help="Скрипт будет применяться к этим данным.")
                
                # Обновляем ID, а не имя файла
                new_h_id = handlers_dict.get(sel_h_name, None)
                if new_h_id != src.handler_id:
                    src.handler_id = new_h_id

        st.divider()
        if st.button("💾 Сохранить всё", type="primary", use_container_width=True):
            db.commit()
            st.success("Данные синхронизированы с БД!")
            time.sleep(1)
            st.rerun()

    except Exception as e:
        st.error(f"Ошибка БД: {e}")
        db.rollback()
    finally:
        db.close()

# --- WIZARD: MANAGE PAGES ---
@st.dialog("📑 Управление дашбордами", width="large")
def wizard_manage_pages():
    current_username = st.session_state["username"]
    db = SessionLocal()
    
    try:
        active_ws_id = st.session_state.get("active_ws_id")
        user_pages = db.query(Page).filter(Page.workspace_id == active_ws_id).all()
        
        available_charts = db.query(Chart).filter(Chart.workspace_id == active_ws_id).all()
        chart_options = {c.technical_name: c.display_name for c in available_charts}

        st.write("### 🏗️ Структура вашего проекта")

        c1, c2 = st.columns([0.7, 0.3], vertical_alignment="bottom")
        new_pg_name = c1.text_input("Название новой страницы", placeholder="Например: Продажи 2024")
        if c2.button("➕ Создать страницу", use_container_width=True):
            if new_pg_name:
                new_pg = Page(workspace_id=active_ws_id, name=new_pg_name)
                db.add(new_pg)
                db.commit()
                st.toast(f"Страница '{new_pg_name}' создана")
                st.rerun(scope="fragment")

        st.divider()

        for pg in user_pages:
            with st.expander(f"📄 {pg.name}", expanded=True):
                current_selected = [c.technical_name for c in pg.charts]
                
                selected_names = st.multiselect(
                    f"Какие графики показать на '{pg.name}':", 
                    options=list(chart_options.keys()), 
                    default=current_selected,
                    format_func=lambda x: chart_options.get(x, x),
                    key=f"ms_pg_{pg.id}"
                )
                
                if set(selected_names) != set(current_selected):
                    pg.charts = [c for c in available_charts if c.technical_name in selected_names]
                    db.commit()
                    st.toast(f"Обновлено для '{pg.name}'")

                if pg.name != "Главная страница":
                    with st.popover(f"🗑️ Удалить страницу", use_container_width=True):
                        st.warning("Удалить страницу? Графики останутся в базе.")
                        if st.button("Да, удалить", key=f"del_pg_{pg.id}", type="primary", use_container_width=True):
                            # Сначала очищаем связи, потом удаляем страницу
                            pg.charts = []
                            db.delete(pg)
                            db.commit()
                            st.rerun(scope="fragment")

    except Exception as e:
        st.error(f"Ошибка базы данных: {e}")
    finally:
        db.close()

    if st.button("✅ Готово", type="primary", use_container_width=True):
        st.rerun()


# --- WIZARD: MANAGE LLM INTEGRATIONS ---
@st.dialog("🤖 Интеграции с AI", width="large")
def wizard_manage_llm():
    from modules.llm_manager import get_providers, save_provider, delete_provider
    
    st.write("Настройте подключения к ChatGPT, DeepSeek или другим моделям.")
    
    tab_list, tab_new = st.tabs(["📋 Мои интеграции", "➕ Добавить новую"])
    
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
                        st.rerun(scope="fragment")

    with tab_new:
        st.write("### Новое подключение")
        
        new_name = st.text_input("Название интеграции", placeholder="Например: Corporate DeepSeek")
        
        col_type, col_url = st.columns(2)
        p_type = col_type.selectbox("Тип API", ["openai", "deepseek", "gemini", "other"], help="DeepSeek и 'other' используют формат OpenAI")
        base_url = col_url.text_input("Base URL (Прокси)", placeholder="[https://api.openai.com/v1](https://api.openai.com/v1)", help="Оставьте пустым для стандарта")
        
        api_key = st.text_input("API Key", type="password")
        
        st.write("### Доступные модели")
        st.caption("Перечислите через запятую названия моделей, которые вы хотите использовать.")
        models_str = st.text_area("Список моделей", placeholder="gpt-4o, gpt-3.5-turbo, deepseek-coder", height=100)
        
        if st.button("💾 Сохранить интеграцию", type="primary"):
            if new_name and api_key and models_str:
                save_provider(new_name, p_type, api_key, base_url, models_str)
                st.success(f"Интеграция '{new_name}' сохранена!")
                time.sleep(1)
                st.rerun(scope="fragment")
            else:
                st.error("Заполните Название, API Key и список моделей.")


# --- WIZARD: УПРАВЛЕНИЕ ПРОСТРАНСТВАМИ (WORKSPACES) ---
@st.dialog("🏢 Управление пространствами", width="large")
def wizard_manage_workspaces():
    current_username = st.session_state["username"]
    db = SessionLocal()

    try:
        current_user = db.query(User).filter(User.username == current_username).first()
        all_users = db.query(User).all()
        user_dict = {u.id: u.username for u in all_users}

        st.write("### ➕ Создать новое пространство")
        c1, c2 = st.columns([0.7, 0.3], vertical_alignment="bottom")
        new_ws_name = c1.text_input("Название (например: Маркетинг)", key="new_ws_name")

        if c2.button("Создать", use_container_width=True, type="primary"):
            if new_ws_name:
                new_ws = Workspace(name=new_ws_name, owner_id=current_user.id)
                new_ws.users.append(current_user)
                db.add(new_ws)
                db.commit()
                st.session_state.active_ws_id = new_ws.id
                st.toast(f"Пространство '{new_ws_name}' создано!")
                st.rerun()

        st.divider()
        st.write("### 👥 Мои пространства")

        for ws in current_user.workspaces:
            is_owner = ws.owner_id == current_user.id
            role_text = "👑 Владелец" if is_owner else "👤 Участник"

            with st.expander(f"🏢 {ws.name} ({role_text})"):
                current_members = [u.id for u in ws.users]

                if is_owner:
                    # Владелец может добавлять и удалять коллег
                    new_members = st.multiselect(
                        "Участники (могут просматривать и редактировать):",
                        options=list(user_dict.keys()),
                        default=current_members,
                        format_func=lambda x: user_dict[x],
                        key=f"ws_members_{ws.id}"
                    )

                    if set(new_members) != set(current_members):
                        ws.users = [db.query(User).get(uid) for uid in new_members]
                        # Защита от случайного удаления самого себя (владельца)
                        if current_user not in ws.users:
                            ws.users.append(current_user)
                            st.toast("⚠️ Владелец не может удалить сам себя!")
                            
                        db.commit()
                        st.rerun()

                    # Личное пространство удалить нельзя
                    if not ws.name.startswith("Личное ("):
                        if st.button("🗑️ Удалить пространство", key=f"del_ws_{ws.id}"):
                            # Удаляем связи и сам воркспейс
                            db.delete(ws)
                            db.commit()
                            if st.session_state.active_ws_id == ws.id:
                                st.session_state.active_ws_id = current_user.workspaces[0].id
                            st.rerun(scope="fragment")
                else:
                    # Обычный участник видит список коллег и может выйти
                    st.write("**Участники:**", ", ".join([user_dict[uid] for uid in current_members]))
                    if st.button("🚪 Покинуть пространство", key=f"leave_{ws.id}"):
                        ws.users.remove(current_user)
                        db.commit()
                        if st.session_state.active_ws_id == ws.id:
                            st.session_state.active_ws_id = current_user.workspaces[0].id
                        st.rerun(scope="fragment")

    finally:
        db.close()