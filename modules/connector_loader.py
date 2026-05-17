import os
import importlib.util
import inspect
from modules.settings import BASE_DIR

CONNECTORS_DIR = os.path.join(BASE_DIR, "modules", "connectors")


def load_connectors():
    """Scan the modules/connectors directory and return a dict of available connector classes.

    Each connector module is dynamically imported. Classes that expose both ``get_meta``
    and ``get_fields`` methods are registered. The returned dict maps ``connector_id``
    (from ``get_meta()['id']``) to the class itself.

    Returns:
        dict: Mapping of connector_id (str) to connector class.
    """
    connectors = {}

    if not os.path.exists(CONNECTORS_DIR):
        return connectors

    for filename in os.listdir(CONNECTORS_DIR):
        if filename.endswith(".py") and filename != "__init__.py" and filename != "base.py":
            module_name = filename[:-3]
            file_path = os.path.join(CONNECTORS_DIR, filename)

            try:
                spec = importlib.util.spec_from_file_location(
                    f"modules.connectors.{module_name}", file_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if hasattr(obj, 'get_meta') and hasattr(obj, 'get_fields'):
                        meta = obj.get_meta()
                        if meta['id'] != 'base':
                            connectors[meta['id']] = obj
            except Exception as e:
                print(f"Error loading connector {filename}: {e}")

    return connectors
