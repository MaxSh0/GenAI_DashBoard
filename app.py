import streamlit as st
import streamlit_authenticator as stauth
import os
import glob
import importlib.util
import time
import concurrent.futures
from code_editor import code_editor
import shutil
import pandas as pd
import random
# --- ИМПОРТЫ CELERY ---
from modules.tasks import update_source_task, celery_app
from celery.result import AsyncResult
# --- ИМПОРТЫ ---
from modules.auth import is_authenticated, logout_user, login_redirect, check_auth_code
from modules.settings import *
from modules.data_loader import sync_single_source
from modules.wizards import wizard_create_chart, wizard_manage_sources, wizard_manage_pages, wizard_manage_llm, wizard_manage_workspaces
from modules.io_manager import BundleManager
from modules.llm_manager import get_providers, ask_llm
from modules.s3_storage import s3_client
from modules.db_manager import SessionLocal, init_db
from modules.models import User, Page, Chart, DataSource, ETLHandler, Workspace
from modules.utils import sanitize_filename
# ==========================================
# 1. PAGE CONFIG & INIT
# ==========================================
st.set_page_config(page_title="GenAI DashBoard", layout="wide")
init_db() 
init_project_structure()
s3_client.init_buckets(["charts", "handlers", "data-sources"])

# ==========================================
# 2. АУТЕНТИФИКАЦИЯ ЧЕРЕЗ БД
# ==========================================
db_auth = SessionLocal()
try:
    users_db = db_auth.query(User).all()
    credentials = {"usernames": {u.username: {"email": u.email, "name": u.name, "password": u.password_hash} for u in users_db}}
finally:
    db_auth.close()

authenticator = stauth.Authenticate(credentials, "cookie_v1", "key_v1", 30)

try:
    # В новых версиях библиотеки лучше явно указывать location
    authenticator.login(location='main') 
except Exception as e:
    st.error(e)

# ==========================================
# 3. ОСНОВНАЯ ЛОГИКА ПРИЛОЖЕНИЯ
# ==========================================
if st.session_state["authentication_status"]:
    if "active_tasks" not in st.session_state:
        st.session_state.active_tasks = {}
    current_username = st.session_state["username"]
    db = SessionLocal()
    
    # 1. Получаем пользователя
    user_obj = db.query(User).filter(User.username == current_username).first()
    if not user_obj:
        st.warning("⚠️ Ваша сессия устарела (пользователь не найден в текущей базе данных).")
        # Выводим штатную кнопку выхода, которая корректно убьет зависшую куку
        authenticator.logout("🔄 Сбросить сессию и выйти", key="ghost_logout")
        st.stop()

    # --- ИНИЦИАЛИЗАЦИЯ ВОРКСПЕЙСА ---
    user_workspaces = user_obj.workspaces
    if not user_workspaces:
        # Если пространств нет, создаем личное
        default_ws = Workspace(name=f"Личное ({user_obj.username})", owner_id=user_obj.id)
        default_ws.users.append(user_obj)
        db.add(default_ws)
        db.commit()
        db.refresh(default_ws)
        user_workspaces = [default_ws]


    # 2. Инициализируем пространства (Workspaces)
    user_workspaces = user_obj.workspaces
    if not user_workspaces:
        default_ws = Workspace(name=f"Личное ({user_obj.username})", owner_id=user_obj.id)
        default_ws.users.append(user_obj)
        db.add(default_ws); db.commit(); db.refresh(default_ws)
        user_workspaces = [default_ws]

    # --- ХЕЛПЕРЫ ---
    check_auth_code()

    # ==================== SIDEBAR ====================
    with st.sidebar:
        name_weight = max(len(user_obj.name), 5) 
        c1, c2 = st.sidebar.columns([name_weight, 2], gap="small", vertical_alignment="center")
        c1.markdown(f"👤 **{user_obj.name}**")
        with c2:
            authenticator.logout('🚪', key='sidebar_exit')
            
        st.divider()
        
        # --- СЕЛЕКТОР ВОРКСПЕЙСА ---
        ws_dict = {ws.id: ws.name for ws in user_workspaces}
        
        # 1. Приоритет: смотрим в URL
        url_ws_id = st.query_params.get("ws")
        if url_ws_id and int(url_ws_id) in ws_dict:
            st.session_state.active_ws_id = int(url_ws_id)
        
        # 2. Если в URL пусто, но есть в сессии - оставляем как есть. 
        # 3. Если везде пусто - берем первый доступный.
        elif "active_ws_id" not in st.session_state or st.session_state.active_ws_id not in ws_dict:
            st.session_state.active_ws_id = user_workspaces[0].id
            st.query_params["ws"] = str(st.session_state.active_ws_id)
            
        c_ws, c_ws_btn = st.columns([0.85, 0.15], vertical_alignment="bottom")
        sel_ws_id = c_ws.selectbox("🏢 Пространство:", options=list(ws_dict.keys()), format_func=lambda x: ws_dict[x], index=list(ws_dict.keys()).index(st.session_state.active_ws_id), key="workspace_selector")
        if c_ws_btn.button("⚙️", key=f"btn_manage_ws_{user_obj.id}_1", help="Управление пространствами"):
            wizard_manage_workspaces()
            
        if sel_ws_id != st.session_state.active_ws_id:
            st.session_state.active_ws_id = sel_ws_id
            st.query_params["ws"] = str(sel_ws_id) # Записываем в URL
            st.rerun()
            
        # Загружаем страницы ТОЛЬКО для активного воркспейса
        user_pages = db.query(Page).filter(Page.workspace_id == st.session_state.active_ws_id).all()
        if not user_pages:
            new_p = Page(workspace_id=st.session_state.active_ws_id, name="Главная страница")
            db.add(new_p); db.commit(); db.refresh(new_p)
            user_pages = [new_p]

        st.divider()
        st.title("📊 GenAI DashBoard")
        
        # --- 1. ДАШБОРДЫ ---
        st.header("📑 Дашборды")
        page_names = [p.name for p in user_pages]
        query_params = st.query_params
        
        d_idx = page_names.index(query_params["page"]) if "page" in query_params and query_params["page"] in page_names else 0
        current_page_name = st.selectbox("Выберите страницу:", page_names, index=d_idx, label_visibility="collapsed", key="db_page_sel")
        st.query_params["page"] = current_page_name
        
        current_page_obj = next(p for p in user_pages if p.name == current_page_name)

        c_info, c_ren, c_set = st.columns([0.6, 0.2, 0.2], vertical_alignment="center")
        c_info.caption(f"Графиков: {len(current_page_obj.charts)}")
        
        with c_ren:
            with st.popover("✏️", help="Переименовать", use_container_width=True):
                new_n = st.text_input("Название:", value=current_page_obj.name, key=f"ren_pg_{current_page_obj.id}")
                if st.button("Сохранить", key=f"btn_ren_pg_{current_page_obj.id}", type="primary"):
                    if new_n and new_n != current_page_obj.name:
                        current_page_obj.name = new_n; db.commit(); st.query_params["page"] = new_n; st.rerun()

        if c_set.button("⚙️", help="Настройки состава", key="btn_pg_settings"):
            wizard_manage_pages()
        
        st.divider()

        # --- 2. ДАННЫЕ И ИСТОЧНИКИ ---
        if GUIDE_URL: st.link_button("📘 Инструкция", GUIDE_URL, use_container_width=True)
        st.header("☁️ Данные")
        
        with st.popover("🔐 Доступ (Google)", use_container_width=True):
            if is_authenticated():
                st.success("Google: ✅ OK")
                if st.button("Выйти", use_container_width=True, key="btn_logout"): logout_user(); st.rerun()
            else:
                st.error("Google: ❌ Off"); login_redirect()

        active_sources_db = db.query(DataSource).filter(DataSource.workspace_id == st.session_state.active_ws_id, DataSource.active == True).all()
        
        # --- КОМПАКТНАЯ СТРОКА: ПОИСК + ЗАГРУЗКА ---
        c_search, c_upload = st.columns([0.85, 0.15], vertical_alignment="center")
        search_q = c_search.text_input("Поиск...", placeholder="🔍 Найти...", label_visibility="collapsed", key="src_search")
        
        with c_upload:
            with st.popover("📤", help="Загрузить локальный CSV/Excel файл"):
                man_file = st.file_uploader("Загрузка файла", type=["csv", "xlsx"], label_visibility="collapsed")
                if man_file:
                    if st.button("💾 Сохранить", type="primary", use_container_width=True):
                        # 1. Сохраняем физически (локальный кэш + облако S3)
                        path = os.path.join(DATA_FOLDER, man_file.name)
                        with open(path, "wb") as f: 
                            f.write(man_file.getbuffer())
                        s3_client.upload_file(path, "data-sources", man_file.name)
                        
                        # 2. Регистрируем в БД как "base" (локальный файл)
                        exist_ds = db.query(DataSource).filter(DataSource.filename == man_file.name, DataSource.workspace_id == st.session_state.active_ws_id).first()
                        if not exist_ds:
                            new_ds = DataSource(workspace_id=st.session_state.active_ws_id, connector_id="base", filename=man_file.name, active=True)
                            db.add(new_ds)
                        
                        db.commit()
                        st.rerun()
        
        # --- НЕВИДИМЫЙ ТРЕКЕР ФОНОВЫХ ЗАДАЧ (ДЛЯ ДАННЫХ) ---
        @st.fragment(run_every=2)
        def invisible_task_tracker():
            if not st.session_state.get("active_tasks"):
                return

            completed_tasks = []
            for task_id, task_desc in list(st.session_state.active_tasks.items()):
                # ПРОПУСКАЕМ графики (у них будет свой красивый интерфейс внизу)
                if str(task_desc).startswith("AI код для"):
                    continue

                res = AsyncResult(task_id, app=celery_app)
                
                if res.ready(): 
                    result_data = res.result
                    if result_data and isinstance(result_data, dict) and result_data.get("status"):
                        st.toast(f"✅ {task_desc} выполнено!")
                    else:
                        err_msg = result_data.get('msg') if isinstance(result_data, dict) else 'Неизвестная ошибка'
                        st.error(f"❌ Ошибка ({task_desc}): {err_msg}")
                    completed_tasks.append(task_id)

            for t in completed_tasks:
                del st.session_state.active_tasks[t]
            
            if completed_tasks:
                time.sleep(1)
                st.rerun()

        invisible_task_tracker()

        
        with st.container(height=200, border=True):
            if not active_sources_db: st.caption("Нет источников.")
            for i, src in enumerate(active_sources_db):
                if search_q and search_q.lower() not in src.filename.lower(): continue
                
                c_icon = {"google_sheets": "📄", "ytsaurus": "🦖"}.get(src.connector_id, "📁")
                r_c1, r_c2 = st.columns([0.8, 0.2], vertical_alignment="center")
                
                disp_name = (src.filename[:16] + '..') if len(src.filename) > 18 else src.filename
                handler_info = f" &nbsp;<span style='color: #888888; font-size: 0.85em; white-space: nowrap;'>🛠️ {src.handler.name}</span>" if src.handler else ""
                r_c1.markdown(f"{c_icon} `{disp_name}`{handler_info}", help=f"Файл: {src.filename}", unsafe_allow_html=True)
                
                if src.connector_id != "base":
                    # Проверяем, есть ли имя этого файла в списке активных задач
                    is_running = any(src.filename in desc for desc in st.session_state.active_tasks.values())
                    
                    if is_running:
                        # Если задача идет, прячем кнопку и показываем статус
                        r_c2.markdown("<span style='color:#888; font-size: 0.85em;'>🔄 В процессе..</span>", unsafe_allow_html=True)
                    else:
                        if r_c2.button("↻", key=f"upd_src_{src.id}"):
                            creds = st.session_state.get("google_creds")
                            task = update_source_task.delay(src.id, creds)
                            st.session_state.active_tasks[task.id] = src.filename
                            st.rerun()

        c_all, c_manage = st.columns([0.7, 0.3])
        if c_all.button("🚀 Обновить ВСЕ", type="primary", use_container_width=True):
            creds = st.session_state.get("google_creds")
            for src in active_sources_db:
                if src.connector_id == "base": 
                    continue 
                # 🚀 Асинхронный вызов Celery
                task = update_source_task.delay(src.id, creds)
                st.session_state.active_tasks[task.id] = src.filename
            st.rerun()

        if c_manage.button("⚙️", help="Настройки", use_container_width=True): wizard_manage_sources()
        st.divider()

# --- 3. ГРАФИКИ И СВЯЗИ ---
        st.header("📊 Графики")
        if st.button("➕ Новый график", use_container_width=True): wizard_create_chart()

        # Графики, которые РЕАЛЬНО привязаны к этой странице (из БД)
        page_charts = current_page_obj.charts 
        chart_dict = {c.id: c for c in page_charts}
        all_chart_ids = list(chart_dict.keys())
        
        # ХАК ПРОТИВ КЭША STREAMLIT: добавляем длину списка в ключ.
        # Теперь, как только добавится новый график, ключ изменится и подхватит новый default!
        dynamic_key = f"ms_cv_{current_page_obj.id}_{len(all_chart_ids)}"
        
        sel_chart_ids = st.multiselect(
            "Показать на экране:", 
            options=all_chart_ids, 
            default=all_chart_ids, 
            format_func=lambda cid: chart_dict[cid].display_name, 
            label_visibility="collapsed",
            key=dynamic_key
        )

        # Финальный список объектов для рендера
        charts_to_render = [chart_dict[cid] for cid in sel_chart_ids]
        st.divider()
        st.header("📥 Импорт графиков")
        with st.expander("Загрузить (.geb)"):
            if up_geb := st.file_uploader("Загрузить файл", type=["geb", "zip"], label_visibility="collapsed"):
                if st.button("Установить", use_container_width=True):
                    success, msg = BundleManager.import_bundle(up_geb, target_page=current_page_name)
                    if success: st.success("Готово!"); time.sleep(1); st.rerun()
                    else: st.error(msg)

        # 🔗 УПРАВЛЕНИЕ СВЯЗЯМИ (Графики ↔ Данные)
        st.divider()
        st.header("🔗 Связь данных")
        with st.expander("Графики ↔ Данные"):
            if not page_charts: st.caption("Сначала добавьте графики.")
            
            src_dict = {s.id: s for s in active_sources_db} 
            
            for chart in page_charts:
                cur_src_ids = [s.id for s in chart.data_sources]
                
                new_src_ids = st.multiselect(
                    f"Файлы для '{chart.display_name}'", 
                    options=list(src_dict.keys()), 
                    default=cur_src_ids, 
                    format_func=lambda sid: src_dict[sid].filename, 
                    key=f"link_{chart.id}"
                )
                
                if set(new_src_ids) != set(cur_src_ids):
                    chart.data_sources = [src_dict[sid] for sid in new_src_ids]
                    db.commit()
                    st.rerun()
        # --- 3. AI НАСТРОЙКИ ---
        st.divider()
        st.header("🧠 AI Настройки")
        if st.button("⚙️ Управление AI интеграциями", use_container_width=True, key="btn_manage_llm"):
            wizard_manage_llm()
        
        # --- 4. AI ЧАТ ---
        st.divider()
        st.header("💬 AI Чат")
        auto_open = bool(st.session_state.get("gen_prompt"))
        with st.expander("Открыть чат с AI", expanded=auto_open):
            providers = get_providers()
            if providers:
                c_p, c_m = st.columns(2)
                p_names = list(providers.keys())
                sel_prov = c_p.selectbox("Провайдер", p_names, index=p_names.index(st.session_state.get("chat_prov", p_names[0])) if st.session_state.get("chat_prov") in p_names else 0, key="c_prov", label_visibility="collapsed")
                st.session_state.chat_prov = sel_prov
                
                avail_models = providers[sel_prov]["models"]
                sel_model = c_m.selectbox("Модель", avail_models, index=avail_models.index(st.session_state.get("chat_mod", avail_models[0])) if st.session_state.get("chat_mod") in avail_models else 0, key="c_mod", label_visibility="collapsed")
                st.session_state.chat_mod = sel_model

                if "msgs" not in st.session_state: st.session_state.msgs = []
                if st.button("🗑️ Очистить"): st.session_state.msgs = []; st.rerun()
                for m in st.session_state.msgs: st.chat_message(m["role"]).write(m["content"])

                def send_to_llm(p_text):
                    ctx = "\n".join([f"{'User' if m['role']=='user' else 'AI'}: {m['content']}" for m in st.session_state.msgs[-4:]])
                    success, resp = ask_llm(sel_prov, sel_model, "You are a helpful assistant.", f"HISTORY:\n{ctx}\nREQUEST:\n{p_text}")
                    if success: st.session_state.msgs.append({"role": "assistant", "content": resp}); st.rerun()
                    else: st.error(resp)

                if draft := st.session_state.get("gen_prompt"):
                    st.info("✨ Черновик")
                    d_txt = st.text_area("Текст:", value=draft, height=150)
                    c_s, c_c = st.columns([0.4, 0.6])
                    if c_s.button("🚀 Отправить", type="primary", use_container_width=True):
                        del st.session_state.gen_prompt; st.session_state.msgs.append({"role": "user", "content": d_txt}); send_to_llm(d_txt)
                    if c_c.button("❌ Отмена", use_container_width=True): del st.session_state.gen_prompt; st.rerun()

                if p := st.chat_input("Вопрос..."):
                    st.session_state.msgs.append({"role": "user", "content": p}); send_to_llm(p)

    # ==================== MAIN ====================
    st.title(f"📊 {current_page_obj.name}")
    tab_charts, tab_etl = st.tabs(["📈 Просмотр Графиков", "🛠️ Редактор ETL"])

    # --- TAB 1: CHARTS ---
    with tab_charts:
        if not charts_to_render: 
            st.info("Графики скрыты или отсутствуют. Добавьте их в состав дашборда (кнопка ⚙️ слева вверху) и выберите в меню.")
            
        if "chart_backups" not in st.session_state: st.session_state.chart_backups = {}

        # Бежим только по видимым графикам!
        for chart_db in charts_to_render:
            fname = chart_db.technical_name
            fpath = os.path.join(CHARTS_FOLDER, fname)
            
            try: s3_client.download_file("charts", fname, fpath); file_exists = True
            except: st.warning(f"Файл {fname} не найден в S3."); file_exists = False
            
            if not file_exists: continue
            
            st.markdown("---")
            ver_key = f"ver_{chart_db.id}"
            if ver_key not in st.session_state: st.session_state[ver_key] = 0
            ed_key = f"ed_{chart_db.id}_{st.session_state[ver_key]}"
            is_dark = st.session_state.get("wiz_active_dark", True)

            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], fpath)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e: st.error(f"Ошибка модуля {fname}: {e}"); continue

            # Проверяем, не редактируется ли этот график прямо сейчас
            edit_task_desc = f"Редактирование графика '{chart_db.display_name}'|{chart_db.id}"
            is_editing = edit_task_desc in st.session_state.get("active_tasks", {}).values()

            c_title, c_edit, c_ai, c_exp, c_chat, c_del = st.columns([0.60, 0.08, 0.08, 0.08, 0.08, 0.08], vertical_alignment="center")
            
            with c_title: 
                if is_editing:
                    st.subheader(f"📌 {chart_db.display_name} ⏳ (Обновление...)")
                else:
                    st.subheader(f"📌 {chart_db.display_name}")
            
            with c_edit:
                with st.popover("✏️"):
                    if n_title := st.text_input("Имя:", value=chart_db.display_name, key=f"r_{chart_db.id}"):
                        if st.button("OK", key=f"bo_{chart_db.id}"): chart_db.display_name = n_title; db.commit(); st.rerun()
            
            with c_exp:
                with st.popover("📦"):
                    t_html, t_geb = st.tabs(["HTML", "GEB"])
                    with t_html: 
                        html_placeholder = st.empty()
                        html_placeholder.info("Отрисовка...")
                    with t_geb:
                        try:
                            geb_data = BundleManager.export_chart(fname).getvalue()
                            st.download_button("Скачать .geb", data=geb_data, file_name=f"{fname[:-3]}.geb", mime="application/zip", type="primary", key=f"geb_{chart_db.id}", use_container_width=True)
                        except Exception as e: st.error(e)
            with c_chat:
                # Проверяем, не идет ли уже анализ этого графика
                analyze_task_desc = f"Анализ данных '{chart_db.display_name}'|{chart_db.id}"
                is_analyzing = analyze_task_desc in st.session_state.get("active_tasks", {}).values()
                
                if is_analyzing:
                    st.button("⌛", key=f"btn_chat_{chart_db.id}", disabled=True, help="Анализ в процессе...")
                else:
                    if st.button("💬", key=f"btn_chat_{chart_db.id}", help="Получить инсайты от AI"):
                        # Подготовка данных (берем первые 50 строк)
                        data_sample = "Нет данных"
                        if chart_db.data_sources:
                            try:
                                d_path = os.path.join(DATA_FOLDER, chart_db.data_sources[0].filename)
                                df_s = pd.read_csv(d_path, nrows=50) if d_path.endswith('.csv') else pd.read_excel(d_path, nrows=50)
                                data_sample = df_s.to_csv(index=False)
                            except: pass
                        
                        with open(fpath, "r", encoding="utf-8") as f: chart_code = f.read()
                        
                        # Выбираем модель (берем ту же, что в AI чате или дефолтную)
                        prov_list = list(providers.keys())
                        p_name = st.session_state.get("chat_prov", prov_list[0])
                        m_name = st.session_state.get("chat_mod", providers[p_name]["models"][0])

                        from modules.tasks import analyze_chart_task
                        task = analyze_chart_task.delay(
                            chart_id=chart_db.id,
                            code=chart_code,
                            data_sample_str=data_sample,
                            user_id=user_obj.id,
                            sel_prov=p_name,
                            sel_model=m_name
                        )
                        st.session_state.active_tasks[task.id] = analyze_task_desc
                        st.rerun()
                        
            with c_ai:
                with st.popover("✨"):
                    if is_editing:
                        st.status("🤖 ИИ пишет код...", state="running")
                    else:
                        # ОТКАТ (Работает, если есть бэкап в памяти)
                        if fname in st.session_state.chart_backups:
                            if st.button("↩️ Откат", key=f"u_{chart_db.id}", use_container_width=True):
                                with open(fpath, "w", encoding="utf-8") as f: 
                                    f.write(st.session_state.chart_backups[fname])
                                s3_client.put_text("charts", fname, st.session_state.chart_backups[fname])
                                del st.session_state.chart_backups[fname]
                                st.session_state[ver_key] += 1; st.rerun()
                        if not providers: st.error("Нет AI")
                        else:
                            r_p = st.selectbox("AI", list(providers.keys()), key=f"rp_{chart_db.id}", label_visibility="collapsed")
                            r_m = st.selectbox("Mod", providers[r_p]["models"], key=f"rm_{chart_db.id}", label_visibility="collapsed")
                            req = st.text_area("Запрос", key=f"rq_{chart_db.id}")
                            if st.button("🚀 Выполнить", key=f"b_ai_{chart_db.id}", type="primary"):
                                with open(fpath, "r", encoding="utf-8") as f: cur_code = f.read()
                                st.session_state.chart_backups[fname] = cur_code
                                
                                data_ctx = "Нет данных"
                                if chart_db.data_sources:
                                    d_path = os.path.join(DATA_FOLDER, chart_db.data_sources[0].filename)
                                    try:
                                        df_p = pd.read_csv(d_path, nrows=3) if d_path.endswith('.csv') else pd.read_excel(d_path, nrows=3)
                                        data_ctx = "\n".join([f"- {c} ({t})" for c, t in zip(df_p.columns, df_p.dtypes)])
                                    except: pass
                                
                                pmt = f"### ТЕКУЩИЙ КОД:\n```python\n{cur_code}\n```\n\n### ДАННЫЕ:\n{data_ctx}\n\n### ЗАПРОС:\n\"{req}\"\n"
                                sys_msg = "Ты Senior Python Developer. Верни ТОЛЬКО валидный код модуля (def render). В конце верни fig."
                                
                                from modules.tasks import edit_chart_task
                                task = edit_chart_task.delay(
                                    prompt=pmt, 
                                    sys_msg=sys_msg, 
                                    fname=fname, 
                                    sel_prov=r_p, 
                                    sel_model=r_m, 
                                    user_id=user_obj.id
                                )
                                
                                st.session_state.active_tasks[task.id] = edit_task_desc
                                st.rerun()

            with c_del:
                with st.popover("🗑️"):
                    st.write(f"Удалить **{chart_db.display_name}**?")
                    if st.button("🔥 Да", key=f"del_{chart_db.id}", type="primary"):
                        # 1. Удаляем физические файлы
                        if os.path.exists(fpath): os.remove(fpath)
                        try:
                            s3_client.delete_file("charts", fname)
                        except:
                            pass # Если файла там уже нет, игнорируем ошибку

                        # 2. ОТВЯЗЫВАЕМ ГРАФИК ОТ ВСЕХ СТРАНИЦ
                        linked_pages = db.query(Page).filter(Page.charts.contains(chart_db)).all()
                        for p in linked_pages:
                            p.charts.remove(chart_db)
                        
                        # 3. ОТВЯЗЫВАЕМ ОТ ВСЕХ ИСТОЧНИКОВ ДАННЫХ
                        chart_db.data_sources = []
                        
                        # 4. Теперь безопасно удаляем сам график
                        db.delete(chart_db)
                        db.commit()
                        st.rerun()

            # Редактор кода
            try:
                with open(fpath, "r", encoding="utf-8") as f: code_c = f.read()
                with st.expander(f"Код: {chart_db.display_name}"):
                    res = code_editor(code_c, lang="python", height=[8, 15], key=ed_key, buttons=[{"name": "Save", "feather": "Save", "hasText": True, "commands": ["submit"]}])
                    if res['type'] == "submit" and res['text'] != code_c:
                        with open(fpath, "w", encoding="utf-8") as f: f.write(res['text'])
                        s3_client.put_text("charts", fname, res['text'])
                        st.session_state[ver_key] += 1; st.rerun()
            except Exception as e: st.warning(f"Ошибка редактора: {e}")

            # Рендер
            if hasattr(mod, "render"):
                # ✅ БЕРЕМ ФАЙЛЫ ДЛЯ ГРАФИКА НАПРЯМУЮ ИЗ БАЗЫ!
                source_paths = [os.path.join(DATA_FOLDER, ds.filename) for ds in chart_db.data_sources]
                
                # Sandboxing...
                WIDGETS = ["button", "checkbox", "radio", "selectbox", "multiselect", "slider", "select_slider", "text_input", "number_input", "text_area", "date_input", "time_input", "file_uploader", "color_picker", "toggle", "plotly_chart", "data_editor"]
                orig_funcs = {name: getattr(st, name) for name in WIDGETS if hasattr(st, name)}
                u_suffix = f"chart_inst_{chart_db.id}"
                
                def create_patch(func, sfx):
                    def patched(*args, **kwargs):
                        # Если в коде графика уже прописан key, добавляем к нему суффикс
                        if "key" in kwargs and kwargs["key"] is not None:
                            kwargs["key"] = f"{kwargs['key']}_{sfx}"
                        else:
                            # Если ключа нет, создаем его на основе метки (label)
                            label_part = str(kwargs.get('label', 'w'))[:10]
                            kwargs["key"] = f"auto_{label_part}_{sfx}"
                        return func(*args, **kwargs)
                    return patched
                
                for n, f in orig_funcs.items(): setattr(st, n, create_patch(f, u_suffix))
                
                try:
                    import inspect
                    sig = inspect.signature(mod.render)
                    c_args = {"files": source_paths}
                    if "chart_key" in sig.parameters: c_args["chart_key"] = fname
                    if "theme" in sig.parameters: c_args["theme"] = "plotly_dark" if is_dark else "plotly_white"
                    if "return_fig" in sig.parameters: c_args["return_fig"] = False
                    
                    # 1. Отрисовываем график
                    fig = mod.render(**c_args)
                    
                    # 2. Если график успешно вернул объект (fig), отдаем его в кнопку HTML!
                    if fig:
                        from modules.utils import ChartExporter
                        html_data = ChartExporter.export_to_html(fig, app_theme_is_dark=is_dark)
                        # Заменяем текст "Отрисовка..." на реальную кнопку скачивания
                        html_placeholder.download_button(
                            label="⬇️ Скачать HTML", 
                            data=html_data, 
                            file_name=f"{fname[:-3]}.html", 
                            mime="text/html", 
                            key=f"dl_html_{chart_db.id}", 
                            use_container_width=True
                        )
                    # --- БЛОК ИНСАЙТОВ ---
                    insight_key = f"insight_{chart_db.id}"
                    if insight_key in st.session_state:
                        st.write("") # Небольшой отступ
                        with st.chat_message("assistant", avatar="🤖"):
                            st.markdown(f"**Аналитический разбор:**\n\n{st.session_state[insight_key]}")
                            if st.button("Закрыть анализ", key=f"close_ins_{chart_db.id}", type="secondary"):
                                del st.session_state[insight_key]
                                st.rerun()

                except Exception as e: st.error(f"Ошибка рендера: {e}")
                finally:
                    for n, f in orig_funcs.items(): setattr(st, n, f)

        # --- НЕВИДИМЫЙ ТРЕКЕР ФОНОВЫХ ЗАДАЧ (ДЛЯ ДАННЫХ И РЕДАКТИРОВАНИЯ) ---
        # --- НЕВИДИМЫЙ ТРЕКЕР ФОНОВЫХ ЗАДАЧ (ДАННЫЕ, РЕДАКТИРОВАНИЕ, АНАЛИЗ) ---
        @st.fragment(run_every=2)
        def invisible_task_tracker():
            if not st.session_state.get("active_tasks"):
                return

            completed_tasks = []
            for task_id, task_desc in list(st.session_state.active_tasks.items()):
                # 1. Игнорируем ТОЛЬКО создание новых графиков (их ловит визуальный трекер внизу)
                if str(task_desc).startswith("Создание графика"):
                    continue

                res = AsyncResult(task_id, app=celery_app)
                
                if res.ready(): 
                    result_data = res.result
                    
                    # Разбираем техническую строку (имя|ID)
                    desc_parts = str(task_desc).split("|")
                    clean_desc = desc_parts[0]
                    chart_id = desc_parts[1] if len(desc_parts) > 1 else None
                    
                    if result_data and isinstance(result_data, dict) and result_data.get("status"):
                        # СПЕЦИФИКА: Если это был анализ графика — сохраняем текст инсайта в сессию
                        if "Анализ данных" in clean_desc:
                            # Мы используем ID из данных задачи, если в результате его нет
                            cid = result_data.get("chart_id") or chart_id
                            st.session_state[f"insight_{cid}"] = result_data.get("msg")
                        
                        # СПЕЦИФИКА: Если редактирование — сбрасываем кэш редактора
                        if "Редактирование" in clean_desc and chart_id:
                            v_key = f"ver_{chart_id}"
                            st.session_state[v_key] = st.session_state.get(v_key, 0) + 1

                        st.toast(f"✅ {clean_desc} выполнено!")
                    else:
                        err_msg = result_data.get('msg') if isinstance(result_data, dict) else 'Неизвестная ошибка'
                        st.error(f"❌ Ошибка ({clean_desc}): {err_msg}")
                    
                    completed_tasks.append(task_id)

            # Чистим список активных задач
            for t in completed_tasks:
                del st.session_state.active_tasks[t]
            
            # Если что-то завершилось — обновляем страницу
            if completed_tasks:
                time.sleep(1)
                st.rerun()

        invisible_task_tracker()

        # --- ВИЗУАЛЬНЫЙ ТРЕКЕР ГЕНЕРАЦИИ ГРАФИКОВ (Для новых) ---
        @st.fragment(run_every=2)
        def visual_chart_tracker():
            if not st.session_state.get("active_tasks"):
                return
            
            completed_charts = []
            for task_id, task_desc in list(st.session_state.active_tasks.items()):
                # 1. Отсекаем задачи, которые НЕ относятся к графикам
                if "графика" not in str(task_desc).lower() and "ai код" not in str(task_desc).lower():
                    continue
                
                # 2. Отсекаем задачи РЕДАКТИРОВАНИЯ (у них есть символ |)
                # Их мы не рисуем внизу, так как они отображаются поверх существующих графиков
                if "|" in str(task_desc):
                    continue
                    
                res = AsyncResult(task_id, app=celery_app)
                
                # Чистим имя для отображения
                display_name = str(task_desc).replace("Создание графика ", "").replace("AI код для ", "").strip("'")
                
                # РИСУЕМ СКЕЛЕТ (Placeholder)
                st.markdown("---")
                col1, col2 = st.columns([0.7, 0.3], vertical_alignment="center")
                col1.subheader(f"📌 {display_name}")
                
                with col2:
                    if not res.ready():
                        st.status("🤖 Генерируем новый график...", state="running", expanded=False)
                    else:
                        result_data = res.result
                        if result_data and isinstance(result_data, dict) and result_data.get("status"):
                            st.status("✅ Готово! Отрисовываю...", state="complete", expanded=False)
                        else:
                            err_msg = result_data.get('msg') if isinstance(result_data, dict) else 'Ошибка API'
                            st.status(f"❌ Ошибка: {err_msg}", state="error", expanded=False)
                        
                        completed_charts.append(task_id)
            
            # Чистим завершенные задачи
            for t in completed_charts:
                del st.session_state.active_tasks[t]
            
            # Если что-то завершилось — делаем общий реран, чтобы график появился в основном списке
            if completed_charts:
                time.sleep(1.5)
                st.rerun()

        visual_chart_tracker()
    
    # --- TAB 2: ETL ---
    with tab_etl:
        st.write("🛠️ **Редактор ETL**")
        db_etl = SessionLocal()
        
        try:
            # Берем скрипты ТОЛЬКО текущего пространства!
            user_handlers = db_etl.query(ETLHandler).filter(ETLHandler.workspace_id == st.session_state.active_ws_id).all()
            
            handlers_dict = {h.name: h for h in user_handlers}
            handler_names = list(handlers_dict.keys())
            
            c_sel, c_new, c_del = st.columns([0.74, 0.13, 0.13], vertical_alignment="bottom")
            s_h_name = c_sel.selectbox("Скрипт:", handler_names, label_visibility="collapsed")
            
            with c_new:
                with st.popover("➕ Создать"):
                    nh = st.text_input("Название (напр. 'Очистка'):", key="new_etl_name")
                    if st.button("💾 Сохранить", type="primary", use_container_width=True):
                        if nh and nh not in handlers_dict:
                            # Уникальное имя файла под капотом
                            tech_name = f"ws_{st.session_state.active_ws_id}_{sanitize_filename(nh)}.py"
                            
                            new_h = ETLHandler(workspace_id=st.session_state.active_ws_id, name=nh, technical_name=tech_name)
                            db_etl.add(new_h)
                            db_etl.commit()
                            
                            default_code = "import pandas as pd\n\ndef handle(df):\n    # Ваш код очистки здесь\n    return df\n"
                            p = os.path.join(HANDLERS_FOLDER, tech_name)
                            with open(p, "w", encoding="utf-8") as f: f.write(default_code)
                            s3_client.put_text("handlers", tech_name, default_code)
                            st.rerun()

            with c_del:
                if s_h_name:
                    with st.popover("🗑️ Удалить"):
                        st.write(f"Удалить `{s_h_name}`?")
                        if st.button("Да, удалить", type="primary", use_container_width=True):
                            h_obj = handlers_dict[s_h_name]
                            tech_name = h_obj.technical_name
                            
                            # Отвязываем от всех источников данных
                            linked_sources = db_etl.query(DataSource).filter(DataSource.handler_id == h_obj.id).all()
                            for s in linked_sources: s.handler_id = None
                            
                            db_etl.delete(h_obj)
                            db_etl.commit()
                            
                            try: os.remove(os.path.join(HANDLERS_FOLDER, tech_name)) 
                            except: pass
                            s3_client.delete_file("handlers", tech_name)
                            st.rerun()

            # --- Редактор кода ---
            if s_h_name:
                h_obj = handlers_dict[s_h_name]
                tech_name = h_obj.technical_name
                h_path = os.path.join(HANDLERS_FOLDER, tech_name)
                
                if "etl_lf" not in st.session_state or st.session_state.etl_lf != tech_name:
                    try:
                        s3_client.download_file("handlers", tech_name, h_path)
                        with open(h_path, "r", encoding="utf-8") as f: st.session_state.etl_h = f.read()
                    except Exception:
                        st.session_state.etl_h = "import pandas as pd\n\ndef handle(df):\n    return df\n"
                    st.session_state.etl_lf = tech_name
                
                res_h = code_editor(st.session_state.etl_h, lang="python", height=[20, 30], key=f"ed_{tech_name}", buttons=[{"name": "Save", "feather": "Save", "hasText": True, "alwaysOn": True, "commands": ["submit"]}])
                
                if res_h['type'] == "submit" and res_h['text'] != st.session_state.etl_h:
                    st.session_state.etl_h = res_h['text']
                    with open(h_path, "w", encoding="utf-8") as f: f.write(res_h['text'])
                    s3_client.put_text("handlers", tech_name, res_h['text'])
                    st.toast(f"✅ Скрипт {s_h_name} сохранен!")
        finally:
            db_etl.close()
    db.close()
    
elif st.session_state["authentication_status"] is False:
    st.error('❌ Неверный логин или пароль')
elif st.session_state["authentication_status"] is None:
    st.warning('🔒 Введите логин и пароль')