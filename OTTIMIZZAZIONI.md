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
