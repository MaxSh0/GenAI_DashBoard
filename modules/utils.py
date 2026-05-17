import os
import json
import re
from cryptography.fernet import Fernet
from modules.settings import ENCRYPTION_KEY


cipher_suite = Fernet(ENCRYPTION_KEY)


def encrypt_token(plain_text_token: str) -> str:
    """Encrypts an API key string using Fernet encryption.

    Args:
        plain_text_token: The plain-text API key to encrypt.

    Returns:
        The encrypted token as a string, or the original if empty.
    """
    if not plain_text_token:
        return plain_text_token
    return cipher_suite.encrypt(plain_text_token.encode('utf-8')).decode('utf-8')


def decrypt_token(encrypted_token: str) -> str:
    """Decrypts a Fernet-encrypted API key string.

    If decryption fails (e.g. legacy unencrypted key), returns the input as-is.

    Args:
        encrypted_token: The encrypted token string to decrypt.

    Returns:
        The decrypted plain-text token, or the original on failure.
    """
    if not encrypted_token:
        return encrypted_token
    try:
        return cipher_suite.decrypt(encrypted_token.encode('utf-8')).decode('utf-8')
    except Exception:
        return encrypted_token


class ChartExporter:
    """Prepares Plotly figures for HTML export with proper background handling."""

    @staticmethod
    def export_to_html(fig, app_theme_is_dark=True):
        """Exports a Plotly figure to a self-contained HTML string.

        Sets appropriate background colors for dark/light mode and embeds
        the Plotly.js library inline.

        Args:
            fig: A Plotly figure object.
            app_theme_is_dark: Whether the app uses dark theme (default True).

        Returns:
            A complete HTML string with the embedded chart.
        """
        try:
            export_fig = fig

            if app_theme_is_dark:
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

            html_str = export_fig.to_html(
                include_plotlyjs='inline',
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
    """Loads a JSON file, returning a default if the file is missing or invalid.

    Args:
        filepath: Path to the JSON file.
        default: Value to return if the file cannot be loaded.

    Returns:
        Parsed JSON content or the default value.
    """
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(filepath, data):
    """Saves data as a JSON file with indentation.

    Args:
        filepath: Path where the JSON file will be written.
        data: The data to serialize.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def sanitize_filename(name):
    """Converts a display name into a safe Python filename.

    Lowercases, replaces spaces with underscores, strips non-alphanumeric
    characters, and appends .py.

    Args:
        name: The human-readable name to convert.

    Returns:
        A sanitized .py filename string.
    """
    name = name.lower().replace(" ", "_")
    name = re.sub(r'[^a-z0-9_]', '', name)
    return name + ".py"
