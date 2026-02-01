import streamlit as st
import os
import glob
import importlib.util
import datetime
import time
import concurrent.futures
from code_editor import code_editor
import shutil
import pandas as pd

# --- ИМПОРТЫ ---
from modules.settings import *
from modules.utils import load_json, save_json
from modules.data_loader import sync_single_source
from modules.wizards import wizard_create_chart, wizard_manage_sources, wizard_manage_pages, wizard_manage_llm

# !!! НОВЫЕ ИМПОРТЫ ДЛЯ ИНТЕГРАЦИЙ !!!
from modules.llm_manager import get_providers, ask_llm
from modules.auth import is_authenticated, logout_user, login_redirect, check_auth_code

# --- INIT ---
titles_conf_init = load_json(TITLES_CONFIG_FILE, {})
# Ищем ключ "app_title", если нет — берем дефолт
APP_TITLE = titles_conf_init.get("app_title", "B2B Отчетность")

# --- 2. INIT ---
st.set_page_config(page_title=APP_TITLE, layout="wide")
init_project_structure()

# ... (Проверка Auth и Helper functions остаются без изменений) ...

# ==================== SIDEBAR ====================
with st.sidebar:
    # --- ИСПОЛЬЗУЕМ ДИНАМИЧЕСКОЕ НАЗВАНИЕ ---
    st.title(f"📊 {APP_TITLE}")

# !!! ВАЖНО: ПРОВЕРКА КОДА ОТ GOOGLE !!!
check_auth_code()
# -------------------------------------

# --- HELPER: PARALLEL UPDATE ---

def run_updates_in_parallel(sources_to_update, ui_placeholders):
    results_log = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_source = {
            executor.submit(sync_single_source, src): (i, src) 
            for i, src in sources_to_update.items()
        }
        for future in concurrent.futures.as_completed(future_to_source):
            idx, src = future_to_source[future]
            fname = src.get('filename')
            container = ui_placeholders[idx]
            try:
                ok, msg, _ = future.result()
                if ok:
                    container.success(f"✅ {fname}")
                    results_log.append(f"✅ {fname}: OK")
                else:
                    # --- ИСПРАВЛЕНИЕ: Выводим текст ошибки (msg) ---
                    container.error(f"❌ {fname}\n\n**Ошибка:** `{msg}`")
                    results_log.append(f"❌ {fname}: {msg}")
            except Exception as e:
                container.error(f"❌ {fname}: {e}")
                results_log.append(f"❌ {fname}: {e}")
    return results_log

# --- LOAD CONFIGS ---
s_conf = load_json(SOURCES_CONFIG_FILE, {})
pages_conf = load_json(PAGES_CONFIG_FILE, {})
titles_conf = load_json(TITLES_CONFIG_FILE, {}) 

if "General" in pages_conf:
    pages_conf["B2B Дашборд"] = pages_conf.pop("General")
    save_json(PAGES_CONFIG_FILE, pages_conf)

if not pages_conf:
    all_charts = sorted([f for f in os.listdir(CHARTS_FOLDER) if f.endswith(".py")])
    pages_conf = {"B2B Дашборд": all_charts}
    save_json(PAGES_CONFIG_FILE, pages_conf)

# --- HELPER: FORMAT TITLE ---
def get_chart_display_name(filename):
    return titles_conf.get(filename, filename)

# ==================== SIDEBAR ====================
with st.sidebar:
    # --- 1. ВЫБОР ДАШБОРДА ---
    st.header("📑 Дашборды")
    
    page_names = list(pages_conf.keys())
    if "B2B Дашборд" in page_names:
        page_names.remove("B2B Дашборд")
        page_names.insert(0, "B2B Дашборд")
    
    query_params = st.query_params
    default_index = 0
    
    if "page" in query_params:
        url_page = query_params["page"]
        if url_page in page_names:
            default_index = page_names.index(url_page)

    current_page = st.selectbox(
        "Выберите страницу:", 
        page_names, 
        index=default_index, 
        label_visibility="collapsed"
    )
    
    st.query_params["page"] = current_page
    
    c_p1, c_p2 = st.columns([0.85, 0.15], vertical_alignment="bottom")
    c_p1.caption(f"Графиков: {len(pages_conf.get(current_page, []))}")
    if c_p2.button("⚙️", help="Настроить страницы"):
        wizard_manage_pages()

    st.divider()

    # --- 2. ДАННЫЕ (NEW DESIGN: CONTROL CENTER) ---
    # --- 2. ДАННЫЕ (SCROLLABLE LIST) ---
    if GUIDE_URL: st.link_button("📘 Инструкция", GUIDE_URL, use_container_width=True)
    
    c_h1, c_h2 = st.columns([0.7, 0.3], vertical_alignment="center")
    c_h1.header("☁️ Данные")
    
# 1. AUTH POPOVER
    with st.popover("🔐 Настройка доступа (Google)", use_container_width=True):
        st.write("**Статус подключений**")
        
        if is_authenticated():
            st.success("Google: ✅ OK")
            
            # Проверка: если токен лежит на диске - пугаем пользователя
            if os.path.exists("user_token.json"):
                st.warning("Ваш личный токен сохранен в файле `user_token.json`.", icon="⚠️")
                st.caption("🔴 **НИКОГДА НЕ ПЕРЕДАВАЙТЕ ЭТОТ ФАЙЛ НИКОМУ!** Он дает полный доступ к вашим таблицам.")
            
            if st.button("Выйти (и удалить токен)", use_container_width=True):
                logout_user() # Это теперь удаляет и файл
        else:
            st.error("Google: ❌ Off")
            login_redirect() # Рисует кнопку входа
            
        st.divider()
        st.caption("Настройки в меню ⚙️")

    # 2. СПИСОК ИСТОЧНИКОВ (Scrollable)
    def get_conn_icon(c_id):
        icons = {"google_sheets": "📄", "ytsaurus": "🦖", "superset": "📊", "base": "📁"}
        return icons.get(c_id, "❓")

    active_sources = [s for s in s_conf.get("sources", []) if s.get("active", True)]
    status_placeholders = {}

    search_q = st.text_input("Поиск источника", placeholder="🔍 Найти файл...", label_visibility="collapsed")

    with st.container(height=200, border=True):
        if not active_sources:
            st.caption("Нет источников.")
        else:
            c_n, c_act = st.columns([0.75, 0.25])
            c_n.caption("**Источник**")
            c_act.caption("**Обн.**")
            
            for i, src in enumerate(active_sources):
                fname = src.get('filename', 'no_name')
                if search_q and (search_q.lower() not in fname.lower()): continue

                c_id = src.get("connector_id", "base")
                icon = get_conn_icon(c_id)
                
                r_c1, r_c2 = st.columns([0.75, 0.25], vertical_alignment="center")
                display_name = (fname[:16] + '..') if len(fname) > 18 else fname
                r_c1.markdown(f"{icon} `{display_name}`", help=f"{c_id}: {fname}")
                
                # КНОПКА ОБНОВЛЕНИЯ ОДНОГО ФАЙЛА
                if r_c2.button("↻", key=f"upd_s_{i}"):
                    status_placeholders[i] = st.empty()
                    status_placeholders[i].info("⏳")
                    
                    # --- FIX: Подготовка задачи с кредами ---
                    task_src = src.copy()
                    task_src["config"] = src.get("config", {}).copy()
                    if "google_creds" in st.session_state:
                        task_src["config"]["_injected_creds"] = st.session_state.google_creds
                    # ----------------------------------------

                    logs = run_updates_in_parallel({i: task_src}, status_placeholders)
                    
                    if not any("❌" in log for log in logs):
                        time.sleep(0.5); st.rerun()
                    else:
                        st.toast(f"Ошибка: {fname}", icon="❌")

                if i not in status_placeholders:
                    status_placeholders[i] = st.empty()

    # 3. КНОПКИ ДЕЙСТВИЙ
    c_all, c_set = st.columns([0.7, 0.3])
    
    if c_all.button("🚀 Обновить ВСЕ", type="primary", use_container_width=True):
        for i in range(len(active_sources)): status_placeholders[i].info("⏳")
        
        # --- FIX: Подготовка ВСЕХ задач с кредами ---
        tasks = {}
        creds = st.session_state.get("google_creds")
        
        for i, src in enumerate(active_sources):
            s_copy = src.copy()
            s_copy["config"] = src.get("config", {}).copy()
            if creds:
                s_copy["config"]["_injected_creds"] = creds
            tasks[i] = s_copy
        # --------------------------------------------
        
        logs = run_updates_in_parallel(tasks, status_placeholders)
        
        s_conf["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_json(SOURCES_CONFIG_FILE, s_conf)
        
        if not any("❌" in log for log in logs):
            st.toast("✅ Готово!"); time.sleep(1); st.rerun()
        else: st.warning("Ошибки в логе.")

    if c_set.button("⚙️", help="Настройки", use_container_width=True): 
        wizard_manage_sources()
        
    if "last_updated" in s_conf:
        st.caption(f"Last update: {s_conf['last_updated']}")

    st.divider()
    
    # --- 3. AI НАСТРОЙКИ ---
    st.header("🧠 AI Настройки")
    if st.button("⚙️ Управление моделями", use_container_width=True):
        wizard_manage_llm()
    st.divider()

    # --- 4. ГРАФИКИ ---
    st.header("📊 Графики")
    if st.button("➕ Новый график", use_container_width=True): wizard_create_chart()

    page_charts = pages_conf.get(current_page, [])
    existing_charts = [f for f in page_charts if os.path.exists(os.path.join(CHARTS_FOLDER, f))]
    
    sel_charts = st.multiselect(
        "Показать на экране:", 
        existing_charts, 
        default=existing_charts, 
        label_visibility="collapsed",
        format_func=get_chart_display_name 
    )

    with st.expander("📂 Файлы и Связи"):
        st.write("**Файлы данных:**")
        up = st.file_uploader("Upload", type=["csv", "xlsx"], label_visibility="collapsed")
        if up:
            with open(os.path.join(DATA_FOLDER, up.name), "wb") as f: f.write(up.getbuffer())
            st.rerun()
        
        # --- БЭКАПЫ И ИНСТРУМЕНТЫ ---
        BACKUP_FOLDER = os.path.join(DATA_FOLDER, "backups")
        if not os.path.exists(BACKUP_FOLDER): os.makedirs(BACKUP_FOLDER)

        for f in glob.glob(os.path.join(DATA_FOLDER, "*")):
            if os.path.isdir(f): continue
            f_name = os.path.basename(f)
            backup_path = os.path.join(BACKUP_FOLDER, f_name)
            has_backup = os.path.exists(backup_path)
            
            fc1, fc_info, fc2, fc3 = st.columns([0.45, 0.22, 0.18, 0.15], vertical_alignment="center")
            fc1.caption(f_name)
            with fc_info:
                if has_backup: st.markdown(":orange[**Mod**]", help="Есть оригинал")
            
            with fc2:
                icon = "🛠️" if not has_backup else "♻️"
                with st.popover(icon, help="Обработка"):
                    st.markdown(f"**Файл:** `{f_name}`")
                    if has_backup:
                        st.info("Есть оригинал.")
                        if st.button("⏪ Вернуть", key=f"rest_{f_name}", use_container_width=True):
                            try:
                                shutil.copy2(backup_path, f)
                                os.remove(backup_path)
                                st.toast("✅ Восстановлено!")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e: st.error(f"Err: {e}")
                        st.divider()

                    handlers_list = [h for h in os.listdir(HANDLERS_FOLDER) if h.endswith(".py") and h != "__init__.py"]
                    if not handlers_list: st.warning("Нет скриптов")
                    else:
                        sel_script = st.selectbox("Скрипт:", handlers_list, key=f"h_sel_{f_name}")
                        if st.button("🚀 Запуск", key=f"run_{f_name}_{sel_script}", type="primary", use_container_width=True):
                            try:
                                if not has_backup: shutil.copy2(f, backup_path)
                                if f.endswith('.csv'): df_source = pd.read_csv(f)
                                else: df_source = pd.read_excel(f)
                                
                                import time
                                script_path = os.path.join(HANDLERS_FOLDER, sel_script)
                                unique_name = f"handler_{int(time.time())}_{f_name}"
                                spec = importlib.util.spec_from_file_location(unique_name, script_path)
                                mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(mod)
                                
                                if hasattr(mod, "handle"):
                                    df_result = mod.handle(df_source)
                                    if df_result is not None and not df_result.empty:
                                        if f.endswith('.csv'): df_result.to_csv(f, index=False)
                                        else: df_result.to_excel(f, index=False)
                                        st.toast(f"✅ Готово!")
                                        time.sleep(1)
                                        st.rerun()
                                    else: st.error("Пустой результат")
                                else: st.error("Нет функции handle()")
                            except Exception as e: st.error(f"Err: {e}")

            with fc3:
                with st.popover("✕", help="Удалить"):
                    st.write(f"Удалить **{f_name}**?")
                    if st.button("🔥 Да", key=f"conf_del_{f}", type="primary", use_container_width=True):
                        os.remove(f)
                        if os.path.exists(backup_path): os.remove(backup_path)
                        st.rerun()
        
        st.divider()
        st.write("**Связи:**")
        conf = load_json(CONFIG_FILE, {})
        data_files = [os.path.basename(f) for f in glob.glob(os.path.join(DATA_FOLDER, "*"))]
        changed = False
        for ch in sel_charts:
            cur = [f for f in conf.get(ch, []) if f in data_files]
            readable_name = get_chart_display_name(ch)
            sel = st.multiselect(f"Для '{readable_name}'", data_files, default=cur, key=f"s_{ch}")
            if sel != conf.get(ch, []):
                conf[ch] = sel
                changed = True
        if changed: save_json(CONFIG_FILE, conf)

    # --- 5. УНИВЕРСАЛЬНЫЙ AI ЧАТ (Вместо Legacy Gemini) ---
    auto_open = True if ("gen_prompt" in st.session_state and st.session_state.gen_prompt) else False
    
    with st.expander("💬 AI Чат (Все модели)", expanded=auto_open):
        providers = get_providers()
        
        if not providers:
            st.warning("⚠️ Сначала добавьте интеграцию в настройках!")
        else:
            # Селекторы модели (сохраняем выбор в сессии)
            c_p, c_m = st.columns(2)
            p_names = list(providers.keys())
            
            # Выбор провайдера
            idx_p = 0
            if "chat_prov" in st.session_state and st.session_state.chat_prov in p_names:
                idx_p = p_names.index(st.session_state.chat_prov)
            sel_prov = c_p.selectbox("Провайдер", p_names, index=idx_p, key="chat_prov_sel", label_visibility="collapsed")
            st.session_state.chat_prov = sel_prov
            
            # Выбор модели
            avail_models = providers[sel_prov]["models"]
            idx_m = 0
            if "chat_mod" in st.session_state and st.session_state.chat_mod in avail_models:
                idx_m = avail_models.index(st.session_state.chat_mod)
            sel_model = c_m.selectbox("Модель", avail_models, index=idx_m, key="chat_mod_sel", label_visibility="collapsed")
            st.session_state.chat_mod = sel_model

            st.divider()

            if "msgs" not in st.session_state: st.session_state.msgs = []
            if st.button("🗑️ Очистить"): 
                st.session_state.msgs = []
                st.rerun()
            
            # Отображение истории
            for m in st.session_state.msgs: 
                st.chat_message(m["role"]).write(m["content"])
            
            # --- ФУНКЦИЯ ОТПРАВКИ ---
            def send_to_llm(prompt_text):
                # Формируем историю для контекста (так как ask_llm stateless)
                # Берем последние 4 сообщения
                context_str = ""
                for m in st.session_state.msgs[-4:]:
                    role = "User" if m["role"] == "user" else "Assistant"
                    context_str += f"{role}: {m['content']}\n"
                
                final_user_prompt = f"HISTORY:\n{context_str}\nCURRENT REQUEST:\n{prompt_text}"
                
                with st.spinner(f"🤖 {sel_prov} думает..."):
                    success, resp = ask_llm(sel_prov, sel_model, "You are a helpful assistant.", final_user_prompt)
                    
                    if success:
                        st.session_state.msgs.append({"role": "assistant", "content": resp})
                        st.rerun()
                    else:
                        st.error(f"Ошибка: {resp}")

            # 1. ОБРАБОТКА ЧЕРНОВИКА (из Визарда)
            if "gen_prompt" in st.session_state and st.session_state.gen_prompt:
                st.markdown("---")
                st.info("✨ **Черновик запроса**")
                draft_prompt = st.text_area("Текст:", value=st.session_state.gen_prompt, height=200, key="draft_prompt_area")
                
                c_send, c_close = st.columns([0.4, 0.6])
                if c_send.button("🚀 Отправить", type="primary", use_container_width=True):
                    del st.session_state.gen_prompt
                    st.session_state.msgs.append({"role": "user", "content": draft_prompt})
                    send_to_llm(draft_prompt)

                if c_close.button("❌ Сбросить", use_container_width=True):
                    del st.session_state.gen_prompt
                    st.rerun()

            # 2. ОБЫЧНЫЙ ЧАТ
            if p := st.chat_input("Вопрос..."):
                st.session_state.msgs.append({"role": "user", "content": p})
                send_to_llm(p)

# ==================== MAIN ====================
st.title(f"📊 {current_page}")

tab_charts, tab_etl = st.tabs(["📈 Просмотр Графиков", "🛠️ Редактор ETL (Обработчики)"])

# --- TAB 1: CHARTS ---
with tab_charts:
    if not sel_charts: 
        st.info("На этой странице нет графиков или они скрыты. Добавьте их через настройки ⚙️ или создайте новый.")
    
    chart_config = load_json(CONFIG_FILE, {})
    if "chart_backups" not in st.session_state: st.session_state.chart_backups = {}

    for fname in sel_charts:
        fpath = os.path.join(CHARTS_FOLDER, fname)
        st.markdown("---")
        display_name = get_chart_display_name(fname)
        
        c_title, c_edit, c_ai, c_del = st.columns([0.76, 0.08, 0.08, 0.08], vertical_alignment="center")
        
        with c_title: st.subheader(f"📌 {display_name}")
            
        with c_edit:
            with st.popover("✏️", help="Переименовать", use_container_width=True):
                new_title_input = st.text_input("Новое имя:", value=display_name, key=f"ren_input_{fname}")
                if st.button("Сохранить", key=f"save_ren_{fname}", type="primary"):
                    titles_conf[fname] = new_title_input
                    save_json(TITLES_CONFIG_FILE, titles_conf)
                    st.rerun()

        # --- AI REFACTORING (УНИВЕРСАЛЬНЫЙ) ---
        with c_ai:
            has_backup = fname in st.session_state.chart_backups
            ai_icon = "✨"
            with st.popover(ai_icon, help="AI Редактор (+Откат)", use_container_width=True):
                if has_backup:
                    st.warning("Доступна предыдущая версия кода")
                    if st.button("↩️ Вернуть как было", key=f"undo_{fname}", use_container_width=True):
                        old_code = st.session_state.chart_backups[fname]
                        with open(fpath, "w", encoding="utf-8") as f: f.write(old_code)
                        del st.session_state.chart_backups[fname]
                        st.toast("✅ Изменения отменены!")
                        time.sleep(0.5)
                        st.rerun()
                    st.divider()

                st.write(f"**AI Рефакторинг: {display_name}**")
                
                # ВЫБОР МОДЕЛИ ДЛЯ РЕФАКТОРИНГА
                providers = get_providers()
                if not providers:
                    st.error("Нет AI интеграций!")
                    llm_ok = False
                else:
                    llm_ok = True
                    # Берем первую попавшуюся или последнюю выбранную (упростим до первой попавшейся для компактности)
                    # Или дадим выбор
                    rp_names = list(providers.keys())
                    r_prov = st.selectbox("Провайдер", rp_names, key=f"r_prov_{fname}", label_visibility="collapsed")
                    r_models = providers[r_prov]["models"]
                    r_mod = st.selectbox("Модель", r_models, key=f"r_mod_{fname}", label_visibility="collapsed")

                ai_request = st.text_area("Запрос к AI", placeholder="Сделай красным...", key=f"aireq_{fname}", height=100)
                
                if st.button("🚀 Выполнить", key=f"do_ai_{fname}", type="primary", use_container_width=True, disabled=not llm_ok):
                    if not ai_request:
                        st.warning("Напишите запрос.")
                    else:
                        try:
                            with open(fpath, "r", encoding="utf-8") as f: current_code = f.read()
                            st.session_state.chart_backups[fname] = current_code
                        except: current_code = ""

                        data_context = "Нет данных"
                        try:
                            linked_files = chart_config.get(fname, [])
                            if linked_files:
                                d_path = os.path.join(DATA_FOLDER, linked_files[0])
                                if d_path.endswith('.csv'): df_p = pd.read_csv(d_path, nrows=3)
                                else: df_p = pd.read_excel(d_path, nrows=3)
                                data_context = "\n".join([f"- {c} ({t})" for c, t in zip(df_p.columns, df_p.dtypes)])
                        except: pass

                        refactor_prompt = (
                            f"### ТЕКУЩИЙ КОД:\n```python\n{current_code}\n```\n\n"
                            f"### ДАННЫЕ:\n{data_context}\n\n"
                            f"### ЗАПРОС ПОЛЬЗОВАТЕЛЯ:\n\"{ai_request}\"\n"
                        )
                        system_msg = "Ты Senior Python Developer. Ты меняешь код Streamlit/Plotly по запросу. Верни ТОЛЬКО валидный Python код всего модуля. Без маркдауна."

                        with st.spinner(f"🤖 {r_prov} переписывает код..."):
                            success, result_text = ask_llm(r_prov, r_mod, system_msg, refactor_prompt)
                            
                            if success:
                                new_code = result_text
                                if "```python" in new_code: new_code = new_code.split("```python")[1].split("```")[0]
                                elif "```" in new_code: new_code = new_code.split("```")[1]
                                new_code = new_code.strip()
                                
                                with open(fpath, "w", encoding="utf-8") as f: f.write(new_code)
                                st.toast("✨ Готово!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"Ошибка AI: {result_text}")

        with c_del:
            with st.popover("🗑️", help="Удалить график", use_container_width=True):
                st.write(f"Удалить **{display_name}**?")
                if st.button("🔥 Да", key=f"del_chart_btn_{fname}", type="primary"):
                    if os.path.exists(fpath): os.remove(fpath)
                    if fname in titles_conf: del titles_conf[fname]; save_json(TITLES_CONFIG_FILE, titles_conf)
                    if fname in chart_config: del chart_config[fname]; save_json(CONFIG_FILE, chart_config)
                    p_conf = load_json(PAGES_CONFIG_FILE, {})
                    for p_nm, ch_list in p_conf.items():
                        if fname in ch_list: ch_list.remove(fname)
                    save_json(PAGES_CONFIG_FILE, p_conf)
                    st.rerun()

        code_content = ""
        file_read_error = False
        
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f: code_content = f.read()
            except Exception as e: st.error(f"Ошибка чтения: {e}"); file_read_error = True
        else: st.error(f"Файл не найден: {fname}"); file_read_error = True

        if file_read_error: continue 

        with st.expander(f"Редактировать код: {display_name}"):
            try:
                res = code_editor(code_content, lang="python", height=[8, 15], key=f"ed_{fname}", buttons=[{"name": "Save", "feather": "Save", "hasText": True, "commands": ["submit"]}])
                if res['type'] == "submit" and res['text'] != code_content:
                    with open(fpath, "w", encoding="utf-8") as f: f.write(res['text'])
                    st.rerun()
            except Exception as e: st.warning(f"Ошибка редактора: {e}")

        if "st.set_page_config" in code_content:
            st.error("Это не модуль, а приложение! Убери `st.set_page_config`.")
        else:
            try:
                spec = importlib.util.spec_from_file_location(fname[:-3], fpath)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "render"):
                    source_files_paths = [os.path.join(DATA_FOLDER, f) for f in chart_config.get(fname, [])]
                    mod.render(source_files_paths)
                else: st.warning("Нет функции `render(files)`.")
            except Exception as e: st.error(f"Ошибка выполнения: {e}")
            
# --- TAB 2: ETL EDITOR ---
with tab_etl:
    st.write("🛠️ **Редактор скриптов обработки (ETL)**")
    
    if not os.path.exists(HANDLERS_FOLDER): os.makedirs(HANDLERS_FOLDER)
    handlers = sorted([f for f in os.listdir(HANDLERS_FOLDER) if f.endswith(".py") and f != "__init__.py"])

    c_sel, c_new, c_ren, c_del = st.columns([0.6, 0.13, 0.13, 0.13], vertical_alignment="bottom")
    sel_handler = c_sel.selectbox("Выберите скрипт:", handlers, label_visibility="collapsed", key="etl_selector")

    with c_new:
        with st.popover("➕", use_container_width=True, help="Создать новый"):
            st.write("**Новый скрипт**")
            new_h_name = st.text_input("Имя файла (лат):", placeholder="clean_sales", key="new_h_input")
            if st.button("Создать", type="primary", key="create_h_btn"):
                if new_h_name:
                    if not new_h_name.endswith(".py"): new_h_name += ".py"
                    new_path = os.path.join(HANDLERS_FOLDER, new_h_name)
                    if os.path.exists(new_path): st.error("Файл существует!")
                    else:
                        template_code = '"""\nЗадача: обработка df\n"""\nimport pandas as pd\n\ndef handle(df):\n    return df\n'
                        with open(new_path, "w", encoding="utf-8") as f: f.write(template_code)
                        st.toast(f"✅ Создан: {new_h_name}")
                        time.sleep(0.5)
                        st.rerun()

    with c_ren:
        with st.popover("✏️", use_container_width=True, help="Переименовать"):
            if sel_handler:
                st.write(f"Переименовать **{sel_handler}**")
                ren_name = st.text_input("Новое имя:", value=sel_handler, key="ren_h_input")
                if st.button("Сохранить", key="ren_h_btn"):
                    if ren_name and ren_name != sel_handler:
                        if not ren_name.endswith(".py"): ren_name += ".py"
                        os.rename(os.path.join(HANDLERS_FOLDER, sel_handler), os.path.join(HANDLERS_FOLDER, ren_name))
                        st.rerun()

    with c_del:
        with st.popover("🗑️", use_container_width=True, help="Удалить"):
            if sel_handler:
                st.write(f"Удалить **{sel_handler}**?")
                if st.button("🔥 Да", type="primary", key="del_h_btn"):
                    os.remove(os.path.join(HANDLERS_FOLDER, sel_handler))
                    st.rerun()

    st.divider()

    if sel_handler:
        h_path = os.path.join(HANDLERS_FOLDER, sel_handler)
        buffer_key = "etl_code_buffer"
        last_file_key = "etl_last_loaded_file"

        if (last_file_key not in st.session_state) or (st.session_state[last_file_key] != sel_handler):
            if os.path.exists(h_path):
                with open(h_path, "r", encoding="utf-8") as f: st.session_state[buffer_key] = f.read()
            else: st.session_state[buffer_key] = ""
            st.session_state[last_file_key] = sel_handler

        custom_buttons = [{"name": "Save", "feather": "Save", "hasText": True, "alwaysOn": True, "commands": ["submit"], "style": {"top": "0.46rem", "right": "0.4rem", "background-color": "#FF4B4B", "color": "white", "border-radius": "4px"}}]
        res_h = code_editor(st.session_state[buffer_key], lang="python", height=[20, 30], key=f"editor_component_{sel_handler}", buttons=custom_buttons)
        
        if res_h['text'] is not None and res_h['text'] != st.session_state[buffer_key]:
            st.session_state[buffer_key] = res_h['text']

        if res_h['type'] == "submit":
            if res_h['text']:
                with open(h_path, "w", encoding="utf-8") as f: f.write(res_h['text'])
                st.toast(f"✅ Сохранено!")
    else:
        st.info("👈 Выберите скрипт.")