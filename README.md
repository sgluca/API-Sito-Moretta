# Gestione sito Parrocchia Moretta

Interfaccia desktop in italiano, client Python e comandi JSON per gestire **articoli, eventi The Events Calendar e media** su https://parrocchiamoretta.altervista.org. Usa le REST API già presenti: non richiede un plugin personalizzato.

## Avvio

1. Aprire **Avvia.cmd** con doppio clic. Al primo avvio installa le dipendenze in `.venv` se necessario. Serve Python 3.11 o successivo con Tkinter.
2. In WordPress aprire **Utenti → Profilo → Password per le applicazioni** e crearne una chiamata, ad esempio, “Gestione Moretta”.
3. Nella scheda **Collegamento** inserire utente e password per applicazioni, poi premere **Collega e verifica**.

La password rimane nel portachiavi di Windows (tramite `keyring`); `.local/config.json` contiene solo sito e utente. Non usare la password ordinaria di accesso. L'utente deve avere i permessi per modificare articoli/eventi e caricare file. Si può revocare la password da WordPress.

## Finestra desktop

- **Articoli / Eventi**: cercare, filtrare per stato, sfogliare le pagine e aprire un elemento con doppio clic. **Nuovo** prepara una bozza. Il contenuto è HTML o markup dei blocchi WordPress; si può importare da un file UTF-8. Non è un editor visuale Gutenberg.
- **Salva modifiche / crea** conserva lo stato selezionato. Scegliere `publish` per pubblicare; l'interfaccia chiede conferma. `draft` indica una bozza, `pending` una revisione, `private` un contenuto privato. Per programmare una pubblicazione con `future`, usare la CLI specificando anche `date`.
- **Eventi**: date locali `YYYY-MM-DD HH:MM:SS`, fuso `Europe/Rome`, tutto il giorno, luogo/organizzatori, costo, sito, categorie, tag e immagine. I luoghi e gli organizzatori si richiamano per ID esistenti. Non gestisce serie ricorrenti di Events Calendar Pro.
- **Media**: **Nuovo media**, compilare titolo/testo alternativo/didascalia e premere **Salva modifiche / crea** per scegliere il file. Dopo il caricamento l'ID è visibile e **Copia URL** copia l'indirizzo. Si possono modificare i metadati dei file esistenti.
- Incollare l'ID del media nel campo immagine dell'articolo/evento. Per inserirlo nel corpo usare ad esempio `<img src="URL" alt="Descrizione">` oppure un collegamento al PDF.
- Il cestino riguarda articoli ed eventi. I media non vengono eliminati da questo programma.

## Comandi richiamabili dall'assistente

Eseguire nella cartella del progetto. Le risposte sono JSON su stdout; gli errori JSON su stderr e codice di uscita 1. Le credenziali configurate dalla finestra sono condivise con la CLI, quindi l'assistente può usarle senza leggerle nella conversazione.

```powershell
# Configurazione alternativa, password richiesta in modo nascosto
.\.venv\Scripts\python.exe -m moretta configure --username nomeutente

# Verifica collegamento
.\.venv\Scripts\python.exe -m moretta check

# Elenchi e ricerca (20 elementi, prima pagina)
.\.venv\Scripts\python.exe -m moretta list posts --data '{"status":"any","per_page":20,"page":1}'
.\.venv\Scripts\python.exe -m moretta list events --data '{"status":"draft","per_page":20}'
.\.venv\Scripts\python.exe -m moretta list media --data '{"search":"locandina"}'
.\.venv\Scripts\python.exe -m moretta list categories
.\.venv\Scripts\python.exe -m moretta list event-categories
.\.venv\Scripts\python.exe -m moretta list venues
.\.venv\Scripts\python.exe -m moretta list organizers

# Leggere l'originale prima di modificarlo
.\.venv\Scripts\python.exe -m moretta get posts 123 --edit
.\.venv\Scripts\python.exe -m moretta get events 456 --edit

# Nuove bozze dai file di esempio
.\.venv\Scripts\python.exe -m moretta create posts --file esempi/articolo.json
.\.venv\Scripts\python.exe -m moretta create events --file esempi/evento.json

# Modifica parziale / pubblicazione esplicita
.\.venv\Scripts\python.exe -m moretta update posts 123 --data '{"title":"Nuovo titolo"}'
.\.venv\Scripts\python.exe -m moretta update events 456 --data '{"status":"publish"}'

# Caricare una locandina e collegare l'ID ottenuto
.\.venv\Scripts\python.exe -m moretta upload "C:\Immagini\locandina.jpg" --title "Locandina" --alt-text "Programma dell’incontro"
.\.venv\Scripts\python.exe -m moretta update posts 123 --data '{"featured_media":789}'
.\.venv\Scripts\python.exe -m moretta update events 456 --data '{"image":789}'
.\.venv\Scripts\python.exe -m moretta update media 789 --data '{"caption":"Incontro in parrocchia"}'

# Categorie e tag
.\.venv\Scripts\python.exe -m moretta create categories --data '{"name":"Vita parrocchiale"}'
.\.venv\Scripts\python.exe -m moretta create event-categories --data '{"name":"Incontri"}'
.\.venv\Scripts\python.exe -m moretta create tags --data '{"name":"Giovani"}'

# Cestino e campi supportati dal sito
.\.venv\Scripts\python.exe -m moretta trash posts 123
.\.venv\Scripts\python.exe -m moretta schema events
```

Con Windows PowerShell 5, per JSON complessi usare sempre `--file` al posto di `--data`: il passaggio delle virgolette agli eseguibili può variare. Gli ID sono esempi: usare quelli restituiti dal sito. Le liste sono paginate: aumentare `page`; la risposta TEC include `total` e `total_pages`, mentre WordPress restituisce l'array della pagina richiesta (massimo 100 elementi per pagina).

Per eventi già trascorsi specificare filtri `start_date` / `end_date` nell'elenco: il calendario può mostrare per impostazione predefinita solo gli eventi futuri. Per pubblicazioni programmate inviare `status: "future"` e `date` nel fuso del sito; WordPress usa WP-Cron per pubblicarle.

## Uso Python

```python
from moretta import WordPressClient

client = WordPressClient.from_config()
media = client.upload_media("locandina.jpg", title="Locandina", alt_text="Programma")
articolo = client.create_post("Incontro in parrocchia", "<p>Vi aspettiamo!</p>",
                             featured_media=media["id"])
evento = client.create_event("Incontro", "2026-12-01 20:30:00", "2026-12-01 22:00:00",
                            description="<p>Vi aspettiamo!</p>", image=media["id"])
client.update_event(evento["id"], title="Titolo aggiornato")
```

In alternativa al portachiavi si possono impostare `WP_URL`, `WP_USERNAME`, `WP_APP_PASSWORD` nell'ambiente del processo. Nessun `.env` viene caricato automaticamente. Il client richiede HTTPS, verifica i certificati, non segue reindirizzamenti e non ritenta automaticamente le scritture. Un timeout può arrivare dopo il salvataggio sul sito: controllare l'elenco prima di ripetere.

La verifica del collegamento è di sola lettura e non garantisce i permessi di pubblicazione o upload; vengono valutati dal server sulla singola operazione. Firewall, limiti upload e filtri HTML dipendono da WordPress/Altervista. Non sono gestite le ricorrenze Pro né l'amministrazione di plugin o utenti.

## Sviluppo e test

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

I test simulano il server: non creano contenuti sul sito. `AGENTS.md` contiene le istruzioni operative per l'assistente.

Riferimenti: [WordPress: autenticazione](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/), [WordPress: media](https://developer.wordpress.org/rest-api/reference/media/), [The Events Calendar: REST API](https://dev.theeventscalendar.com/knowledgebase/introduction-to-the-events-calendar-rest-api/).
