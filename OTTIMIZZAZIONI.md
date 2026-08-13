# Ottimizzazioni — skin Arctic Fuse 3 + Fen Light

Registro del lavoro di alleggerimento. Il dispositivo di riferimento è uno **Xiaomi Mi TV Stick**:
è il più debole del parco ed è lo standard su cui misurare tutto. Se gira bene lì, gira ovunque.

## Sintomi di partenza (test sul Mi Stick)

Tutto funziona e non crasha, ma:

- landscape, clearlogo e sfondo sfocato **molto lenti** al primo caricamento;
- la **paginazione nei widget della home non funziona** (sembra andare in timeout);
- in cerca la paginazione **funziona**;
- dopo molte pagine **crasha**: spariscono le pagine successive alla prima e riparte da capo;
- dopo il primo caricamento le immagini arrivano da locale e sono veloci, ma **a ogni riavvio di Kodi
  si torna da capo**.

---

## Le 18 inefficienze individuate

Numerazione stabile: viene citata nei commenti al codice e nei messaggi di commit.

### A. Costruzione delle liste

| # | Problema | Dove | Gravità | Stato |
|---|---|---|---|---|
| 1 | `UpdateLibrary` globale: paginare un widget li ricostruisce tutti | `service.py:242` | critico | da fare |
| 2 | Ricostruzione cumulativa: pagina N rifà le pagine 1..N, costo quadratico | `movies.py:82` | critico | da fare |
| 3 | `reuselanguageinvoker=false`: interprete Python nuovo a ogni build | `addon.xml:17` | critico | da fare |
| 4 | `except: pass` cieco: una build fallita chiude la directory vuota, in silenzio | `movies.py:151` | bloccante per la diagnosi | ✅ fatto |
| 5 | Cache meta dentro le proprietà di finestra: crescita illimitata | `meta_cache.py:96-117` | critico | ✅ fatto |
| 6 | Payload TMDb gonfio (`translations`, `images`, `alternative_titles`) | `tmdb_api.py:12-13` | alto | ⚠️ vedi nota |
| 7 | Cast completo (100+ voci) salvato nel blob | `metadata.py:319` | alto | ✅ fatto |
| 8 | `setCast` su ogni riga dei widget | `movies.py:228` | alto | ✅ risolto da #7 |
| 9 | Filtro doppiaggio rieseguito su tutte le pagine a ogni build | `movies.py:289` | medio | cade con #2 |
| 10 | Log di diagnostica della paginazione sempre attivo | `paginator.py:63` | basso | ✅ fatto |

### B. Sfondo sfocato e immagini

| # | Problema | Dove | Gravità | Stato |
|---|---|---|---|---|
| 11 | La potatura della cache gira **una sola volta**, all'avvio del servizio | `blur_service.py:155` | alto | da fare |
| 12 | Sfratto FIFO e non LRU: butta via per prime le immagini **più riusate** | `blur_service.py:117` | alto | da fare |
| 13 | Tetto di 200 file, ma ogni sfondo produce 3 file → ~66 sfondi reali | `blur_service.py:15` | alto | da fare |
| 14 | La potatura non conosce i gruppi: invalidazione parziale → ricalcolo totale | `blur_service.py:81` | alto | da fare |
| 15 | `_local_copy` chiamata due volte, con una query JSON-RPC dentro | `blur_service.py:201,206` | medio | da fare |
| 16 | Download HTTP sincrono nel ciclo del servizio (timeout 10s bloccante) | `blur_service.py:49` | medio | da fare |

### C. Servizi in polling

| # | Problema | Dove | Gravità | Stato |
|---|---|---|---|---|
| 17 | ~110 chiamate all'API di Kodi al secondo, anche a schermo fermo | `service.py:169`, `blur_service.py:156` | medio | da fare |
| 18 | Il blur risolve poster e label a ogni giro anche se nulla è cambiato | `blur_service.py:181-186` | basso | da fare |

---

## Due equivoci chiariti in partenza

**Le foto del cast non venivano scaricate.** Al momento della costruzione della lista vengono salvati
solo gli URL; le immagini le scarica Kodi solo se qualcosa le mostra. Il costo del cast era reale ma
stava in tre punti diversi — dimensione del payload, dimensione del blob in cache, `setCast` per riga —
e il rimedio giusto era limitare il numero di voci, non evitare un download che non avveniva.

**Le proprietà di finestra avevano un motivo, ed è caduto.** Ogni build del widget è un processo Python
nuovo (#3), quindi un dizionario in memoria non sopravviverebbe: le proprietà di `Window(10000)` erano
l'unica memoria condivisa. Ma **SQLite sopravvive ugualmente**, ed è già servito dalla cache di pagina
del sistema. La scelta era obbligata solo in apparenza.

---

## Ordine di lavorazione

1. **#4** — diagnostica. Non velocizza nulla, ma finché i fallimenti sono silenziosi ogni misura
   successiva è cieca. Va per primo, sempre.
2. **#10, #7, #8, #5** — alleggerire il primo caricamento. Contenuti nel plugin, rischio basso,
   effetto su *ogni* build indipendentemente dal resto.
3. **#11-14** (poi #15, #16) — cache del blur. Autocontenuti in un file, effetto immediatamente
   visibile.
4. **#2, #1** — architettura della paginazione. Rischio più alto, richiede attenzione dedicata.
5. **#3** — `reuselanguageinvoker`. Il guadagno più grosso e l'unico che può rompere cose in modo
   non ovvio: da solo, con un test dedicato.
6. **#17, #18** — polling. Ottimizzazioni vere ma marginali rispetto alle precedenti.

---

# Lotto 1 — diagnostica e peso del primo caricamento

Stato: **completato**, da provare sul Mi Stick.

## #4 — I fallimenti di build non sono più silenziosi

`indexers/movies.py`, `indexers/tvshows.py`

L'intero corpo di `fetch_list` era avvolto in un `try` che finiva con `except: pass`. Qualunque
fallimento — timeout, memoria esaurita, un campo mancante — produceva lo stesso risultato: `add_items`
non veniva mai chiamato e la directory si chiudeva **vuota**, senza una riga di log. Il container
tornava a ricostruirsi da capo.

**È il meccanismo esatto dietro "spariscono le pagine successive alla 1 e prova a ricaricarle da capo".**

Ora l'eccezione viene loggata con il traceback completo e il nome dell'azione. In `tvshows.py` il
`logger` era commentato: riattivato.

## #10 — Log della paginazione spento

`modules/paginator.py`: `PG_DEBUG` da `True` a `False`. Scriveva su log a ogni build e a ogni pagina
caricata, sulla flash lenta dello stick. Da riaccendere solo quando si indaga sulla paginazione.

## #7 e #8 — Il cast non si porta più dietro 100 persone

`modules/metadata.py`: nuova costante `CAST_LIMIT = 20`, applicata alla costruzione del cast sia per i
film sia per le serie.

TMDb restituisce il cast **completo**. Per un film importante sono oltre 100 voci, ognuna con nome,
ruolo, id e URL immagine: la fetta maggiore del blob di metadati. Quel blob finiva in cache e poi in
`setCast()` su **ogni riga** dei widget — con 200 elementi caricati sono decine di migliaia di oggetti
attore creati lato Kodi per mostrarne sei sullo schermo.

Nessuna interfaccia della skin ne mostra più di una ventina. Limitare a 20 risolve #7 e #8 insieme,
senza toccare il pannello attori della scheda info, che continua a essere alimentato dalla listitem.

## #5 — Via lo strato di cache nelle proprietà di finestra

`caches/meta_cache.py`

Il metadato completo di ogni titolo veniva serializzato in JSON e messo in una proprietà di
`Window(10000)`. Nessun limite e nessuno sfratto: cresceva finché Kodi non veniva chiuso. Su un
dispositivo da 1 GB, poche centinaia di titoli sfogliati diventano megabyte di stringhe dentro il
processo di Kodi — il candidato più probabile per i crash dopo molte pagine.

In più costava, per **ogni elemento a ogni ricostruzione**, un `getProperty` e — sui cache miss — un
`json.dumps` seguito da un `setProperty` dello stesso blob appena letto da disco.

Rimosso da `get`/`get_season`/`set`/`set_season`: la lettura passa direttamente da SQLite, che è in
modalità WAL con connessione riusata per thread, quindi già servito dalla cache di pagina del sistema.
I metodi `delete_memory_cache*` restano: ripuliscono le proprietà lasciate dalle sessioni precedenti.

## Nota su #6, rinviato con motivo

Ridurre `append_to_response` sembrava ovvio, ma i tre campi pesanti **sono usati**:

- `images` serve a scegliere poster, fanart, clearlogo e landscape (`metadata.py:266,430`);
- `alternative_titles` e `translations` alimentano gli alias usati dallo **scraping**
  (`source_utils.py:86-91`) — toglierli peggiorerebbe la ricerca delle fonti;
- `all_trailers` serve alla finestra extra.

La strada giusta non è tagliare la richiesta, che è **una sola per titolo e viene messa in cache in
SQLite a lungo**, ma separare il blob che serve alla lista da quello che serve a scheda info e
riproduzione. Con #7 fatto, il grosso del peso è già andato via. Da riprendere dopo #3, che rende
possibile una cache in memoria vera.

## Trappola incontrata: fine riga

I sorgenti Python di Fen Light usano **CRLF**. I primi script di modifica li hanno riscritti in LF,
producendo un diff di 1500 righe su modifiche da 20. Ripristinati.

**Regola per le modifiche successive:** dopo ogni riscrittura via script, controllare
`git diff --numstat` — se il numero di righe non somiglia a quello che si è cambiato davvero, è quasi
sempre questo. La skin usa LF, il plugin CRLF.

## Cosa verificare

1. **Che tutto funzioni ancora come prima**: home, widget, cerca, apertura scheda info, riproduzione.
   Questo lotto non cambia comportamenti, solo il peso.
2. **Il pannello attori** nella scheda info: deve mostrare gli attori come prima (fino a 20).
3. **Il log**: cercare `FenLight BUILD FALLITA`. Se compare, abbiamo finalmente il motivo per cui le
   pagine sparivano — ed è l'informazione più preziosa di tutto il lotto.
4. **La paginazione**: probabilmente ancora non funziona in home (serve #1), ma il crash dopo molte
   pagine potrebbe già essere sparito o rimandato molto più in là.

> **Il beneficio pieno di #7 arriva solo sui titoli nuovi.** Le voci già in cache mantengono il cast
> completo finché non scadono. Per misurare davvero, svuotare la cache dei metadati dalle impostazioni
> di Fen Light prima del test.
