"""CLI JSON per l'uso da parte di Codex e da altri programmi."""

import argparse
import getpass
import json
import sys
from pathlib import Path

from .client import ROUTES, WordPressClient, WordPressError
from .config import DEFAULT_URL, save_config


def object_json(value):
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("Il JSON deve essere un oggetto.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gestione sito Parrocchia Moretta; risultati JSON.")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure", help="Salva il collegamento e la password nel portachiavi")
    setup.add_argument("--url", default=DEFAULT_URL)
    setup.add_argument("--username")
    sub.add_parser("gui", help="Apri la finestra desktop")
    sub.add_parser("check", help="Verifica autenticazione e disponibilità calendario")
    for command in ("list", "get", "schema", "create", "update", "trash"):
        p = sub.add_parser(command)
        p.add_argument("resource", choices=list(ROUTES))
        if command in ("get", "update", "trash"):
            p.add_argument("id", type=int)
        if command in ("list", "create", "update"):
            group = p.add_mutually_exclusive_group()
            group.add_argument("--data", help="Oggetto JSON di campi o filtri")
            group.add_argument("--file", type=Path, help="File JSON UTF-8")
        if command == "get":
            p.add_argument("--edit", action="store_true", help="Leggi il contenuto originale modificabile")
    upload = sub.add_parser("upload", help="Carica un file nella libreria media")
    upload.add_argument("path", type=Path)
    upload.add_argument("--title")
    upload.add_argument("--alt-text")
    upload.add_argument("--caption")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            gui_main()
            return
        if args.command == "configure":
            username = args.username or input("Utente WordPress: ").strip()
            password = getpass.getpass("Password per applicazioni: ")
            client = WordPressClient(args.url, username, password)
            result = client.check()
            save_config(args.url, username, password)
        else:
            client = WordPressClient.from_config()
            data = {}
            if getattr(args, "file", None):
                data = object_json(args.file.read_text(encoding="utf-8-sig"))
            elif getattr(args, "data", None):
                data = object_json(args.data)
            if args.command == "check":
                result = client.check()
            elif args.command == "schema":
                result = client.schema(args.resource)
            elif args.command == "list":
                result = client.list(args.resource, **data)
            elif args.command == "get":
                result = client.get(args.resource, args.id, edit=args.edit)
            elif args.command == "create":
                if args.resource == "posts":
                    result = client.create_post(**data)
                elif args.resource == "events":
                    result = client.create_event(**data)
                else:
                    result = client.create_term(args.resource, **data)
            elif args.command == "update":
                method = {"posts": client.update_post, "events": client.update_event, "media": client.update_media}.get(args.resource)
                if method is None:
                    raise ValueError("Modifica disponibile per posts, events e media.")
                result = method(args.id, **data)
            elif args.command == "trash":
                result = client.trash(args.resource, args.id)
            else:
                metadata = {k: v for k, v in {"title": args.title, "alt_text": args.alt_text, "caption": args.caption}.items() if v is not None}
                result = client.upload_media(args.path, **metadata)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        error = {"error": str(exc)}
        if isinstance(exc, WordPressError):
            error.update(status=exc.status, code=exc.code)
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
