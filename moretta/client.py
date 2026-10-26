"""Metodi riutilizzabili da script e assistenti. Nessuna scrittura all'importazione."""

import mimetypes
from datetime import datetime
from pathlib import Path

import requests

from .config import credentials, normalize_url


class WordPressError(RuntimeError):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


ROUTES = {
    "posts": "wp/v2/posts",
    "media": "wp/v2/media",
    "categories": "wp/v2/categories",
    "tags": "wp/v2/tags",
    "events": "tribe/events/v1/events",
    "venues": "tribe/events/v1/venues",
    "organizers": "tribe/events/v1/organizers",
    "event-categories": "tribe/events/v1/categories",
}


def positive_id(value):
    if isinstance(value, bool) or int(value) <= 0 or str(int(value)) != str(value):
        raise ValueError("L'ID deve essere un intero positivo.")
    return int(value)


class WordPressClient:
    def __init__(self, url, username, app_password, timeout=40):
        self.url = normalize_url(url)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (username, app_password.replace(" ", "").strip())
        self.session.headers.update({"Accept": "application/json", "User-Agent": "MorettaWordPress/1.0"})

    @classmethod
    def from_config(cls):
        return cls(*credentials())

    def request(self, method, route="", *, params=None, data=None, files=None):
        url = self.url + "/wp-json/" + route.lstrip("/")
        try:
            response = self.session.request(
                method, url, params=params, json=data if files is None else None,
                data=data if files is not None else None, files=files,
                timeout=self.timeout, allow_redirects=False,
            )
        except requests.RequestException as exc:
            # Non ripetere automaticamente scritture: potrebbero essere già riuscite.
            hint = " Controlla l'elenco prima di ripetere l'operazione." if method != "GET" else ""
            raise WordPressError("Connessione al sito non riuscita." + hint) from exc
        if 300 <= response.status_code < 400:
            raise WordPressError("Il sito reindirizza la richiesta. Configura l'indirizzo HTTPS finale del sito.", response.status_code)
        try:
            result = response.json()
        except ValueError as exc:
            raise WordPressError("Il sito non ha restituito JSON: verifica REST API, firewall e indirizzo.", response.status_code) from exc
        if not response.ok:
            message = result.get("message", "Errore WordPress") if isinstance(result, dict) else "Errore WordPress"
            code = result.get("code") if isinstance(result, dict) else None
            raise WordPressError(f"HTTP {response.status_code}: {message}", response.status_code, code)
        return result

    def check(self):
        user = self.request("GET", "wp/v2/users/me", params={"context": "edit"})
        index = self.request("GET")
        return {"site": index.get("name"), "url": self.url,
                "user": {"id": user["id"], "name": user.get("name")},
                "events_available": "tribe/events/v1" in index.get("namespaces", [])}

    def schema(self, resource):
        return self.request("OPTIONS", ROUTES[resource])

    def list(self, resource, **filters):
        """Una pagina; WordPress restituisce una lista, TEC un oggetto con total_pages."""
        return self.request("GET", ROUTES[resource], params=filters)

    def get(self, resource, item_id, *, edit=False):
        item_id = positive_id(item_id)
        result = self.request("GET", f"{ROUTES[resource]}/{item_id}",
                              params={"context": "edit"} if edit and resource != "events" else None)
        if edit and resource == "events":
            # L'API TEC restituisce HTML renderizzato. Per modificare conservare i blocchi originali.
            raw = self.request("GET", f"wp/v2/tribe_events/{item_id}", params={"context": "edit"})
            result = dict(result)
            result.update(title=raw["title"]["raw"], description=raw["content"]["raw"],
                          excerpt=raw["excerpt"]["raw"], status=raw["status"])
        return result

    def create_post(self, title, content="", **fields):
        if not title.strip():
            raise ValueError("Il titolo è obbligatorio.")
        return self.request("POST", ROUTES["posts"], data={"title": title, "content": content, "status": "draft", **fields})

    def update_post(self, post_id, **fields):
        return self.request("POST", f"{ROUTES['posts']}/{positive_id(post_id)}", data=fields)

    @staticmethod
    def _validate_dates(fields):
        parsed = {}
        for key in ("start_date", "end_date"):
            if key in fields:
                try:
                    date = datetime.fromisoformat(fields[key])
                except (ValueError, TypeError) as exc:
                    raise ValueError("Date evento: usa YYYY-MM-DD HH:MM:SS e timezone separato.") from exc
                if date.tzinfo is not None:
                    raise ValueError("Usa date locali senza offset e il campo timezone (es. Europe/Rome).")
                parsed[key] = date
        if len(parsed) == 2 and parsed["end_date"] < parsed["start_date"]:
            raise ValueError("La fine dell'evento precede l'inizio.")

    def create_event(self, title, start_date, end_date, **fields):
        if not title.strip():
            raise ValueError("Il titolo è obbligatorio.")
        payload = {"title": title, "start_date": start_date, "end_date": end_date,
                   "status": "draft", "timezone": "Europe/Rome", **fields}
        self._validate_dates(payload)
        return self.request("POST", ROUTES["events"], data=payload)

    def update_event(self, event_id, **fields):
        event_id = positive_id(event_id)
        current = self.get("events", event_id)
        # Alcune versioni TEC assegnano false ai flag omessi durante una modifica.
        payload = {key: current[key] for key in ("all_day", "show_map", "show_map_link", "sticky", "featured", "status", "website") if key in current}
        if "hide_from_listings" in current:
            payload["hide_from_listings"] = current["hide_from_listings"]
        elif "hidden" in current:
            payload["hide_from_listings"] = current["hidden"]
        payload.update(fields)
        dates = {k: fields.get(k, current.get(k)) for k in ("start_date", "end_date")}
        self._validate_dates(dates)
        return self.request("POST", f"{ROUTES['events']}/{event_id}", data=payload)

    def upload_media(self, path, **metadata):
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        # Un'unica richiesta multipart: evita di perdere l'ID se fallisce una seconda scrittura.
        with path.open("rb") as stream:
            return self.request("POST", ROUTES["media"], data=metadata,
                                files={"file": (path.name, stream, mime)})

    def update_media(self, media_id, **metadata):
        return self.request("POST", f"{ROUTES['media']}/{positive_id(media_id)}", data=metadata)

    def create_term(self, resource, name, **fields):
        if resource not in ("categories", "tags", "event-categories"):
            raise ValueError("Tipo di tassonomia non valido.")
        return self.request("POST", ROUTES[resource], data={"name": name, **fields})

    def trash(self, resource, item_id):
        if resource not in ("posts", "events"):
            raise ValueError("Il cestino è disponibile per articoli ed eventi.")
        item_id = positive_id(item_id)
        # WordPress può cancellare definitivamente un articolo già nel cestino: impedirlo.
        current = self.get(resource, item_id)
        if current.get("status") == "trash":
            raise ValueError("Il contenuto è già nel cestino.")
        return self.request("DELETE", f"{ROUTES[resource]}/{item_id}")
