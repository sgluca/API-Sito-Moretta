"""Configurazione pubblica su disco, password nel portachiavi di sistema."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import keyring

DEFAULT_URL = "https://parrocchiamoretta.altervista.org"
CONFIG_PATH = Path(__file__).resolve().parent.parent / ".local" / "config.json"


def normalize_url(url):
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment):
        raise ValueError("Usa l'indirizzo HTTPS del sito, senza credenziali o parametri.")
    if parts.path.endswith("/wp-json"):
        url = url[:-8]
    return url


def service(url):
    return "moretta-wordpress:" + normalize_url(url)


def public_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"url": DEFAULT_URL, "username": ""}


def save_config(url, username, password):
    url = normalize_url(url)
    username = username.strip()
    if not username or not password.strip():
        raise ValueError("Inserisci nome utente e password per applicazioni.")
    # Se il portachiavi non funziona, non ripiegare su un file in chiaro.
    keyring.set_password(service(url), username, password.replace(" ", "").strip())
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"url": url, "username": username}, indent=2), encoding="utf-8")


def credentials():
    config = public_config()
    url = normalize_url(os.environ.get("WP_URL", config["url"]))
    username = os.environ.get("WP_USERNAME", config.get("username", "")).strip()
    password = os.environ.get("WP_APP_PASSWORD")
    if password is None and username:
        password = keyring.get_password(service(url), username)
    if not username or not password:
        raise ValueError("Collegamento non configurato. Apri l'interfaccia o esegui: python -m moretta configure")
    return url, username, password
