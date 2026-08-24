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
| 1 | `UpdateLibrary` globale: paginare un widget li ricostruisce tutti | `service.py:242` | critico | ✅ fatto |
| 2 | Ricostruzione cumulativa: pagina N rifà le pagine 1..N, costo quadratico | `movies.py:82` | critico | da fare |
| 3 | `reuselanguageinvoker=false`: interprete Python nuovo a ogni build | `addon.xml:17` | critico | da fare |
| 4 | `except: pass` cieco: una build fallita chiude la directory vuota, in silenzio | `movies.py:151` | bloccante per la diagnosi | ✅ fatto |
| 5 | Cache meta dentro le proprietà di finestra: crescita illimitata | `meta_cache.py:96-117` | critico | ✅ fatto |
| 6 | Payload TMDb gonfio (`translations`, `images`, `alternative_titles`) | `tmdb_api.py:12-13` | alto | ⚠️ vedi nota |
| 7 | Cast completo (100+ voci) salvato nel blob | `metadata.py:319` | alto | ✅ fatto |
| 8 | `setCast` su ogni riga dei widget | `movies.py:228` | alto | ✅ risolto da #7 |
| 9 | Filtro doppiaggio rieseguito su tutte le pagine a ogni build | `movies.py:289` | medio | cade con #2 |
| 10 | Log di diagnostica della paginazione sempre attivo | `paginator.py:63` | basso | ✅ fatto |
| 21 | Tornando dalla riproduzione la pagina caricata sparisce e la selezione salta | `kodi_utils.py:277` | basso | ✅ atteso da #1 |
| 20 | Menu contestuale dei film: 16 voci costruite per ogni elemento | `movies.py:193-224` | alto | ✅ fatto |
| 19 | `stuck_timeout=8` toglieva il flag `LOADING` a build ancora in corso → collasso alla prima pagina | `service.py:162` | **era la causa del blocco** | ✅ fatto |

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

---

# Lotto 2 — trovata la causa vera del blocco della paginazione

Stato: **completato**, da provare sul Mi Stick.

Il log del primo test (Xiaomi MiTV-AESP0, Android 9, Mali-450, Kodi 21.1) ha chiuso la questione.
Non serviva indovinare: c'era tutto scritto.

## Cosa dice il log

**1. Nessun `FenLight BUILD FALLITA`.** Le build non esplodono. Il collasso alla prima pagina non è
un'eccezione: è una decisione presa dal codice.

**2. I trigger di paginazione si vedono tutti.** Ogni `UpdateLibrary(video,special://skin/foo)` lascia
la traccia `VideoInfoScanner: Starting scan .. / Process directory 'special://skin/foo' does not exist`.
Otto occorrenze:

| Ora | Contesto | Distanza dalla precedente |
|---|---|---|
| 18:15:07 | home | — |
| 18:16:46 | cerca | — |
| 18:16:52 | cerca | 6,3 s |
| 18:16:59 | cerca | 7,2 s |
| 18:17:07 | cerca | 8,1 s |
| 18:17:21 | cerca | 13,6 s |
| 18:17:27 | cerca | 6,7 s |
| 18:17:35 | cerca | 7,4 s |

Poi più nulla.

**3. Quella cadenza di 6-8 secondi non è l'utente che scorre. È un timeout.**

## Il meccanismo

`service.py` aveva `stuck_timeout = 8`: il watcher considera morta una build che non finisce entro
8 secondi e le toglie il flag `LOADING`.

Ma quel flag è anche il segnale che la build legge, all'inizio, per decidere **quante pagine
ricostruire** (`paginator.get_pages`): con `LOADING` alzato ricostruisce tutte le pagine accumulate,
senza ricade sul lotto iniziale — perché l'assenza del flag significa "apertura pulita del widget".

La sequenza sul Mi Stick:

1. il watcher alza `LOADING` e spara `UpdateLibrary`;
2. l'evento è **globale**: tutti i widget si ricaricano, e ognuno apre un **interprete Python nuovo**
   (#3). Sullo stick le invocazioni si accodano;
3. la build del widget che ci interessa è in fondo alla coda e **parte dopo più di 8 secondi**;
4. nel frattempo il watcher ha già tolto `LOADING`;
5. la build legge `get_pages()`, non trova il flag, conclude "apertura pulita" e ricostruisce **il
   lotto iniziale**;
6. il widget resta identico — o torna alla prima pagina se era già cresciuto.

Da qui, tutti e tre i sintomi, con la stessa causa:

- **in home non pagina mai**: più widget in coda, la build parte sempre oltre gli 8 s;
- **in cerca funziona per qualche pagina**: meno widget, la build parte in tempo — finché la
  ricostruzione cumulativa (#2) non si allunga abbastanza da sforare;
- **su Mac funziona tutto**: le build partono entro 8 s e il timeout non scatta mai.

Non era un timeout di rete e non era un crash: era una condizione di corsa fra il servizio e il
plugin, che su hardware lento si perde sistematicamente.

## Correzioni applicate

**`stuck_timeout` da 8 a 90 secondi.** Il valore originale era più corto della durata reale di una
build sul dispositivo di riferimento. Commentato nel codice perché non venga riabbassato senza misurare.

**Il flag `LOADING` ora contiene il timestamp di partenza** invece della stringa `'true'`
(`paginator.is_loading()` / `paginator.loading_started()`, aggiornati anche `router.py` e `service.py`).
Prima il momento di partenza stava solo nel dizionario in memoria del servizio: se il servizio
ripartiva a metà build, quel flag non si sarebbe sbloccato **mai più** e il widget sarebbe rimasto
muto per sempre.

**Lo sblocco di emergenza ora si logga sempre**, non più dietro `PG_DEBUG`. È un evento raro e
diagnostico: se ricompare vuol dire che le build superano i 90 secondi, cioè un problema diverso e
peggiore.

**Bonus dal log**: `ExecuteAsync - Not executing non-existing script plugin.video.themoviedb.helper`
all'avvio. Era il blur dello sfondo semplice in `skinvariables-startup.json`, rimasto puntato
sull'addon rimosso. Riscritto su `plugin://plugin.video.fenlight/?mode=fen_blur`.

## Onestà sul risultato

**Questa è una mitigazione, non la cura.** Rimuove il collasso, quindi la paginazione dovrebbe
finalmente avanzare anche in home — ma ogni passo resterà lento, perché la causa a monte è intatta:
un widget da paginare ne fa ricostruire sei (#1), e ognuno ricostruisce anche tutte le pagine
precedenti (#2). La cura è quella, e viene subito dopo.

**Un errore mio da segnalare**: ho spento `PG_DEBUG` (#10) *prima* di questo test, e così ho perso la
traccia diretta della paginazione proprio nella sessione in cui serviva. La diagnosi è arrivata lo
stesso, per via indiretta, dalle tracce del `VideoInfoScanner`. Al posto del log verboso ho lasciato
la singola riga sullo sblocco di emergenza, che dà lo stesso segnale a costo quasi nullo.

## Cosa verificare

1. **In home**: scorri un widget fino in fondo. Ora dovrebbe **caricare la pagina successiva**. Sarà
   lento — vedrai ancora tutti i widget aggiornarsi — ma deve avanzare e **non tornare più alla prima
   pagina**.
2. **In cerca**: scorri per molte pagine di seguito. Non deve più azzerarsi dopo qualche pagina.
3. **Nel log** cerca `WidgetPaginator: build ferma da oltre 90s`. Se **non** compare, la corsa è
   chiusa. Se compare, le build superano il minuto e mezzo e il problema si sposta sul peso.
4. **All'avvio**: `Not executing non-existing script plugin.video.themoviedb.helper` non deve più
   comparire.
5. Lo sfondo sfocato deve funzionare come prima.

---

# Lotto 3 — menu contestuale dei film

Stato: **completato**, da provare. Riguarda **solo i film**: serie, stagioni ed episodi restano
com'erano.

Le voci del menu contestuale non vengono costruite quando si apre il menu: vengono costruite per
**ogni elemento della lista, a ogni ricostruzione**, che è il costo di cui si parlava. Erano 16.

## Refresh Widgets contro Reload Widgets

Erano due voci vicine e la differenza non si capiva. È questa:

- **Reload Widgets** (`kodi_refresh`) ricostruisce i widget. I dati arrivano dalla cache, quindi le
  liste restano identiche: è un ridisegno.
- **Refresh Widgets** (`refresh_widgets`) alza prima `fenlight.refresh_widgets` e lo tiene per ~5
  secondi. Quel flag lo legge `random_lists.py`, che in sua presenza **rigenera una selezione nuova**
  invece di riusare quella in cache. Poi chiama comunque `kodi_refresh`.

**Refresh è il superset di Reload.** Tenuto solo Refresh, rinominato *Aggiorna widget*.

## Il menu oggi

| Voce | Nota |
|---|---|
| Riproduci | solo quando il clic sull'elemento apre gli extra |
| Opzioni di riproduzione | |
| Segna come visto / Segna come non visto | rinominate, si escludono a vicenda |
| Aggiungi alla watchlist / Rimuovi dalla watchlist | **nuova**, sostituisce il gestore liste |
| Azzera avanzamento | solo se c'è un avanzamento |
| Aggiorna widget / Esci dalla lista | l'una o l'altra secondo il contesto |

Rimosse: *Extras*, *Options*, *Browse Movie Set*, *Browse Recommended*, *Browse More Like This*,
*In Trakt Lists*, *Trakt Lists Manager*, *Favorites Manager*, *Reload Widgets*.

Da 17 `build_url` e 16 voci a 12 e 8 nel sorgente; a runtime, per elemento, da ~14 voci costruite a
circa 5.

## La watchlist

Nuove funzioni in `apis/trakt_api.py`:

- `watchlist_tmdb_ids(media_type)` — insieme dei tmdb_id già in watchlist. Letto **una volta per
  costruzione di lista**, come `watched_info` e `bookmarks`, non una volta per elemento: passa da
  `cache_trakt_object`, quindi è una lettura da SQLite senza rete.
- `watchlist_toggle(params)` — aggiunge o rimuove secondo lo stato, raggiungibile come
  `mode=trakt.watchlist_toggle`.

Due scelte deliberate:

**Nessun `kodi_refresh` dopo il toggle.** Un refresh globale ricostruirebbe tutti i widget (#1) per
aggiornare una sola etichetta. La cache Trakt viene invalidata e la voce si aggiorna alla prossima
ricostruzione naturale; la notifica conferma subito l'azione.

**Import pigro di `trakt_api` dentro `worker()`.** In cima al modulo avrebbe caricato `requests` e
tutta la catena Trakt a ogni costruzione di lista anche senza Trakt attivo — e con
`reuselanguageinvoker=false` si paga davvero ogni volta.

## Cosa NON è stato rimosso, e perché

`extras_params`, `options_params` e `more_like_this_params` continuano a essere calcolati e messi
come proprietà della listitem: **`custom_keys.py` li legge da lì** per i tasti rapidi. Toglierli
avrebbe rotto le scorciatoie da tastiera senza che il menu c'entrasse.

Di conseguenza *Extras*, *Opzioni* e *Simili a questo* restano raggiungibili da tasto rapido anche se
non sono più nel menu. Vale la pena saperlo perché dentro **Opzioni** vivono cose che ogni tanto
servono: *Auto Play*, *Limite qualità*, *Abilita scraper* e soprattutto **Re-Cache Info**, l'unico
modo per rigenerare i metadati di un titolo sbagliato.

## Cosa verificare

1. Menu contestuale su un film: devono comparire solo le voci della tabella, in italiano.
2. **Segna come visto** su un film non visto: la voce deve cambiare in *Segna come non visto* dopo
   l'aggiornamento del widget.
3. **Aggiungi alla watchlist**: notifica di conferma, e il film deve comparire su Trakt. Riaprendo il
   menu dopo un aggiornamento del widget la voce deve dire *Rimuovi dalla watchlist*.
4. **Rimuovi dalla watchlist** sullo stesso film: deve sparire da Trakt.
5. Su un film mai iniziato *Azzera avanzamento* non deve comparire; su uno a metà sì.
6. Le liste di **serie** devono avere il menu di prima, invariato.
7. Se usa i tasti rapidi per extra/opzioni, devono funzionare ancora.

---

# Lotto 4 — misura e prova sul menu nativo

Stato: **due strumenti di prova**, non ottimizzazioni. Servono a smettere di andare a stime.

## Rimessa la voce Opzioni

Rientra nel menu contestuale dei film. Dentro ci sono *Auto Play*, *Limite qualità*,
*Abilita scraper* e **Re-Cache Info**, che è l'unico modo per rigenerare i metadati di un titolo
venuto male: era l'unica cosa davvero irrecuperabile fra quelle tolte.

## Il cronometro sulla costruzione

`modules/paginator.py`: `PERF`, `now()`, `log_build()`. Agganciato in `indexers/movies.py`.

Una riga di log per costruzione di lista, che separa le due metà del tempo:

```
FenLight PERF: movies tmdb_movies_popular | 120 elementi | 6 pagine |
               totale 4.31s = risoluzione 0.42s + costruzione 3.89s | 32.4 ms/elemento
```

- **risoluzione** — pagine TMDb, filtri, id. Dopo il primo giro è quasi tutta cache.
- **costruzione** — una listitem per elemento: menu contestuale, info tag, artwork. È la parte
  incomprimibile *per ricostruzione*, quella che il costo quadratico moltiplica.

Il `ms/elemento` è il numero che conta: fissa il costo unitario e dice quanto vale davvero ogni
alleggerimento della singola riga.

**Da togliere quando le ottimizzazioni sono chiuse** (`PERF = False`).

### Perché serviva

Il guadagno del lotto 3 l'ho **stimato** al 5-12%, non misurato. Con questa riga la prossima stima
non serve: si legge.

## Prova su `replaceItems`

*Riproduci successivo*, *Accoda elemento*, *Segna come già visto*, *Aggiungi ai preferiti* **non sono
della skin**. `Dialog_DialogContextMenu.xml` non ne definisce nessuna: il controllo `996` è la lista
nativa di Kodi e la skin disegna quello che il core ci mette dentro. Una skin non può toglierle.

L'unica leva è dal lato addon: il secondo parametro di `addContextMenuItems`, che storicamente
sostituiva del tutto il menu predefinito. Non è certo che Kodi 21 lo rispetti ancora.

`indexers/movies.py` ha ora `set_context_menu()`:

- prova `addContextMenuItems(cm, True)`;
- se la firma non accetta più il parametro, intercetta il `TypeError`, ricade sulla chiamata normale
  e lo scrive nel log **una volta sola**.

La rete di sicurezza non è un dettaglio: senza, quell'eccezione sarebbe finita nell'`except` cieco di
`build_movie_content` e avrebbe fatto sparire **ogni elemento** da tutte le liste dei film.

### Attenzione: è tutto-o-niente

Se funziona spariscono le quattro voci volute, ma **anche *Informazioni***. La scheda info resta
raggiungibile dal tasto Info, che è come la si apre normalmente — ma va saputo prima.

## Cosa verificare

1. **Menu contestuale su un film.** Tre esiti possibili:
   - restano solo le voci di Fen Light → `replaceItems` funziona, si può estendere a serie ed episodi;
   - le quattro voci native ci sono ancora → il parametro è accettato ma ignorato, strada chiusa;
   - nel log compare `replaceItems non piu' supportato` → rimosso dall'API, strada chiusa.
2. **Che la voce *Opzioni* sia tornata** e apra il suo menu.
3. **Nel log, le righe `FenLight PERF`.** Servono tre misure:
   - un widget della home appena aperto (poche pagine);
   - lo stesso widget dopo aver paginato parecchio (molti elementi);
   - una ricerca.

   Il confronto fra il primo e il secondo dà la curva del costo quadratico, e il `ms/elemento` dice
   quanto pesa davvero la singola riga.
4. Che tutto il resto funzioni come prima: nulla qui cambia comportamenti.

---

# Lotto 5 — #1: ricarica mirata al posto dell'evento globale

Stato: **completato**, da provare sul Mi Stick. È l'intervento più grosso finora e tocca sia il
plugin sia la skin.

## Esito della prova su `replaceItems`

**Non funziona su Kodi 21.** Il parametro viene accettato (nessun `TypeError` nel log) ma ignorato: le
voci native restano. La prova è stata rimossa, il codice è tornato com'era. *Riproduci successivo*,
*Accoda elemento*, *Segna come già visto* e *Aggiungi ai preferiti* le mette il core di Kodi e da qui
non si tolgono. Chiuso.

Rimessa la voce **Opzioni** nel menu contestuale dei film.

## Prime misure

Da Mac, widget `trakt_watchlist`, 21 elementi: **0,3-0,5 ms/elemento**, totale 0,01 s.

Sono numeri di riferimento, non il caso che interessa: lista corta, lista personale (nessuna
risoluzione di rete, `risoluzione 0.00s`) e macchina veloce. Servono ancora le misure dal Mi Stick su
una lista lunga. Ma confermano l'ordine di grandezza della stima del lotto 3: se su Mac una riga costa
0,4 ms, su un Cortex-A53 costa qualche millisecondo, e la stima del 5-12% era plausibile.

## Il meccanismo

Il problema (#1) era che l'unico modo di far comparire la pagina nuova era
`UpdateLibrary(video,special://skin/foo)`: un evento **globale**, che ricarica ogni
`DirectoryProvider` della schermata. Per paginare un widget se ne ricostruivano sei, ognuno con il
suo interprete Python nuovo — ed era la coda di invocazioni che ne usciva a far scadere il flag
`LOADING` (#19).

Il precedente per farlo bene era già dentro la skin: **i widget di ricerca si ricaricano a ogni tasto**
perché il loro `<content>` contiene un `$VAR` dinamico. Kodi riesamina l'espressione del path e
ricarica *quel* contenitore. Bastava usare lo stesso meccanismo.

Ora il `<content>` di ogni widget finisce con:

```
$INFO[Window(Home).Property(fenlight.pg.ctl<id>.pages),&pages=,]
```

`$INFO[X,prefisso,suffisso]` emette il prefisso **solo se la proprietà non è vuota**. Quindi:

- widget mai paginato, o widget non-Fen Light: non viene aggiunto niente, il path è identico a prima;
- il watcher scrive `3` nella proprietà → il path diventa `...&pages=3` → **ricarica solo quel
  contenitore**.

## Il numero di pagine è diventato stato durevole

È la conseguenza più importante, e vale più della velocità.

Prima il conteggio viveva in un flag transitorio (`LOADING`) che una build lenta poteva perdere. Ora
**sta nel path**. Un path non scade e non si azzera: sopravvive a una build lenta, e sopravvive al
ritorno dalla riproduzione. Questo dovrebbe chiudere anche il difetto #21 senza averlo affrontato
direttamente.

`_VOLATILE_PARAMS` conteneva già `'pages'`, quindi la chiave del widget non cambia quando cambia il
numero di pagine: l'impianto era già predisposto.

## Le due insidie, e come sono chiuse

**Gli id dei contenitori si ripetono.** Nel file generato 502 e 503 compaiono due volte, in categorie
diverse. Un token indicizzato per id sarebbe stato ereditato dal widget sbagliato. Due difese:

1. il watcher registra in `fenlight.pg.ctl<id>.key` quale widget occupa quel contenitore e **azzera il
   token quando l'inquilino cambia** — vale anche per la ricerca, dove ogni query nuova è una chiave
   nuova;
2. `get_pages` non si fida del path: prende il **minore** fra il valore letto dal path e le pagine
   davvero accumulate da *questa* chiave. Se la chiave non ha storia, il token altrui viene ignorato
   senza nemmeno un transitorio.

**I widget non-Fen Light.** Un path di libreria (`videodb://`, `special://`) con un `&pages=3`
appiccicato sarebbe malformato. Non può succedere: il watcher scrive il token solo per contenitori che
ha già verificato essere di Fen Light, e senza token `$INFO[]` non emette nulla.

## File toccati

| File | Cosa |
|---|---|
| `modules/paginator.py` | `CTL_PAGES_PROP`, `CTL_KEY_PROP`, `get_pages(..., path_pages)` |
| `service.py` | token al posto di `UpdateLibrary`; azzeramento al cambio di inquilino |
| `indexers/movies.py`, `indexers/tvshows.py` | passano `?pages=` a `get_pages` |
| `generator/data/parts/widgets_row.xmltemplate` | token nel `<content>` |
| `generator/data/parts/search_row_standard.xmltemplate` | idem |
| `1080i/script-skinvariables-generator-includes-.xml` | 5 `<content>` già generati |
| `1080i/Includes_Hubs.xml` | 2 `<content>` dei widget hub |

Il token è stato messo **sia nei template sia nel file già generato**: nei template perché
sopravviva alla rigenerazione quando si modificano i widget, nel file generato perché funzioni subito
senza doverlo rigenerare.

## Cosa verificare

1. **La paginazione in home deve essere molto più veloce**, e soprattutto **gli altri widget non
   devono più aggiornarsi** quando se ne pagina uno. È il segnale visivo che dice se ha funzionato.
2. **Nel log non devono più comparire** le righe `VideoInfoScanner: Starting scan` con
   `special://skin/foo`: erano la firma dell'evento globale. Se ci sono ancora, il token non sta
   arrivando al path.
3. **Il ritorno dalla riproduzione**: apri un film da una pagina caricata dinamicamente e chiudilo. La
   pagina dovrebbe restare, e la selezione tornare sul film giusto (difetto #21).
4. **La ricerca**: deve paginare come prima e, cambiando query, ripartire da capo senza ereditare le
   pagine della ricerca precedente.
5. **I widget delle categorie con id ripetuti** (502, 503 compaiono due volte): passando da una
   categoria all'altra, il widget nuovo deve aprirsi corto, non già espanso.
6. Le righe `FenLight PERF` dal Mi Stick, su una lista lunga.

---

# Lotto 6 — correzione dopo il primo test di #1

## Cosa il log ha dimostrato

**La ricarica mirata funziona.** Fra le 19:21:02 e le 19:21:39 la ricerca discover ha paginato
**dieci volte di fila** — da 29 a 132 elementi — e in tutta quella finestra **non c'è una sola riga
`VideoInfoScanner`**. Prima ogni passo ne produceva una. L'evento globale non viene più usato per
paginare.

I tempi confermano anche dove sta il costo, e ribaltano un'assunzione:

| Pagine | Elementi | Risoluzione | Costruzione |
|---|---|---|---|
| 2 | 29 | 5,13 s | 0,02 s |
| 5 | 70 | 2,69 s | 0,02 s |
| 10 | 132 | 2,63 s | 0,06 s |

Sulla ricerca avanzata **la costruzione è irrilevante** (millisecondi): il tempo è tutto nella
risoluzione, cioè nel filtro IMDb che riqualifica ogni pagina TMDb. Il costo quadratico che temevo
sulla costruzione non si vede: cresce da 0,02 a 0,06 s. Le stime del lotto 3 valgono per i widget
normali, non per la ricerca avanzata, che ha un collo di bottiglia diverso e finora non misurato.

## Il difetto introdotto, e perché

```
19:20:54  GetDirectory - Error getting &pages=11
```

Avevo messo il token anche nelle righe di ricerca. Lì il path nasce da
`$VAR[Path_SearchTerm,...]`, che **non emette nulla se la casella di ricerca è vuota** — ma il token,
che dipende da un'altra condizione, veniva emesso lo stesso. Path risultante: `&pages=11`. Kodi prova
a risolverlo e fallisce.

Lo avevo previsto come rischio e l'ho accettato senza chiuderlo. Era il caso da chiudere.

## La cosa che non sapevo

**Le righe di ricerca usano lo stesso include `Widget_Row` e gli stessi id dei widget della home**
(502 e 503 compaiono in entrambi i contesti). Questo cambia due cose:

1. non si può distinguere ricerca e home a livello di include: la distinzione va fatta a runtime;
2. il token, indicizzato per id di contenitore, è **condiviso** fra un widget della home e uno della
   ricerca. Senza precauzioni una ricerca azzererebbe lo stato di paginazione di un widget della home.

## Correzioni

**Token tolto dalle righe di ricerca** (template e file generato). Il path della ricerca torna
esattamente com'era.

**Il watcher ora riconosce i contenitori tokenizzati** leggendo `Container(id).FolderPath`: se
contiene già `pages=`, quel contenitore ha il token nel suo `<content>`.

- **tokenizzato** → si scrive solo il token: ricarica mirata, nessun evento globale;
- **non tokenizzato** (ricerca, o primissima paginazione prima che il token compaia nel path) →
  si usa ancora `UpdateLibrary`. La vecchia strada resta solo dove la nuova non arriva.

**L'azzeramento al cambio di inquilino avviene solo sui contenitori tokenizzati**, così una ricerca
non tocca più lo stato di un widget della home con lo stesso id.

## Diagnostica aggiunta per il difetto sulla riproduzione

Non ho ancora la prova di cosa succeda al ritorno dalla riproduzione: nel log l'unico film è stato
avviato da un widget con **2 sole pagine**, cioè il lotto iniziale — non c'era nessuna pagina dinamica
da perdere. Il `VideoInfoScanner` delle 19:19:40 è il refresh globale che `player.py` fa a fine
riproduzione, ed è atteso.

La riga `FenLight PERF` ora riporta anche **`path_pages=`**, cioè il `?pages=` arrivato dal path del
widget. Alla prossima prova si legge direttamente:

- riproduzione avviata da un widget espanso, e al ritorno `path_pages=` mostra ancora quel numero
  → il token regge e il problema è altrove;
- `path_pages=-` → il token si è perso, e sappiamo dove guardare.

Meglio un dato che un'altra ipotesi.

## Cosa verificare

1. **La ricerca**: aprire la ricerca **a casella vuota** non deve più produrre
   `GetDirectory - Error getting &pages=...`. E la paginazione in ricerca deve funzionare come prima.
2. **Home**: paginare un widget non deve produrre `VideoInfoScanner` (a parte, eventualmente, il
   primo passo).
3. **Riproduzione**: far partire un film da un widget **paginato a lungo** (non dal lotto iniziale) e
   guardare `path_pages=` nella riga PERF che segue la chiusura.
4. **Home ↔ ricerca**: paginare un widget della home, andare in ricerca, tornare. Il widget della home
   non deve essere stato azzerato.

---

# Lotto 7 — la fonte vera del path malformato

## Cosa dice il log dal vivo

**La ricarica mirata regge.** Il nuovo campo `path_pages` lo dimostra: la ricerca discover ha paginato
da 34 a 103 elementi e a ogni passo il path portava il numero giusto — `path_pages=3`, poi `4`, `5`,
`6`. Lo stato **è** nel path e viene letto correttamente.

**Restano due difetti visibili.**

### 1. `GetDirectory - Error getting &pages=6` — non era dove pensavo

Nel lotto 6 avevo tolto il token dalle righe di ricerca credendo fosse quella la fonte. Non lo era, o
non solo. La fonte è `Includes_Hubs.xml`: i widget hub combinati ricevono il path come
`<param name="content">`, e per la ricerca quel parametro vale `$VAR[Path_SearchTerm,...]` — **vuoto a
casella vuota**. Il token invece veniva emesso lo stesso, perché la sua condizione è un'altra: che la
proprietà sia valorizzata da una paginazione precedente. Path risultante: `&pages=6`.

L'errore compariva **prima** che discover arrivasse a 6 pagine: quel `6` era il residuo di una
sessione precedente. Un dettaglio che conferma la diagnosi.

**Il criterio che avevo sbagliato**: la condizione di emissione del token deve essere *"il path di base
non è vuoto"*, non *"il token è valorizzato"*. Dove il path di base è un URL letterale le due coincidono;
dove nasce da un `$VAR` condizionale, no.

**Correzione**: il token resta **solo** sui `<content>` il cui path è un URL letterale che non può mai
essere vuoto — le tre righe dei widget della home e il loro template. Tolto da hub e ricerca, che
tornano al refresh globale tramite il fallback del lotto 6.

### 2. Doppia costruzione a ogni passo

Ogni paginazione produce **due** righe PERF identiche e un `VideoInfoScanner`. Due contenitori mostrano
la stessa lista: uno tokenizzato, l'altro no. Quello non tokenizzato fa scattare il fallback globale,
che ricostruisce anche il primo. Con la correzione qui sopra la ricerca resta interamente sul percorso
globale — coerente, ma da riprendere.

## Sul difetto della riproduzione: il log non lo contiene

Va detto chiaramente. In questa sessione c'è **una sola riproduzione**, alle 19:28:11, avviata dal
widget `trakt_watchlist`, che risulta `21 elementi | 2 pagine | path_pages=-`: era al **lotto iniziale**.
Non c'era nessuna pagina dinamica da perdere, né prima né dopo. Il log quindi **non può** né confermare
né smentire il difetto.

Il campo `path_pages` è ora lo strumento giusto, ma serve la prova nelle condizioni giuste:

1. paginare **un widget della home** (non la ricerca: lì il token non c'è più) finché le righe PERF
   mostrano `path_pages=4` o più;
2. avviare un film **da quella parte espansa** della lista;
3. chiuderlo e guardare la prima riga PERF dopo la chiusura.

`path_pages` ancora valorizzato → il token regge, il problema è a valle. `path_pages=-` → il token si
è perso, e a quel punto si sa dove guardare.

## Nota metodologica

Due volte di fila ho identificato la fonte di questo errore in modo sbagliato, e in entrambi i casi
perché ho generalizzato da un solo punto del codice invece di cercare **tutti** i posti in cui un
`<content>` può risultare vuoto. La regola per il seguito: prima di aggiungere qualcosa a un path,
elencare tutti i modi in cui quel path può essere vuoto.

---

# Lotto 8 — trovato: il crollo avviene all'AVVIO della riproduzione

## La prova

Il campo `path_pages` ha fatto il suo lavoro. Sequenza dal log:

| Ora | Evento | Stato del widget |
|---|---|---|
| 19:36:00.783 | ultima paginazione | **151 elementi, 11 pagine** |
| 19:36:13.728 | `VideoPlayer::OpenFile` | il film parte |
| **19:36:13.969** | ricostruzione | **35 elementi, 2 pagine** |
| 19:36:28.7 | `CloseFile` | — |

Il crollo avviene **241 millisecondi dopo l'avvio**, non alla chiusura. Per tutta la sessione le righe
riportano `path_pages=-`.

Avevamo cercato per due giri nel posto sbagliato — a valle della riproduzione — perché il sintomo si
*osserva* alla chiusura. Ma la lista era già collassata da prima: alla chiusura si vedeva soltanto il
risultato.

## Perché

Il test è stato fatto sulla ricerca discover, ed è esattamente il contenitore da cui nel lotto 7 avevo
**tolto** il token per chiudere l'errore `&pages=`. Senza token nel path:

- `get_pages` non riceve `path_pages` e ricade sulla via vecchia, che riconosce una ricostruzione
  "in corso" solo tramite i flag `LOADING` o `PG_REFRESH`;
- l'avvio della riproduzione provoca una ricostruzione che **non porta nessuno dei due flag**;
- conclusione: "apertura pulita", si riparte dal lotto iniziale.

**La correzione del lotto 7 ha causato il difetto del lotto 8.** Togliendo il token per chiudere un
errore cosmetico ho riportato quel contenitore sulla logica fragile che stavamo sostituendo. È lo
stesso difetto di fondo del lotto 2 — lo stato della paginazione affidato a un flag transitorio invece
che al path — ricomparso da un'altra porta.

## Correzione

**Token ripristinato ovunque**: righe di ricerca, widget hub e tutti i path del file generato — 13
punti in totale. Con il numero di pagine nel path, nessuna ricostruzione può più far collassare la
lista, qualunque cosa la inneschi: il path *è* lo stato.

**E il path malformato si chiude dall'altro lato.** Il watcher ora azzera il token quando un
contenitore tokenizzato non ha nessuna lista — tipicamente la ricerca a casella vuota, dove il path di
base sparisce e resterebbe il solo `&pages=N`. Si toglie il token dove sappiamo che non c'è nulla da
paginare, invece di togliere il token dove serviva.

## La lezione

Le due correzioni si sono annullate a vicenda perché ho trattato l'errore `&pages=` come un problema
del **token** anziché come un problema del **path di base che diventa vuoto**. La soluzione giusta
agiva sul secondo, non sul primo. Quando due sintomi si scambiano il posto a ogni giro, di solito la
causa è una sola e sta a monte di entrambi.

## Cosa verificare

1. **Il test di prima, identico**: paginare a lungo in ricerca o in home, avviare un film **dalla
   parte espansa**, chiuderlo. La lista deve restare com'era e la selezione tornare sul film giusto.
   Nelle righe PERF `path_pages` deve restare valorizzato **anche subito dopo l'avvio** del film — è
   lì che si vedeva il crollo.
2. **Ricerca a casella vuota**: `GetDirectory - Error getting &pages=` può comparire **una volta** con
   un token rimasto dalla sessione precedente, poi il watcher lo azzera e non deve tornare.
3. Che la paginazione continui a funzionare in home e in ricerca.

---

# Lotto 9 — la ricerca è a posto, la home mancava di due chiamate

## La ricerca funziona

Il log lo conferma senza margini. Test delle 20:01, widget discover a 9 pagine:

| Ora | Evento | `path_pages` |
|---|---|---|
| 20:01:35 | ultima paginazione, 126 elementi | `9` |
| 20:01:43.9 | avvio riproduzione | — |
| 20:01:44.2 | ricostruzione | **`9`** |
| 20:01:55 | chiusura | — |
| 20:01:57 | ricostruzione | **`9`** |

Prima, nello stesso punto, il widget crollava a 35 elementi e 2 pagine. Lo stato nel path regge sia
all'avvio sia alla chiusura.

## Perché la home no

I widget della home di questa configurazione non passano da `movies.py`. Sono:

- `mdblist.list.build_mdblist_list` → `indexers/mdblist_lists.py`
- `build_movie_list` con liste Trakt → `indexers/trakt_lists.py`
- `build_continue_watching` → non usa il paginatore, non pagina mai

E **quei due indexer chiamavano `get_pages` senza il terzo argomento**:

```python
pages_to_load = paginator.get_pages(pg_key, paginator.initial_batch())
```

Quando ho aggiunto `path_pages` avevo aggiornato solo `movies.py` e `tvshows.py`. `mdblist_lists.py` e
`trakt_lists.py` continuavano quindi a ricadere sui flag transitori — cioè esattamente il difetto che
il lotto 8 ha chiuso per la ricerca, rimasto intatto per la home.

Non era una causa diversa: **era la stessa causa in due file che non avevo toccato.**

## Come me ne sono accorto (e perché non prima)

Le righe `FenLight PERF` per la home riportavano sempre `trakt_watchlist | 21 elementi | 2 pagine`. Non
è un widget che si espande: la watchlist ha 21 titoli e finisce lì. Tutti gli altri widget della home
**non producevano nessuna riga**, perché il cronometro era solo in `movies.py`.

Avevo quindi un log che sembrava dire "in home non succede niente", quando in realtà stava dicendo
"in home non sto guardando".

## Correzioni

**`get_pages` riceve il `?pages=` del path anche in `mdblist_lists.py` e `trakt_lists.py`.** È la
correzione che chiude il difetto.

**Il cronometro esteso a entrambi gli indexer**, così i widget della home compaiono nel log con
elementi, pagine e `path_pages`. Da ora "non vedo niente nel log" significa davvero che non succede
niente.

## Nota

Tre lotti su questo difetto, e tutte e tre le volte il rimedio era corretto ma applicato a una parte
sola del sistema. La verifica che mancava è banale e la annoto per il seguito: **quando si cambia la
firma di una funzione condivisa, elencare tutti i chiamanti prima di dichiarare chiuso il lavoro.**
Un `grep get_pages` all'inizio avrebbe risparmiato due giri di test.

## Cosa verificare

1. **Home**: paginare a lungo un widget mdblist (*Latest Releases*) o una lista Trakt, avviare un film
   dalla parte espansa, chiuderlo. La lista deve restare e la selezione tornare sul film giusto.
2. **Nel log** devono comparire righe nuove: `FenLight PERF: mdblist ...` e `FenLight PERF: trakt ...`,
   con `path_pages` valorizzato durante la paginazione e **mantenuto** attraverso avvio e chiusura.
3. La ricerca deve continuare a comportarsi come adesso.

---

# Lotto 10 — A: eliminata la doppia costruzione

Stato: **completato**, da provare. La paginazione funziona ora in home, in ricerca e attraverso la
riproduzione: questo lotto tocca solo il *costo*, non il comportamento.

## Il sintomo

Nel log, due righe identiche a 12 millisecondi di distanza:

```
20:06:46.221  mdblist 91378 | 131 elementi | 6 pagine | path_pages=6 | 0.22s
20:06:46.233  mdblist 91378 | 131 elementi | 6 pagine | path_pages=6 | 0.16s
```

Stesso widget, stesso contenuto, **due costruzioni complete** per un solo passo di paginazione.

## La causa

La riga che le precede: `20:06:45.856 VideoInfoScanner: Starting scan ..` — il refresh **globale**.
Stava ancora scattando a ogni passo.

Il colpevole è il fallback del lotto 6, che decideva se un contenitore avesse il token leggendo
`Container(id).FolderPath` e cercandoci `pages=`. Per un contenitore widget quell'infolabel **non
restituisce il path del contenitore** come avevo assunto: la condizione risultava sempre falsa, quindi
oltre alla ricarica mirata partiva *anche* l'evento globale. Il widget veniva costruito due volte —
una dal token, una dal refresh — e con lui tutti gli altri della schermata.

Avevo introdotto quel rilevamento per proteggere i contenitori senza token. Nel frattempo **non ce ne
sono più**: la copertura è completa e senza sovrapposizioni.

| Modalità | Da dove arriva il token |
|---|---|
| Standard (home) | `widgets_row.xmltemplate` |
| Ricerca | `search_row_standard.xmltemplate` |
| Wall / Combined | `Includes_Hubs.xml`, sul `$PARAM[content]` |

Il fallback proteggeva quindi da un caso che non esiste, e in cambio raddoppiava ogni paginazione.

## Una scoperta importante sul file generato

`1080i/script-skinvariables-generator-includes-.xml` **viene rigenerato da script.skinvariables a ogni
avvio** (`script.skinvariables - update_xml: 0.139 sec` nel log). Le modifiche fatte direttamente su
quel file **spariscono**: contano solo i template in `shortcuts/generator/data/parts/`.

Spiega a posteriori diverse incongruenze fra quello che leggevo nel repository e quello che Kodi
caricava davvero. Il file è anche in `.gitignore`, il che è coerente: è un artefatto, non una fonte.

**Regola**: per la skin, modificare i template. Il file generato serve solo a leggere cosa è stato
prodotto.

## Correzioni

- Rimosso il rilevamento `tokenized` e il fallback `UpdateLibrary`. Una paginazione ora produce
  **una sola** ricostruzione, del solo widget scorso.
- L'azzeramento del token residuo (ricerca a casella vuota) non dipende più dal rilevamento: scatta
  quando il contenitore ha **zero elementi**. Durante una ricostruzione gli elementi restano, quindi
  non c'è rischio di svuotare un widget vivo.

## Guadagno atteso

Su Mac spariscono ~0,2 s a passo, invisibili. Sul Mi Stick si dimezza il lavoro: se una ricostruzione
costa 1,5-2,5 s, il passo passa da 3-5 s a 1,5-2,5 s. E il beneficio si estende agli altri widget della
schermata, che non vengono più ricostruiti per niente.

## Cosa verificare

1. **Nel log, durante la paginazione, non deve più comparire `VideoInfoScanner: Starting scan`.** È il
   segnale diretto.
2. **Una sola riga PERF per passo**, non due.
3. **Gli altri widget non devono più comparire** nel log quando se ne pagina uno: prima
   `trakt_watchlist` si ricostruiva a ogni passo del widget mdblist.
4. Che paginazione, riproduzione e ricerca continuino a funzionare come adesso.

---

# Lotto 11 — B: `reuselanguageinvoker`

Stato: **flag attivato, con uno strumento per verificare che serva davvero.** È l'intervento con il
rischio più alto finora e va provato da solo.

## Conferma del lotto 10

Prima di procedere, il log conferma che la doppia costruzione è sparita:

```
01:29:41.601  mdblist | 131 elementi | 6 pagine | path_pages=6
01:29:52.432  mdblist | 248 elementi | 12 pagine | path_pages=12
```

Una riga per passo, nessun `VideoInfoScanner` durante la paginazione, e `trakt_watchlist` non compare
più quando si pagina il widget mdblist. L'unico refresh globale rimasto è quello di fine riproduzione,
che è previsto.

## I due colli di bottiglia si separano

| | Risoluzione | Costruzione |
|---|---|---|
| Widget home (mdblist, 248 elementi) | 0,00 s | 0,13 s |
| Ricerca avanzata (discover) | **2,5 s** | 0,04 s |

I widget della home sono **interamente locali**: il tempo è CPU sulla costruzione, ed è lì che il Mi
Stick paga 10-20 volte tanto. La ricerca avanzata invece spende 2,5 s in rete (riqualificazione IMDb
per ogni pagina nuova) e costerà uguale ovunque. `reuselanguageinvoker` agisce **solo sul primo caso**.
I tempi di rete della ricerca restano un argomento separato, da valutare dopo.

## L'audit prima di toccare il flag

Con l'interprete riusato lo stato a livello di modulo **sopravvive tra le invocazioni**. Ho elencato
tutto quello che viene eseguito all'import:

| Categoria | Esito |
|---|---|
| Percorsi database, cartella blur | costanti, sicuri |
| Icone e fanart | costanti per sessione |
| Regex, namedtuple, `_WORKER_COUNT`, `_KODI_VERSION` | costanti |
| Singleton delle cache (`main_cache = MainCache()`, …) | oggetti senza stato, sicuri |
| `requests.Session()` nei moduli API | **vantaggio**: il pool di connessioni sopravvive |
| `Lock()` in `trakt_api` | più corretto con il riuso, non meno |
| Variabili globali mutate a runtime | solo due, entrambe memoizzazioni idempotenti (`_pil_available`, `_session`) |

L'unico rischio vero era una connessione SQLite in thread-local che sopravvive a un file cancellato.
**È già gestito**: `check_databases_integrity` sfratta la connessione dal pool prima di cancellare, e
`remove_old_databases` tocca solo file mai connessi. Entrambe girano nel servizio, non nelle build.

## L'incognita dichiarata

`fenlight.py` termina con:

```python
routing(sys)
if sys_exit_check(): sys.exit(1)
```

`sys_exit_check()` è vero per le build dei widget, quindi **ogni costruzione di widget finisce con
`sys.exit(1)`**. Non so con certezza se questo impedisca a Kodi di riusare l'interprete: potrebbe
renderlo inutile proprio dove serve di più.

Invece di indovinare, l'ho reso misurabile.

## Il contatore

`modules/paginator.py` tiene ora `_INVOCATIONS`, un contatore **che vive nell'interprete**, riportato
in coda alla riga PERF come `inv=N`:

- **`inv=1` sempre** → ogni build apre un processo nuovo: il riuso non sta avvenendo, e il primo
  sospetto è il `sys.exit(1)`;
- **`inv=` che cresce** → l'interprete sopravvive, il flag ha effetto.

Senza questo si finirebbe a giudicare da quanto "sembra" veloce, che su Mac non vuol dire niente
perché i totali sono già di centesimi di secondo.

## Cosa verificare

1. **Che tutto funzioni ancora**: home, ricerca, riproduzione, scraping, Trakt. È il lotto con più
   superficie di rischio: un modulo che tenesse stato sporco si manifesterebbe come dato vecchio che
   non si aggiorna.
2. **`inv=` nelle righe PERF.** È la domanda a cui questo lotto deve rispondere.
3. **Sul Mi Stick, i tempi dei widget della home.** È lì che il guadagno deve vedersi: su Mac
   probabilmente resterà invisibile come il lotto 10.
4. Attenzione a dati che non si aggiornano dopo un cambio di impostazione: sarebbe il sintomo tipico
   di stato sopravvissuto tra invocazioni.

**Se qualcosa si comporta in modo strano, il primo passo è rimettere `false` in `addon.xml`**: il
flag è l'unica cosa che cambia il comportamento, il contatore è solo diagnostica.

---

# Lotto 11b — il flag da solo non basta: il riuso non avviene

## La risposta del contatore

**`inv=1` su tutte e 17 le build della sessione.** Nessuna eccezione.

Il flag *è* attivo nell'addon che Kodi carica — `reuselanguageinvoker=true` in
`~/Library/Application Support/Kodi/addons/plugin.video.fenlight/addon.xml`, scritto alle 01:36, con
Kodi avviato alle 01:39 — quindi è stato letto. Ma l'interprete non viene riusato.

Conferma indipendente dal log di Kodi:

```
01:40:53  CPythonInvoker(24, .../fenlight.py): waiting on thread
```

**Ventiquattro invoker** creati in un'ora. Con il riuso attivo quel numero resterebbe basso.

Senza il contatore avremmo concluso "sembra uguale, forse su Mac non si vede" e saremmo passati oltre
con una modifica inefficace in produzione. È valso la pena aggiungerlo.

## Il sospetto, e la prova

`fenlight.py` terminava con:

```python
if sys_exit_check(): sys.exit(1)
```

`sys_exit_check()` è vero per le build dei widget, quindi **ogni costruzione di widget usciva con
SystemExit**. Un'uscita esplicita fa scartare a Kodi l'interprete invece di rimetterlo nel pool: è la
spiegazione più probabile di 24 invoker con il flag attivo.

Riga neutralizzata, **con il codice originale conservato nel commento**: il motivo per cui era stata
scritta non è documentato da nessuna parte, quindi va rimessa identica se l'esperimento non riesce.

Il criterio è netto: **se `inv=` cresce era lui; se resta 1, il riuso è impedito da altro** e la riga
va ripristinata prima di cercare altrove.

## Un limite da conoscere in anticipo

Anche con il riuso funzionante, Kodi riusa un interprete solo fra invocazioni **non sovrapposte**. Ai
widget della home che si costruiscono insieme all'apertura non servirà: ognuno avrà il suo. Il
guadagno riguarda le invocazioni **sequenziali** — cioè esattamente la paginazione, che è il caso che
ci interessa.

## Altre due cose che il log dice

### Il path malformato è tornato

```
01:40:54.332  GetDirectory - Error getting &pages=12
```

`12` è il numero di pagine del widget **mdblist della home**. Ricompare perché i widget della home e
quelli della ricerca **condividono gli id di contenitore** (502, 503): il token è una proprietà
indicizzata per id su `Home`, quindi è letteralmente lo stesso valore per due widget diversi. Quando
il contenitore della ricerca ha il path di base vuoto, resta il token dell'altro.

La protezione aggiunta nel lotto 10 (azzerare a contenitore vuoto) copre solo il contenitore che il
watcher sta osservando in quel momento; qui il fatto avviene mentre il focus è altrove.

**La correzione pulita** è rendere il token una proprietà **della finestra** invece che di `Home`:
`Window.Property(...)` lato skin e `xbmcgui.Window(getCurrentWindowId())` lato watcher. Così home e
ricerca hanno due depositi separati e la collisione sparisce alla radice. Da fare dopo l'esperimento
sul riuso, per non mescolare due variabili nello stesso test.

### Quattro ricostruzioni dopo ogni riproduzione

Alle 01:40:54, :54, :56 e :59 — quattro build della stessa lista, con due `VideoInfoScanner`. Sono i
refresh globali che `player.py` fa a fine riproduzione. Su Mac sono 0,3 s; sul Mi Stick sono una pausa
percepibile dopo ogni film. Candidato successivo: renderli mirati come la paginazione, o almeno non
doppi.

## Cosa verificare

1. **`inv=` nelle righe PERF.** È l'unica domanda di questo passo.
2. Che tutto continui a funzionare: home, ricerca, riproduzione, scraping. La riga tolta riguarda la
   *terminazione* delle build dei widget: un eventuale effetto si vedrebbe come widget che restano in
   caricamento o non si chiudono.
3. Se `inv=` resta 1, **ripristinare la riga dal commento** prima di procedere.

---

# Lotto 11c — l'esperimento risponde: `reuselanguageinvoker` è **chiuso in negativo**

## Cosa è successo

Kodi non si apriva più: crash all'avvio, riproducibile a ogni tentativo.

Il crash report di macOS
(`~/Library/Logs/DiagnosticReports/Kodi-2026-08-14-014917.ips`) non lascia margini
di interpretazione:

```
EXC_BAD_ACCESS (SIGSEGV) — KERN_INVALID_ADDRESS at 0x00000000000000ab
Thread 42: LanguageInvoker
  PyDict_SetItemString
  CPythonInvoker::execute(...)
  CLanguageInvokerThread::Process()
```

Segfault **dentro il codice C++ di Kodi**, non in Python. Il thread è
`LanguageInvoker` e la funzione è `CPythonInvoker::execute` mentre popola via
`PyDict_SetItemString` il dizionario globale del modulo da ri-eseguire. È
letteralmente il percorso del riuso dell'interprete. L'indirizzo `0xab` è un
offset su un puntatore nullo: lo stato dell'interprete che Kodi credeva di poter
riusare non era più valido.

## La conclusione, che è definitiva

Le due metà dell'esperimento vanno lette insieme:

- con `reuselanguageinvoker=true` **e** `sys.exit(1)` al suo posto → Kodi parte,
  `inv=1` su tutte e 17 le build. Il flag è inerte: nessun riuso avviene.
- con `reuselanguageinvoker=true` **e** `sys.exit(1)` neutralizzato → il riuso
  avviene davvero, e Kodi **segfaulta**.

Quindi `sys.exit(1)` non era un residuo senza motivo: **era la riga che impediva
il riuso**, e impedirlo era corretto. Il motivo non era documentato nel sorgente,
ma adesso lo è qui.

Non esiste una terza combinazione da provare. Il riuso è o inerte o fatale, e in
nessuno dei due casi guadagniamo tempo di CPU. **Il punto B è chiuso: non si
percorre.** Se un giorno venisse ritentato, questa sezione è la ragione per non
farlo.

## Ripristino

Entrambi i file riportati a HEAD, che era già lo stato corretto:

- `plugin.video.fenlight/addon.xml` → `<reuselanguageinvoker>false</reuselanguageinvoker>`
- `plugin.video.fenlight/resources/lib/fenlight.py` → `if sys_exit_check(): sys.exit(1)`

Tutti gli altri lotti (1–11a) sono intatti: il ripristino ha toccato solo questi
due file. `~/Library/Application Support/Kodi/addons/plugin.video.fenlight` è un
symlink al repo, quindi non serve nessun passo di deploy.

## Perché il costo della CPU resta dov'era

La misura che aveva motivato il punto B resta valida e non trova più questa
risposta: i widget della home costano `risoluzione 0.00s` / `costruzione 0.13s`
su Mac, cioè sono **CPU-bound**, e sul Mi Stick lo stesso lavoro costa 10–20×.
L'avvio dell'interprete era solo *una* delle voci di quel costo, e non possiamo
toglierla. Restano le altre, tutte dentro la costruzione della lista:

- **#2** ricostruzione quadratica;
- **#6** blob "slim" per la lista contro blob completo per la scheda info — è la
  voce con il rapporto beneficio/rischio migliore adesso che B è chiuso, perché
  agisce sulla quantità di dati che ogni elemento deve deserializzare;
- **#9**.

## Lezione di metodo

Il contatore `inv=` ha fatto esattamente il suo lavoro. Senza, avremmo concluso
"su Mac sembra uguale" e ci saremmo portati dietro un flag inerte credendolo
attivo — per poi vederlo esplodere sul Mi Stick, dove i log si leggono molto
peggio.

E la regola scritta nel lotto 11b — *conservare la riga originale verbatim nel
commento* — è ciò che ha reso il ripristino immediato e certo invece di una
ricostruzione a memoria.

---

# Lotto 12 — #6 misurato e **archiviato**: il parse non è il collo di bottiglia

## La misura, fatta prima di scrivere codice

Il punto #6 (blob "slim" per la lista contro blob completo per la scheda info) partiva da
un'intuizione sensata: ogni elemento della lista deserializza l'intero metadato, cast e
immagini del cast compresi, quando per disegnare una riga servono titolo, anno, poster e
poco altro.

Il database reale dà ragione all'intuizione sulla **dimensione**. Su 1750 film in cache,
blob medio 6,7 KB:

| campo | medio | quota del blob |
|---|---|---|
| `cast` | 3472 B | **55,5%** |
| `alternative_titles` | 1267 B | **20,3%** |
| `all_trailers` | 236 B | 3,8% |
| `writers` + `directors` | 311 B | 4,9% |
| tutto il resto | ~1,4 KB | ~15% |

Cinque campi fanno l'85% del peso, e **nessuno dei cinque serve a costruire una riga**:
`alternative_titles` lo legge solo `source_utils.py` (alias per lo scraping), `all_trailers`
solo `windows/extras.py`, `writers`/`directors` solo `skin_properties.py` (scheda info).

Ma la dimensione non è il tempo. Simulando una pagina reale da 112 elementi:

```
blob pieno:  716.1 KB   json.loads  2.00 ms
blob slim :  177.4 KB   json.loads  0.51 ms
112 SELECT puntuali su metacache.db  0.53 ms
112 x 7 build_url (urlencode)        3.16 ms
```

Contro una **costruzione misurata in Kodi di ~130 ms**.

## Perché il lotto si chiude senza scriverlo

Deserializzazione + database + costruzione URL sommano **~5,7 ms su 130: il 4%**. Lo split
slim/full ne risparmierebbe 1,49: **poco più dell'1% del totale**.

Sul Mi Stick il rapporto non cambia — entrambi i lati scalano con la CPU, quindi l'1% resta
l'1%.

Per quell'1% il prezzo sarebbe: una colonna nuova in `metadata`, una migrazione dello schema
su un database da 17 MB, 19 call site di `movie_meta`/`tvshow_meta` da rivedere, e un rischio
concreto di regressione silenziosa (un chiamante che riceve il blob slim e trova `cast` vuoto
non fallisce: mostra una sezione vuota, che è il tipo di bug che si scopre settimane dopo).

**#6 è archiviato come non conveniente.** Non è stato "rimandato": è stato misurato e scartato.
Se un giorno il costo di costruzione scendesse di un ordine di grandezza, il 4% tornerebbe a
contare e questa sezione dice esattamente dove guardare.

## Nota di metodo, perché è la seconda volta

Il lotto 11c ha chiuso `reuselanguageinvoker` con un contatore. Questo chiude #6 con un
benchmark. In entrambi i casi la modifica *sembrava* ovviamente giusta e in entrambi i casi
la misura ha detto di no — la prima per un crash, la seconda per irrilevanza.

La differenza rispetto al lotto sul menu contestuale, dove avevo stimato invece di misurare, è
che qui il costo della misura è stato di pochi minuti e ha risparmiato un refactor inutile su
dieci file.

## Cosa resta: dove stanno davvero i 130 ms

Sappiamo ora dove il tempo **non** sta. Restano, dentro `build_movie_content`, le chiamate
all'API C++ di Kodi, che sono ~30 per elemento: `getVideoInfoTag()` e una ventina di setter,
`setCast` (20 oggetti `xbmc.Actor` per elemento = 2240 per pagina), `setArt`, `setProperties`,
`addContextMenuItems`, `setLabel`.

Non è misurabile da fuori Kodi. Quindi è stata aggiunta una misura **per fase**, sullo stesso
modello del contatore `inv=`:

- `paginator.phase_record()` — ogni elemento fa **una** `list.append` di una tupla di durate.
  `append` è atomica sotto GIL, quindi nessun lock fra i thread del pool.
- `paginator.phase_report()` — somma per fase e logga una riga alla fine della costruzione.
- cinque fasi: `meta` (lettura metadato) · `prep+cm` (estrazione + 7 `build_url` + menu
  contestuale) · `infotag` (i setter) · `cast` (`setCast`) · `art+prop` (artwork, proprietà,
  menu, label).

**Attenzione a leggere il numero**: è la somma dei tempi di *thread*, non tempo di parete. Con
il pool a 6–10 worker la somma supera la durata reale della costruzione. Il dato utile è la
**quota relativa fra le fasi**, non il totale.

## Cosa verificare

1. Navigare un widget della home e paginare almeno una volta, poi cercare in log la riga
   `FenLight PERF FASI`.
2. La domanda a cui deve rispondere: **quale fase prende la quota maggiore.** Se è `cast`,
   l'intuizione iniziale era giusta ma per il motivo sbagliato — non il parse del JSON, ma il
   marshalling di 2240 oggetti `Actor` verso il C++.
3. Che nulla sia cambiato nel comportamento: la strumentazione non modifica la logica, solo
   misura. Home, ricerca, paginazione e riproduzione devono essere identiche.

## Il risultato della misura per fase

Dieci costruzioni, da 2 a 131 elementi, home e discover. Il quadro è stabile:

| fase | quota |
|---|---|
| `meta` | 41–60% |
| `art+prop` | 36–54% |
| `prep+cm` | 2–3% |
| `cast` | **1–2%** |
| `infotag` | 0–1% |

**`setCast` costa l'1%** — 5 ms su 406 nella costruzione più grande. L'ipotesi dei 2240 oggetti
`Actor` per pagina era sbagliata: Kodi li marshalla molto più a buon mercato di quanto stimassi.
Anche questa via è chiusa, e chiusa da un numero.

Restano due blocchi quasi identici, `meta` e `art+prop`, che insieme fanno il ~95%.

## L'anomalia che vale più di tutto il resto

La fase `meta` misura **168 ms su 112 elementi = 1,5 ms per elemento**. Fuori da Kodi, lettura
SQLite + `json.loads` dello stesso blob costano **22 µs**. Sono **60 volte** di scarto, e lo
scarto non può stare nei dati: sta in qualcosa che dentro Kodi costa e fuori no.

Nel percorso caldo di `movie_meta` (cache hit) ci sono esattamente due cose:

```python
lang = meta_language()                                   # -> get_setting -> get_property
meta = metacache_get('movie', id_type, media_id, ...)    # -> SELECT + json.loads
```

E `get_setting` è:

```python
return get_property(setting_id) or settings_cache.get(setting_id) or fallback
```

cioè un **`getProperty` su `Window(10000)`**: una chiamata C++ con lock sulla finestra, eseguita
**una volta per elemento** da 6–10 thread del pool contemporaneamente. È il candidato naturale
per un costo che esiste solo dentro Kodi e che peggiora con il parallelismo.

Non lo do per dimostrato: è esattamente l'errore che ho già fatto due volte. Quindi le due metà
sono state separate (`phase_record_meta`) e il log dirà quale paga, prima di toccarle.

Se è `meta_language()`, la correzione è banale e sicura: il valore è **costante per l'intera
costruzione**, quindi si calcola una volta in `worker()` e si passa come parametro opzionale
(`lang=None`, retrocompatibile, due soli call site da cambiare sui 19).

Nel frattempo `art+prop` è stato spezzato in `label+cmenu` / `setArt` / `props`, perché vale
quanto `meta` e ha lo stesso profilo: poche chiamate C++ ripetute per elemento. Il sospetto qui
è `setArt`, che può innescare risoluzioni nella texture cache.

---

# Lotto 13 — il costo è nella lettura di cache, e non si spiega con i dati

## L'ipotesi del `getProperty` era sbagliata

Il log è netto: nella fase `meta`, **`meta_language()` pesa l'1–3%**. Il `getProperty` su
`Window(10000)` che avevo indicato come sospetto principale non costa nulla. Il 97–99% è la
**lettura di cache** vera e propria — `SELECT` + `json.loads`.

Terza ipotesi mia smentita da una misura, dopo `reuselanguageinvoker` e il cast. La differenza
è che ogni smentita è costata un giro di log invece di un refactor.

## Cosa dicono i numeri, in dettaglio

Dodici costruzioni, da 31 a 248 elementi. Il costo per elemento **scende** al crescere della
lista, che è la firma di un costo fisso che si ammortizza:

```
costo_cache(ms) = 0.765 * elementi + 59.7      (regressione sulle 12 costruzioni)
```

- **~60 ms fissi** per costruzione
- **~0,77 ms per elemento** marginali

Contro **0,022 ms/elemento** misurati fuori da Kodi sullo stesso database e sugli stessi blob.

## Due spiegazioni scartate

**Connessioni SQLite per thread.** `connect_database` è thread-local, quindi ognuno dei 6–10
thread del pool apre la propria connessione al database da 17 MB ed esegue due PRAGMA. Sembrava
il candidato perfetto per il costo fisso. Misurato: `connect` + 2 PRAGMA = **0,27 ms**, per dieci
thread **2,7 ms**. Non 60. Scartata.

**Contesa sul GIL da sola.** Il rapporto fra somma dei tempi di thread e tempo di parete dice
parallelismo ~2,1. Una contesa 2× non trasforma 22 µs in 1000.

## L'ipotesi che resta, e perché è credibile

Kodi imbarca il proprio Python. Se in quella build manca l'estensione C `_json`, il decoder cade
sul percorso **puro Python**. Misurato fuori, sugli stessi 112 blob:

```
json con acceleratore C :   1.99 ms
json puro Python        :  24.69 ms      (12x)
```

24,7 ms moltiplicati per la contesa fra thread arrivano nell'ordine di grandezza dei ~130 ms
osservati. Nessun'altra ipotesi finora copre il divario.

**Se è confermata, ribalta il lotto 12.** Con un decoder 12 volte più lento, il costo del blob
pieno non è più il 4% del totale ma la voce principale — e **#6 (blob slim) torna in gioco come
intervento maggiore**, perché tagliare il 75% del blob taglierebbe il 75% di un costo grande
invece che di uno trascurabile. Il lotto 12 resta corretto nella misura e sbagliato nella
conclusione solo se questa ipotesi passa: è il motivo per cui la si verifica prima di agire.

## L'autotest

`paginator.selftest()` gira **una volta per costruzione, nel thread principale, senza pool**, così
il numero non contiene né contesa sul GIL né parallelismo ed è direttamente confrontabile con il
benchmark esterno. Logga:

- se `json.decoder.c_scanstring` esiste (cioè se l'acceleratore C c'è)
- la versione di Python che Kodi sta usando
- una `SELECT` unica da 100 righe e il tempo di `json.loads` sequenziale sulle stesse

## Cosa verificare

Cercare in log `FenLight PERF SELFTEST`. Tre esiti possibili:

1. **acceleratore assente** → causa trovata, e #6 diventa la priorità.
2. **acceleratore presente ma ms/blob molto sopra 0,018** → il decoder non è il problema, lo è
   l'ambiente Python di Kodi in generale; si guarda al numero di operazioni, non alla loro natura.
3. **acceleratore presente e ms/blob ~0,018** → la lettura singola è veloce e il costo nasce
   solo sotto pool: allora il colpevole è il parallelismo stesso, e la mossa è ridurre i thread
   per le costruzioni servite da cache.

---

# Lotto 14 — la causa: i thread non parallelizzano, fanno la fila

## L'autotest chiude la questione

```
acceleratore C json: True | python 3.11.7 | 100 blob, medio 7667 B
SELECT unico 0.50 ms | json.loads sequenziale 3.15 ms = 0.031 ms/blob
```

Dentro Kodi, nel thread principale e senza pool, la lettura costa **~0,036 ms per elemento** —
in pratica quanto fuori (0,022). L'ipotesi del decoder puro Python è morta: `_json` c'è, la
versione è una 3.11.7 normale.

Ma **sotto il pool la stessa identica operazione misura 1,0–1,7 ms**: da 30 a 45 volte tanto.
L'operazione non è lenta. È lenta *soltanto quando gira in dieci thread*.

## Perché

È l'effetto convoglio del GIL. `sqlite3` rilascia il GIL durante `execute`; per riprenderlo deve
attendere un passaggio di consegne, che avviene al più ogni 5 ms (`sys.setswitchinterval`). Con
6–10 thread che alternano SQLite (rilascia) e `json.loads` (trattiene), ogni ritorno da SQLite
finisce in coda dietro chi sta macinando Python.

La conferma sta nel rapporto fra somma dei tempi di thread e tempo di parete: **~2,1**. Con dieci
worker su lavoro davvero parallelizzabile ci si aspetta molto di più. I thread non stanno
parallelizzando, stanno facendo la fila — e il costo fisso di ~60 ms per costruzione stimato nel
lotto 13 è precisamente il prezzo di quella fila.

Questo spiega anche perché il Mi Stick soffre in modo sproporzionato: ha 4 core invece di 8–10,
quindi il pool è più piccolo ma la contesa relativa è peggiore, e ogni attesa di handoff pesa di
più su un core lento.

## L'intervento

Non ottimizzare la lettura: **toglierla dal pool.**

- `meta_cache.get_many()` — una sola `SELECT ... IN (...)` per l'intera lista, spezzata a blocchi
  di 500 per il limite di parametri di SQLite. Le voci **scadute non vengono restituite**: cadono
  sul percorso normale, che le cancella e le riscarica come prima.
- `metadata.movie_meta_prefetch()` — replica esattamente la semantica di `movie_meta`: risoluzione
  `trakt_dict` → `tmdb_id`/`imdb_id` e controllo della lingua. Chi non passa questi controlli non
  finisce nel lotto e prende la strada di sempre.
- `Movies.worker()` — esegue il prefetch **in sequenza, prima di aprire il pool**.
- `build_movie_content()` — consulta il lotto; se l'elemento non c'è, chiama `movie_meta` come
  prima.

Il punto di progetto è che **questo strato non decide nulla**: anticipa soltanto letture che
sarebbero comunque avvenute, pagandole a prezzo sequenziale. Ogni caso che non sa gestire con
certezza lo lascia al codice esistente, che è rimasto intatto. I thread restano per chi ne ha
davvero bisogno: le voci non in cache, che devono andare in rete — dove il parallelismo funziona,
perché lì il GIL è rilasciato per millisecondi veri.

## Verifica di correttezza già fatta

Sul database reale, 400 id, confronto fra percorso per elemento e percorso a lotto:

```
per elemento : 400    a lotto : 400
stesse chiavi     : True
stessi contenuti  : True
```

## Cosa verificare

1. **`FenLight PERF PREFETCH`** — deve dire una percentuale di cache alta (vicina al 100% su una
   lista già navigata) e una lettura unica di pochi millisecondi.
2. **`FenLight PERF FASI`** — la fase `meta`, che valeva il 41–60%, deve crollare vicino a zero.
   È la misura del successo o del fallimento di questo lotto.
3. **`FenLight PERF`** — il numero che conta davvero per l'utente: `costruzione`. Su Mac era
   ~0,13 s per 112 elementi.
4. Che le liste siano **identiche** a prima: stessi film, stesso ordine, nessun buco. Un elemento
   che sparisce indicherebbe una chiave di prefetch sbagliata.

Nota: per ora il prefetch è solo su `movies`. Le liste miste (MDbList, Trakt) hanno anche una metà
`tvshows` che paga ancora il prezzo vecchio. Le liste `discover`, che sono solo film, sono il caso
di prova più pulito. Se il risultato è quello atteso, `tvshows.py` riceve lo stesso trattamento.

## Il risultato: il lotto 14 funziona

`FenLight PERF PREFETCH` su undici costruzioni consecutive: **100% già in cache**, lettura unica
da 3,8 a 21 ms per l'intera lista. E la fase che doveva sparire è sparita:

```
meta 0ms (0%)     <-- valeva 41-60%
```

Confronto a numero di elementi confrontabile, su `somma thread` (l'unica metrica omogenea fra le
due sessioni):

| elementi | prima | dopo | delta |
|---|---|---|---|
| 88 ~ 83 | 350 ms | 103 ms | **−71%** |
| 101 ~ 100 | 397 ms | 153 ms | **−61%** |
| 117 ~ 116 | 274 ms | 166 ms | −39% |
| 142 ~ 147 | 375 ms | 197 ms | −47% |
| 155 ~ 162 | 612 ms | 299 ms | **−51%** |

Mediana **−47%**.

### L'effetto secondario, che vale quanto il primo

Il rapporto fra somma dei tempi di thread e tempo di parete **è passato da ~2,1 a ~5**. Tolta dal
pool l'unica fase che alternava rilascio e ripresa del GIL, il lavoro rimasto ha cominciato a
parallelizzare per davvero. Il guadagno sul tempo di parete è quindi maggiore del −47% misurato
sulla somma: `costruzione` sta ora fra 0,02 s (34 elementi) e 0,07 s (194).

I widget della home: **131 elementi in 0,08 s**, contro gli 0,13 s per 112 elementi misurati prima
dell'intervento.

---

# Lotto 15 — tre mosse sul costo rimasto

Chiusa `meta`, il profilo si è ridisegnato: `label+cmenu` ~50%, `props` ~35%, `setArt` ~8%.

**1. Separata `setLabel` da `addContextMenuItems`.** Erano misurate insieme e valgono metà del
totale; il sospetto è il menu contestuale, che monta sette voci per elemento. Adesso il log lo
dirà invece di farmelo supporre — è la stessa domanda che era rimasta senza risposta quando le
voci del menu erano state ridotte "a occhio".

**2. Una sola `setProperties` invece di due o tre.** Erano già tutte proprietà dello stesso
listitem: il dizionario si compone in Python a costo nullo e il confine verso il C++ si attraversa
una volta sola. Nessun cambiamento di semantica — le stesse chiavi, gli stessi valori.

**3. Prefetch esteso a `tvshows.py`.** Le liste miste (MDbList, Trakt) pagavano ancora il prezzo
vecchio sulla metà serie. La risoluzione degli id per le serie ha un ramo in più rispetto ai film
(ripiego su `tvdb`), quindi gli helper sono stati generalizzati con un parametro `media_type`
invece di duplicati.

## Verifica di correttezza già fatta

Sul database reale, per tutti e tre i tipi di id usati dal prefetch:

```
tvshow tmdb_id  148 id   per-elemento=148  a-lotto=148  identici=True
tvshow tvdb_id  142 id   per-elemento=142  a-lotto=142  identici=True
movie  imdb_id  300 id   per-elemento=300  a-lotto=300  identici=True
```

## Cosa verificare

1. **`PERF PREFETCH` con riga `tvshows`** — deve comparire per i widget MDbList/Trakt.
2. **`PERF FASI`** — ora otto fasi: quanto pesa `ctxmenu` da solo.
3. **`props`** — deve calare, avendo una sola chiamata al posto di due o tre.
4. Che **le serie** nelle liste miste siano tutte presenti e corrette: è il punto dove una chiave
   di prefetch sbagliata si vedrebbe (elemento mancante o metadato di un'altra serie).

---

# Lotto 16 — il bug che il prefetch ha portato alla luce: 12 secondi per un id invalido

## Il sintomo

Widget di sole serie TV, molto più lento dei film. Il log dice esattamente quanto:

| elementi | in cache | costruzione |
|---|---|---|
| 43 | **100%** | **0,02 s** |
| 81 | 99% (1 mancante) | **9,28 s** |
| 148 | 99% (1 mancante) | **12,17 s** |

**Una sola voce non in cache costa 9–12 secondi**, e la costruzione intera la aspetta, perché il
pool attende tutti i thread prima di restituire la lista.

Il prefetch non ha causato questo: lo ha reso **visibile e quantificabile**. Prima quel costo
c'era identico, indistinguibile dentro il mucchio delle letture per elemento.

## La causa

Nella cache ci sono **4 righe `blank_entry`**: segnaposto salvati quando TMDb rifiuta un id
(codici 6/34/37), il cui scopo è precisamente **non richiedere di nuovo quell'id** per 24 ore.

```json
{"tmdb_id": 1234731, "imdb_id": "tt0000000", "tvdb_id": "0000000", "blank_entry": true}
```

Non hanno il campo `meta_language`. E il controllo era:

```python
if meta and meta.get('meta_language', 'en') != lang: meta = None
```

Un blank entry viene quindi valutato come `'en'`. Con la lingua impostata su `it` — o su
qualunque cosa diversa da `en` — il confronto fallisce, il segnaposto viene scartato, e si va in
rete. **Ogni singola costruzione, per sempre.** La protezione veniva annullata proprio per le voci
che esistevano solo per fornirla, e su un id invalido la richiesta va a vuoto lentamente.

È un bug preesistente, indipendente dal prefetch, e colpisce chiunque non usi l'inglese.

## La correzione

Il controllo lingua non si applica ai segnaposto, nei tre punti dove esiste: `movie_meta`,
`tvshow_meta` e `meta_prefetch`. Un `_is_blank()` con il commento del perché, così non torna.

A valle nulla cambia: `build_movie_content` e `build_tvshow_content` fanno già
`if not meta or 'blank_entry' in meta: return`, quindi la voce viene saltata come prima — solo
senza pagare la rete per scoprirlo.

## Cosa verificare

1. Il widget di sole serie: `PERF PREFETCH` deve dire **100%** (i 4 blank ora contano come
   presenti) e `costruzione` deve crollare da ~12 s a frazioni di secondo.
2. Che le liste mostrino **gli stessi titoli di prima**: le voci blank erano già invisibili, quindi
   il numero di elementi visualizzati non deve cambiare.
3. Nessuna regressione sui film, dove i blank in cache al momento sono zero.

## Nota

Vale la pena ricordarlo perché è il secondo caso in questa serie: il costo peggiore non era in
quello che il codice faceva per ogni elemento, ma in una singola voce patologica ripetuta a ogni
costruzione. La misura per fase serviva a trovare i costi diffusi; è stato il prefetch, dicendo
"99% invece di 100%", a rendere evidente quello concentrato.

## Il risultato del lotto 16: confermato

| lista | prima | dopo |
|---|---|---|
| 81 elementi | 9,28 s | **0,04 s** |
| 148 elementi | 12,17 s | **0,07 s** |

Il prefetch delle serie ora dice **100%**, e la costruzione è allineata a quella dei film
(0,5 ms/elemento).

---

# Lotto 17 — la riga PERF mentiva, e nascondeva il filtro doppiaggio

## Il caso che non tornava

Resta una costruzione lenta: **199 richiesti, 199 già in cache (100%), 9,79 s**. Con tutti i
metadati in cache quel numero è impossibile — e infatti non era vero.

In `mdblist_lists.py` e `trakt_lists.py` la chiamata era:

```python
paginator.log_build('mdblist', ..., _t0, _t0, paginator.now(), ...)
```

`_t0` passato **sia** come istante iniziale **sia** come istante di "risolto". Per costruzione,
quindi, `risoluzione` risultava sempre `0.00s` e **tutto il tempo finiva in `costruzione`** —
compreso il filtro doppiaggio, che gira prima che i worker partano.

La prova nel log: la riga `PERF PREFETCH` compare a `02:30:12.500` e la riga finale a
`02:30:12.551`. Fra l'inizio della costruzione vera e la fine passano **51 ms**. I 9,79 s erano già
stati spesi prima, in una finestra in cui il log è completamente muto.

Confine spostato al punto giusto: dopo il filtro doppiaggio, prima dei worker. Ora `risoluzione`
misura il filtro e `costruzione` misura la costruzione.

## Cosa fa davvero il filtro doppiaggio

Per ogni elemento: risolve il metadato, poi consulta `dub.db`; se il verdetto manca, interroga
TMDb per la disponibilità in streaming e, **solo se non è in streaming**, ripiega su blu-ray.com,
che è la chiamata lenta.

Due costi distinti, e solo uno è inevitabile:

1. **La risoluzione del metadato girava dentro il suo thread pool**, chiamando `movie_meta`/
   `tvshow_meta` per elemento: esattamente il costo convoglio sul GIL tolto agli indexer nel lotto
   14, qui ancora per intero. Ed è peggio che negli indexer, perché il filtro gira per primo e lo
   pagava su **tutta** la lista, non solo sui nuovi elementi. Ora usa lo stesso `meta_prefetch`.
2. **La rete per i verdetti mancanti** è irriducibile: un titolo mai visto va chiesto. Ma va
   *misurata*, per sapere quanta parte della lentezza percepita è questa e quanta è lavoro nostro.

## La misura aggiunta

Riga `FenLight PERF DUB`, sempre attiva (non gated da `DUB_DEBUG`, che è `False` e infatti ha
lasciato quella finestra senza una riga di log):

```
media | N elementi | meta anticipati | verdetto in cache | rete: streaming X, bluray Y | scartati | prefetch ms + valutazione s
```

Separa nettamente ciò che è cache da ciò che è rete, e distingue le due sorgenti di rete — perché
blu-ray.com è molto più lento di TMDb e il codice lo interroga solo come ripiego.

## Cosa verificare

1. **`PERF DUB`** sulla lista di serie a 12 pagine: quanti elementi finiscono in `rete` e quanto
   dura `valutazione`. È il numero che dice se i ~10 s sono rete inevitabile.
2. **`PERF`** ora deve mostrare `risoluzione` diversa da zero sulle liste MDbList/Trakt: se resta
   `0.00s` con una costruzione lunga, il confine è ancora nel posto sbagliato.
3. Che la seconda visita alla stessa pagina sia veloce: i verdetti appena scaricati sono ora in
   `dub.db`, quindi il costo si paga una volta sola per titolo.

---

# Lotto 18 — il Mi Stick misurato: restano tre voci, tutte verso il C++

## Il quadro sul dispositivo di riferimento

Xiaomi Mi TV Stick, 4 core ARM 32-bit. Cinque costruzioni, 302 elementi in totale:

| fase | quota | ms/elemento |
|---|---|---|
| `ctxmenu` | **37%** | 18,69 |
| `props` | **23%** | 11,71 |
| `infotag` | **17%** | 8,43 |
| `prep+cm` | 9% | 4,59 |
| `setArt` | 6% | 3,01 |
| `setLabel` | 3% | 1,69 |
| `cast` | 3% | 1,65 |
| `meta` | **0%** | 0,08 |

**`meta` è a zero anche sulla stick**: il prefetch del lotto 14 regge sul dispositivo debole, che
era il punto. Tre voci — menu contestuale, proprietà, info tag — fanno il **77%** di quel che resta,
e sono tutte attraversamenti verso l'API C++ di Kodi.

Per confronto, sul Mac le stesse fasi costano ~0,5 ms/elemento contro i ~50 della stick: **un
fattore 100**, molto più del rapporto di CPU pura. Il che conferma che il costo non è calcolo
nostro, ma attraversamento del confine Python/C++.

## La domanda che decide la correzione

Il costo di una fase è proporzionale al **numero di chiamate** o al **numero di chiavi** che ogni
chiamata trasporta? Le due risposte portano a correzioni opposte:

- **per chiamata** → accorpare. Il menu contestuale, per esempio, internamente non è altro che una
  coppia di proprietà per voce (`contextmenulabel(N)` / `contextmenuaction(N)`), quindi potrebbe
  entrare nello stesso dizionario che già passiamo a `setProperties`: da 1 chiamata + 14 proprietà
  a 0 chiamate aggiuntive.
- **per chiave** → accorpare non serve a niente, e bisogna invece *ridurre*: meno voci di menu,
  meno proprietà, meno setter.

Non è deducibile dal codice sorgente di Kodi senza averlo sotto mano, e ho già sbagliato tre
ipotesi in questa serie. Quindi si misura.

## L'autotest sostituito

Il vecchio autotest su json ha già dato la sua risposta (acceleratore C presente, ~0,03 ms/blob) e
sulla stick **costava 130–320 ms per costruzione**: era diventato esso stesso una voce di spesa.
Rimosso e sostituito con un micro-benchmark dell'API C++ che misura, dentro Kodi:

- **N `setProperty` singole** contro **una `setProperties` con le stesse N chiavi** — è il confronto
  che risponde alla domanda: se i tempi si somigliano il costo è per chiave, se la seconda è molto
  più rapida è per chiamata;
- `addContextMenuItems` con 7 voci, costo per chiamata;
- un setter di info tag, costo per chiamata.

## Sul riavvio della stick

Il log si interrompe di netto, senza traccia né errore: coerente con un riavvio di sistema, non con
un crash di Kodi. Da questo log **non è diagnosticabile**, e non ho intenzione di indovinare.

Due osservazioni utili però ci sono. La prima: il dispositivo ha 1 GB condiviso con la GPU, e una
lista interattiva arriva a 200 elementi con i metadati di tutti in memoria. La seconda: il
`meta_prefetch` viene eseguito **due volte** sulla stessa lista — una nel filtro doppiaggio e una
nell'indexer — quindi per un momento esistono due dizionari completi. Sono ~2,4 MB per 200
elementi: poco, ma è spreco puro ed è eliminabile.

Ridurre gli attraversamenti verso il C++ agisce nella stessa direzione della stabilità, perché
riduce insieme tempo di CPU e oggetti temporanei.

## Cosa verificare

Cercare `FenLight PERF API`. Una riga sola, e dice quale delle due correzioni fare.

---

# Lotto 19 — REGRESSIONE MIA: `phase_report` cancellata, addon rotto

## Cosa è successo

Nel lotto 18 ho sostituito l'autotest con uno script Python che riscriveva `paginator.py`
prendendo tutto il testo fra un commento iniziale e `def log_prefetch(`. In quell'intervallo non
c'era solo l'autotest: c'era anche **`phase_report`**, che è stata cancellata.

`ast.parse` passava — la sintassi era perfettamente valida — quindi il controllo che facevo
abitualmente non ha visto niente. L'addon è finito in mano all'utente rotto:

```
AttributeError: module 'modules.paginator' has no attribute 'phase_report'
  File "indexers/movies.py", line 311, in worker
```

`phase_report` è chiamata in fondo a `Movies.worker()`, quindi **ogni costruzione di lista film
falliva**. Conseguenze osservate: widget della home vuoti (`0 elementi`), watchlist vuota,
"latest releases" vuoto, ricerca ferma — su Mac e su Mi Stick.

Il segnale c'era e non l'ho letto: `git diff --numstat` diceva `40 aggiunte / 47 rimozioni` per
una modifica che doveva solo *sostituire* un blocco. Sette righe sparite in più.

## La lezione, che è diversa da quella già annotata

Era già scritto in questo documento di verificare `git diff --numstat` dopo ogni modifica
scriptata — regola nata dal disastro CRLF. Non bastava, perché guardavo il numero e non cosa
fosse sparito.

**La sintassi valida non dice niente sui simboli.** Dopo una riscrittura scriptata va verificato
che i nomi esistano ancora, non che il file compili.

## Il controllo, ora automatizzato

`check_symbols.py` (nella cartella di lavoro) analizza l'AST di tutti i 91 moduli e verifica:

1. ogni `from <modulo interno> import nome` → il nome esiste nel modulo di origine;
2. ogni `<modulo>.attributo` → l'attributo esiste, limitato ai nomi legati da un import di modulo
   interno **nello stesso file** e solo su nodi `ast.Attribute`.

La prima versione usava una regex e produceva 591 falsi positivi (pescava stringhe come
`'fenlight.rd'` e `'offcloud.com'`): rifatta sull'AST, ora è pulita.

Da eseguire **dopo ogni modifica scriptata**, prima di consegnare.

## Ripristino

`phase_report` riscritta identica, con dentro anche il report delle sotto-fasi `meta` che stava
nello stesso blocco. Verifica: tutti e 33 gli attributi `paginator.*` usati nel codice esistono.

## Tre bug preesistenti trovati per strada

Il controllo ha fatto emergere tre route rotte **a monte, in Fen Light**, in file che non ho mai
toccato (`git diff` su `router.py` è vuoto):

```
modules/router.py:224  from modules.search import add_to_history   -> non esiste
modules/router.py:364  from modules.kodi_utils import show_text_media -> non esiste
modules/router.py:374  from modules.kodi_utils import set_view      -> non esiste
```

Due hanno anche la chiamata incoerente con l'import (la riga dopo `show_text_media` chiama
`show_text` con cinque argomenti posizionali sbagliati). Non sono correzioni meccaniche e non
vanno infilate dentro un ripristino: annotate, da fare a parte.

## Sul riavvio della stick: cosa dice davvero questo log

**Non è attribuibile alla costruzione delle liste.** In questa sessione le build fallivano
immediatamente con l'AttributeError e restituivano `0 elementi`: il carico di CPU e memoria era
quindi *minimo*, e il dispositivo si è riavviato lo stesso, prima ancora di mostrare i widget.

Nel log non c'è nessuna traccia di tempesta di invocazioni (le due ricostruzioni distano 40
secondi) né alcun errore prima dell'interruzione. Da qui non è diagnosticabile, e non ho
intenzione di indovinare una quarta volta.

Il prossimo test, su un addon funzionante, dice se il riavvio persiste: se persiste, non c'entra
il nostro percorso di costruzione.

---

# Lotto 20 — la risposta: non "per chiamata" né "per chiave". Erano i thread.

## Il micro-benchmark

Diciassette esecuzioni sul Mi Stick, `FenLight PERF API`:

| misura | min | mediana | max |
|---|---|---|---|
| `setProperty` singola (ms/chiave) | 0,018 | 0,033 | 7,177 |
| `setProperties` accorpata (ms/chiave) | 0,015 | 0,023 | 1,969 |
| `addContextMenuItems` 7 voci (ms/chiamata) | 0,150 | 0,260 | 9,200 |
| setter info tag (ms/chiamata) | 0,004 | 0,006 | 0,030 |

**Accorpare non serve**: singole e accorpate costano lo stesso per chiave (0,018 contro 0,015 al
minimo, rapporto mediano 1,1x). L'idea di riscrivere il menu contestuale come proprietà è morta,
e per fortuna non l'avevo scritta.

Ma il numero che conta è un altro. La **stessa singola chiamata** `addContextMenuItems`:

```
nel thread principale (selftest) :  0,15 - 0,26 ms
dentro il pool (fase 'ctxmenu')  :  1951 ms / 131 elementi = 14,9 ms
                                    -> 74 volte tanto
```

Non è un'inferenza: è la stessa operazione misurata in due contesti. E la varianza enorme del
selftest (fino a 9,2 ms quando un'altra costruzione gira in parallelo) è la stessa causa vista da
un'altra angolazione: **contesa**, non costo dell'operazione.

## La diagnosi

È l'effetto convoglio sul GIL del lotto 14, che avevo tolto **solo alla lettura dei metadati**.

Tolta quella, nel pool non è rimasto niente che benefici dei thread: solo Python e chiamate
all'API C++, che il GIL serializza comunque. I sei worker del Mi Stick non parallelizzano — si
fanno la coda a vicenda sul passaggio di consegne del GIL, che avviene al più ogni 5 ms.

Il pool aveva senso quando ogni elemento poteva andare in rete. Dopo il prefetch non è più così,
e la struttura è rimasta indietro rispetto alla ragione per cui esisteva.

## L'intervento: costruzione in due fasi

1. **Prefetch** dei metadati già in cache — una query, in sequenza (lotto 14, invariato).
2. **`_resolve_missing()`** — le voci non servite dal prefetch vanno chieste alla rete, e *lì* i
   thread restano: il tempo è attesa di I/O, il GIL è rilasciato per millisecondi veri, il
   parallelismo funziona davvero. Il risultato confluisce nello stesso dizionario del prefetch
   (l'assegnazione a un dizionario è atomica sotto GIL, nessun lock necessario).
3. **Costruzione in sequenza** — `build_movie_content` / `build_tvshow_content` a questo punto non
   fanno mai I/O: tutti i metadati sono già risolti. Il ciclo sostituisce il pool.

Applicato a `movies.py` e `tvshows.py`. Nessun cambiamento nell'ordine degli elementi: il ramo
`custom_order` continua a restituire le tuple `(item, posizione)` che ordina il chiamante, l'altro
ordina come prima.

## Perché va anche nella direzione della stabilità

Meno thread vivi contemporaneamente, meno oggetti temporanei, meno contesa con il thread di
rendering. Su un dispositivo da 1 GB condiviso con la GPU è la stessa medaglia dell'ottimizzazione,
non un compromesso opposto.

## Cosa verificare

1. **`PERF FASI`**: `ctxmenu`, `props` e `infotag` devono crollare. Sul Mi Stick valevano
   rispettivamente 37%, 23% e 17% di una somma-thread di ~5300 ms su 131 elementi.
2. **`PERF`**: `costruzione`. Era 1,31 s per 131 elementi e 3,55 s per 248.
3. **`PERF PREFETCH ... (rete)`**: la riga nuova, che isola quanto costa risolvere le voci mancanti.
   Deve comparire solo quando ci sono voci non in cache.
4. Che le liste siano **identiche**: stessi titoli, stesso ordine, nessun buco.
5. Che una lista con voci **non in cache** (discover su un genere nuovo) funzioni ancora: è il caso
   che esercita `_resolve_missing`.

## Due cose segnalate, da fare dopo

- **Selezione dopo la riproduzione dalla ricerca**: alla chiusura del player il focus finisce sulla
  barra di ricerca invece che sul film, e non si riesce a scendere di nuovo alla lista.
- **Richiesta di installare TMDbHelper**: nel log compare
  `Unable to find plugin plugin.video.themoviedb.helper` seguito da
  `GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=discover&with_id=True&tmdb_type=movie`.
  È un riferimento a TMDbHelper **ancora vivo nella skin**, sul percorso discover — quindi rientra
  nella rimozione dei riferimenti, con il path esatto già individuato.

## Il risultato su Mac (cache svuotata)

Nessun errore, nessuna lista vuota, ordine corretto. E il costo di CPU crolla:

| | ms/elemento (somma thread) |
|---|---|
| con il pool | **1,693** (1027 elementi su 7 costruzioni) |
| in sequenza | **0,134** (714 elementi su 9 costruzioni) |
| | **13x più leggero** |

La ridistribuzione delle fasi è esattamente quella prevista dal micro-benchmark:

| fase | con il pool | in sequenza |
|---|---|---|
| `ctxmenu` | 37–43% | **4–5%** |
| `props` | 23–29% | **2–3%** |
| `infotag` | 15–22% | 10–11% |
| `setArt` | 5–12% | 2% |
| `prep+cm` | 4–9% | **52–58%** |
| `cast` | 2–5% | **22–26%** |

Le chiamate C++ sono diventate marginali, come il selftest prometteva (0,2 ms contro 14,9). Quel
che resta è ora **lavoro Python puro**: `prep+cm` sono le sette `build_url` per elemento, `cast` è
la comprensione che costruisce gli oggetti attore. Su Mac il totale è 0,134 ms/elemento, quindi
lì non vale la pena toccarli; sulla stick lo stesso lavoro pesa ~100 volte tanto ed è il prossimo
candidato, se serve.

Nota strutturale emersa dal test a freddo: la riga `PERF RETE` è comparsa **una volta sola**
(trakt_watchlist, 2237 ms per 21 voci). Tutte le altre costruzioni hanno trovato il 100% in cache,
perché il **filtro doppiaggio gira prima** e risolve già i metadati mancanti. `_resolve_missing`
è quindi una rete di sicurezza, non il percorso normale — il che è esattamente come deve essere.

## Correzione di un'etichetta sbagliata

La riga di rete riusava `log_prefetch` e stampava *"21 richiesti, 21 già in cache (100%)"*, che per
voci **non** in cache è un controsenso. Sostituita con `log_network`, che dice il numero di voci
risolte e il costo per voce.

## Perché la prova che conta è sul Mi Stick

Il Mac ha confermato **correttezza** e ha misurato il guadagno di CPU (13x). Ma non può dire se
l'obiettivo è raggiunto, per due motivi:

1. **Su Mac le chiamate C++ non erano mai state il collo di bottiglia.** Il fattore 74x
   dell'effetto convoglio è stato misurato *sulla stick*: 4 core, GIL conteso, ogni passaggio di
   consegne fino a 5 ms. Il Mac ne vedeva una versione attenuata (parallelismo ~2,1 contro ~5).
2. **La stabilità si manifesta solo lì.** I due riavvii sono avvenuti sulla stick, e la riduzione
   di thread vivi e oggetti temporanei è proprio ciò che dovrebbe cambiare quel quadro.

Sulla stick, con il pool, il costo era **49,85 ms/elemento** di somma thread. Se il convoglio è
davvero la causa, deve scendere di un ordine di grandezza.

---

# Lotto 21 — il verdetto sul Mi Stick, letto per intero

## Stabilità: risolta

Sessione di 11 minuti, molte pagine, una ricerca, due riproduzioni: **nessun crash, nessun
riavvio**. Il carico di CPU crollato è la spiegazione plausibile, anche se non dimostrata.

## Il lavoro di CPU: −7,7×

Somma dei tempi di thread, stessa stick, stesse liste: **da 49,85 a 6,5 ms/elemento** a sessione
fresca. Il profilo delle fasi è quello previsto: `ctxmenu` da 37% a 5%, `props` da 23% a 2%.

## Ma il tempo di parete non è migliorato sulle liste grandi

Questa è la parte che va detta chiaramente, perché contraddice l'aspettativa:

| elementi | con pool | in sequenza | delta |
|---|---|---|---|
| 48 ~ 47 | 2,22 s | **0,86 s** | 2,6x |
| 54 | 2,72 s | **1,34 s** | 2,0x |
| 131 ~ 130 | 1,31 s | 1,39 s | **0,9x** |
| 248 | 2,34 s | 2,35 s | **1,0x** |

Liste piccole molto meglio, liste grandi **invariate**.

La ragione è nei numeri: sulla stick il pool otteneva un parallelismo **reale di 3,6–4,1×**, molto
più dei ~2,1× visti su Mac. Quindi il pool pagava un'inflazione da convoglio di 7,7× ma la
divideva per 4. Togliendolo abbiamo eliminato l'inflazione e perso il parallelismo: sulle liste
grandi le due cose si annullano.

Sulle liste piccole no, perché lì dominava il costo fisso di avvio del pool — ed è sparito.

**Non è una sconfitta**: 7,7× di lavoro di CPU in meno significa meno calore, meno contesa con il
thread di rendering, meno consumo. Ma va registrato che *la costruzione delle liste lunghe non è
diventata più rapida*, e credere il contrario sarebbe stato un errore di lettura.

### Il margine che ne deriva

Sequenziale e pool-a-6 sono i due estremi. In mezzo c'è un **pool piccolo (2–3 worker)**: abbastanza
per usare i core, troppo poco perché il convoglio sul GIL esploda. Con 880 ms di lavoro reale su
248 elementi, anche solo 2 worker con inflazione 2× darebbero ~880 ms di parete contro i 2350
attuali. È un'ipotesi, ma costa una riga e una prova.

## Il degrado durante la sessione: reale, e NON è nostro

Il rallentamento percepito è nel log:

| | ms/elemento |
|---|---|
| prima della 1a riproduzione (16:04–16:08) | **6,5** |
| dopo (16:09–16:14) | **14,6** |

La prova che non dipende dal nostro codice è l'autotest sintetico, che esegue **codice identico**
a ogni giro, indipendente da liste e cache:

```
addContextMenuItems (7 voci):  mediana 0,17 ms  ->  0,71 ms   (4x)
lettura unica su 248 elementi:        554 ms   ->  1737 ms    (3x)
```

Stessa operazione, stessi dati, tre volte più lenta a fine sessione. È il dispositivo che degrada —
memoria frammentata, throttling termico, stato accumulato di Kodi. Non c'è una perdita nel nostro
percorso: se ci fosse, l'autotest sintetico non ne risentirebbe.

## Le inefficienze di codice che restano, misurate

Profilo a sessione fresca (media sui campioni puliti):

| fase | quota | cos'è |
|---|---|---|
| `prep+cm` | **~48%** | 7 `build_url` per elemento + estrazione + menu |
| `infotag` | ~19% | una ventina di setter |
| `cast` | ~17% | 20 oggetti `xbmc.Actor` costruiti per elemento |
| tutto il resto | ~16% | |

Non è più C++: è **Python nostro**. E dentro `build_url` la distribuzione è netta:

```
more_like_this (contiene il TITOLO)   21%
options        (contiene il POSTER)   20%
watched_status (contiene il TITOLO)   16%
                                      --
le tre con stringhe lunghe da codificare: 58%
```

Il poster è un URL da ~70 caratteri e il titolo può essere lungo: entrambi vanno percent-encodati
a ogni elemento, per parametri che servono **solo se l'utente apre quella voce**.

## Dove lavorerei, in ordine

1. **Pool piccolo per la costruzione** — una riga, e recupera il parallelismo perso senza
   ripagare il convoglio. È il candidato con il rapporto valore/rischio migliore.
2. **Togliere poster e titolo dalle URL** — si passa il solo `tmdb_id` e il gestore risolve il
   resto quando serve. Taglia più della metà del 48%.
3. **`CAST_LIMIT`** — 17% per venti attori di cui la skin mostra una lista di nomi. Scendere a
   8–10 è una scelta di prodotto, non un'ottimizzazione: cambia cosa si legge nel pannello trama.

---

# Lotto 22 — numero di worker del pool impostabile dall'utente

## Perché una impostazione e non una costante

Il lotto 21 ha lasciato una domanda aperta a cui **non si può rispondere con un numero fisso**: sul
Mi Stick il pool consegnava 3,6–4,1× di parallelismo reale ma pagava il convoglio del GIL; sul Mac
il sequenziale batte già il pool (0,24 contro 0,32 ms/elemento). Due dispositivi, due ottimi
diversi. E il valore automatico attuale non è il risultato di una misura:

```python
_WORKER_COUNT = max(4, min((os.cpu_count() or 4) + 2, 10))
```

Sul Mi Stick (4 core) dà **6**. Non perché 6 sia stato misurato: perché è `cpu_count + 2`.

C'è anche un moltiplicatore che la formula ignora: la home costruisce **più widget insieme**, quindi
i thread vivi contemporaneamente sono `worker × widget`. Con 6 worker e 4 widget sono 24 thread che
si contendono il GIL su una stick da 1 GB. È lo scenario in cui il convoglio pesa di più, ed è
esattamente lo scenario che l'utente incontra all'apertura.

Quindi: si rende il numero regolabile e **si misura**, invece di scegliere.

## Cosa è cambiato

**`modules/utils.py`** — la costante diventa una funzione letta a ogni creazione di pool:

```python
_WORKER_AUTO = max(4, min((os.cpu_count() or 4) + 2, 10))

def worker_count():
	try:
		value = int(get_property('fenlight.pool_workers') or 0)
	except: value = 0
	return value if value > 0 else _WORKER_AUTO
```

`0` significa automatico, cioè il comportamento di prima: **con l'impostazione al default nulla
cambia**. La lettura passa dalla property della finestra e non da `modules.settings`, perché
`utils.py` è importato praticamente ovunque e non deve tirarsi dietro `caches.settings_cache`.
Costa una chiamata per pool creato, non per elemento.

Le tre funzioni `make_thread_list`, `make_thread_list_multi_arg`, `make_thread_list_enumerate`
usano `worker_count()`. Essendo letta a ogni pool, l'impostazione ha effetto **subito**, senza
riavviare Kodi: è la differenza fra fare quattro prove in dieci minuti e farne quattro in un'ora.

**`caches/settings_cache.py`** — nuova voce accanto a `limit_concurrent_threads`:

```python
{'setting_id': 'pool_workers', 'setting_type': 'action', 'setting_default': '0',
	'settings_options': {'0': 'Auto', '1': '1', '2': '2', '3': '3', '4': '4', '6': '6', '8': '8', '10': '10'}},
```

**`resources/skins/Default/1080i/settings_manager.xml`** — voce "Thread Pool Workers" in
General, sotto "Maximum Active Threads".

**`modules/paginator.py`** — le due righe di log che contano ora stampano il numero di worker:

```
FenLight PERF      ... | worker 6 | totale 2.41s = risoluzione ... + costruzione ...
FenLight PERF FASI ... | worker 6 | somma thread ... ms | ...
```

Senza questo, confrontare due log significherebbe fidarsi del ricordo di come era impostato il
dispositivo in quel momento.

## Come leggere le due righe insieme

Le due misure rispondono a domande diverse e vanno lette in coppia:

- `PERF ... ms/elemento` è **tempo di parete**: è quello che l'utente sente. È la metrica da
  ottimizzare.
- `PERF FASI ... somma thread` è la **somma dei tempi di thread**. Rapporto fra le due =
  parallelismo reale ottenuto.

Con meno worker la somma-thread deve **scendere** (meno convoglio) e il parallelismo **scendere**
anch'esso. Il numero giusto è quello dove il tempo di parete tocca il minimo — non quello dove la
somma-thread è più bassa.

## Protocollo di prova

Su **entrambi** i dispositivi, stessa lista e stesso ordine, con la cache già calda (così si misura
CPU e non rete, che è il focus dichiarato):

1. Impostazioni Fen Light → General → **Thread Pool Workers**
2. Prova con `Auto`, poi `1`, poi `2`, poi `3`
3. Per ogni valore: aprire la stessa lista lunga (~130 e ~248 elementi) e la home con i widget
4. Riavviare Kodi fra un valore e l'altro **se possibile** — il lotto 21 ha dimostrato che la stick
   degrada durante la sessione (autotest sintetico 0,17 → 0,71 ms), quindi provare quattro valori
   di fila senza riavviare farebbe sembrare peggiore semplicemente l'ultimo provato
5. Alternativa se il riavvio è scomodo: provare nell'ordine `1, 2, 3, Auto` e poi **ripetere `1`
   alla fine**. Se il secondo `1` è molto peggiore del primo, il degrado di sessione sta sporcando
   la misura e i confronti vanno rifatti a freddo.

Da confrontare, per ogni valore: `ms/elemento` (parete), `somma thread`, e il rapporto fra i due.

## Verifiche fatte

- `python3 -m py_compile` sui tre moduli toccati: OK
- controllo AST dei simboli su tutti i moduli: nessun simbolo mancante introdotto (restano i **tre
  problemi preesistenti** di `router.py`, mai toccato da noi: `add_to_history`, `show_text_media`,
  `set_view`)
- `git diff --numstat` riga per riga: `utils.py 17/7`, `paginator.py 14/4`,
  `settings_cache.py 2/0`, `settings_manager.xml 8/0` — tutte le rimozioni sono spiegate dalle
  sostituzioni fatte, nessuna riga sparita di troppo
- XML della finestra impostazioni: parsing OK

---

# Lotto 23 — le URL delle voci: via `urlencode`, via poster e titolo

## La misura che ha cambiato il piano

Il piano era "togliere poster e titolo dalle URL". Misurando prima di scrivere è venuto fuori che
il grosso stava altrove:

```
8 build_url di un elemento film, come erano       32,67 us
le stesse senza poster e senza titolo             25,49 us     -22%
le stesse per formattazione diretta                0,92 us     -97%
```

Togliere le stringhe lunghe vale il 22%. Non chiamare `urlencode` vale il 97%. Sulle serie, dove
un elemento costruisce dieci URL e sette portavano testo libero:

```
10 URL di un elemento serie, come erano           45,03 us
per formattazione diretta                          1,41 us     -97%
```

Il riscontro con il log del Mac: `prep+cm` su 249 elementi misurava **9 ms**, e 32,67 us × 249 =
**8,1 ms**. Quella fase era `build_url` e basta.

## Perché `urlencode` costava tanto per non fare nulla

`urlencode` non sa che i valori sono sicuri: costruisce la lista delle coppie, chiama `quote_via`
su ogni chiave e ogni valore, e `quote_plus` scandisce **carattere per carattere** anche una
stringa come `movie` o un intero. Su una voce di menu i valori sono id numerici, id imdb `tt...`,
booleani e letterali: non c'è **niente** da percent-encodare. Il lavoro era tutto a vuoto.

La sostituzione è un template di modulo per URL:

```python
_BASE = 'plugin://plugin.video.fenlight/?'
URL_OPTIONS = _BASE + 'mode=options_menu_choice&content=movie&tmdb_id=%s&is_external=%s'
```

**Il vincolo che rende la cosa sicura, e che va rispettato in futuro:** qui dentro possono stare
solo valori che non hanno bisogno di codifica. Qualunque testo libero — titoli, nomi di raccolte,
URL di poster — deve tornare a passare da `build_url`, altrimenti la URL si rompe al primo spazio
o `&`. Per questo `open_movieset_choice` (che porta il nome della raccolta) è rimasto su `build_url`.

## Il testo libero: non accorciato, rimosso

Tre valori viaggiavano nelle URL solo per essere letti molto più tardi, se e quando l'utente
apriva quella voce. Ora nell'URL c'è il solo `tmdb_id` e il gestore rilegge il resto:

| valore | prima | adesso |
|---|---|---|
| `poster` (~70 caratteri) | in `options_params` di ogni elemento | `options_menu_choice` lo prende dai metadati, che leggeva già per conto suo |
| `title` in "More Like This" / "Recommended" | frase composta in ogni elemento | passa `name_id`, il nome si compone all'apertura della lista |
| `title` per "Segna come visto" | in ogni elemento | `mark_movie` / `mark_tvshow` lo rileggono (e `mark_tvshow` caricava già i metadati) |
| `title` per "In Trakt Lists" e "Preferiti" | in ogni elemento | risolti da `tmdb_id` all'apertura |
| `icon` (poster) per "Trakt Lists Manager" | in ogni elemento | risolto da `tmdb_id` all'apertura |

Costo spostato: **una lettura da cache quando l'utente clicca**, invece di una percent-codifica per
ogni elemento di ogni lista costruita.

**Tutti i vecchi parametri restano accettati.** `name`, `category_name`, `title`, `poster`, `icon`:
se presenti vincono. Serve perché ci sono URL già in giro — widget salvati nella home, e
`windows/extras.py` che chiama gli stessi gestori passando ancora `name` e `category_name`.

## File toccati

- `indexers/movies.py` — 11 template, `_resolve_more_like_this_name()`
- `indexers/tvshows.py` — 14 template, `_resolve_list_name()` con prefisso per azione
- `indexers/dialogs.py` — `meta_from_params()`; poster in `options_menu_choice` e
  `trakt_manager_choice`, titolo in `favorites_choice`
- `indexers/trakt_lists.py` — `name_id` in `get_trakt_lists_with_media`
- `modules/watched_status.py` — titolo in `mark_movie` e `mark_tvshow`

## Verifiche fatte

La verifica che conta: **le stringhe prodotte devono essere identiche byte per byte** a quelle che
`urlencode` avrebbe generato. Un errore qui non si vede alla costruzione della lista — si vede solo
cliccando la voce, magari settimane dopo.

`scratchpad/check_urls.py` legge i template **dalla sorgente** (via AST, non riscritti a mano) e
confronta ognuno con `urlencode` sugli stessi parametri, incluso il caso `imdb_id = None`:

```
OK: 27 URL identiche a urlencode
```

Inoltre: `py_compile` sui cinque moduli, controllo AST dei simboli su tutti i moduli (restano i soli
tre problemi preesistenti di `router.py`), e riconciliazione riga per riga di `git diff --numstat`
— le 23 righe rimosse da `tvshows.py` e le 15 da `movies.py` sono esattamente quelle sostituite.

## Cosa verificare sul dispositivo

Le misure sopra sono di micro-benchmark: dicono quanto costa il codice, non quanto si guadagna a
schermo. Nel log va guardata la quota di **`prep+cm`**, che era 55–58%: se il ragionamento regge
deve crollare, e le altre fasi devono salire di quota **senza salire in millisecondi**.

Da provare a mano, perché sono i percorsi che ora risolvono a valle:

1. menu contestuale → **Opzioni** (l'icona del poster nel dialogo deve esserci ancora)
2. tasto rapido **Opzioni** e **More Like This** (leggono le proprietà della listitem)
3. **Browse More Like This** e **Browse Recommended**: il titolo della schermata deve dire
   "More Like This based on ..." / "Recommended based on ...", non "Movies" o "TV Shows"
4. **In Trakt Lists** (titolo della schermata) e **Trakt Lists Manager** (icona)
5. **Segna come visto** su un film, poi aprire la lista **Visti**: il titolo deve comparire e
   l'ordinamento alfabetico deve funzionare — è la prova che il titolo è finito nel database
6. **Preferiti** su una serie: il nome salvato deve essere quello giusto

---

# Lotto 23 bis — il risultato misurato sul Mac

Stessa lista, stessi 249 elementi, tutti da cache (`mdblist 91378`):

| fase | prima | dopo |
|---|---|---|
| **somma thread** | 16 ms | **9 ms** |
| `prep+cm` | 9 ms (57%) | **2 ms (23%)** |
| `infotag` | 1 ms (9%) | 1 ms (17%) |
| `cast` | 4 ms (23%) | 4 ms (43%) |

`prep+cm` **−78%**. Il micro-benchmark prevedeva 7,9 ms di risparmio su 249 elementi, la misura in
Kodi ne dà 7: previsione e realtà coincidono, quindi il meccanismo era quello giusto.

La controprova: `infotag` e `cast` sono **identici in millisecondi** e salgono solo di quota. È il
comportamento atteso se il taglio ha colpito `build_url` e non ha spostato lavoro altrove.

## Una precisione del log che avevo dichiarato e non fatto

Nel messaggio precedente avevo detto di aver corretto la granularità di `costruzione`. Non l'avevo
fatto: il codice stampava ancora `%.2fs`, cioè 10 ms di risoluzione su misure da 20-40 ms. Adesso:

```
... | costruzione 24 ms (0.096 ms/elemento) | 0.5 ms/elemento totale
```

---

# Lotto 24 — il cast: niente più `setCast` nelle liste

## Cosa costava, e per cosa

`cast` era diventata la voce singola più grossa della costruzione: **43%**, 4 ms su 249 elementi.
Sono venti oggetti `xbmc.Actor` per elemento — quasi **cinquemila** per una lista da 250 — più la
chiamata `setCast`, ciascuno un attraversamento verso il C++ di Kodi.

Per cosa? La skin legge il cast in **un solo punto**:

```
Includes_Labels.xml:997  Label_Overlay_TopCast  ->  $INFO[ListItem.Cast]
      -> Label_Overlay_PlotBox -> Dialog_DialogPlot.xml:54
```

Cioè il pannello trama, che si apre solo se l'utente lo chiede. `DialogVideoInfo.xml` della skin non
mostra cast (87 righe, nessun riferimento), e la skin di Fen Light nemmeno.

## Perché non serviva un servizio

L'idea iniziale era pubblicare il cast su richiesta all'apertura del dialogo, sul modello di
`blur_service.py`. Non serve, per un dettaglio di come Kodi compone `ListItem.Cast`:

```cpp
// CVideoInfoTag::GetCast(bIncludeRole = false)
strLabel += StringUtils::Format("{}\n", castItem.strName);
```

Sono **i soli nomi separati da un a capo**. Nessun ruolo, nessuna miniatura. Quindi la stessa
stringa si compone in Python con una `join`, e finisce nella `setProperties` che l'elemento fa
**comunque**: zero attraversamenti in più verso il C++, e nessun servizio, nessuna asincronia,
nessun ritardo alla prima apertura del pannello.

`kodi_utils.cast_label()` fa esattamente questo. Le miniature degli attori non si perdono: la
finestra Extras costruisce la sua lista Cast dai metadati (`windows/extras.py:156`), non dalla
listitem.

## File toccati

- `modules/kodi_utils.py` — `cast_label()`
- `indexers/movies.py`, `tvshows.py`, `episodes.py` (due punti), `seasons.py` — via `setCast`,
  la proprietà `fenlight.cast` entra nella `setProperties` già presente
- `skin.arctic.fuse.3/1080i/Includes_Labels.xml` — `Label_Overlay_TopCast` legge la proprietà, con
  `ListItem.Cast` come ripiego per gli elementi che non vengono da Fen Light (libreria Kodi, altri
  addon)

In `seasons.py` il cast è quello della serie, uguale per tutte le stagioni: si compone **una volta**
fuori dal ciclo.

## Un bug che ho scritto e corretto

La prima versione in `seasons.py` metteva `_cast_names` nella `set_properties` di riga 68 e lo
assegnava a riga 79 — **dentro lo stesso ciclo**. Prima iterazione: `UnboundLocalError`, ingoiato
dal `except: pass` dell'indexer, quindi prima stagione mancante e nessuna traccia nel log. È
esattamente la classe di errore del lotto 19: sintassi valida, simboli tutti esistenti.

Il controllo generico "uso prima dell'assegnazione" su tutti i moduli non è utilizzabile: dà 228
segnalazioni, quasi tutte false (chiusure e cicli preesistenti). Al suo posto, un controllo mirato
che per ogni nome introdotto stampa **in quale funzione** avviene assegnazione e lettura:

```
seasons.py   cast_names
    assegnato  riga 97    in build_season_list()
    letto      riga 68    in _process()
```

Chiusura legittima: `_process()` viene consumato a riga 108, dopo l'assegnazione. Negli altri tre
file assegnazione e lettura sono nella stessa funzione, in quest'ordine.

## Cosa verificare sul dispositivo

Nel log, `cast` deve crollare da ~43% a una quota trascurabile, **senza che le altre fasi crescano
in millisecondi**.

A mano — il punto è uno solo, ma va guardato su ogni tipo di elemento perché sono quattro builder
diversi: aprire il **pannello trama** e controllare che la sezione cast ci sia ancora e mostri gli
stessi nomi, su **film**, **serie**, **stagione** ed **episodio**.

---

# Da riprendere

- **Widget watchlist non si aggiorna** dopo aver aggiunto un film alla watchlist Trakt dal menu
  contestuale (rilevato il 2026-08-16). Da verificare insieme al funzionamento della
  sincronizzazione periodica con Trakt.
- Impostazione `pool_workers` (lotto 22): resta in piedi, il default non cambia nulla. Vale solo
  per la fase di rete, dato che la costruzione è sequenziale.
- Rimozione della strumentazione `PERF` / `PERF_SELFTEST` quando le ottimizzazioni si chiudono.

## Lotto 24 — il cast non compariva più nel pannello trama

Il lato Python era corretto: nel log `cast` è sceso da 43% (4 ms su 249) a 9% (0,4 ms), e la somma
thread da 9 a 5 ms. La stringa quindi si compone e finisce nella `setProperties`. Il difetto era
nella riga di skin che avevo scritto io:

```xml
<!-- sbagliata -->
<value condition="!$EXP[...] + !String.IsEmpty(ListItem.Property(fenlight.cast))">$INFO[ListItem.Property(fenlight.cast)]</value>
<value condition="!$EXP[...]">$INFO[ListItem.Cast]</value>
```

Il sintomo — **niente cast**, non nomi attaccati o sbagliati — dice che il valore non arriva proprio
al textbox, quindi non è la stringa ma la selezione del valore. `String.IsEmpty(ListItem.Property(...))`
dentro la condizione di una variabile di skin non è affidabile quando manca il contesto
dell'elemento, che è esattamente il caso di un dialogo: la condizione risulta falsa, si passa al
secondo valore, e `ListItem.Cast` ora è vuoto perché `setCast` non c'è più. Doppio buco.

La correzione toglie il problema invece di aggirarlo: **i due `$INFO` si concatenano**, senza
condizione. Uno dei due è sempre vuoto per costruzione — gli elementi Fen Light non hanno più il
cast nell'info tag, quelli della libreria Kodi non hanno la proprietà:

```xml
<value condition="!$EXP[Exp_TMDbHelper_IsData]">$INFO[ListItem.Property(fenlight.cast)]$INFO[ListItem.Cast]</value>
```

Il controllo XML ha intercettato per strada un secondo errore mio: `--` non è ammesso dentro un
commento XML. Da qui in poi la verifica gira su **tutti** i file XML della skin, non solo su quello
toccato.

### Se non basta

Se dopo questa correzione il cast continua a non comparire, la causa non è la condizione ma il
fatto che dentro il dialogo `ListItem.Property()` non si risolva affatto. In quel caso la strada è
già tracciata e collaudata in questo repo: `blur_service.py` legge dal vivo `ListItem.<token>` e
pubblica su `Window(Home)` (`TMDbHelper.ListItem.base_poster`, `base_label`) proprio perché lo
scope del dialogo non arriva alla lista. Basterebbe aggiungere il cast a quei token e leggere
`Window(Home).Property(...)` come terzo ripiego. Costo per la costruzione delle liste: zero in
entrambi i casi.

### La diagnosi giusta: era un'altra finestra

Avevo guardato il **pannello trama** (dialogo 1113). La "pagina informazioni" è un'altra cosa:
è `movieinformation`, cioè il `DialogVideoInfo` di Kodi, e la sua riga Cast è il **contenitore 50**,
che Kodi riempie **dal C++** leggendo il cast dell'info tag. Nessuna proprietà può alimentarlo:
quella riga si popola solo con `setCast`. La mia correzione precedente era puntata sul dialogo
sbagliato.

Ma la strada on demand esisteva già, ed era spenta da un residuo di TMDbHelper.
`Includes_DialogInfo.xml` ha **due** righe Cast alternative:

| riga | contenuto | condizione originale |
|---|---|---|
| locale (299) | contenitore 50 riempito da Kodi dall'info tag | `![!UseLocalCast + TMDbHelperData]` |
| servita (314) | `<content>` = `$VAR[Path_VideoInfo_OnlineCast]` | `!UseLocalCast + TMDbHelperData` |

E `Path_VideoInfo_OnlineCast` (`Includes_Paths.xml:254`) **punta già a Fen Light**:

```
plugin://plugin.video.fenlight/?mode=build_cast_list&media_type=...&tmdb_id=$INFO[Window.Property(FenLight.TMDb_ID)]
```

`DialogVideoInfo.xml:11-12` imposta già `FenLight.TMDb_ID` e `FenLight.DBType` in `onload`, e
`indexers/people.build_cast_list()` esiste e serve la directory del cast leggendo i metadati da
cache. Tutto pronto: mancava solo che la condizione non richiedesse più TMDbHelper, che in questo
fork non c'è.

Le due condizioni ora discriminano su **quello che conta davvero** — se l'elemento viene da Fen
Light — e restano esatte complementari, così le due righe non possono mai comparire insieme:

```
riga servita:  !Skin.HasSetting(Info.UseLocalCast) + [$EXP[Exp_TMDbHelper_IsData] | !String.IsEmpty(Window.Property(FenLight.TMDb_ID))]
riga locale:  ![ la stessa espressione ]
```

Gli elementi della libreria Kodi non hanno `FenLight.TMDb_ID`, quindi continuano a usare la riga
locale e il cast dell'info tag. L'interruttore di skin `Info.UseLocalCast` resta funzionante.

**Questo è l'on demand vero**: il cast si scarica dalla cache e si costruisce solo quando la
finestra informazioni si apre, per il singolo titolo richiesto. Zero costo su ogni elemento di
ogni lista.

La modifica precedente su `Label_Overlay_TopCast` resta: serve al **pannello trama**, che è un
percorso diverso e legge `ListItem`, non il contenitore 50.

### Terza diagnosi, questa volta con le prove

Ho sbagliato bersaglio due volte perché ho ragionato per ipotesi invece di guardare i fatti. I fatti,
raccolti dopo:

**1. `DialogVideoInfo` non era mai stata aperta.** `set_videoinfo_properties` è un `<onload>` di
`DialogVideoInfo.xml` che non ho toccato, e non compare in **nessuna** delle due sessioni di log.
Quindi la "scheda informazioni" non è quella finestra, e il lotto precedente era puntato altrove.

**2. `Label_Overlay_PlotBox` è usato in un solo punto di tutta la skin**: `Dialog_DialogPlot.xml:54`.
E `Label_Overlay_TopCast` solo dentro di esso. Quindi l'unico posto della skin che abbia mai
mostrato il cast di Fen Light è il **dialogo 1113**, comunque lo si apra. La voce "Informazioni" del
menu contestuale (`$LOCALIZE[207]`) è proprio `ActivateWindow(1113)`.

**3. In tutto quel pannello la skin non legge nemmeno una proprietà.** Tagline, plot, regia,
sceneggiatura, titolo: `ListItem.TagLine`, `ListItem.Plot`, `ListItem.Director`, `ListItem.Writing`,
`ListItem.Label`. Sono **tutti campi dell'info tag o campi core**. Nessun
`ListItem.Property(...)`, in un pannello che ne avrebbe mille occasioni.

Da qui la conclusione, che spiega ogni osservazione: **il dialogo 1113 risolve i campi dell'info tag
ma non le proprietà della listitem.** `ListItem.Cast` funzionava perché è un campo dell'info tag;
`ListItem.Property(fenlight.cast)` no. Nessuna delle due varianti di condizione che avevo provato
poteva funzionare.

### La correzione

La strada che quel dialogo sa leggere è già in uso nel repo: `blur_service.py` pubblica
`TMDbHelper.ListItem.base_poster` e `base_label` su `Window(Home)` **esattamente per questo motivo**.
Il cast prende la stessa strada:

- `blur_service.BlurService._publish_cast()` legge `ListItem.Property(fenlight.cast)` dall'elemento
  in focus (dal contesto della finestra media, dove le proprietà si risolvono) e lo ripubblica come
  `Window(Home).Property(FenLight.ListItem.Cast)`.
- La pubblicazione segue l'**identità** dell'elemento (l'etichetta), non il valore del cast: va
  riscritta anche a vuoto quando l'elemento cambia, altrimenti il pannello mostrerebbe gli attori
  del titolo precedente — errore peggiore del non mostrarne nessuno.
- Sta **prima** del cancello `Skin.HasSetting(TMDbHelper.EnableBlur)`: il cast non c'entra con la
  sfocatura e deve funzionare anche a sfocatura spenta.
- Costo: una `getInfoLabel` per ciclo da 0,3 s, e una seconda solo quando l'elemento cambia.

Nella skin la condizione ora è `String.IsEmpty(Window(Home).Property(...))`, che è affidabile perché
**non dipende dal contesto dell'elemento** — a differenza di quella su `ListItem.Property` che avevo
scritto due giri fa. `ListItem.Cast` resta come ripiego per gli elementi non Fen Light.

La proprietà `fenlight.cast` sulla listitem resta: è ciò che il servizio legge. Il costo pesante —
i circa cinquemila oggetti `xbmc.Actor` per lista — non torna in nessun caso.

La modifica del giro precedente su `Includes_DialogInfo.xml` (riga Cast servita da Fen Light invece
che dall'info tag) resta anch'essa: è una pulizia corretta di un residuo di TMDbHelper, ma **non è
verificata**, perché quella finestra non risulta mai aperta nei log.

### La causa vera: una condizione valutata al caricamento, non all'apertura

Le due sezioni precedenti contengono due mie conclusioni sbagliate. Le lascio scritte perché
l'errore di metodo è più istruttivo della correzione.

**Errore 1 — ho scambiato l'assenza di prove per una prova.** Avevo dedotto che `DialogVideoInfo`
non fosse mai stata aperta perché `set_videoinfo_properties` non compariva nel log. Ma quello è un
`RunPlugin` che non scrive nulla: a livello di log normale non lascia traccia. La schermata era
quella giusta fin dal secondo giro, e da lì sono partito a inseguire il dialogo trama, il blur
service e le proprietà della Home — tutta roba che non c'entrava.

**Errore 2 — condizione dinamica in un punto statico.** La correzione al secondo giro era:

```xml
<include content="Widget_Info_Row" condition="!Skin.HasSetting(Info.UseLocalCast) + [$EXP[...] | !String.IsEmpty(Window.Property(FenLight.TMDb_ID))]">
```

Non poteva funzionare. La `condition` di un `<include>` è risolta **al caricamento della finestra**,
e il log lo dice:

```
Loading skin file: DialogVideoInfo.xml, load type: KEEP_IN_MEMORY
```

`KEEP_IN_MEMORY` significa caricata una volta all'avvio della skin. In quel momento
`Window.Property(FenLight.TMDb_ID)` è vuota, quindi la riga servita non è mai stata compilata nella
finestra. Il `<content>`, invece, è una **variabile**, e quelle sì vengono valutate all'apertura:
per questo `Path_VideoInfo_OnlineCast` funziona benissimo dov'è.

**Regola da ricordare**: nella `condition` di un `<include>` possono stare solo espressioni stabili
al caricamento della skin (`Skin.HasSetting`, `Skin.String`). Qualsiasi `Window.Property`,
`ListItem.*` o `Container.*` è vuota o irrilevante in quel momento.

### La correzione

Le due righe Cast si scelgono ora sul solo interruttore di skin, che è stabile al caricamento:

```
riga servita (Fen Light):  !Skin.HasSetting(Info.UseLocalCast)      <- predefinita
riga locale (info tag):     Skin.HasSetting(Info.UseLocalCast)
```

È coerente con l'interruttore che la skin già espone (`Dialog_DialogCustom.xml:1197`, dove
"selezionato" corrisponde proprio a `!Skin.HasSetting(Info.UseLocalCast)`). Con l'impostazione al
suo valore predefinito si usa la riga servita, cioè
`build_cast_list` di Fen Light: **cast on demand, caricato all'apertura della finestra**, nomi e
foto, e cliccando un attore si apre la sua scheda (`DialogInfo_Widgets_Action` legge `tmdb_id` e
`tmdb_type`, che `build_cast_list` scrive su ogni elemento).

### Cosa ho rimosso

- `blur_service.py`: tolto `_publish_cast` e la sua chiamata. Serviva al dialogo trama, che non è
  la schermata giusta, e costava una `getInfoLabel` ogni 0,3 s. Il file è tornato identico all'originale.
- `Label_Overlay_TopCast` è tornato alla forma concatenata, senza dipendenze dal servizio. Quel
  pannello non è la schermata dove il cast conta.

### Il fatto che mancava: le impostazioni della skin

Ho continuato a scrivere condizioni basate su `Skin.HasSetting` senza mai andare a leggere il valore
di quei flag. Sono in
`userdata/addon_data/skin.arctic.fuse.3/settings.xml`, e dicono:

```
info.uselocalcast     = true
tmdbhelper.enabledata = true
```

Due conseguenze, entrambe fatali per i giri precedenti:

1. La riga Cast servita da Fen Light la compilavo con `!Skin.HasSetting(Info.UseLocalCast)`, e quel
   flag è **acceso**. Restava compilata la riga locale, che senza `setCast` è vuota.
2. `Exp_TMDbHelper_IsData` è **vera**, quindi `Label_Overlay_TopCast` (che ha
   `condition="!$EXP[Exp_TMDbHelper_IsData]"`) non produce nulla in nessun caso: tutte le modifiche
   che gli avevo fatto erano codice morto in partenza.

### La correzione definitiva

Le due righe non potevano restare entrambe compilate: passano `altvisible=true`, quindi si vedono
**anche da vuote** (`Includes_Widgets.xml:66`), e si sarebbero viste due intestazioni "Cast".

Quindi la riga locale è stata **rimossa** e quella servita da Fen Light è ora **incondizionata**.
La riga locale non aveva più una sorgente: `setCast` non c'è più sugli elementi delle liste, ed era
proprio quello il costo che volevamo togliere. Come effetto collaterale, l'impostazione di skin
`Info.UseLocalCast` non ha più effetto sul cast.

Il cast ora è davvero on demand: `build_cast_list` viene chiamata quando si apre la scheda, legge i
metadati da cache e restituisce nomi e foto; cliccando un attore si apre la sua scheda, perché
`DialogInfo_Widgets_Action` legge `tmdb_id` e `tmdb_type`, che `build_cast_list` scrive su ogni voce.

### Da segnalare, separato

`tmdbhelper.enabledata = true` con TMDbHelper disinstallato: molti rami della skin prendono la
strada TMDbHelper e non trovano nulla. È probabilmente all'origine anche del prompt "installa
TMDbHelper" già annotato. Non l'ho toccato perché spegnerlo cambia decine di condizioni in una volta
(per esempio le righe Recommended e Collection della scheda informazioni sono compilate **solo** se
quel flag è vero): è una pulizia a sé, da fare con calma. La riga del cast ora è incondizionata,
quindi funziona con il flag in entrambi gli stati.

### Metodo, per non ripetere il giro

Tre errori in fila, tutti dello stesso tipo: **ho dedotto invece di guardare**.
Assenza nel log presa per prova (le `GetDirectory` riuscite sono solo in debug); condizione
dinamica messa dove viene valutata solo al caricamento; valore di un flag dato per scontato invece
di leggerlo da `settings.xml`. Prima di scrivere una condizione di skin: leggere il file delle
impostazioni, e verificare **quando** quella condizione viene valutata.

---

# Lotto 25 — rimossa l'impostazione sui worker del pool (lotto 22)

Tolta perché non serve a niente e può fare danno.

**Non serve**: dal lotto 20 la costruzione delle listitem gira in sequenza, quindi quei pool restano
solo sulla fase di **rete**, che è fuori dal campo di ottimizzazione dichiarato. La prova sul Mac
(Auto contro 6) non aveva prodotto nessun segnale, per costruzione.

**Può fare danno**: abbassare i worker sulla fase di rete non riduce nessun convoglio del GIL — lì
l'attesa è I/O e il GIL è rilasciato davvero — serializza soltanto. Con 2 worker una pagina di 20
elementi non in cache fa 10 giri di rete invece di 2.

`_WORKER_COUNT` torna costante, rinominata `WORKER_COUNT` perché `paginator.py` la importa per
stamparla nel log. Rimosse: la voce in `default_settings`, la riga nella finestra impostazioni,
`worker_count()`. `blur_service.py` e `settings_manager.xml` sono tornati identici a HEAD.

## Un difetto delle mie riscritture scriptate: le terminazioni di riga

`git diff --numstat` dava **502 aggiunte / 502 rimozioni** su `settings_cache.py` per una rimozione
di due righe. Causa: i file del repo sono **CRLF**, e i miei script li riscrivevano con
`io.open(path, 'w')`, che su macOS scrive LF. Ogni riga risultava modificata.

Non cambia niente per Python, ma rende il diff illeggibile e nasconde gli errori veri — che è
esattamente il modo in cui il lotto 19 era passato inosservato. Quattro file erano stati convertiti
(`settings_cache.py`, `episodes.py`, `seasons.py`, `utils.py`); CRLF ripristinato ovunque. Dopo il
ripristino `settings_cache.py` non ha **nessuna** differenza rispetto a HEAD, come dev'essere.

**Regola**: dopo una riscrittura scriptata, controllare le terminazioni di riga insieme ai simboli.
Se `--numstat` riporta un numero di righe vicino al totale del file, è quasi sempre questo.

---

# Lotto 26 — il log della stick del 2026-08-16 18:21: cosa dice davvero

## Primo: quella stick monta ancora il codice vecchio

Le righe PERF non contengono `worker N` e stampano `costruzione 2.49s` invece di
`costruzione X ms (Y ms/elemento)`. Sono il formato precedente al lotto 22. Conferma dal profilo:

| | prep+cm | cast |
|---|---|---|
| stick, questo log | ~50% | ~20% |
| Mac **prima** dei lotti 23-24 | 57% | 23% |
| Mac **dopo** | 23% | 43% |

Quindi i numeri di questo log **non misurano** i lotti 23 e 24. Marcatore rapido per la prossima
prova: se nella riga `FenLight PERF` non c'è la parola `worker`, il codice è vecchio.

## Secondo: il rallentamento NON dipende dal numero di risultati

Stessa lista da 248 elementi, quattro costruzioni nella stessa sessione:

| ora | costruzione | ms/elemento | autotest sintetico |
|---|---|---|---|
| 18:23:46 | 2,37 s | 20,1 | 0,019 ms/chiave |
| **18:25:45** | **10,45 s** | **78,2** | **1,313 ms/chiave** |
| 18:25:58 | 9,02 s | 54,3 | 0,337 ms/chiave |
| 18:26:22 | 2,09 s | 22,8 | 0,017 ms/chiave |

Stessa lista, stesso codice, 4,6× di differenza, e poi il ritorno ai valori iniziali. La lunghezza
della lista non è la variabile.

## La variabile è la riproduzione video

Il filmato va da 18:24:30 a 18:24:52. Prima: tutto veloce. Nei ~90 secondi successivi: tutto lento.
Poi recupera e resta veloce fino a fine sessione.

L'autotest sintetico esegue **30 `setProperty` identiche** a ogni costruzione, senza toccare liste
né cache. È il termometro pulito:

```
18:23:46   0,019 ms/chiave
18:25:27   8,180 ms/chiave      <- subito dopo la riproduzione, 430x
18:26:22   0,017 ms/chiave      <- recuperato
```

Stesse chiamate, stessi dati, 430 volte più lente. Non è la costruzione delle liste: è lo stato di
Kodi/Android dopo aver tenuto aperto il decoder. Nel log compaiono anche tre
`CPythonInvoker(22, fenlight.py): waiting on thread` fra 18:24:52 e 18:24:58, cioè l'invocazione
della riproduzione che aspetta i propri thread in chiusura: vale la pena guardarci, ma è un
capitolo diverso dalla costruzione delle liste.

## Controprova: a sessione pulita non c'è degrado con la crescita

Sequenza finale di paginazione discover, tutta in periodo "pulito" (autotest stabile a 0,018):

| elementi | costruzione | ms/elemento |
|---|---|---|
| 27 | 0,29 s | 10,7 |
| 37 | 0,34 s | 9,2 |
| 50 | 0,37 s | 7,4 |
| 63 | 0,43 s | 6,8 |

Il costo per elemento **scende** al crescere della lista: l'avvio dell'interprete si spalma su più
elementi. Nessuna degradazione progressiva.

Il tempo di parete lì è 6-8 s a pagina, ma sta quasi tutto in `risoluzione` (5,7-7,6 s), con le
righe `DUB` che mostrano `rete: streaming 9-15` per pagina. È il filtro doppiaggio che va in rete.

## Cosa fare

1. **Risincronizzare davvero la stick** e ripetere. Senza `worker` nella riga di log la prova non
   vale. Attenzione ai `.pyc` tracciati in `__pycache__`.
2. Il degrado post-riproduzione è device-level e va affrontato a parte, non come ottimizzazione
   della costruzione.
3. Resta aperto `GetDirectory - Error getting &pages=12` (18:26:12), già annotato.

# Lotto 27 — il log della stick del 2026-08-16 18:32 e la riproduzione intoccabile

## Le ottimizzazioni ci sono e si misurano

Questa volta la stick monta il codice nuovo: `worker 6` nelle righe PERF e `costruzione N ms`.
Confronto solo fra campioni con lo **stesso stato del dispositivo** (autotest sintetico
0,019-0,036 ms/chiave), altrimenti si confrontano condizioni diverse e non codice:

| lista | prima | dopo | |
|---|---|---|---|
| 130 elementi | 7,95 ms/el | 2,45 | −69% |
| ~50 discover | 4,82 ms/el | 2,27 | −53% |
| ~30 discover | 6,63 ms/el | 2,38 | −64% |

Le due fasi attaccate, su 248 elementi: `cast` 301 ms (20%) → 24-34 ms (1%); `prep+cm`
737 ms (49%) → 173-292 ms (6-9%). Le altre fasi restano ferme a parità di stato: era il controllo.

## La stick ha spento un core a metà sessione

`WORKER_COUNT = max(4, min(cpu_count + 2, 10))`, e su Android `os.cpu_count()` conta i core
**online**. Nel log: `worker 6` fino alle 18:34:41, poi `worker 5` fino alla fine. `worker 5` si
ottiene solo con `cpu_count = 3`. La stick ha spento un core alle ~18:35 e non l'ha più riacceso —
gestione termica di Android, non nostro codice. È il 25% della CPU che sparisce a metà sessione, e
spiega il "peggiora man mano che la uso" molto meglio della lunghezza delle liste.

Effetto collaterale utile: il numero di worker nella riga di log è diventato un **sensore di
throttling gratuito**. Vale la pena non toglierlo.

## Perché la riproduzione laggava

Film da 18:36:25 a 18:37:19. Dentro quella finestra: ~20 righe `PERF DUB`, una build da 54 elementi
(3552 ms) e una da 248 (`risoluzione 15,57 s + costruzione 5826 ms`). In parallelo Kodi scrive
decine di `ActiveAE - large audio sync error: -1000...-1630` e `OutputPicture - timeout waiting for
buffer`. Controprova sulla stessa quantità di dati: la lettura da cache di 248 elementi costa
**2412 ms durante il film** contro **904 ms** subito dopo.

Non è il decoder: gli stavamo togliendo la macchina da sotto.

## Cosa è stato cambiato

Tutti i servizi (`TraktMonitor`, `WidgetRefresher`, `WidgetPaginator`, `BlurService`) avevano già la
guardia `is_playing()`. Il buco era altrove.

1. **`kodi_utils.kodi_refresh()` / `refresh_widgets()`** — è qui il vero innesco. `kodi_refresh` fa
   `UpdateLibrary(video,...)`, un evento **globale** che ricostruisce ogni widget della schermata,
   ognuno con un interprete Python nuovo, e ha una dozzina di chiamanti (Trakt, cache, watched
   status, menu editor, ricerca). Ora entrambe controllano `Player.HasVideo`: se un video è in
   corso la richiesta **non viene persa**, si annota in `fenlight.refresh_pending` e viene eseguita
   alla chiusura. Gatire qui invece che sui singoli chiamanti copre anche gli innescatori che non
   avevo identificato con certezza nel log.
2. **`player.py` — Trakt solo a inizio e fine.** Tolto il rinvio periodico dello scrobble ogni 120s
   e la sua riattivazione a ogni seek. Tolta anche la marcatura del visto al 90% mentre il film
   ancora va: ora tutto avviene una volta sola all'uscita dal ciclo, con la percentuale reale di
   chiusura. Trakt riceve **uno start all'avvio e uno stop alla chiusura**.
3. **`player.flush_pending_refresh()`** — alla fine della riproduzione rilancia il refresh rimandato,
   dopo 3s per lasciar passare prima quello del segnalibro (che parte dopo 2s e azzera la stessa
   proprietà): si ricostruisce una volta sola invece di due.
4. **`WidgetRefresher`** — rete di sicurezza: se il video non è passato da `FenLightPlayer` (video
   generico, trailer) nessuno rilancerebbe il refresh rimandato; il servizio lo recupera entro 10s
   dalla fine.
5. **`CustomFonts`** — era l'unico servizio che durante la riproduzione continuava a lavorare
   (`execute_custom_fonts()` ogni 20s invece di 10). Ora si ferma del tutto.

## Effetto collaterale: chiuso il widget che non si aggiornava

`mark_movie`/`mark_episode` con `from_playback` impostano `refresh = False`, quindi **finire un film
non aggiornava mai i widget** — era il problema segnalato e messo da parte. Il commento in
`player.py` diceva il contrario ("kodi_refresh is already called internally"): era falso. Ora la
marcatura chiede il refresh, ed è sicuro proprio perché il gate lo rimanda a fine riproduzione:
passando all'episodio successivo non si ricostruisce nulla mentre il video va.

## Distinzione che ho tenuto

È stata eliminata la costruzione di interfaccia **automatica/di sfondo** durante la riproduzione. La
navigazione avviata dall'utente mentre il film va non è bloccata: se si esce dal video a sfogliare
una lista, quella lista va costruita, altrimenti l'interfaccia si svuota.

## Dove non conviene più insistere

Su un campione pulito: `totale 3,15 s = risoluzione 2,81 s + costruzione 338 ms`. La costruzione è
ormai il **10%** del tempo di parete; anche dimezzandola ancora si guadagnerebbe il 5%. Il tempo sta
in `risoluzione`, cioè rete e filtro doppiaggio — che era stato messo fuori campo e a questo punto
va rimesso in discussione. Se proprio si volesse continuare sulla CPU il candidato sarebbe
`infotag` (33-44% del residuo, ~20 setter per elemento), ma non con quel 10%.

## Nota di metodo

L'autotest sintetico in questa sessione varia da 0,019 a 1,457 ms/chiave: 75x, a codice identico.
Due misure prese in stati diversi non sono confrontabili. Senza leggere prima quel valore avrei
letto un peggioramento dove c'è un −69%.

## Da verificare sul dispositivo

1. Avviare un film e **guardarlo senza toccare nulla**: nel log non devono comparire righe `PERF`
   fra `OpenFile` e `CloseFile`, né `ActiveAE - large audio sync error`.
2. Finire un film (oltre il 90%) e controllare che il badge "visto" compaia e che i widget
   (cronologia, watchlist) si aggiornino **dopo** la chiusura.
3. Chiudere un film a metà e controllare che il punto di ripresa sia corretto.
4. Con `autoplay next episode`: passando all'episodio successivo non deve ricostruirsi nulla; il
   refresh deve arrivare solo alla fine dell'ultimo episodio.
5. Trakt: verificare che l'elemento risulti "in riproduzione" all'avvio e venga chiuso alla fine.
   **Compromesso accettato**: senza il rinvio ogni 120s, se Kodi viene ucciso a metà film Trakt
   resta con uno scrobble aperto e non si registra nulla. Prima il rinvio periodico lo copriva.
6. Controllare il `worker N` nelle righe PERF: se scende a 5 la stick ha spento un core.

# Lotto 27 bis — verifica sul Mac (log 2026-08-18 11:08-11:15)

Tre riproduzioni dello stesso film, avviate e interrotte a mano.

## Il risultato principale: decodifica pulita

| | OpenFile | Demuxer | ultima riga PERF | CloseFile |
|---|---|---|---|---|
| 1 | 11:08:32.272 | .784 | **.702** | 11:08:51.314 |
| 2 | 11:09:22.583 | 23.106 | **23.016** | 11:09:56.983 |
| 3 | 11:14:39.283 | 39.745 | **39.713** | 11:14:58.838 |

In tutte e tre, fra la creazione del demuxer e la chiusura — 18,5 s, 34 s, 19 s di decodifica vera —
**non c'è nessuna riga di costruzione, nessun DUB, nessun refresh**. Era esattamente il problema del
log della stick, dove dentro quella finestra cadevano una build da 248 elementi e ~20 pagine DUB.

## Il refresh differito funziona

Chiusura 1 a 11:08:51,3. A 11:08:56,0 (~4,5 s dopo) parte una ricostruzione con
`114 elementi | 5 pagine` e `66 elementi | 3 pagine`: sono le pagine **espanse**, conservate da
`fenlight.pg.refresh`. Una sola ricostruzione in più, non una raffica: l'attesa di 3 s in
`flush_pending_refresh` ha fatto il suo lavoro di fusione con il refresh del segnalibro.

Il confronto fra i due tipi di ricostruzione è diventato leggibile nel log e vale come firma:

* `47 elementi | 2 pagine` = apertura pulita, lotto iniziale → **ricostruzione guidata da Kodi/skin**
* `114 elementi | 5 pagine` = pagine conservate → **il nostro refresh differito**

## Quello che resta: i widget si ricostruiscono all'ingresso e all'uscita dalla riproduzione

In tutte e tre le riproduzioni, fra `OpenFile` e `Creating Demuxer` — cioè nei ~450 ms in cui Kodi
apre lo stream e non sta ancora decodificando — si ricostruiscono i 3 widget di home
(21 / 47 / 43 elementi), e lo stesso accade alla chiusura. Sono ricostruzioni del **tipo "apertura
pulita"**: non passano da `kodi_refresh`, quindi il gate del lotto 27 non le vede e non le vedrebbe
comunque, perché `Player.HasVideo` è ancora falso. È Kodi che ripopola i DirectoryProvider quando la
finestra home viene rimostrata (i widget chiudono con `cacheToDisc=False`).

Sul Mac costano 3-35 ms l'una e sono invisibili. Sulla stick sono le build da secondi, e cadono
proprio mentre lo stream riempie il buffer: è il candidato numero uno del prossimo lotto.

## Errori Trakt: artefatti del test, non regressione

```
11:09:57  409 Conflict            scrobble/stop
11:09:58  404 Not Found           sync/playback/1824024453
11:14:59  422 Unprocessable       scrobble/stop
```

Lo stesso film è stato avviato e fermato **tre volte in sei minuti**: Trakt rifiuta uno
`scrobble/stop` ripetuto sullo stesso elemento a breve distanza. Le modifiche del lotto 27 su questo
percorso sono per queste riproduzioni un **no-op dimostrabile**: durano tutte meno di 120 s, quindi
il rinvio periodico dello scrobble non sarebbe partito comunque, e nessuna supera il 90%, quindi la
marcatura anticipata non sarebbe scattata. La chiamata di stop alla chiusura è identica a prima.

**Limite di questa conclusione**: è un ragionamento, non una misura. `kodi.old.log` non contiene
nessuna riproduzione, quindi non esiste una base di confronto. Da riguardare alla prossima sessione
con film diversi.

## Ancora aperto

`Control 2000 in window 13001/13002 has been asked to focus, but it can't` (tre occorrenze): è la
finestra di dialogo delle sorgenti, non tocca la riproduzione. Non indagato.

# Lotto 27 ter — verifica sulla stick (log 2026-08-18 11:29-11:36)

## La riproduzione lunga è pulita dal nostro codice

Due riproduzioni:

| | OpenFile | CloseFile | durata | righe PERF dentro |
|---|---|---|---|---|
| 1 | 11:30:43.399 | 11:31:07.133 | 24 s | **sì**, da 11:31:03.7 (ultimi 3,4 s) |
| 2 | 11:33:09.007 | 11:34:42.428 | **93 s** | **nessuna** |

Nella riproduzione 2, fra la creazione del demuxer e la chiusura, il log contiene solo messaggi del
decoder. Novantatré secondi senza una riga di Fen Light.

E il segnale che dominava il log precedente è **sparito del tutto**: in questa sessione non c'è
**nemmeno un** `ActiveAE - large audio sync error` (prima erano decine), e nessun
`OutputPicture - timeout waiting for buffer` se non a chiusura del player, dove è normale.

La riproduzione 1 ha invece 3,4 s di costruzione sovrapposti alla coda della decodifica: alle
11:31:01.8 si carica `VideoOSD.xml`, poi partono le build. È l'utente che torna verso la home mentre
il film va — il caso che avevo esplicitamente lasciato fuori, perché bloccarlo svuoterebbe i
contenitori. Resta la scelta giusta, ma va saputo che quel percorso costa ancora.

## Quindi lo stutter residuo non è nostro

L'utente riferisce comunque "piccoli lag e sfasamenti audio/video ogni tanto". Con 93 secondi di
decodifica senza una nostra riga, la causa va cercata nel percorso video. Quello che dice il log:

**1. La cache di rete è sottile.** Impostazioni all'avvio:

```
Buffer Mode: 4          (bufferizza tutti i filesystem internet)
Memory Size: 64 MB
Read Factor: 1.50 x
Chunk Size : 131072 bytes
```

Read factor 1,5x significa leggere appena una volta e mezza il bitrate di riproduzione. Su uno
stream ad alto bitrate da CDN, ogni esitazione della rete svuota il buffer e produce un singhiozzo.
È il candidato più diretto per "piccoli lag ogni tanto".

**2. L'audio è decodificato in software.** Il dispositivo dichiara `m_streamTypes: No passthrough
capabilities`, quindi:

```
Creating audio stream (codec id: 86056, channels: 6, sample rate: 48000, no pass-through)
CDVDAudioCodecFFmpeg::Open() Successful opened audio decoder eac3
CAESinkAUDIOTRACK::Initializing with: ... channels: 2
```

EAC3 5.1 decodificato da FFmpeg e ridotto a stereo, in continuo, per tutta la durata del film, su un
ARM 32 bit. Con il passthrough attivo (se TV/ampli lo accettano) quel costo sparirebbe.

**3. Il renderer perde fotogrammi.** `CMediaCodecVideoBuffer::ReleaseOutputBuffer error in
render(false)`: 3 volte nella riproduzione 1, ~6 nella riproduzione 2. Poche, ma sono esattamente
fotogrammi che non arrivano allo schermo. Il decoder scelto è `OMX.amlogic.avc.decoder.awesome`,
cioè **H.264**: se la sorgente era 2160p H.264 questo SoC non la regge — il 4K qui è roba da HEVC/VP9.
La risoluzione non compare nel log, quindi resta un'ipotesi da verificare scegliendo la sorgente.

**4. `OpenStream: Allowing max Out-Of-Sync Value of 50 ms`** — sotto i 50 ms di deriva Kodi non
logga e non corregge. "Sfasamenti ogni tanto" cade esattamente in quella finestra.

## Due perdite nostre, piccole, corrette

1. **`WidgetPaginator`** valutava `get_setting('fenlight.paginate.interactive')` **prima** di
   `is_playing()`. `get_setting` ricade su `settings_cache.get()`, che è una query SQLite: era una
   lettura da disco al secondo per tutta la durata del film, sulla stessa eMMC lenta su cui il player
   scrive la cache dello stream. Ora `is_playing()` viene per primo.
2. **`BlurService`** girava a 3,3 risvegli al secondo anche in riproduzione, senza fare nulla di
   utile. Ora rallenta a uno al secondo: ogni risveglio prende comunque il GIL condiviso.

## Il degrado post-riproduzione è ancora lì, e resta il fenomeno più violento

Dopo la chiusura della riproduzione 2 (11:34:42):

```
11:34:53  autotest 3,821 ms/chiave | addContextMenuItems 22,13 ms/chiamata
11:35:11  lettura di 54 elementi dalla cache: 2019,9 ms
11:35:14  54 elementi | costruzione 8327 ms (154,2 ms/elemento)
11:35:20  248 elementi | totale 24,57s = risoluzione 18,97s + costruzione 5600 ms
```

154 ms per elemento contro i 2,4 ms di una sessione pulita: **65 volte**. Poi alle 11:35:48
l'autotest è di nuovo a 0,053 e la stessa lista da 248 si costruisce in 2040 ms (8,2 ms/elemento).
Il recupero arriva circa 65 secondi dopo la fine del film. Non è codice nostro: è lo stato di
Kodi/Android dopo aver tenuto aperto il decoder, ed è un capitolo a sé.

Alle 11:35:48 ricompare anche `worker 5`: la stick ha di nuovo spento un core.

## Cosa proverei, in ordine

1. **Alzare la cache di rete** (`advancedsettings.xml`: `memorysize` e soprattutto `readfactor` a 4-8).
   È l'intervento più probabile per i singhiozzi, e non costa CPU.
2. **Provare una sorgente 1080p H.264** invece di 2160p, per isolare il punto 3.
3. **Attivare il passthrough audio** se la catena HDMI lo permette.

Nessuno dei tre è codice: a questo punto il collo di bottiglia della riproduzione sta fuori da Fen Light.

# Lotto 27 quater — stick con impostazioni cambiate (log 2026-08-18 11:47-12:32)

Sessione di 45 minuti: 29 minuti dentro i menu impostazioni (con due cambi di skin), poi cinque
riproduzioni fra le 12:18 e le 12:31.

## Cosa è stato cambiato davvero

| impostazione | stato nel log |
|---|---|
| Cambio frequenza di aggiornamento | **fatto e funzionante** |
| Cache di rete | `Read Factor: 1.50 x` — **invariata** |
| Passthrough audio | `No passthrough capabilities` — **invariato** |
| `peripheral.joystick` | disattivato a metà sessione (12:16:20) |
| Zeroconf | disattivato a metà sessione (12:15:27) |
| `plugin.program.autocompletion` | disattivato — **e la skin lo chiama comunque** |
| `script.fentastic.helper`, `versioncheck`, server eventi UDP | ancora attivi |

Il cambio frequenza si vede a ogni film: `[WHITELIST] ... fps: 23.976` → `Display resolution
ADJUST : 1920x1080 @ 23.976025`. Costa un `Flush - timed out waiting for renderer to flush`
esattamente **1,000 s** a ogni cambio modalità, ma il tempo totale da `OpenFile` al renderer passa da
4,75 s a 5,06 s: **+0,3 s**, trascurabile.

## Le cinque riproduzioni, e la controprova

| # | durata | audio | sync error | render error | build durante |
|---|---|---|---|---|---|
| 1 | 61 s | AC3 5.1 | 0 | ~6 | sì |
| 2 | 79 s | EAC3 5.1 | 0 | ~4 | sì, due volte |
| 3 | 30 s | AC3 2.0 | 0 | ~2 | sì |
| 4 | **156 s** | AC3 5.1 | **0** | **0** | solo nei primi 11 s |
| 5 | 81 s | EAC3 5.1 | **~35** | 2 | sì, + `stream stalled` |

**La riproduzione 4 è la prova che il dispositivo può funzionare**: 12:26:02 → 12:28:39, due minuti e
mezzo, e fra `12:26:13.603` e `12:28:39.236` il log è **completamente vuoto**. Nessun errore di
nessun tipo. È l'unica in cui l'utente non è tornato in home mentre il film andava.

La riproduzione 5 è l'opposto e cumula tutto: EAC3 decodificato in software, ricostruzione di due
widget in mezzo (2313 ms e 3687 ms), core già offline, autotest già a 0,8-1,7 ms/chiave. Risultato:
trenta righe di `ActiveAE - large audio sync error` fra -1000 e -1960, e
`CVideoPlayerAudio::Process - stream stalled` alle 12:30:38 — cioè l'audio è rimasto **senza dati**.
Quello è un sintomo di rete/cache, non di CPU: è esattamente il `readfactor 1,5` non alzato.

## Il degrado non è monotono: è varianza che cresce

L'autotest sintetico (stesso codice, stessi dati, a ogni build):

```
11:47:59   0,039 / 0,014 / 0,016 ms/chiave   | addContextMenuItems 0,13-0,17 ms
12:18:15   0,041                              | addContextMenuItems 49,00 ms
12:19:24   0,110  (setProperties 7,994!)      | addContextMenuItems 11,84 ms
12:21:10   0,023                              | addContextMenuItems 63,76 ms
12:31:55   0,024                              | addContextMenuItems 0,20 ms
```

Il valore migliore di tutta la sessione (13,9 ms/elemento su 46 elementi) arriva alle **12:31:54**,
cioè alla fine. Quindi non c'è una discesa progressiva: c'è un **fondo che resta buono e picchi che
diventano sempre più violenti**. `addContextMenuItems` passa da 0,13 ms a 63,76 ms — 490× — a codice
identico.

Tutte le chiamate che impazziscono (`addContextMenuItems`, `setProperty`, `setProperties`) hanno una
cosa in comune: **attraversano il confine Python → GUI di Kodi**. Quando il thread GUI è occupato,
si bloccano. Il sospetto strutturale è la pressione di memoria: Arctic Fuse tiene ogni finestra
`KEEP_IN_MEMORY`, e in questa sessione ne sono state caricate una quindicina (Settings,
SettingsCategory, AddonBrowser, DialogAddonInfo, EventLog, SettingsSystemInfo, SkinSettings,
DialogKeyboard, DialogContextMenu, Custom_1105_Search, VideoOSD, VideoFullScreen...) su 1 GB di RAM
totale. A conferma, allo spegnimento: `Cleanup: Having to cleanup texture common/menu.png`.

**Caveat sulla sessione**: 29 minuti su 45 sono stati passati nei menu, con due cambi di skin. È il
caso peggiore possibile per la memoria, non l'uso normale. Le misure vanno lette in quella luce.

## Il core, di nuovo

`worker 6` fino alle 12:25:16, poi `worker 5`, poi **di nuovo 6** alle 12:25:30, poi 5 stabile dalle
12:28:56 in avanti. Primo calo a 38 minuti dall'avvio. Va e torna: è il governatore termico, non un
guasto.

## TMDbHelper: i tre percorsi ancora vivi nella skin

```
12:12:53  ExecuteAsync - Not executing non-existing script plugin.video.themoviedb.helper
          (subito dopo SkinSettings + Custom_1118_Dialog_Settings: e' una RunScript)
12:20:20  plugin://plugin.video.themoviedb.helper/?info=discover&with_id=True
          &tmdb_type=movie&with_text_query=quarto potere       (ricerca, 3 occorrenze)
12:28:44  plugin://plugin.video.themoviedb.helper/?info=discover&with_id=True&tmdb_type=movie
          seguito da "GetDirectory - Error getting " con path VUOTO   (discover, 2 occorrenze)
```

Tre punti distinti: una RunScript nelle impostazioni skin, un widget di ricerca, un widget discover.
Da riscrivere su FenLight secondo la regola del fork (vedi la memoria `tmdbhelper-removal`).

## Un consiglio sbagliato che ho dato

Avevo suggerito di disattivare `plugin.program.autocompletion`. La casella di ricerca di Arctic Fuse
lo interroga **a ogni tasto premuto**: digitando "quarto potere" il log raccoglie **14**
`Unable to find plugin` + `GetDirectory - Error getting` consecutivi, uno per carattere. Va
riattivato, o va tolta la chiamata dalla skin. Errore mio.

## Cosa manca ancora

1. **Cache: `readfactor` da 1,5 a 4-5.** Non fatto, ed è l'unica cosa che risponde direttamente allo
   `stream stalled`.
2. **Passthrough audio.** Non fatto. Le due riproduzioni andate male sono entrambe EAC3 in software.
3. **GUI a 720p.** Non risulta applicata (il log dice sempre `GUI format 1920x1080`).

# Lotto 28 — analisi (log stick 2026-08-21 21:33-21:45). Nessun codice scritto.

Sessione di 12 minuti sul Mi Stick, uso volutamente stressante: quattro riproduzioni, ritorni in
home durante il film, una ricerca a tastiera. Questo lotto è **solo diagnosi**: cambia il bersaglio
dei prossimi interventi e archivia due ipotesi sbagliate, mie.

## Le impostazioni fuori-codice hanno funzionato

| | Lotto 27 quater | questo log |
|---|---|---|
| `Read Factor` | 1.50 x | **4.00 x** |
| GUI | `1920x1080` | **`GUI format 1280x720`** |
| `ActiveAE - large audio sync error` | ~35 in una riproduzione | **0 in tutta la sessione** |
| `CVideoPlayerAudio - stream stalled` | sì | **mai** |
| Passthrough | `No passthrough capabilities` | invariato |

I due sintomi più violenti del log precedente sono spariti, e non con del codice. Non c'è nessun
`advancedsettings.xml` (`No settings file to load`): la cache è stata alzata dall'interfaccia.

## L'ipotesi "pressione di memoria" è sbagliata. È contesa sul thread GUI.

L'autotest sintetico (stesso codice, stesse 30 chiavi, a ogni build):

| ora | contesto | ms/chiave | `addContextMenuItems` |
|---|---|---|---|
| 21:34:06 | home a riposo | 0,019 | 0,13 ms |
| 21:36:12 | 3 widget in parallelo, durante pb1 | 1,519 | **9,65 ms** |
| 21:37:04 | 3 widget in parallelo, dopo pb1 | 1,766 | **10,06 ms** |
| **21:38:01** | **film in corso, nient'altro** | **0,018** | **0,15 ms** |
| 21:41:19 | home a riposo | 0,019 | 0,18 ms |
| 21:43:03 | film in corso, nient'altro | 0,024 | 0,20 ms |
| 21:43:48 | dopo pb3, build multipla | 2,110 | 6,23 ms |
| 21:45:12 / :13 | due build **dello stesso** widget | 1,439 / 1,668 | 4,49 / 5,35 ms |

Escursione **117×** sulle chiavi, **77×** su `addContextMenuItems`, a codice identico.

La riga che decide è quella delle 21:38:01: **è il valore migliore di tutta la sessione ed è stato
preso mentre un film decodificava.** Idem alle 21:43:03. Quindi non è "durante la riproduzione si va
piano" (la riproduzione da sola costa zero al nostro Python), e non è "peggiora col tempo di
sessione" (i valori buoni sono sparsi dall'inizio alla fine). L'unica variabile che correla è
**quante costruzioni di interfaccia sono in volo nello stesso istante**.

L'ipotesi del Lotto 27 quater — finestre `KEEP_IN_MEMORY` su 1 GB — va **declassata**: questa
sessione ha caricato una manciata di finestre, non quindici, e i picchi 77× ci sono lo stesso.

## Il parallelismo non paga: l'overlap costa più della somma

Nella riga `FASI`, `meta` — Python puro + cache, l'unica fase davvero parallelizzabile — costa
**5 ms su 1330, cioè 0%**. L'85% è `infotag + ctxmenu + props`, cioè il confine Python→C++, che è
**già un punto seriale**. I widget non lavorano in parallelo: fanno la fila tenendo occupati tre
interpreti, tre pool da sei thread e la RAM di tutti e tre.

Stesso widget da 130 elementi, stessi dati, sempre `100% in cache`, nove ricostruzioni:

| ora | contesto | `somma thread` | ms/elemento |
|---|---|---|---|
| 21:41:19 | da solo | 342 ms | **5,6** |
| 21:36:14 | quasi da solo | 240 ms | 7,9 |
| 21:34:56 | quasi da solo | 437 ms | 7,8 |
| 21:37:08 | in onda con altri due | 1069 ms | 20,1 |
| 21:37:59 | in onda con altri due | 2142 ms | 27,5 |
| 21:41:08 | in onda con altri due | 2060 ms | 28,4 |
| 21:45:18 | in onda con altri due | **2427 ms** | **29,0** |

**5,2×** a codice e dati identici. Prova diretta che l'overlap *crea* lavoro: alle 21:45:12 lo stesso
widget da 9 elementi viene costruito due volte a 200 ms di distanza — prima build `somma thread
236 ms`, seconda **677 ms**. Il Lotto 21 aveva annotato "−7,7× di CPU ma il tempo di parete non
migliora" senza spiegarlo: il pool paralleliza la fase che non conta e affolla quella che conta.

## Il costo si vede sul player: 13 secondi al primo fotogramma

| # | OpenFile | primo frame | ritardo | costruzione UI in corso? |
|---|---|---|---|---|
| 1 | 21:35:53.5 | 21:35:59.8 | 6,2 s | in coda |
| 2 | 21:37:43.7 | 21:37:48.2 | **4,5 s** | no |
| 3 | 21:42:53.9 | 21:42:58.9 | 5,0 s | marginale |
| 4 | 21:44:05.2 | 21:44:18.3 | **13,0 s** | **sì, in pieno** |

Nella pb4 cade una build da 48 elementi: `totale 5.95s = risoluzione 1.85s + costruzione 4101 ms
(85,4 ms/elemento)`. Due conferme che non lasciano scampo:

* **apertura dello stream audio**: `Creating audio thread` → `Creating audio stream` costa 0,19 /
  0,14 / 0,20 s nelle pb1-3 e **4,05 s** nella pb4. Venti volte.
* **handshake col decoder hardware**: `Testing codec` → `Using codec: OMX.amlogic.avc.decoder.awesome`
  costa 0,41 / 0,53 s nelle pb2-3 e **1,24 s** nella pb4. Rallenta persino l'init di MediaCodec, che
  è C++ e driver.

## Il conto della ricostruzione inutile

Quattro widget in home (`script-skinvariables-generator-includes-.xml`): `continue_watching`, due
liste mdblist, una lista film. Elementi richiesti, build per build:

| widget | 21:33 | 21:37 | 21:40 | 21:44 |
|---|---|---|---|---|
| continua a guardare | 6 | **7** | **8** | **9** |
| lista A | 48 | 48 | 48 | 48 |
| lista B | 54 | 54 | 54 | 54 |
| lista C | 130 | 130 | 130 | 130 |

In dodici minuti e quattro film **è cambiato un widget solo, di un elemento alla volta**. Intanto il
widget da 130 elementi è stato ricostruito **nove volte**: 1170 costruzioni di ListItem per una
lista che non è mai cambiata.

Dopo la chiusura della pb2 (21:40:32) la home non si ricostruisce una volta, ma **quattro**:

```
21:40:48 → 21:40:53   onda A   (8, 54, 130 el)   — Kodi ripopola i DirectoryProvider
21:41:02.623          VideoInfoScanner special://skin/foo   <- il NOSTRO kodi_refresh differito
21:41:02 → 21:41:08   onda B   (8, 130, 54 el)   ctxmenu 828 ms (40%)
21:41:11 → 21:41:13   onda C   (54 el)
21:41:16 → 21:41:19   onda D   (8, 130 el)
```

Quarantasei secondi di costruzione quasi continua. E dopo la pb4, alle 21:44:47, un
`prefetch 3098.1 ms` per **20 elementi già in cache**: lettura SQLite sulla eMMC ancora satura
dalla cache dello stream appena chiuso.

## Le tre cause, che vanno tenute separate perché si curano in modo diverso

**a) `cacheToDisc=False`.** In `movies.py:190`, `tvshows.py:192`, `seasons.py:114` la directory di un
widget (`is_external`) si chiude senza cache su disco. Kodi butta la lista: ogni volta che la home
torna visibile rilancia il plugin da zero — entrando in riproduzione **e** uscendone. È una scelta
di Fen Light, non un vincolo di Kodi.

**b) `UpdateLibrary(video,…)` è un annuncio globale.** Il `DirectoryProvider` di Kodi invalida **ogni**
contenitore con `<content>` video, non quello i cui dati sono cambiati.

**c) La paginazione ha moltiplicato il costo di ogni refresh.** Il `<content>` di Arctic Fuse
(`Includes_Hubs.xml:124` e `:178`) è:

```xml
<content ...>$PARAM[content]$INFO[Window(Home).Property(fenlight.pg.ctl$PARAM[id].pages),&pages=,]</content>
```

Il numero di pagine sta **dentro il path**. Un widget espanso a 6 pagine si ricarica sempre a 130
elementi, mai a 20 (`130 elementi | 6 pagine | path_pages=6`, nove volte). **Più navighi, più cara
diventa ogni singola ricostruzione**: la penale cresce con l'uso.

## Il martello mirato ce l'abbiamo già, e lo usiamo per un chiodo solo

La causa (b) sembra un vincolo di Kodi. Non lo è, e la prova è nel nostro codice. `paginator.py:35`:

> *"Token di ricarica MIRATA, indicizzato per id del contenitore. Compare dentro il `<content>` come
> `$INFO[…]`, quindi cambiarlo fa ricaricare SOLO quel contenitore invece di sparare UpdateLibrary."*

Una `setProperty` su `Window(Home)` ricarica **un** widget. È in produzione dal Lotto 5 — ma serve
solo ad aggiungere pagine. È esattamente il meccanismo che serve per "ho chiuso Matrix, aggiorna solo
chi contiene Matrix", e non l'abbiamo mai collegato lì.

Mancano: un token di ricarica **separato dal numero di pagine** (oggi cambiare le pagine cambia anche
cosa si vede) e una mappa "widget → id contenuti", che possiamo pubblicare a costo zero perché la
lista degli id ce l'abbiamo già in mano mentre costruiamo. Limite onesto: anche il refresh mirato
ricostruisce quel contenitore **per intero**, 130 elementi compresi — 130:1 invece di 340:1.

## Trakt: il mio "×60" era sbagliato. La leva è l'ultima riga.

I 30 secondi non costano. `trakt_api.py:987-1006` fa una GET a `sync/last_activities`, confronta un
timestamp e se non è cambiato nulla esce con `'not needed'` **senza toccare la UI**. Il log conferma:
~24 poll in dodici minuti, **un solo** `VideoInfoScanner`. La cadenza è voluta e va lasciata.

La leva è dove quella funzione **butta via quello che sa**. Calcola una diagnosi granulare —
confronta separatamente `movies`, `shows`, `episodes`, `lists`, `favorites`, `recommendations`, e
tiene `lists_actions`, `refresh_movies_progress`, `refresh_shows_progress`,
`clear_tvshow_watched_cache` — poi restituisce la stringa `'success'`, e `service.py:89` la traduce
in un `kodi_refresh()`, cioè tutto. Sa già che è cambiata solo la watchlist. Lo dimentica sulla soglia.

## Perché Arctic Fuse è fatta così: il buco a forma di TMDbHelper

Arctic Fuse 3 è progettata **attorno a TMDbHelper**, e non è un dettaglio storico: è il suo modello
dei dati. Ogni widget porta ancora `<onfocus>SetProperty(TMDbHelper.WidgetContainer,$PARAM[id])`, e
c'è un `Custom_1190_TMDbHelper.xml` intero. Il funzionamento previsto: ListItem **magro** (titolo,
poster, un id), e tutto il resto — trama, cast, valutazioni, artwork, badge — spinto da un servizio
esterno dentro proprietà di finestra **solo per l'elemento in fuoco**.

Togliendo TMDbHelper e mettendo Fen Light sotto, quel lavoro non è sparito: **si è spostato dal fuoco
alla costruzione.** Oggi ogni item paga ~20 setter di infotag, ~30 proprietà e un menu contestuale da
7 voci — 130 volte, anche per i 125 item che non guarderai mai. Un costo *per elemento focalizzato*
è diventato un costo *per elemento esistente*.

Si aggiungono due scelte di Arctic Fuse ragionevoli altrove e non qui:

* **tratta i widget plugin come i nodi di libreria.** Un `videodb://` lo serve il C++ da SQLite:
  ricaricarlo è quasi gratis, quindi ricaricare tutto a ogni evento non fa danno. Un `plugin://`
  avvia un interprete Python. La skin non distingue.
* **è enorme e "tutto in memoria":** 208 file XML in `1080i`, un sistema di Hub (Home + 1101-1109)
  generato a runtime da `script.skinvariables`, ogni finestra `KEEP_IN_MEMORY`.

**Su Fentastic, dichiarato come ipotesi**: non è nel repo, non l'ho letta. Ma sulla stick è installato
`script.fentastic.helper`, che fa partire il proprio *Ratings Service* — cioè Fentastic **si porta
dietro il proprio addon di supporto scritto per Fen Light**, lo stesso ruolo che TMDbHelper aveva per
Arctic Fuse. Se è così, un suo refresh è leggero non perché refreshi meglio, ma perché **ogni item
costa una frazione**. Verifica economica: la strumentazione `PERF` è dentro Fen Light, non dentro la
skin — basta montare Fentastic, aprire la stessa lista da 130 elementi e leggere `ms/elemento`.

## Il player: audit di cosa resta acceso

**Kodi non spegne niente durante la riproduzione, e non lo fa per progetto**: non esiste una modalità
che sospenda addon o servizi. Restano vivi il server JSON-RPC, il server eventi UDP sulla 9777,
`script.module.cocoscrapers`, `service.xbmc.versioncheck`, e — nota — il **`FENtastic Ratings
Service`** (21:33:40 → 21:45:48) di una skin **non in uso**, mentre quella attiva è Arctic Fuse.

Dalla parte nostra invece la riproduzione è pulita, e il log lo dimostra: 168 s (pb2) e 93 s (log
precedente) senza una riga di Fen Light. Risvegli residui, misurati sul codice:

| thread | risvegli/s in riproduzione | cosa fa a ogni giro |
|---|---|---|
| `FenLightPlayer.monitor` | 1 | `getTotalTime()` + `getTime()` |
| `BlurService` | 1 | `isPlayingVideo()` |
| `WidgetPaginator` | 1 | `isPlayingVideo()` |
| `WidgetRefresher` | 0,1 | `isPlayingVideo()`, `clearProperty`, **`get_setting(...)`** |
| `TraktMonitor` | 0,1 | `isPlayingVideo()` |
| `CustomFonts` | 0,05 | `isPlayingVideo()` |

~3,25 risvegli/s: non c'è più niente da guadagnare, tranne **una perdita rimasta**. In
`service.py:126` il `WidgetRefresher` valuta `get_setting('fenlight.widget_refresh_timer', '60')`
**prima** di `condition_check()`, che è dove sta la guardia `is_playing()`. È lo stesso identico
difetto corretto per il `WidgetPaginator` nel Lotto 27 ter, nel servizio gemello, ancora aperto: se
quella chiave non è rispecchiata in una proprietà di finestra, è una query SQLite ogni 10 s per tutta
la durata del film, sulla eMMC su cui il player scrive la cache. Da verificare e chiudere.

### Costi lato Kodi, non nostri

* **`Flush - timed out waiting for renderer to flush`: esattamente 1,000 s, 4 volte su 4** (1.001 /
  1.002 / 1.001 / 1.004). È il prezzo fisso del cambio frequenza di aggiornamento — un timeout, non
  lavoro. Vale ampiamente il secondo che costa: elimina il judder per tutto il film.
* **Sondaggio dei codec**: Kodi prova `audio.decoder.ac3`, `.dtshd`, `.eac3`, `.ffmpeg`, `vp6a`,
  `vp6f` **prima** di arrivare a `avc.decoder.awesome`. 0,4-1,2 s per riproduzione. Non configurabile.
* **`ReleaseOutputBuffer error in render(false)`**: ~3 per riproduzione **anche nella pb2 rimasta
  pulita per 2,5 minuti** (21:38:13 e 21:40:22, in pieno silenzio). È il renderer, non noi. Da non
  inseguire.
* **Il sink audio si riapre 3-4 volte per riproduzione** (44100 → 48000 → 44100 alla chiusura).
  Normale, marginale.

### Passthrough: declassato

`m_streamTypes : No passthrough capabilities`. Non è un flag di Kodi che manca: è **Android** che
risponde "nessuna codifica accettata" quando Kodi interroga l'uscita HDMI. Kodi il suo lavoro l'ha
fatto — `ValidateOutputDevices: passthrough output device ... updated to 'AUDIOTRACK:AudioTrack
(RAW)|Android IEC packer'`. Il rifiuto viene dal basso: sistema Android o EDID del televisore.

Quanto pesa davvero: AC3/EAC3 5.1 decodificato da FFmpeg e downmixato a 2.0 su un Cortex-A53 costa
qualche punto percentuale di un core, costante e non a picchi. Nel Lotto 27 quater era l'indiziato
numero uno perché le due riproduzioni peggiori erano EAC3 — ma il colpevole era il buffer di rete che
si svuotava (`stream stalled`), e con `readfactor 4` quel sintomo è sparito. In questo log la pb2
(168 s, AC3 5.1 in software) è **perfettamente pulita**. Nota anche che il passthrough conviene solo
se a valle c'è un ampli/soundbar che decodifica: verso un TV stereo il downmix serve comunque.

**Verdetto: dieci minuti di ricerca dell'impostazione, non un progetto.** Non è più un blocco.

## Ordine di lavoro rivisto (era rovesciato: serializzare curava il sintomo)

1. **Non ricostruire ciò che non è cambiato.** Da "4 widget × N ricostruzioni" a "il widget
   interessato, quando serve". Tre pezzi: usare il token mirato anche fuori dalla paginazione;
   pubblicare la mappa widget → id contenuti; far arrivare fin lì la diagnosi granulare di Trakt
   invece della stringa `'success'`.
2. **Chiudere il rientro dalla riproduzione** (`cacheToDisc=False`): è la causa isolata delle
   ricostruzioni all'apertura *e* alla chiusura del player, indipendente da Trakt. Miglior rapporto
   beneficio/rischio.
3. **Serializzare** quel poco che resterà: a quel punto è una rete di sicurezza, non un progetto.
4. **Alleggerire il ListItem** (il buco di TMDbHelper) solo dopo, e solo se il confronto con
   Fentastic dice che vale il prezzo di toccare la skin.

Fuori corsia, a costo quasi zero: la `get_setting` del `WidgetRefresher`; disinstallare
`skin.fentastic` (il suo servizio gira per niente); riattivare `plugin.program.autocompletion` o
togliere la chiamata dalla skin (7 errori, uno per tasto, alle 21:41:34-48); i tre percorsi
TMDbHelper ancora vivi — uno dei quali, alle 21:42:58, cade **dentro l'apertura della pb3**.

# Lotto 29 — analisi dell'avvio (log stick 2026-08-21 22:29, crash) + piano di lavoro consolidato

## Il log non finisce: è troncato

Lo spegnimento pulito delle 21:45 ha quindici righe di chiusura ordinata. Qui l'ultima riga è
`22:30:15.902 BlurService Starting (Pillow: OK)` e poi il nulla: nessun trailer, nessun traceback
Python, nessun errore. **Un log troncato senza trailer significa processo terminato dall'esterno** —
SIGKILL del lowmemorykiller di Android, o segfault. Un blocco avrebbe lasciato i sei thread di
servizio a loggare.

## Non stava rallentando: è morta di colpo

Tempi relativi all'avvio di Kodi, contro l'avvio riuscito delle 21:33 (stesso dispositivo, stesso
codice):

| traguardo | avvio OK | avvio crashato |
|---|---|---|
| `initialize done` | +5,09 s | **+4,64 s** |
| `Home.xml` caricato | +8,26 s | **+6,75 s** |
| `Main Monitor Service` | +8,10 s | +7,95 s |
| `cocoscrapers Service Started` | +13,77 s | **+12,93 s** |
| `BlurService Starting` | +15,94 s | +16,14 s |
| `FENtastic Ratings Service` | +24,27 s | **mai** |
| prima riga `PERF` | +27,41 s | **mai** |

Fino a 16 secondi la sessione crashata era **più veloce**. Poi sparisce. Non è degrado progressivo,
è una soglia superata di colpo: punta sulla **memoria**, non sulla CPU. Coerente con l'intermittenza
(l'OOM killer scatta o no a seconda di cosa Android ha in RAM); un bug deterministico crasherebbe
sempre nello stesso punto e lascerebbe una traccia.

## Cosa gira in quella finestra (dal codice, non dal log)

`Startup.xml` (`LOAD_EVERY_TIME`; Kodi avverte `startup.xml taints init process`):

* `AlarmClock(SplashTimeOut,noop,00:59,silent)` — **la fase di avvio ha un budget di 59 secondi**.
* `RunScript(script.skinvariables, skinvariables-startup.json)` — ~50 `Skin.SetString/SetBool`, e in
  coda `SetProperty(InitStatus,Reticulating Splines)` +
  **`RunPlugin(plugin://plugin.video.fenlight/?mode=fen_blur&image=…)`**, che importa **Pillow**.

`Home.xml` `<onload>`:

* `Action_BuildShortcuts_OnLoad` → `skinvariables-build-templates.json` →
  `route=action=buildtemplate&background=false` — **rigenerazione sincrona e bloccante** di
  `script-skinvariables-generator-includes-.xml` (33 KB, 572 righe, 12 widget) da nove file dati.
* `skinvariables-splash.json`, che sotto `Startup.EnableHubPreloading` fa:

```
ActivateWindow(1101) sleep=0.3 ... 1102 ... 1103 ... 1104 ... 1106 ... 1107 ... 1108
ActivateWindow(Home)
```

Ogni `ActivateWindow` **carica il XML della finestra hub** (`KEEP_IN_MEMORY`, non si scarica più) **e
avvia tutti i suoi DirectoryProvider**, cioè un'invocazione del plugin Fen Light per ogni widget di
ogni hub. Che gli hub siano configurati lo conferma il log: i sei
`Label Formatting: $VAR[Home_Icon_1106/1107/1108] is not defined` esistono perché sono referenziati.

**E il file si richiama da solo**: finché i contenitori 301 o 501 stanno aggiornandosi si rilancia
ogni 0,5 s (`route=run_executebuiltin=…skinvariables-splash.json`), e ogni giro è una nuova
esecuzione di `script.skinvariables`. I contenitori stanno aggiornandosi *perché li ha appena
avviati tutti insieme*: più le build sono lente, più giri fa, più interpreti aggiunge. Su un
dispositivo lento accelera invece di rallentare. È il "Loading Widgets" a schermo.

## Il conto degli interpreti nel secondo in cui muore

`reuselanguageinvoker` è `false` e deve restarci (Lotto 11c): **ogni** invocazione è un interprete
Python nuovo con import completo dell'albero dei moduli.

| in volo | quanti |
|---|---|
| widget della home | 4 |
| widget degli hub precaricati | fino a 12, in coda a 0,3 s |
| `RunPlugin(?mode=fen_blur)` — **importa Pillow** | 1 |
| `BlurService` — **importa Pillow** | 1 |
| `skinvariables-startup.json` | 1 |
| `skinvariables-build-templates.json` (sincrono) | 1 |
| `skinvariables-splash.json` + ricorsioni | 1 + N |
| `cocoscrapers` Settings Monitor | 1 |
| `script.fentastic.helper` Ratings Service (skin **non in uso**) | sta per partire |
| thread di servizio Fen Light | 6 |

Più Kodi: 3,1 MB di XML in `1080i` (208 file), il fontset, e ogni finestra aperta dal precaricamento
che resta in RAM per sempre. Su ARM 32 bit con 1 GB totale, di cui Android TV 9 prende 400-500 MB.
**I due import simultanei di Pillow sono lì per caso** — il `RunPlugin` fa un lavoro che il
`BlurService` rifarebbe un secondo dopo — e sono la voce più grassa dell'elenco.

Anche quando non crasha quella fase dura quasi un minuto: nel log riuscito la prima riga `PERF`
arriva a +27 s e il primo widget completo a +44 s. Il budget di 59 s non è lì per caso.

## Prova mancante

Il log di Kodi non può dire "sono stato ucciso". Serve, subito dopo un crash:

```
adb logcat -d | grep -iE "lowmemorykiller|Low on memory|am_kill|SIGSEGV|org.xbmc.kodi"
```

`am_kill … org.xbmc.kodi` o `Low on memory` → confermato, è memoria. `SIGSEGV` → capitolo diverso.

## Fatto

**Precaricamento degli hub disattivato** (2026-08-21). Da verificare nel prossimo log: assenza di
`ActivateWindow` a catena all'avvio, prima riga `PERF` più vicina all'avvio, e nessun crash.

---

# Piano di lavoro consolidato

Priorità dichiarate dall'utente, in ordine: (1) riproduzione, (2) generazione interfaccia e
navigazione su contenuti già in cache, (3) via TMDbHelper dalla skin e alleggerimento strutturale,
(4) avvio leggero.

## P1 — Riproduzione

Il lato Fen Light **è già pulito**: 168 s di log vuoto durante un film, 3,25 risvegli/s totali,
autotest a 0,018 ms/chiave *mentre il video decodifica*. Resta una cosa sola.

| # | cosa | dove | perché |
|---|---|---|---|
| 1.1 | `get_setting` valutata prima della guardia `is_playing()` | `service.py:126` (`WidgetRefresher`) | query SQLite ogni 10 s per tutto il film, sulla eMMC su cui il player scrive la cache. Identico al difetto chiuso nel Lotto 27 ter per `WidgetPaginator`, nel servizio gemello. Rischio nullo. |

**Il costo vero della riproduzione è attorno, non dentro**: 13,0 s al primo fotogramma contro 4,5 s
quando non c'è una build in mezzo, e quattro onde di ricostruzione all'uscita. Si risolve in P2.

## P2 — Generazione interfaccia e navigazione

| # | cosa | dove | perché |
|---|---|---|---|
| 2.1 | `cacheToDisc=False` sulle directory dei widget | `movies.py:190`, `tvshows.py:192`, `seasons.py:114` | Kodi butta la lista: il plugin rigira da zero a ogni ri-mostra della home, entrando **e** uscendo dalla riproduzione. Causa isolata del ritardo al primo fotogramma e delle onde all'uscita. **Il più isolato e a rischio più basso: si parte da qui.** |
| 2.2 | Refresh mirato al posto di `UpdateLibrary` globale | token già esistente, `paginator.py:35` | Chiudere un film cambia **un** elemento; oggi se ne ricostruiscono 340 su quattro widget. Serve un token separato dal numero di pagine + una mappa widget → id contenuti (la lista degli id ce l'abbiamo già in mano). |
| 2.3 | La granularità di Trakt buttata via | `trakt_api.py:1007` → `service.py:89` | La funzione calcola `lists_actions`, `refresh_movies_progress`, `refresh_shows_progress`, e confronta `movies`/`shows`/`episodes`/`lists`/`favorites`/`recommendations` separatamente — poi restituisce `'success'`, che diventa un refresh globale. Sa già cosa è cambiato e lo dimentica sulla soglia. La cadenza di 30 s **va lasciata**: costa una GET e un confronto di timestamp. |
| 2.4 | Il `kodi_refresh` differito si somma a una ricostruzione che Kodi fa già | `player.py:217-222` | Dopo la pb2: onda alle 21:40:48 (Kodi), poi la nostra alle 21:41:02, poi altre due. Se 2.1 riesce, questo va **eliminato**, non rimandato. Da verificare con prova mirata prima di toglierlo. |
| 2.5 | Build duplicate e overlap superlineare | — | 21:45:12: lo stesso widget da 9 elementi costruito da due thread a 200 ms di distanza (236 ms vs 677 ms di `somma thread`). Stesso widget da 130 elementi: 5,6 → 29,0 ms/elemento a seconda di quante build sono in volo. Debounce sui path identici + serializzazione, come **rete di sicurezza dopo** 2.1-2.4, non come primo intervento. |
| 2.6 | Path malformato `&pages=6` | — | `GetDirectory - Error getting &pages=6`, ancora vivo (21:41:29). Vecchio, mai chiuso. |

## P3 — TMDbHelper fuori dalla skin, e alleggerimento strutturale

Censimento attuale: **321 occorrenze** della stringa `TMDbHelper` in 31 file di `1080i`, e ~70 punti
che invocano davvero `plugin.video.themoviedb.helper` (XML + `skinvariables-shortcut-config.json` +
`generator/data/setup/`). Il metodo è già fissato in `TMDBHELPER-RIMOZIONI.md`.

**Distinzione da tenere ferma**: le proprietà `TMDbHelper.*` sono un *namespace*, non una dipendenza
— il nostro `blur_service` ci scrive dentro apposta (`TMDbHelper.ListItem.BlurImage`) e legge
`Skin.HasSetting(TMDbHelper.EnableBlur)`. Vanno rimosse le **invocazioni**, non i nomi.

| # | cosa | perché |
|---|---|---|
| 3.1 | I tre percorsi che sparano a runtime | RunScript nelle impostazioni skin; widget di ricerca `?info=discover&with_id=True&tmdb_type=movie&with_text_query=…`; widget discover con `GetDirectory` a path vuoto. Uno di questi cade **dentro l'apertura di una riproduzione** (21:42:58). |
| 3.2 | `Includes_NextAired.xml` | otto `<content>` che puntano tutti a themoviedb.helper: il widget non può funzionare. |
| 3.3 | `shortcuts/generator/data/setup/widgets_row.xml` e `search_path.xml` | i percorsi TMDbHelper sono nei **dati del generatore**: ricompaiono a ogni rigenerazione. Vanno tolti alla fonte, non nell'output. |
| 3.4 | `autocompletion` | la casella di ricerca lo interroga a ogni tasto (7 errori per "minions"). Riattivarlo o togliere la chiamata. Consiglio sbagliato mio, già ritirato. |
| 3.5 | **Il buco strutturale: il ListItem grasso** | Arctic Fuse assumeva ListItem magri + dati spinti sul focus da un servizio esterno. Senza quel servizio, ogni elemento paga ~20 setter di infotag, ~30 proprietà e un menu da 7 voci — 130 volte, anche per i 125 che non guarderai. Prima la **misura**: montare Fentastic, aprire la stessa lista da 130 elementi, leggere le nostre righe `PERF` (la strumentazione è in Fen Light, non nella skin). Solo se il confronto lo giustifica. |

## P4 — Avvio

| # | cosa | stato |
|---|---|---|
| 4.1 | `Startup.EnableHubPreloading` off | **fatto**, da verificare nel log |
| 4.2 | `Startup.DisableWaitForLoad` | da provare separatamente, per isolare quale delle due pesa |
| 4.3 | `RunPlugin(?mode=fen_blur)` in `skinvariables-startup.json` | duplica il lavoro del `BlurService` un secondo dopo, con un secondo import di Pillow. Nostro codice, eliminabile |
| 4.4 | Disinstallare `skin.fentastic` | il suo Ratings Service gira per tutta la sessione per una skin non in uso — un interprete in meno proprio nella finestra critica. **Da fare dopo** la misura 3.5 |
| 4.5 | Rigenerazione sincrona (`background=false`) del file generato | il file cambia solo quando si riconfigura la home; verificare se il guard `lastbuildtime` funziona |

**Da non fare**: alzare la memoria di Kodi o allungare i timeout. Non manca tempo, c'è troppa roba
viva insieme.

## Fuori corsia

* Passthrough: **declassato**. `No passthrough capabilities` viene da Android/EDID, non da Kodi
  (che ha già scelto il device da solo). Con `readfactor 4` i sintomi che lo accusavano sono spariti.
* `worker N` nella riga PERF: **tenere**, è un termometro gratuito del throttling termico.
* Strumentazione `PERF` / `PERF_SELFTEST`: da rimuovere alla chiusura dell'ottimizzazione.
* Tre import rotti preesistenti in `router.py` (`add_to_history`, `show_text_media`, `set_view`).

# Lotto 30 — P1.1 (`get_setting` in riproduzione) e P2.1 (`cacheToDisc` sui widget)

## Prima: la verifica del precaricamento hub disattivato (log stick 22:48)

Nessun crash, chiusura pulita con trailer completo, e la fase "Loading Widgets" con le sue
ricorsioni sparita dal log. Confronto con i due log precedenti della stessa serata, in tempo
relativo all'avvio di Kodi:

| traguardo | OK 21:33 | crash 22:29 | **22:48** |
|---|---|---|---|
| `initialize done` | +5,09 s | +4,64 s | **+4,34 s** |
| `Main Monitor Service` | +8,10 s | +7,95 s | **+5,81 s** |
| `cocoscrapers Started` | +13,77 s | +12,93 s | **+6,83 s** |
| `BlurService` | +15,94 s | +16,14 s | **+11,59 s** |
| primo widget completo | +44,45 s | mai | **+24,33 s** |
| home completa | +49,65 s | mai | **+24,71 s** |

**−50% sul tempo di home pronta**, con una impostazione e zero codice. `skin.fentastic` e
`script.fentastic.helper` sono stati disinstallati: il Ratings Service non compare piu'.
Conseguenza da ricordare: la misura di confronto prevista in P3.5 richiede di reinstallarla.

Correzione a un conteggio del Lotto 28: i widget di home costruiti sono **tre**, non quattro
(9 continue watching, 48 mdblist 91378, 54 mdblist 101881). La lista da 130 elementi non e' un
quarto widget: e' la 91378 dopo che la paginazione l'ha espansa a 6 pagine.

Le fasi dominanti in questo log sono `setArt 196ms (36%)` e `setLabel 294ms (30%)`: e' un avvio a
freddo con cache texture vuota, quindi 23,9 e 31,3 ms/elemento non sono confrontabili con i valori a
caldo. Nessuna conclusione da trarne.

## P1.1 — la `get_setting` pagata durante il film

`service.py`, `WidgetRefresher`: `get_setting('fenlight.widget_refresh_timer')` era valutata
**prima** di `condition_check()`, che e' dove sta la guardia `is_playing()`. `get_setting` e'
`get_property() or settings_cache.get()`: quando la chiave non e' anche una proprieta' di finestra
ricade su una query SQLite. Era una lettura da disco ogni 10 s per tutta la durata del film, sulla
stessa eMMC su cui il player scrive la cache dello stream. `condition_check()` scartava comunque il
giro, ma solo **dopo** averla pagata.

Ora la guardia e' esplicita e viene per prima (`playing = self.is_playing()` ... `if playing:
continue`). Stesso difetto gia' corretto per `WidgetPaginator` nel lotto 27 ter, nel servizio
gemello: era rimasto aperto.

Effetto collaterale accettato: se si cambia `widget_refresh_timer` **mentre** un film e' in corso, il
nuovo valore viene letto alla fine della riproduzione invece che entro 10 s. Prima il giro veniva
comunque scartato da `condition_check()`, quindi non cambia nulla di visibile.

## P2.1 — `cacheToDisc`, chirurgico invece che uniforme

`cacheToDisc=False` significa: Kodi butta la lista appena la finestra smette di mostrarla, quindi
rilancia il plugin -- un interprete Python nuovo -- ogni volta che la home torna visibile. Cioe'
anche **entrando** in riproduzione e uscendone, quando la CPU serve al decoder.

Sono sei i punti, non tre come scritto nel Lotto 28. E il modello dei widget dell'utente suggerisce
di non trattarli allo stesso modo:

| file | prima | ora | perche' |
|---|---|---|---|
| `movies.py:190` | `False if is_external` | **`True`** | lista che non cambia da sola |
| `tvshows.py:192` | `False if is_external` | **`True`** | idem |
| `seasons.py:114` | `False if is_external` | **`True`** | idem |
| `mdblist_lists.py:125` | `False if is_external` | **`True`** | sono i due widget cari della home (48 e 54 elementi, 130 da espansi) |
| `continue_watching.py:65` | `False if is_external` | **invariato** | e' il widget che cambia davvero: nel log 21:33 e' passato da 6 a 9 elementi in quattro film |
| `trakt_lists.py:364` | `False if is_external` | **invariato** | watchlist e liste Trakt cambiano quando l'utente aggiunge o guarda qualcosa |

Cosi' si smette di ricostruire il 92% degli elementi (102 su 111) e resta viva la lista che deve
esserlo -- che e' anche la piu' corta, quindi ricostruirla costa poco (`somma thread 68 ms`).

### Cosa NON si rompe, e perche'

* **La paginazione.** Il token `&pages=N` sta **dentro il path** (`Includes_Hubs.xml:124` e `:178`):
  aggiungere una pagina produce un path diverso, quindi una chiave di cache diversa. La cache non
  c'entra. Il meccanismo del lotto 5 e' indipendente da questa modifica.
* **Il riavvio.** Kodi svuota `special://temp` all'avvio (`removing tempfiles`, visibile in ogni
  log): nessuna lista sopravvive alla chiusura di Kodi.

### Il rischio dichiarato, che e' il motivo per cui P2.2 deve seguire

Con la lista in cache, un `UpdateLibrary` potrebbe essere servito **dalla cache** invece di
rifare la build: in quel caso il badge "visto" su un film dentro una lista mdblist non si
aggiornerebbe finche' il path non cambia. Non e' stato possibile deciderlo leggendo il codice --
dipende da come `CDirectoryProvider` di Kodi interagisce con `CDirectoryCache`, e non e' verificabile
da qui. **Va misurato sul dispositivo**, ed e' esattamente la domanda che decide la forma di P2.2:
se l'invalidazione non passa, il token di ricarica mirata nel path non e' un'ottimizzazione in piu',
e' il meccanismo di invalidazione obbligatorio.

Il fallimento e' visibile, non distruttivo e reversibile in una riga.

## Verifiche fatte

* fine riga: invariate su tutti e otto i file (`kodi_utils.py`, `seasons.py`, `trakt_lists.py` CRLF;
  gli altri LF -- **non** sono tutti CRLF come diceva la nota generale);
* `ast.parse` su tutti e otto;
* confronto dei simboli top-level e annidati contro `HEAD`: **nessuno perso, nessuno aggiunto**;
* `git diff --numstat`: 2/1 sui quattro file girati (un commento + la riga), 2/0 e 1/0 sui due
  lasciati com'erano (solo commento), 10/0 su `kodi_utils.py` (solo commento), 14/3 su `service.py`.

## Da verificare sul dispositivo

1. **Il guadagno.** Aprire la home, aspettare che i tre widget finiscano (righe `PERF`), entrare in
   un film e uscirne. **Non devono comparire nuove righe `PERF` per i widget da 48 e 54 elementi**,
   ne' all'apertura ne' alla chiusura. Quella da 9 elementi puo' ricomparire: e' voluto.
2. **Il ritardo al primo fotogramma.** Da `VideoPlayer::OpenFile` a `Instancing CRendererMediaCodec`:
   il riferimento e' 4,5 s quando non c'e' una build di mezzo, 13,0 s quando c'e'. Deve stare vicino
   al primo valore anche tornando in home durante il film.
3. **Il rischio.** Guardare un film oltre il 90%, tornare in home e controllare se il badge "visto"
   compare sul film **dentro la lista mdblist** (non solo in continue watching). Se **non** compare,
   l'invalidazione non passa attraverso la cache: e' l'informazione che serve, non una regressione da
   annullare -- e P2.2 diventa obbligatorio invece che opzionale.
4. **La paginazione.** Scorrere un widget fino a caricare pagine nuove: deve funzionare come prima.
   Se si rompe, la diagnosi e' sbagliata alla radice e va annullato tutto il lotto.
5. **P1.1**: nessun modo diretto di vederlo nel log (la lettura non logga). Si verifica solo che non
   compaia nessuna riga `WidgetRefresher` durante la riproduzione, come gia' accadeva.

# Lotto 30 bis — l'esperimento risponde: **P2.1 è falsificato**. Annullato.

Prova sul Mac (log 2026-08-21 23:09:56-23:15:08). Il Mac va bene per questa verifica: tre domande su
quattro sono di **comportamento**, non di velocità, e la logica dei contenitori è la stessa C++ di
Kodi. L'addon sul Mac è un symlink al repo e i file erano stati modificati alle 23:01-23:02, quindi
la sessione delle 23:09 montava il codice nuovo (con `reuselanguageinvoker=false` ogni invocazione
rilegge i `.py`).

## Il risultato: `cacheToDisc=True` non cambia nulla

Riproduzione 1, `OpenFile` alle 23:10:14.007. **Trecento millisecondi dopo**, tutti i widget si
ricostruiscono lo stesso:

```
23:10:14.317  movies trakt_watchlist | 21 elementi      (lasciato a False -- atteso)
23:10:14.367  movies None | 9 richiesti                 (continue watching, lasciato a False -- atteso)
23:10:14.376  mdblist mdblist 91378 | 47 elementi       <- girato a True. RICOSTRUITO LO STESSO
23:10:14.430  mdblist mdblist 2194  | 41 elementi       <- girato a True. RICOSTRUITO LO STESSO
```

Stessa cosa alla chiusura (23:10:44.921 → onde alle 23:10:45.7-46.1). Il path era identico prima e
dopo (`2 pagine | path_pages=-` in entrambi i casi), quindi la chiave di cache era la stessa: doveva
essere un colpo a segno, non lo è stato.

Controllo che la modifica fosse sul percorso giusto: `log_build('mdblist', 'mdblist 91378', …)` alla
riga 115 e `end_directory(handle, cacheToDisc=True)` alla riga 126 stanno **nella stessa funzione**,
`build_mdblist_list` (righe 54-129). Era il punto giusto. Non funziona.

## Perché: l'attribuzione del Lotto 27 bis era un'assunzione, non una misura

Nel Lotto 27 bis avevo scritto: *"È Kodi che ripopola i DirectoryProvider quando la finestra home
viene rimostrata (i widget chiudono con `cacheToDisc=False`)"*. La prima metà è vera e osservata; la
seconda è una **causa dedotta e mai verificata**, e la prova dice che è sbagliata.

`cacheToDisc` governa la cache di cartella di `CGUIMediaWindow` -- quella che serve quando si naviga
avanti e indietro dentro una finestra -- **non** il `CDirectoryProvider` di un widget, che rifà la
richiesta comunque. È anche il motivo per cui l'autore originale metteva `True` sulla navigazione e
`False` sui widget: sui widget non serviva a niente in nessuno dei due sensi.

## Annullato

`git checkout` sui sei indexer e su `kodi_utils.py`. Nel codice non resta nulla: tenere una modifica
inefficace con un commento che dice che funziona sarebbe una bugia nell'albero. Il fix **P1.1 in
`service.py` resta** -- è indipendente e non è in discussione.

## La conseguenza, che è la cosa importante

**P2.2 non è più un raffinamento opzionale: è l'unico meccanismo.** Non esiste una scorciatoia lato
Kodi per far sì che un widget non venga ricostruito; l'unica leva che abbiamo è quella che già
funziona -- il token dentro il path -- e va usata al contrario: non per *forzare* una ricostruzione,
ma perché **il path resti identico** finché non c'è davvero qualcosa da cambiare, e cambi solo per il
widget interessato. L'ordine di lavoro non cambia, cambia il fatto che il passo 2.1 non esisteva.

## Trovato per strada: **i widget si gonfiano a ogni ondata di refresh**

Questa è nuova, ed è un bug, non un'inefficienza. La lista `mdblist 91378`, senza che nessuno
scorra:

```
23:09:57.271    47 elementi |  2 pagine | path_pages=-
23:10:14.376    47 elementi |  2 pagine | path_pages=-     (apertura riproduzione)
23:10:45.776    47 elementi |  2 pagine | path_pages=-     (chiusura)
23:10:45.975    47 elementi |  2 pagine                    (build DUPLICATA, 199 ms dopo)
23:10:47.744    VideoInfoScanner  <- kodi_refresh
23:10:48.041   114 elementi |  5 pagine | path_pages=-
23:10:48.050    VideoInfoScanner  <- kodi_refresh di nuovo, 306 ms dopo il primo
23:10:48.293   202 elementi | 10 pagine | path_pages=-
23:11:30.202   249 elementi | 17 pagine | path_pages=17
```

**Da 47 a 202 elementi in 252 millisecondi**, e a 249 poco dopo: **5,3×**. Nessuno scorre otto pagine
in un quarto di secondo. `path_pages=-` dice che il conteggio non veniva dal path: veniva da
`fenlight.pg.refresh`, il flag che il `kodi_refresh` mette per conservare le pagine già espanse. Due
`kodi_refresh` a 306 ms di distanza, e in mezzo il watcher della paginazione che vede un widget
appena ricostruito col fuoco vicino al fondo e carica avanti.

Il danno non è il quarto di secondo: è che **ogni ricostruzione futura di quel widget costa 5,3
volte tanto**, per sempre. È la spiegazione migliore che abbiamo finora del "più la uso più
rallenta" della stick, e spiega da dove veniva il widget da 130 elementi partito da 48.

## Confermate sul Mac due cose del Lotto 28

* **Build duplicate**: `mdblist 2194 | 65 elementi` costruito da due thread alle 23:10:49.486 e
  23:10:49.489 (1,08 s e 1,37 s); `91378 | 249` due volte alle 23:15:02.495 e 23:15:02.935;
  `trakt_watchlist | 21` due volte alle 23:15:02.347 e 23:15:02.914.
* **Il volume**: **32 ricostruzioni di widget e 4 `UpdateLibrary` in cinque minuti**, con l'utente
  che ha guardato due spezzoni di film e navigato un po'. `trakt_watchlist` da solo: 8 volte.

## Cosa invece regge

Il gate del Lotto 27 tiene: in entrambe le riproduzioni (31 s e 32 s) le build stanno **solo nei
primi 250-420 ms**, poi il log è pulito fino alla chiusura. Durante il film non si costruisce niente.

## Nota di metodo, la terza

È la terza volta che una causa plausibile viene falsificata dalla misura: `reuselanguageinvoker`
(11c), il parse degli include (12), e ora `cacheToDisc`. In tutti e tre i casi il ragionamento
reggeva e la prova no. La regola che ne esce, e che questa volta ho seguito: **un intervento la cui
causa non è stata osservata va trattato come esperimento, con un criterio di fallimento scritto
prima**. Era scritto, è fallito, si annulla in due minuti invece di restare nell'albero per mesi.

## Segnalato, non toccato

I `.pyc` sotto `resources/lib/**/__pycache__/` sono **tracciati da git** e cambiano a ogni
esecuzione: sporcano ogni `git status`. Preesistente, da mettere in `.gitignore` e rimuovere
dall'indice quando si fa pulizia.

# Lotto 31 — il cricchetto delle pagine: un'unità sbagliata, e i widget crescevano da soli

Il bug trovato nel Lotto 30 bis. È un difetto di **unità di misura**, non di logica, ed è il migliore
candidato che abbiamo finora per il "più la uso, più rallenta" della stick.

## La catena

`PAGES_PROP` (`fenlight.pg.<key>.pages`) è il contatore delle pagine di un widget. Viene:

* **letto** da `get_pages()` → `raw_pages()` e usato come `pages_to_load`, cioè **quante pagine
  mostrare**;
* **incrementato di 1** dal watcher della paginazione, che scrive lo stesso valore anche in
  `CTL_PAGES_PROP` → finisce nel path come `&pages=N`;
* **scritto** da `set_state()` alla fine di ogni build.

Le prime due sono in "pagine da mostrare". La terza no. In `mdblist_lists.py` e `trakt_lists.py`
riceveva `pages_consumed`, che `_dub_paginate` definisce così:

```python
target = pages_to_load * limit
...
while pages_consumed < page_cap and consumed < total:
    pages_consumed += 1
    chunk = result[consumed:consumed + limit]
    kept.extend(_dub_keep_chunk(chunk, ...))
    if pages_consumed >= pages_to_load and len(kept) >= target: break
```

`pages_consumed` sono le pagine **grezze lette dalla sorgente** per raccogliere `target`
sopravvissuti al filtro doppiaggio. Se il filtro scarta anche un solo elemento, `pages_consumed >
pages_to_load` **per costruzione**. E quel numero tornava dentro come "pagine da mostrare" alla
ricostruzione successiva.

**Ogni ricostruzione riconvertiva pagine grezze in pagine da mostrare e rimoltiplicava per
1/frazione-sopravvissuta.** Un cricchetto: sale e non scende mai.

## La prova, dal log del Mac del 21/08 (23:10)

`mdblist 91378`, senza che nessuno scorra (`path_pages=-` in tutte e tre le righe: il conteggio non
veniva dal path ma da `PAGES_PROP`):

```
23:09:57.271    47 elementi |  2 pagine richieste
23:10:47.744    VideoInfoScanner  <- kodi_refresh
23:10:48.041   114 elementi |  5 pagine richieste
23:10:48.050    VideoInfoScanner  <- kodi_refresh di nuovo, 306 ms dopo
23:10:48.293   202 elementi | 10 pagine richieste
23:11:30.202   249 elementi | 17 pagine richieste   (lista esaurita: si ferma qui)
```

**Da 47 a 202 elementi in 252 millisecondi.** Il danno non è quel quarto di secondo: è che da lì in
poi **ogni ricostruzione di quel widget costa 5,3 volte tanto, per sempre**. Sulla stick è il motivo
per cui un widget da 48 elementi diventava da 130 dopo qualche film, e ogni onda di refresh
post-riproduzione ne ricostruiva 130 invece di 48.

Il cricchetto si innesca alla **primissima** ricostruzione: già la build di avvio pubblica un conteggio
gonfiato. Sulla stick il filtro doppiaggio scarta molto (`scartati 17`, `scartati 11`, `scartati 12`
su 20 nei log), quindi il fattore è 1,7-2,5× per giro.

C'era anche il commento che documentava la motivazione sbagliata: *"pages_consumed is the REAL number
of pages taken, so set_state records reality"*. L'intenzione — non far chiedere al watcher pagine che
non esistono — è già coperta da `has_more`, che è il gate del watcher.

## La correzione

`set_state(pg_key, pages_to_load, has_more)` invece di `pages_consumed`, in
`mdblist_lists.py:103` e `trakt_lists.py:343`. `pages_consumed` resta nella riga di log, dove è
diagnostica utile (dice quanto sta sfoltendo il filtro).

**Perché è sicuro**: `_dub_paginate` riempie fino a `pages_to_load * limit` sopravvissuti, cioè in
modo **proporzionale** alla richiesta. A parità di `pages_to_load` rende sempre la stessa lunghezza,
quindi registrare la richiesta riproduce esattamente il contenuto — nessun rischio di far accorciare
il contenitore (l'invariante append-only e il fuoco restano). Vale anche quando si tocca il cap: con
lo stesso `pages_to_load` si tocca lo stesso cap e si ottiene la stessa lista, mentre prima il cap
stesso saliva a ogni giro (`page_cap = pages_to_load + 12`, con `pages_to_load` che cresceva).

Conferma indipendente: il ramo **senza** filtro doppiaggio della stessa funzione già restituiva
`pages_to_load`. L'unità era giusta a filtro spento e sbagliata a filtro acceso.

## La distinzione da NON sbagliare: `load_cumulative` è corretta com'è

`load_cumulative` (usata da `movies.py:108` e `tvshows.py:111`) ha la stessa forma — restituisce
`last_page`, le pagine realmente lette, e il chiamante la passa a `set_state`. **Sembra lo stesso bug
e non lo è**, perché il riempimento ha una semantica diversa:

| | target di riempimento | `pages_to_load` riproduce la lunghezza? |
|---|---|---|
| `_dub_paginate` | `pages_to_load * limit` — **proporzionale** | **sì** → registrare la richiesta |
| `load_cumulative` | `min_items` (20, **assoluto**) | **no** → registrare `last_page` |

Con un target assoluto, chiedere di nuovo `pages_to_load` produrrebbe meno pagine di quante il widget
ne mostra, e il contenitore **si accorcerebbe** — esattamente la regressione contro cui mettono in
guardia i commenti del lotto 5. Lì `last_page` è l'unico valore che riproduce la lunghezza, e va
lasciato.

Il commento nei chiamanti dice esplicitamente di non copiare il ragionamento sull'altra funzione.

## Cosa questo NON risolve

Le due `kodi_refresh` a 306 ms di distanza restano, e restano le 32 ricostruzioni in cinque minuti.
Il cricchetto era il moltiplicatore; il numero di ricostruzioni è P2.2, ancora da fare. Ma ora P2.2
lavorerà su widget rimasti della dimensione giusta.

## Verifiche fatte

* fine riga invariate (`mdblist_lists.py` LF, `trakt_lists.py` CRLF);
* `ast.parse` su entrambi;
* simboli contro `HEAD`: nessuno perso, nessuno aggiunto;
* `numstat` 14/1 e 21/3, spiegabili riga per riga (commento + riga cambiata; sul secondo anche la
  docstring riscritta, 4 righe sostituite da 9).

## Da verificare sul dispositivo

Basta il Mac, è una verifica di comportamento.

1. **Il cricchetto è chiuso.** Aprire la home, leggere gli elementi del widget mdblist. Avviare un
   film, chiuderlo. Il widget deve tornare **con lo stesso numero di elementi**: nel log, righe `PERF`
   con lo stesso `N elementi | M pagine` di prima. Prima passava da 47 a 114 a 202.
2. **La paginazione avanza ancora.** Scorrere il widget fino in fondo: deve caricare una pagina alla
   volta (`path_pages=3`, poi `4`, poi `5`...), non collassare al lotto iniziale e non saltare avanti.
3. **Il widget non si accorcia.** Dopo una ricostruzione di un widget espanso a mano (es. 5 pagine),
   deve tornare a 5 pagine, non a 2. È il rischio speculare, ed è quello che il ramo `load_cumulative`
   lasciato invariato protegge per gli altri widget.

# Lotto 31 bis — il cricchetto è chiuso, verificato (log Mac 2026-08-21 23:35:58-23:38:27)

Sessione avviata alle 23:35:58, file corretti alle 23:24-23:25: montava il codice nuovo.

## Le sequenze delle pagine, per widget

```
trakt_watchlist:       2  2  2
tmdb_movies_discover:  2  3  4  5  5  5  5  5
mdblist 91378:         2  3  4  5  6  7  8  9  10  11  12  12  12
mdblist 2194:          2  2  2  3  4  5  6  7  8  9  10
```

**Monotone, +1 alla volta, mai un salto.** Prima la 91378 faceva `2 -> 5 -> 10 -> 17`.

## I tre criteri

**1. Cricchetto chiuso.** Riproduzione 23:37:24.991 -> 23:37:42.082. Cinque ricostruzioni
consecutive dello stesso widget attorno alla riproduzione, numero **identico**:

```
23:36:55   discover | 65 elementi | 5 pagine | path_pages=5   (prima)
23:37:25   discover | 65 | 5 | path_pages=5                   (apertura)
23:37:42.719 / .729 / 23:37:44.968   65 | 5 | path_pages=5    (chiusura, tre volte)
23:37:47.942 / 23:37:52.319   91378 | 249 | 12 | path_pages=12
```

Prima: 47 -> 114 -> 202 in 252 ms.

**2. Paginazione intatta.** `path_pages` segue esattamente 3,4,5,6,7,8,9,10,11,12. Gli elementi
crescono in modo irregolare (47, 61, 86, 114, 129, 142, 170, 184, 202, 236, 249) ed e' **giusto**:
e' il filtro doppiaggio che sfoltisce ogni pagina in modo diverso. La pagina 5 rende 114 elementi
anche adesso; la differenza e' che ci si arriva scorrendo invece che per sbaglio.

**3. Nessun accorciamento** -- il rischio che avevo introdotto io. La 91378 era espansa a 12
pagine / 249 elementi **prima** della riproduzione ed e' tornata `249 | 12 | path_pages=12`. Non e'
collassata al lotto iniziale. Idem la discover a 5 pagine. Conferma che il ragionamento sul
riempimento proporzionale reggeva.

## Cosa resta, ed e' P2.2

Il gate del lotto 27 tiene: nei 17 s di riproduzione c'e' **una sola** build, 238 ms dopo l'apertura,
poi il log e' pulito fino alla chiusura. Ma le onde ci sono tutte:

```
23:37:42.082  CloseFile
23:37:42.719  build discover      | due build dello STESSO widget
23:37:42.729  build discover      | a 10 ms di distanza
23:37:44.874  VideoInfoScanner #1
23:37:44.968  build discover
23:37:47.8-.9 onda completa (watchlist + 91378 + 2194)
23:37:51.969  VideoInfoScanner #2   <- 5,1 s dopo il primo
23:37:52.2-.3 onda completa di nuovo
```

**Due `UpdateLibrary` e ~9 ricostruzioni per una riproduzione di 17 secondi.** In tutta la sessione
di 2,5 minuti: **35 build, 2 `UpdateLibrary`**. Intatto: e' esattamente P2.2 e P2.4.

La differenza e' che ora quelle ricostruzioni lavorano su widget della dimensione scelta dall'utente.
Sul Mac ricostruire 249 elementi costa `totale 0,14 s`; sulla stick il widget che si gonfiava a 130
costava 2-3 secondi ogni volta, e continuava a crescere.

# Lotto 32 — P2.2-a: le due ondate erano lo stesso evento contato due volte

## La diagnosi, dal log invece che per ipotesi

Le due `UpdateLibrary` dopo una riproduzione hanno un'origine identificata riga per riga:

```
23:37:42.082  CloseFile
23:37:44.874  scan #1   <- 2,79 s dopo: flush_pending_refresh (player.py, dorme 3000 ms)
23:37:51.907  ###Fen Light###: TraktMonitor Service Update Success. Trakt Update Performed
23:37:51.969  scan #2   <- 62 ms dopo la riga di Trakt: service.py, ramo status == 'success'
```

Non sono due cambiamenti: e' **lo stesso**. A fine film mandiamo lo scrobble di stop a Trakt; il
poll successivo (ogni ~30 s) rilegge l'attivita' aggiornata, la classifica come "qualcosa e'
cambiato" e ricostruisce tutta la schermata una seconda volta **per il titolo che abbiamo appena
finito di guardare**. Il costo, per una riproduzione di 17 secondi: una seconda ondata completa
(watchlist + 91378 + 2194), cioe' circa un terzo di tutte le ricostruzioni post-riproduzione.

## La correzione

* `kodi_utils.kodi_refresh()` timbra `fenlight.refresh.last` con l'istante in cui esegue davvero
  l'`UpdateLibrary`, e la nuova `refresh_age()` dice quanti secondi sono passati (un numero enorme se
  non risulta nessuna ricostruzione, cosi' in caso di dubbio si ricostruisce invece di saltare).
* Il `TraktMonitor` esegue la sua ricostruzione **solo se** ne e' passata una da almeno
  `TRAKT_REFRESH_COALESCE = 30` secondi. Altrimenti scrive a log `refresh saltato, interfaccia
  ricostruita N.Ns fa`, cosi' la soppressione e' visibile e non silenziosa.

Blast radius volutamente stretto: **non** e' un debounce dentro `kodi_refresh()`, che avrebbe toccato
tutti e dodici i chiamanti. Si sopprime solo il ramo di Trakt, che e' quello dimostrato ridondante.

## Il compromesso, dichiarato

La sincronizzazione con Trakt **avviene comunque**: `trakt_sync_activities()` ha gia' applicato il
cambiamento alla cache locale. Quello che si salta e' il **ridisegno**. Se in quella finestra di 30 s
fosse arrivato un cambiamento fatto davvero altrove (telefono, sito), il dato c'e' ma l'interfaccia
lo mostra alla prima ricostruzione successiva -- che con la navigazione arriva in pochi secondi (35
ricostruzioni in 2,5 minuti nel log di riferimento). Il caso opposto -- un'ondata completa doppia
dopo **ogni** riproduzione, per sempre, su un dispositivo da 1 GB -- e' peggiore.

`TRAKT_REFRESH_COALESCE` e' tarata sopra il ritardo osservato (7,1 s) con margine. Alzarla sopprime
piu' duplicati e ritarda di piu' un cambiamento esterno.

## Verifiche fatte

fine riga invariate (`service.py` LF, `kodi_utils.py` CRLF); `ast.parse` su entrambi; simboli contro
`HEAD`: nessuno perso, unico nuovo `refresh_age` (voluto); `numstat` 32/5 e 17/0, spiegabili.

## Da verificare (basta il Mac)

1. Avviare e chiudere un film. Nel log deve comparire **una sola** riga `VideoInfoScanner: Starting
   scan` invece di due, e **una sola** ondata di ricostruzione invece di due.
2. Deve comparire la riga `TraktMonitor: refresh saltato, interfaccia ricostruita N.Ns fa`. Se non
   compare, la soppressione non e' scattata e la diagnosi va rivista.
3. Il badge "visto" e il widget "continua a guardare" devono aggiornarsi lo stesso: e' la prima
   ondata a farlo, quella soppressa era la copia.

---

# P2.2-b — il refresh mirato: progetto, non ancora scritto

Perche' separato: P2.2-a e' deterministico e verificabile da solo; P2.2-b poggia su due assunzioni
non ancora osservate. Mescolarli renderebbe illeggibile il log -- non si saprebbe quale dei due ha
ridotto le ricostruzioni. Regola gia' fissata nel lotto 30 bis.

## Il sotto-problema che lo blocca

Il token di ricarica mirata e' indicizzato per **id del contenitore**
(`fenlight.pg.ctl<ID>.pages`, `Includes_Hubs.xml:124` e `:178`), perche' l'id e' l'unica cosa che la
skin conosce al momento dell'include. Ma chi vuole ricostruire un widget sa il **tmdb_id cambiato**,
non l'id del contenitore. Manca la catena `tmdb_id -> chiave widget -> id contenitore`.

`CTL_KEY_PROP` (`service.py:236`) tiene `id contenitore -> chiave`, ma lo scrive **solo per il
contenitore che ha il fuoco**: non esiste una mappa generale.

## Il progetto

1. **`chiave -> insieme di tmdb_id`**: `paginator.set_head(key, items)` gira gia' subito dopo
   `add_items` in tutti e quattro gli indexer interattivi. Li' si pubblica anche l'elenco degli id
   costruiti (`fenlight.pg.ids.<key>`). ~250 id sono ~1,7 KB di proprieta': accettabile.
2. **`id contenitore -> chiave`, a domanda**: i contenitori dei widget sono **501-504**, un
   intervallo piccolo e fisso (verificato nel file generato e in `Includes_Search.xml`). Al momento
   del refresh mirato si sondano quegli id con
   `Container(N).ListItemAbsolute(0).FolderPath` e si risolve la chiave con `head_lookup()`, che
   esiste gia'. Nessun polling aggiunto: il sondaggio avviene dentro l'invocazione di refresh, una
   volta.
3. **Il colpo mirato**: per ogni contenitore la cui chiave contiene un id cambiato, si scrive
   `CTL_PAGES_PROP % id` con un nonce accodato (`"12&reload=<n>"` -> path `&pages=12&reload=<n>`).
   `reload` e' **gia'** in `_VOLATILE_PARAMS` (`paginator.py:47`), quindi non altera la chiave del
   widget e la paginazione non se ne accorge.
4. **Rete di sicurezza**: se il sondaggio non risolve nessun contenitore, si ricade sul
   `kodi_refresh()` globale di oggi. Cosi' il comportamento non puo' mai essere peggiore
   dell'attuale, e il log dice da solo se il sondaggio ha funzionato.

## Le due assunzioni da verificare, e come

* **A1** -- `Container(N).ListItemAbsolute(0).FolderPath` risolve anche per un contenitore **senza
  fuoco**, letto da un'invocazione di plugin. Probabile (gli infolabel `Container(id)` non sono
  legati al fuoco), mai osservato qui.
* **A2** -- cambiare `CTL_PAGES_PROP` di un contenitore **senza fuoco** ne innesca davvero la
  ricostruzione. Il watcher lo fa sempre e solo sul contenitore col fuoco.

Entrambe le rispondera' il primo log dopo l'implementazione, grazie alla rete di sicurezza del punto
4: se una delle due cade, si vede la ricaduta sul globale e non una regressione.

# Lotto 32 bis — la soppressione funziona, ma solo in una direzione. Corretta.

Log Mac 2026-08-21 23:48:36-23:50:06, **due** riproduzioni. Averne fatte due e' cio' che ha rivelato
il difetto: si comportano diversamente.

## Riproduzione 1: funziona

```
23:49:24.688  CloseFile
23:49:28.451  VideoInfoScanner   <- flush_pending_refresh (unico)
23:49:30.088  TraktMonitor: Trakt Update Performed
23:49:30.089  ###Fen Light###: TraktMonitor: refresh saltato, interfaccia ricostruita 1.7s fa
```

**Una sola `UpdateLibrary` invece di due**, e la soppressione e' scritta a log come previsto. Otto
ricostruzioni invece delle nove della sessione precedente.

## Riproduzione 2: NON funziona, e il motivo e' istruttivo

```
23:49:57.741  CloseFile
23:50:00.483  TraktMonitor: Trakt Update Performed
23:50:00.655  VideoInfoScanner   <- innescato da TRAKT: 172 ms dopo
23:50:00.937  VideoInfoScanner   <- flush_pending_refresh: 282 ms dopo il primo
```

Qui **Trakt e' arrivato prima**. Quando ha controllato, l'ultima ricostruzione risaliva a 32,2 s
prima (quella della riproduzione 1): oltre i 30 s della soglia, quindi non soppressa — **e la regola
ha funzionato correttamente**. Poi `flush_pending_refresh` e' partito 282 ms dopo, e lui non e'
gatato da nulla.

Il difetto e' mio: avevo messo la guardia **su un solo chiamante**, quello che nel primo log era
arrivato secondo. La corsa fra i due puo' finire in entrambi i modi -- dipende da quanto dista la
chiusura dal poll di Trakt -- e la guardia asimmetrica copre solo un esito.

## La correzione: accorpamento simmetrico dentro `kodi_refresh()`

`REFRESH_COALESCE_SECONDS = 5` in `kodi_utils.py`: chi arriva primo ricostruisce, chi arriva entro
cinque secondi scrive `kodi_refresh accorpato: ricostruzione N.NNs fa` e si ferma. Simmetrico per
costruzione: non importa chi vince la corsa.

Avevo evitato apposta di toccare `kodi_refresh()` per non coinvolgere i dodici chiamanti. La prova
dice che l'asimmetria **era** il difetto, quindi il posto giusto e' qui. La finestra e' corta (5 s
contro i 30 del gate Trakt) perche' deve sopprimere solo le **collisioni**, non un cambiamento
davvero diverso arrivato qualche secondo dopo.

`PENDING_REFRESH_PROP` viene azzerata **anche quando si accorpa**: la richiesta rimandata e'
soddisfatta dalla ricostruzione appena avvenuta, e lasciarla accesa farebbe scattare la rete di
sicurezza del `WidgetRefresher` — una terza onda.

Il gate Trakt a 30 s resta: i due meccanismi dicono cose diverse e complementari.

* accorpamento a 5 s — *"due ricostruzioni accavallate sono una"*;
* gate Trakt a 30 s — *"Trakt sta riecheggiando lo scrobble che gli abbiamo appena mandato noi"*
  (nel primo log distavano 7,1 s, fuori dalla finestra dei 5).

## Confermato di nuovo: nessun cricchetto

In tutta la sessione i widget restano a `47 | 2 pagine`, `41 | 2 pagine`, `21 | 2 pagine`, attraverso
due riproduzioni e quattro ondate. Il lotto 31 regge.

## Resta aperto: le build duplicate dentro la stessa ondata

Non e' l'`UpdateLibrary` doppia — e' un'altra cosa, e ora si vede pulita:

```
23:49:25.184  trakt_watchlist | 21    23:49:58.531  trakt_watchlist | 21
23:49:25.219  mdblist 91378  | 47     23:49:58.558  mdblist 91378  | 47
23:49:25.405  mdblist 91378  | 47  <- 23:49:58.749  mdblist 91378  | 47  <-
23:49:25.475  trakt_watchlist | 21 <- 23:49:58.807  trakt_watchlist | 21 <-
23:49:25.508  mdblist 2194   | 41     23:49:58.852  mdblist 2194   | 41
```

Lo stesso widget costruito due volte a 190-290 ms di distanza, **senza nessuna `UpdateLibrary` in
mezzo**, in entrambe le riproduzioni. E' il ripopolamento della home da parte di Kodi che si
sovrappone a qualcos'altro: raddoppia la prima ondata. E' P2.5, e ora ha un caso riproducibile.

## Da verificare

1. Due riproduzioni ravvicinate, chiuse a mano. In **entrambe** deve comparire una sola
   `VideoInfoScanner: Starting scan`.
2. Almeno una volta deve comparire `kodi_refresh accorpato: ricostruzione N.NNs fa`. Se non compare
   mai ed escono comunque due scan, la corsa avviene fuori dalla finestra dei 5 s e va allargata.
3. Badge "visto" e "continua a guardare" devono aggiornarsi comunque.

# Lotto 32 ter — accorpamento validato: una sola `UpdateLibrary` per riproduzione

Log Mac 2026-08-21 23:53:10-23:54:40, due riproduzioni. **In ognuna e' scattato un meccanismo
diverso**, che e' la ragione per cui erano due.

```
pb1  23:53:46.304 CloseFile
     23:53:48.965 VideoInfoScanner                        <- flush_pending_refresh
     23:53:53.684 TraktMonitor: refresh saltato, interfaccia ricostruita 4.7s fa   <- gate Trakt 30s

pb2  23:54:32.938 CloseFile
     23:54:34.069 TraktMonitor: Trakt Update Performed
     23:54:34.117 VideoInfoScanner                        <- Trakt (45,2s dall'ultima: giusto eseguirlo)
     23:54:35.844 kodi_refresh accorpato: ricostruzione 1.74s fa                   <- accorpamento 5s
```

La corsa e' finita nei due modi opposti e ogni meccanismo ha coperto il suo.

| | scan | build |
|---|---|---|
| baseline (23:37) | 2 | 9 |
| dopo P2.2-a, pb sfortunata (23:48) | 2 | 11 |
| **ora, entrambe** | **1** | **8** |

Cricchetto ancora chiuso: `86 | 4 pagine` invariato attraverso due riproduzioni e quattro ondate.

## Resta P2.5, ma va trattato come sospetto

```
23:53:47.203  trakt_watchlist | 21
23:53:47.330  mdblist 91378   | 86
23:53:47.504  trakt_watchlist | 21   <- duplicato, 301 ms dopo
23:53:47.529  mdblist 91378   | 86   <- duplicato, 199 ms dopo
23:53:47.561  mdblist 2194    | 41
```

Prima ondata: 5 build per 3 widget. Seconda (dopo lo scan): 3 pulite. **I duplicati avvengono senza
nessuna `UpdateLibrary` in mezzo**: non li innesca il nostro codice, e' Kodi che ripopola i
DirectoryProvider al ritorno della home -- le stesse ricostruzioni su cui `cacheToDisc` si e'
rivelato non avere presa (lotto 30 bis). Prima di investirci va verificato che una leva esista.

# Lotto 33 — P2.2-b: la ricarica mirata per id

Finora, chiudere un film ricostruiva **tutti** i widget della schermata. Ma se hai visto Matrix,
l'unica cosa cambiata e' Matrix. Mancava solo il modo di rispondere alla domanda *"questo widget
contiene il film che e' cambiato?"*.

## I tre pezzi

**1. Ogni widget si annota cosa contiene.** `paginator.set_head()` gira gia' subito dopo `add_items`
in tutti e quattro gli indexer interattivi. Ora pubblica anche `fenlight.pg.ids.<chiave>`, l'elenco
dei tmdb_id costruiti. L'estrazione e' uniforme e non richiede di conoscere la forma dei dati di
ciascun indexer: **ogni URL di elemento porta `tmdb_id=`** (`URL_PLAY`, `URL_OPTIONS`, `URL_MARK`...),
quindi basta una regex sul path. ~250 id sono ~1,7 KB di proprieta'.

**2. Si sondano i contenitori.** I widget di Arctic Fuse stanno nei contenitori **501-504**
(verificato nel file generato e in `Includes_Search.xml`); si sonda 500-520 per lasciare margine a una
riconfigurazione della home. Per ciascuno: `Container(N).ListItemAbsolute(0).FolderPath` ->
`head_lookup()` -> chiave -> elenco id. Una `getInfoLabel` per contenitore, **una volta per refresh**,
non in un ciclo: nessun polling aggiunto.

**3. Il colpo mirato.** Si scrive `fenlight.pg.ctl<N>.pages` con il numero di pagine **invariato** e un
nonce accodato: `"4&reload=1755823456789"` -> path `...&pages=4&reload=1755823456789`. Il token vive
dentro il `<content>` come `$INFO[]`, quindi cambiarlo ricarica **solo quel contenitore**.
`reload` era **gia'** in `_VOLATILE_PARAMS` (`paginator.py:62`), quindi non entra nella chiave del
widget e la paginazione non se ne accorge. Verificato che `CTL_PAGES_PROP` non viene mai **letto**
come intero da nessuna parte (solo scritto o azzerato in `service.py:246, 254, 305`), quindi il nonce
non puo' rompere il watcher.

## La regola e' PRUDENTE, e questo e' il punto delicato

Si salta un contenitore **solo quando si riesce a dimostrare che non c'entra**: identificato **e**
con un elenco di id che non contiene nessuno di quelli cambiati. Tutto il resto viene ricaricato.

Serviva, e non e' teoria: **`continue_watching` non chiama `set_head`** -- non e' un widget paginato,
quindi non ha ne' chiave ne' elenco. Con una regola ottimistica ("ricarica solo cio' che riconosci")
sarebbe rimasto fermo, ed e' proprio il widget che **deve** cambiare a fine film. Con la regola
prudente si ricarica come prima. Stesso discorso per un widget il cui elenco non e' stato pubblicato.

## Rete di sicurezza

Se il sondaggio non identifica **nessun** contenitore Fen Light, `kodi_refresh_ids()` scrive a log
`refresh mirato: nessun contenitore identificato, si ricostruisce tutto` e chiama il `kodi_refresh()`
globale di oggi. Il comportamento non puo' essere peggiore dell'attuale, e il log dice da solo se il
sondaggio ha funzionato.

Un refresh mirato riuscito timbra `LAST_REFRESH_PROP`: senza, il monitor Trakt sparerebbe comunque il
globale un secondo dopo per lo stesso evento e il lavoro mirato sarebbe sprecato (lotto 32).

## Chi lo usa

`FenLightPlayer.flush_pending_refresh()`, cioe' il caso piu' frequente in assoluto: **e' finito un
film e ne conosciamo il tmdb_id**. Gli altri chiamanti di `kodi_refresh()` restano globali: chi non sa
cosa e' cambiato non puo' mirare, e va bene cosi'.

## Aspettativa onesta, ridimensionata

Nel messaggio precedente avevo detto "da 8 ricostruzioni a 1-2". **Sbagliato**, e va corretto: delle 8
build per riproduzione, **5 sono della prima ondata, che e' Kodi che ripopola la home al rientro** --
non passa da noi e su quella non abbiamo leva (e' cio' contro cui `cacheToDisc` ha fallito). Le
nostre sono le **3 della seconda ondata**. P2.2-b agisce solo su quelle: 3 -> 1 o 2. Circa **il 25%
del totale sul Mac**, di piu' sulla stick dove le ondate nostre erano quattro.

## Verifiche fatte

* fine riga invariate (`paginator.py` e `service.py` LF, `kodi_utils.py` e `player.py` CRLF);
* `ast.parse` su tutti e quattro;
* simboli contro `HEAD`: **nessuno perso**; nuovi solo i voluti (`_item_url`, `_publish_ids`,
  `refresh_containers_for_ids`, `kodi_refresh_ids`);
* prova a secco della regex e della logica di intersezione: id estratti correttamente da URL misti,
  un widget che non contiene l'id viene saltato, uno che lo contiene no, e il numero di pagine si
  ricava correttamente dal token con nonce (`'4&reload=...'.split('&')[0]` -> `'4'`).

## Da verificare (Mac)

Le due assunzioni mai osservate finora si risolvono con questo log.

1. **A1 + A2 insieme** -- avviare e chiudere un film. Nel log deve comparire
   `refresh mirato: N contenitori ricaricati` con N maggiore di zero, e **nessuna**
   `VideoInfoScanner: Starting scan` nella seconda ondata. Se compare invece
   `nessun contenitore identificato`, A1 e' falsa: gli infolabel `Container(N)` non risolvono fuori
   dal fuoco, e la rete di sicurezza ha fatto il suo lavoro.
2. **Il mirato ha davvero mirato** -- nella riga `refresh_for_ids ... ricaricati=N saltati=M` di
   `paginator.log` (visibile con il log della paginazione acceso) M deve essere maggiore di zero:
   significa che almeno un widget e' stato riconosciuto come non interessato e risparmiato.
3. **Il badge compare lo stesso** -- guardare un film oltre il 90%, tornare in home: badge "visto" e
   widget "continua a guardare" aggiornati. Se il badge NON compare sul film dentro la lista mdblist,
   il widget e' stato saltato a torto e va rivista l'estrazione degli id.
4. **La paginazione regge** -- un widget espanso a N pagine deve tornare a N pagine dopo la
   riproduzione, non collassare: il nonce non deve alterare il conteggio.

# Lotto 33 bis — il mirato non era cablato dove serviva. Corretto.

Log Mac 2026-08-22 00:15:31-00:16:52, due riproduzioni.

## Il verdetto: silenzio totale

Nel log **non compare nessuna delle due righe** di `kodi_refresh_ids`: ne' `refresh mirato: N
contenitori ricaricati`, ne' `nessun contenitore identificato, si ricostruisce tutto`. La funzione
non e' stata chiamata affatto. E la `VideoInfoScanner: Starting scan` post-riproduzione c'e' ancora
(00:16:14.380 e 00:16:45.464), quindi qualcuno il globale lo spara comunque.

L'assenza della riga di ricaduta e' la prova che decide: non era A1 o A2 a essere false. **Ero
attaccato al ramo sbagliato.**

## Il ramo giusto

`flush_pending_refresh()` -- dove avevo cablato il mirato -- in pratica **non fa mai niente**. Il suo
stesso commento lo diceva e non l'avevo letto fino in fondo: aspetta 3000 ms *"per lasciar passare
prima il refresh del segnalibro, che parte da run_media_progress dopo 2s e azzera la stessa
proprieta'"*. Al risveglio trova `PENDING_REFRESH_PROP` gia' azzerata ed esce.

Chi ricostruisce davvero e' `run_media_progress(..., do_refresh=True)` (`player.py:231`), lanciato in
un thread da `mark_as_watched` e da `set_bookmark`:

```python
ku.sleep(2000)
ku.run_plugin({'mode': 'refresh_widgets'})
```

I tempi combaciano: `CloseFile` 00:16:10.946 -> sleep 2000 ms -> `refresh_widgets()` che fa
`sleep(250)` -> `kodi_refresh` -> scan a 00:16:14.380, cioe' 3,43 s dopo. E' quello.

## La correzione

Il mirato va in `run_media_progress`, che conosce `self.tmdb_id`. Il cablaggio su
`flush_pending_refresh` resta: serve per i video che **non** passano da li' (trailer, video generici),
dove `PENDING_REFRESH_PROP` viene davvero valorizzata.

In piu', `kodi_refresh_ids` ora alza e riabbassa `fenlight.refresh_widgets` come faceva
`refresh_widgets()`: e' il segnale che i widget "random" leggono per riestrarre
(`random_lists.py:84` e `:270`). Senza, il loro comportamento sarebbe cambiato di riflesso -- una
modifica non voluta e non richiesta.

Nota di progetto verificata: il mirato **non** ha bisogno di `fenlight.pg.refresh`, il flag che fa
conservare le pagine espanse. Il numero di pagine viaggia nel path (`&pages=N` conservato tale e
quale, nonce a parte), e `get_pages` preferisce `path_pages`. E' proprio il motivo per cui questo
meccanismo puo' funzionare.

## Quello che il log conferma comunque

* L'accorpamento del lotto 32 regge in entrambe le riproduzioni: `TraktMonitor: refresh saltato,
  interfaccia ricostruita 1.3s fa` e `... 0.6s fa`. Una sola `UpdateLibrary` per riproduzione.
* Il cricchetto resta chiuso: `86 | 4 pagine` invariato attraverso due riproduzioni.
* La divisione delle ondate e' quella dichiarata: 5 build subito dopo `CloseFile` (Kodi che ripopola,
  non nostre) + 3 dopo lo scan (nostre). Il mirato agisce su quelle 3.

## Lezione

Avevo verificato la regex, l'intersezione, il token, i simboli, le fine riga -- tutto tranne **che il
codice venisse eseguito**. Le due assunzioni A1 e A2 restano non verificate: il prossimo log le
risolve davvero, perche' adesso la funzione viene chiamata e in ogni caso scrive una riga.

## Da verificare (Mac)

1. Deve comparire **una** delle due righe `refresh mirato: ...`. Qualunque delle due: se compare la
   ricaduta, A1 e' falsa e lo sappiamo; se compare `N contenitori ricaricati`, ha funzionato.
2. Con N maggiore di zero, **nessuna** `VideoInfoScanner: Starting scan` dopo la riproduzione.
3. Badge "visto" e "continua a guardare" aggiornati lo stesso.
4. Widget espanso a N pagine ancora a N pagine dopo la riproduzione.

# Lotto 34 — il mirato FUNZIONA (A1 e A2 sono vere), e due difetti residui

Log Mac 2026-08-22 00:22:20-00:24:53, tre riproduzioni.

## Il risultato principale

```
00:24:16.949  ###Fen Light###: refresh mirato: 2 contenitori ricaricati
00:24:42.697  ###Fen Light###: refresh mirato: 2 contenitori ricaricati
```

**A1 e A2 sono entrambe vere**: gli infolabel `Container(N)` risolvono anche per un contenitore
**senza fuoco**, e cambiarne il token ne innesca davvero la ricostruzione. Il sondaggio 500-520
identifica i contenitori e il colpo mirato arriva a destinazione. Due su tre ricaricati, uno
risparmiato.

**La terza riproduzione e' il caso pulito**: chiusura alle 00:24:39.761, nessuna
`VideoInfoScanner: Starting scan`, `refresh mirato: 2 contenitori ricaricati` alle 00:24:42.697, e
**una sola** riga di ricostruzione dopo (`mdblist 91378`) invece di tre. Poi `TraktMonitor: refresh
saltato, interfaccia ricostruita 4.6s fa`.

## La prima riproduzione non era un crash

L'utente ha segnalato che il player si e' chiuso da solo. Il log dice altro:

```
00:23:30.001  Process - eof reading from demuxer
00:23:30.001  CVideoPlayer::OnExit()
```

**La sorgente e' finita.** Era un torrent `UNCACHED` su TorBox (decine di righe
`DEBRID TorBox UNCACHED` alle 00:23:13), quindi il file non era completo: il player ha riprodotto 12
secondi e ha trovato la fine dello stream. Non e' codice nostro, e non e' un crash: e' una sorgente
rotta. Sintomo a corredo: `OutputPicture - timeout waiting for buffer` a 00:23:25 e
`Trakt Error: 422 scrobble/stop` (Trakt rifiuta uno scrobble di 12 secondi).

Conseguenza secondaria: `run_media_progress` non e' partito, quindi per quella riproduzione non c'e'
nessun refresh mirato -- lo scan alle 00:23:35.100 e' del monitor Trakt (155 ms dopo la sua riga), non
soppresso perche' l'ultima ricostruzione risaliva a 36 s prima.

## Difetto 1: due ricostruzioni per lo stesso evento, a 46 ms di distanza

Riproduzione 2:

```
00:24:16.903  VideoInfoScanner: Starting scan     <- flush_pending_refresh, ramo GLOBALE
00:24:16.949  refresh mirato: 2 contenitori ricaricati   <- run_media_progress, 46 ms dopo
```

`flush_pending_refresh` usava il mirato solo per `kind != 'refresh_widgets'`. Quando la richiesta
rimandata era di tipo `refresh_widgets` ricadeva sul globale, **in parallelo** al mirato dell'altro
percorso. La distinzione non serve piu': `kodi_refresh_ids` alza da sola `fenlight.refresh_widgets`.

Correzione doppia, perche' una sola non basta a coprire tutte le corse:

* `flush_pending_refresh` usa il mirato per **entrambi** i tipi quando l'id e' noto;
* `kodi_refresh_ids` rispetta la **stessa finestra di accorpamento** di `kodi_refresh()`
  (`REFRESH_COALESCE_SECONDS`): due ricostruzioni accavallate sono la stessa, e non importa se una e'
  mirata e l'altra globale.

## Difetto 2: "azzera avanzamento" lento e senza risposta -- segnalato dall'utente

`erase_bookmark` aveva l'ordine **rovesciato**, lo stesso che avevamo gia' corretto per `set_bookmark`
nel lotto 27 e che qui era rimasto:

```python
resume_id = ...            # lettura locale
sleep(1000)                # un secondo di attesa, bloccante
trakt_progress(...)        # chiamata di RETE a Trakt
watched_db.execute(DELETE) # solo ORA si cancella in locale
refresh_container(...)     # e solo ora si aggiorna l'interfaccia
```

Un secondo di sonno piu' un giro di rete **prima** di toccare il dato che il badge legge. Da li' la
sensazione che il comando non facesse niente.

Ora: si legge il `resume_id` (locale, gratis), si **cancella subito**, si aggiorna **subito**
l'interfaccia con la ricarica mirata sull'id che l'utente ha appena toccato, e l'allineamento con
Trakt -- attesa di un secondo compresa -- lo paga un thread di sfondo. Se fallisce, la riga locale e'
comunque gia' andata e il segnalibro remoto viene ripulito alla prima sincronizzazione utile.

Aggiunta `refresh_container_for(media_id, refresh)`: quando si sa **quale** elemento e' cambiato --
e in tutte le voci del menu contestuale si sa -- si ricaricano i soli contenitori che lo contengono.
Per ora la usa `erase_bookmark`; gli altri cinque chiamanti di `refresh_container` restano globali e
sono candidati naturali per lo stesso trattamento.

**Sull'avviso**: l'utente segnala anche che non compare nessuna conferma. Non l'ho aggiunta: la
regola del progetto e' "aspetto invariato" e una notifica e' una modifica visibile. Con l'operazione
resa istantanea, il segno di riuscita e' l'interfaccia che si aggiorna. Se serve comunque un avviso,
e' una riga (`notification` e' gia' importata in `watched_status.py`) ma va deciso.

## Verifiche fatte

fine riga invariate (`player.py`, `kodi_utils.py`, `watched_status.py` CRLF); `ast.parse` su tutti;
simboli contro `HEAD`: nessuno perso, nuovi solo i voluti (`_clear_progress_on_trakt`,
`refresh_container_for`, piu' `_push_bookmark_to_trakt` che era gia' nel working tree dal lotto 27).

## Da verificare (Mac)

1. **Una riproduzione normale, con una sorgente CACHED**, chiusa a mano oltre il minuto: deve
   comparire `refresh mirato: N contenitori ricaricati` e **nessuna** `VideoInfoScanner`.
2. **Nessuna coppia** scan + mirato ravvicinata: se ricompare, deve esserci `refresh mirato
   accorpato: ricostruzione N.NNs fa`.
3. **"Azzera avanzamento" deve essere istantaneo**: il film sparisce da "continua a guardare" subito,
   e nel log deve comparire `refresh mirato: N contenitori ricaricati` invece di
   `VideoInfoScanner`. Controllare anche che il segnalibro resti cancellato dopo il successivo
   `TraktMonitor ... Update Performed` (cioe' che il thread di sfondo abbia fatto il suo lavoro).
4. Badge "visto" ancora corretto, e widget espanso a N pagine ancora a N pagine.

# Lotto 34 bis — l'alternanza pari/dispari: l'accorpamento guardava solo l'orologio

Log Mac 2026-08-22 00:32:20-00:35:02. L'utente segnala che "azzera avanzamento" e' istantaneo alla
prima, terza, quinta interazione, e non alla seconda e alla quarta. Il log lo mostra esatto:

```
00:32:28.548  refresh mirato: 1 contenitori ricaricati            <- 1a  OK
00:32:32.037  refresh mirato accorpato: ricostruzione 3.49s fa    <- 2a  SALTATA
00:32:39.141  refresh mirato: 1 contenitori ricaricati            <- 3a  OK
00:32:43.607  refresh mirato accorpato: ricostruzione 4.47s fa    <- 4a  SALTATA
00:32:48.699  refresh mirato: 1 contenitori ricaricati            <- 5a  OK
```

## Il meccanismo, che e' aritmetico

L'utente azzera un avanzamento ogni ~3,5-4,5 secondi. La finestra di accorpamento e' 5 secondi.
La prima passa e timbra l'orologio; la seconda cade dentro la finestra e viene **buttata via**; e
siccome una richiesta saltata **non timbra**, la terza si misura dall'ultima ESEGUITA ed e' di nuovo
fuori finestra. Alternanza perfetta, per costruzione.

## L'assunzione sbagliata, che e' mia

L'accorpamento (lotto 32 bis) nasce da *"due ricostruzioni accavallate sono la stessa"*. E' vero per
la corsa post-riproduzione -- **stesso film**, due chiamanti diversi -- ed e' **falso** quando e'
l'utente a fare operazioni **diverse** in fila. Guardavo l'orologio e non cosa era cambiato, pur
avendo gli id in mano.

## La correzione: si accorpa per COPERTURA, non per tempo

Nuova proprieta' `fenlight.refresh.last.scope`: `'*'` se l'ultima ricostruzione era globale,
altrimenti gli id ricaricati.

| ultima | nuova richiesta | esito |
|---|---|---|
| mirata su A | mirata su A | accorpa |
| mirata su A | mirata su **B** | **esegue** (era il difetto) |
| mirata su A | mirata su A+B | esegue |
| globale | mirata su qualunque | accorpa |
| globale | globale | accorpa |
| **mirata su A** | **globale** | **esegue** |

L'ultima riga e' l'altra meta' dello stesso difetto: `kodi_refresh()` si accorpa ora **solo dietro
un'altra globale**. Dietro una mirata no -- una globale puo' riguardare tutt'altro, e saltarla lo
perderebbe. La soppressione dell'eco di Trakt post-riproduzione non ne risente: la fa il gate a 30 s
in `service.py`, che nel log ha funzionato tre volte su tre (`refresh saltato, interfaccia
ricostruita 4.3s / 3.4s / 1.9s fa`).

Regola verificata a secco su cinque scenari reali prima di spedirla, compresi i due che il log ha
prodotto.

## Il resto del test: superato

* **Zero `VideoInfoScanner: Starting scan` in tutta la sessione.** Nessuna ricostruzione globale, mai:
  in tre minuti di uso con due riproduzioni e cinque azzeramenti, il globale non e' mai partito.
* **Riproduzione 1** (00:33:42.687 -> 00:34:08.142, 25,5 s): tre build subito dopo la chiusura (Kodi
  che ripopola), poi `refresh mirato: 2 contenitori ricaricati` e **una sola** ricostruzione
  (00:34:10.686). Prima erano tre.
* **Riproduzione 2**: due mirati riusciti a 6,4 s di distanza (00:34:47.843 e 00:34:54.258) piu' un
  terzo accorpato. Resta della duplicazione fra i percorsi, ma ora costa un contenitore invece di
  tutta la schermata.

## Nota di metodo

Terza volta in questo filone che una regola giusta in un caso viene applicata troppo largamente:
`cacheToDisc` (dedotta e non osservata), la guardia Trakt asimmetrica (un solo chiamante),
l'accorpamento a tempo (un solo tipo di evento). Il denominatore comune: **avevo l'informazione che
distingueva i casi e non la stavo usando** -- qui erano gli id, che il mirato gia' conosceva.

# Lotto 35 — verifica del lotto 34 bis, e la mappa di cosa resta globale

Log Mac 2026-08-22 00:38:44-00:41:18: tre azzeramenti in fila e tre riproduzioni.

## L'alternanza e' sparita

```
00:38:52.197  refresh mirato: 1 contenitori ricaricati
00:38:55.244  refresh mirato: 1 contenitori ricaricati   <- 3,0 s dopo, ESEGUITO
00:38:58.254  refresh mirato: 1 contenitori ricaricati   <- 3,0 s dopo, ESEGUITO
```

Tre azzeramenti a **3,0 secondi** di distanza, tutti e tre eseguiti, nessun `accorpato`. Con la regola
precedente il secondo sarebbe stato buttato via (3,0 < 5). L'accorpamento per copertura funziona.

E l'accorpamento **giusto** si vede lo stesso, alle 00:40:29.391: `refresh mirato accorpato: gli
stessi id ricostruiti 1.21s fa`, dietro a una ricostruzione che aveva gia' coperto quegli id.

## Le riproduzioni

| # | chiusura | esito |
|---|---|---|
| 1 | 00:39:47.868 | `refresh mirato: 1 contenitori ricaricati`, **nessuno scan**, Trakt soppresso |
| 2 | 00:40:26.795 | uno scan globale a +1,4 s, poi il mirato correttamente accorpato |
| 3 | 00:41:08.961 | `refresh mirato: 2 contenitori ricaricati`, **nessuno scan**, Trakt soppresso |

Due su tre completamente pulite. Nella 2 uno scan globale parte 1,4 s dopo la chiusura -- troppo
presto sia per `run_media_progress` (2 s) sia per `flush_pending_refresh` (3 s): viene da un altro
chiamante ancora globale. Non identificato con certezza dal log; la mappa qui sotto dice dove puo'
stare.

## La mappa: cosa e' ancora globale

Censimento completo dei chiamanti di `kodi_refresh()` / `mode=kodi_refresh` / `mode=refresh_widgets`.

**Convertiti in questo lotto** (`watched_status.py`, tutti hanno l'id in mano e sono le voci che
l'utente tocca dal menu contestuale):

| funzione | prima | ora |
|---|---|---|
| `hide_unhide_progress_items` | `kodi_refresh()` | `refresh_container_for(media_id)` |
| `set_bookmark` | `refresh_container(refresh)` | `refresh_container_for(tmdb_id, refresh)` |
| `mark_movie` | `refresh_container(refresh)` | `refresh_container_for(tmdb_id, refresh)` |
| `mark_tvshow` | `refresh_container()` | `refresh_container_for(tmdb_id)` |
| `mark_season` | `refresh_container()` | `refresh_container_for(tmdb_id)` |
| `mark_episode` | `refresh_container(refresh)` | `refresh_container_for(tmdb_id, refresh)` |

Piu' `erase_bookmark`, gia' convertita nel lotto 34. `refresh_container()` resta definita ma non ha
piu' chiamanti: si lascia perche' e' il fallback naturale per chi non ha un id.

**Ancora globali, e vanno bene cosi'** -- chi non sa cosa e' cambiato non puo' mirare:

* `service.py:104` monitor Trakt (gia' gatato a 30 s), `:138` rete di sicurezza, `:151` refresh periodico;
* `base_cache.py:310` svuotamento cache, `router.py:387` e `search.py` voci esplicite, `menu_editor.py:223`;
* le voci di menu **"Refresh Widgets" / "Reload Widgets"** in `seasons.py` ed `episodes.py`: sono
  comandi espliciti dell'utente che chiedono proprio "ricostruisci tutto".

**Ancora globali e convertibili** -- hanno l'id ma non sono stati toccati:

* `apis/trakt_api.py`: otto punti (watchlist, collection, my_lists, e i due `if refresh: kodi_refresh()`
  alle righe 658 e 672). Sono le operazioni "aggiungi/togli dalla watchlist", che l'utente fa dal menu
  contestuale quanto le altre;
* `indexers/dialogs.py:508`;
* `modules/player.py:247` (`run_next_ep`).

## Verifiche fatte

fine riga CRLF invariata; `ast.parse`; simboli contro `HEAD`: nessuno perso; `refresh_container()`
verificata come non piu' chiamata (0 occorrenze oltre la definizione), quindi nessun percorso e'
rimasto a meta'.

---

## Lotto 36 — P2 punto 1: gli ultimi chiamanti convertibili

**Obiettivo.** Chiudere la conversione da refresh globale a refresh mirato per tutti i punti che
hanno gia' in mano l'id di cio' che e' cambiato. Dopo il lotto 35 restavano dieci chiamanti di
`kodi_refresh()` fuori dai fallback; qui si e' deciso, punto per punto, quali sono convertibili.

### Censimento e verdetto

| File | Punto | Cosa cambia | Verdetto |
|---|---|---|---|
| `apis/trakt_api.py` | `remove_from_list` | un titolo esce da una lista utente | **convertito** |
| `apis/trakt_api.py` | `remove_from_watchlist` | un titolo esce dalla watchlist | **convertito** |
| `apis/trakt_api.py` | `remove_from_collection` | un titolo esce dalla collection | **convertito** |
| `apis/trakt_api.py` | `hide_unhide_progress_items` | un titolo sparisce/torna nel «continua a guardare» | **convertito** |
| `indexers/dialogs.py` | `favorites_choice` | un titolo esce dai preferiti | **convertito** |
| `modules/player.py` | `run_next_ep` | — | **gia' fatto nel lotto 34**: la riga censita era il ramo di fallback |
| `apis/trakt_api.py` | `make_new_trakt_list`, `delete_trakt_list` | cambia l'INSIEME delle liste, non un titolo | globale legittimo |
| `apis/trakt_api.py` | `trakt_like_a_list`, `trakt_unlike_a_list` | cambia l'insieme delle liste seguite | globale legittimo |
| `modules/search.py` | ×2 | cronologia ricerche | globale legittimo |
| `caches/base_cache.py` | svuotamento cache | invalida tutto per definizione | globale legittimo |
| `modules/menu_editor.py` | editor menu | cambia la struttura, non i contenuti | globale legittimo |
| `modules/router.py` | voce «Refresh Widgets» | l'utente CHIEDE il globale | globale legittimo |

La distinzione che regge tutta la tabella: **si converte quando cambia lo stato di un titolo, non
quando cambia l'insieme dei contenitori.** Creare o cancellare una lista non ha un tmdb_id da
inseguire — nessun contenitore esistente «contiene» la lista nuova.

### Come sono stati convertiti i tre `remove_from_*`

Quei tre non ricevono un id ma il dizionario che va a Trakt, di forma
`{'movies'|'shows': [{'ids': {'tmdb'|'imdb'|'tvdb': id}}]}`. Due funzioni nuove in `trakt_api.py`:

- `_tmdb_ids_from_data(data)` — estrae i soli `tmdb_id`, perche' sono quelli che `paginator`
  pubblica per ogni contenitore. Se il titolo era identificato per imdb o tvdb la lista esce vuota.
- `_refresh_for_data(data)` — mirato se ci sono id, globale altrimenti.

**Perche' non peggiora mai.** Due reti di sicurezza indipendenti, entrambe gia' esistenti:
1. lista vuota → `_refresh_for_data` chiama direttamente `kodi_refresh()`;
2. dentro una finestra di directory (my_lists, watchlist, collection, preferiti) il sondaggio dei
   contenitori 500-520 non trova widget, `refresh_containers_for_ids` torna 0 e `kodi_refresh_ids`
   ricade da sola sul globale — che li' e' proprio cio' che serve per rileggere la cartella aperta.

Quest'ultimo punto e' il motivo per cui la conversione ha senso anche dove la condizione e'
`path_check(...) or external()`: il ramo `path_check` continua a comportarsi come prima, il ramo
`external()` (chiamata dal menu contestuale di un widget) diventa mirato.

### Pulizia

Rimossa `watched_status.refresh_container()`, rimasta senza chiamanti dopo il lotto 35. Lasciarla
significava tenere in vita un ingresso al refresh globale pronto per essere riusato per sbaglio.

### Verifiche fatte

- `file` su tutti i file toccati: **CRLF preservati** (`trakt_api.py`, `dialogs.py`,
  `watched_status.py` sono CRLF).
- `ast.parse` + `py_compile` su tutti e sei i file della catena refresh.
- **Diff dei simboli di primo livello** contro `HEAD`: in `trakt_api.py` solo due aggiunte
  (`_tmdb_ids_from_data`, `_refresh_for_data`), in `dialogs.py` nessuna differenza, in
  `watched_status.py` la sola rimozione voluta. Nessuna funzione persa.
- `git diff --numstat` spiegabile riga per riga: trakt_api `+30/-4` (1 import + 23 helper + 3 scambi
  + 3 commento/codice; 4 righe sostituite), dialogs `+7/-1`, watched_status `-2` netto.

### Da verificare sul dispositivo

Ogni operazione qui sotto, fatta **da un widget della home**, deve produrre nel log
`refresh mirato: N contenitori ricaricati` e **nessun** `VideoInfoScanner: Starting scan`:

1. togli un titolo dalla watchlist;
2. togli un titolo dalla collection;
3. togli un titolo da una lista personale;
4. nascondi un titolo dal «continua a guardare»;
5. togli un titolo dai preferiti.

Le stesse operazioni fatte **dentro la finestra della lista** devono invece mostrare lo scan
globale: e' il fallback che funziona, non una regressione.

### Stato di P2

Punto 1 chiuso. Restano aperti: la duplicazione fra `flush_pending_refresh` e `run_media_progress`
(costa poco grazie all'accorpamento, ma va deciso chi e' il proprietario), P2.5 (le ricostruzioni
che Kodi fa da solo dopo `CloseFile`, da dimostrare prima di investirci) e il path malformato
`&pages=6`.

---

## Lotto 37 — I menu contestuali non erano mai stati allineati

**Come e' venuto fuori.** Dopo il lotto 36 l'utente ha fatto notare che collection, liste personali,
preferiti e «nascondi da continua a guardare» non li usa piu': li aveva tolti dal menu contestuale,
unico punto di accesso. Quattro delle cinque conversioni del lotto 36 erano quindi su codice morto.

**Lezione, la stessa gia' registrata due volte.** La raggiungibilita' andava verificata PRIMA di
convertire, non dopo. Un censimento di chiamanti dice chi chiama una funzione, non se qualcuno possa
mai arrivarci.

### Il censimento vero

| File | voci di menu | lingua |
|---|---|---|
| `movies.py` | 6-7 | italiano |
| `tvshows.py` | **11** | inglese, originale Fen Light |
| `episodes.py` | **8** (×2 blocchi) | inglese, originale |
| `seasons.py` | **6** | inglese, originale |

Solo i film erano stati ripuliti. Le voci che l'utente credeva rimosse erano ancora li' per serie,
stagioni ed episodi. `addContextMenuItems` e' uno dei setter misurati (fino al 44% del tempo di
costruzione in una FASI del 22/08), e si paga per OGNI elemento costruito.

### Cosa e' stato fatto

Tutti e tre allineati a `movies.py`, su indicazione esplicita dell'utente («le stesse voci attive per
i film valgono per le serie», piu' `Sfoglia` sugli episodi):

| | prima | dopo |
|---|---|---|
| serie | 11 | **5** |
| stagioni | 6 | **3** |
| episodi | 8 | **5** (6 con `Sfoglia`) |

Rimosse: Extras, Browse Recommended, Browse More Like This, In Trakt Lists, Trakt Lists Manager,
Favorites Manager, Reload Widgets. `extras_params` e `more_like_this_params` restano **pubblicate
come proprieta'**: i tasti rapidi di `custom_keys.py` continuano a funzionare, e' solo la voce di
menu a sparire.

Aggiunta alle serie la voce watchlist che avevano i film, con la lettura unica di
`watchlist_tmdb_ids('shows')` in `__init__` (una lettura da cache per costruzione, non una per
elemento) e l'import pigro di `trakt_api`.

**In piu', non richiesto ma della stessa famiglia:** `seasons.py` ed `episodes.py` costruivano ancora
le URL con `build_url`/urlencode, la strada che film e serie avevano gia' abbandonato. Convertite a
formattazione diretta tutte quelle senza testo libero, e tolto il `poster` da `options_params` (URL
da percent-encodare per ogni elemento, per un'icona che si vede solo aprendo il menu). Restano su
`build_url` le sole voci `mark_season`/`mark_episode`, che portano ancora il titolo della serie.

**Ancora aperto:** togliere il titolo anche da quelle due, come fatto per `mark_movie`. Richiede che
`mark_season`/`mark_episode` lo rileggano dai metadati -- `mark_season` gia' carica `tvshow_meta`,
quindi per lei e' gratis. Non fatto qui: tocca `watched_status.py` e merita la sua verifica.

---

## Lotto 38 — «Aggiungi alla watchlist» non era istantaneo

**Sintomo.** Rimuovere dalla watchlist aggiorna il widget subito; aggiungere no.

**Log (22/08, sessione 00:53-00:54).** La rimozione si vede tutta: `refresh mirato: 2 contenitori
ricaricati` alle 00:54:23.079, e 0,48 s dopo il widget si ricostruisce con **20** elementi (erano 21
alle 00:53:04). Dell'aggiunta non c'e' **nessuna traccia**.

### Due difetti sovrapposti, non uno

**1. `add_to_watchlist` non chiamava alcun refresh.** `remove_from_watchlist` si', dal lotto 36.
Asimmetria pura.

**2. Il difetto vero: aggiungere e togliere non sono lo stesso problema.** La regola di
`refresh_containers_for_ids` e' «salta un contenitore solo se si dimostra che non c'entra», cioe' se
il suo elenco di id non contiene nessuno di quelli cambiati. Alla **rimozione** funziona: il widget
mostra ancora il titolo, quindi il suo elenco lo contiene e viene ricostruito. All'**aggiunta** no:
il widget della watchlist non contiene ancora quell'id, quindi viene **dimostrato non c'entrare
proprio mentre e' l'unico che deve cambiare**.

Sistemare solo il punto 1 non avrebbe prodotto nulla di visibile.

### La cura

Identificare un contenitore per **cosa e'**, non per cosa contiene. Nuova `ACTION_PROP`: `set_head`
riceve l'azione del widget (`trakt_watchlist`, `tmdb_movies_popular`, ...) e la pubblica accanto
all'elenco degli id. `refresh_containers_for_ids(ids, actions=())` ricostruisce l'unione dei due
insiemi, e servono entrambi:

- **per id** — i widget che gia' mostrano il titolo, la cui voce di menu deve passare da «Aggiungi» a
  «Rimuovi» o viceversa;
- **per azione** — il widget della watchlist, che cambia composizione.

Nell'accorpamento le azioni si marcano con `@` (`_scope_items`) per non confonderle con i tmdb_id.

### Una corsa che stavamo vincendo per fortuna

`watchlist_toggle` invalidava la cache Trakt **dopo** aver chiamato add/remove, quindi il refresh
partiva prima dell'invalidazione. Alla rimozione funzionava lo stesso perche' `trakt_sync_activities`
ripuliva la cache in tempo. E' una corsa, non una garanzia: e' la stessa forma di ragionamento che
aveva prodotto il falso positivo di `cacheToDisc` (lotto 30 bis). Ora `add_to_watchlist` e
`remove_from_watchlist` accettano `refresh=False`, e l'ordine e' esplicito in `watchlist_toggle`:
**scrivi -> invalida la cache -> ricostruisci**.

Corretta anche una perdita preesistente: `_register` liberava `PAGES/HASMORE/BUILT/LOADING` ma non
`IDS_PROP` quando un widget usciva dal registro.

### Da verificare sul dispositivo

1. **Aggiungi alla watchlist** da un widget della home -> il widget watchlist deve mostrare il titolo
   subito, e nel log deve uscire `refresh mirato: N contenitori ricaricati` con
   `refresh_for_ids ids=1 azioni=1`, senza `VideoInfoScanner: Starting scan`.
2. **Rimuovi dalla watchlist** -> deve restare istantaneo come prima (non regredito).
3. Menu contestuale di **serie, stagioni ed episodi**: voci in italiano, nessuna delle voci rimosse.
4. Su una **serie**: la voce watchlist deve dire «Aggiungi» o «Rimuovi» correttamente.
5. Su un **episodio**: `Sfoglia` deve ancora portare alla serie/stagione.
6. Tasti rapidi Extras e Options: devono funzionare ovunque, anche dove Extras non e' piu' una voce.

---

## Lotto 38 bis — Validazione: la watchlist e' simmetrica

Log del 22/08, sessione 11:44:55 - 11:48:22. Cinque toggle consecutivi, alternando aggiunta e
rimozione, correlando il refresh con la ricostruzione del widget:

| refresh mirato | widget ricostruito | elementi | ritardo | operazione |
|---|---|---|---|---|
| 11:45:25.357 (3 contenitori) | 11:45:25.823 | 21 -> **22** | 466 ms | **aggiunta** |
| 11:45:35.140 (3 contenitori) | 11:45:35.636 | 22 -> **21** | 496 ms | rimozione |
| 11:45:41.956 (3 contenitori) | 11:45:42.556 | 21 -> **22** | 600 ms | **aggiunta** |
| 11:45:49.877 (3 contenitori) | 11:45:50.368 | 22 -> **21** | 491 ms | rimozione |
| 11:45:56.007 (3 contenitori) | 11:45:56.462 | 21 -> **20** | 455 ms | rimozione |

**Aggiunta e rimozione sono ormai indistinguibili**, 455-600 ms in entrambi i versi. Prima
l'aggiunta non produceva alcun evento.

I «3 contenitori» sono l'unione che il lotto 38 ha introdotto: i widget che mostrano il titolo
(per id, la voce deve passare da Aggiungi a Rimuovi) piu' il widget watchlist (per azione).

### Il resto della sessione

- **12 refresh, 11 mirati.** L'unico globale, alle 11:48:05.863, e' preceduto alle 11:47:58.763 da
  `Control 500 in window 10025`: l'utente era dentro una finestra di directory, dove i contenitori
  500-520 non esistono. Il sondaggio non trova nulla e si ricade sul globale -- che li' e'
  **esattamente cio' che serve** per rileggere la cartella aperta. Fallback corretto, non un difetto.
- **Accorpamento Trakt attivo:** `TraktMonitor: refresh saltato, interfaccia ricostruita 7.3s fa`.
- **Nessuna eccezione** in tutta la sessione. La lista `tvshows trakt_watchlist` e' stata costruita,
  quindi il nuovo `watchlist_tmdb_ids('shows')` ha girato senza errori.

### Non ancora verificato

Nella sessione **non e' stata costruita nessuna lista di stagioni o episodi**: le riscritture di
`seasons.py` ed `episodes.py` (lotto 37) restano non esercitate, ed erano le piu' delicate --
`episodes.py` ha due blocchi gemelli e la conversione da `build_url`.

### Osservazione da tenere d'occhio (non una regressione)

`mdblist 2194` (41 serie) oscilla fra **2 ms e 301 ms di costruzione** per gli stessi 41 elementi,
nella stessa sessione: 150x. La prima costruzione a freddo era gia' 288 ms, quindi non e' imputabile
al lotto 37. E' la stessa varianza da concorrenza gia' registrata per l'autotest PERF (117x).

Da notare per quando la si affrontera': **le liste di serie costruite via mdblist non emettono la
riga FASI**, quindi la ripartizione per fase non e' visibile su quel percorso.

---

## Lotto 39 — L'accorpamento ingoiava i comandi dell'utente

**Sintomo riportato.** Episodio segnato come visto e subito dopo come non visto: il secondo comando
va a buon fine su Trakt ma l'interfaccia non cambia. L'utente lo ripete, e stavolta **da errore**,
perche' su Trakt era gia' stato eseguito.

**Log (22/08, 11:52).**

```
11:52:28.673  refresh mirato: nessun contenitore identificato, si ricostruisce tutto
11:52:32.173  refresh mirato accorpato: gli stessi id ricostruiti 3.50s fa
```

Il secondo refresh e' stato scartato.

### Perche', ed e' peggio di come sembra

Due cause sovrapposte:

1. **L'accorpamento per scope tratta due comandi opposti come un evento solo.** «Segna come visto» e
   «segna come non visto» hanno lo stesso tmdb_id, quindi lo stesso scope. Ma sono due cambi di stato
   distinti, non due chiamanti che reagiscono allo stesso evento.
2. **Il primo comando era caduto sul globale** (l'utente era dentro la lista episodi, dove i
   contenitori 500-520 non esistono). Il fallback timbra scope `*`, e `_refresh_covered_by_last`
   risponde «coperto» a **qualunque** richiesta. Da quel momento ogni refresh mirato veniva ingoiato
   per cinque secondi, non solo quello sullo stesso titolo.

### La cura: separare chi chiede

L'accorpamento esiste per **un solo** problema: due chiamanti *automatici* che reagiscono allo stesso
evento (fine riproduzione + monitor Trakt, a un paio di secondi l'uno dall'altro). Non serve mai
quando a chiedere e' l'utente: due comandi consecutivi sono due eventi, punto.

`kodi_refresh(coalesce=True)` e `kodi_refresh_ids(ids, actions, coalesce=True)`. Tutto cio' che nasce
da un comando esplicito passa `coalesce=False`; il fallback al globale **propaga la scelta**, o il
difetto n.2 resterebbe.

| chiamante | accorpa |
|---|---|
| menu contestuale: visto / non visto / azzera avanzamento / nascondi | **no** |
| watchlist, preferiti, rimozioni dalle liste | **no** |
| crea/cancella/segui una lista Trakt, cronologia ricerche, editor menu, svuota cache | **no** |
| voce «Aggiorna widget» | **no** |
| fine riproduzione (`player.py`) | si' |
| monitor Trakt, WidgetRefresher periodico | si' |

**Il caso «Aggiorna widget» meritava un accorgimento.** `refresh_widgets` serve due padroni: la voce
di menu e il servizio periodico, e al router arrivano identiche. Accorpare una richiesta *esplicita*
di aggiornamento e' il caso peggiore possibile, quindi la voce di menu ora si dichiara con
`user=true` nell'URL e il router distingue.

### La forma ricorrente di questi difetti

E' la quarta volta che l'accorpamento sbaglia, sempre nello stesso modo: **una regola corretta per un
caso applicata a un caso che sembrava uguale.** Prima il tempo da solo (lotto 34 bis), poi lo scope
troppo grosso, ora lo scope applicato a chiamanti di natura diversa. Il criterio che mancava non era
tecnico: era *chi* sta chiedendo.

### Verificato nello stesso log, e funziona

- **Sincronizzazione da Trakt:** l'utente ha segnato un film come visto dall'app Trakt; alla sync il
  badge e' comparso. Il percorso automatico non e' toccato.
- 11:53:49.061 `refresh mirato: 2 contenitori ricaricati`.

### Da verificare sul dispositivo

1. Episodio: **visto -> non visto** in rapida successione. Entrambi devono aggiornare l'interfaccia
   subito; il secondo non deve piu' dare errore alla ripetizione.
2. Fine riproduzione: **non deve regredire**. Deve restare una sola ricostruzione, con
   `refresh mirato accorpato` per la seconda ondata.
3. Sync Trakt da telefono: il badge deve continuare a comparire.
4. «Aggiorna widget» premuto due volte di fila: entrambe devono agire.

---

## Lotto 39 bis — Validazione, e una trappola trovata per strada

Log del 22/08, sessione 12:00:47 - 12:02:36. Sei operazioni consecutive di marcatura sugli episodi,
piu' una successiva.

**Il lotto 39 funziona: sette refresh, sette eseguiti, ZERO accorpati.** Nessuna eccezione. Prima,
diversi di questi sarebbero stati ingoiati e l'utente avrebbe ripetuto il comando ottenendo un errore
da Trakt.

### Cosa il log NON puo' dire

L'utente segnala che aggiungere il badge «visto» non ricarica tutto il widget degli episodi mentre
toglierlo si'. **Non e' verificabile da questo log:** `episodes.py` e `seasons.py` hanno **zero**
strumentazione PERF (`movies.py` ne ha 14 punti, `tvshows.py` 4). Sul percorso che l'utente stava
esercitando siamo ciechi. Dal lato nostro le due direzioni sono simmetriche -- `mark_episode` chiama
lo stesso `refresh_container_for` in entrambi i casi -- quindi l'asimmetria, se c'e', nasce a valle.

**Prossimo passo per rispondere davvero:** strumentare `episodes.py` e `seasons.py` come gli altri
due. Finche' non c'e', qualunque spiegazione sarebbe una supposizione.

### La trappola: 500-528 in una finestra Video non sono widget

Tutti e sette i refresh sono caduti sul globale (`nessun contenitore identificato`), perche' l'utente
era dentro la lista episodi. Indagando il perche', e' emerso che nella finestra Video quei numeri
hanno un significato **completamente diverso**:

```xml
<!-- Includes_Views.xml:218 -->
<views>500,501,502,...,520,521,522,523,524,526,528</views>
```

Non sono contenitori di widget: sono le **viste** della finestra (lista, poster, landscape...). Il
log lo mostra: `Control 521 in window 10025`.

**Il difetto latente.** Il sondaggio si ferma a 520, e la vista in uso era la 521: per puro caso e'
uscito a mani vuote ed e' scattato il fallback globale, che e' la cosa giusta. **Con una vista fra
500 e 520** il sondaggio avrebbe trovato un contenitore Fen Light, impostato il token delle pagine --
che li' non governa niente, quindi nessuna ricarica -- e contato `hit=1`. Risultato: nessun
aggiornamento, nessun fallback, **e nessuna traccia nel log**. Il comando sarebbe sparito nel nulla.

**Cura.** `refresh_containers_for_ids` esce subito con 0 quando la finestra attiva e' la 10025. Il
comportamento osservato non cambia; si chiude il caso che non era ancora capitato.

Da notare: e' la stessa forma di errore del `cacheToDisc` (lotto 30 bis) e dell'accorpamento (lotto
39) -- **un identificatore riusato in due contesti con significati diversi**, e una regola tarata su
uno dei due.

### Verificato che non e' regredito

- Sincronizzazione da Trakt (film segnato come visto dall'app del telefono): il badge compare.
- Nessuna eccezione in tutta la sessione.

---

## Lotto 40 — Diagnostica completa: strumentati `episodes.py` e `seasons.py`

Erano gli ultimi due indexer ciechi. `movies.py` aveva 14 punti di misura, `tvshows.py` 4, questi
**zero** -- proprio sulle liste che si ricostruiscono piu' spesso (continua a guardare, prossimi
episodi) e proprio dove l'utente aveva segnalato un comportamento che non sapevamo spiegare.

### Cosa esce ora nel log

Tre nuove famiglie di righe, nella stessa forma delle altre:

| lista | riga `PERF###` | riga `PERF FASI###` |
|---|---|---|
| stagioni di una serie | `seasons <titolo>` | 6 fasi |
| episodi di una stagione | `episodes <categoria>` | 7 fasi |
| continua a guardare / prossimi episodi / calendario | `episodi singoli <list_type>` | **8** fasi |

Fasi: `prep+cm`, `infotag`, `cast+resume`, `setLabel`, `ctxmenu`, `setArt`, `props` -- piu' `meta`
per gli episodi singoli.

### La fase `meta` esiste solo negli episodi singoli, ed e' il punto interessante

Gli altri tre indexer leggono i metadati **una volta per lista** (`movie_meta_prefetch`,
`tvshow_meta_prefetch`, o l'unico `tvshow_meta` della serie). `build_single_episode` invece chiama
`tvshow_meta` **dentro il thread, per ogni elemento**. E' l'unico percorso rimasto con una lettura
per elemento, ed e' quello dei widget della home.

La fase `meta` e' li' apposta per misurare quanto costa. Se pesa, la cura e' la stessa gia' applicata
altrove: un prefetch unico prima del ciclo.

Per lo stesso motivo il confine risoluzione/costruzione e' diverso qui: la lettura dei metadati cade
**dentro** la costruzione, non prima. La riga `PERF###` lo riflette, e la fase `meta` lo rende
leggibile invece che nascosto.

### Accorgimenti

- **`single_seasons` chiama `build_season_list` in parallelo**, una volta per stagione. Azzerare le
  fasi li' cancellerebbe le misure di una lista che un altro thread sta ancora costruendo: su quella
  strada non si riporta nulla, quindi non si azzera nulla.
- Stessa ragione per cui `log_build` non viene emesso sulla strada `custom_order`: stamperebbe una
  riga per stagione invece di una per lista.

### Verifiche

`ast.parse` + `py_compile`; CRLF preservati (entrambi i file sono CRLF); **nessun simbolo perso**;
**conteggio fasi verificato programmaticamente**: 7 durate / 7 etichette per `build_episode_list`,
8 / 8 per `build_single_episode`, 6 / 6 per le stagioni -- una discordanza avrebbe prodotto un log
muto senza errori, che e' il modo peggiore di sbagliare una misura.

Un'insidia trovata durante il lavoro: i due blocchi di `episodes.py` sono quasi identici e
differiscono solo per l'indentazione (3 tab contro 4). Un pattern a 3 tab combacia **anche dentro**
la riga a 4 tab, quindi le sostituzioni vanno ancorate a inizio riga. L'assert di controllo lo ha
intercettato prima di scrivere.

### Da fare al prossimo giro sul dispositivo

Aprire una serie, entrare in una stagione, e guardare la home con «continua a guardare». Le tre righe
nuove diranno per la prima volta quanto costano davvero, e in particolare **quanto pesa `meta` sugli
episodi singoli**: e' il candidato numero uno per il prossimo intervento.

---

## Lotto 41 — Prima lettura della diagnostica nuova: tre scoperte

Log del 22/08, 12:15:22 - 12:17:20. **Zero eccezioni**, e le righe nuove hanno gia' pagato.

### 1. Ogni lista di stagioni ed episodi viene costruita DUE VOLTE

```
12:15:28.587  seasons Conversazioni con un killer   |  12:15:28.637  (+50 ms)
12:16:13.440  seasons Conversazioni con un killer   |  12:16:13.491  (+51 ms)
12:16:16.964  seasons Sterling Point                |  12:16:17.016  (+52 ms)
12:16:22.740  seasons Furious                       |  12:16:22.790  (+50 ms)
12:16:25.222  seasons Stuart Fails...               |  12:16:25.271  (+49 ms)
12:16:28.903  seasons Lucky                         |  12:16:28.953  (+50 ms)
```

**Sistematico, sempre a ~50 ms di distanza, su ogni apertura di serie.** Non e' un refresh: fra le
due non c'e' nulla. E' la duplicazione gia' sospettata in P2.5, ma finora invisibile perche' su
questi percorsi non si misurava niente. Ora e' riproducibile a comando: basta aprire una serie.

### 2. La `risoluzione` e' tutto il costo, la costruzione e' rumore

```
12:16:30.900  episodes Season 1 | 7 elementi
              totale 1.05s = risoluzione 1.05s + costruzione 1 ms (0.167 ms/elemento)
```

**Un secondo pieno di risoluzione contro 1 ms di costruzione**: la costruzione e' lo 0,1% del tempo.
La stessa lista, riaperta 25 s dopo, fa `totale 0.00s`. Quindi il costo e' la lettura dei metadati a
freddo, non i ListItem.

Conferma con un numero cio' che era un'ipotesi da diversi lotti: **ogni ulteriore ottimizzazione dei
setter sposta lo 0,1%.** Il lavoro vero e' nella risoluzione.

### 3. Chiuso l'ultimo punto cieco: `tvshows.py`

Restava senza fasi, e proprio li' c'era il numero inspiegato: `mdblist 2194` (41 serie) costa
**268-291 ms** di costruzione contro i 13-47 ms di `mdblist 91378` (47 film). Stesso dispositivo,
stessi worker, ordine di grandezza di differenza -- e nessun modo di vedere dove finissero.

Ora `tvshows.py` ha le sette fasi (`meta`, `prep+cm`, `setLabel`, `ctxmenu`, `setArt`, `infotag`,
`cast+props`) e una riga `PERF###` anche quando la lista non passa da mdblist/trakt.

**Tutti e quattro gli indexer sono ora strumentati.** Non restano percorsi ciechi.

---

## Lotto 42 — Il fuoco perso a fine episodio

**Sintomo.** Chiusa la riproduzione di un episodio, la lista si rigenera da capo e il fuoco torna sul
primo elemento invece di restare sull'episodio appena visto.

**Dal log.**

```
12:16:55.181  CloseFile
12:16:55.723  episodes Season 1 | 7 elementi      <- Kodi rilegge la cartella uscendo dal player
12:16:58.099  refresh mirato: nessun contenitore identificato, si ricostruisce tutto
12:16:58.116  VideoInfoScanner: Starting scan
12:16:59.793  episodes Season 1 | 7 elementi      <- la nostra ricostruzione
```

Due riletture. La prima e' di Kodi e arriva **prima** che `run_media_progress` abbia scritto
l'avanzamento (che aspetta 2 s), quindi non mostrerebbe il nuovo stato: la nostra serve davvero.

**Il difetto e' come la facciamo.** Dentro una finestra di directory il refresh mirato non trova
contenitori (giustamente, lotto 39 bis) e ricade su `UpdateLibrary`, che e' globale. Due conseguenze,
entrambe sbagliate proprio li':

1. invalida i widget della home, che **non sono a schermo** e che Kodi rilegge comunque quando ci si
   torna -- un DirectoryProvider non ha il concetto di «ancora valido». Lavoro buttato;
2. fa rileggere la cartella aperta **come una navigazione nuova**, e la posizione si perde.

**Cura.** `kodi_refresh()` distingue la finestra: dentro la 10025 usa `Container.Refresh`, che
rilegge solo la cartella aperta e ne conserva la selezione. Fuori, `UpdateLibrary` come prima.

Lo scope timbrato non e' `'*'` ma `'@contenitore'`: una ricarica di cartella non copre i widget della
home, e spacciarla per globale farebbe accorpare a vuoto la richiesta successiva -- l'errore del
lotto 39, che non va reintrodotto da un'altra porta.

---

## Lotto 42 bis — La serie che non ha caricato: quello che si sa e quello che no

**Sintomo riportato.** Dopo aver segnato episodi in una serie, entrando in quella accanto non
caricavano logo e stagioni. Uscendo e rientrando, tutto a posto.

**Cosa il log esclude:** nessuna eccezione, nessun `BUILD FALLITA`, nessuna directory vuota. Anche un
controllo statico apposta -- ogni marcatore di misura assegnato prima dell'uso, in tutti e quattro
gli indexer -- non trova niente: un `NameError` dentro un indexer sarebbe stato catturato da `except:`
e avrebbe prodotto proprio quel sintomo, quindi andava escluso per primo.

**L'unica anomalia oggettiva.** «Sterling Point» alle 12:16:10.583 e' stata costruita **una volta
sola**; ogni altra apertura di serie della sessione risulta costruita due volte. E quel momento
coincide con la ricostruzione dell'intera home (12:16:10.5 - 12:16:10.9, quattro widget) partita dal
refresh precedente.

**Ipotesi, non conclusione:** la navigazione dentro la serie e' avvenuta mentre la home si stava
ricostruendo, e la seconda passata -- quella che normalmente popola logo e stagioni -- non e'
arrivata. Se e' cosi', **e' la duplicazione del punto 1 a essere il vero problema**: una seconda
costruzione che finisce il lavoro della prima non e' ridondanza, e' una dipendenza nascosta.

**Come confermarlo:** riprodurre marcando episodi e navigando subito alla serie accanto, e guardare
se la riga `seasons <titolo>` compare una volta o due. E' il primo esperimento da fare al prossimo
giro.

---

## Lotto 43 — Il ritardo dopo una riproduzione: tre cause, una sola mia

Log del 22/08, 12:26:48 - 12:28:43. La diagnostica nuova permette per la prima volta di **separare**
le cause invece di attribuirle tutte al refresh.

### Il meccanismo di refresh NON e' lento

```
12:27:15.072  refresh   ->  12:27:15.303  lista ricostruita   (231 ms)
12:27:22.417  refresh   ->  12:27:22.653  lista ricostruita   (236 ms)
```

Dalla richiesta al ridisegno passano **230 ms**. Il tempo che l'utente percepisce sta tutto PRIMA di
quella riga di log.

### Causa 1 — Due secondi di attesa messi apposta (preesistente)

```
12:27:42.152  CloseFile  ->  12:27:45.035  refresh   =  2,88 s
12:28:19.233  CloseFile  ->  12:28:21.784  refresh   =  2,55 s
```

Di questi, **2,0 s sono `ku.sleep(2000)` in `run_media_progress`**, fra la scrittura dei dati e la
richiesta di ricostruzione. La scrittura (`function(params)`) e' gia' finita quando il sonno comincia:
serve solo a non accavallarsi con la rilettura che Kodi fa da solo uscendo dal player.

**Quella rilettura ora e' misurata:** arriva a **+390 ms** (12:27:42.542) e **+653 ms**
(12:28:19.886) dal CloseFile. Il sonno e' quindi circa **quattro volte** l'attesa realmente
necessaria su Mac. Sul Mi Stick sara' di piu', ma 2000 ms resta un numero scelto a occhio, mai
verificato -- e ora c'e' il modo di verificarlo.

Non e' una regressione: c'era anche prima. E' semplicemente la voce piu' grossa del conto.

### Causa 2 — La rete prima della scrittura locale (preesistente)

`mark_episode` esegue in quest'ordine:

1. `trakt_watched_status_mark(...)` -- **POST di rete a Trakt**
2. `clear_trakt_collection_watchlist_data(...)`
3. `watched_status_mark(...)` -- scrittura nel DB locale
4. `refresh_container_for(...)` -- aggiornamento visibile

L'interfaccia non puo' muoversi finche' la rete non ha risposto. **E' lo stesso identico difetto gia'
corretto in `erase_bookmark`** (scrittura locale -> refresh -> push a Trakt in un thread di sfondo),
che era proprio l'intervento che aveva reso «azzera avanzamento» istantaneo.

Applicarlo qui comporta un compromesso vero: scrivendo prima in locale, un fallimento di Trakt
lascerebbe lo stato locale in anticipo su quello remoto. In `erase_bookmark` il compromesso fu
accettato. **Va deciso, non deciso di nascosto.**

### Causa 3 — La mia regressione del lotto 42: RITIRATA

`Container.Refresh` ricarica **solo la cartella aperta**. Le cartelle padre in cronologia restano
quelle in cache -- in finestra Video `end_directory` usa `cacheToDisc=True` -- quindi il badge
«episodi rimanenti» sulla serie non si aggiornava finche' non la si riapriva. Con `UpdateLibrary`
succedeva perche' invalidava tutto.

Ritirato: si torna a `UpdateLibrary`. Un badge sbagliato e' correttezza, il fuoco perso e' comodita'.

**Ancora la stessa forma di errore, la quinta volta:** una regola giusta per un caso (il fuoco nella
cartella aperta) applicata a un caso che sembrava uguale (tutto cio' che va aggiornato). Il criterio
mancante era: *cosa deve cambiare sta dentro o fuori la cartella aperta?*

**Il fuoco resta un problema aperto**, da risolvere conservando la posizione, non rinunciando
all'aggiornamento.

### Le due decisioni da prendere

1. **Abbassare `sleep(2000)`.** Ora c'e' una misura contro cui tararlo (390-653 ms su Mac). Da
   verificare sul Mi Stick prima di scegliere il numero: e' esattamente il tipo di costante che
   questo registro ha gia' sbagliato deducendo invece di misurare.
2. **Spostare la chiamata Trakt in sfondo** in `mark_episode` / `mark_movie` / `mark_season` /
   `mark_tvshow`, come in `erase_bookmark`. Rende la marcatura istantanea; in cambio, un errore di
   rete si scopre dopo che l'interfaccia si e' gia' aggiornata.

---

## Lotto 44 — La rete esce dal percorso interattivo (decisione dell'utente)

Applicato alle quattro marcature lo schema gia' usato per `erase_bookmark`: **prima il locale e
l'interfaccia, poi Trakt in un thread di sfondo.**

| funzione | prima | ora |
|---|---|---|
| `mark_movie` | POST Trakt -> DB -> refresh | DB -> refresh -> thread Trakt |
| `mark_episode` | POST Trakt (+ mappa episodio) -> DB -> refresh | DB -> refresh -> thread Trakt |
| `mark_tvshow` | POST Trakt -> lotto locale (lungo) -> refresh | thread Trakt **in parallelo** al lotto locale |
| `mark_season` | POST Trakt -> lotto locale -> refresh | thread Trakt **in parallelo** al lotto locale |

Per serie e stagioni il thread parte nello stesso punto in cui c'era la chiamata bloccante: cosi' la
rete si sovrappone all'inserimento locale, che li' e' lungo (un record per episodio, con dialogo di
avanzamento), invece di precederlo.

**`_mark_on_trakt` porta dentro anche `_map_to_tmdb_episode`**, la conversione episodio tvdb->tmdb: a
cache fredda e' un'altra chiamata di rete (skyhook). Lasciarla fuori avrebbe tenuto meta' del ritardo
sul percorso caldo.

**Il compromesso, esplicito.** Se Trakt fallisce, l'avviso di errore arriva DOPO che l'interfaccia si
e' gia' aggiornata, e lo stato locale resta in anticipo su quello remoto fino alla prima
sincronizzazione utile. Prima il fallimento annullava anche la scrittura locale. Scelta dell'utente,
coerente con quella gia' presa per `erase_bookmark`.

**Effetto collaterale utile:** `trakt_watched_status_mark` ha ora **un solo chiamante**, il thread di
sfondo. Non restano percorsi che aspettano Trakt prima di ridisegnare.

**Nota su un ramo morto trovato per strada** (non toccato): in `mark_movie` e `mark_episode` c'era
`if from_playback == 'true'`, ma `from_playback` era gia' stato convertito in booleano poche righe
sopra. Il confronto era sempre falso, quindi quel ramo non si e' mai eseguito. Sparisce con la
riscrittura, ma vale la pena saperlo: era li' da prima.

---

## Lotto 44 bis — La misura per tarare `sleep(2000)`

Non si tocca il numero finche' non c'e' il dato del Mi Stick. Strumento aggiunto:

- `player.media_watched_marker` timbra `fenlight.perf.closefile` all'uscita dal player;
- `paginator.log_build` aggiunge ` | +N ms da CloseFile` a ogni riga `PERF###` entro 30 s da quel
  timbro.

**La prima riga che riporta quel valore dopo una chiusura e' la rilettura che Kodi fa per conto suo**
-- cioe' esattamente l'attesa che il sonno deve coprire. Su Mac vale 390-653 ms; se sulla stick
restasse sotto il secondo, 2000 ms sarebbe il doppio del necessario e si potrebbe dimezzare il
ritardo percepito a fine riproduzione.

E' il metodo che questo registro ha imparato a forza di sbagliare: `cacheToDisc`, l'accorpamento a
tempo, `Container.Refresh`. **Prima la misura, poi la costante.**

### Da verificare sul dispositivo

1. **Segna come visto / non visto** su un episodio: deve essere immediato, non piu' in attesa della
   rete. Il badge «episodi rimanenti» sulla serie deve aggiornarsi.
2. Stesso test su un **film**, su una **stagione** e su una **serie intera**.
3. Con Trakt attivo, controllare che lo stato **arrivi comunque** su Trakt (l'app del telefono).
4. Chiudere una riproduzione e leggere nel log la prima riga con `+N ms da CloseFile`: e' il numero
   che serve per decidere il nuovo valore del sonno.

---

## Lotto 45 — Il Mi Stick ribalta la diagnosi: non e' il sonno, e' Trakt

Log della stick del 22/08, 12:49:12 - 12:57:52. La misura `+N ms da CloseFile` aggiunta nel lotto 44
bis ha risposto subito, e la risposta non e' quella che ci aspettavamo.

### Il numero

| | Mac | **Mi Stick** |
|---|---|---|
| da `CloseFile` alla lista aggiornata | ~2,5 s | **10,6 - 12,0 s** |

```
12:54:14.521  seasons Conversazioni...  | +11511 ms da CloseFile
12:54:14.977  episodes Season 1         | +11968 ms da CloseFile
12:56:10.217  episodes Season 1         | +10656 ms da CloseFile
12:56:11.158  seasons Sterling Point    | +11582 ms da CloseFile
```

### Dove vanno quei secondi

```
12:54:02.742  CloseFile
12:54:05.103  refresh nostro                      <- +2,1 s: e' il sleep(2000), fa il suo dovere
12:54:05.221  scan finito                         <- 41 ms
12:54:09.886  Trakt: sync/watched/shows
12:54:11.766  Trakt: watched episodes rebuild: 35 shows, 1286 plays su 6 pagine, 1274 episodi
12:54:14.521  la lista finalmente si ricostruisce  <- +9,4 s DOPO il nostro refresh
```

**Il sonno non e' il problema.** Abbassarlo a 1000 ms recupererebbe 1 secondo su 11,5. La decisione
presa al lotto 44 bis ("prima misuro, poi scelgo il numero") ha evitato di spendere lavoro sulla voce
sbagliata: e' esattamente il caso per cui la misura serviva.

### La causa: ogni marcatura scatena un rebuild completo della cronologia Trakt

`trakt_watched_episodes` ha due strade: una **incrementale** (`watched episodes sync: N new plays
added, no rebuild needed`) e un **rebuild completo** che scarica 6 pagine di cronologia e ricostruisce
1274 episodi.

**In tutta la sessione l'incrementale e' scattata UNA volta** (12:49:40, all'avvio). Tutte le altre
volte -- 12:53:03, 12:54:11, 12:57:44 -- rebuild completo. Sulla stick costa 2-6 s di rete e CPU, e
compete con la ricostruzione dell'interfaccia.

Ironia: l'aver spostato Trakt in sfondo (lotto 44) ha tolto l'attesa dal percorso interattivo, ma il
lavoro che quella chiamata scatena nel monitor e' rimasto tutto li'.

**Non si indovina perche'.** Le tre ipotesi plausibili -- nessun play piu' recente (rimozioni), prima
pagina tutta nuova, cronologia locale assente -- portano a correzioni diverse. Verificata e scartata
una quarta (formati di data diversi fra Trakt e cache locale: `_make_row` salva `watched_at`
verbatim, quindi il confronto e' omogeneo). Aggiunta una riga di log che stampa il motivo, l'ultimo
timestamp locale e il numero di pagine.

### Il problema del fuoco e' un SINTOMO, non un difetto a se'

```
12:54:02.742  CloseFile
12:54:03.828  Control 521 in window 10025 has been asked to focus, but it can't
12:54:14.521  la lista arriva
```

La skin chiede il fuoco **1,1 s dopo** la chiusura, quando il contenitore e' ancora vuoto: fallisce.
Quando la lista arriva, dieci secondi dopo, la posizione e' persa e il fuoco finisce sul primo
elemento. Stessa sequenza a 12:56:00.487 e 12:56:54.198.

**Quindi non serve un meccanismo per conservare il fuoco: serve che la lista arrivi in tempo.**
Chiudere la latenza chiude anche questo. Vale anche per "uscendo dalla serie il fuoco non e' sempre
sulla serie": stesso contenitore, stessa corsa persa.

### Due conferme collaterali

**La contesa amplifica tutto.** Alle 12:54:14.977, con il rebuild Trakt in corso:

```
episodes Season 1 | 3 elementi | costruzione 355 ms
FASI: setLabel 257ms (72%) + ctxmenu 77ms (22%)
```

**257 ms di `setLabel` per 3 elementi**, cioe' 85 ms per chiamata, contro gli 0-1 ms delle stesse
liste a macchina scarica. Non e' il codice: e' il dispositivo occupato. Conferma con un esempio netto
la varianza da concorrenza gia' registrata.

**Il cricchetto non e' morto.** Widget da **250, 298 e 375 elementi**, e per uno di essi
`RETE tvshows: 239 voci non in cache risolte in rete | 34097 ms (143 ms/voce)`: **34 secondi di rete
per un solo widget.**

### Ordine di lavoro rivisto

1. **Il rebuild completo di Trakt a ogni marcatura** -- 2-6 s per volta sulla stick, e blocca l'interfaccia.
2. **I widget da 250-375 elementi** e i 34 s di risoluzione in rete.
3. Il `sleep(2000)`: recupera 1 s su 11,5. Ultimo.

### Da fare al prossimo test

Marcare un episodio come visto e uno come non visto, poi mandare il log. La riga nuova
`rebuild completo, motivo: ...` dira' quale delle tre strade porta li', e da quella dipende la cura.

---

## Lotto 46 — Il rebuild Trakt se lo innescava la nostra stessa scrittura

La riga diagnostica del lotto 45 ha risposto al primo colpo. Log della stick del 22/08:

```
13:13:26.534  rebuild completo, motivo: nessun play piu' recente del piu' recente locale (rimozioni?)
              | ultimo locale=2026-08-22T11:12:54.000Z | pagine=6
```

`11:12:54Z` con l'Italia a UTC+2 e' **13:12:54 locali**, cioe' **due secondi dopo il CloseFile** delle
13:12:52.758. Quel "piu' recente locale" non veniva da Trakt: era **la marcatura che avevamo appena
scritto noi**.

### Il cerchio, dimostrato nel codice

```python
# watched_status.py:17
indicators_dict = {0: 'watched_db', 1: 'trakt_db'}
```

Con gli indicatori Trakt, `watched_status_mark` scrive nel **trakt_db** -- lo stesso database che
`last_watched_episode_date()` interroga per sapere "fin dove sono sincronizzato".

Quindi, a ogni marcatura:

1. scriviamo la riga locale in `trakt_db`, con `last_played` = adesso;
2. il monitor legge `last_synced` e trova **la nostra stessa riga**;
3. nessun play remoto risulta piu' recente -> `new_plays` vuota;
4. la condizione `if new_plays and len(new_plays) < len(history)` fallisce -> **rebuild completo**:
   6 pagine di cronologia, 1287 play, 1275 episodi, ~4 secondi sulla stick.

**Ogni marcatura si autoinnescava il lavoro piu' pesante dell'addon.** La via incrementale non poteva
mai scattare per le modifiche fatte da questo dispositivo: solo per quelle di un altro.

### La cura

Un timbro: chi spinge su Trakt (`_mark_on_trakt`) segna `fenlight.trakt.self_mark`. Il monitor, se
`new_plays` e' vuota **e** il timbro e' recente (< 120 s), salta il rebuild -- non c'e' niente da
ricostruire, la riga locale e' gia' scritta.

Vale anche per le **rimozioni**, perche' anche quelle le applica gia' il percorso locale. Le modifiche
fatte da un **altro dispositivo** portano play piu' recenti del nostro ultimo, quindi continuano a
passare dalla via incrementale. Se il timbro scade, si ricostruisce come prima: la rete di sicurezza
resta.

### Il fuoco: stessa catena, numeri di questa sessione

```
13:12:52.758  CloseFile
13:12:54.140  Control 521 in window 10025 has been asked to focus, but it can't
13:13:01.817  episodes Season 1 ... | +8183 ms da CloseFile
```

La skin chiede il fuoco **7 secondi prima che la lista esista**. Fallisce, e il fuoco resta
sull'elemento padre -- la scritta «Stagione N». E' esattamente quello che l'utente descrive.

Distanze misurate in questa sessione: **+8183, +9288, +9471, +10466 ms**. Leggermente meglio della
precedente (10,6-12,0 s), stesso ordine di grandezza.

### Confermato funzionante

`13:13:41.534  kodi_refresh accorpato: ricostruzione globale 0.02s fa` -- l'accorpamento ha preso un
doppione arrivato a 20 ms di distanza.

### Da verificare sul dispositivo

1. Marca un episodio come **visto**: nel log deve comparire
   `rebuild saltato: la modifica e' nostra ed e' gia' applicata in locale`, **non**
   `watched episodes rebuild`.
2. Stesso test con **non visto** (rimozione).
3. Rileggere `+N ms da CloseFile`: e' il numero che dice se il tappo era davvero quello.
4. Controllare dall'app Trakt che lo stato arrivi comunque.
5. Cambiare qualcosa **dal telefono** e verificare che il badge compaia: e' la via incrementale, che
   non deve essere stata toccata.

---

## Lotto 46 bis — Verifica sulla stick: il rebuild Trakt e' chiuso, ne restano due

Log stick del 22/08 23:12-23:17. La correzione del lotto 46 **funziona**, due volte:

```
23:14:08.385  rebuild saltato: la modifica e' nostra ed e' gia' applicata in locale
23:16:47.427  rebuild saltato: la modifica e' nostra ed e' gia' applicata in locale
```

Zero `watched episodes rebuild` in tutta la sessione. Confermato anche l'accorpamento col monitor
(`refresh saltato, interfaccia ricostruita 0.0s / 17.8s / 18.6s / 29.0s fa`, quattro volte).

E le liste di navigazione sono ormai gratis: `seasons Furious | 1 elemento | totale 0.03s / 0.04s /
0.10s`, `episodes Season 1 | 8 elementi | totale 0.03s / 0.05s`. **Entrare in una serie non e' piu'
il problema.** Il problema e' tutto nella tempesta di widget.

Ma la latenza e' **peggiorata**: `+17422, +18160, +27545, +29068, +29270 ms da CloseFile` contro i
`+8183` della sessione precedente. Il log dice perche', e sono tre cose distinte.

---

## Lotto 47 — Cinque cause, tre delle quali nostre

### 47.1 — La guardia sulla finestra 10025 trasformava il mirato in globale (regressione mia)

```
23:16:29.889  refresh mirato: nessun contenitore identificato, si ricostruisce tutto
23:16:30.041  VideoInfoScanner: Starting scan ..
```

L'utente era **dentro la lista episodi** (MyVideoNav caricata alle 23:16:11). La guardia del lotto
39 bis -- giusta in se': nella finestra Video i controlli 500-528 sono le viste, non i widget --
restituiva `0`, e il chiamante interpretava lo zero come «non ho trovato niente» e ripiegava su
`UpdateLibrary`, cioe' **la ricostruzione di ogni widget video della skin, invisibili compresi**.

Fuori da quella finestra il mirato funzionava (`refresh mirato: 1 contenitori`, `2 contenitori`).
Dentro, cioe' **proprio nel caso in cui l'utente guarda la lista che deve cambiare**, si faceva la
cosa piu' costosa possibile. E' questa la causa principale del peggioramento da +8 a +29 secondi.

**Corretto**: in finestra 10025 si esegue `Container.Refresh` sulla cartella aperta e **non** si
ripiega sul globale. `Container.Refresh` ricarica solo la lista visibile e ne conserva la posizione,
quindi rimedia anche al fuoco perso.

Resta il difetto che nel lotto 43 aveva fatto ritirare `Container.Refresh`: le cartelle padre
(stagioni, serie) erano servite dalla cache su disco e mostravano un badge vecchio. Ora e' risolto
alla radice: `cacheToDisc=False` per seasons ed episodes anche in finestra Video. Il prezzo e' una
rilettura del plugin al ritorno, e ora sappiamo quanto costa perche' e' **misurata**: 30-100 ms.
Era un baratto sensato quando quelle liste erano lente; oggi la cache si paga solo in correttezza.

### 47.2 — Ogni widget veniva costruito due volte dopo la riproduzione

```
23:15:23.246  mdblist 101881 | 54 elementi | +17422 ms da CloseFile
23:15:23.983  mdblist  91378 | 48 elementi | +18160 ms da CloseFile
23:15:33.368  mdblist  91378 | 48 elementi | +27545 ms da CloseFile   <- la stessa
23:15:35.095  mdblist 101881 | 54 elementi | +29270 ms da CloseFile   <- la stessa
```

Stessi id, stesso numero di elementi, a ~10 secondi di distanza. Spiegazione coerente con il
`CDirectoryProvider`: alla chiusura del player la finestra sotto torna in primo piano e **Kodi
rilegge i widget da sola**; poi arriva anche il nostro refresh esplicito.

**Corretto**: il refresh post-riproduzione ha ora **un padrone solo** (`run_media_progress`, che
azzera subito `PENDING_REFRESH_PROP` cosi' ne' `flush_pending_refresh` ne' la rete di sicurezza di
`WidgetRefresher` possono partire in parallelo) e **cede il passo**: `kodi_rebuilt_by_itself()`
attende fino a 20 s che compaia una ricostruzione spontanea e, se compare, non ordina la propria. La
riga di visto e' scritta in locale *prima* di tutto questo, quindi la rilettura di Kodi legge gia' il
dato giusto.

Attendere non costa una tempesta: e' un thread fermo in un interprete gia' vivo, contro tre-cinque
ricostruzioni da 2,5-4 s l'una.

### 47.3 — La sincronizzazione dei film non aveva alcuna via incrementale

```
23:16:13.871  sync/watched/movies: 599 elementi su 6 pagine
23:16:14.197  watched movies: 599 da Trakt, 599 in cache, 0 scartati
```

**599 su 599 gia' in cache, 0 scartati**: sei pagine scaricate per non cambiare una riga, e per
giunta mentre la stessa CPU costruiva la lista stagioni. Gli episodi erano stati corretti nel lotto
46; i film erano rimasti l'unico percorso che si autoinnescava il rebuild integrale.

**Corretto** con la stessa guardia. E si e' chiuso un buco che il lotto 46 aveva lasciato anche sul
lato episodi: il timbro `fenlight.trakt.self_mark` ora porta **anche il tipo**. Con il solo istante,
marcare un episodio zittiva per due minuti anche il controllo sui film, e una modifica ai film
arrivata da un altro dispositivo in quella finestra sarebbe stata **persa per sempre** -- perche'
`reset_activity` aveva gia' registrato la nuova attivita' come vista.

### 47.4 — La contesa, misurata al suo peggio: il codice per elemento non e' lento

| misura | a riposo | durante la tempesta | fattore |
|---|---|---|---|
| `addContextMenuItems(7 voci)` | 0,13 ms | **9,49 ms** | 73x |
| `setProperty` (per chiave) | 0,016 ms | **1,422 ms** | 89x |
| `prep+cm` (per elemento) | ~2 ms | **216 ms** (1296 ms per 6 elementi) | ~100x |

**La macchina e' satura, non il codice.** Ottimizzare ancora i setter non sposta niente: l'unica leva
e' fare *meno costruzioni*. Questo chiude definitivamente quel filone.

Conseguenza operativa: `PERF_SELFTEST` **spento**. Girava a ogni costruzione e costava ~100 ms,
pagati anche in piena tempesta, cioe' proprio quando la macchina non ne aveva. Le risposte che doveva
dare le ha date.

### 47.5 — Lo `sleep(2000)` era sbagliato due volte

`refresh mirato` -> `CPythonInvoker waiting on thread` misura 2,002s / 2,017s / 2,065s tre volte nel
log: lo sleep era esatto. Ma serviva a tenere alzato il segnale «ricostruzione in corso» che i widget
leggono per conservare le pagine espanse, e:

- teneva vivo **un interprete Python per due secondi a non fare nulla**, su un dispositivo dove
  avviarne uno e' gia' caro e i processi contendono;
- era comunque **troppo corto**: fra l'ordine di ricarica (23:15:09.240) e la prima costruzione
  (23:15:20.219) passano **11 secondi**, quindi la build leggeva il segnale gia' spento.

**Corretto**: si scrive una scadenza (`REFRESH_FLAG_SECONDS = 20`) e si esce subito. A spegnere il
segnale pensa `WidgetRefresher`, che gira gia' ogni 10 s. L'interprete si libera **e** la finestra
utile si allunga invece di accorciarsi.

### 47.6 — Il cricchetto delle pagine ha finalmente un tetto

48 -> 62 (3 pagine) -> 87 elementi (4 pagine) nel giro di un minuto, e la ricostruzione da 87 arriva
a **4,35s**. Ogni paginazione allargava per sempre cio' che ogni ricostruzione successiva doveva
ricostruire, e non tornava mai indietro.

`fenlight.paginate.max_pages`, default **8**. Raggiunto il tetto il widget smette di *allungarsi*:
nessuna lista si accorcia mai e la posizione non salta. Il tetto agisce su `has_more` in `set_state`,
non su `raw_pages` -- applicarlo li' avrebbe accorciato una lista gia' mostrata a ogni ricostruzione,
esattamente cio' che il paginatore esiste per evitare.

### 47.7 — La tempesta arriva anche all'APERTURA del player (non corretto, diagnosticato)

```
23:14:26.175  VideoPlayer::OpenFile
23:14:37.752  mdblist 91378 | 48 elementi | totale 3.10s
23:14:43.886  mdblist  2194 | 42 elementi | totale 0.94s
```

Nessun `+N ms da CloseFile`, nessun `refresh mirato` prima: **non e' roba nostra**. Diciassette
secondi di CPU spesi a ricostruire widget invisibili mentre il decoder video parte, su una Mali-450
con 1 GB. Poco dopo: `ReleaseOutputBuffer error in render(false)`, `CVideoPlayerAudio: stream stalled`.

Il sospetto e' il cambio di frequenza di aggiornamento: `SetNativeResolution: 8: ...@23.976025` alle
23:14:28.886, `GLES: Maximum texture width` alle 23:14:30.644 -- il contesto GL viene ricreato e la
finestra sotto torna attiva. **Non si puo' correggere dal plugin**: e' Kodi che ci chiama e noi
dobbiamo rispondere. La diagnostica ora lo marca (`DURANTE RIPRODUZIONE`) e la prova decisiva e'
provare con l'adattamento della frequenza disattivato.

---

## Lotto 47 bis — La diagnostica: adesso il log dice PERCHE', non solo CHE COSA

Il difetto di fondo delle ultime sessioni: il log diceva che una lista era stata ricostruita, mai
chi l'avesse chiesta. Con due ondate dopo ogni riproduzione, ogni ipotesi restava indimostrabile.

**`FenLight PERF AVVIO`** (nuovo, in `fenlight.py`, prima degli import) — gli 11 secondi ciechi:

```
avvio interprete ~N ms + import N ms + esecuzione N ms = N ms | <query>
```

`avvio` e' la CPU gia' bruciata prima della prima riga: il costo dell'interprete che parte, l'unica
parte non strumentabile dall'interno. Con `reuselanguageinvoker=false` ogni invocazione reimporta
tutto l'albero, quindi l'import e' il sospetto principale -- ma finora era **solo** un sospetto.

**`causa=`** su ogni riga `PERF` di costruzione:

| valore | significato |
|---|---|
| `ricarica-mirata` | il nonce e' nel path: l'abbiamo ordinata noi |
| `paginazione` | l'utente ha scorso |
| `apertura/re-show` | Kodi rilegge da sola il DirectoryProvider |

**`DOPPIONE: stessa lista gia' costruita N ms fa (causa X)`** — riconosce le ricostruzioni ripetute
entro 45 s. Registro unico con tetto di 12 voci (~330 caratteri), non una proprieta' per chiave:
le chiavi cambiano a ogni ricerca e avrebbero lasciato rifiuti nelle sessioni lunghe.

**`DURANTE RIPRODUZIONE`** — costruzione mentre il video va, cioe' CPU rubata alla decodifica.

**`DIAG refresh:`** — la catena decisionale completa, una riga per decisione:
`MIRATO N contenitori` / `MIRATO finestra Video (Container.Refresh)` / `GLOBALE (UpdateLibrary)` /
`nessun contenitore identificato, si ricade sul GLOBALE` / `RIMANDATO, riproduzione in corso` /
`NON ordinato, Kodi ha gia' ricostruito da sola N s dopo la chiusura`.

**`DIAG paginazione: tetto di N pagine raggiunto`**.

Tutto a livello `info`: nessun bisogno del log di debug.

### Come leggere il prossimo log, in ordine

1. `grep "DIAG refresh"` — dev'essere **`MIRATO`**. Ogni `GLOBALE` che non arrivi dal monitor Trakt
   e' un caso da capire.
2. `grep "DOPPIONE"` — **deve sparire**. Se resta, la seconda ondata non era la nostra e
   `kodi_rebuilt_by_itself` sta guardando il segnale sbagliato.
3. `grep "PERF AVVIO"` — se `import` domina, il prossimo lotto e' l'albero degli import; se domina
   `avvio interprete`, non c'e' niente da fare in Python.
4. `grep "da CloseFile"` — il numero che dice se abbiamo vinto. Da +29 secondi a quanto?
5. `grep "rebuild saltato"` — deve comparire sia per `watched movies` sia per `watched episodes`.
6. `grep "DURANTE RIPRODUZIONE"` — quante costruzioni rubano CPU al decoder.

### Da verificare sul dispositivo

1. **Segna un episodio come visto stando dentro la serie**: nel log
   `DIAG refresh: MIRATO finestra Video (Container.Refresh sulla lista aperta)`, e **nessuno**
   `VideoInfoScanner: Starting scan`. Il badge deve cambiare **e il fuoco restare dov'era**.
2. **Torna indietro alle stagioni**: il badge «episodi rimanenti» dev'essere aggiornato (e' il
   difetto del lotto 43, che ora dipende da `cacheToDisc=False`). Se tornare indietro e' diventato
   *lento*, il baratto non regge e va rivisto: e' l'unica assunzione non ancora misurata.
3. **Chiudi una riproduzione**: cercare `DOPPIONE`. Zero occorrenze = il doppione e' chiuso.
   Confrontare `+N ms da CloseFile` con i +17/+29 s di partenza.
4. **Segna un film come visto**: `watched movies: rebuild saltato`, non `599 elementi su 6 pagine`.
5. **Modifica qualcosa dal telefono** (un film *e* un episodio): il badge deve comparire lo stesso.
   E' la via incrementale, che non dev'essere stata toccata.
6. **Pagina un widget a fondo**: dopo 8 pagine dev'esserci
   `DIAG paginazione: tetto di 8 pagine raggiunto`.

### Nota: l'avviso «e' necessario installare un addon: Fen Light»

Non e' un difetto del codice. Nel log e' visibile la causa esatta:

```
23:12:43.126  service.py: waiting on thread          <- i servizi si fermano
23:12:47.943  FindAddon: plugin.video.fenlight v3.0.15 installed
23:12:48.381  error: Unable to find plugin plugin.video.fenlight
23:12:50.146  FindAddon: repository.bowserr v1.1.16 installed
```

Kodi stava **aggiornando l'addon** da `repository.bowserr` (3.0.14 -> 3.0.15). Mentre sostituisce
l'addon lo deregistra e lo riregistra; ogni richiesta `plugin://` che cade in quella finestra non si
risolve, e Kodi propone di installarlo. Succede «generalmente all'apertura» perche' il controllo
aggiornamenti parte poco dopo l'avvio, cioe' **in mezzo alla raffica di widget della home** -- e
perche' su questo repo la versione viene incrementata a ogni sviluppo.

Rimedio: Impostazioni -> Sistema -> Add-on -> Aggiornamenti = **«Notifica»** invece di «Installa
automaticamente». Non e' dannoso: a aggiornamento finito tutto riprende.

---

# Lotto 48 — adb sulla stick, il bisect che ha smentito se stesso, e tre correzioni

Sessione del 23/08 pomeriggio-sera. Prima volta con controllo diretto della Mi Stick via `adb` (rete,
gia' configurato), invece del ciclo commit -> deploy -> test manuale. Il resoconto e' lungo perche'
contiene un errore di metodo mio, non solo risultati.

## L'errore di metodo, per primo

Le prime due misure hanno usato `adb` con un campionatore che interrogava il dispositivo una volta al
secondo (`adb shell` in loop) mentre Kodi avviava. La stick si e' riavviata due volte durante quelle
misure, e per un momento ho scambiato il mio stesso carico per la causa. **Non lo era**, ma il sospetto
era legittimo e andava escluso, non ipotizzato. La prova: `am start` seguito da `adb kill-server`
(zero traffico per 200s) ha lasciato Kodi in piedi senza incidenti. Da quel momento ogni misura ha
seguito un protocollo fisso: orchestrazione intera scritta su file **sul device** (script push+`nohup`),
`adb kill-server` subito dopo il lancio, nessun comando fino al prelievo a fine corsa. E' il protocollo
da tenere per ogni test futuro via adb.

## La scoperta che conta: non e' un commit, e' una finestra di tempo

Cinque crash misurati in questa sessione, cinque versioni di codice diverse (HEAD, `a1edbba`,
`2599160`, `c887628` due volte), piu' i due nei log gia' raccolti (allegato 15:30, lotto 29 21:33):

| origine | scarto dall'avvio di Kodi |
|---|---|
| log utente 15:30 | +16,4 s |
| lotto 29 (storico) | +16,1 s |
| HEAD (sessione odierna) | ~16 s |
| `a1edbba` | 16,6 s |
| `2599160` | 18,2 s |
| `c887628` (2a corsa) | 23,3 s |

**Sempre e solo li'**, mai a meta' sessione, mai durante la navigazione normale -- tranne un caso
diverso discusso sotto. E' la finestra in cui 4 widget della home, `BlurService` (+ import Pillow),
`TraktMonitor`, `WidgetPaginator`, `CustomFonts` e i processi Python di `script.skinvariables` (skin
esterna, non nostra: vedi sotto) partono tutti insieme. Il tipo di riavvio e' sempre
`ro.boot.reboot_mode=watchdog_reboot` -- un blocco a livello di sistema, non un crash applicativo, non
un OOM kill (i kill di `lowmemorykiller` visti nei log sono tutti `adj=906`, cache normale, mai Kodi).

## Il bisect ha smentito se stesso

Ipotesi iniziale: la diagnostica aggiunta in `a1edbba` (`external()` dentro `end_directory`, prima
messo PRIMA di `endOfDirectory` -- vero rischio di abbraccio mortale, poi spostato dopo in `3c0d3d4`
-- e `_diag_note()` in `paginator.py`, lettura-modifica-scrittura di una proprieta' CONDIVISA a ogni
build) avesse abbassato il margine. La sequenza dei test:

1. `c887628` (prima corsa): **regge**, MemAvailable sceso fino a 149 MB.
2. `a1edbba`: **crasha**.
3. `2599160` (un solo commit prima di `a1edbba`, diff limitato al fix Trakt, niente sul percorso di
   avvio): **crasha comunque** -- diff insufficiente a spiegarlo.
4. `c887628` (seconda corsa, stesso identico codice della prova 1, verificato bit a bit): **crasha**.

Il punto 4 chiude la questione: **la stessa versione ha retto una volta e crashato la successiva.**
Il crash non e' una funzione deterministica del commit installato. E' probabilistico, e la sequenza di
riavvii bruschi da watchdog (niente spegnimento pulito, niente raffreddamento) fatta susseguire in poco
tempo puo' essa stessa peggiorare la prova successiva -- lo stesso "degrado di sessione" gia'
documentato altrove in questo file, qui applicato a una catena di riavvii invece che a una sessione
lunga.

**Lezione**: su un fenomeno probabilistico un singolo test pass/fail per commit non prova niente. Il
bisect per commit presuppone determinismo; qui non c'era, e insistere avrebbe solo consumato altri
riavvii della stick dell'utente senza una risposta valida.

## Tre correzioni applicate, indipendenti dalla causa esatta

Non sapendo quale singola riga sia necessaria e sufficiente, la strada scelta e' stata ridurre il
carico concorrente totale nella finestra 0-25s, su tre fronti misurati:

**1. `dub_filter` senza pool sprecato** (`modules/metadata.py`, `dub_keep_mask`). Apriva un
`ThreadPoolExecutor` per OGNI pagina di 20 elementi, anche a verdetto gia' tutto in cache: dal log del
23/08, **10,74 s su 47 pagine, zero chiamate di rete**. Stesso difetto che il lotto 14 aveva gia'
chiuso per la costruzione delle listitem, mai applicato qui. Corretto in due fasi: risoluzione dei
verdetti in cache in sequenza (zero rete, solo SQLite/dict), pool aperto solo per chi resta senza
verdetto. Verificato sul device: stessi esiti, stesso log, solo senza l'overhead.

**2. `fen_blur` ridondante all'avvio** (skin, `shortcuts/skinvariables-startup.json`). Un
`RunPlugin(mode=fen_blur)` sparato da `Startup.xml` per pre-sfocare lo sfondo dello splash, misurato
**4-11 secondi** di lavoro Pillow in un interprete Python a se', anche nelle sessioni che completano
con successo (log 16:16, tre chiamate: 11,3s / 4,5s / 4,6s). Ridondante: `BlurService`, gia' in
esecuzione, produce lo stesso sfondo (stessa cache su disco) pochi secondi dopo. Rimossa la sola riga
`RunPlugin`; il resto del file (stato dello splash) intatto. Gia' segnalato come "eliminabile" nel
lotto 29 e mai tolto fino ad ora.

**3. `DIAG` spenta** (`modules/paginator.py`). `_diag_note()` faceva una lettura-modifica-scrittura di
`DIAG_BUILDS_PROP`, una proprieta' di finestra CONDIVISA, a ogni singola costruzione -- contesa fra
processi proprio quando piu' widget si costruiscono in parallelo. Le domande a cui doveva rispondere
(causa=, DOPPIONE) hanno gia' avuto risposta nei log raccolti finora. Stesso criterio di
`PERF_SELFTEST` (lotto 47.4): spenta quando ha gia' dato le risposte, riaccendibile a mano.

Tutte e tre verificate: sintassi, simboli (nessuna funzione persa nella riscrittura), stesso
comportamento a parita' di input. Nessuna nuova diagnostica aggiunta.

## Il test che ha funzionato, e quello ambiguo subito dopo

Nono tentativo della giornata (HEAD + le tre correzioni): **primo boot completo su nove**, tutti e 4 i
widget costruiti, `dub_filter` verificato corretto nel nuovo percorso, `TraktMonitor` completa il suo
giro. Poi, nell'istante esatto del primo `input keyevent` mandato via adb per simulare la navigazione,
crash -- ultima riga di log: caricamento di un layout tastiera/controller, il percorso che Android
attraversa quando registra un nuovo dispositivo di input. Sospetto forte che sia un effetto collaterale
di `adb input keyevent` (puo' comportarsi come "nuovo HID collegato") e non un difetto dell'app: la
memoria in quel momento era tutt'altro che in crisi (MemAvailable 228 MB, sopra tutti i livelli visti
negli altri crash). Non verificabile senza un tasto vero premuto sul telecomando fisico -- motivo per
cui il test finale e' stato lasciato all'utente.

## Rifatto un giro su `c887628`, e ha crashato anche quello

Su richiesta dell'utente (convinto che le versioni precedenti fossero piu' stabili), il codice del
plugin e' stato riportato esattamente a `c887628` ("miglioramenti player e navigazione") e ridistribuito
per un test con telecomando vero, sessione lunga. **Crash allo stesso identico punto.** Conferma diretta,
sul campo, di quanto gia' visto nel bisect: nessuna versione storica del plugin e' stata immune. Il
codice del plugin e' stato quindi riportato a HEAD + le tre correzioni sopra.

## Due piste segnalate, non nostre da correggere

- `script.texturemaker`: nessuna invocazione trovata nel percorso di avvio della skin (solo pannello
  impostazioni). Probabilmente non c'entra, ma importa anche `script.module.pil` -- se in futuro
  qualcosa lo richiama, e' un altro punto Pillow da controllare.
- `script.skinvariables`: addon Python esterno (non in questo repository), invocato PIU' VOLTE
  separatamente durante l'avvio (`skinvariables-startup.json`, poi `skinvariables-build-templates.json`
  -- rigenerazione sincrona e bloccante gia' segnalata nel lotto 29 --, poi `skinvariables-splash.json`
  che si rilancia da solo ogni 0,5s finche' i widget aggiornano). Ogni invocazione e' un interprete
  Python della skin, concorrente con quelli di Fen Light nella stessa finestra critica. Codice non
  nostro: nessuna correzione possibile da qui, ma e' un pezzo reale del carico totale che va tenuto
  presente prima di dire "e' colpa nostra" o "e' colpa loro".

## Stato a fine sessione

Sul device: HEAD del plugin + le tre correzioni sopra, skin con `fen_blur` rimosso dallo startup.
Working tree del repository allineato (stesse tre modifiche, non ancora committate). L'utente user'a'
la stick per qualche giorno in condizioni reali -- il test piu' onesto che esista per un fenomeno
probabilistico -- prima di decidere il prossimo passo.

## Metodo, per la prossima sessione

Un test pass/fail non prova niente su un fenomeno probabilistico: servono piu' ripetizioni della STESSA
build prima di attribuire un esito al codice. Il protocollo adb (orchestrazione su device, kill-server
durante la misura, nessun comando fino al prelievo) resta valido e va riusato. `adb input keyevent` non
e' equivalente a un tasto fisico e non va usato per riprodurre problemi vicini al confine
hardware/sistema -- solo per navigazione in condizioni non critiche.

---

# Lotto 48 bis — la sera dopo: telecomando vero, tre crash diversi, e BlurService isolato

Continuazione dello stesso giorno, con l'utente che ha ripreso a usare la stick col telecomando reale
(non piu' `adb input keyevent`). Tre crash in successione, ognuno diverso dagli altri -- la prova piu'
netta finora che non esiste una causa sola.

## Crash A: durante l'avvio di un film, non nostro

Log pulito, nessun'altra riga Fen Light nel mezzo. Sequenza:

```
Display resolution ADJUST: 1920x1080 @ 23.976025   <- 1o cambio modalita' (film a 23,976 fps)
VideoPlayer: OnLostDisplay received
error: Flush - timed out waiting for renderer to flush
VideoPlayer: OnResetDisplay received
Creating video thread (OMX.amlogic.avc.decoder.awesome aperto)
Loading skin file: VideoFullScreen.xml
Display resolution ADJUST: 1920x1080 @ 23.976025   <- 2o cambio modalita', 3s dopo il primo
[fine log]
```

Nessuna riga di codice nostro in questo tratto: e' la pipeline video di Kodi (VideoPlayer, MediaCodec,
il driver GPU Mali) che ricrea il contesto grafico due volte in tre secondi per adattare la frequenza
al file. Conferma diretta, con le prove, di quanto il lotto 47.7 aveva gia' sospettato senza log a
supporto. La leva possibile e' **Impostazioni -> Player -> Video -> "Adatta la frequenza di
aggiornamento del display"** = Off: costo, un po' di judder sui contenuti a 24fps; non ancora testato
pulito.

## Il test decisivo: BlurService isolato, 4 cicli, 4 su 4

In tre catture indipendenti raccolte fino a quel punto (17:20, `a1edbba`, e un nuovo crash delle
19:51), la riga finale del log prima del riavvio da watchdog era **sempre** `BlurService Starting
(Pillow: OK)` o l'equivalente import di Pillow da `fen_blur`. Mai visto prima con questa nettezza
perche' il bisect per commit del pomeriggio aveva distratto da un pattern piu' semplice.

Test: `Thread(target=BlurService().run).start()` commentato in `service.py`, poi **4 avvii consecutivi
via script sul device** (adb staccato, uptime controllato automaticamente + confermato dall'utente in
diretta guardando lo schermo). **4 su 4 senza riavvio** -- la prima sequenza pulita di tutta la
giornata, dopo una serie di crash quasi sistematici.

### La sfocatura sembrava esserci comunque: verificato, non lo era

L'utente ha notato che le immagini di sfondo sembravano ancora sfocate nonostante `BlurService` fermo,
e ha ipotizzato che il crash successivo fosse dovuto a un tentativo di generarne una nuova a servizio
spento. Controllata la cartella cache su disco (`addon_data/plugin.video.fenlight/blur/`): **l'ultimo
file scritto risaliva al 18 agosto**, cinque giorni prima. Zero produzione nuova durante i quattro
avvii di test. Quello che si vedeva era il **fallback gia' previsto dal codice** (`pil_available()`:
"la skin ricade sullo sfondo semplice + artwork nitido invece che sul nero") -- non sfocatura vera,
solo un fallback abbastanza dignitoso da non sembrare rotto a uno sguardo veloce. Buona notizia in se':
il fallback regge.

### La correzione: non tolto, differito

Disattivare per sempre perde la sfocatura. La cura e' rimandarne l'avvio oltre la finestra critica:

```python
BLUR_START_DELAY = 25

def _delayed_blur_start(self):
    if xbmc.Monitor().waitForAbort(BLUR_START_DELAY): return
    BlurService().run()
```

Chiamato con `Thread(target=self._delayed_blur_start).start()` al posto dell'avvio diretto.
`waitForAbort` invece di `sleep`, cosi' un abort di Kodi durante l'attesa non lascia il thread appeso.
L'interprete e' gia' vivo: aspettare qui non costa un processo in piu', solo un thread fermo.

## Crash B: una raffica di rete vera, non l'avvio

Sessione lunga e produttiva -- 4 minuti e mezzo di uso reale, non un crash da avvio. Cronologia
ricostruita dal log:

1. Riproduzione di un film avviata con successo (stessi sintomi del Crash A -- `Flush - timed out`,
   `ReleaseOutputBuffer error in render` -- ma stavolta **non e' crashato**: prova che quel sintomo non
   e' deterministico nemmeno lui).
2. Rientro alla home, widget ricostruiti.
3. Ricerca aperta, poi cronologia ricerche, poi un pannello di selezione.
4. Apertura di "Discover" con filtro di genere (Horror + Romance): titoli mai visti prima, quindi il
   filtro doppiaggio deve interrogare **davvero** la rete (TMDb + blu-ray.com) per una ventina di
   titoli insieme -- due chiamate da 1,84s e 1,94s di lavoro di rete vero, dentro il pool a 6 worker
   della correzione del lotto 48 (che qui lavora come previsto: non e' lo spreco chiuso prima, e'
   proprio il caso in cui il parallelismo serve).
5. La build di quella lista Discover impiega **11,64 secondi in totale**, quasi tutti di rete.
6. **Un'altra build di filtro doppiaggio parte in contemporanea** (altro widget in aggiornamento).
7. Il log si interrompe di netto.

Zero righe di blur, zero Pillow in tutta la sessione -- `BlurService` differito non aveva ancora
raggiunto i 25s da nessun avvio recente, quindi e' escluso con certezza da questo crash specifico.
La causa qui e' **una raffica di richieste di rete vere sovrapposta a un'altra costruzione di lista in
corso** -- un momento di carico che nessuna delle tre correzioni del lotto 48 tocca.

## Il quadro che emerge, detto senza girarci intorno

Tre crash, tre meccanismi scatenanti diversi: tempesta all'avvio (lotto 48), cambio di contesto grafico
all'apertura di un film (non nostro, Crash A), raffica di rete durante la navigazione (Crash B). Il
filo comune non e' un componente specifico -- e' che **su questo hardware qualsiasi sovrapposizione
sufficiente di operazioni pesanti e' un momento a rischio**, e i punti in cui questo succede sono
diversi ogni volta. Le correzioni fatte finora tolgono carico reale da alcuni di questi momenti, non
da tutti.

### Le leve rimaste, distinte per cosa richiedono

**Senza root (la stick non lo ha: `/sys/fs/pstore/` nega il permesso), da impostazioni, zero rischio:**
- Player -> Video -> "Adatta la frequenza di aggiornamento" = Off (Crash A).
- Fen Light -> `paginate.interactive` = Off (spegne il polling di `WidgetPaginator`, mai testato isolato).
- Fen Light -> `paginate.limit_widgets`/`limit_addon` piu' basso (liste piu' corte).
- Android -> disattivare/forzare l'arresto di app di sistema non usate (Google Cast, Play Games: visti
  girare in concorrenza con Kodi nei log, stesso 1 GB di RAM, non e' carico nostro ma lo occupa).

**Non disponibile senza root**: governor della CPU, dimensione/parametri dello zram, priorita' dello
scheduler, soglie dell'OOM killer -- le leve che servirebbero per un limite di sistema vero, chiuse su
un dispositivo Android non rootato di serie.

**Richiede codice, non ancora fatto**: limitare la concorrenza di rete del filtro doppiaggio quando
scopre molti titoli mai visti insieme (Crash B) -- proposto, non applicato, perche' la sessione era
gia' troppo lunga per un altro giro di test dal vivo.

## La skin: pista aperta, non ancora lavorata

L'utente sostiene che Arctic Fuse sia una delle cause di fondo -- troppo codice, molto inutilizzato --
e l'ipotesi e' coerente con la prima analisi di questa sessione (47.458 righe di XML in 239 file; alcune
variabili immagine rivalutate con fino a 18 condizioni concatenate **per elemento visibile, per
fotogramma**, durante lo scorrimento -- carico CPU vero, non solo peso a riposo). Non e' stato aperto
stasera: e' un progetto a se', per una sessione dedicata, non l'ultimo mezz'ora di una giornata gia'
pesante.

## Stato a fine sessione

Sul device: HEAD del plugin + le quattro correzioni (filtro doppiaggio senza pool sprecato, `fen_blur`
ridondante tolto dalla skin, `DIAG` spenta, `BlurService` differito di 25s). Repository allineato, non
ancora committato. Nessun altro test dal vivo previsto per stasera.

---

# Lotto 49 — La stick girava un ibrido di due generazioni di codice

## Il fatto, prima di ogni interpretazione

Confrontando gli MD5 dei file **sul device** con quelli di ogni commit recente, il quadro era questo:

| file | MD5 sul device | corrisponde a |
|---|---|---|
| `modules/kodi_utils.py` | `dfa079cf` | `c887628` / `07d747a` / `2599160` (22/08) |
| `modules/player.py` | `2d720a2c` | `c887628` / `07d747a` / `2599160` (22/08) |
| `modules/paginator.py` | `7258dc7f` | `a1edbba` (23/08) + patch `DIAG=False` |
| `service.py` | `eea2bc89` | HEAD + patch BlurService differito |
| `modules/metadata.py` | `945db478` | HEAD + patch filtro doppiaggio |

Cioe': **due file chiave fermi al 22/08, gli altri al 23/08.** Nessuna versione in git corrispondeva
all'insieme. Non era "HEAD + quattro correzioni" come scritto a fine lotto 48 bis: era un ibrido.

## Perche' questo spiega cose che sembravano inspiegabili

**1. Il bisect che si smentiva.** Nel lotto 48 lo stesso commit era stato spinto due volte e aveva
prodotto due esiti diversi, e la conclusione era stata "il crash e' probabilistico". Puo' anche
esserlo, ma la premessa era falsa: se i push non sostituivano tutti i file, due prove "dello stesso
commit" non stavano provando lo stesso codice. **La conclusione del lotto 48 va considerata non
dimostrata**, non smentita: semplicemente non era un esperimento valido.

**2. Il refresh globale invisibile nel log.** La riga `DIAG refresh: GLOBALE (UpdateLibrary)` e' stata
aggiunta in `kodi_utils.py` dopo il 22/08. Il `kodi_utils.py` sul device e' del 22/08 e **quella riga
non ce l'ha** (`grep` conferma: zero occorrenze). Quindi ogni ricostruzione globale avvenuta sulla
stick in questi giorni **non ha lasciato traccia nel log**: leggendo i log si vedevano gli effetti
(ondate di build) senza mai la causa. Abbiamo diagnosticato per giorni con lo strumento di misura
staccato.

**3. La guardia anti-scrobble non era mai arrivata.** In `player.py` il blocco che timbra "questa
modifica e' nostra" anche quando NON si marca niente -- quello che impedisce al monitor Trakt di
rileggere il proprio scrobble-stop come cambiamento remoto e ordinare `UpdateLibrary` -- **non e'
presente nella copia sul device**. E' esattamente la correzione descritta nel lotto 47, applicata nel
repository e mai finita sulla stick.

## Il log del crash delle 20:46 letto alla luce di questo

```
20:45:37  Display resolution ADJUST : 1920x1080 @ 23.976  <- inizio riproduzione
20:45:55  CVideoPlayer::CloseFile()                       <- l'utente chiude dopo ~18s (film NON finito)
20:45:56  SetNativeResolution 60.000004 / GLES: Maximum texture width: 4096  <- contesto GL ricreato
20:45:59  refresh mirato: 2 contenitori ricaricati        <- UNICO ordine di refresh loggato
20:46:08  ...prima build, 8.6s DOPO l'ordine
20:46:11  mdblist 101881 | 54 elementi | +14949 ms da CloseFile
20:46:12  mdblist 91378  | 62 elementi | +16101 ms da CloseFile   <- ondata 1: i 2 contenitori attesi
20:46:21  mdblist 101881 | 54 elementi | +25501 ms da CloseFile   <- LO STESSO di prima, di nuovo
20:46:23  mdblist 2194   | 42 elementi | +26951 ms da CloseFile   <- ondata 2, senza ordine loggato
          -> watchdog_reboot
```

Un solo ordine di refresh a log, due ondate di ricostruzione, e un contenitore costruito **due volte
in dieci secondi**. Con il `kodi_utils.py` vecchio l'ondata 2 non poteva loggarsi; con il `player.py`
vecchio la sua causa piu' probabile -- chiusura a meta' film -> scrobble stop -> monitor Trakt ->
ricostruzione globale -- non era intercettata. Le due cose combaciano.

Da notare anche il sintomo riferito dall'utente, "lo schermo diventa tutto di un colore": e' coerente
con il momento esatto in cui il contesto GL viene ricreato (uscita dal player, 60 Hz) e subito dopo
quattro interpreti Python con sei worker ciascuno si mettono a costruire ~180 listitem.

## Un difetto di progetto emerso per strada, indipendente dall'ibrido

`REFRESH_COALESCE_SECONDS = 5`, e l'accorpamento si misura da `_stamp_refresh()`, cioe' **dall'istante
in cui il refresh e' ORDINATO**. Ma su questa stick fra l'ordine e l'inizio effettivo della
costruzione passano 8-11 secondi (misurato: 20:45:59.797 -> 20:46:08.387, cioe' 8.6s; il lotto 43
aveva gia' misurato 11s). Un secondo ordine che arriva a +6s **passa la guardia** e accoda una
seconda ondata completa, che finisce per sovrapporsi alla prima ancora in corso. La finestra di
accorpamento e' piu' corta della latenza che dovrebbe coprire: cosi' com'e' non puo' funzionare.
Segnalato, non ancora corretto -- va corretto misurando il lavoro in volo, non l'orologio.

## Fatto in questo lotto

1. **Allineata la stick a una sola generazione di codice.** `am force-stop`, rimossi tutti i
   `__pycache__` (bytecode di una generazione diversa dai sorgenti), push dell'intera `resources/lib`
   (168 file) e del file skin. **MD5 dei cinque file chiave verificati uno per uno dopo il push**:
   device e working tree coincidono. Da adesso "la versione sul device" e' un'affermazione verificata,
   non un'assunzione.
2. **BlurService spento del tutto** (richiesta dell'utente), non piu' solo differito: la riga che lo
   avvia in `startServices()` e' commentata, `_delayed_blur_start` resta definito per riaccenderlo.
3. Restano attive le altre tre correzioni del lotto 48 (filtro doppiaggio senza pool sprecato,
   `fen_blur` ridondante tolto dalla skin, `DIAG=False`).

## Metodo, e vale piu' delle correzioni

**Dopo ogni deploy, verificare gli hash.** Tutta questa sessione e la precedente hanno ragionato su
"cosa gira sulla stick" senza mai controllarlo. Il costo e' stato due giorni di diagnosi su un
bersaglio che non era quello che credevamo, piu' una conclusione (il crash probabilistico del lotto
48) che ora va rimessa in discussione. Un `md5sum` costa un secondo.

## Lotto 49 bis — La sessione dell'utente sul codice allineato, e cosa NON dimostra

Dodici minuti di uso reale (20:56:53 -> 21:09:10), due riproduzioni complete, navigazione, load average
a 3,88. **Nessun crash**, uptime continuo. Primo risultato positivo su uso vero da giorni.

### La domanda dell'utente: "il BlurService spento e' la discriminante?"

**No, non lo si puo' dire, e le prove indicano semmai l'altra cosa.** Fra il crash delle 20:46 e questa
sessione sono cambiate DUE cose insieme: blur spento *e* codice allineato. Sono confuse fra loro, e una
sola delle due si vede agire nel log:

```
21:02:13  DIAG refresh: NON ordinato, Kodi ha gia' ricostruito da sola 12.0s dopo la chiusura
21:05:43  DIAG refresh: NON ordinato, Kodi ha gia' ricostruito da sola  4.0s dopo la chiusura
```

E' la guardia del `player.py` di HEAD -- quella che il lotto 49 ha scoperto non essere mai arrivata sul
device -- che sopprime il refresh ridondante alla chiusura del film. Ha lavorato due volte, esattamente
nel momento che nel crash delle 20:46 aveva prodotto la doppia ondata. Del blur, invece, il log non puo'
dire niente: e' spento, non lascia tracce, e non c'e' modo di sapere se sarebbe intervenuto.

Attribuire il miglioramento al blur sarebbe ripetere l'errore del lotto 48 bis, dove la stessa
conclusione era stata tratta su una correlazione e poi smentita. Per isolarlo davvero servirebbe
riaccendere il blur lasciando il codice allineato: una variabile per volta. Non fatto -- non vale il
costo di altri riavvii forzati per una domanda estetica.

### Quello che invece il log dimostra: il doppione post-riproduzione e' ancora li'

```
21:02:14  widget 101881 | 54 elementi | +13692 ms da CloseFile
21:02:15  widget  91378 | 48 elementi | +14380 ms
21:02:29  widget  91378 | 48 elementi | +28708 ms   <- lo stesso
21:02:30  widget 101881 | 54 elementi | +29737 ms   <- lo stesso
```

Gli stessi due contenitori, due volte, a quindici secondi di distanza. Stavolta non ha fatto crashare,
ma il lavoro doppio si fa ancora e resta un candidato aperto. Da notare che la guardia AVEVA soppresso
il refresh: la seconda ondata nasce altrove (paginator, o rilettura dei DirectoryProvider da parte di
Kodi al ritorno in primo piano) e va identificata prima di correggerla -- **non** corretta a intuito.

### Osservazione laterale, da verificare

`TraktMonitor` scrive "Next Update in 30 minutes" ma nel log ricorre ogni ~30 SECONDI (21:01:17,
21:02:10, 21:02:42, 21:05:45, 21:06:16). O il messaggio mente sull'unita', o l'intervallo non e'
rispettato. Ogni occorrenza e' una chiamata di rete piu' un potenziale innesco di ricostruzione
globale. Segnalato, non indagato.

### Correzione applicata (la "seconda strada", scelta dall'utente)

`kodi_utils.stamp_startup_rebuild()`, chiamata in cima a `service.startServices()` prima che parta
`TraktMonitor`: timbra la costruzione iniziale dei widget -- che Kodi fa comunque, per conto suo -- come
la ricostruzione globale che di fatto e'. Cosi' la prima sincronizzazione Trakt trova `refresh_age()`
piccolo invece di 1e9, si accorpa, e non ordina il `UpdateLibrary` duplicato 15 s dentro la sessione.
Una modifica Trakt fatta davvero altrove arriva comunque: dopo `TRAKT_REFRESH_COALESCE` la guardia
riapre. E' lavoro tolto, non aggiunto.

Deploy: `force-stop`, `__pycache__` rimossi, intera `lib` (168 file) spinta, **hash verificati**.

### Verifica della correzione: A/B sullo stesso device, stesso tipo di avvio

Costruzioni di widget durante l'avvio, prima e dopo `stamp_startup_rebuild()`:

```
PRIMA (avvio 20:57)                         DOPO (avvio 21:12)
20:57:16  DIAG refresh: GLOBALE             (nessun refresh globale)
20:57:18  91378   48 elementi               21:12:53  101881  54 elementi
20:57:18  101881  54 elementi               21:12:53  91378   48 elementi
20:57:28  2194    42 elementi               21:12:57  2194    42 elementi
20:57:30  91378   48 elementi  <- doppione
20:57:33  101881  54 elementi  <- doppione
--------------------------------            --------------------------------
5 costruzioni, 246 elementi                 3 costruzioni, 144 elementi
```

In entrambi i casi `Trakt Update Performed` e' avvenuto (21:12:49): la sincronizzazione fa il suo
lavoro, semplicemente non ordina piu' la ricostruzione duplicata. **Circa il 41% degli elementi
costruiti all'avvio non viene piu' costruito**, e sparisce la sovrapposizione fra la ricostruzione
globale e la costruzione iniziale ancora in corso -- cioe' la finestra in cui i crash da avvio si
concentravano. Nessun riavvio nell'avvio di verifica.

## Lotto 49 ter — Un modo di morire DIVERSO: Kodi cade, la stick resta in piedi

Alle 21:15:00.861 Kodi (pid 8173) e' morto **mentre era in primo piano**. La stick **non** si e'
riavviata: `uptime` continuo, 28 minuti, nessun `watchdog_reboot`. **Non e' lo stesso guasto** di tutti
i lotti precedenti e non va confuso con quello.

### Quello che le fonti dicono, e quello che non possono dire

| fonte | esito |
|---|---|
| `kodi.log` | finisce pulito alle 21:14:50.983 su una riga di routine di TraktMonitor. Nessun errore, nessuna eccezione Python, nessun traceback. |
| `logcat -b crash` | **vuoto**: nessun tombstone accessibile. |
| `logcat` (main+system, copre 20:48:17 -> 21:16:18, quindi tutta la sessione) | **zero righe `lowmemorykiller`, zero `Killing`**. Kodi non e' stato ucciso dal low memory killer di Android. |
| `logcat` righe del pid 8173 | **nessuna**: il processo non ha lasciato nulla nei buffer di sistema. |
| `dmesg` | `klogctl: Operation not permitted` -- serve root. **L'OOM killer del kernel scrive li' e solo li'**: se e' stato lui, non possiamo vederlo. |
| `addon.xml` sul device | `reuselanguageinvoker=false` -- intatto. |
| `fenlight.py` sul device | `if sys_exit_check(): sys.exit(1)` -- intatto. |

Le due protezioni note come fatali se rimosse ci sono entrambe: quella pista e' chiusa.

### L'indizio che resta, ed e' indiretto ma non debole

Subito **dopo** la morte di Kodi, Android ha riavviato in blocco: `mediashell` (CastReceiverService),
`gms`, `providers.tv`, `katniss`, `vending`, `inputmethod.latin`, `videos`, `gapps`. Non e' la causa --
e' l'effetto: quei servizi erano stati **sfrattati** mentre Kodi girava, e sono tornati appena la
memoria si e' liberata. Android aveva svuotato la casa per tenere in piedi Kodi, e Kodi e' morto lo
stesso. Su 1 GB, con `MemTotal` 1004 MB e il sistema a riposo (senza Kodi) gia' a 906 MB usati.

Cosa stava facendo l'utente: serie TV -> stagioni -> episodi. `Loading skin file: MyVideoNav.xml, load
type: KEEP_IN_MEMORY` alle 21:14:38, `seasons Lucky` alle 21:14:42 e **di nuovo** alle 21:14:44 (altro
doppione, 1 elemento, trascurabile come costo ma sintomo dello stesso difetto), `episodes Season 1`
alle 21:14:48, poi dieci secondi di silenzio e la morte.

### Ipotesi, dichiarata come tale

Esaurimento di memoria del processo Kodi (allocazione fallita o OOM killer del kernel), non un carico
CPU. **Non e' dimostrata** e con gli strumenti disponibili non e' dimostrabile a posteriori: senza root
non si legge `dmesg`, e senza tombstone non si sa se e' stato un `abort` o un segnale.

### Cosa e' stato messo in piedi invece di indovinare

Un campionatore che gira **sulla stick**, non da adb: `/sdcard/rss.sh`, ogni 10 s scrive in
`/sdcard/kodi_rss.csv` l'RSS di Kodi, `MemAvailable` e `SwapFree`. Due letture da `/proc`, nessuna rete,
nessun `adb shell` ripetuto -- cioe' nessuno dei difetti di metodo del lotto 48. Se Kodi cresce fino a
morire, la curva lo mostra; se muore a memoria stabile, l'ipotesi memoria cade e si guarda altrove.
E' la prima misura vera su questo modo di guasto.

### Nota sulla skin, che ora e' pertinente e non piu' solo un sospetto

47.458 righe di XML in 239 file; i piu' grandi: `Includes_Layouts.xml` 2517, `Includes_Objects.xml`
2096, `Dialog_DialogCustom.xml` 1716, `script-skinvariables-images-includes.xml` 1502. `MyVideoNav.xml`
si carica `KEEP_IN_MEMORY`, cioe' resta residente. Se la misura conferma la pista memoria, alleggerire
la skin smette di essere un'intuizione dell'utente e diventa la correzione indicata dai dati.

## Lotto 49 quater — La prima misura di memoria, e cosa si puo' onestamente dire dell'allineamento

Sessione 21:19:01 -> 21:24:50, chiusa **dall'utente** (`Saving settings`, tutti i servizi `Finished`,
`Exiting the application...`): chiusura pulita, nessun crash. Circa sei minuti, con una riproduzione.

### La curva di memoria (campionatore on-device, adb staccato)

```
21:19:09   RSS 250 MB   MemAvail 194 MB   SwapFree 431 MB
21:20:41   RSS 274 MB   MemAvail 276 MB   SwapFree 427 MB
21:21:03   RSS 391 MB   MemAvail 139 MB   SwapFree 407 MB   <- picco
21:21:56   RSS 206 MB   MemAvail 103 MB   SwapFree 369 MB   <- minimo di disponibile
21:22:16   RSS 127 MB   MemAvail 203 MB   SwapFree 348 MB
21:24:41   RSS 127 MB   MemAvail 217 MB   SwapFree 368 MB
```

**Non e' una perdita di memoria: e' il contrario.** L'RSS *scende* da 391 a ~120 MB mentre l'app e' in
uso attivo. Significa che il sistema ha compresso e spostato in zram una larga parte del working set di
Kodi: `SwapFree` cala da 431 a 348 MB, cioe' **~85 MB spinti nello swap**. Da quel momento in poi ogni
accesso a quelle pagine costa una decompressione su una CPU ARM32 debole. E' il meccanismo per cui "va
tutto lento" -- e rende il sistema fragile, perche' il margine e' gia' speso.

**Il picco ha una causa identificata nel log**, ed e' la skin:
```
21:20:52  Loading skin file: MyVideoNav.xml, load type: KEEP_IN_MEMORY
21:21:03  RSS 391 MB, MemAvailable 139 MB
```
Su `MemTotal` di 1004 MB. `KEEP_IN_MEMORY` vuol dire che quella finestra resta residente. **La pista
"alleggerire Arctic Fuse" non e' piu' un'intuizione: e' il picco misurato.**

Da segnalare anche che in questa sessione compare la firma del Crash A del lotto 48 bis
(`OnLostDisplay`, `Flush - timed out waiting for renderer to flush`, `OnResetDisplay`, 21:21:46-48)
**senza** che sia successo niente. Conferma che quella firma da sola non basta a spiegare un crash.

### Le guardie che non erano mai state sulla stick, all'opera

Quattro volte in sei minuti, ognuna una ricostruzione globale evitata:
```
21:22:16  TraktMonitor: refresh saltato, la modifica e' nostra ed e' gia' a schermo
21:22:28  DIAG refresh: MIRATO finestra Video (Container.Refresh sulla lista aperta)
21:24:09  DIAG refresh: NON ordinato, Kodi ha gia' ricostruito da sola 2.0s dopo la chiusura
21:24:18  TraktMonitor: refresh saltato, la modifica e' nostra ed e' gia' a schermo
```
E all'avvio i tre widget si costruiscono **una volta ciascuno** (21:19:25, :26, :30): la correzione
`stamp_startup_rebuild` tiene.

### La domanda dell'utente: "era il codice non allineato?"

**E' la spiegazione meglio sostenuta che abbiamo, e non e' piu' solo una correlazione**: le guardie
sopra sono codice che sulla stick fisicamente non c'era, sono state scritte esattamente per fermare le
tempeste di ricostruzione post-riproduzione, e le si vede agire nel log.

Ma va detto per intero, perche' la tentazione di dichiarare vittoria e' gia' costata due volte oggi:
- Dall'allineamento (20:56) **nessun `watchdog_reboot`**: uptime continuo di 1h22, due sessioni, tre
  riproduzioni, navigazione. Prima erano frequenti. E' il segnale migliore della giornata.
- Ma **Kodi e' comunque morto una volta** alle 21:15:00 gia' sul codice allineato (lotto 49 ter).
  L'allineamento ha plausibilmente chiuso una *classe* di guasto, non tutti i guasti.
- E il campione e' piccolo: ore, non giorni. "Sembra meglio" e' un'impressione corretta e coerente coi
  dati, non ancora una dimostrazione.

### Difetto residuo, invariato e ancora aperto

Il doppione post-riproduzione c'e' ancora: 21:24:09 `101881` + 21:24:12 `91378`, poi **di nuovo**
21:24:25 `101881` + 21:24:26 `91378` + 21:24:28 `2194`. E `91378` nel frattempo e' cresciuto a 87
elementi per la paginazione interattiva, quindi ogni doppione costa sempre di piu'. Prossimo bersaglio
naturale, da identificare (paginator? rilettura dei DirectoryProvider da parte di Kodi?) prima di
correggere.

# Lotto 50 — Il log di debug: quanto pesa la skin, quanto Fen Light, e la regressione di ieri notte

## 1. La quantificazione richiesta (sessione 22:34:22 -> 22:42:15, log di debug)

Tempo di vita degli interpreti Python, per addon, misurato accoppiando `start processing` con
`execution done` di `CPythonInvoker`:

| addon | invocazioni | totale | media |
|---|---|---|---|
| **plugin.video.fenlight** | 12 | **180,84 s** | 15,07 s |
| **script.skinvariables** (e' della SKIN) | 11 | **47,20 s** | 4,29 s |
| service.xbmc.versioncheck | 1 | 7,51 s | 7,51 s |

**Fen Light pesa circa 3,8 volte la skin.** All'avvio il rapporto e' anche piu' netto: tre interpreti
Fen Light da ~22 s ciascuno (~67 s) contro due `skinvariables` da 4,07 e 7,75 s piu' uno da 2,18 s
(~14 s), cioe' **~5x**. La priorita' indicata dall'utente e' confermata dai numeri.

**Ma il dettaglio decisivo e' un altro.** Per ogni widget, confronto fra vita dell'interprete e lavoro
dichiarato dalla nostra strumentazione:

| widget | interprete vivo | PERF "totale" | overhead |
|---|---|---|---|
| `mdblist 101881` (54 el.) | 22,95 s | 3,06 s | **19,9 s (87%)** |
| `mdblist 91378` (48 el.) | 23,67 s | 3,82 s | **19,9 s (84%)** |
| `mdblist 2194` (42 el.) | 7,23 s | 0,69 s | **6,5 s (90%)** |
| `build_continue_watching` | 21,44 s | (nessun PERF) | -- |

**L'85-90% del costo di Fen Light non e' la costruzione della lista.** E' avvio dell'interprete +
import dell'albero dei moduli + contesa sul GIL. Tutta la strumentazione costruita finora misurava il
10-15% del problema: ecco perche' ottimizzare la costruzione dava miglioramenti che l'utente non
sentiva.

L'avvio in chiaro: alle 22:34:35.137-.175, **cinque interpreti Python partono in 38 millisecondi**
(3 Fen Light + 2 skinvariables), piu' `versioncheck` e `cocoscrapers` gia' in volo, piu' il servizio
Fen Light. Un solo GIL per tutti.

Nota di metodo: le 29 invocazioni Fen Light su 41 che finiscono con `script aborted` **non sono un
guasto**: `fenlight.py` chiama `sys.exit(1)` quando `sys_exit_check()` -> `external()` e' vero, cioe'
per ogni widget. E' il comportamento voluto che previene il segfault di Kodi. Verificato prima di
segnalarlo.

## 2. I tre difetti segnalati dall'utente hanno UNA causa sola

Sintomi: (a) chiudendo il player la pagina paginata risultava "crashata"; (b) "segna come visto" su un
episodio non ha avuto effetto visibile; (c) il menu contestuale agisce sulla serie invece che
sull'episodio.

Il log li spiega tutti e tre con la stessa sequenza:
```
22:41:15.366  CGUIWindowManager::PreviousWindow: Activate new
22:41:15.368  ------ Window Init (MyVideoNav.xml) ------
22:41:15.373  CDirectoryProvider[]: refreshing..          <- path VUOTO
22:41:15.373  GetDirectory - Error getting                <- path VUOTO
22:41:15.417  Control 521 in window 10025 asked to focus, but it can't
22:41:16.725  inv=46  ?mode=build_season_list&tmdb_id=296756   <- ricade sul PADRE
22:41:21.301  inv=47  ?mode=build_episode_list&season=1&tmdb_id=296756
```
e identicamente dopo "segna come visto":
```
22:37:44.517  inv=34  mark_episode action=mark_as_watched season=1 episode=2
22:37:49.310  inv=35  build_season_list tmdb_id=328735    <- ricostruisce il PADRE
```

**Causa**: `end_directory(handle, cacheToDisc=False)` incondizionato in `indexers/seasons.py:153` e
`indexers/episodes.py:180`, introdotto in **`a1edbba` (test stick 3, 23/08 00:15)**. Senza cache su
disco, tornando dal player Kodi non ha la cartella da ripristinare: il path arriva vuoto, la lista e'
vuota, il fuoco non si posa, e si ricade sul genitore. Il menu contestuale agisce quindi sulla serie
perche' **a schermo c'e' davvero la serie**, non l'episodio.

Tutti gli altri indexer usano `cacheToDisc=False if is_external else True` (`tvshows.py:192`,
`movies.py:190`, `mdblist_lists.py:138`, `random_lists.py:255`, `continue_watching.py:65`). Solo
seasons ed episodes sono stati resi incondizionati: e' un'asimmetria, non una scelta di sistema.

**E il baratto era basato su una misura sbagliata.** Il commento nel codice scrive: *"Il prezzo e' una
rilettura del plugin al ritorno, e ora sappiamo quanto costa perche' e' misurata: 30-100 ms sulla
stick"*. Ma quei 30-100 ms sono il PERF "totale", cioe' la sola costruzione. Il prezzo VERO della
rilettura, misurato stasera con il debug:

```
inv=33  build_episode_list season=1 tmdb_id=328735   15,99 s
inv=40  build_episode_list season=1 tmdb_id=296756   20,41 s
```

**16-20 secondi, non 30-100 millisecondi: sbagliato di oltre 200 volte.** Stesso identico punto cieco
del paragrafo 1 -- si misurava la costruzione e si ignorava l'interprete.

## 3. Correzione indicata (proposta, non applicata)

Riportare `seasons.py` ed `episodes.py` alla forma usata da tutti gli altri indexer:
`end_directory(handle, cacheToDisc=False if is_external else True)`. Si riprende la cache in finestra
Video, quindi il ritorno dal player e' immediato e la lista non si svuota. Si riaccetta il difetto per
cui il badge "episodi rimanenti" puo' restare vecchio finche' non si riapre la serie -- che e'
estetico, contro tre difetti funzionali. Il baratto originale era sensato con 30-100 ms di prezzo; con
16-20 s non lo e'.

## Lotto 50 bis — Tampone applicato e marcatori messi

### Tampone (i tre difetti dell'utente)

`indexers/seasons.py` e `indexers/episodes.py` (`build_episode_list`) tornano a
`end_directory(handle, cacheToDisc=False if is_external else True)`, cioe' esattamente la forma che
avevano prima di `a1edbba` e che usano tutti gli altri indexer. Verificato con `git show 922743c`:
`seasons.py:114` e `episodes.py:141` erano gia' cosi'. **`episodes.py:416` (episodi singoli) era `False`
gia' prima e NON e' stato toccato** -- non fa parte della regressione.

E' dichiarato tampone nel commento del codice, non soluzione: il badge "episodi rimanenti" puo'
tornare a restare vecchio. La soluzione vera e' invalidare la cache in modo MIRATO quando siamo noi a
cambiare lo stato visto -- cache accesa di default, una rilettura sola sulla cartella davvero cambiata.
Oggi non abbiamo ne' freschezza ne' velocita': il tampone e' strettamente meglio dello stato attuale su
ogni dimensione tranne il badge.

### Marcatori (i 18 secondi invisibili)

Prima di scriverli e' stato verificato il sospetto piu' ovvio, e **si e' rivelato falso**: l'albero dei
moduli e' gia' pigro (`router.py` importa 2 cose, `kodi_utils.py` 4). **Gli import non sono la causa.**
Evitata cosi' una correzione basata su un'ipotesi, che e' l'errore di metodo contestato dall'utente
all'inizio di tutto.

Verificato anche che `set_view_mode` **esce subito per i widget** (`if is_external: return`): la sua
attesa attiva non spiega il costo dei widget, ma non era mai stata cronometrata per stagioni/episodi,
dove puo' valere fino a 3 s. Ora e' misurata da un involucro che lascia la logica intatta
(`_set_view_mode_impl`).

Nuova riga di log, una per invocazione:
```
###FenLight PERF INVOCAZIONE###: <mode> | totale N ms | import A + routing->lista B + consegna C + coda D ms
```
- `import` -- caricamento moduli (atteso piccolo, conferma o smentisce quanto sopra)
- `routing->lista` -- da fine import a quando la lista e' pronta. **Contiene la costruzione che PERF
  gia' misura: la differenza fra questo numero e il PERF 'totale' e' il preparativo mai visto.**
- `consegna` -- `add_items` + `endOfDirectory` (gia' dettagliato da PERF CONSEGNA)
- `coda` -- tutto cio' che gira dopo la consegna, prima dell'uscita

Costo della misura: quattro letture di orologio e una riga di log per invocazione. Nessuna proprieta'
di finestra, nessuna traversata verso la GUI -- l'errore fatto con `DIAG` in `paginator` non si ripete.
Da spegnere quando avranno risposto.

`fenlight.py` cresce da 7 a 19 righe. Verificato con `ast` che **`sys.exit(1)` resta l'ULTIMA
istruzione** (memoria: e' cio' che previene il segfault sui widget) e che `kodi_utils` passa da 105 a
107 simboli, nessuno perso.

### Cosa serve dal prossimo log

Il confronto fra `CPythonInvoker start processing` (Kodi, livello debug) e il nostro `totale`: la
differenza e' il costo di creazione dell'interprete, l'unico pezzo che dall'interno non possiamo
vedere. **Per questo il debug va lasciato acceso ancora una sessione**, poi si spegne.

## Lotto 50 ter — I marcatori parlano, e un crash DA FERMA con un colpevole nuovo

### Prima lettura dei marcatori (avvio 23:46:48)

| invocazione | totale | import | routing->lista | di cui costruzione (PERF) | **cieco** | consegna | coda |
|---|---|---|---|---|---|---|---|
| `build_continue_watching` | 15207 | 2480 | 12715 | -- | -- | 6 | 5 |
| `mdblist 101881` (54 el.) | 16665 | 2761 | 13856 | 2410 | **11446** | 41 | 6 |
| `mdblist 91378` (48 el.) | 16950 | 2777 | 13904 | 2590 | **11314** | 259 | 9 |
| `mdblist 2194` (42 el.) | 4769 | 580 | 4163 | 440 | **3723** | 19 | 8 |

*(millisecondi)*

**Consegna e coda sono irrilevanti** (6-259 ms su 17 s). Questo **chiude** la domanda posta dal lotto
48 -- "il costo sta in `add_items` (peso dell'elemento) o in `endOfDirectory` (numero)?": **nessuno dei
due**. Alleggerire il singolo elemento non avrebbe spostato niente, e sarebbe stato il prossimo lavoro
se non avessimo misurato.

**Restano ~11,4 s ciechi** fra la fine degli import e l'inizio della costruzione misurata: l'85%
dell'invocazione, ancora senza nome.

**La contesa vale un fattore 3-4.** `2194` e' partita 3,5 s dopo le altre, quasi da sola: import 580 ms
contro 2760, preparativo 3,7 s contro 11,4. Stesso codice, un terzo del costo. **Sfalsare le partenze
non e' un ritocco: e' il fattore piu' grosso misurato finora.**

### Correzione a quanto scritto nel lotto 50

Nel lotto 50 avevo dichiarato "gli import non sono la causa", basandomi sul conteggio degli import in
cima ai file (`router.py` 2, `kodi_utils.py` 4). **Il controllo era sbagliato**: l'import misurato e'
2,5-2,8 s, non zero. E soprattutto gli import di Fen Light sono in maggioranza **pigri**, dentro le
funzioni: non compaiono in testa ai file e non finiscono nel segmento `import`, finiscono **dentro
`routing->lista`**, cioe' dentro gli 11,4 s ciechi. L'ipotesi scartata e' probabilmente viva, stava
solo in un altro segmento. Prossimo marcatore: ingresso di `routing()` e subito dopo l'import
dell'indexer.

### Il crash: nuovo per il momento in cui avviene

23:46:48 avvio, 23:47:16 tempesta d'avvio conclusa **regolarmente** (tre widget costruiti, marcatori
scritti, nessun errore). Poi Kodi resta **fermo sulla home, senza input dell'utente**. Le uniche righe
sono i tick di TraktMonitor: 23:47:38, 23:48:08, 23:48:41. Il tick successivo atteso (~23:49:11) non
arriva. Riavvio da watchdog alle ~23:50:40.

**Tutti i crash precedenti erano sotto carico** (tempesta d'avvio, riproduzione, navigazione). Questo
e' a riposo. Cautela d'obbligo: le scritture del log sono bufferizzate e un reset hardware ne perde una
parte, quindi l'ultima attivita' vera puo' essere leggermente posteriore alle 23:48:41.

### Il colpevole nuovo: TraktMonitor gira 60 volte troppo spesso

```python
wait_time = 1800                                   # fallback: 1800 secondi = 30 minuti
sync_interval, wait_time = trakt_sync_interval()   # wait_time = 30, che sono MINUTI
next_update_string = update_string % sync_interval # "Next Update in 30 minutes..."
wait_for_abort(wait_time)                          # waitForAbort vuole SECONDI
```
`trakt_sync_interval()` (`modules/settings.py:152`) restituisce l'impostazione in **minuti** (default
`30`, e il fallback `1800` secondi = 30 minuti lo conferma). **Manca la conversione `* 60`.** Il
servizio interroga Trakt via rete **ogni 30 secondi invece che ogni 30 minuti**: 120 chiamate l'ora
invece di 2, ognuna con handshake TLS su ARM32 debole, e ognuna un potenziale innesco di ricostruzione.

E' anche **l'unica cosa che girava** nel momento in cui la stick e' morta da ferma. Non e' una prova di
causalita', ma e' un difetto reale, dimostrato dal disaccordo fra cio' che il log dichiara ("30
minutes") e cio' che fa (30 secondi), indipendentemente dal crash.

### Due errori miei, registrati

1. **Il campionatore di memoria era morto alle 22:26**, un'ora prima del crash: per questo riavvio non
   ci sono dati di memoria. Era avviato con `nohup` e non e' sopravvissuto. Ora riparte con `setsid`,
   in sessione propria. Inoltre `/proc/loadavg` e' negato da SELinux: il load si legge da `uptime`.
2. **La sessione crashata l'avevo avviata io**, non l'utente, e durante quella sessione ho fatto due
   `adb pull` del log (23:47:00 e ~23:48:08). Sono letture, ma non sono gratis. Il codice **non** e'
   stato cambiato con Kodi attivo -- `am force-stop` precede il push e gli hash sono stati verificati
   prima di riaccendere -- ma la domanda dell'utente era legittima e la risposta va data con la
   sequenza, non con una rassicurazione.

### Marcatore dentro routing() (24/08)

`router.routing()` timbra `routing_in` in cima, e `indexer_in` subito dopo l'import PIGRO del modulo
indexer, sui quattro rami che ci interessano: `mdblist.*.list`, `build_season_list`,
`build_episode_list`, `build_continue_watching`. Non su tutti e trenta i rami: non serve sporcare il
router per rispondere a una domanda.

La riga di log diventa:
```
###FenLight PERF INVOCAZIONE###: <mode> | totale N ms | import A + import pigri B + indexer C + consegna D + coda E ms
```
**`import pigri`** = parsing dei parametri + caricamento del modulo indexer e di tutto il suo albero.
**`indexer`** = il lavoro vero, che contiene la costruzione gia' misurata da PERF.

E' il taglio che decide fra due correzioni diverse:
- se i ~10 s ciechi stanno in **`import pigri`**, sono import mascherati (stanno dentro le funzioni,
  per questo il conteggio degli import in cima ai file non li vedeva) e la correzione e' alleggerire
  l'albero dei moduli;
- se stanno in **`indexer`**, e' lavoro vero o contesa sul GIL, e la correzione e' la coda proposta
  dall'utente.

Senza questo taglio si sceglierebbe a caso fra le due.

### Decisione dell'utente su TraktMonitor

Il polling ogni 30 s **resta com'e'**: l'utente riferisce che non e' mai stato un problema e che tiene
lo stato Trakt sempre allineato. Decisione informata, registrata. Resta il fatto che l'impostazione si
chiama "minuti" e il log scrive "Next Update in 30 minutes": se un giorno il valore venisse alzato a 60
aspettandosi un'ora, si otterrebbero 60 secondi. Da allineare almeno nel testo, quando si tocchera'
altro in quella zona.

---

# Lotto 51 — Trovato: i ~10 secondi ciechi sono gli IMPORT PIGRI

## La misura che chiude la domanda (24/08, marcatore dentro routing)

```
build_continue_watching | import 1727 + import pigri 10882 + indexer 1345 + consegna 2 + coda 2
mdblist 101881          | import 1959 + import pigri 10661 + indexer 2375 + consegna 21 + coda 23
mdblist 91378           | import 1629 + import pigri 11104 + indexer 2731 + consegna 69 + coda 7
mdblist 2194 (da sola)  | import  529 + import pigri  2966 + indexer  403 + consegna 41 + coda 6
build_season_list       | import  214 + import pigri  2094 + indexer   23 + consegna 1 + coda 128
build_season_list       | import  270 + import pigri  3972 + indexer   30 + consegna 1 + coda 101
```

**`build_season_list`: 2094 ms per caricare i moduli, 23 ms per fare il lavoro. Novanta volte tanto.**

Costruire le liste era gia' praticamente gratis. Il costo di Fen Light e' **ricaricare da capo il
proprio albero di moduli a ogni invocazione**, perche' con `reuselanguageinvoker=false` fra
un'invocazione e l'altra non sopravvive niente.

La contesa moltiplica: 10,9 s in parallelo contro 3,0 s da soli per lo stesso tipo di lavoro (fattore
3,6). Tre interpreti leggono **gli stessi file** dalla stessa flash lenta nello stesso momento,
ciascuno costruendosi la propria copia, senza condividere nulla.

## L'albero, misurato

`indexers.seasons` caricava **20 moduli Fen Light, 8297 righe** -- piu' `requests` con tutto il suo
albero -- per 23 ms di lavoro. La catena:

```
indexers.seasons
 |- modules.metadata (867)
 |   |- apis.imdb_api (320) --> requests
 |   |   \- modules.dom_parser (115)
 |   \- apis.skyhook_api (122)
 \- modules.watched_status (573)
     |- apis.trakt_api (1155) --> requests
     \- caches.trakt_cache (245)
```

## Tre correzioni applicate

1. **`apis/imdb_api.py`: `import requests` era MORTO.** Zero occorrenze di `requests.*` nel file --
   le richieste passano da `make_session()` di `kodi_utils`. Rimosso: guadagno puro, rischio nullo.
2. **`modules/watched_status.py`: `apis.trakt_api` non si importa piu' a livello di modulo.** Lo
   pagava chiunque toccasse `watched_status`, compresa la lista stagioni, che di Trakt non chiede
   niente (legge il visto dal database locale). Spostato dentro le **sei** funzioni che lo usano
   davvero, verificato con `ast` che ogni uso abbia il suo import in scope e che non resti nessun
   import in cima.
3. **`apis/trakt_api.py` e `apis/mdblist_api.py`: `requests` e la `Session` nascono alla prima
   richiesta.** Erano `session = requests.Session()` a livello di modulo. Ora un `_get_session()`
   pigro; la Session resta una sola per interprete, cambia solo *quando* nasce. 7 + 1 chiamate
   riscritte, verificato che nessun altro modulo usi `trakt_api.session` o `mdblist_api.session`.

## Risultato statico

| catena | prima | dopo | `requests` |
|---|---|---|---|
| `indexers.seasons` | 20 mod / 8297 righe + requests | 19 mod / 7155 righe | **NO** |
| `indexers.episodes` | 21 mod / 8600 + requests | 21 mod / 8610 | **NO** |
| `indexers.mdblist_lists` | 27 mod / 10265 + requests | 27 mod / 10282 | **NO** |
| `indexers.continue_watching` | 23 mod / 9127 + requests | 23 mod / 9137 | **NO** |

Il conteggio di righe cambia poco (le poche in piu' sono i commenti di queste correzioni), ma
**`requests` sparisce da tutte e quattro le catene**: e' quello il pezzo caro, perche' si tira dietro
`urllib3`, `certifi`, `ssl`, `http.client`, `email`.

## Da verificare sul device

Baseline da battere, stesse operazioni: `build_season_list` **2094 ms** di import pigri, widget
dell'avvio **10,6-11,1 s**. Se il numero non scende, l'ipotesi e' sbagliata e va detto.

## Correzione a un mio conteggio precedente

Avevo scritto "16 moduli, 6202 righe": il mio tracciatore saltava i casi `from apis import tmdb_api`,
dove il sottomodulo importato non veniva seguito. I numeri veri sono quelli sopra.

## Lotto 51 bis — La prima correzione non era servita a niente, ed ecco perche'

### Il confronto, senza addolcirlo

| invocazione | `import pigri` prima | dopo | delta |
|---|---|---|---|
| `build_continue_watching` | 10882 | 10654 | -2% |
| `mdblist 101881` | 10661 | 10561 | -1% |
| `mdblist 91378` | 11104 | 10782 | -3% |
| `mdblist 2194` (da sola) | 2966 | 2437 | -18% |
| `build_season_list` | 2094 | **2460** | **+17%** |

Nessun guadagno. E il segmento `import` iniziale -- codice che **non ho toccato** -- e' passato da
1727/1959/1629/529 a 2545/2563/2407/1284, cioe' +31% / +143%. Due letture indicano quindi anche un
rumore di fondo notevole fra un avvio e l'altro (nella sola sessione baseline, `build_season_list` era
gia' variato da 2094 a 3972 ms per lavoro identico). Ma la causa principale e' un'altra ed e' un mio
errore di analisi.

### L'errore: un import che non si vede

`apis/imdb_api.py` aveva `import requests` (morto, rimosso) **ma anche**, alla riga 36:
```python
session = make_session('https://')
```
e `kodi_utils.make_session()` fa `import requests` al suo interno. Quindi `requests` continuava a
essere caricato all'import del modulo, **senza che nel file comparisse una sola istruzione
`import requests`**. Il mio tracciatore statico seguiva solo le istruzioni `import` e non vedeva una
CHIAMATA DI FUNZIONE a livello di modulo che importa.

Cercando la stessa forma in tutto il codice: `make_session()` a livello di modulo compare in
**sette** file, e tre stanno nelle catene dell'avvio e della navigazione:
`apis/tmdb_api.py:15`, `apis/skyhook_api.py:10`, `apis/imdb_api.py:36`
(gli altri quattro -- torbox, offcloud, easydebrid, easynews -- sono sul percorso della riproduzione,
non ancora toccati).

Avevo quindi tolto **una dichiarazione su quattro vie d'accesso**. Il risultato nullo era corretto.

### Correzione applicata

Stessa `_get_session()` pigra di `trakt_api`/`mdblist_api` applicata a `tmdb_api`, `skyhook_api`,
`imdb_api`. Riscritte 2 + 1 + 9 chiamate `session.*`. Verificato che nessun altro modulo usi
`<modulo>.session`.

**E il verificatore e' stato corretto**: ora considera import morto anche una chiamata a
`make_session()` a livello di modulo, e salta i corpi delle funzioni (la prima versione contava come
"sporche" anche le catene appena ripulite, perche' scendeva dentro `_get_session`). Esito:

```
indexers.seasons             NO -- catena pulita
indexers.episodes            NO -- catena pulita
indexers.mdblist_lists       NO -- catena pulita
indexers.continue_watching   NO -- catena pulita
```

### Nota di metodo per la prossima misura

Il rumore fra avvii e' grande (lo stesso `build_season_list` ha oscillato 2094 -> 3972 ms nella stessa
sessione). Una singola coppia prima/dopo non basta a decidere differenze sotto il 20%: servono piu'
ripetizioni e il **minimo**, non la media, perche' il minimo e' il caso meno disturbato.

---

# Lotto 52 — `reuselanguageinvoker` resta chiuso; potatura completata; una misura mirata

## 1. Il punto B non si riapre, ed e' documentato dal 14/08

L'utente ha scelto di attaccare `reuselanguageinvoker`. **Era gia' stato tentato e chiuso: lotto 11c.**
Crash report macOS `EXC_BAD_ACCESS (SIGSEGV)` in `CPythonInvoker::execute` -> `PyDict_SetItemString`,
thread `LanguageInvoker`. Due esiti, entrambi inutili: con `sys.exit(1)` il flag e' **inerte**
(`inv=1` su 17 build), senza `sys.exit(1)` il riuso avviene e **Kodi segfaulta all'avvio**.

**E c'e' un limite che rende il punto discutibile a prescindere**, scritto nel lotto 11b e che avevo
ignorato proponendolo: *Kodi riusa un interprete solo fra invocazioni NON sovrapposte*. I tre widget
dell'avvio sono concorrenti, quindi ognuno avrebbe comunque il suo interprete. **La mia stima "vale
~23 s a boot" era sbagliata** e va cancellata: il riuso non tocca il caso che stiamo inseguendo.

## 2. Due ipotesi eliminate

**Il bytecode funziona.** I `.pyc` sul device vengono rigenerati (dir `__pycache__` del 24/08 00:24,
piu' recenti dei sorgenti) e riusati: la compilazione da sorgente non e' il costo.

**Ma si spingevano 75 `.pyc` di giugno a ogni deploy.** Erano dentro il repo e finivano nel `push`,
per poi essere invalidati sul device. Rimossi: il push passa da **168 file / 2,9 MB a 93 file /
1,2 MB**. Non e' un guadagno di runtime, e' igiene -- e toglie un confondente dalle misure, perche' il
primo avvio dopo ogni deploy pagava la ricompilazione di quei file.

## 3. La misura mirata (il "chi sveglia la rete")

Sulla stick, stesso widget, **entrambe misure del device**:
```
23:57 (boot2.log)  mdblist 101881 | risoluzione 0.65s + costruzione 1455 ms
00:28 (c2.log)     mdblist 101881 | risoluzione 7.22s + costruzione 1079 ms
```
I metadati sono al 100% in cache e il filtro doppiaggio fa zero rete, eppure la risoluzione esplode:
e' `requests` che si importa li' dentro. Ma la cache delle liste mdblist ha **TTL 24 ore**
(`mdblist_api.py:65`), quindi qualcuno sveglia la rete su un widget che dovrebbe essere tutto in cache.

`kodi_utils.import_requests(who)` e' ora **l'unico punto** da cui `requests` entra in un interprete:
cronometra l'import e scrive **una riga per interprete**:
```
###FenLight PERF REQUESTS###: importato in N ms | primo richiedente: <chi>
```
`make_session()` e i `_get_session()` di `trakt_api` e `mdblist_api` ci passano tutti. Cosi' sapremo
CHI e QUANTO, invece di indovinare.

## 4. Fronte 2 completato: potatura

**Avvio** -- `modules/metadata.py` non importa piu' `apis.imdb_api` ne' `apis.skyhook_api` a livello di
modulo (li usavano solo `movie_meta`, `tvshow_meta`, `episodes_meta`). `metadata` e' importato da quasi
tutti gli indexer, quindi li pagava anche chi non ne aveva bisogno -- ed entrambi creavano una Session
di modulo, cioe' tiravano dentro `requests`.

**Riproduzione** -- gli otto moduli API rimasti (`torbox`, `alldebrid`, `real_debrid`, `easydebrid`,
`premiumize`, `offcloud`, `bluray`, `easynews`) avevano `import requests` e/o `session = make_session()`
a livello di modulo. Ora tutto pigro. Due degli import erano **morti** (`torbox`, `easydebrid`: zero
occorrenze di `requests.*`).

### Risultato

| catena | righe prima | righe dopo | `requests` all'import |
|---|---|---|---|
| `indexers.seasons` | 8297 | **6628** | NO |
| `indexers.episodes` | 8600 | **8083** | NO |
| `indexers.mdblist_lists` | 10265 | **9755** | NO |
| `indexers.continue_watching` | 9127 | **8610** | NO |
| `modules.sources` (riproduzione) | -- | 11653 | NO |
| `modules.player` | -- | 8027 | NO |

Verificato con `ast` su tutti i file di `apis/`: **nessun simbolo perso** rispetto al backup, solo i
nuovi `_get_session`/`_requests`. Nessun `import requests` ne' `session = ` di modulo residuo.
L'intero `lib` compila.

## Nota di metodo dall'utente

I test sono stati fatti **anche su Mac**, che ha tempi molto piu' piccoli. `OTTIMIZZAZIONI.md` mescola
le due fonti: **ogni numero storico va letto con l'etichetta del dispositivo**. I confronti di questo
lotto sono tutti fra log della stick, verificati uno per uno.

## Lotto 52 bis — Il risultato, e chi resta a svegliare la rete

### Il guadagno, misurato (secondo boot, `.pyc` caldi, tutte misure stick)

| invocazione | run B (00:17) | run C2 (00:28) | **d2 (00:57)** | delta vs C2 |
|---|---|---|---|---|
| `mdblist 101881` | 15487 | 14689 | **9453** | **-36%** |
| `mdblist 91378` | 16022 | 15262 | **10049** | **-34%** |
| `build_continue_watching` | 14654 | 14191 | **13239** | -7% |
| `mdblist 2194` (da sola) | 4380 | 3827 | **3389** | -11% |

La `risoluzione` del widget mdblist torna a **1,10 s** dai 7,22 s: quei widget non toccano piu'
`requests`. E' il primo guadagno grosso e non ambiguo della serie.

### La misura che serviva: quanto costa `requests`, e chi lo chiede

```
[boot 1]  importato in 8749 ms | primo richiedente: trakt_api
          importato in 4533 ms | primo richiedente: make_session(https://api.themoviedb.org/3)
[boot 2]  importato in 7617 ms | primo richiedente: trakt_api
          importato in 5425 ms | primo richiedente: make_session(https://api.themoviedb.org/3)
```

**`requests` costa 4,5-8,7 s** a freddo su questa stick, misurato direttamente e non piu' dedotto. E si
paga **due volte per avvio**, non quattro:

1. **`trakt_api` -> l'interprete del SERVIZIO.** Il timestamp lo dimostra: `PERF REQUESTS` alle
   00:58:04.592, `TraktMonitor Service Update Success` alle 00:58:05.525. E' la prima sincronizzazione
   Trakt dopo l'avvio. **L'utente ha scelto di tenere il polling**, quindi questo costo e' voluto --
   ma va saputo che l'avvio ne paga 7,6 s.
2. **`tmdb_api` -> `build_continue_watching`.** `PERF REQUESTS` alle 00:58:06.141, l'invocazione
   chiude alle 00:58:06.683. Dei 7099 ms del suo segmento `indexer`, **5425 sono l'import di
   requests**: "continua a guardare" fa una chiamata TMDb a ogni avvio. Perche' -- cioe' cosa non e'
   in cache -- non e' ancora stabilito. **Prossimo bersaglio.**

I due widget mdblist non lo caricano piu' affatto.

### Un difetto mio, trovato rileggendo il proprio lavoro

In `get_hidden_progress_items` avevo messo l'import pigro **in cima alla funzione**, ma serve solo in
uno dei due rami:
```python
if watched_indicators == 0: return main_cache.get(...)   # ramo locale, NON usa Trakt
else: return trakt_get_hidden_items('progress_watched')
```
E `watched_indicators` vale **0** sulla stick (predefinito 'Fen Light', non 'Trakt'): il ramo preso e'
sempre quello locale, e l'import in cima caricava comunque `apis.trakt_api`, 1155 righe, per niente --
su `continue_watching`, cioe' a ogni avvio. Import spostato dentro il ramo che lo usa.

Lezione generale: **rendere un import pigro non basta, va messo nel ramo giusto.** Gli altri cinque
punti di `watched_status.py` sono su percorsi da azione dell'utente (marcature, segnalibri) dove Trakt
serve davvero, e restano dove sono.

### Igiene

`__pycache__` tolti dal repo: il push passa da **168 file / 2,9 MB a 93 / 1,2 MB**. Erano 75 `.pyc` di
giugno che finivano sul device per essere invalidati -- e sporcavano il primo avvio dopo ogni deploy.

## Lotto 52 ter -- verifica della correzione `get_hidden_progress_items` (boot e1, 24/08 01:04)

Tutte le misure sotto vengono dalla **stick** (`adb pull` di `kodi.log`), non dal Mac.

### Il totale mente: il primo boot dopo un deploy paga la ricompilazione del bytecode

A colpo d'occhio e1 sembra una regressione (mdblist 12510/12801 contro i 9453/10049 di d2). Non lo e':
**tutti i `.pyc` sul device sono datati 01:04**, cioe' generati *durante* e1. Il deploy aveva svuotato
`__pycache__`, quindi e1 e' un primo-avvio-a-bytecode-freddo, d2 era caldo. Il costo si scarica quasi
per intero sul segmento `import`:

| segmento `import` | d1 (freddo) | d2 (caldo) | e1 (freddo) |
|---|---|---|---|
| mdblist A | 2833 | 1374 | 3928 |
| mdblist B | 2892 | 1561 | 4914 |
| continue_watching | 2827 | 1523 | 4006 |

**Regola di misura:** dopo un deploy che tocca `__pycache__`, il segmento `import` del primo boot va
scartato. Confrontare freddo-con-freddo (d1 vs e1) o caldo-con-caldo.

### Confronto valido: il segmento `indexer`, l'unico che la correzione poteva toccare

| `indexer` | d1 (freddo, pre-fix) | e1 (freddo, post-fix) | delta |
|---|---|---|---|
| mdblist A | 4541 | **3494** | -23% |
| mdblist B | 4949 | **3180** | -36% |
| build_continue_watching | 7618 | **6244** | -18% |
| mdblist piccola | 768 | **325** | -58% |

Il guadagno c'e' ed e' coerente anche contro d2 (caldo): 3586->3494, 3871->3180, 7099->6244. Togliere
le 1155 righe di `apis.trakt_api` dal ramo sbagliato vale **1,0-1,8 s per invocazione**.

### Cosa NON e' cambiato

- **`import pigri` e' piatto:** 4993-5182 (d1), 4464-4586 (d2), 4619-5048 (e1). L'albero dei moduli e'
  intatto, e resta il bersaglio piu' grosso rimasto.
- **`requests` si importa ancora due volte**, 7445 ms (`trakt_api`, interprete del servizio: costo
  voluto) + 4355 ms (`make_session(tmdb)` dentro `build_continue_watching`). La chiamata TMDb
  all'avvio di 'continua a guardare' e' ancora li'. **Prossimo bersaglio, invariato.**

### Salute del boot

3 costruzioni (stabile da lotto 51), nessun errore reale in log, 4 `script aborted` = le 4 invocazioni
widget (intenzionale, lotto 11c), uscita pulita alle 01:05:01. Wall-clock avvio -> ultimo widget:
23,6 s (d1) / 21,4 s (d2) / 23,9 s (e1) -- dominato dal bytecode freddo, non confrontabile.

### Conferma a bytecode caldo (boot e2, 24/08 01:10)

I `.pyc` sono rimasti datati 01:04: e2 li ha riusati, e il segmento `import` e' tornato a
1502-1776 ms (contro i 3928-4914 di e1). **L'ipotesi della ricompilazione e' confermata**, e ora il
confronto caldo-contro-caldo con d2 e' valido. Invocazioni appaiate per `list_id` via thread ID --
l'ordine di completamento nel log **non** e' stabile fra boot, quindi appaiare per posizione sarebbe
sbagliato:

| lista | `indexer` d2 (pre-fix) | `indexer` e2 (post-fix) | delta | totale d2 -> e2 |
|---|---|---|---|---|
| 101881 Top 250 Movies | 3586 | **3020** | -16% | 9453 -> **8962** |
| 91378 Latest releases | 3871 | **3466** | -10% | 10049 -> **9827** |
| build_continue_watching | 7099 | **5953** | -16% | 13239 -> **12210** |
| 2194 Latest TV Shows | 1019 | **379** | -63% | 3389 -> **2346** |

Segmenti `import` (1374-1561 -> 1502-1776) e `import pigri` (4464-4586 -> 4333-4750) **piatti**, come
devono essere: la correzione toccava solo il lavoro dell'indexer. Il guadagno e' tutto li' e si
ripete in due boot indipendenti.

**Scomposizione del wall-clock** (avvio Kodi -> ultimo widget consegnato):

| | pre-fase Kodi+skin | widget Fen Light | totale |
|---|---|---|---|
| d2 | 7,1 s | 14,3 s | 21,4 s |
| e2 | **6,2 s** | **13,5 s** | **19,8 s** |

Risponde alla domanda "quanto pesa la skin e quanto Fen Light": **circa 6 s di Kodi+skin prima che il
primo interprete Fen Light parta, e ~13,5 s di widget dopo.** Fen Light resta i due terzi del boot.

Boot pulito: 3 costruzioni, 4 `script aborted` (le 4 invocazioni widget, intenzionale), nessun
SIGSEGV, nessun crash. `requests` ancora importato due volte: 6872 ms (`trakt_api`, servizio) +
4459 ms (`make_session(tmdb)` in `build_continue_watching`).

## Lotto 53 -- la chiamata TMDb all'avvio: e' UNA serie che non finisce mai in cache

### Correzione di un assunto del lotto 52 bis

`watched_indicators` sulla stick vale **1 = Trakt**, non 0. Letto da `settings.db`:
`('watched_indicators','action','0','1')` -- terza colonna il predefinito, quarta il valore reale --
e `watched_indicators_name = 'Trakt'`. La `watched.db` locale ha **0 righe** in tutte e tre le tabelle;
`indicators_dict = {0: 'watched_db', 1: 'trakt_db'}`, quindi tutto passa da `traktcache.db`
(1880 episodi, 38 serie).

Conseguenza: la spiegazione data nel lotto 52 bis per il guadagno misurato **e' sbagliata**. Il ramo
`if watched_indicators == 0` non e' quello preso, quindi spostare l'import di `apis.trakt_api` dentro
di esso non puo' aver prodotto quel miglioramento. **I numeri (-10/-16% sul segmento `indexer`,
riprodotti su due boot) restano validi; la causa attribuita no, ed e' tuttora ignota.**

### Il marcatore `TMDB CALL`

Aggiunto in `get_tmdb`: registra le prime 12 chiamate per interprete con endpoint, `sys.argv[2]`
dell'invocazione e catena dei chiamanti (`sys._getframe`, nessun traceback costruito).
Boot f1 (24/08 01:17) -> **una sola chiamata in tutto l'avvio**:

```
/tv/46298 | da: tvshow_details <- tvshow_meta <- _process <- run <- _worker <- run
```

**46298 = Hunter x Hunter** (da `traktcache.db`: 148 episodi visti, ultimo S3E148). L'intero costo di
`requests` all'avvio -- 4311 ms in questo boot -- si paga per i metadati di **una** serie.

Nota metodologica: la sola finestra temporale **non** basta a dire quale invocazione la fa, perche' le
tre finestre `indexer` si sovrappongono (24,1-30,3 / 24,2-27,8 / 24,2-28,1 s). Il marcatore ora logga
`sys.argv[2]`, che e' per-interprete anche dentro i thread worker.

### Il record non e' scaduto: non c'e' proprio

Interrogato `metacache.db` (13,7 MB) scaricato a Kodi chiuso -- quindi con il WAL gia' consolidato,
e infatti sul device non esiste alcun file `-wal`:

- `SELECT ... WHERE tmdb_id='46298'` -> **nessuna riga**
- `SELECT ... WHERE meta LIKE '%Hunter x Hunter%'` -> **nessuna riga in tutta la tabella**
- ma `season_metadata` contiene `46298_4_it`, con scadenza futura valida

Quindi `episodes_meta` memorizza correttamente, e a fallire e' **solo** `tvshow_meta`. Su 1612 record
totali (349 serie) questa e' l'unica anomalia: le altre 37 serie vanno in cache.

### Dove si perde la scrittura

`metadata.py:677-679` era:
```python
	metacache_set('tvshow', id_type, meta, tvshow_expiry(current_date, meta), current_time)
except: pass
return meta
```
Qualunque eccezione sollevata **prima** di `metacache_set` salta la scrittura in silenzio, e la serie
viene riscaricata a ogni avvio per sempre. Hunter x Hunter e' giapponese, quindi
`_is_anime = original_language in ('ja','ko','zh')` e' vero e attiva il ramo skyhook
(`get_skyhook_season_data`, `get_tvdb_to_tmdb_map`) che le altre serie non percorrono.

Tre `except: pass` potevano nascondere il fatto, tutti e tre ora strumentati:
- `metadata.py` `tvshow_meta` -> `META FALLITA` (tipo ed eccezione)
- `meta_cache.py` `MetaCache.set` -> `CACHE SET FALLITA`
- `meta_cache.py` `MetaCache.get` -> `CACHE SCADUTA` (distingue "mai scritto" da "scritto e scaduto")

**Da misurare al prossimo boot.** L'ipotesi anime/skyhook e' plausibile ma NON dimostrata: entrambe
le funzioni skyhook restituiscono `None`/`{}` sugli errori invece di sollevare, quindi il punto di
rottura va visto, non dedotto.

### L'eccezione, misurata (boot g1, 24/08 01:28)

```
CACHE SET FALLITA###: tvshow tmdb=46298 | TypeError: keys must be str, int, float, bool or None, not tuple
TMDB CALL###: /tv/46298 | inv: ?mode=build_continue_watching |
              da: tmdb_api.py:tvshow_details <- metadata.py:tvshow_meta <- episodes.py:_process <- ...
```

`META FALLITA` **vuoto**: nessuna eccezione in `tvshow_meta`. Il punto di rottura e' `json.dumps`
dentro `MetaCache.set`. `CACHE SCADUTA` vuoto: il record non era scritto-e-poi-cancellato, non veniva
proprio scritto. E `sys.argv[2]` conferma l'invocazione: **`build_continue_watching`**.

L'ipotesi anime/skyhook del paragrafo precedente era giusta come zona ma sbagliata come meccanismo:
non e' una chiamata di rete che fallisce, e'
`get_tvdb_to_tmdb_map` che costruisce `mapping[(seasonNumber, episodeNumber)] = (s, e)` -- un
dizionario con **chiavi tuple**, che JSON non puo' rappresentare. Vale per qualunque anime la cui
numerazione TVDb non coincida con quella TMDb.

### La correzione

Rappresentazione in memoria invariata (tutti i punti di lettura fanno `ep_map.get((s, e))`, sono 8 in
5 file), conversione **solo al confine con la cache**: `"s|e" -> [s, e]`.

- `_pack_ep_maps(meta)` -- ritorna una **copia superficiale**: se mutasse `meta` sul posto, i
  consumatori si ritroverebbero chiavi stringa. Applicata ai 2 `metacache_set('tvshow', ...)` che
  possono contenere le mappe (il terzo scrive una voce `blank_entry`, senza mappe).
- `_unpack_ep_maps(meta)` -- inverso, sul posto (il dizionario viene da `json.loads`, non e'
  condiviso). Applicata al ritorno da cache di `tvshow_meta` e ai risultati `tvshow` di
  `meta_prefetch`, che legge da `get_many` senza passare da `tvshow_meta`.

Verificato fuori da Kodi estraendo le due funzioni dall'AST: `json.dumps` riesce, il dizionario
originale conserva le chiavi tuple, il giro completo e' identico all'originale, il lookup con tupla
funziona, e i casi limite tengono (meta senza mappe, mappe vuote, unpack idempotente su dati gia'
a tuple, meta `None`).

**Attenzione alla verifica:** il primo boot dopo questa correzione fara' **comunque** la chiamata TMDb
(la cache e' vuota, non c'e' nulla da leggere) ma questa volta la scrittura deve riuscire. E' il
**secondo** boot che deve mostrare zero `TMDB CALL` e zero `CACHE SET FALLITA`. Servono due boot.

### Verifica (boot h0 01:37 e h1 01:39): la correzione regge

Marcatori: **zero `CACHE SET FALLITA`, zero `META FALLITA`, zero `CACHE SCADUTA`, zero `TMDB CALL`**.
`PERF REQUESTS` compare **una volta sola** per avvio (`trakt_api`, l'interprete del servizio) invece
di due: l'import di `requests` dentro `build_continue_watching` e' sparito del tutto.

Il record e' in cache, verificato leggendo `metacache.db`:
```
tvshow | Hunter x Hunter | lingua it | scade 2027-02-22 (182 giorni) | 10 KB
tvdb_to_tmdb_ep: 78 voci | chiavi '2|1', '2|2', '2|3', ...
```
78 voci di rimappatura, esattamente il formato impacchettato previsto.

**Errore di misura mio, da non ripetere:** la prima interrogazione ha dato "0 righe" e stavo per
concludere che la correzione non funzionasse. Il database aveva un file **`-wal` da 24 KB** che non
avevo scaricato (nel controllo precedente Kodi era chiuso e il WAL era gia' consolidato, quindi il
solo `.db` bastava; qui Kodi era stato chiuso ma il WAL era rimasto). **Con `journal_mode=wal` vanno
sempre scaricati `.db`, `.db-wal` e `.db-shm` insieme**, oppure il file va letto a Kodi chiuso dopo
aver verificato che il `-wal` non esista.

| `build_continue_watching` | d2 (pre) | e2 (pre) | h0 (post) | h1 (post) |
|---|---|---|---|---|
| segmento `indexer` | 7099 | 5953 | **2056** | **2109** |
| totale | 13239 | 12210 | 10708 | 8658 |

Sul segmento `indexer`, il solo che la correzione poteva toccare: **-65%**.

**Il wall-clock complessivo NON e' migliorato** (23,5 s in h1 contro 19,8 s in e2), e la ragione non
e' la correzione: la stick **si e' riavviata verso le 01:38**, cioe' fra h0 e h1 (`uptime` = 5 min).
h1 e' quindi un avvio a cache del sistema operativo completamente fredda -- si vede nella pre-fase
Kodi+skin, 9,3 s contro 6,2 s, che con Fen Light non c'entra nulla. h0, che precede il riavvio, e' il
confronto piu' onesto. (`ro.boot.bootreason` dice `reboot,adb` e `ro.boot.reboot_mode` dice
`watchdog_reboot`: si contraddicono, e nessun comando di riavvio e' partito da qui. Rimandato con il
resto dell'analisi crash.)

Boot sano: 3 costruzioni, 4 `script aborted` (le invocazioni widget), nessun SIGSEGV.

### Misura pulita a cache calda (boot i1, 24/08 01:45)

Bytecode caldo (`import` 1537-2091 ms, la stessa fascia di e2), sistema operativo caldo (stick attiva
da 8 minuti), nessun riavvio in mezzo. Marcatori diagnostici **tutti a zero**; `PERF REQUESTS` una
sola volta (6850 ms, `trakt_api`, servizio).

Invocazioni appaiate per `list_id` via thread ID:

| | `indexer` e2 | `indexer` i1 | delta | totale e2 | totale i1 |
|---|---|---|---|---|---|
| **build_continue_watching** | 5953 | **1578** | **-73%** | 12210 | **8100** (-34%) |
| 101881 Top 250 Movies | 3020 | 2760 | -9% | 8962 | 8539 |
| 91378 Latest releases | 3466 | 3199 | -8% | 9827 | 9962 |
| 2194 Latest TV Shows | 379 | 363 | -4% | 2346 | 2960 |

Wall-clock, tre boot tutti a bytecode caldo:

| | Kodi+skin | widget Fen Light | totale |
|---|---|---|---|
| d2 (pre-lotto 52) | 7,1 s | 14,3 s | 21,4 s |
| e2 (pre-lotto 53) | 6,2 s | 13,5 s | 19,8 s |
| **i1 (post-lotto 53)** | 6,6 s | **12,2 s** | **18,8 s** |

**Cambio strutturale, piu' importante del numero:** `build_continue_watching` era il palo piu' lungo
dell'avvio (12210 ms contro i 9827 della mdblist peggiore). Ora finisce **per prima** (8100 contro
9962): il percorso critico del boot e' passato a un widget mdblist. Il prossimo lavoro va mirato li',
non piu' su 'continua a guardare'.

Boot sano: 3 costruzioni, 4 `script aborted`, nessun SIGSEGV.

### Stato dei fronti dopo il lotto 53

1. **`import pigri`: 4178-4813 ms per widget**, praticamente identico in tutti gli 8 boot misurati da
   d1 a i1. Mai toccato. E' il singolo costo piu' grosso e piu' prevedibile rimasto.
2. **`requests` del servizio: 6850-8749 ms**, una volta per avvio. E' la sincronizzazione Trakt
   iniziale, costo accettato consapevolmente (lotto 52).
3. **Pre-fase Kodi+skin: ~6,2-7,1 s.** Arctic Fuse, non Fen Light.

## Lotto 54 -- fronte 1: profilare l'albero degli import

### Cosa e' davvero `import pigri`

Guardando `router.py`, il segmento fra `mark_phase('routing_in')` e `mark_phase('indexer_in')`
contiene il parsing dei parametri e **una sola istruzione di import**:

```python
if 'mdblist.' in mode:
    if '.list' in mode:
        from indexers import mdblist_lists      # <-- 4,2-4,8 s
        mark_phase('indexer_in')
```

Quindi i 4,2-4,8 s sono interamente il caricamento dell'albero dei moduli di quell'indexer. Per
potarlo serve sapere quale modulo costa cosa: senza quel dato si potrebbe solo tirare a indovinare,
ed e' il modo in cui in questo progetto si e' gia' sbagliato bersaglio piu' volte.

### Il profilatore

In `fenlight.py`, prima di qualunque import di Fen Light, `builtins.__import__` viene sostituito con
una versione che cronometra ogni caricamento. Misura il tempo **proprio** di ciascun modulo -- al
netto di quelli che importa a sua volta -- tenendo una pila dei tempi figli: altrimenti la radice si
prenderebbe il merito dell'intero albero e il rendiconto sarebbe inutile.

Rendiconto in `kodi_utils.log_import_profile`: totale, quota Fen Light contro quota esterna, e i
primi 22 moduli sopra i 25 ms.

Sicurezza: `reuselanguageinvoker=false` garantisce un interprete nuovo a ogni invocazione (lotto 11c),
quindi la modifica a `builtins` non sopravvive e non puo' contaminare nulla; l'originale viene
comunque ripristinato prima del rendiconto, e `sys.exit(1)` resta l'ultima istruzione del file.

Verificato fuori da Kodi su un albero reale (`email.mime`, `xml.dom`, `unittest`, `http.client`):
95 moduli, somma dei tempi propri **127,4 ms contro 127,5 ms di wall reale, scarto 0,0%**, nessun
tempo negativo, e nessun modulo che monopolizza il totale.

**Nota di misura:** questo deploy NON svuota `__pycache__` -- servirebbe solo a gonfiare il profilo
con la ricompilazione, che e' esattamente cio' che non vogliamo misurare. Rimosso il solo `.pyc` di
`kodi_utils`, l'unico modulo modificato (`fenlight.py` gira come `__main__` e non ha bytecode
memorizzato). Restano 32 `.pyc` caldi.

### Prima misura (boot j1, 24/08 01:51): il fronte 1 non e' dove pensavamo

| invocazione | totale import | di cui Fen Light | resto (libreria standard) | moduli |
|---|---|---|---|---|
| build_continue_watching | 6651 ms | **1547 ms** | **5105 ms** | 109 |
| mdblist 101881 | 6467 ms | 1589 ms | 4878 ms | 111 |
| mdblist 91378 | 6176 ms | 1461 ms | 4714 ms | 111 |
| mdblist 2194 | 2716 ms | 971 ms | 1745 ms | 111 |

**Il 76% del costo degli import NON e' codice Fen Light.** Potare l'albero dei moduli dell'addon --
la cosa che stavamo per fare -- puo' recuperare al massimo ~1,5 s dei ~6,5. Il resto e' la libreria
standard di Python caricata da un interprete ARM 32-bit su flash lenta.

Nessun modulo domina: il piu' caro e' `indexers.movies` a 242 ms, e il costo e' spalmato su 109
moduli. I primi per `build_continue_watching`:

```
242 ms indexers.movies      234 ms (import relativo)   221 ms logging
212 ms decoder (json)       191 ms indexers.episodes   182 ms concurrent.futures
164 ms modules.kodi_utils   163 ms enum                156 ms ipaddress
140 ms nt                   135 ms caches.settings_cache  135 ms _sre
119 ms apis                 117 ms functools           115 ms _compression
110 ms html.entities        103 ms string               96 ms _weakrefset
 96 ms modules.router        94 ms _locale              90 ms modules.dom_parser
```

Due osservazioni che valgono da sole:
- **`nt` costa 140 ms** ed e' il modulo `os` di Windows: su Android l'import **fallisce**, dentro il
  `try/except` di `os.py`. Un import fallito si paga comunque.
- **`ipaddress` (156 ms) e `_compression` (115 ms)** appartengono alla catena `ssl`/`gzip`. Ma in
  questo boot `requests` NON viene importato da `continue_watching`: qualcos'altro tira dentro
  quella catena.

Sapere quanto costa la libreria standard non basta: serve sapere **da dove entra**. Il profilatore ora
registra anche il **richiedente** di ciascun modulo (`sys._getframe(1).f_globals['__name__']`, preso
solo al primo caricamento) e il rendiconto raggruppa per pacchetto di primo livello, indicando il
primo richiedente **esterno** al pacchetto -- senza quel filtro si otterrebbe `email <- email.header`,
cioe' un pacchetto che importa se stesso, che non dice nulla.

Verificato fuori da Kodi: la somma dei gruppi coincide con il totale, e l'attribuzione e' corretta
(`ssl <- http.client`, `socket <- email.utils`).

### La mappa dei richiedenti (boot k1, 24/08 01:55)

`build_continue_watching`: 6098 ms di import, di cui Fen Light 1304 e libreria standard **4795**.
Esterni per pacchetto, con chi li ha tirati dentro:

```
186 ms contextlib  <- traceback      179 ms concurrent <- modules.utils
175 ms decoder     <- json           167 ms nt         <- ntpath
158 ms (relativo)  <- ?              146 ms enum       <- re
141 ms traceback   <- logging        133 ms ipaddress  <- urllib.parse
124 ms html        <- modules.utils  123 ms sqlite3    <- caches.base_cache
110 ms logging     <- concurrent.futures._base   109 ms textwrap <- traceback
104 ms importlib   <- zipfile        103 ms re         <- urllib.parse
```

**Una sola riga di codice spiega la catena piu' costosa.** Ordinando per richiedente invece che per
costo:

```
modules.utils --> concurrent.futures --> logging --> traceback --> contextlib
                                                              --> textwrap
                                                              --> linecache -> tokenize -> token
                                                     logging --> weakref
```

Verificato: `concurrent` compare in **un solo punto** di tutto il codice (`modules/utils.py:12`), e
`logging` e `traceback` non sono importati da nessuna parte a livello di modulo (solo due
`import traceback` dentro gestori di errore). L'intero sottoalbero esisteva per quella riga.

### La correzione: sostituire, non rendere pigro

I tre `make_thread_list*` stanno sul **percorso caldo** (episodes, movies, tvshows, trakt_api): un
import pigro avrebbe solo spostato gli 800-900 ms da `import pigri` a `indexer`. `ThreadPoolExecutor`
e' stato quindi **sostituito** con `_run_pool`, costruito sui soli `threading.Thread` gia' importati.

Semantica preservata, tutta verificata contro l'originale:
- concorrenza limitata a `WORKER_COUNT`, con distribuzione **dinamica** (contatore condiviso sotto
  `Lock`) e non a partizione statica, che con lavori di durata diversa lascerebbe thread fermi;
- la chiamata **blocca** fino al termine, come l'uscita dal blocco `with`;
- le eccezioni del target restano **inghiottite**. Non e' una svista lasciata li': `submit()` le
  depositava in una `Future` che nessun chiamante legge, quindi il comportamento osservabile era gia'
  quello. "Correggerlo" qui avrebbe fatto emergere errori finora invisibili in tutt'altro punto.

Altri tre import resi pigri in `modules/utils.py`, ciascuno con un solo punto d'uso:
`html.unescape` (~230 ms con `html.entities`), `zipfile.ZipFile` (tirava dentro `importlib`, ~100-200
ms), `importlib.import_module`.

**Verifica fuori da Kodi**, 8 gruppi di prove su `_run_pool`: i tre stili di chiamata (item, `*item`,
`(indice, item)`) con accoppiamento indice/elemento corretto, blocco fino al termine, eccezioni non
propagate ma resto della lista elaborato, **risultato identico a `ThreadPoolExecutor` sullo stesso
carico**, picco di concorrenza misurato = 6 = `WORKER_COUNT`, lista vuota, generatore in ingresso,
elemento singolo. Simboli confrontati con `git show HEAD`: nessuno perso, uno aggiunto (`_run_pool`).

Guadagno atteso: **600-900 ms per interprete**, moltiplicato per i 3-4 interpreti dell'avvio. Da
misurare.

### Verifica (boot l1, 24/08 02:01): la catena e' sparita

Nel profilo **non compare piu' nessuno** di `concurrent`, `logging`, `traceback`, `contextlib`,
`textwrap`, `tokenize`, `token`, `linecache`, `html`, `importlib`. Sparito anche **`nt` (167 ms)**:
era `ntpath`, tirato dentro da `zipfile`. Un import che su Android **fallisce** e si pagava comunque.

| | k1 (prima) | l1 (dopo) | delta |
|---|---|---|---|
| moduli caricati | 109-111 | **69-71** | **-40** |
| import totale | 6098-6467 ms | **4660-4819 ms** | **-1400 ms** |
| di cui libreria standard | 4795 ms | **2828 ms** | **-1967 ms** |
| segmento `import pigri` | 4402-4607 ms | **3040-3149 ms** | **-1350 ms** |

Per invocazione: `build_continue_watching` 7997 -> **6511**, mdblist 9379/9688 -> **7935/8202**.

Wall-clock, tutti boot a bytecode caldo:

| | Kodi+skin | widget Fen Light | totale |
|---|---|---|---|
| e2 (pre-lotto 53) | 6,2 s | 13,5 s | 19,8 s |
| i1 (post-lotto 53) | 6,6 s | 12,2 s | 18,8 s |
| j1 (con profilatore) | 6,4 s | 12,0 s | 18,3 s |
| **l1 (post-lotto 54)** | 6,6 s | **10,3 s** | **16,9 s** |

**Un dato che non torna, segnalato e non insabbiato:** la quota attribuita a Fen Light *sale*, da 1304
a 1991 ms, mentre i suoi moduli sono gli stessi. Non e' spiegato dalla modifica. Le cause plausibili
sono la ricompilazione del `.pyc` di `utils` (cancellato prima di questo boot) e la varianza del
dispositivo -- il `load average` era 7,07 al momento della misura. I numeri robusti, che non
dipendono dall'attribuzione, sono gli altri quattro della tabella. Da riverificare a freddo.

Boot sano: 3 costruzioni, 4 `script aborted`, nessun SIGSEGV, zero marcatori di cache fallita.

### Cosa resta nell'albero (l1, `build_continue_watching`)

```
esterni:  json+decoder+encoder 346 | re+_constants+enum+copyreg 446 | sqlite3+datetime+math+calendar 334
          urllib+ipaddress+collections 262 | (relativo) 207 | _locale 110 | threading+_weakrefset 167
Fen Light: indexers.movies 405 | modules.kodi_utils 186 | caches.main_cache 182 |
           caches.settings_cache 148 | apis.trakt_api 144
```

`json`, `re`, `sqlite3` sono strutturali: Fen Light non puo' funzionare senza. I due bersagli residui
plausibili sono `urllib <- modules.kodi_utils` (~170-260 ms, se bastano `parse_qsl`/`quote` si possono
riscrivere a mano) e `indexers.movies` (405 ms, importato a livello di modulo da
`continue_watching.py` ma usato solo dentro `_do_movies`). Rendimenti in calo: siamo passati dal
tagliare 1350 ms al ragionare su 200-400.

## Lotto 55 -- "segna come non visto": Trakt si aggiorna, l'interfaccia no

Sintomi riferiti: su 4 effetti attesi funziona **solo** la scrittura su Trakt. Non spariva il badge
visto dall'episodio, non si ricalcolava 'continua a guardare', non si ricalcolava il badge episodi
rimanenti sulla serie. E nemmeno la sincronizzazione Trakt ogni 30 s rimediava.

### Cronologia dal log (m1, 24/08 02:36)

```
02:36:42.359  INIZIO  build_episode_list                          <- 10,3 s per costruirsi
02:36:47.7    UTENTE  segna come non visto (menu contestuale)
02:36:47.989  INIZIO  watched_status.mark_episode
02:36:49.214  DIAG refresh: MIRATO finestra Video (Container.Refresh) | id=1 azioni=0
02:36:49.689  INIZIO  build_season_list       <- ricostruita la lista STAGIONI, non gli episodi
02:36:52.6    fine    build_episode_list      <- consegnata con i dati letti PRIMA della modifica
02:37:06.277  GUARDIA Trakt: rebuild saltato, la modifica e' nostra ed e' gia' applicata in locale
```

### Difetto 1 -- il ramo "finestra Video" non tocca i widget, ma zittisce chi potrebbe farlo

In `kodi_refresh_ids`, dentro la finestra Video (10025) si esegue `Container.Refresh` e si **esce
subito**, senza mai arrivare a `hold_refresh_flag('fenlight.refresh_widgets')` ne' a
`paginator.refresh_containers_for_ids`. `Container.Refresh` ricarica **solo la cartella aperta**: i
widget della schermata principale non sono raggiungibili da li'.

Il guaio e' che a valle **due** guardie danno per scontato che ci abbiamo pensato noi, entrambe
fondate su `self_mark_recent()`:
- `apis/trakt_api.py:913` -- salta la ricostruzione della cache Trakt
- `service.py:121` -- salta il refresh dell'interfaccia ("la modifica e' nostra ed e' gia' a schermo")

**La loro premessa e' vera per il database e falsa per lo schermo.** Il commento in service.py lo dice
a lettere chiare: "mark_movie/mark_episode scrivono in locale e ricaricano i contenitori toccati". Il
primo pezzo e' vero, il secondo lo e' solo per la cartella aperta. Risultato: le due sole occasioni di
rimediare vengono soppresse, e i widget restano fermi **a tempo indeterminato** -- non fino al
prossimo poll, proprio finche' non succede altro.

**Correzione:** il ramo 10025 ora imposta anche `PENDING_REFRESH_PROP`. E' lo stesso canale gia' usato
per il refresh rimandato durante la riproduzione: `WidgetRefresher` (service.py:166) lo vede entro
10 s, a riproduzione ferma, e lancia `refresh_widgets`. Nessun meccanismo nuovo, nessun rebuild
globale, e l'aggiornamento avviene mentre i widget non sono nemmeno a schermo.

### Difetto 2 -- la ricarica mirata ha colpito il contenitore sbagliato (NON corretto)

`Container.Refresh` alle 02:36:49 ha prodotto un `build_season_list`, non un `build_episode_list`.
Nessuna costruzione della lista episodi e' partita dopo la marcatura: quella a schermo e' rimasta
quella iniziata alle 02:36:42, cioe' **con i dati letti prima della modifica**. Ecco perche' il badge
non spariva.

Causa piu' probabile: al momento della ricarica la cartella che Kodi considerava corrente era ancora
la lista stagioni, perche' la lista episodi lanciata 5 s prima non era stata consegnata. **La lentezza
apre da sola la corsa critica:** `build_episode_list` ha impiegato 10,3 s (e 12,0 s in un'altra
navigazione dello stesso log). Con una costruzione veloce la finestra non esisterebbe.

Non corretto di proposito: e' una corsa critica dipendente dai tempi, e "aggiustarla" a intuito senza
prima misurare e' esattamente il modo in cui in questo progetto si e' gia' sbagliato bersaglio.
Va affrontata come problema a se', e il primo sospetto da verificare e' il costo di
`build_episode_list`.

### Verifica (log n2, 24/08 02:48): funziona, e costa un rebuild globale

```
02:48:18.167  mark_episode
02:48:19      DIAG refresh: MIRATO finestra Video (Container.Refresh) + PENDING_REFRESH_PROP
02:48:27.582  refresh_widgets AVVIATO      <- WidgetRefresher raccoglie il pending, 8 s dopo
02:48:28      DIAG refresh: GLOBALE (UpdateLibrary) | finestra=10025
02:48:29      build_episode_list  (9910 ms)  <- ricostruita DOPO la marcatura: dati aggiornati
02:48:36-42   build_continue_watching + 3 mdblist
```

**Tutti e quattro gli effetti attesi ora avvengono**, difetto 2 compreso: la lista episodi viene
ricostruita alle 02:48:29, dopo la marcatura delle 02:48:18, quindi con i dati giusti. Non e' pero'
"istantaneo": arriva ~11 s dopo, ed e' un effetto collaterale del rebuild globale, non una ricarica
mirata riuscita. La corsa critica del difetto 2 **non e' stata corretta**, e' stata scavalcata.

**Il costo, misurato:** `refresh_widgets` chiama `run_plugin({'mode': 'kodi_refresh'})`
(kodi_utils:674), cioe' `UpdateLibrary` -- globale. Dalla marcatura in poi si contano **7 costruzioni
di cartella**: 2 liste stagioni, 2 liste episodi, 'continua a guardare' e 3 widget mdblist, per circa
40 s di lavoro di fondo cumulativo. Per un episodio segnato come non visto.

E' il compromesso onesto della situazione attuale: prima era 0 lavoro e 0 correttezza, ora e'
correttezza piena a prezzo pieno. La via mirata non e' applicabile cosi' com'e', perche' nella
finestra Video i widget non sono a schermo e nessun `Container.Refresh` puo' raggiungerli --
`UpdateLibrary` e' l'unico canale che li fa rileggere.

Boot e sessione sani: 0 `CACHE SET FALLITA`, 0 `META FALLITA`, 0 `TMDB CALL`, 0 SIGSEGV.

**Prossimo passo indicato dai dati:** `build_episode_list` costa **9,9-11,3 s**. E' insieme (a) la
voce piu' lenta rimasta, (b) la causa della corsa critica del difetto 2 -- con una costruzione veloce
la finestra fra lancio e consegna non esisterebbe -- e (c) meta' del costo del rebuild globale qui
sopra. Un solo bersaglio che chiude tre problemi.

## Lotto 56 -- i 10 secondi della lista episodi sono un'attesa che scade a vuoto

`build_episode_list` era gia' strumentata: `paginator.log_build` separa risoluzione e costruzione.
Nel log n2:

```
PERF###: episodes Season 1 | 3 elementi | totale 0.06s = risoluzione 0.04s + costruzione 20 ms
PERF###: episodes Season 1 | 3 elementi | totale 0.16s = risoluzione 0.15s + costruzione 15 ms
```

**La costruzione della cartella costa 0,06-0,16 s.** L'invocazione intera ne costava 9,9-11,3. Il
segmento `coda` -- cio' che gira DOPO la consegna della lista -- dice dove:

```
build_episode_list | totale 11273 ms | import 243 + import pigri 370 + indexer  61 + consegna 1 + coda 10598 + (set_view 10588)
build_episode_list | totale  9910 ms | import 526 + import pigri 580 + indexer 167 + consegna 2 + coda  8636 + (set_view  8634)
```

**`set_view_mode` da solo vale il 94% dell'invocazione.** Per confronto, nella lista stagioni la
stessa funzione costa 101-287 ms.

### La causa

`_set_view_mode_impl` aspetta che il contenitore dichiari il contenuto atteso, e il limite era a
**iterazioni**:
```python
hold = 0; sleep(100)
while not container_content() == content:
    hold += 1
    if hold < 3000: sleep(1)
    else: return          # <-- si arrende SENZA impostare la vista
```
3000 giri sono "3 secondi" solo dove un giro costa 1 ms. Sulla stick un giro costa ~3,5 ms fra
`sleep`, passaggio Python->C++ per l'infolabel e contesa sul GIL: **10,6 s**. E il ramo che si
raggiunge e' `return`, cioe' la vista **non viene impostata**. Non sono dieci secondi di lavoro: sono
dieci secondi buttati per poi rinunciare.

Nota: nel lotto 50 questa funzione era stata esaminata e archiviata come irrilevante perche' "per i
widget esce subito (is_external)". Vero per i widget, e infatti il costo dei widget non e' questo. La
lista episodi **non e' un widget**: `is_external` e' falso e il corpo gira per intero. L'archiviazione
era corretta nel suo ambito e sbagliata come conclusione generale.

### La correzione

Limite sul **tempo** invece che sui giri (`VIEW_MODE_WAIT_SECONDS = 2.0`), cosi' vale uguale su
qualunque hardware: il caso peggiore passa da "3000 giri, quanto durino dipende dal dispositivo" a
"2 secondi, punto". Due secondi sono larghi: nella lista stagioni l'attesa si chiude in 101-287 ms.

**Perche' il confronto non riesca mai per gli episodi non e' ancora stabilito.** La correzione limita
il danno ma non spiega il difetto, quindi alla scadenza si registra ora il valore osservato:
`DIAG vista: attesa scaduta a 2.0s | Container.Content=... atteso 'episodes' | vista NON impostata`.
Una riga al massimo per invocazione. Se il valore osservato e' diverso da 'episodes' abbiamo anche il
motivo per cui la vista degli episodi non viene mai applicata -- che sarebbe un secondo difetto,
funzionale, nascosto dietro il primo.

Atteso: `build_episode_list` da ~10 s a **~2,2 s**. Da misurare.

### Verifica (log p1, 24/08 13:58): il tetto tiene, e nomina il difetto vero

`set_view` passa da 8634-10588 ms a **2001-2148 ms**, cioe' il tetto. `build_episode_list`:
5460 / 7690 / 2887 ms contro i 9910-11999 di prima. Il 2887 e' il caso a cache calda, dove ormai
**il tetto E' il costo**: indexer 111 ms, coda 2148.

La riga di diagnosi ha risposto, 3 volte su 3, sempre la stessa cosa:
```
DIAG vista: attesa scaduta a 2.0s | Container.Content='seasons' atteso 'episodes' | vista NON impostata
```

### Perche' non puo' funzionare

Nel log, subito prima dell'invocazione:
```
CDirectoryProvider[plugin://plugin.video.fenlight/?mode=build_episode_list&season=1&tmdb_id=298168]: refreshing
```

La lista episodi **non e' il contenitore della finestra**: e' un pannello della skin caricato da un
`CDirectoryProvider` (Arctic Fuse mostra gli episodi accanto alle stagioni). Il contenitore principale
e', e resta, la lista stagioni. `Container.Content` **non diventera' mai 'episodes'**: l'attesa non e'
lenta, e' impossibile. Prima costava 10,6 s per arrendersi, ora 2, ma resta un'attesa che non puo'
riuscire.

Ne discendono due cose:
1. **La vista degli episodi non viene mai applicata.** Difetto funzionale finora invisibile perche'
   nascosto dietro quello di prestazioni. A schermo si vede la vista predefinita della skin, che a
   quanto pare va bene: l'utente non se n'era accorto.
2. **E' la stessa causa del difetto 2 del lotto 55.** `Container.Refresh` ricarica il contenitore
   principale -- le stagioni -- ed e' esattamente cio' che il log mostrava: `build_season_list` al
   posto di `build_episode_list`. Non era una corsa critica sui tempi: era il contenitore sbagliato,
   sempre.

`external()` non se ne accorge: `'fenlight' not in Container.PluginName` e' **falso**, perche' il
contenitore principale e' comunque una lista Fen Light (le stagioni). La funzione distingue
"widget di un'altra skin" da "nostra finestra", ma non "pannello caricato da un provider" da
"contenitore della finestra". Correggerla ha pero' un raggio d'azione ampio -- decide anche
`cacheToDisc`, i menu contestuali, `set_view_mode` -- e non va toccata di corsa dentro un lotto sulle
prestazioni.

### Cosa e' stato fatto e cosa no

Tetto abbassato a **1,0 s**: ogni attesa andata a buon fine misurata finora (5 campioni, liste
stagioni) si e' chiusa entro 229 ms di `coda`, cioe' meno di 130 ms di ciclo dopo il settle da 100 ms.
Un secondo lascia un margine di 8x. Non si scende oltre perche' il caso della navigazione in avanti su
un contenitore di finestra vero, dove il cambio puo' tardare legittimamente, non e' ancora stato
misurato in isolamento.

**Non corretto:** il riconoscimento dei pannelli `CDirectoryProvider`. E' la correzione giusta -- farebbe
uscire subito `set_view_mode` e chiuderebbe anche il difetto 2 del lotto 55 -- ma passa da `external()`,
che e' usata ovunque. Va affrontata da sola, con la sua verifica.

## Lotto 57 -- non e' un bug della skin: e' la vista "Combined" di Arctic Fuse

Domanda posta dall'utente: quel comportamento e' voluto o e' un difetto della skin? Risposta letta
nella skin, `1080i/Includes_Views_Combined.xml`:

```xml
<variable name="View_530_Content">
    <value condition="... !String.IsEmpty(Container(520).ListItem.FolderPath) + Container(520).ListItem.IsFolder">
        $INFO[Container(520).ListItem.FolderPath]
    </value>
</variable>
```

Il contenitore **52X e' la lista della finestra** (le stagioni); il contenitore **53X e' un pannello
affiancato** il cui contenuto e' il `FolderPath` dell'elemento **a fuoco**. Mettendo a fuoco una
stagione, 53X carica `build_episode_list` per quella stagione. E' il funzionamento previsto della
vista Combined, non un difetto: percio' all'uso sembra tutto corretto, e lo e'.

**Correzione di una mia formulazione ambigua del lotto 56:** avevo scritto "il contenitore resta sulle
stagioni" in un modo che si poteva leggere come "gli episodi non vengono mostrati". Non e' cosi'. Gli
episodi vengono costruiti e consegnati regolarmente (`9 elementi` nel log) e si vedono. Cio' che non
avviene e' l'applicazione della **vista** da parte di Fen Light, che e' tutt'altra cosa e non ha
effetti visibili qui.

### Cosa ne discende, ora su basi solide

1. **`Container.Content='seasons'` e' il valore GIUSTO.** Il contenitore della finestra e' davvero la
   lista stagioni. `set_view_mode('view.episodes', 'episodes')` non e' "in attesa di un cambio che
   tarda": sta aspettando una condizione che in questa vista non deve verificarsi. Di piu':
   `Container.SetViewMode` agisce sul contenitore ATTIVO, quindi se l'attesa riuscisse imporrebbe la
   vista episodi al contenitore delle **stagioni**. Che fallisca e', in questa vista, la cosa giusta;
   sbagliato e' solo che ci metta un secondo a scoprirlo.

2. **Il pannello 53X non e' raggiungibile dai nostri meccanismi mirati.** `Container.Refresh` agisce
   sul contenitore della finestra (le stagioni) -- ed e' esattamente cio' che il log del lotto 55
   mostrava. Il paginatore non aiuta: `WIDGET_CONTAINER_IDS = range(500, 521)` non arriva a 53X, e
   soprattutto il suo meccanismo funziona alterando il **percorso** del contenitore con un token,
   mentre il percorso di 53X e' dettato dal `FolderPath` dell'elemento a fuoco e non e' modificabile
   dall'esterno. Il paginatore infatti esce con `return 0` dentro la finestra 10025.

3. **Quindi il "martello globale" del lotto 55 non e' una reazione sproporzionata: e' l'unico
   attrezzo disponibile.** `UpdateLibrary` produce l'annuncio che i `CDirectoryProvider` ascoltano, ed
   e' per questo che alle 02:48:29 la lista episodi si e' davvero ricostruita. Sostituirlo con una
   ricarica mirata, come si era ipotizzato, **non e' possibile** con i meccanismi presenti.

### Conseguenza sul piano di lavoro

L'idea di "correggere `external()` per riconoscere i pannelli e tornare al mirato" **cade**: la meta'
"tornare al mirato" non ha un bersaglio raggiungibile. Resta in piedi solo la parte prestazionale --
riconoscere il caso pannello per uscire subito da `set_view_mode` invece di scoprirlo dopo 1 s -- che
vale 1 secondo per apertura di stagione e non sblocca nient'altro.

Da verificare separatamente, perche' discende dalla stessa classificazione errata: in `episodes.py`
`end_directory(handle, cacheToDisc=False if is_external else True)`. Per il pannello `is_external` e'
falso, quindi la cartella viene messa in cache su disco. Se Kodi la servisse dalla cache al posto di
rileggerla, sarebbe una seconda sorgente di dati vecchi -- ma il log del lotto 55 mostra che dopo
`UpdateLibrary` la ricostruzione avviene davvero, quindi il sospetto **non e' confermato** e va
misurato prima di toccare qualcosa.

### Lotto 57 bis -- risolto, non limitato

Obiezione dell'utente, corretta: un comportamento che sappiamo sbagliato non va limitato, va tolto. Il
tetto era un ripiego presentato come se la soluzione non esistesse, quando semplicemente non era stata
cercata.

**Pista 1, caduta.** `Window.Property(TMDBHelper.WidgetContainer)` -- la proprieta' con cui la skin
distingue i propri pannelli -- nella skin viene solo **letta**, in 7 file, e mai impostata: la
scriveva TMDbHelper, rimosso. Quelle condizioni sono sempre false, il segnale e' morto.

**Il dato che ha chiuso la questione.** Distribuzione di `set_view` su tutti i log raccolti:

| modo | campioni | min | max |
|---|---|---|---|
| `build_season_list` | **19** | 100 ms | 287 ms |
| `build_episode_list` | 7 | 2001 ms | 10588 ms |

Il minimo di 100 ms **e' il `sleep(100)` iniziale**: in 19 casi su 19 il contenuto era gia' corretto
al primo controllo, e il massimo oltre il settle e' 187 ms. Gli episodi falliscono 7 volte su 7.
**L'attesa non e' mai servita, in nessun campione.** Non e' un meccanismo che a volte aiuta: e' un
costo fisso che paga una domanda alla quale non puo' rispondere.

**Correzione, due parti:**
1. `VIEW_MODE_WAIT_SECONDS` da 1,0 a **0,3 s** -- 1,6x il caso piu' lento mai osservato oltre il
   settle, invece di un numero scelto a occhio.
2. **Il caso irraggiungibile si impara.** Alla prima scadenza il contenuto viene marcato in una
   proprieta' di finestra; dalle volte successive `set_view_mode` esce dopo il solo settle. Poiche' il
   segnale a priori non esiste, lo si ricava dal primo tentativo e non lo si ripaga mai piu'.
   **Si auto-corregge:** il controllo del contenuto avviene comunque prima di guardare il marchio,
   quindi se un giorno gli episodi diventassero il contenitore della finestra (altra vista, altra
   skin) il caso buono passerebbe e il marchio verrebbe tolto. Nessun rischio di blocco permanente.

Verificato fuori da Kodi con 7 scenari sulla funzione estratta dall'AST: contenuto gia' giusto (105 ms,
vista impostata), primo fallimento (405 ms, impara), secondo e terzo (100-105 ms, salta), caso buono
che continua a funzionare con il marchio attivo, auto-correzione quando il contenuto torna
raggiungibile (marchio rimosso, vista impostata), e ritorno alla normalita'.

`set_view` per `build_episode_list`: **10588 -> 2001 -> ~100 ms** dalla seconda apertura in poi. I
100 ms residui sono il settle, tenuto apposta: e' cio' che rende possibile l'auto-correzione.

## Lotto 58 -- la sincronizzazione Trakt CONSUMA i cambiamenti remoti e li butta

Log q1, 24/08 14:20-14:25.

```
14:21:12  rebuild completo, motivo: nessun play piu' recente del piu' recente locale (rimozioni?)
14:21:14  watched episodes rebuild: 33 shows, 1287 history plays, 1275 episodes   <- all'avvio i dati SI sincronizzano
14:21:15  TraktMonitor: refresh saltato, interfaccia ricostruita 16.9s fa
14:21:46  Update Success. No Changes Needed
14:22:16  Update Success. No Changes Needed
14:24:40  watched episodes: rebuild saltato, la modifica e' nostra ed e' gia' applicata in locale
14:24:40  TraktMonitor: refresh saltato, la modifica e' nostra ed e' gia' a schermo
14:25:16  (identico)
```

Le righe delle 14:24:40 e 14:25:16 arrivano dal ramo `status == 'success'`, cioe' **Trakt aveva
davvero dei cambiamenti**. Sono stati scartati due volte: prima il rebuild dei dati
(`trakt_api.py:913`), poi il refresh dell'interfaccia (`service.py:121`). Entrambe le guardie
poggiano su `self_mark_recent()`, valido **120 secondi** e riarmato da ogni marcatura locale.

### Perche' il cambiamento non torna mai piu'

`trakt_sync_activities` chiama `reset_activity(latest)` (riga 1101). Quella funzione, in
`caches/trakt_cache.py:115`, legge i timestamp precedenti **e subito li sovrascrive con quelli
nuovi**. Il segnalibro "visto fino a qui" avanza PRIMA che il lavoro a valle venga fatto.

Se il rebuild viene poi saltato dalla guardia, il cambiamento e' **consumato e perso**: al giro dopo
`_compare(latest, cached)` trova i due valori uguali e restituisce `'not needed'`. Per sempre. E'
esattamente la sequenza dei log: due 'success' scartati alle 14:24-14:25, e prima due
'No Changes Needed'.

### Perche' colpisce proprio le modifiche fatte dall'app Trakt

La condizione della guardia e' `not new_plays and last_synced and self_mark_recent('tvshow')`.
`not new_plays` significa "nessuna riproduzione piu' recente di quella gia' nota in locale", cioe'
proprio il caso delle **rimozioni** -- segnare come NON visto dall'app Trakt non produce nessun play
nuovo. E il log delle 14:21:12 lo dice a chiare lettere: *"nessun play piu' recente del piu' recente
locale (rimozioni?)"*. Quindi lo scenario piu' comune dell'utente e' anche quello che la guardia
inghiotte meglio.

Basta una marcatura locale per aprire una finestra di 120 s in cui qualunque modifica remota viene
letta, marcata come vista e cestinata. Chi sta provando le cose sulla stick -- cioe' quello che stiamo
facendo da due giorni -- tiene quella finestra quasi sempre aperta.

### Correzione di un mio errore (lotto 57)

Avevo scritto che la proprieta' con cui la skin marca i propri pannelli "non e' piu' scritta da
nessuno". **Falso, ed e' colpa di una mia ricerca sbagliata:** avevo cercato `TMDBHelper` con la B
maiuscola, ma la skin la SCRIVE come `TMDbHelper` (b minuscola) e la LEGGE come `TMDBHelper` -- le
proprieta' di finestra di Kodi sono insensibili alle maiuscole, quindi funziona. Ci sono **22 punti**
che la impostano, fra cui proprio il pannello della vista Combined:

```xml
<onfocus>SetProperty(TMDbHelper.WidgetContainer,53$PARAM[id])</onfocus>
```

Il segnale deterministico che avevo dichiarato inesistente **esiste**. La soluzione del lotto 57 bis
(impararlo al primo tentativo) funziona ed e' verificata, ma poggiava su una premessa sbagliata: si
puo' sapere *prima*, leggendo quella proprieta'. Da rifare come si deve.

### Lotto 58 bis -- la guardia diventa un rinvio, non un cestino

La guardia del lotto 47 non viene rimossa: il problema che risolveva e' reale (una marcatura locale
faceva ripartire un rebuild da 6 pagine e 1275 episodi, ~1,5 s, per un dato gia' esatto in locale).
Cambia cio' che comporta saltarlo.

**Perche' non si e' verificata l'affermazione della guardia.** L'idea piu' pulita sarebbe confrontare
l'istante dell'attivita' Trakt (`latest['episodes']['watched_at']`, UTC) con quello della nostra
marcatura (`time.time()`). Scartata: mescolare i due orologi richiede una conversione UTC/locale
esplicita, e `_get_timestamp` usa gia' `time.mktime` su un orario UTC -- un errore che oggi si annulla
perche' confronta Trakt con Trakt, ma che si manifesterebbe appena introdotto il nostro orologio.
Troppo fragile per il difetto piu' grave aperto.

**Correzione, tre pezzi:**
1. `caches/trakt_cache.py` -> nuova `restore_activity(previous)`: rimette il segnalibro al valore
   precedente.
2. `apis/trakt_api.py` -> `_SYNC_DEFERRED`, alzato dalle due guardie (film ed episodi) quando saltano
   una ricostruzione, azzerato subito dopo `reset_activity`.
3. In fondo a `trakt_sync_activities`, se il flag e' alzato il segnalibro **torna indietro**. Il giro
   successivo ritrova il cambiamento invece di 'not needed'.

`TRAKT_SELF_MARK_SECONDS` da 120 a **45 s**: ora la costante non decide piu' *cosa si perde* ma solo
*quanto si aspetta*, e a 45 s si conserva l'accorpamento di piu' marcature consecutive -- il motivo per
cui la guardia esiste -- dimezzando abbondantemente il caso peggiore.

**Verifica per simulazione** della macchina a stati (marcatura locale a t=0, modifica dall'app Trakt a
t=10, poll ogni 30 s):

| | esito |
|---|---|
| prima (guardia = cestino) | **mai applicata, persa** |
| dopo, finestra 120 s | applicata a t=120 |
| **dopo, finestra 45 s** | **applicata a t=60** |

Il messaggio di log cambia di conseguenza, da "rebuild saltato ... gia' applicata in locale" a
"rebuild RIMANDATO ... segnalibro attivita' NON avanzato": la vecchia dicitura affermava una cosa che
il codice non verificava.

**Costo accettato:** dopo una marcatura locale la ricostruzione non e' piu' evitata, solo rinviata di
al massimo 45 s. Si perde parte del guadagno del lotto 47 e si riprende la correttezza. Non e' un
compromesso alla pari: quel guadagno valeva ~1,5 s di lavoro di fondo, il difetto costava la perdita
silenziosa e definitiva di modifiche fatte dall'utente.

## Lotto 59 -- refresh MIRATO dopo la sincronizzazione Trakt

Verifica del lotto 58 bis sul dispositivo (log r1): i `rebuild RIMANDATO` si ripetono e poi il lavoro
viene **ripreso** -- `sync/watched/movies: 600 elementi` alle 14:57:56, `599` alle 14:59:29 (cioe' la
rimozione arrivata), rebuild episodi alle 15:00:04. Nessun cambiamento piu' perso.

### Il limite dell'API, e cio' che invece dipende da noi

`sync/last_activities` restituisce solo marche temporali **per categoria** (`movies.watched_at`,
`episodes.watched_at`, `shows.hidden_at`, ...). Non dice mai QUALI titoli sono cambiati: per saperlo
bisogna scaricare l'insieme completo e confrontarlo, che e' il `rebuild completo`. Questa meta' non e'
migliorabile.

**Ma dopo la ricostruzione l'elenco ce l'abbiamo**, e finora veniva buttato: si chiamava
`refresh_widgets` -> `kodi_refresh` -> `UpdateLibrary`, cioe' ogni widget della schermata a
prescindere da quali titoli fossero cambiati e dal fatto che fossero presenti.

### Correzione

1. `caches/trakt_cache.py`: `_watched_keys` + `_changed_media_ids` calcolano la differenza fra
   l'insieme prima e quello dopo. `set_bulk_movie_watched` / `set_bulk_tvshow_watched` /
   `add_tvshow_watched` restituiscono ora i media_id toccati. Costo: una SELECT sulla tabella che si
   sta comunque per riscrivere.
2. `apis/trakt_api.py`: `trakt_sync_activities` raccoglie gli id dalle due ricostruzioni e li pubblica
   in `fenlight.trakt.changed_ids`. **Tre stati distinti, e servono tutti e tre:** `''` = non lo
   sappiamo (globale, come prima), `'-'` = lo sappiamo e non e' cambiato nulla (nessuna
   ricostruzione), altrimenti l'elenco.
3. `modules/router.py`: nuovo modo `kodi_refresh_ids`.
4. `service.py`: il monitor legge la proprieta' e sceglie fra mirato, niente e globale.

**Perche' la distinzione fra `''` e `'-'` non e' pedanteria:** un insieme vuoto trattato come
"sconosciuto" farebbe partire un rebuild globale proprio nel caso in cui si e' dimostrato che non
serve, cioe' quello piu' frequente.

**Normalizzazione dei tipi:** le chiavi vengono confrontate come stringhe perche' dal database
stagione ed episodio arrivano INTEGER e dalla lista da inserire spesso come stringa. Senza, ogni riga
risulterebbe cambiata e il mirato degenererebbe in un globale piu' costoso.

Verificato fuori da Kodi su SQLite in memoria, 7 casi: nessun cambiamento -> `set()`; rimozione di un
episodio -> solo la sua serie; aggiunta -> solo il nuovo titolo; azzeramento -> tutti; **stessi dati
con stagione/episodio come stringhe -> `set()`** (il caso che senza normalizzazione fallirebbe); riga
malformata -> `None` (ricaduta sul globale); db_type diverso che non interferisce.

Nota: dentro la finestra Video `refresh_containers_for_ids` esce con `return 0` e `kodi_refresh_ids`
ricade da sola sul globale. Il mirato agisce quindi dove ha senso, cioe' sulla schermata principale.

### Marcatore per 'continua a guardare' (difetto aperto)

Segnalato: una serie con **un solo** episodio visto, tolto il visto, continua a mostrare l'episodio
successivo invece di sparire. 'Continua a guardare' fonde TRE sorgenti (film in pausa, episodi in
pausa, prossimo episodio) e a schermo sono indistinguibili. Aggiunto in `build_continue_watching` un
marcatore che stampa quante voci arrivano da ciascuna e con quali id e S/E. Nel log r1 non c'e' nessuna
marcatura di episodi -- solo film -- quindi l'evento non era osservabile. **Da riprodurre.**

## Lotto 60 -- il refresh mirato funziona, ma lo degradavamo noi

Verifica del lotto 59 sul dispositivo (log s1). Sulla schermata principale funziona come voluto:
```
15:16:17  titoli cambiati: 1 -> ['1297842']
15:16:17  TraktMonitor: refresh MIRATO su 1 titoli
15:16:18  DIAG refresh: MIRATO 2 contenitori ricaricati | finestra=10000
```
**Due contenitori** invece dell'intera schermata. Ripetuto piu' volte nel log con 1, 2 e 3 titoli.

### Il difetto: gli id venivano buttati nella finestra Video

```
15:19:00.72  TraktMonitor: refresh MIRATO su 1 titoli          <- gli id li avevamo
15:19:01.12  DIAG refresh: MIRATO finestra Video (Container.Refresh)
15:19:01     refresh_widgets avviato                            <- il PENDING del lotto 55
15:19:03.15  DIAG refresh: GLOBALE (UpdateLibrary) | finestra=10025
```

Il ramo aggiunto nel lotto 55 alzava la bandiera del rinvio **senza portarsi dietro gli id**, e
`WidgetRefresher` rispondeva con `refresh_widgets`, cioe' `UpdateLibrary`. Un refresh mirato su UN
titolo diventava una ricostruzione di tutto, solo perche' l'utente si trovava dentro la finestra
Video. L'informazione c'era: la buttavamo noi.

**Correzione:**
1. `PENDING_IDS_PROP`: il rinvio porta con se' gli id.
2. `WidgetRefresher` li usa (`kodi_refresh_ids`) e ricade sul globale solo quando non ci sono.
3. Il rinvio si **tiene** finche' si e' dentro la finestra Video: li' i widget non sono a schermo,
   quindi ricostruirli non mostra nulla a nessuno, e la ricarica mirata non raggiungerebbe comunque i
   contenitori (`refresh_containers_for_ids` esce con `return 0`). Si aspetta di essere tornati dove i
   widget si vedono.
4. `_defer_refresh_if_playing` azzera gli id: quel rinvio non ne porta, e senza l'azzeramento
   erediterebbe quelli di un rinvio precedente ricaricando i contenitori del titolo **sbagliato**.

Verificato fuori da Kodi con la macchina a stati, 5 casi: rinvio in finestra Video che conserva gli id;
refresher che tiene il rinvio finche' si e' in 10025; refresher che a schermata principale esegue il
mirato con quegli id; mirato immediato quando si e' gia' in home; e il caso 4, cioe' un rinvio senza id
dopo uno con id, che deve dare GLOBALE e non riusare i vecchi.

### Cosa NON dipende da noi (chiusura del player)

Dopo la chiusura, alle 15:19:40-43 si ricostruiscono `build_continue_watching` e due widget mdblist.
Non li ordiniamo noi: alla stessa ora `player.py` registra *"DIAG refresh: NON ordinato, Kodi ha gia'
ricostruito da sola 10.6s dopo la chiusura"*. E' Kodi che rilegge i widget rientrando nella schermata
principale, e lo fa perche' le cartelle dei widget vengono consegnate con `cacheToDisc=False` quando
`is_external` -- quindi non esiste una copia da servire e vanno ricostruite.

E' lo stesso compromesso del lotto 50: con la cache attiva Kodi le servirebbe vecchie. Ridurre questa
ricostruzione e' un lavoro a se', che tocca la cache delle cartelle e non il percorso di refresh.

## Lotto 61 -- la tempesta di ricostruzioni dopo il player: TRE ondate, non una

Log t1, 24/08 16:06. Il player chiude alle 16:06:11.

```
16:06:12.439  Window Init (Home)
16:06:12      CDirectoryProvider x4 -> continue_watching + 3 mdblist          <- ONDATA 1 (Kodi)
16:06:13      CDirectoryProvider x4 -> gli stessi quattro, di nuovo           <- ONDATA 2 (Kodi)
16:06:25.819  build_continue_watching chiude (11886 ms)
16:06:26.171  DIAG refresh: nessuna ricostruzione spontanea entro 14s, la ordiniamo noi
16:06:26.371  DIAG refresh: MIRATO 2 contenitori ricaricati                   <- ONDATA 3 (nostra)
```

`build_continue_watching` viene costruita **tre volte** (16:06:25, 16:06:30, 16:06:33), le mdblist due
o tre volte ciascuna.

### Difetto 1 -- il rilevatore manca per 352 ms (corretto)

`kodi_rebuilt_by_itself` cicla `while _now() < deadline` e controlla **solo prima** di dormire 500 ms.
La ricostruzione e' arrivata alle 16:06:25.819, la scadenza e' caduta alle 16:06:26.171: 352 ms di
scarto, e un'ondata intera ordinata per niente. Aggiunto un **ultimo controllo dopo la scadenza**.
Da solo elimina l'ondata 3.

### Difetto 2 -- le ondate 1 e 2 sono di Kodi, e nascono da `cacheToDisc`

I widget escono con `cacheToDisc=False` (`False if is_external else True`), quindi Kodi non ha nessuna
copia da servire e **ri-invoca il plugin** ogni volta che la schermata principale torna in primo piano.
Non e' un difetto di Fen Light: e' la conseguenza diretta di quella scelta.

**Esperimento controllato (lotto 61), NON una correzione adottata:** cambiato `cacheToDisc=True` per
**il solo** `build_continue_watching`. Gli altri tre widget restano com'erano e fanno da gruppo di
controllo nello stesso log. Se al rientro in Home mancano le invocazioni di 'continua a guardare' e ci
sono quelle delle mdblist, la cache fa quel che speriamo e si puo' estendere.

**Rischio noto, da tenere presente prima di estendere:** con la cache attiva una ricostruzione ordinata
via `UpdateLibrary` **non basta piu'** a rinfrescare il widget, perche' l'URL non cambia e Kodi
servirebbe la copia. Tutta l'invalidazione dovrebbe passare dal nonce del paginatore
(`RELOAD_PARAM`), che invece cambia il percorso e quindi supera la cache -- verificato leggendo
`refresh_containers_for_ids`. Oggi pero' diversi percorsi usano ancora `kodi_refresh` globale come
ripiego: estendere la cache senza prima convertirli significherebbe widget che non si aggiornano piu',
cioe' la stessa classe di difetto appena chiusa nei lotti 55-60. Per questo si misura un widget solo.

### Lotto 61 bis -- esito: una correzione confermata, un'ipotesi smentita

Log u1, 24/08 16:24-16:25 (film riprodotto e interrotto a meta').

**Confermato -- il controllo finale funziona.** Alle 16:25:05.367:
`DIAG refresh: NON ordinato, Kodi ha gia' ricostruito da sola 8.0s dopo la chiusura`.
La terza ondata, quella nostra, e' sparita.

**Smentito -- `cacheToDisc=True` non ha alcun effetto.** `build_continue_watching` aveva la cache
attiva e gli altri tre widget no; al rientro in Home e' stata **ri-invocata come loro** (16:25:05 e
16:25:09). Un `CDirectoryProvider` che si aggiorna rilegge la sorgente e scavalca la cache delle
cartelle. Modifica **revocata**: teneva un rischio di dati vecchi senza dare niente in cambio.

**Cosa fa scattare davvero le ricostruzioni.** Ogni ondata segue un cambio di finestra, a millisecondi:
```
16:24:58.278  Window Init (Home.xml)
16:24:58.281  CDirectoryProvider x4: refreshing          <- 3 ms dopo
16:24:59.166  Window Init (Custom_1182_Dialog_Topmenu_Overlay.xml)
16:24:59.430  CDirectoryProvider x4: refreshing
```
Nessuna delle due parte da noi. Uscendo dal player la schermata principale viene riattivata, e Kodi
rilegge i propri provider; l'overlay del menu della skin la riattiva una seconda volta.

### Il limite vero, che non e' un difetto di Fen Light

La richiesta ragionevole -- "metti il badge al film nei widget in cui compare, senza toccare il resto"
-- **non e' esprimibile nel modello dei widget di Kodi**. Un widget e' una *directory*: il plugin la
consegna intera e Kodi la rilegge intera. Non esiste un'API per modificare un singolo elemento di un
contenitore gia' costruito, ne' dal plugin ne' dalla skin. Quando Kodi decide che un provider va
riletto, l'unica cosa che il plugin puo' fare e' ricostruire tutta la lista.

Cio' che controlliamo:
- **le nostre ricariche**, ora mirate ai soli contenitori interessati (lotto 59-60, verificato:
  2 contenitori invece di tutta la schermata) e non piu' duplicate (questo lotto);
- **il costo di ogni ricostruzione**, che e' il filo conduttore dei lotti 50-56.

Cio' che NON controlliamo dal plugin: la rilettura dei provider alla riattivazione della finestra.
L'unica leva sarebbe nella skin (attributo `refreshinterval` sul nodo `<content>`, o meno transizioni
di finestra), non in Fen Light.

## Lotto 62 -- due affermazioni da rettificare

### 1. "Si puo' correggere dalla skin": RITIRATA

Nel lotto 61 bis avevo indicato l'attributo `refreshinterval` sul nodo `<content>` come leva per
impedire a Kodi di rileggere i provider alla riattivazione della finestra. **Verificato: in tutta la
skin `refreshinterval` non compare mai**, e non e' stato accertato che Kodi lo supporti per i
`CDirectoryProvider`. Era una supposizione presentata come una via praticabile.

Stato reale: **non e' noto un modo affidabile, ne' dal plugin ne' dalla skin,** per evitare la
rilettura dei provider quando la finestra torna in primo piano. Cio' che resta dimostrato e' solo che
la causa non e' nostra e non e' `cacheToDisc` (misurato nel lotto 61 bis).

### 2. `TMDbHelper.WidgetContainer`: il candidato ha un difetto strutturale

Il ciclo di vita della proprieta', letto nella skin:
```
Includes_Views_Combined.xml:116  <onfocus>SetProperty(TMDbHelper.WidgetContainer,53X)</onfocus>   pannello
Includes_Views_Combined.xml:166  <onfocus>ClearProperty(TMDbHelper.WidgetContainer)</onfocus>     lista principale
```
piu' altri 7 `ClearProperty` sulle viste normali (Row, List, Wall, DialogInfo).

**Segue il FUOCO, non chi sta costruendo.** E il pannello episodi si ricarica proprio quando cambia
l'elemento a fuoco nella lista stagioni -- cioe' mentre il fuoco e' su 52X, dove la skin la cancella.
Nel momento in cui servirebbe potrebbe quindi essere vuota, e in tal caso non distingue un pannello da
un contenitore di finestra.

Non si deduce: si misura. Aggiunto il valore osservato alla riga `DIAG vista`, che grazie al marchio
del lotto 57 bis esce **una sola volta per sessione** -- un campione, che e' quanto basta per decidere
se questo ramo e' percorribile o va chiuso.

Se esce `'530'` il candidato regge e `set_view_mode` (e probabilmente il menu contestuale) si possono
sistemare all'origine. Se esce vuota, l'unico modo di sapere che l'attesa e' inutile resta scoprirlo
provando -- cioe' il marchio che gia' abbiamo.

---

## Lotto 63 -- `TMDbHelper.WidgetContainer`: verdetto (24/08)

Misura eseguita, un campione, log della sessione delle 16:37.

```
16:37:51.160  DIAG vista: attesa scaduta a 0.3s | Container.Content='seasons' atteso 'episodes'
              | WidgetContainer='' | vista NON impostata | 'episodes' marcato irraggiungibile
```

**Vuota.** Il difetto strutturale ipotizzato nel lotto 62 e' reale: al momento in cui il pannello
episodi si costruisce il fuoco e' ancora sulla lista stagioni (52X), che la cancella. La proprieta'
segue il fuoco, non chi costruisce.

**Ramo chiuso per `set_view_mode`.** Non esiste, dal plugin, un modo di sapere quale contenitore sta
ricevendo la cartella che si sta consegnando. Il marchio "irraggiungibile" del lotto 57 bis resta
l'unica soluzione, e funziona: `set_view` 459 ms alla prima costruzione di `build_episode_list` della
sessione (100 ms di sleep + 300 ms di attesa + contorno), poi ~100 ms per tutte le successive.

**Ma la proprieta' NON e' morta.** La riga 116 la imposta a `53X` quando il pannello prende il fuoco:
e' vuota al momento della *costruzione*, e valorizzata al momento dell'*interazione*. Se un problema
si manifesta mentre l'utente e' fermo sul pannello -- il menu contestuale, per esempio -- li' la
proprieta' e' leggibile e discrimina. Va tenuta a mente per quel fronte, non per questo.

### Boot della stessa sessione

16:37:13.729 avvio Kodi -> 16:37:30.187 ultimo widget della home consegnato = **16.5 s**, in linea con
il migliore misurato finora. Nessun errore, nessuna cache fallita, nessuna chiamata di rete nei quattro
widget (`verdetto in cache 20` su tutti i lotti DUB, `54/54 gia' in cache` nei prefetch).

Trakt: `titoli cambiati: 0` dopo l'azzeramento di un segnalibro, e refresh saltato perche' l'interfaccia
era stata ricostruita 25.2 s prima. Comportamento corretto: nessuna ricostruzione sprecata.

---

## Lotto 64 -- Menu contestuale nella vista Combined: due difetti distinti (24/08)

Log delle 16:49. Il menu contestuale sul pannello episodi **e' quello giusto**: alla scelta
dell'utente e' partito

```
16:49:34.228  mark_episode&action=mark_as_watched&tmdb_id=283297&season=1&episode=2
```

cioe' l'episodio a fuoco, non la stagione ne' la serie. Quello che e' sbagliato sono altre due cose.

### 1. L'intestazione mostra la serie invece dell'episodio

L'header e' `$VAR[DialogContextMenu_HeaderLabel]` = `Window(Home).Property(TMDbHelper.ListItem.base_label)`
(Dialog_DialogContextMenu.xml:5). Quella proprieta' la pubblichiamo **noi**, in `blur_service.py`:

```python
label = self._resolve('Label', container=last_container)
```

e `_resolve` provava per primo `ListItem.Label` "nudo". Da un widget della home quello e' l'elemento a
fuoco -- l'episodio -- e infatti li' l'header e' corretto. Dentro la finestra Video, invece, `ListItem`
nudo risolve sul contenitore della **finestra**, cioe' la lista stagioni: non e' mai vuoto, quindi
vinceva sempre, e il pannello episodi non veniva mai interrogato.

Correzione: quando la skin sta **dichiarando in questo istante** quale contenitore ha il fuoco --
`TMDbHelper.WidgetContainer` letta non vuota nel giro corrente -- quel contenitore ha la precedenza su
`ListItem` nudo. Solo il valore appena letto, mai `last_container`, che e' un ricordo e non puo'
scavalcare un elemento a fuoco reale.

E' il primo uso concreto della proprieta' dopo il verdetto del lotto 63: **vuota in costruzione,
valorizzata in interazione**. Qui siamo nel secondo caso.

### 2. Il badge dell'episodio non si aggiorna dopo "segna come visto"

```
16:49:34.2  mark_as_watched S1E2
16:49:35.5  fatto (1049 ms)
16:49:37.4  build_season_list ricostruita     <- solo la lista stagioni
            build_episode_list MAI            <- il pannello resta fermo
16:49:53.6  l'utente torna in Home -> kodi_refresh_ids&ids=283297 (rimandato dal lotto 58)
16:50:08.5  rientra nella serie -> build_episode_list -> ora il badge c'e'
```

`Container.Refresh` ricarica la cartella aperta, che nella vista Combined e' la lista **stagioni**. Il
pannello episodi non e' un contenitore di finestra: il suo `<content>` vale
`$INFO[Container(52X).ListItem.FolderPath]`, e quella URL dopo il refresh torna **identica**. Kodi non
ha alcun motivo di ricaricarlo. Non era lentezza ne' attesa di Trakt: non succedeva proprio niente
finche' l'utente non usciva e rientrava.

Correzione, stesso principio del token pagine dei widget: `kodi_refresh_ids` scrive un nonce in
`PANEL_RELOAD_PROP` **prima** di `Container.Refresh`, e `seasons.py` lo accoda alla URL di ogni
stagione. La lista stagioni si ricostruisce con FolderPath nuove, il pannello se ne accorge e si
ricarica da solo. `reload` e' gia' in `paginator._VOLATILE_PARAMS`, quindi non entra nella chiave del
widget ne' nella paginazione. Il nonce si legge una volta per costruzione, non una per stagione.

Costo: una `build_episode_list` in piu' (~850 ms misurati) e **solo** dopo un'azione dell'utente.

---

## Lotto 64 bis -- Il crash del 24/08 alle 16:58: leggere il log senza sbagliare

Il log si interrompe alle **16:58:33.767**, durante il caricamento degli XML della skin, 2,2 s prima
che parta qualunque codice Fen Light. La lettura ovvia -- "e' morto li'" -- e' **sbagliata**.

```
adb shell "date; cat /proc/uptime"   ->  17:01:26, uptime 160 s  ->  boot alle 16:58:46
```

Il riavvio e' avvenuto **12 secondi dopo** l'ultima riga scritta. Il log vive su storage emulato con
scritture bufferizzate: un kernel panic perde la coda non ancora scaricata su disco. Quei 12 secondi --
invisibili -- sono esattamente la finestra in cui, nel boot buono delle 16:48, si costruivano tutti e
quattro i widget della home (16:48:44 -> 16:48:54).

Quindi: **il punto di troncamento non e' il punto del crash.** Prenderlo per tale avrebbe accusato la
skin e scagionato l'addon, sbagliando due volte.

```
ro.boot.reboot_mode: kernel_panic     <- non 'watchdog_reboot' come nei casi precedenti
ro.boot.bootreason:  reboot,userrequested   <- fuorviante, va ignorata
```

Cio' che il log dimostra davvero: il prefisso scaricato su disco e' identico, riga per riga fino alla
471, a quello del boot riuscito delle 16:48. Nessuna anomalia prima del buio.

### Le tre modifiche del lotto 64 davanti a questo crash

- `seasons.py` e il ramo 10025 di `kodi_utils`: **non girano all'avvio**. La home costruisce film,
  liste mdblist e 'continua a guardare'; `seasons.py` non viene nemmeno importato.
- `blur_service.py`: e' l'unico che gira in quella fascia -- ma non in quella finestra.
  `BLUR_START_DELAY = 25` (mitigazione del 23/08) lo fa partire 25 s dopo i servizi, e il panic e'
  arrivato a 16 s dall'avvio di Kodi. Non era ancora partito.

Nessuna delle tre puo' aver causato il panic. Resta comunque applicata una precauzione: la nuova
precedenza al contenitore dichiarato dalla skin ora vale **solo fuori dalla schermata principale**
(`getCurrentWindowId() != 10000`). Sulla home l'ordine vecchio era gia' corretto -- il difetto esiste
solo nelle finestre media -- e cosi' il ramo che gira durante la tempesta dei widget resta identico a
prima. Non e' una correzione: e' togliere una variabile dal tavolo prima della prossima misura.

---

## Lotto 64 ter -- Verifica sul campo e il "lampeggio" del pannello episodi (24/08, 17:04)

### Il lotto 64 funziona, dal log

```
17:04:12  mark_as_watched S1E3 -> DIAG refresh: MIRATO finestra Video
17:04:15  build_episode_list&reload=1787583853070   <- il pannello SEGUE, non serve piu' uscire
17:04:24  mark_as_unwatched S1E2 -> stessa cosa, reload=1787583864679
17:04:27  Trakt: rebuild RIMANDATO, la modifica sembra nostra
          TraktMonitor: refresh saltato, la modifica e' nostra ed e' gia' a schermo
17:04:32  rientro in Home -> kodi_refresh_ids&ids=283297
17:04:35  DIAG refresh: MIRATO 2 contenitori ricaricati | finestra=10000
```

Nessun `GLOBALE`, nessun `UpdateLibrary`, nessuna cache fallita, nessuna eccezione. `DIAG vista` esce
una volta sola, come previsto dal marchio del lotto 57 bis.

Boot 17:03:37.384 -> 17:03:55.618 = **18.2 s** contro i 16.5 s del boot precedente. Non e' una
regressione: e' il confondente noto dei `.pyc`. I tre file modificati sono stati ricompilati
(`import pigri` 3.5 s contro 2.4-3.0 s). Il prossimo boot torna in linea.

Unica stranezza minore: alle 17:04:41 `Latest TV Shows` viene riletto una seconda volta **senza**
parametro `reload`. E' la rilettura spontanea dei provider alla riattivazione della finestra gia'
documentata nel lotto 61 bis, non un nostro doppione.

### Perche' nella home il ricarico e' netto e nel pannello episodi no

Non e' un caso, ed e' nella skin. Le due regole sono opposte.

**Widget della home** (`Includes_Widgets.xml:101`):
```xml
<visible>... + [Container(X).IsUpdating | !Integer.IsEqual(Container(X).NumItems,0) | ...]</visible>
```
Il widget resta visibile mentre si aggiorna **oppure** finche' ha elementi. Non attraversa mai uno
stato vuoto: e' esattamente il "netto" che si vede.

**Pannello episodi** (`Includes_Views_Combined.xml:107`):
```xml
<animation type="Conditional" reversible="false" condition="Container(53X).IsUpdating">
    <effect type="fade" start="100" end="0" time="200" delay="600" />
</animation>
```
Il pannello **sfuma a zero** appena l'aggiornamento supera 600 ms. Una nostra ricostruzione ne impiega
1400-1900 (interprete Python nuovo compreso), quindi la soglia viene superata **sempre**. Poi rientra,
e le texture si ricaricano in modo asincrono: da qui il "ricompaiono senza immagine".

La regola della skin ha senso per il caso a cui era destinata -- hai cambiato stagione, gli episodi
vecchi sono sbagliati, meglio nasconderli -- ma scatta identica sul refresh in posto, dove la lista e'
la stessa di prima.

Non e' aggirabile dal plugin: 600 ms non sono raggiungibili con un interprete Python nuovo per
invocazione, e la durata non distingue un refresh da un cambio stagione. L'unica via e' una riga di
skin: condizionare la dissolvenza anche a `Integer.IsEqual(Container(53X).NumItems,0)`, cioe' sfumare
solo quando non c'e' davvero niente da mostrare -- la stessa regola dei widget della home. Non
applicata: e' cosmetica e tocca la skin, quindi va decisa a parte.

---

## Lotto 65 -- Il cambio finestra NON ricostruisce i widget: correzione di quanto detto finora

Misurato nel log delle 17:04, contando le riletture dei provider evento per evento:

```
17:03:43.679  Window Init (Home.xml)          -> 4 provider riletti   (avvio, la pagina corrente)
17:04:01.398  Window Init (MyVideoNav.xml)    -> 2 provider           (stagioni + pannello episodi)
17:04:32.744  Window Init (Home.xml)          -> ZERO provider riletti
17:04:35.893  kodi_refresh_ids (nostro)       -> 2 provider, mirati
```

**Tornando dalla serie alla Home, Kodi non ha riletto nulla.** Le uniche due ricostruzioni sono le
nostre, mirate, con il nonce. Lo stesso si legge nel log delle 16:37 (rientro in Home alle 16:38:47,
nessuna rilettura).

Va quindi corretto quanto scritto nei lotti 61 bis e 62: **non e' il cambio di finestra a invalidare i
provider.** Quella formulazione era troppo larga e nasceva dall'unico caso osservato, che era un altro.

Il caso reale e' la **riproduzione**: alla chiusura del player tutti i widget video della pagina
corrente si ricostruiscono (misurato piu' volte nei lotti 59-61). Spiegazione che regge su entrambe le
misure: `CDirectoryProvider` si iscrive agli annunci `Player` di Kodi e si invalida su OnPlay/OnStop.
E' codice di Kodi, senza leve dal plugin ne' dalla skin. Il cambio finestra, da solo, non produce
nessun annuncio e infatti non ricostruisce niente.

Conseguenza pratica per le **pagine di widget separate** di Arctic Fuse: funzionano come sperato. Un
provider invalidato rilegge solo quando torna VISIBILE, quindi i widget delle altre pagine non pagano
nulla finche' non ci si va. La prova e' nell'avvio: 4 provider letti, non tutti quelli della skin.

## Lotto 65 bis -- Dissolvenza del pannello episodi (applicata, da provare)

`Includes_Views_Combined.xml:107`, condizione dell'animazione:

```xml
condition="Container(53X).IsUpdating"
         -> "Container(53X).IsUpdating + Integer.IsEqual(Container(53X).NumItems,0)"
```

Si sfuma solo quando non c'e' davvero niente da mostrare: la stessa regola dei widget della home
(`Includes_Widgets.xml:101`), che infatti non lampeggiano mai. Il cambio stagione, che svuota davvero
il pannello, continua a sfumare come prima.

Nota per il futuro: i commenti XML non possono contenere due trattini di fila. Il primo tentativo ha
prodotto un file non valido, intercettato dal parse prima del deploy.

---

## Lotto 66 -- Seconda finestra di widget: diagnosi (24/08, log delle 17:17-17:28)

### 1. La lentezza NON e' memoria: e' rete su cache fredda

Nessun OOM, nessun `lowmemorykiller`, nessun avviso di memoria in tutto il log. Il costo sta altrove.

I due widget nuovi sono liste **Trakt** (Movies Watchlist, Trending), i cui titoli non erano mai stati
messi in cache. Costo per pagina, dal log:

```
17:24:25  build_movie_list | 14866 ms | routing->lista 14401   (3 pagine, 43 elementi)
17:24:45  build_movie_list | 17882 ms | routing->lista 17452   (4 pagine, 61 elementi)
17:25:31  build_movie_list | 42047 ms | routing->lista 41089   (5 pagine, 80 elementi)
17:27:31  build_movie_list | 24655 ms | routing->lista 21316
```

`routing->lista` e' il 97% del totale. Dentro ci sono due sorgenti di rete:

- **30 chiamate TMDb** `/movie/<id>`, una per titolo mai visto (55 in tutta la sessione, 30 delle
  quali di Trending).
- **`dub_filter`**: `rete: streaming 3-8, bluray 0-7 | valutazione 5.4 - 14.6 s` **per pagina**. E'
  la voce singola piu' cara e la piu' variabile.

Confronto sullo stesso dispositivo e nella stessa sessione: i widget mdblist della home, con
`verdetto in cache 20` e `rete: streaming 0, bluray 0`, costano 2-6 s. **Non e' un muro hardware: e'
la cache fredda.** Ogni titolo si paga una volta sola, e infatti la stessa lista Trending scende a
9,6 s quando si riscalda.

Resta pero' un costo strutturale: Trending e Watchlist **cambiano nel tempo**, quindi avranno sempre
titoli nuovi. Un widget su lista Trakt non arrivera' mai al regime dei widget mdblist.

### 2. Perche' si e' sentita cosi' tanto: la paginazione a scorrimento

Ogni pagina caricata dal `WidgetPaginator` mentre l'utente scorre e' una di quelle invocazioni da
15-18 s. Non e' lavoro di sfondo: e' esattamente il momento in cui l'utente sta guardando la lista.

### 3. Dopo il player: undici ricostruzioni

Riproduzione 17:27:05 -> 17:27:47. Poi:

```
17:27:48.137  OnPlayBackStopped  (CApplication)
17:27:48.76   Hub: 2 provider
17:27:50.005  OnPlayBackStopped  (CXBMCApp -- SECONDO annuncio)
17:27:50.18   Hub: 2 provider     <- gli stessi due, di nuovo
17:28:02.56   Home: 4 provider
17:28:10.74   Hub: 1 provider
17:28:20.71   Home
```

Kodi emette **due** annunci di stop a 1,9 s di distanza e i provider si invalidano due volte. Sommando,
nove ricostruzioni fra 17:27:48 e 17:28:17, ~67 s di lavoro cumulato in 29 s di orologio. Il nostro
codice non ha aggiunto nulla: `DIAG refresh: NON ordinato, Kodi ha gia' ricostruito da sola`.

### 4. Il collasso della pagina dinamica: causa trovata, e' una collisione di id

Il token delle pagine vive sull'**id del contenitore** (`fenlight.pg.ctl<ID>.pages`). Gli id dei
contenitori **non sono unici fra finestre**. Dal file generato dalla skin sulla stick:

```
Home        ctl501 = continua a guardare   ctl502 = Latest releases Gary
                    ctl503 = Top 250              ctl504 = Latest TV Shows
Hub 1101    ctl501 = Movies Watchlist      ctl502 = Trending
Ricerca                                    ctl502 = ricerca film
```

**`ctl502` e' condiviso da tre widget diversi in tre finestre diverse.** E `service.py:306-308` fa,
correttamente per il caso a cui era destinato:

```python
if window.getProperty(paginator.CTL_KEY_PROP % widget_id) != key:
    window.setProperty(paginator.CTL_KEY_PROP % widget_id, key)
    window.clearProperty(paginator.CTL_PAGES_PROP % widget_id)   # cambio inquilino -> azzera
```

Ogni passaggio di finestra fa cambiare inquilino a ctl502 e **azzera il token condiviso**. Nel log si
vede due volte:

```
17:28:02.577  PROV ...Gary&pages=5        17:28:04.795  PROV ...Gary   (senza pages) -> collassa
17:28:10.597  Trending path_pages=5       17:28:16.816  Trending path_pages=- , 26 elementi (2 pagine)
```

Con una sola finestra di widget il difetto non poteva manifestarsi: nasce esattamente aggiungendo la
seconda. Non e' un bug della logica di azzeramento, che e' giusta: e' che lo **spazio dei nomi** (l'id
del contenitore) smette di essere univoco appena le finestre sono piu' di una.

Due strade, da decidere:
- **Lato plugin**: tenere il conteggio in un deposito per (finestra, contenitore) e confrontare la
  chiave sempre per (finestra, contenitore). Problema di tempistica: alla riattivazione Kodi rilegge
  il provider entro 2 ms dall'Init (misurato: 17:28:02.560 -> .562), mentre il watcher gira ogni
  300 ms; ripristinare il valore dopo sarebbe una ricostruzione in piu', non in meno.
- **Lato skin**: dare a ogni finestra un intervallo di id proprio nel generatore (Home 501+,
  hub 1101 511+, ...). Risolve alla radice e non ha problemi di tempistica, ma tocca la catena di
  generazione degli include della skin.

---

## Lotto 67 -- Token di paginazione indicizzato per (finestra, contenitore)

### La sonda

Prima di toccare qualunque cosa, una riga di commento nel template per verificare che `{window_id}`
arrivasse fin dentro `widgets_row.xmltemplate`, dove non era mai stato usato. Esito nel file generato:

```
228: <!-- fenlight-pgscope-probe: whome ctl501 -->     455: <!-- ... w1101 ctl501 -->
256: <!-- fenlight-pgscope-probe: whome ctl502 -->     483: <!-- ... w1101 ctl502 -->
```

La sostituzione funziona, e conferma anche la collisione: `ctl502` esiste in Home e in 1101.

**Nessun id di controllo e' stato cambiato.** La domanda era se rinumerarli non facesse ricaricare i
widget a ogni cambio finestra: la risposta e' no -- Kodi rilegge un provider per attivazione della
finestra o per invalidazione da annuncio, e il numero non entra in nessuno dei due (nel log delle
17:27 le riletture seguono gia' la finestra, non l'id) -- ma la domanda ha portato a una soluzione
migliore, che gli id non li tocca affatto: cambiare il **nome della proprieta'**, non il controllo.

### Cinque punti nella skin

```
widgets_row.xmltemplate         fenlight.pg.ctl{widget_id}.pages
                             -> fenlight.pg.w{window_id}.ctl{widget_id}.pages
widgets_wall.xmltemplate        + <param name="pgscope">{window_id}</param>
widgets_combined.xmltemplate    + <param name="pgscope">{window_id}</param>
search_row_standard.xmltemplate -> fenlight.pg.w1105.ctl{widget_id}.pages
                                   (la ricerca vive in Custom_1105_Search.xml e nel generatore
                                    non ha window_id: nessuna lista lo definisce per quel ramo)
Includes_Hubs.xml:125,180       -> fenlight.pg.w$PARAM[pgscope].ctl$PARAM[id].pages
                                   con <param name="pgscope">home</param> come default, cosi' un
                                   chiamante che non lo passa produce comunque un nome scrivibile
                                   invece di uno letterale che nessuno scrive.
```

### Due punti nel plugin

`CTL_PAGES_PROP` e `CTL_KEY_PROP` prendono due argomenti, e `paginator.ctl_scope()` traduce la
finestra corrente nel nome che usa la skin: 10000 -> `home`, altrimenti il numero (hub 1101-1104,
ricerca 1105). Lo scope si legge una volta per ciclo in `service.py` e una volta per refresh in
`refresh_containers_for_ids`.

Il controllo di cambio inquilino resta identico -- e' giusto per il caso a cui serviva, la ricerca che
cambia chiave a ogni query -- ma ora opera su (finestra, contenitore) e non scatta piu' quando a
cambiare e' soltanto la finestra.

### Ordine di attivazione

Finche' gli include non sono rigenerati, il file generato legge ancora il nome vecchio mentre il
plugin scrive quello nuovo: la paginazione non si espande. Va rigenerato subito dopo il riavvio,
salvando dall'editor dei widget. Non e' un rischio, e' una finestra di qualche minuto in cui i widget
restano al lotto iniziale.

### Lotto 67 bis -- La skin dice 1101, Kodi dice 11101

La paginazione dell'hub e' sparita del tutto (la Home continuava a funzionare). Causa: i due lati non
chiamano la finestra con lo stesso numero.

Il file si chiama `Custom_1101_Hub.xml`, dichiara `<window type="window" id="1101">` e il generatore
scrive `w1101`. Ma Kodi assegna alla finestra `WINDOW_HOME + 1101 = 11101`. Lo stampa da solo nelle
righe dei tasti, che sono l'unico posto del log dove l'id numerico compare:

```
17:50:45.593  HandleKey: right, window 10000     <- Home
17:50:45.595  Window Init (Custom_1101_Hub.xml)
17:50:46.113  HandleKey: down,  window 11101     <- l'hub
17:51:08.904  HandleKey: down,  window 11170     <- Custom_1170_Dialog_Options
```

Quindi `ctl_scope()` restituiva `'11101'` e il servizio scriveva `fenlight.pg.w11101.ctl502.pages`
mentre la skin leggeva `fenlight.pg.w1101.ctl502.pages`. Sulla Home i due nomi coincidevano
(10000 -> `home` da entrambe le parti) e infatti li' funzionava: e' il motivo per cui il difetto si
vedeva solo nella seconda finestra.

Corretto in `ctl_scope()` sottraendo `WINDOW_HOME` **solo** nell'intervallo delle finestre custom
(11000-11999). Fuori da li' si lascia il numero com'e': 10025 e' la finestra Video standard di Kodi e
sottrarre 10000 darebbe `'25'`, un nome che nessuno scrive.

Verificato in locale sulla sola logica di traduzione, senza dispositivo:
`10000 -> home`, `11101 -> 1101`, `11105 -> 1105`, `10025 -> 10025`.

Nota di metodo: la sonda del lotto 67 ha verificato il lato **skin** e l'ha dato per buono a ragione.
Il lato **plugin** non e' stato sondato, e li' stava l'errore. Quando due sistemi devono concordare su
un nome, vanno misurati tutti e due, non uno.

---

## Lotto 68 -- La ricarica mirata raggiunge solo la finestra a fuoco

Segnalato: azzerando l'avanzamento di un film da una finestra diversa dalla Home, 'continua a
guardare' resta col vecchio stato, e nemmeno Trakt lo rimedia. Dal log delle 18:24:

```
18:24:23.722  erase_bookmark media_type=movie tmdb_id=324857
18:24:24.542  DIAG refresh: MIRATO 2 contenitori ricaricati | finestra=11101
              (i due contenitori sono Watchlist e Trending: quelli dell'HUB)
18:24:33.377  Window Init (Home.xml)   -> nessun provider riletto, la Home NON si ricostruisce
18:24:41.095  TraktMonitor: refresh saltato, interfaccia ricostruita 16.6s fa
```

`Container(N).ListItem...` non risolve per una finestra che non e' a schermo: dall'hub la ricarica
mirata poteva raggiungere **solo** i due widget dell'hub. Il difetto non e' che fallisce -- e' che
**riesce parzialmente e si dichiara completa**. `hit=2 > 0`, quindi niente fallback, e il timbro
`_stamp_refresh` zittiva pure il monitor Trakt, che era l'ultima occasione di rimediare.

La sincronizzazione Trakt, come si vede, non c'entrava: `titoli cambiati: 0` e' corretto, la modifica
era davvero nostra e il database era allineato. A non essere allineato era lo **schermo**, e solo in
un'altra finestra. Stessa distinzione gia' incontrata nel lotto 58.

**Correzione, due punti.**

`kodi_refresh_ids`: quando la finestra corrente non e' la Home, il lavoro e' parziale per costruzione
anche a `hit > 0`. Gli id si tramandano in `PENDING_IDS_PROP` invece di essere considerati chiusi. La
riga di diagnostica lo dice: `| resto RIMANDATO alla Home`.

`WidgetRefresher`: la condizione per applicare un rinvio era `getCurrentWindowId() != 10025`, cioe'
"ovunque tranne la finestra Video". Bastava finche' l'unico posto irraggiungibile era quello; con una
seconda finestra di widget no. Ora e' `== 10000`: si applica **dove i contenitori da ricostruire
esistono davvero**. Se l'utente non torna mai in Home non si perde niente -- quei widget non sono a
schermo e il rinvio resta li' ad aspettare.

L'accorpamento non lo sopprime: `REFRESH_COALESCE_SECONDS` e' 5 s e il servizio gira ogni 10 s, quindi
il rinvio arriva sempre fuori dalla finestra di accorpamento.

---

## Lotto 69 -- La ricarica mirata attraversa le finestre

Il lotto 68 funzionava ma era **a due tempi**, e solo in un verso. Dal log delle 18:57:

```
18:57:20.802  MIRATO 1 | finestra=11101 | resto RIMANDATO      (azione dall'hub)
18:57:32.712  MIRATO 1 | finestra=10000                        -> continua a guardare, 12 s dopo
18:57:41.739  erase_bookmark 569094                            (azione dalla Home)
18:57:42.531  MIRATO 2 | finestra=10000
18:57:47.911  Window Init (Custom_1101_Hub.xml)                -> nessun provider: hub FERMO
```

Obiezione dell'utente, corretta: gli effetti non devono arrivare in due momenti diversi, e nessun hub
deve poter restare disallineato.

### Il vincolo vero, e come si aggira

`Container(N).ListItem...` risolve **solo** per la finestra a schermo. Da un hub non si puo' chiedere
a Kodi cosa contengano i widget della Home. Questo non cambia.

Ma il token delle pagine non e' una infolabel: e' una **proprieta' della finestra Home**, scrivibile da
qualunque contesto. Cambiarla cambia il `<content>` di QUEL contenitore in QUELLA finestra. Serviva
solo sapere quali coppie (finestra, contenitore) esistono e cosa contengono -- e quello ce lo possiamo
ricordare.

### Censimento

`WidgetPaginator` gia' calcola lo scope a ogni giro. Quando **cambia** -- cioe' a ogni passaggio di
finestra, non a ogni giro -- fa una passata sui contenitori della finestra corrente (~20 infolabel) e
registra `(finestra, contenitore) -> chiave del widget` in `CTL_KEY_PROP`, aggiungendo la coppia a
`CTL_REGISTRY_PROP`. La stessa passata applica per ogni contenitore la regola di cambio inquilino che
prima valeva solo per quello a fuoco: piu' corretta di prima, non meno.

### Ricarica

`refresh_containers_for_ids` fa due giri:
1. la finestra a schermo, dalle infolabel, come prima (autorevole e copre anche i widget mai messi a fuoco);
2. tutte le altre coppie censite: chiave da `CTL_KEY_PROP`, verifica su `IDS_PROP`/`ACTION_PROP`
   esattamente come nel primo giro, e cambio del token.

La **decisione** e' quindi sincrona su tutte le finestre. Il ridisegno di una finestra non a schermo
avviene quando torna a schermo -- Kodi non puo' ricostruire un contenitore che non esiste ancora -- ma
il suo path e' gia' cambiato, quindi l'utente non vede mai un valore vecchio e non si paga nulla per
finestre che non guarda.

Il valore restituito resta il conteggio della sola finestra a schermo: e' cio' che governa il fallback
globale, e ricadere sul globale perche' l'unico contenitore interessato sta altrove sarebbe il
contrario di quanto si vuole. Il conteggio delle altre finestre viaggia in `LAST_OTHER_HITS`.

### Il rinvio del lotto 68 si restringe

Non si rimanda piu' nulla quando il censimento ha risposto: sarebbe lavoro doppio sugli stessi
contenitori, e sarebbe di nuovo il comportamento a due tempi. Resta solo come rete di sicurezza per il
caso in cui non ci sia proprio niente di censito da raggiungere -- una finestra mai aperta nella
sessione.

Verificato a secco, senza dispositivo: dalla Home, con 569094 presente in 'continua a guardare' e in
Trending (hub) ma non in Watchlist, il giro sulle altre finestre tocca **solo** `1101:502`.

### Lotto 69 bis -- Verifica sul campo, e il difetto che la verifica ha scoperto

**L'assunzione regge, ed e' dimostrata dai nonce.** Log delle 19:08, azione fatta dalla Home:

```
19:08:44.763  erase_bookmark tmdb_id=1314481                              (Home)
19:08:45.573  PROV build_continue_watching&pages=2&reload=1787591325571
19:08:45.617  PROV ...Gary&pages=2&reload=1787591325571
19:08:45.649  DIAG refresh: MIRATO 2 | altre finestre 1 | finestra=10000
19:08:51.637  Window Init (Custom_1101_Hub.xml)
19:08:51.639  PROV ...Trending...&pages=3&reload=1787591325571            <- 2 ms dopo l'Init
```

Il nonce che l'hub rilegge e' **lo stesso** generato sei secondi prima, sulla Home, mentre l'hub non
era a schermo. Kodi onora quindi un cambio di `<content>` avvenuto a finestra nascosta e rilegge alla
riattivazione. Il meccanismo del lotto 69 e' valido, non per deduzione ma per confronto di identita'.

Da notare anche `pages=3`: l'hub ha conservato la propria paginazione attraverso la ricarica.

**Il difetto scoperto: il censimento sbagliava il momento.** Nella stessa sessione:

```
19:08:10.967  Window Init (Home.xml)
19:08:10.969  i quattro provider partono          <- 2 ms dopo
19:08:27.642  DIAG refresh: ... | altre finestre 0 | finestra=11101 | nessuna finestra censita
```

Il censimento girava **una volta sola** al cambio di finestra, cioe' entro 0,3 s dall'Init: i
contenitori erano ancora vuoti, non registrava niente e la sua unica occasione era bruciata. Agendo
dall'hub, la Home risultava quindi non censita e si ricadeva sul rinvio -- la rete di sicurezza
funzionava, ma stava coprendo il caso normale invece di quello raro.

Corretto ripassando a scatti dopo ogni cambio di finestra: giri 0 / 5 / 10 / 20 / 35 / 55, cioe'
0 / 1,5 / 3 / 6 / 10,5 / 16,5 secondi, che copre il tempo di costruzione dei widget sulla stick (spesso
oltre 5 s). Sei passate da ~20 infolabel per cambio di finestra, non un sondaggio perpetuo.
`registry_add` e' idempotente, quindi ripassare non duplica: aggiunge solo cio' che nel frattempo e'
comparso.

**Metodo.** La verifica non doveva confermare l'impressione ("sembra funzionare"), ma cercare cosa
l'impressione non poteva vedere. L'utente vedeva l'hub aggiornato in entrambi i versi -- ed era vero.
Solo che in un verso ci arrivava per la strada giusta e nell'altro per la rete di sicurezza, e senza i
nonce nel log le due cose sono indistinguibili a schermo.

### Lotto 69 ter -- Conferma completa (log delle 19:14)

Un'unica azione, dalla Home, e tutti i segnali attesi al posto giusto:

```
19:14:58.792  erase_bookmark tmdb_id=931285                                   (Home)
19:14:59.587  PROV build_continue_watching&pages=2&reload=1787591699585
19:14:59.588  PROV ...Gary&pages=3&reload=1787591699585
19:14:59.655  DIAG refresh: MIRATO 2 | altre finestre 1 | finestra=10000
19:15:07.883  PROV ...Trending&pages=4&reload=1787591699585                   (hub, alla riapertura)
```

- Stesso nonce nelle tre riletture: la decisione e' UNA, presa in un istante solo.
- Nell'hub si e' ricostruito **solo Trending**. `Movies Watchlist` non compare: zero riletture nella
  finestra. La selezione per id funziona anche attraverso le finestre, non solo in quella a schermo.
- `pages=2`, `pages=3`, `pages=4` conservati ovunque: nessun widget e' tornato al lotto iniziale.
- `nessuna finestra censita`: **0 occorrenze**. Il censimento a scatti del lotto 69 bis regge.
- `GLOBALE`, `UpdateLibrary`, `FALLITA`, `SCADUTA`, `Traceback`: **0 occorrenze**.
- Trakt: `titoli cambiati: 0` e `refresh saltato, la modifica e' nostra ed e' gia' a schermo`. Corretto:
  il database era gia' allineato e nessuna ricostruzione ridondante e' partita.
- Post-riproduzione: `NON ordinato, Kodi ha gia' ricostruito da sola 4.3s dopo la chiusura`. Non
  aggiungiamo ondate.

Avvio 19:12:39.979 -> ultimo widget 19:12:56.748 = **16.8 s**, in linea col migliore misurato, e ora
con sei widget configurati su due finestre invece di quattro su una (la seconda finestra si costruisce
solo quando la si apre: vedi lotto 65).

Il fronte "allineamento fra finestre" si puo' considerare chiuso.
