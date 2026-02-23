import os
from sqlalchemy.orm import Session
from modules.db_manager import SessionLocal
from modules.models import User, Page, Chart, DataSource, LLMProvider, ChartTheme
from tabulate import tabulate


def mask_key(key: str) -> str:
    """Маскирует API ключ для безопасности."""
    if not key or len(key) < 8: return "***"
    return f"{key[:4]}...{key[-4:]}"


def inspect():
    db: Session = SessionLocal()  #

    print("\n" + "=" * 80)
    print("🔍 GENAI DASHBOARD: ПОЛНАЯ ИНСПЕКЦИЯ БАЗЫ ДАННЫХ")
    print("=" * 80 + "\n")

    try:
        # 1. ПОЛЬЗОВАТЕЛИ
        users = db.query(User).all()
        user_data = [
            [u.id, u.username, u.name, u.email, u.default_theme_id or "-"]
            for u in users
        ]
        print("👤 ПОЛЬЗОВАТЕЛИ (Users):")
        print(tabulate(user_data, headers=["ID", "Username", "Name", "Email", "Def. Theme"], tablefmt="grid"))
        print("\n")

        # 2. ИНТЕГРАЦИИ С LLM
        providers = db.query(LLMProvider).all()
        llm_data = [
            [p.id, p.name, p.api_type, mask_key(p.api_key), p.base_url or "Default",
             p.models[:30] + "..." if p.models else "-"]
            for p in providers
        ]
        print("🧠 ИНТЕГРАЦИИ С ИИ (LLM Providers):")
        print(tabulate(llm_data, headers=["ID", "Name", "Type", "API Key", "Base URL", "Models"], tablefmt="grid"))
        print("\n")

        # 3. ЦВЕТОВЫЕ ПАЛИТРЫ
        themes = db.query(ChartTheme).all()
        theme_data = [
            [t.id, t.name, t.colors, "🌙" if t.dark_mode else "☀️", t.user_id]
            for t in themes
        ]
        print("🎨 ПАЛИТРЫ (Chart Themes):")
        print(tabulate(theme_data, headers=["ID", "Name", "Colors", "Mode", "Owner ID"], tablefmt="grid"))
        print("\n")

        # 4. СТРАНИЦЫ И ГРАФИКИ НА НИХ
        pages = db.query(Page).all()
        page_data = []
        for p in pages:
            charts_on_page = ", ".join([c.display_name for c in p.charts])  #
            page_data.append([p.id, p.name, p.order, p.user.username if p.user else "N/A", charts_on_page or "---"])

        print("📑 СТРАНИЦЫ (Pages & Linked Charts):")
        print(tabulate(page_data, headers=["ID", "Name", "Order", "Owner", "Charts on Page"], tablefmt="grid"))
        print("\n")

        # 5. ГРАФИКИ И ИСТОЧНИКИ ДАННЫХ
        charts = db.query(Chart).all()
        chart_data = []
        for c in charts:
            sources = ", ".join([s.filename for s in c.data_sources])  #
            chart_data.append([c.id, c.display_name, c.technical_name, sources or "⚠️ NO DATA"])

        print("📊 ГРАФИКИ (Charts & Data Sources):")
        print(tabulate(chart_data, headers=["ID", "Display Name", "File (.py)", "Linked Files"], tablefmt="grid"))
        print("\n")

        # 6. ИСТОЧНИКИ ДАННЫХ
        ds_list = db.query(DataSource).all()
        ds_data = [
            [s.id, s.filename, s.connector_id, s.handler_name or "-", "✅" if s.active else "❌"]
            for s in ds_list
        ]
        print("☁️ ИСТОЧНИКИ ДАННЫХ (Data Sources):")
        print(tabulate(ds_data, headers=["ID", "Filename", "Connector", "Handler", "Active"], tablefmt="grid"))

    except Exception as e:
        print(f"❌ ОШИБКА ПРИ ЧТЕНИИ: {e}")
    finally:
        db.close()
        print("\n" + "=" * 80)


if __name__ == "__main__":
    inspect()