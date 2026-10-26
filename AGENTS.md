# Gestione del sito della parrocchia

Questo progetto fornisce un client per https://parrocchiamoretta.altervista.org.

- Usare `.venv/Scripts/python.exe -m moretta` dalla cartella del progetto.
- Prima delle operazioni sul sito, eseguire `check`. Le credenziali sono nel portachiavi del sistema oppure in WP_URL, WP_USERNAME e WP_APP_PASSWORD. Non stamparle e non scriverle in file o comandi.
- Per le operazioni disponibili e gli esempi leggere README.md. `--help` mostra i parametri; `schema RESOURCE` legge i campi supportati dal sito.
- Gli output sono JSON. Per testi lunghi creare un file JSON UTF-8 in `.local/` e usare `--file`, evitando problemi di quoting.
- I nuovi articoli e gli eventi sono bozze salvo richiesta esplicita di pubblicazione da parte dell'utente. Non creare contenuti di prova sul sito pubblico senza richiesta.
- Per una modifica leggere prima `get RESOURCE ID --edit`, conservare il testo originale e aggiornare solo i campi necessari. Gli eventi usano The Events Calendar, non semplici post WordPress.
- Dopo una scrittura verificare il risultato con `get`. Se c'è un timeout verificare l'elenco prima di riprovare, per evitare duplicati.
- I media si caricano con `upload`; usare l'ID restituito per `featured_media` negli articoli e `image` negli eventi. Usare `source_url` per immagini e documenti dentro l'HTML.
- Non cancellare definitivamente contenuti o media. Il comando `trash` sposta articoli/eventi nel cestino.
- Test locali: `.venv/Scripts/python.exe -m unittest discover -s tests -v`.
