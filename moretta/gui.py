"""Interfaccia desktop Tk; le richieste di rete non bloccano la finestra."""

import html
import json
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .client import WordPressClient
from .config import public_config, save_config


def text_value(value):
    if isinstance(value, dict):
        return value.get("raw", value.get("rendered", ""))
    return value or ""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Parrocchia Moretta · Contenuti del sito")
        self.geometry("1180x820")
        self.minsize(980, 720)
        self.client = None
        self.pending = False
        self.results = queue.Queue()
        self.status = tk.StringVar(value="Configura il collegamento per iniziare.")
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TButton", padding=5)
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        ttk.Label(self, text="Parrocchia Moretta", style="Title.TLabel", padding=(18, 12)).pack(anchor="w")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.connection_tab()
        self.editors = [Editor(self, resource, label) for resource, label in (("posts", "Articoli"), ("events", "Eventi"), ("media", "Media"))]
        ttk.Label(self, textvariable=self.status, padding=(16, 8), wraplength=1100).pack(fill="x")
        self.after(100, self.poll)

    def connection_tab(self):
        frame = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(frame, text="Collegamento")
        conf = public_config()
        self.url = tk.StringVar(value=conf["url"])
        self.username = tk.StringVar(value=conf.get("username", ""))
        self.password = tk.StringVar()
        ttk.Label(frame, text="Collega il sito WordPress", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 20))
        for row, (label, variable) in enumerate((("Indirizzo HTTPS", self.url), ("Utente WordPress", self.username), ("Password per applicazioni", self.password)), 1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=8)
            ttk.Entry(frame, textvariable=variable, width=64, show="•" if row == 3 else "").grid(row=row, column=1, sticky="ew", pady=8)
        ttk.Label(frame, text="La password viene salvata nel portachiavi di Windows.\nLasciala vuota per usare quella già salvata.", wraplength=650).grid(row=4, column=1, sticky="w", pady=10)
        ttk.Button(frame, text="Collega e verifica", command=self.connect).grid(row=5, column=1, sticky="w", pady=12)
        ttk.Label(frame, text="In WordPress: Utenti → Profilo → Password per le applicazioni.\nCrea una password dedicata, ad esempio “Gestione Moretta”.\nI permessi corrispondono a quelli del tuo utente WordPress.", wraplength=780).grid(row=6, column=0, columnspan=2, sticky="w", pady=22)
        frame.columnconfigure(1, weight=1)

    def run(self, action, callback):
        if self.pending:
            messagebox.showinfo("Operazione in corso", "Attendi il completamento dell'operazione corrente.")
            return
        self.pending = True
        self.status.set("Operazione in corso…")

        def worker():
            try:
                self.results.put((callback, action(), None))
            except Exception as exc:
                self.results.put((callback, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            callback, result, error = self.results.get_nowait()
            self.pending = False
            if error:
                self.status.set(str(error))
                messagebox.showerror("Operazione non riuscita", str(error))
            else:
                self.status.set("Operazione completata.")
                try:
                    callback(result)
                except Exception as exc:
                    messagebox.showerror("Risultato", str(exc))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def connect(self):
        url, username, password = self.url.get(), self.username.get().strip(), self.password.get()

        def action():
            if not password:
                from .config import normalize_url, service
                import keyring
                secret = keyring.get_password(service(normalize_url(url)), username)
                if not secret:
                    raise ValueError("Inserisci la password per applicazioni.")
            else:
                secret = password
            client = WordPressClient(url, username, secret)
            result = client.check()
            save_config(url, username, secret)
            return client, result

        def done(result):
            self.client, info = result
            self.password.set("")
            self.status.set(f"Collegato a {info['site']} come {info['user']['name']}. Calendario: {'disponibile' if info['events_available'] else 'non rilevato'}.")

        self.run(action, done)

    def require_client(self):
        if self.client is None:
            messagebox.showinfo("Collegamento", "Collega prima il sito dalla scheda Collegamento.")
            self.tabs.select(0)
            return False
        return True


class Editor:
    def __init__(self, app, resource, label):
        self.app, self.resource = app, resource
        self.item_id = None
        self.item_link = ""
        self.original = {}
        self.page = 1
        self.variables = {}
        self.frame = ttk.Frame(app.tabs, padding=12)
        app.tabs.add(self.frame, text=label)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x")
        self.search = tk.StringVar()
        ttk.Label(bar, text="Cerca").pack(side="left")
        entry = ttk.Entry(bar, textvariable=self.search, width=28)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _: self.refresh(reset=True))
        self.filter_status = tk.StringVar(value="publish" if resource == "events" else "any")
        if resource != "media":
            ttk.Combobox(bar, textvariable=self.filter_status, values=("any", "publish", "draft", "pending", "private", "future", "trash"), state="readonly", width=10).pack(side="left", padx=4)
        ttk.Button(bar, text="Cerca / aggiorna", command=lambda: self.refresh(reset=True)).pack(side="left", padx=4)
        ttk.Button(bar, text="←", command=lambda: self.change_page(-1)).pack(side="left")
        self.page_label = ttk.Label(bar, text="Pagina 1")
        self.page_label.pack(side="left", padx=6)
        ttk.Button(bar, text="→", command=lambda: self.change_page(1)).pack(side="left")
        ttk.Button(bar, text="Nuovo" if resource != "media" else "Nuovo media", command=self.new).pack(side="right")
        pane = ttk.Panedwindow(self.frame, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=("id", "title"), show="headings", selectmode="browse")
        self.tree.heading("id", text="ID")
        self.tree.heading("title", text="Titolo · doppio clic per aprire")
        self.tree.column("id", width=55, stretch=False)
        self.tree.column("title", width=260)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self.load_selected())
        ttk.Button(left, text="Apri selezionato", command=self.load_selected).pack(fill="x", pady=6)
        right = ttk.Frame(pane, padding=(14, 0, 0, 0))
        pane.add(right, weight=3)
        self.heading = ttk.Label(right, text="Nuovo contenuto", font=("Segoe UI", 12, "bold"))
        self.heading.pack(anchor="w", pady=(0, 8))
        fields = ttk.Frame(right)
        fields.pack(fill="x")
        specs = [("title", "Titolo", "")]
        if resource != "media":
            specs += [("status", "Stato", "draft"), ("slug", "Indirizzo breve (slug)", ""),
                      ("image" if resource == "events" else "featured_media", "ID immagine in evidenza", ""),
                      ("categories", "ID categorie (separati da virgola)", ""), ("tags", "ID tag (separati da virgola)", "")]
        if resource == "events":
            specs += [("start_date", "Inizio · YYYY-MM-DD HH:MM:SS", ""), ("end_date", "Fine · YYYY-MM-DD HH:MM:SS", ""),
                      ("timezone", "Fuso orario", "Europe/Rome"), ("all_day", "Tutto il giorno", False),
                      ("venue", "ID luogo", ""), ("organizer", "ID organizzatori (virgola)", ""),
                      ("cost", "Costo (0 = gratuito)", ""), ("website", "Sito dell'evento", "")]
        if resource == "media":
            specs += [("alt_text", "Testo alternativo", ""), ("caption", "Didascalia", "")]
        self.defaults = dict((key, default) for key, _, default in specs)
        for row, (key, label_text, default) in enumerate(specs):
            ttk.Label(fields, text=label_text).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 12))
            var = tk.BooleanVar(value=default) if isinstance(default, bool) else tk.StringVar(value=default)
            self.variables[key] = var
            if key == "all_day":
                widget = ttk.Checkbutton(fields, variable=var)
            elif key == "status":
                widget = ttk.Combobox(fields, textvariable=var, values=("draft", "publish", "pending", "private", "future"), state="readonly")
            else:
                widget = ttk.Entry(fields, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", pady=2)
        fields.columnconfigure(1, weight=1)
        ttk.Label(right, text="Descrizione" if resource == "media" else "Contenuto HTML / blocchi WordPress").pack(anchor="w", pady=(10, 4))
        self.content = scrolledtext.ScrolledText(right, height=9, wrap="word", font=("Consolas", 10), undo=True)
        self.content.pack(fill="both", expand=True)
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Salva modifiche / crea", command=self.save).pack(side="left")
        if resource == "media":
            ttk.Button(actions, text="Copia URL", command=self.copy_url).pack(side="left", padx=4)
        else:
            ttk.Button(actions, text="Importa HTML…", command=self.import_html).pack(side="left", padx=4)
            ttk.Button(actions, text="Cestina", command=self.trash).pack(side="right")
        ttk.Button(actions, text="Apri nel browser", command=self.open_browser).pack(side="left", padx=4)
        self.baseline = self.snapshot()

    def snapshot(self):
        return {**{k: v.get() for k, v in self.variables.items()}, "_content": self.content.get("1.0", "end-1c")}

    def can_discard(self):
        return self.snapshot() == self.baseline or messagebox.askyesno("Modifiche non salvate", "Abbandonare le modifiche non salvate?")

    def new(self):
        if not self.can_discard():
            return
        self.item_id, self.item_link, self.original = None, "", {}
        for key, var in self.variables.items():
            var.set(self.defaults[key])
        self.content.delete("1.0", "end")
        self.heading.configure(text="Nuovo contenuto")
        self.baseline = self.snapshot()

    def change_page(self, delta):
        self.page = max(1, self.page + delta)
        self.refresh()

    def refresh(self, reset=False):
        if not self.app.require_client():
            return
        if reset:
            self.page = 1
        params = {"per_page": 20, "page": self.page}
        if self.search.get().strip():
            params["search"] = self.search.get().strip()
        if self.resource != "media":
            params["status"] = self.filter_status.get()

        def done(data):
            items = data.get(self.resource, []) if isinstance(data, dict) else data
            self.tree.delete(*self.tree.get_children())
            for item in items:
                self.tree.insert("", "end", iid=str(item["id"]), values=(item["id"], html.unescape(text_value(item.get("title")))))
            self.page_label.configure(text=f"Pagina {self.page}")
            self.app.status.set(f"{len(items)} elementi caricati. Doppio clic per modificare.")

        self.app.run(lambda: self.app.client.list(self.resource, **params), done)

    def load_selected(self):
        if not self.app.require_client() or not self.tree.selection() or not self.can_discard():
            return
        item_id = int(self.tree.selection()[0])
        self.app.run(lambda: self.app.client.get(self.resource, item_id, edit=True), self.populate)

    def populate(self, item):
        self.original = item
        self.item_id = item["id"]
        self.item_link = item.get("source_url", item.get("url", item.get("link", "")))
        for key, var in self.variables.items():
            value = item.get(key, self.defaults[key])
            if key == "image":
                value = value.get("id", "") if isinstance(value, dict) else (value or "")
            elif key in ("venue",):
                value = value.get("id", "") if isinstance(value, dict) else (value or "")
            elif key in ("categories", "tags", "organizer"):
                if isinstance(value, list):
                    value = ",".join(str(v.get("id")) if isinstance(v, dict) else str(v) for v in value)
            elif isinstance(value, dict):
                value = text_value(value)
            var.set(value)
        content = item.get("description" if self.resource in ("events", "media") else "content", "")
        self.content.delete("1.0", "end")
        self.content.insert("1.0", text_value(content))
        self.heading.configure(text=f"Modifica {self.resource} · ID {self.item_id}")
        self.baseline = self.snapshot()
        self.app.status.set(f"Caricato ID {self.item_id}. {self.item_link}")

    def payload(self):
        now = self.snapshot()
        result = {}
        for key in self.variables:
            value = now[key]
            if self.item_id is not None and value == self.baseline[key]:
                continue
            if key in ("categories", "tags", "organizer"):
                value = [int(v.strip()) for v in str(value).split(",") if v.strip()]
            elif key in ("image", "featured_media", "venue"):
                if not value:
                    if self.item_id is None:
                        continue
                    value = 0
                else:
                    value = int(value)
            result[key] = value
        content_key = "description" if self.resource in ("events", "media") else "content"
        if self.item_id is None or now["_content"] != self.baseline["_content"]:
            result[content_key] = now["_content"]
        return result

    def save(self):
        if not self.app.require_client():
            return
        try:
            data = self.payload()
        except ValueError:
            messagebox.showerror("Valori non validi", "Immagine, luogo, categorie e tag devono contenere ID numerici.")
            return
        if not data:
            self.app.status.set("Nessuna modifica da salvare.")
            return
        if data.get("status") == "publish" and not messagebox.askyesno("Pubblicazione", "Pubblicare questo contenuto sul sito?"):
            return
        resource, item_id, client = self.resource, self.item_id, self.app.client
        path = None
        if resource == "media" and item_id is None:
            path = filedialog.askopenfilename(title="Scegli il file da caricare")
            if not path:
                return

        def action():
            if item_id is not None:
                method = {"posts": client.update_post, "events": client.update_event, "media": client.update_media}[resource]
                item = method(item_id, **data)
            elif resource == "posts":
                item = client.create_post(**data)
            elif resource == "events":
                item = client.create_event(**data)
            else:
                item = client.upload_media(path, **data)
            # Il salvataggio è già riuscito: un errore di rilettura non deve invitare a duplicarlo.
            try:
                return client.get(resource, item["id"], edit=True), None
            except Exception as exc:
                return item, str(exc)

        def done(result):
            item, warning = result
            if warning:
                self.item_id = item["id"]
                self.baseline = self.snapshot()
                self.heading.configure(text=f"Salvato · ID {self.item_id}")
                self.app.status.set(f"Salvato ID {self.item_id}. Rilettura non riuscita: riapri dall'elenco.")
            else:
                self.populate(item)
                self.app.status.set(f"Salvato ID {self.item_id}. {self.item_link}")

        self.app.run(action, done)

    def trash(self):
        if not self.app.require_client() or self.item_id is None:
            return
        if not messagebox.askyesno("Cestino", f"Spostare nel cestino il contenuto ID {self.item_id}?"):
            return
        item_id = self.item_id

        def done(_):
            self.baseline = self.snapshot()
            self.new()
            self.refresh()

        self.app.run(lambda: self.app.client.trash(self.resource, item_id), done)

    def import_html(self):
        path = filedialog.askopenfilename(filetypes=[("HTML e testo", "*.html *.htm *.txt"), ("Tutti i file", "*.*")])
        if path:
            try:
                from pathlib import Path
                content = Path(path).read_text(encoding="utf-8-sig")
                self.content.delete("1.0", "end")
                self.content.insert("1.0", content)
            except Exception as exc:
                messagebox.showerror("File", str(exc))

    def copy_url(self):
        if self.item_link:
            self.app.clipboard_clear()
            self.app.clipboard_append(self.item_link)
            self.app.status.set(f"URL copiato: {self.item_link}")

    def open_browser(self):
        if self.item_link.startswith("https://"):
            webbrowser.open(self.item_link)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
