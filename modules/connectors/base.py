import pandas as pd


class BaseConnector:
    """Abstract base class for all data source connectors.

    Subclasses must implement ``load_data`` and may override
    ``get_meta``, ``get_fields``, and ``validate``.
    """

    @staticmethod
    def get_meta():
        """Return connector metadata.

        Returns:
            dict: A dictionary with keys ``id`` (str), ``name`` (str),
                and ``icon`` (str).
        """
        return {
            "id": "base",
            "name": "Base Connector",
            "icon": "🔌",
        }

    @staticmethod
    def get_fields():
        """Return the list of user-facing configuration fields.

        Each field is a dict with keys such as ``key``, ``label``,
        ``type``, ``placeholder``, and ``default``.

        Returns:
            list[dict]: Configuration fields for the connector.
        """
        return []

    def validate(self, config):
        """Optionally validate the connector configuration.

        Args:
            config (dict): Connector configuration dictionary.

        Returns:
            tuple[bool, str]: A tuple of (is_valid, message).
        """
        return True, "OK"

    def load_data(self, config) -> pd.DataFrame:
        """Load data from the source and return it as a DataFrame.

        Args:
            config (dict): Connector configuration dictionary.

        Returns:
            pd.DataFrame: The loaded data.

        Raises:
            NotImplementedError: Always; subclasses must override.
        """
        raise NotImplementedError("Method load_data must be implemented")
