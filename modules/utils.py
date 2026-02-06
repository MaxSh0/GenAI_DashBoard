import os
import json
import re
import io

class ChartExporter:
    """
    Класс для подготовки Plotly графиков к экспорту в HTML.
    Решает проблемы с белым фоном и отсутствием JS-библиотек.
    """
    
    @staticmethod
    def export_to_html(fig, app_theme_is_dark=True):
        try:
            # 1. Делаем копию, чтобы не сломать отображение на экране
            # (хотя to_html обычно не ломает, но для надежности)
            export_fig = fig

            # 2. Исправляем фон (Background Fix)
            # Если тема темная, а фон прозрачный -> ставим темный цвет
            # Иначе в браузере будет белый фон и белый текст.
            if app_theme_is_dark:
                # Цвет фона Streamlit Dark Mode
                bg_color = "#0e1117" 
                export_fig.update_layout(
                    paper_bgcolor=bg_color,
                    plot_bgcolor=bg_color
                )
            else:
                export_fig.update_layout(
                    paper_bgcolor="#ffffff",
                    plot_bgcolor="#ffffff"
                )

            # 3. Генерируем HTML с встроенным JS (Offline mode)
            html_str = export_fig.to_html(
                include_plotlyjs='inline', # Зашиваем движок внутрь
                full_html=True,
                config={
                    'responsive': True,
                    'displayModeBar': True,
                    'displaylogo': False
                }
            )
            return html_str
        except Exception as e:
            return f"<h1>Export Error</h1><p>{e}</p>"
        
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return default
    return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def sanitize_filename(name):
    name = name.lower().replace(" ", "_")
    name = re.sub(r'[^a-z0-9_]', '', name)
    return name + ".py"