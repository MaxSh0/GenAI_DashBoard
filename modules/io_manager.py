import json
import os
import random
import re
import time
import zipfile
from datetime import datetime

from modules.db_manager import SessionLocal
from modules.models import Chart, DataSource, Page
from modules.s3_storage import s3_client
from modules.settings import CHARTS_FOLDER, DATA_FOLDER


class BundleManager:
    """Import/export of charts as .geb bundle files."""

    @staticmethod
    def _randomize_widget_keys(code_str):
        """Prevent widget key collisions by appending a random suffix.

        Finds hardcoded ``key="..."`` values in Streamlit widget code
        and appends a unique suffix to each, so imported charts do not
        conflict with existing widgets on the page.

        Args:
            code_str: Python source code string to process.

        Returns:
            The modified source code with randomized widget keys.
        """
        suffix = f"{int(time.time())}_{random.randint(100, 999)}"
        pattern_keys = r'(key\s*=\s*)(["\'])(.*?)\2'

        def key_replacer(match):
            prefix = match.group(1)
            quote = match.group(2)
            old_key = match.group(3)
            return f"{prefix}{quote}{old_key}_{suffix}{quote}"

        try:
            return re.sub(pattern_keys, key_replacer, code_str)
        except Exception as e:
            print(f"Regex Error: {e}")
            return code_str

    @staticmethod
    def export_chart_to_s3(filename):
        """Export a chart and its linked data files as a .geb bundle.

        Assembles a ZIP archive containing the chart source code,
        a manifest.json, and all linked data files, then uploads it
        to S3. The archive is built on disk to avoid high memory usage.

        Args:
            filename: The technical_name of the chart to export.

        Returns:
            The filename of the exported .geb bundle in S3.

        Raises:
            ValueError: If the chart is not found in the database.
        """
        db = SessionLocal()
        try:
            chart = db.query(Chart).filter(Chart.technical_name == filename).first()
            if not chart:
                raise ValueError(f"График {filename} не найден в базе данных.")

            display_name = chart.display_name
            linked_data = [ds.filename for ds in chart.data_sources]

            manifest = {
                "version": "2.0",
                "type": "chart",
                "exported_at": datetime.now().isoformat(),
                "items": [
                    {
                        "filename": filename,
                        "display_name": display_name,
                        "data_files": linked_data,
                    }
                ],
            }

            export_filename = f"export_{filename[:-3]}_{int(time.time())}.geb"
            export_path = os.path.join(DATA_FOLDER, export_filename)

            # Write to disk to avoid high memory usage with large archives.
            with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

                src_path = os.path.join(CHARTS_FOLDER, filename)
                if not os.path.exists(src_path):
                    try:
                        s3_client.download_file("charts", filename, src_path)
                    except Exception:
                        pass

                if os.path.exists(src_path):
                    zf.write(src_path, arcname=f"source/{filename}")

                for df_name in linked_data:
                    d_path = os.path.join(DATA_FOLDER, df_name)
                    if not os.path.exists(d_path):
                        try:
                            s3_client.download_file("data-sources", df_name, d_path)
                        except Exception:
                            pass

                    if os.path.exists(d_path):
                        zf.write(d_path, arcname=f"data/{df_name}")

            s3_client.upload_file(export_path, "charts", export_filename)

            return export_filename
        finally:
            db.close()

    @staticmethod
    def import_bundle(file_bytes, workspace_id, target_page=None):
        """Import charts from a .geb bundle into the workspace.

        Unpacks a .geb archive, saves chart code and data files to disk
        and S3, registers them in the database scoped to the given
        workspace, and optionally adds charts to a target page.

        Args:
            file_bytes: A file-like object containing the .geb bundle bytes.
            workspace_id: The workspace to import into.
            target_page: Optional page name to add imported charts to.

        Returns:
            A tuple of ``(success, message)`` where *success* is a bool
            and *message* is a human-readable status string.
        """
        log_messages = []
        new_charts_list = []

        db = SessionLocal()
        try:
            with zipfile.ZipFile(file_bytes, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    return False, "❌ Нет manifest.json"

                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))

                for item in manifest["items"]:
                    orig_fname = item["filename"]
                    display_name = item.get("display_name", orig_fname)
                    data_files = item.get("data_files", [])

                    final_chart_name = orig_fname

                    existing_chart = db.query(Chart).filter(
                        Chart.workspace_id == workspace_id,
                        Chart.technical_name == final_chart_name,
                    ).first()
                    if existing_chart:
                        timestamp = int(time.time())
                        final_chart_name = f"{orig_fname[:-3]}_imp_{timestamp}.py"
                        log_messages.append(f"⚠️ Файл переименован: {final_chart_name}")

                    target_chart_path = os.path.join(CHARTS_FOLDER, final_chart_name)

                    try:
                        code_bytes = zf.read(f"source/{orig_fname}")
                        code_str = code_bytes.decode("utf-8")
                        code_fixed = BundleManager._randomize_widget_keys(code_str)

                        with open(target_chart_path, "w", encoding="utf-8") as f:
                            f.write(code_fixed)
                        s3_client.put_text("charts", final_chart_name, code_fixed)

                    except KeyError:
                        log_messages.append(f"❌ Код {orig_fname} не найден в архиве.")
                        continue

                    db_data_sources = []
                    for df_name in data_files:
                        try:
                            data_bytes = zf.read(f"data/{df_name}")
                            final_df_name = df_name
                            target_data_path = os.path.join(DATA_FOLDER, final_df_name)

                            if os.path.exists(target_data_path):
                                if os.path.getsize(target_data_path) != len(data_bytes):
                                    root, ext = os.path.splitext(df_name)
                                    ts = int(time.time())
                                    final_df_name = f"{root}_imp_{ts}{ext}"
                                    target_data_path = os.path.join(DATA_FOLDER, final_df_name)
                                    log_messages.append(f"📦 Данные сохранены как {final_df_name}")
                                else:
                                    log_messages.append(f"✅ Данные: используется существующий {df_name}")

                            if not os.path.exists(target_data_path):
                                with open(target_data_path, "wb") as f:
                                    f.write(data_bytes)
                                s3_client.upload_file(target_data_path, "data-sources", final_df_name)

                            ds = db.query(DataSource).filter(
                                DataSource.workspace_id == workspace_id,
                                DataSource.filename == final_df_name,
                            ).first()
                            if not ds:
                                ds = DataSource(
                                    workspace_id=workspace_id,
                                    connector_id="base",
                                    filename=final_df_name,
                                    active=True,
                                )
                                db.add(ds)
                                db.flush()

                            db_data_sources.append(ds)

                        except KeyError:
                            pass

                    new_chart = Chart(
                        workspace_id=workspace_id,
                        technical_name=final_chart_name,
                        display_name=f"{display_name} (Import)" if "imp_" in final_chart_name else display_name,
                    )
                    new_chart.data_sources = db_data_sources
                    db.add(new_chart)
                    db.flush()
                    new_charts_list.append(new_chart)

                if target_page and new_charts_list:
                    page = db.query(Page).filter(
                        Page.workspace_id == workspace_id,
                        Page.name == target_page,
                    ).first()
                    if not page:
                        page = Page(workspace_id=workspace_id, name=target_page)
                        db.add(page)

                    for ch in new_charts_list:
                        if ch not in page.charts:
                            page.charts.append(ch)

                    log_messages.append(f"📌 Добавлено на страницу '{target_page}'")

            db.commit()
            return True, "\n".join(log_messages)

        except Exception as e:
            db.rollback()
            return False, f"Ошибка импорта: {str(e)}"
        finally:
            db.close()
