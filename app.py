import streamlit as st
import streamlit_authenticator as stauth
import os
import importlib.util
import time
from code_editor import code_editor
import pandas as pd
import random
import inspect
from modules.tasks import update_source_task, celery_app
from celery.result import AsyncResult
from modules.auth import is_authenticated, logout_user, login_redirect, check_auth_code
from modules.settings import *  # noqa: F403,F405
from modules.data_loader import sync_single_source  # noqa: F401
from modules.wizards import (
    wizard_create_chart,
    wizard_manage_sources,
    wizard_manage_pages,
    wizard_manage_llm,
    wizard_manage_workspaces,
)
from modules.io_manager import BundleManager  # noqa: F401
from modules.llm_manager import get_providers, ask_llm  # noqa: F401
from modules.s3_storage import s3_client
from modules.db_manager import SessionLocal, init_db
from modules.models import User, Page, Chart, DataSource, ETLHandler, Workspace  # noqa: F401
from modules.utils import sanitize_filename

st.set_page_config(page_title="GenAI DashBoard", layout="wide")
init_db()
init_project_structure()
s3_client.init_buckets(["charts", "handlers", "data-sources"])

db_auth = SessionLocal()
try:
    users_db = db_auth.query(User).all()
    credentials = {
        "usernames": {
            u.username: {
                "email": u.email,
                "name": u.name,
                "password": u.password_hash,
            }
            for u in users_db
        }
    }
finally:
    db_auth.close()

authenticator = stauth.Authenticate(credentials, "cookie_v1", "key_v1", 30)

try:
    authenticator.login(location='main')
except Exception as e:
    st.error(e)

if st.session_state["authentication_status"]:
    if "active_tasks" not in st.session_state:
        st.session_state.active_tasks = {}

    current_username = st.session_state["username"]
    db = SessionLocal()

    user_obj = db.query(User).filter(User.username == current_username).first()
    if not user_obj:
        st.warning(
            "⚠️ Ваша сессия устарела (пользователь не найден в текущей базе данных)."
        )
        authenticator.logout("🔄 Сбросить сессию и выйти", key="ghost_logout")
        st.stop()

    user_workspaces = user_obj.workspaces
    if not user_workspaces:
        default_ws = Workspace(
            name=f"Личное ({user_obj.username})", owner_id=user_obj.id
        )
        default_ws.users.append(user_obj)
        db.add(default_ws)
        db.commit()
        db.refresh(default_ws)
        user_workspaces = [default_ws]

    user_workspaces = user_obj.workspaces
    if not user_workspaces:
        default_ws = Workspace(
            name=f"Личное ({user_obj.username})", owner_id=user_obj.id
        )
        default_ws.users.append(user_obj)
        db.add(default_ws)
        db.commit()
        db.refresh(default_ws)
        user_workspaces = [default_ws]

    check_auth_code()

    with st.sidebar:
        name_weight = max(len(user_obj.name), 5)
        c1, c2 = st.sidebar.columns(
            [name_weight, 2], gap="small", vertical_alignment="center"
        )
        c1.markdown(f"👤 **{user_obj.name}**")
        with c2:
            authenticator.logout('🚪', key='sidebar_exit')

        st.divider()

        ws_dict = {ws.id: ws.name for ws in user_workspaces}

        url_ws_id = st.query_params.get("ws")
        if url_ws_id and int(url_ws_id) in ws_dict:
            st.session_state.active_ws_id = int(url_ws_id)
        elif (
            "active_ws_id" not in st.session_state
            or st.session_state.active_ws_id not in ws_dict
        ):
            st.session_state.active_ws_id = user_workspaces[0].id
            st.query_params["ws"] = str(st.session_state.active_ws_id)

        c_ws, c_ws_btn = st.columns(
            [0.85, 0.15], vertical_alignment="bottom"
        )
        sel_ws_id = c_ws.selectbox(
            "🏢 Пространство:",
            options=list(ws_dict.keys()),
            format_func=lambda x: ws_dict[x],
            index=list(ws_dict.keys()).index(st.session_state.active_ws_id),
            key="workspace_selector",
        )
        if c_ws_btn.button(
            "⚙️",
            key=f"btn_manage_ws_{user_obj.id}_1",
            help="Управление пространствами",
        ):
            wizard_manage_workspaces()

        if sel_ws_id != st.session_state.active_ws_id:
            st.session_state.active_ws_id = sel_ws_id
            st.query_params["ws"] = str(sel_ws_id)
            st.rerun()

        user_pages = (
            db.query(Page)
            .filter(Page.workspace_id == st.session_state.active_ws_id)
            .all()
        )
        if not user_pages:
            new_p = Page(
                workspace_id=st.session_state.active_ws_id,
                name="Главная страница",
            )
            db.add(new_p)
            db.commit()
            db.refresh(new_p)
            user_pages = [new_p]

        st.divider()
        st.title("📊 GenAI DashBoard")

        st.header("📑 Дашборды")
        page_names = [p.name for p in user_pages]
        query_params = st.query_params

        if (
            "page" in query_params
            and query_params["page"] in page_names
        ):
            d_idx = page_names.index(query_params["page"])
        else:
            d_idx = 0
        current_page_name = st.selectbox(
            "Выберите страницу:",
            page_names,
            index=d_idx,
            label_visibility="collapsed",
            key="db_page_sel",
        )
        st.query_params["page"] = current_page_name

        current_page_obj = next(
            p for p in user_pages if p.name == current_page_name
        )

        c_info, c_ren, c_set = st.columns(
            [0.6, 0.2, 0.2], vertical_alignment="center"
        )
        c_info.caption(f"Графиков: {len(current_page_obj.charts)}")

        with c_ren:
            with st.popover(
                "✏️", help="Переименовать", use_container_width=True
            ):
                new_n = st.text_input(
                    "Название:",
                    value=current_page_obj.name,
                    key=f"ren_pg_{current_page_obj.id}",
                )
                if st.button(
                    "Сохранить",
                    key=f"btn_ren_pg_{current_page_obj.id}",
                    type="primary",
                ):
                    if new_n and new_n != current_page_obj.name:
                        current_page_obj.name = new_n
                        db.commit()
                        st.query_params["page"] = new_n
                        st.rerun()

        if c_set.button(
            "⚙️", help="Настройки состава", key="btn_pg_settings"
        ):
            wizard_manage_pages()

        st.divider()

        if GUIDE_URL:
            st.link_button(
                "📘 Инструкция", GUIDE_URL, use_container_width=True
            )
        st.header("☁️ Данные")

        with st.popover("🔐 Доступ (Google)", use_container_width=True):
            if is_authenticated():
                st.success("Google: ✅ OK")
                if st.button(
                    "Выйти", use_container_width=True, key="btn_logout"
                ):
                    logout_user()
                    st.rerun()
            else:
                st.error("Google: ❌ Off")
                login_redirect()

        active_sources_db = (
            db.query(DataSource)
            .filter(
                DataSource.workspace_id == st.session_state.active_ws_id,
                DataSource.active == True,  # noqa: E712
            )
            .all()
        )

        c_search, c_upload = st.columns(
            [0.85, 0.15], vertical_alignment="center"
        )
        search_q = c_search.text_input(
            "Поиск...",
            placeholder="🔍 Найти...",
            label_visibility="collapsed",
            key="src_search",
        )

        with c_upload:
            with st.popover(
                "📤", help="Загрузить локальный CSV/Excel файл"
            ):
                man_file = st.file_uploader(
                    "Загрузка файла",
                    type=["csv", "xlsx"],
                    label_visibility="collapsed",
                )
                if man_file:
                    upload_task_desc = (
                        f"Загрузка файла '{man_file.name}'"
                    )
                    is_uploading = any(
                        upload_task_desc == str(v)
                        for v in st.session_state.get(
                            "active_tasks", {}
                        ).values()
                    )

                    if is_uploading:
                        st.button(
                            "⏳ Загружается...",
                            disabled=True,
                            use_container_width=True,
                        )
                    else:
                        if st.button(
                            "🚀 Загрузить на сервер",
                            type="primary",
                            use_container_width=True,
                        ):
                            path = os.path.join(
                                DATA_FOLDER, man_file.name
                            )
                            with open(path, "wb") as f:
                                f.write(man_file.getbuffer())

                            from modules.tasks import (
                                upload_local_file_task,
                            )

                            task = upload_local_file_task.delay(
                                temp_path=path,
                                filename=man_file.name,
                                workspace_id=(
                                    st.session_state.active_ws_id
                                ),
                            )

                            if (
                                "active_tasks"
                                not in st.session_state
                            ):
                                st.session_state.active_tasks = {}
                            st.session_state.active_tasks[task.id] = (
                                upload_task_desc
                            )

                            st.toast("📤 Файл отправлен на сервер!")
                            time.sleep(0.5)
                            st.rerun()

        with st.container(height=200, border=True):
            if not active_sources_db:
                st.caption("Нет источников.")
            for i, src in enumerate(active_sources_db):
                if (
                    search_q
                    and search_q.lower() not in src.filename.lower()
                ):
                    continue

                c_icon = {"google_sheets": "📄", "ytsaurus": "🦖"}.get(
                    src.connector_id, "📁"
                )
                r_c1, r_c2 = st.columns(
                    [0.8, 0.2], vertical_alignment="center"
                )

                if len(src.filename) > 18:
                    disp_name = (src.filename[:16] + '..')
                else:
                    disp_name = src.filename
                if src.handler:
                    handler_info = (
                        " &nbsp;<span style='color: #888888; "
                        "font-size: 0.85em; white-space: nowrap;'>"
                        f"🛠️ {src.handler.name}</span>"
                    )
                else:
                    handler_info = ""
                r_c1.markdown(
                    f"{c_icon} `{disp_name}`{handler_info}",
                    help=f"Файл: {src.filename}",
                    unsafe_allow_html=True,
                )
                if src.connector_id != "base" or src.handler_id:
                    is_running = any(
                        src.filename in desc
                        for desc in st.session_state.get(
                            "active_tasks", {}
                        ).values()
                    )

                    if is_running:
                        r_c2.markdown(
                            "<span style='color:#888; font-size: 0.85em;'>"
                            "🔄 В процессе..</span>",
                            unsafe_allow_html=True,
                        )
                    else:
                        if r_c2.button("↻", key=f"upd_src_{src.id}"):
                            creds = st.session_state.get("google_creds")
                            task = update_source_task.delay(
                                src.id, creds
                            )
                            if (
                                "active_tasks"
                                not in st.session_state
                            ):
                                st.session_state.active_tasks = {}
                            st.session_state.active_tasks[task.id] = (
                                f"Обновление '{src.filename}'"
                            )
                            st.rerun()

        c_all, c_manage = st.columns([0.7, 0.3])
        if c_all.button(
            "🚀 Обновить ВСЕ", type="primary", use_container_width=True
        ):
            creds = st.session_state.get("google_creds")
            for src in active_sources_db:
                if src.connector_id == "base" and not src.handler_id:
                    continue

                task = update_source_task.delay(src.id, creds)
                if "active_tasks" not in st.session_state:
                    st.session_state.active_tasks = {}
                st.session_state.active_tasks[task.id] = (
                    f"Обновление '{src.filename}'"
                )
            st.rerun()

        if c_manage.button(
            "⚙️", help="Настройки", use_container_width=True
        ):
            wizard_manage_sources()
        st.divider()

        st.header("📊 Графики")
        if st.button("➕ Новый график", use_container_width=True):
            wizard_create_chart()

        page_charts = current_page_obj.charts
        chart_dict = {c.id: c for c in page_charts}
        all_chart_ids = list(chart_dict.keys())

        # ХАК ПРОТИВ КЭША STREAMLIT: добавляем длину списка в ключ.
        # Теперь, как только добавится новый график, ключ изменится и
        # подхватит новый default!
        dynamic_key = (
            f"ms_cv_{current_page_obj.id}_{len(all_chart_ids)}"
        )

        sel_chart_ids = st.multiselect(
            "Показать на экране:",
            options=all_chart_ids,
            default=all_chart_ids,
            format_func=lambda cid: chart_dict[cid].display_name,
            label_visibility="collapsed",
            key=dynamic_key,
        )

        charts_to_render = [chart_dict[cid] for cid in sel_chart_ids]
        st.divider()
        st.header("📥 Импорт графиков")
        with st.expander("Загрузить (.geb)"):
            up_geb = st.file_uploader(
                "Загрузить файл",
                type=["geb", "zip"],
                label_visibility="collapsed",
            )
            if up_geb:
                if st.button(
                    "Установить", use_container_width=True, type="primary"
                ):
                    import base64

                    b64_data = base64.b64encode(
                        up_geb.read()
                    ).decode("utf-8")

                    from modules.tasks import import_bundle_task

                    task = import_bundle_task.delay(
                        b64_data=b64_data,
                        workspace_id=st.session_state.active_ws_id,
                        target_page=current_page_name,
                    )

                    st.session_state.active_tasks[task.id] = (
                        f"Импорт архива '{up_geb.name}'"
                    )

                    st.toast("📦 Архив отправлен на распаковку!")
                    time.sleep(0.5)
                    st.rerun()

        st.divider()
        st.header("🔗 Связь данных")
        with st.expander("Графики ↔ Данные"):
            if not page_charts:
                st.caption("Сначала добавьте графики.")

            src_dict = {s.id: s for s in active_sources_db}

            for chart in page_charts:
                cur_src_ids = [s.id for s in chart.data_sources]

                new_src_ids = st.multiselect(
                    f"Файлы для '{chart.display_name}'",
                    options=list(src_dict.keys()),
                    default=cur_src_ids,
                    format_func=lambda sid: src_dict[sid].filename,
                    key=f"link_{chart.id}",
                )

                if set(new_src_ids) != set(cur_src_ids):
                    chart.data_sources = [
                        src_dict[sid] for sid in new_src_ids
                    ]
                    db.commit()
                    st.rerun()

        st.divider()
        st.header("🧠 AI Настройки")
        if st.button(
            "⚙️ Управление AI интеграциями",
            use_container_width=True,
            key="btn_manage_llm",
        ):
            wizard_manage_llm()

        st.divider()
        st.header("💬 AI Чат")
        auto_open = bool(st.session_state.get("gen_prompt"))
        with st.expander("Открыть чат с AI", expanded=auto_open):
            providers = get_providers()
            if providers:
                c_p, c_m = st.columns(2)
                p_names = list(providers.keys())
                sel_prov = c_p.selectbox(
                    "Провайдер",
                    p_names,
                    index=(
                        p_names.index(st.session_state.get(
                            "chat_prov", p_names[0]
                        ))
                        if st.session_state.get("chat_prov") in p_names
                        else 0
                    ),
                    key="c_prov",
                    label_visibility="collapsed",
                )
                st.session_state.chat_prov = sel_prov

                avail_models = providers[sel_prov]["models"]
                sel_model = c_m.selectbox(
                    "Модель",
                    avail_models,
                    index=(
                        avail_models.index(st.session_state.get(
                            "chat_mod", avail_models[0]
                        ))
                        if st.session_state.get("chat_mod") in avail_models
                        else 0
                    ),
                    key="c_mod",
                    label_visibility="collapsed",
                )
                st.session_state.chat_mod = sel_model

                if "msgs" not in st.session_state:
                    st.session_state.msgs = []
                if st.button("🗑️ Очистить"):
                    st.session_state.msgs = []
                    st.rerun()

                for m in st.session_state.msgs:
                    st.chat_message(m["role"]).write(m["content"])

                is_chatting = any(
                    v == "Чат с ИИ"
                    for v in st.session_state.get(
                        "active_tasks", {}
                    ).values()
                )

                if is_chatting:
                    with st.chat_message("assistant", avatar="🤖"):
                        st.markdown("✍️ *ИИ печатает...*")

                def send_to_llm_bg(p_text):
                    """Send a user prompt to the LLM as a background task.

                    Constructs a context window from the last 4 chat messages
                    and dispatches a Celery task to call the LLM provider.
                    The result is handled later by the invisible task tracker.

                    Args:
                        p_text: The user's message text to send to the LLM.
                    """
                    ctx = "\n".join([
                        f"{'User' if m['role'] == 'user' else 'AI'}: "
                        f"{m['content']}"
                        for m in st.session_state.msgs[-4:]
                    ])

                    from modules.tasks import chat_llm_task

                    task = chat_llm_task.delay(
                        sel_prov=sel_prov,
                        sel_model=sel_model,
                        history_context=ctx,
                        user_prompt=p_text,
                        user_id=user_obj.id,
                    )
                    st.session_state.active_tasks[task.id] = "Чат с ИИ"
                    st.rerun()

                if draft := st.session_state.get("gen_prompt"):
                    st.info("✨ Черновик")
                    d_txt = st.text_area(
                        "Текст:", value=draft, height=150
                    )
                    c_s, c_c = st.columns([0.4, 0.6])
                    if c_s.button(
                        "🚀 Отправить",
                        type="primary",
                        use_container_width=True,
                        disabled=is_chatting,
                    ):
                        del st.session_state.gen_prompt
                        st.session_state.msgs.append({
                            "role": "user",
                            "content": d_txt,
                        })
                        send_to_llm_bg(d_txt)
                    if c_c.button(
                        "❌ Отмена", use_container_width=True
                    ):
                        del st.session_state.gen_prompt
                        st.rerun()

                if p := st.chat_input(
                    "Вопрос...", disabled=is_chatting
                ):
                    st.session_state.msgs.append({
                        "role": "user",
                        "content": p,
                    })
                    send_to_llm_bg(p)

    st.title(f"📊 {current_page_obj.name}")
    tab_charts, tab_etl = st.tabs([
        "📈 Просмотр Графиков",
        "🛠️ Редактор ETL",
    ])

    with tab_charts:
        if not charts_to_render:
            st.info(
                "Графики скрыты или отсутствуют. Добавьте их в состав "
                "дашборда (кнопка ⚙️ слева вверху) и выберите в меню."
            )

        if "chart_backups" not in st.session_state:
            st.session_state.chart_backups = {}

        for chart_db in charts_to_render:
            fname = chart_db.technical_name
            fpath = os.path.join(CHARTS_FOLDER, fname)

            try:
                s3_client.download_file("charts", fname, fpath)
                file_exists = True
            except Exception:
                st.warning(f"Файл {fname} не найден в S3.")
                file_exists = False

            if not file_exists:
                continue

            st.markdown("---")
            ver_key = f"ver_{chart_db.id}"
            if ver_key not in st.session_state:
                st.session_state[ver_key] = 0
            ed_key = f"ed_{chart_db.id}_{st.session_state[ver_key]}"
            is_dark = st.session_state.get("wiz_active_dark", True)

            try:
                spec = importlib.util.spec_from_file_location(
                    fname[:-3], fpath
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                st.error(f"Ошибка модуля {fname}: {e}")
                continue

            edit_task_desc = (
                f"Редактирование графика '{chart_db.display_name}'"
                f"|{chart_db.id}"
            )
            is_editing = edit_task_desc in st.session_state.get(
                "active_tasks", {}
            ).values()

            c_title, c_edit, c_ai, c_chat, c_exp, c_del = st.columns(
                [0.60, 0.08, 0.08, 0.08, 0.08, 0.08],
                vertical_alignment="center",
            )

            with c_title:
                if is_editing:
                    st.subheader(
                        f"📌 {chart_db.display_name} ⏳ (Обновление...)"
                    )
                else:
                    st.subheader(f"📌 {chart_db.display_name}")

            with c_edit:
                with st.popover("✏️"):
                    n_title = st.text_input(
                        "Имя:",
                        value=chart_db.display_name,
                        key=f"r_{chart_db.id}",
                    )
                    if n_title:
                        if st.button(
                            "OK", key=f"bo_{chart_db.id}"
                        ):
                            chart_db.display_name = n_title
                            db.commit()
                            st.rerun()

            with c_ai:
                with st.popover("✨"):
                    if is_editing:
                        st.status(
                            "🤖 ИИ пишет код...", state="running"
                        )
                    else:
                        if fname in st.session_state.chart_backups:
                            if st.button(
                                "↩️ Откат",
                                key=f"u_{chart_db.id}",
                                use_container_width=True,
                            ):
                                backup = st.session_state.chart_backups[
                                    fname
                                ]
                                with open(
                                    fpath, "w", encoding="utf-8"
                                ) as f:
                                    f.write(backup)
                                s3_client.put_text(
                                    "charts", fname, backup
                                )
                                del st.session_state.chart_backups[
                                    fname
                                ]
                                st.session_state[ver_key] += 1
                                st.rerun()
                        if not providers:
                            st.error("Нет AI")
                        else:
                            r_p = st.selectbox(
                                "AI",
                                list(providers.keys()),
                                key=f"rp_{chart_db.id}",
                                label_visibility="collapsed",
                            )
                            r_m = st.selectbox(
                                "Mod",
                                providers[r_p]["models"],
                                key=f"rm_{chart_db.id}",
                                label_visibility="collapsed",
                            )
                            req = st.text_area(
                                "Запрос", key=f"rq_{chart_db.id}"
                            )
                            if st.button(
                                "🚀 Выполнить",
                                key=f"b_ai_{chart_db.id}",
                                type="primary",
                            ):
                                with open(
                                    fpath, "r", encoding="utf-8"
                                ) as f:
                                    cur_code = f.read()
                                st.session_state.chart_backups[
                                    fname
                                ] = cur_code
                                data_ctx = "Нет данных"
                                if chart_db.data_sources:
                                    try:
                                        d_path = os.path.join(
                                            DATA_FOLDER,
                                            chart_db.data_sources[
                                                0
                                            ].filename,
                                        )
                                        if d_path.endswith('.csv'):
                                            df_p = pd.read_csv(
                                                d_path, nrows=3
                                            )
                                        else:
                                            df_p = pd.read_excel(
                                                d_path, nrows=3
                                            )
                                        data_ctx = "\n".join([
                                            f"- {c} ({t})"
                                            for c, t in zip(
                                                df_p.columns,
                                                df_p.dtypes,
                                            )
                                        ])
                                    except Exception:
                                        pass

                                pmt = (
                                    f"### ТЕКУЩИЙ КОД:\n"
                                    f"```python\n{cur_code}\n```\n\n"
                                    f"### ДАННЫЕ:\n{data_ctx}\n\n"
                                    f"### ЗАПРОС:\n\"{req}\"\n"
                                )
                                sys_msg = (
                                    "Ты Senior Python Developer. "
                                    "Верни ТОЛЬКО валидный код модуля "
                                    "(def render). В конце верни fig."
                                )
                                from modules.tasks import (
                                    edit_chart_task,
                                )

                                task = edit_chart_task.delay(
                                    prompt=pmt,
                                    sys_msg=sys_msg,
                                    fname=fname,
                                    sel_prov=r_p,
                                    sel_model=r_m,
                                    user_id=user_obj.id,
                                )
                                st.session_state.active_tasks[
                                    task.id
                                ] = edit_task_desc
                                st.rerun()

            with c_chat:
                with st.popover("💬"):
                    analyze_task_desc = (
                        f"Анализ данных '{chart_db.display_name}'"
                        f"|{chart_db.id}"
                    )
                    is_analyzing = any(
                        analyze_task_desc == str(v)
                        for v in st.session_state.get(
                            "active_tasks", {}
                        ).values()
                    )

                    if is_analyzing:
                        st.status(
                            "🤖 ИИ анализирует...", state="running"
                        )
                    else:
                        if not providers:
                            st.error("Нет AI")
                        else:
                            user_instructions = st.text_area(
                                "На чем сфокусироваться?",
                                placeholder=(
                                    "Например: Сравни продажи за весну, "
                                    "найди причину падения..."
                                ),
                                key=f"prompt_ins_{chart_db.id}",
                            )

                            p_chat = st.selectbox(
                                "AI",
                                list(providers.keys()),
                                key=f"pc_{chart_db.id}",
                                label_visibility="collapsed",
                            )
                            m_chat = st.selectbox(
                                "Mod",
                                providers[p_chat]["models"],
                                key=f"mc_{chart_db.id}",
                                label_visibility="collapsed",
                            )

                            if st.button(
                                "🚀 Анализ",
                                key=f"b_an_{chart_db.id}",
                                type="primary",
                            ):
                                data_sample = "Нет данных"
                                if chart_db.data_sources:
                                    try:
                                        d_path = os.path.join(
                                            DATA_FOLDER,
                                            chart_db.data_sources[
                                                0
                                            ].filename,
                                        )
                                        if d_path.endswith('.csv'):
                                            df_s = pd.read_csv(
                                                d_path, nrows=50
                                            )
                                        else:
                                            df_s = pd.read_excel(
                                                d_path, nrows=50
                                            )
                                        data_sample = (
                                            df_s.to_csv(index=False)
                                        )
                                    except Exception:
                                        pass

                                with open(
                                    fpath, "r", encoding="utf-8"
                                ) as f:
                                    chart_code = f.read()

                                current_snapshot = st.session_state.get(
                                    f"fig_snapshot_{chart_db.id}",
                                    "Данные снапшота отсутствуют",
                                )

                                from modules.tasks import (
                                    analyze_chart_task,
                                )

                                task = analyze_chart_task.delay(
                                    chart_id=chart_db.id,
                                    code=chart_code,
                                    data_sample_str=data_sample,
                                    user_id=user_obj.id,
                                    sel_prov=p_chat,
                                    sel_model=m_chat,
                                    user_prompt=user_instructions,
                                    fig_snapshot=current_snapshot,
                                )
                                st.session_state.active_tasks[
                                    task.id
                                ] = analyze_task_desc

            with c_exp:
                with st.popover("📦"):
                    t_html, t_geb = st.tabs(["HTML", "GEB"])

                    with t_html:
                        html_placeholder = st.empty()
                        html_placeholder.info("Отрисовка...")

                    with t_geb:
                        export_task_desc = (
                            f"Экспорт '{chart_db.display_name}'"
                            f"|{chart_db.id}"
                        )
                        is_exporting = any(
                            export_task_desc == str(v)
                            for v in st.session_state.get(
                                "active_tasks", {}
                            ).values()
                        )

                        export_ready_key = (
                            f"export_ready_{chart_db.id}"
                        )

                        if is_exporting:
                            st.status(
                                "📦 Упаковка .geb архива...",
                                state="running",
                            )
                        elif export_ready_key in st.session_state:
                            st.success("✅ Архив готов!")
                            export_filename = st.session_state[
                                export_ready_key
                            ]
                            local_export_path = os.path.join(
                                DATA_FOLDER, export_filename
                            )

                            if not os.path.exists(local_export_path):
                                try:
                                    s3_client.download_file(
                                        "charts",
                                        export_filename,
                                        local_export_path,
                                    )
                                except Exception:
                                    pass

                            if os.path.exists(local_export_path):
                                with open(
                                    local_export_path, "rb"
                                ) as f:
                                    st.download_button(
                                        label="⬇️ Скачать .geb",
                                        data=f,
                                        file_name=(
                                            f"{fname[:-3]}.geb"
                                        ),
                                        mime="application/zip",
                                        type="primary",
                                        key=f"dl_geb_{chart_db.id}",
                                        use_container_width=True,
                                    )
                            else:
                                st.error("Файл не найден")
                        else:
                            st.info(
                                "Сгенерировать пакет для экспорта"
                            )
                            if st.button(
                                "🚀 Начать сборку",
                                key=f"gen_geb_{chart_db.id}",
                                use_container_width=True,
                            ):
                                from modules.tasks import (
                                    export_bundle_task,
                                )

                                task = export_bundle_task.delay(
                                    filename=fname,
                                    chart_id=chart_db.id,
                                )
                                st.session_state.active_tasks[
                                    task.id
                                ] = export_task_desc
                                st.rerun()

            with c_del:
                with st.popover("🗑️"):
                    st.write(f"Удалить **{chart_db.display_name}**?")
                    if st.button(
                        "🔥 Да",
                        key=f"del_{chart_db.id}",
                        type="primary",
                    ):
                        if os.path.exists(fpath):
                            os.remove(fpath)
                        try:
                            s3_client.delete_file("charts", fname)
                        except Exception:
                            pass
                        linked_pages = (
                            db.query(Page)
                            .filter(
                                Page.charts.contains(chart_db)
                            )
                            .all()
                        )
                        for p in linked_pages:
                            p.charts.remove(chart_db)
                        chart_db.data_sources = []
                        db.delete(chart_db)
                        db.commit()
                        st.rerun()

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    code_c = f.read()
                with st.expander(f"Код: {chart_db.display_name}"):
                    res = code_editor(
                        code_c,
                        lang="python",
                        height=[8, 15],
                        key=ed_key,
                        buttons=[
                            {
                                "name": "Save",
                                "feather": "Save",
                                "hasText": True,
                                "commands": ["submit"],
                            }
                        ],
                    )
                    if (
                        res['type'] == "submit"
                        and res['text'] != code_c
                    ):
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(res['text'])
                        s3_client.put_text(
                            "charts", fname, res['text']
                        )
                        st.session_state[ver_key] += 1
                        st.rerun()
            except Exception as e:
                st.warning(f"Ошибка редактора: {e}")

            if hasattr(mod, "render"):
                source_paths = [
                    os.path.join(DATA_FOLDER, ds.filename)
                    for ds in chart_db.data_sources
                ]
                WIDGETS = [
                    "button",
                    "checkbox",
                    "radio",
                    "selectbox",
                    "multiselect",
                    "slider",
                    "select_slider",
                    "text_input",
                    "number_input",
                    "text_area",
                    "date_input",
                    "time_input",
                    "file_uploader",
                    "color_picker",
                    "toggle",
                    "plotly_chart",
                    "data_editor",
                ]
                orig_funcs = {
                    name: getattr(st, name)
                    for name in WIDGETS
                    if hasattr(st, name)
                }
                orig_sidebar = st.sidebar

                # НЕУБИВАЕМЫЙ ПРОКСИ ДЛЯ САЙДБАРА:
                # Настоящий контейнер для приема элементов графика,
                # чтобы сайдбар виджеты из пользовательского кода
                # рендерились в main, а не в реальный сайдбар.
                main_dg = st.container()

                class SidebarProxy:
                    """Proxy that redirects sidebar widget calls to a main
                    container.

                    This allows user chart code that writes to
                    ``st.sidebar`` to render inside the main dashboard
                    area instead of the actual sidebar, preventing
                    layout corruption from user-generated content.
                    """

                    def __getattr__(self, name):
                        if hasattr(st, name):
                            return getattr(st, name)
                        return getattr(main_dg, name)

                    def __enter__(self):
                        return main_dg.__enter__()

                    def __exit__(self, t, v, tb):
                        return main_dg.__exit__(t, v, tb)

                # УМНЫЙ АВТО-ГЕНЕРАТОР КЛЮЧЕЙ:
                # Каждому виджету в коде графика присваивается
                # уникальный ключ с суффиксом chart_id, чтобы
                # избежать конфликтов между разными графиками.
                u_suffix = f"chart_inst_{chart_db.id}"

                def create_patch(func, sfx):
                    """Wrap a Streamlit widget function to auto-generate
                    unique keys.

                    If the caller does not supply a ``key``, one is
                    derived from the widget label (or a random number)
                    and suffixed with the chart instance ID to prevent
                    key collisions across multiple charts.

                    Args:
                        func: The original Streamlit widget function.
                        sfx: A unique suffix (e.g. chart instance ID)
                            appended to every generated key.

                    Returns:
                        A wrapper function with the same signature as
                        ``func`` that ensures a unique ``key`` kwarg.
                    """

                    def patched(*args, **kwargs):
                        base_key = kwargs.get('key')
                        if base_key is None:
                            label = kwargs.get('label')
                            if label is None and len(args) > 0:
                                label = str(args[0])
                            if label is None:
                                label = str(
                                    random.randint(10000, 99999)
                                )
                            base_key = f"auto_{str(label)[:15]}"
                        kwargs["key"] = f"{base_key}_{sfx}"
                        return func(*args, **kwargs)

                    return patched

                for n, f in orig_funcs.items():
                    setattr(st, n, create_patch(f, u_suffix))
                st.sidebar = SidebarProxy()

                try:
                    c_args = {"files": source_paths}
                    if (
                        "chart_key"
                        in inspect.signature(mod.render).parameters
                    ):
                        c_args["chart_key"] = fname

                    fig = mod.render(**c_args)

                    if fig:
                        try:
                            snapshot = []
                            for trace in fig.data:
                                snapshot.append({
                                    "name": getattr(
                                        trace, "name", "Линия"
                                    ),
                                    "type": getattr(
                                        trace, "type", "unknown"
                                    ),
                                    "x": list(
                                        getattr(trace, "x", [])
                                    )[:200],
                                    "y": list(
                                        getattr(trace, "y", [])
                                    )[:200],
                                })
                            st.session_state[
                                f"fig_snapshot_{chart_db.id}"
                            ] = str(snapshot)
                        except Exception:
                            st.session_state[
                                f"fig_snapshot_{chart_db.id}"
                            ] = (
                                "Сложный график, снапшот не снят."
                            )

                        from modules.utils import ChartExporter

                        html_data = ChartExporter.export_to_html(
                            fig, app_theme_is_dark=is_dark
                        )
                        html_placeholder.download_button(
                            "⬇️ HTML",
                            data=html_data,
                            file_name=f"{fname[:-3]}.html",
                            mime="text/html",
                            key=f"dl_h_{chart_db.id}",
                            use_container_width=True,
                        )

                except Exception as e:
                    st.error(f"Ошибка рендера: {e}")
                finally:
                    for n, f in orig_funcs.items():
                        setattr(st, n, f)
                    st.sidebar = orig_sidebar

            ins_key = f"insight_{chart_db.id}"
            if ins_key in st.session_state:
                st.write("")

                # Делаем заголовок экспандера уникальным, чтобы
                # Streamlit не переиспользовал состояние при смене
                # графика.
                with st.expander(
                    f"🤖 Анализ: {chart_db.display_name}", expanded=True
                ):
                    insight_text = st.session_state[ins_key]

                    st.markdown(insight_text)
                    st.divider()

                    col_dl, col_cls, _ = st.columns(
                        [0.2, 0.2, 0.6]
                    )
                    with col_dl:
                        safe_name = sanitize_filename(
                            chart_db.display_name
                        )
                        st.download_button(
                            label="💾 Скачать (.md)",
                            data=insight_text,
                            file_name=(
                                f"AI_Insight_{safe_name}.md"
                            ),
                            mime="text/markdown",
                            key=f"dl_ins_{chart_db.id}",
                            use_container_width=True,
                        )
                    with col_cls:
                        if st.button(
                            "❌ Убрать",
                            key=f"cls_ins_{chart_db.id}",
                            use_container_width=True,
                        ):
                            del st.session_state[ins_key]

        @st.fragment(run_every=2)
        def invisible_task_tracker():
            """Poll background Celery tasks and surface results.

            Runs every 2 seconds as a Streamlit fragment.  Iterates
            over all registered ``active_tasks``, checks their Celery
            status, and when a task completes writes its result into
            the appropriate session-state slot (insights, chart
            version bumps, chat messages, or export readiness).
            Completed tasks are removed from the active tracker and
            trigger a full app rerun so the UI updates immediately.
            """
            if not st.session_state.get("active_tasks"):
                return

            completed_tasks = []
            for task_id, task_desc in list(
                st.session_state.active_tasks.items()
            ):
                desc_str = str(task_desc)

                # Игнорируем ОБА названия задач для новых графиков,
                # потому что они обрабатываются visual_chart_tracker.
                if (
                    desc_str.startswith("Создание")
                    or desc_str.startswith("AI код")
                ):
                    continue

                res = AsyncResult(task_id, app=celery_app)
                if res.ready():
                    try:
                        r_data = res.result
                        if "|" in desc_str:
                            c_desc, c_id = desc_str.split("|")
                        else:
                            c_desc, c_id = desc_str, None

                        if (
                            r_data
                            and isinstance(r_data, dict)
                            and r_data.get("status")
                        ):
                            if "Анализ данных" in c_desc:
                                target_id = (
                                    str(c_id).strip()
                                    if c_id
                                    else str(
                                        r_data.get("chart_id")
                                    ).strip()
                                )
                                st.session_state[
                                    f"insight_{target_id}"
                                ] = r_data.get("msg")
                                st.toast("💡 Анализ готов!")
                            elif "Редактирование" in c_desc:
                                st.session_state[f"ver_{c_id}"] = (
                                    st.session_state.get(
                                        f"ver_{c_id}", 0
                                    )
                                    + 1
                                )
                                st.toast("✅ График обновлен!")
                            elif "Чат с ИИ" in c_desc:
                                if (
                                    "msgs"
                                    not in st.session_state
                                ):
                                    st.session_state.msgs = []
                                st.session_state.msgs.append({
                                    "role": "assistant",
                                    "content": r_data.get("msg"),
                                })
                            elif "Экспорт" in c_desc:
                                target_id = (
                                    str(c_id).strip()
                                    if c_id
                                    else str(
                                        r_data.get("chart_id")
                                    ).strip()
                                )
                                st.session_state[
                                    f"export_ready_{target_id}"
                                ] = r_data.get("export_key")
                                st.toast(
                                    "📦 Архив готов к скачиванию!"
                                )
                            else:
                                st.toast(
                                    f"✅ {c_desc} завершено!"
                                )
                        else:
                            # Обрабатываем ошибку чата отдельно,
                            # чтобы сообщение об ошибке попало
                            # в историю сообщений.
                            if "Чат с ИИ" in c_desc:
                                if (
                                    "msgs"
                                    not in st.session_state
                                ):
                                    st.session_state.msgs = []
                                st.session_state.msgs.append({
                                    "role": "assistant",
                                    "content": (
                                        "❌ Ошибка: "
                                        f"{r_data.get('msg')}"
                                    ),
                                })
                            else:
                                st.error("❌ Ошибка")
                    except Exception:
                        pass

                    completed_tasks.append(task_id)

            for t in completed_tasks:
                if t in st.session_state.active_tasks:
                    del st.session_state.active_tasks[t]

            if completed_tasks:
                time.sleep(0.5)
                st.rerun(scope="app")

        invisible_task_tracker()

        @st.fragment(run_every=2)
        def visual_chart_tracker():
            """Poll background chart-creation tasks and show live
            status.

            Runs every 2 seconds as a Streamlit fragment.  Monitors
            tasks whose descriptions start with ``"Создание"`` or
            ``"AI код"``, displays a per-chart status indicator
            (running / complete / error), and removes finished tasks
            from the active tracker.  Triggers a full app rerun when
            all visible chart tasks have completed so the dashboard
            re-renders.
            """
            if not st.session_state.get("active_tasks"):
                return

            completed_charts = []
            for task_id, task_desc in list(
                st.session_state.active_tasks.items()
            ):
                desc_str = str(task_desc)

                # Ловим ОБА варианта названий для задач создания
                # графиков (могут называться по-разному).
                if not (
                    desc_str.startswith("Создание")
                    or desc_str.startswith("AI код")
                ):
                    continue

                res = AsyncResult(task_id, app=celery_app)
                display_name = (
                    desc_str.replace("Создание графика ", "")
                    .replace("AI код для ", "")
                    .strip("'")
                )

                st.markdown("---")
                col1, col2 = st.columns(
                    [0.7, 0.3], vertical_alignment="center"
                )
                col1.subheader(f"📌 {display_name}")

                with col2:
                    if not res.ready():
                        st.status(
                            "🤖 Генерируем новый график...",
                            state="running",
                            expanded=False,
                        )
                    else:
                        r_data = res.result
                        if (
                            r_data
                            and isinstance(r_data, dict)
                            and r_data.get("status")
                        ):
                            st.status(
                                "✅ Готово!",
                                state="complete",
                                expanded=False,
                            )
                        else:
                            if isinstance(r_data, dict):
                                err_msg = r_data.get('msg')
                            else:
                                err_msg = 'Ошибка API'
                            st.status(
                                f"❌ Ошибка: {err_msg}",
                                state="error",
                                expanded=False,
                            )

                        completed_charts.append(task_id)

            for t in completed_charts:
                if t in st.session_state.active_tasks:
                    del st.session_state.active_tasks[t]

            if completed_charts:
                time.sleep(1.5)
                st.rerun(scope="app")

        visual_chart_tracker()

    with tab_etl:
        st.write("🛠️ **Редактор ETL**")
        db_etl = SessionLocal()

        try:
            user_handlers = (
                db_etl.query(ETLHandler)
                .filter(
                    ETLHandler.workspace_id
                    == st.session_state.active_ws_id
                )
                .all()
            )

            handlers_dict = {h.name: h for h in user_handlers}
            handler_names = list(handlers_dict.keys())

            c_sel, c_new, c_del = st.columns(
                [0.74, 0.13, 0.13], vertical_alignment="bottom"
            )
            s_h_name = c_sel.selectbox(
                "Скрипт:",
                handler_names,
                label_visibility="collapsed",
            )

            with c_new:
                with st.popover("➕ Создать"):
                    nh = st.text_input(
                        "Название (напр. 'Очистка'):",
                        key="new_etl_name",
                    )
                    if st.button(
                        "💾 Сохранить",
                        type="primary",
                        use_container_width=True,
                    ):
                        if nh and nh not in handlers_dict:
                            tech_name = (
                                f"ws_{st.session_state.active_ws_id}"
                                f"_{sanitize_filename(nh)}.py"
                            )

                            new_h = ETLHandler(
                                workspace_id=(
                                    st.session_state.active_ws_id
                                ),
                                name=nh,
                                technical_name=tech_name,
                            )
                            db_etl.add(new_h)
                            db_etl.commit()

                            default_code = (
                                "import pandas as pd\n\n"
                                "def handle(df):\n"
                                "    # Ваш код очистки здесь\n"
                                "    return df\n"
                            )
                            p = os.path.join(
                                HANDLERS_FOLDER, tech_name
                            )
                            with open(
                                p, "w", encoding="utf-8"
                            ) as f:
                                f.write(default_code)
                            s3_client.put_text(
                                "handlers", tech_name, default_code
                            )
                            st.rerun()

            with c_del:
                if s_h_name:
                    with st.popover("🗑️ Удалить"):
                        st.write(f"Удалить `{s_h_name}`?")
                        if st.button(
                            "Да, удалить",
                            type="primary",
                            use_container_width=True,
                        ):
                            h_obj = handlers_dict[s_h_name]
                            tech_name = h_obj.technical_name

                            linked_sources = (
                                db_etl.query(DataSource)
                                .filter(
                                    DataSource.handler_id
                                    == h_obj.id
                                )
                                .all()
                            )
                            for s in linked_sources:
                                s.handler_id = None

                            db_etl.delete(h_obj)
                            db_etl.commit()

                            try:
                                os.remove(
                                    os.path.join(
                                        HANDLERS_FOLDER, tech_name
                                    )
                                )
                            except Exception:
                                pass
                            s3_client.delete_file(
                                "handlers", tech_name
                            )
                            st.rerun()

            if s_h_name:
                h_obj = handlers_dict[s_h_name]
                tech_name = h_obj.technical_name
                h_path = os.path.join(HANDLERS_FOLDER, tech_name)

                if (
                    "etl_lf" not in st.session_state
                    or st.session_state.etl_lf != tech_name
                ):
                    try:
                        s3_client.download_file(
                            "handlers", tech_name, h_path
                        )
                        with open(
                            h_path, "r", encoding="utf-8"
                        ) as f:
                            st.session_state.etl_h = f.read()
                    except Exception:
                        st.session_state.etl_h = (
                            "import pandas as pd\n\n"
                            "def handle(df):\n"
                            "    return df\n"
                        )
                    st.session_state.etl_lf = tech_name

                res_h = code_editor(
                    st.session_state.etl_h,
                    lang="python",
                    height=[20, 30],
                    key=f"ed_{tech_name}",
                    buttons=[
                        {
                            "name": "Save",
                            "feather": "Save",
                            "hasText": True,
                            "alwaysOn": True,
                            "commands": ["submit"],
                        }
                    ],
                )

                if (
                    res_h['type'] == "submit"
                    and res_h['text'] != st.session_state.etl_h
                ):
                    st.session_state.etl_h = res_h['text']
                    with open(h_path, "w", encoding="utf-8") as f:
                        f.write(res_h['text'])
                    s3_client.put_text(
                        "handlers", tech_name, res_h['text']
                    )
                    st.toast(f"✅ Скрипт {s_h_name} сохранен!")
        finally:
            db_etl.close()
    db.close()

elif st.session_state["authentication_status"] is False:
    st.error('❌ Неверный логин или пароль')
elif st.session_state["authentication_status"] is None:
    st.warning('🔒 Введите логин и пароль')
