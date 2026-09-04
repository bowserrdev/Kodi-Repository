# -*- coding: utf-8 -*-
# Centralized pagination logic shared by the indexer modules and the WidgetPaginator service.
# Implements interactive "infinite scroll" pagination for home widgets: instead of appending a
# clickable "Next Page" item, the plugin loads N cumulative pages in a single (append-only) build.
# A service-side watcher bumps the page count as the user scrolls and triggers a silent container
# refresh, so the already-loaded items keep their position and the focus is preserved.
from hashlib import md5
from re import compile as re_compile
from modules.kodi_utils import parse_qsl
from caches.settings_cache import get_setting
# Interruttore unico della strumentazione: qui in testa perche' lo usano sia PG_DEBUG sia PERF,
# e il primo dei due sta molto piu' su del secondo.
from modules.perf import enabled as _perf_enabled

# Window(10000) properties bridging the plugin build and the service watcher. Keyed per widget.
PAGES_PROP = 'fenlight.pg.%s.pages'
HASMORE_PROP = 'fenlight.pg.%s.hasmore'
LOADING_PROP = 'fenlight.pg.%s.loading'
# Count of items actually shown by the last build. The watcher only loads ahead once the container
# has caught up to this (numitems >= built) -- the anti-runaway gate: while a just-loaded page hasn't
# surfaced yet (Kodi coalesces widget refreshes) we wait instead of piling up page loads.
BUILT_PROP = 'fenlight.pg.%s.built'
# Universal container<->key bridge: the plugin maps the FIRST built item's path to the widget key;
# the watcher reads Container(id).ListItemAbsolute(0).FolderPath and looks the key up here. This works
# for every widget (home, hubs, text/advanced search) regardless of how the skin builds the path.
HEAD_PROP = 'fenlight.pg.head.%s'
# Set during a global soft refresh (kodi_refresh: Trakt monitor / periodic WidgetRefresher) so the
# rebuild preserves each widget's already-expanded page count instead of collapsing to the initial batch.
# Distinguishes an in-place refresh of a live, expanded widget from a genuine fresh open (which has no
# flag and starts from the initial batch). The watcher's own pagination refresh uses LOADING instead.
PG_REFRESH_PROP = 'fenlight.pg.refresh'
# Istante dell'ultima build INIZIATA per questa chiave (lo timbra get_pages, che e' il primo punto di
# ogni costruzione paginata). Serve a una sola domanda, ma decisiva: quando il watcher scrive il token
# e non succede niente, la build e' partita ed e' lenta, o non e' MAI partita?
# Non e' teoria: dal 24/08 al 25/08, sul Mac, il file generato della skin era fermo al 14/08 e leggeva
# ancora 'fenlight.pg.ctl502.pages' (senza finestra), mentre il servizio scriveva gia'
# 'fenlight.pg.whome.ctl502.pages'. Il token finiva in una proprieta' che nessuno leggeva: TRIGGER
# regolare nel log, nessuna ricostruzione, LOADING appeso, paginazione morta in silenzio per due
# giorni. Con questo timbro il caso si distingue dal primo e si dice a voce alta.
# Definita in kodi_utils perche' la usa anche il cancello riproduzione (lotto 112), che non puo'
# importare questo modulo: una definizione sola, letta da entrambi.
from modules.kodi_utils import PG_LASTBUILD_PROP as LASTBUILD_PROP
# "STO COSTRUENDO QUESTO WIDGET" (lotto 106). Dichiarazione esplicita, scritta all'inizio della
# costruzione e cancellata quando il widget pubblica la propria testa. Serve al canale dei rinvii:
# finche' anche una sola di queste e' alzata, sparare una ricostruzione significa aggiungere carico
# sopra la tempesta d'avvio.
# UNO SCRITTORE PER CHIAVE, mai un contatore condiviso: incrementare e decrementare un numero in una
# proprieta' di finestra e' una lettura-modifica-scrittura fra processi concorrenti, ed e' esattamente
# cio' che il lotto 23 ha dovuto spegnere (DIAG) perche' si perdevano aggiornamenti. Qui ogni build
# scrive e cancella SOLO la propria chiave: due build concorrenti non si toccano.
INFLIGHT_PROP = 'fenlight.pg.%s.inflight'
# Rete di sicurezza contro il blocco, NON il criterio di scatto. Se un'invocazione muore prima di
# pubblicare la testa (su questo dispositivo succede: vedi l'indagine sui riavvii) la sua marca
# resterebbe alzata per sempre e il rinvio non partirebbe mai piu' -- che e' il guasto peggiore, gia'
# visto nel lotto 100. Il valore non e' scelto a occhio: la costruzione piu' lunga misurata nei log
# vale 16,3 s (un mdblist a cache fredda), questo e' quasi quattro volte tanto.
INFLIGHT_MAX_SECONDS = 60
# Token di ricarica MIRATA, indicizzato per id del contenitore. Compare dentro il <content> del widget
# come $INFO[...], quindi cambiarlo fa ricaricare SOLO quel contenitore invece di sparare
# UpdateLibrary, che e' un evento globale e ricostruisce tutti i widget della schermata (#1).
# Lo stesso meccanismo che la skin usa gia' per i widget di ricerca, che si ricaricano a ogni tasto
# perche' il loro <content> contiene un $VAR dinamico.
# Effetto collaterale voluto: il numero di pagine finisce NEL PATH, quindi e' stato durevole invece di
# un flag transitorio. Sopravvive a una build lenta e al ritorno dalla riproduzione.
#
# Il nome porta anche la FINESTRA, e non e' un vezzo. Il generatore della skin assegna gli id dei
# contenitori con $MATH[501 + {item_x}] (shortcuts/generator/data/setup/widgets_row.xml), senza alcuno
# scarto per finestra: ogni pagina di widget riparte da 501. Con una sola finestra non si notava; con
# due, 'ctl502' e' contemporaneamente un widget della Home, uno dell'hub 1101 e uno della ricerca.
# Misurato il 24/08 alle 17:28: passando fra le due finestre il token condiviso veniva azzerato dal
# controllo di cambio inquilino qui sotto, e il widget a schermo tornava al lotto iniziale
# ('...Gary&pages=5' -> '...Gary' e Trending da 80 elementi a 26). Lo spazio dei nomi deve essere
# (finestra, contenitore), non il solo contenitore. Vedi ctl_scope().
CTL_PAGES_PROP = 'fenlight.pg.w%s.ctl%s.pages'
# IMPRONTA DEL CONTENUTO attualmente in quella posizione (lotto 92: prima ci stava la chiave del
# widget, quando chiave e contenuto erano la stessa cosa). Una posizione e' fissa, ma la lista che ci
# sta dentro no: un hub cambia categoria, la ricerca cambia query a ogni tasto. Quando l'impronta
# cambia, il conteggio pagine di prima non vale piu' e va azzerato -- altrimenti la lista nuova si
# aprirebbe direttamente alle pagine accumulate da quella vecchia.
# Adesso a confrontarla e' la BUILD, non il watcher: e' l'unico momento in cui il contenuto e' noto
# con certezza, e toglie di mezzo tutta la classe di guasti in cui il watcher azzerava il token
# basandosi su cio' che credeva di vedere a schermo (lotti 90-91).
CTL_KEY_PROP = 'fenlight.pg.w%s.ctl%s.key'
# Home e' 10000 per Kodi ma 'home' per il generatore della skin (data/base/home_widgets.xml), che e'
# chi scrive il nome dentro il <content>. I due lati devono chiamarlo allo stesso modo o la skin
# leggerebbe una proprieta' che nessuno scrive.
#
# E per le finestre custom della skin i due lati NON usano lo stesso numero. Il file si chiama
# Custom_1101_Hub.xml e la skin scrive 1101, ma Kodi assegna alla finestra WINDOW_HOME + 1101 = 11101.
# Misurato il 24/08 alle 17:50 dal log di Kodi, che stampa l'id nelle righe dei tasti:
#     17:50:45.593  HandleKey: right, window 10000        <- Home
#     17:50:46.113  HandleKey: down,  window 11101        <- l'hub, dopo il suo Window Init
# Senza questa traduzione il servizio scriveva 'w11101' mentre la skin leggeva 'w1101': sulla Home
# tornava (10000 -> 'home') e nell'hub la paginazione spariva del tutto.
# La conversione si applica SOLO all'intervallo delle finestre custom: 10025 (Video) e' una finestra
# standard di Kodi e sottrarre 10000 li' darebbe '25', un nome inventato.
CUSTOM_WINDOW_BASE = 10000
CUSTOM_WINDOW_RANGE = (11000, 11999)
def ctl_scope():
	from modules.kodi_utils import getCurrentWindowId
	try: wid = getCurrentWindowId()
	except: return 'home'
	if wid == 10000: return 'home'
	if CUSTOM_WINDOW_RANGE[0] <= wid <= CUSTOM_WINDOW_RANGE[1]: return str(wid - CUSTOM_WINDOW_BASE)
	return str(wid)

# Censimento delle coppie (finestra, contenitore) gia' viste, come elenco di 'scope:cid'. Serve a
# rispondere a una domanda che le infolabel non possono soddisfare: 'Container(N).ListItem...' risolve
# solo per la finestra A SCHERMO, quindi da un hub non si puo' sapere cosa contengono i widget della
# Home. Il token delle pagine invece e' una proprieta' della finestra Home, scrivibile da ovunque:
# cambiarlo cambia il path di QUEL contenitore in QUELLA finestra, e Kodi lo rilegge quando la finestra
# torna a schermo. Il censimento e' cio' che permette di indirizzarlo senza vederlo.
# Lo compila WidgetRefresher/WidgetPaginator a ogni cambio di finestra (~20 infolabel, una volta per
# passaggio), non a ogni giro.
CTL_REGISTRY_PROP = 'fenlight.pg.ctlreg'
# Quanti contenitori di ALTRE finestre ha toccato l'ultima ricarica mirata. Lo legge kodi_refresh_ids
# nella stessa invocazione per sapere se il lavoro fuori dalla finestra a schermo e' stato fatto qui
# (e allora non serve nessun rinvio) o se non c'era niente di censito da raggiungere.
LAST_OTHER_HITS = [0]
# L'ultimo sondaggio ha VISTO almeno un contenitore Fen Light nella finestra a schermo? Distingue le
# due ragioni per cui una ricarica mirata puo' finire con zero contenitori ricaricati, che sono
# opposte fra loro: 'non ho potuto verificare niente' (nessun contenitore nostro qui) e 'ho verificato
# e nessuno c'entra' (tutti identificati, nessuno contiene i titoli cambiati). La prima merita il
# fallback globale, la seconda e' la RISPOSTA e ricadere sul globale la butterebbe via. Vedi
# kodi_utils.kodi_refresh_ids.
LAST_SEEN_ANY = [False]
CTL_REGISTRY_CAP = 80

def registry_pairs():
	from modules.kodi_utils import get_property
	return [p for p in (get_property(CTL_REGISTRY_PROP) or '').split(',') if ':' in p]

def registry_add(scope, cid):
	from modules.kodi_utils import get_property, set_property
	pair = '%s:%s' % (scope, cid)
	pairs = [p for p in (get_property(CTL_REGISTRY_PROP) or '').split(',') if p]
	if pair in pairs: return
	pairs.append(pair)
	# Tetto per non far crescere la proprieta' senza limite in sessioni lunghe: si scartano le piu'
	# vecchie, che al massimo tornano al primo passaggio successivo su quella finestra.
	if len(pairs) > CTL_REGISTRY_CAP: pairs = pairs[-CTL_REGISTRY_CAP:]
	set_property(CTL_REGISTRY_PROP, ','.join(pairs))
# Bounded registry of recently-built widget keys, to clean up stale per-widget properties over long
# sessions (each distinct search query mints a new key and leaks its prop set). Entry = 'key:headhash'.
# Pruning only ever drops the OLDEST entries; the focused widget is always newest, and a pruned widget
# simply republishes from scratch if reopened -- so this is behavior-neutral.
REGISTRY_PROP = 'fenlight.pg.registry'
REGISTRY_CAP = 60

# --- Ricarica MIRATA per id (P2.2-b) -----------------------------------------------------------
# Elenco dei tmdb_id pubblicati da un widget, indicizzato per chiave. Serve a rispondere alla sola
# domanda che conta quando qualcosa cambia: "questo widget contiene il film che e' cambiato?". Se no,
# ricostruirlo e' lavoro buttato -- e oggi si ricostruisce tutto perche' nessuno sa rispondere.
IDS_PROP = 'fenlight.pg.ids.%s'
# L'azione del widget (trakt_watchlist, tmdb_movies_popular, ...). Serve al caso OPPOSTO a IDS_PROP:
# quando un titolo viene AGGIUNTO a una lista, il widget di quella lista non contiene ancora il suo
# id, quindi la regola per id lo scarterebbe proprio mentre va ricostruito. Vedi
# refresh_containers_for_ids.
ACTION_PROP = 'fenlight.pg.action.%s'
# La testa dell'ULTIMA costruzione di questo widget: il path del primo elemento. Serve a rispondere a
# una domanda che nessuno sapeva porre -- 'in questa ricostruzione la testa e' cambiata?' -- e la
# risposta la conosce solo set_head, che vede la lista nuova avendo pubblicato la vecchia.
FIRSTURL_PROP = 'fenlight.pg.first.%s'
# I widget che hanno una testa NUOVA e vanno riportati a inizio riga: UNA proprieta' sola, con dentro
# l'elenco delle chiavi separate da virgola. La riempie set_head, la svuota il watcher.
# Perche' una coda e non una bandiera per chiave: il watcher deve poter chiedere 'c'e' qualcosa da
# fare?' a ogni giro da 0,3 s, e con una bandiera per chiave la domanda costava una lettura per ogni
# widget conosciuto anche quando la risposta era no. Cosi' costa una lettura sola, servita dalla
# memoria, e l'elenco si guarda solo nei rari giri in cui c'e' davvero lavoro.
# Perche' il lavoro lo fa il watcher e non il plugin: quando la build finisce Kodi non ha ancora
# popolato il contenitore -- la stessa corsa gia' documentata in refresh_containers_for_ids, dove
# container_head non riesce a leggere un contenitore appena ordinato -- quindi un comando lanciato dal
# plugin cadrebbe sulla lista vecchia. Il watcher e' l'unico che lo guarda DOPO.
REHEAD_PROP = 'fenlight.pg.rehead'
# I contenitori dei widget della skin. Arctic Fuse li numera 501-504 (verificato nel file generato e
# in Includes_Search.xml); il margine copre una riconfigurazione della home senza dover ritoccare qui.
# Sondarli costa una getInfoLabel ciascuno e avviene UNA volta per refresh, non in un ciclo.
WIDGET_CONTAINER_IDS = tuple(range(500, 521))
# Nome del parametro nonce accodato al token del contenitore per forzarne la ricarica. E' gia' in
# _VOLATILE_PARAMS, quindi non entra nella chiave del widget e la paginazione non se ne accorge.
RELOAD_PARAM = 'reload'

# LOTTO 92 -- L'IDENTITA' DI UN WIDGET E' LA SUA POSIZIONE, NON IL SUO CONTENUTO.
#
# La skin scrive questo parametro dentro il <content> di ogni widget paginabile, con la finestra e
# l'id del contenitore che gia' conosce al momento della generazione: 'pgctl=home.502',
# 'pgctl=1101.503', 'pgctl=1105.502'. Sono gli stessi due valori con cui compone il token delle
# pagine, e li avevamo davanti dal 24/08 senza usarli per identificare il widget.
#
# PERCHE' SERVE. I due lati parlano lingue diverse: la build riceve un PATH e non sa di essere "il
# secondo widget della Home"; il watcher vede un CONTENITORE dentro una FINESTRA e non sa quale lista
# ci sia dentro. Il ponte era una firma calcolata sul CONTENUTO -- prima il primo elemento, poi i
# primi tre (lotto 91). Ma un'identita' dedotta dal contenuto e' collidibile per costruzione: nel log
# zd del 25/08 il widget 'Latest releases' della Home e Trakt Trending nell'hub avevano lo stesso
# primo elemento byte per byte, e il watcher scambiava un contenitore per l'altro azzerando il token
# del widget sbagliato. Passare a tre elementi ha reso la collisione rara, non impossibile.
# Con la posizione nel path non c'e' niente da dedurre: la build legge da se' dove si trova, il
# watcher lo sa gia', e i due nomi coincidono per costruzione.
CTL_PARAM = 'pgctl'

# Params that change between cumulative reloads of the SAME widget and must not affect its key.
# 'pgctl' e' qui perche' make_key ora calcola l'impronta del CONTENUTO, che e' un'altra domanda:
# "in questa posizione e' cambiata la lista?". La posizione non deve entrarci.
_VOLATILE_PARAMS = ('new_page', 'paginate_start', 'refreshed', 'pages', 'reload', 'reload_property', CTL_PARAM)

# Text-search hub debounce + anti-stale. The skin rebuilds the search widgets on EVERY keystroke, so a
# burst of typing (or deleting) launches many overlapping builds for the same container; because each
# build takes ~1s (TMDB + per-item metadata) they finish OUT OF ORDER and an older query's build can be
# the last to publish, overwriting the live container and the head/built bridge with a stale (often
# longer) list -- which is what makes the widget jump to "item N" instead of the first result.
#
# The authoritative "what is the user searching right now" is the live search-box text: the skin builds
# every search widget path from $INFO[Control.GetLabel(3000).index(1)] (Path_SearchTerm). We compare a
# build's own query against that live label. We deliberately do NOT use a window property as the signal:
# builds are dispatched OUT OF ORDER by Kodi, so a late old build would overwrite a property backwards
# and wrongly consider itself current (that was the first attempt's flaw). The live label can't be
# corrupted by build ordering.
SEARCH_EDIT_INFOLABEL = 'Control.GetLabel(3000).index(1)'
# How long a search build waits before doing any expensive work. If the live label no longer matches this
# build's query after the wait, a newer keystroke has superseded it and it bails -- so the API/metadata
# work only runs once the user pauses typing.
SEARCH_DEBOUNCE_MS = 500

def _search_live_query():
	from modules.kodi_utils import get_infolabel
	try: return get_infolabel(SEARCH_EDIT_INFOLABEL)
	except: return None

# Verbose diagnostic logging for the interactive pagination flow. Grep the Kodi log for FENLIGHT_PG.
# Flip to True to re-enable tracing when debugging pagination.
# Acceso per l'indagine sulla paginazione (lotto 86): serve la riga che dice, per OGNI build, se
# 'interactive' era attivo e quante pagine ha chiesto il path. Senza, i due sintomi visti nel log zb
# -- il collasso (path chiede 5, build ne fa 2) e l'azzeramento al rientro nella finestra -- non si
# distinguono. Segue comunque l'interruttore unico: con la strumentazione spenta non stampa nulla.
PG_DEBUG = _perf_enabled()

def log(msg):
	if not PG_DEBUG: return
	try:
		import xbmc
		xbmc.log('### FENLIGHT_PG ### %s' % msg, 1)
	except: pass

def short(key):
	return key[:8] if key else key

def interactive_enabled():
	return get_setting('fenlight.paginate.interactive', 'true') == 'true'

def initial_batch():
	try: value = int(get_setting('fenlight.paginate.initial_batch', '2'))
	except: value = 2
	return max(2, value)

def lookahead_pages():
	# Quante PAGINE di margine tenere davanti al fuoco: il watcher fa partire la pagina successiva quando
	# gli elementi che restano scendono sotto page_limit * questo valore (vedi 'runway' in service.py).
	# Il margine va misurato in TEMPO, non in elementi: una pagina in piu' non aggiunge build -- il numero
	# di build per arrivare al tetto e' fissato dal tetto stesso -- decide solo QUANTO PRIMA ciascuna
	# parte. Con 1 il margine e' di 20 elementi, cioe' 2-4 secondi di scorrimento, mentre sulla stick una
	# build misura da 0,6 a 13 secondi (log 24/08, widget Trending): il caricamento non fa in tempo a
	# finire e l'utente arriva in fondo e aspetta. Da qui la sensazione di paginazione "a gradini".
	# Il default e' quindi 2 (40 elementi di margine); l'unico costo e' qualche pagina caricata in liste
	# che l'utente abbandona a poca distanza dalla fine.
	try: value = int(get_setting('fenlight.paginate.lookahead', '2'))
	except: value = 2
	return max(1, value)

def max_items():
	# Tetto agli ELEMENTI che un widget puo' arrivare a mostrare. Contare le PAGINE sarebbe la misura
	# sbagliata: con il filtro doppiaggio una pagina puo' rendere pochissimi elementi o nessuno, quindi
	# lo stesso numero di pagine produce liste di lunghezze molto diverse. Il costo che vogliamo
	# limitare, invece, e' rigorosamente per elemento -- la consegna a Kodi misura ~20 ms/elemento
	# a macchina scarica e fino a 250 sotto contesa (log stick 23/08).
	# Il rapporto e' a cricchetto: ogni paginazione allarga PER SEMPRE cio' che ogni ricostruzione
	# successiva dovra' ricostruire e riconsegnare. Nel log si vede crescere 48 -> 62 -> 87 -> 115.
	# Raggiunto il tetto il widget smette di ALLUNGARSI: nessuna lista si accorcia mai e la posizione
	# non salta, semplicemente non si carica altro.
	try: value = int(get_setting('fenlight.paginate.max_items', '75'))
	except: value = 75
	return max(20, value)

# Hard ceiling on the EXTRA raw pages a fill (see load_cumulative min_items) may fetch beyond the
# requested count. A sparse query -- one whose results are mostly filtered out (server-side for text
# search, post-build for advanced search) -- must not spin through dozens of TMDB pages chasing the
# target; it just hands back whatever it gathered. Generous because advanced search re-qualifies pages
# against IMDb (votes>=1000 + non-film removal) and can discard most of an early vote_average.desc page.
_FILL_PAGE_CAP = 12

def fill_target():
	# Filtered pages (text search server-side; advanced search post-build against IMDb) yield only a
	# handful of display items -- far short of a normal widget page. Every build fills up to this many
	# items so the initial screen is full and the focus starts well clear of the watcher's load-ahead
	# runway. Otherwise landing on item 1 of a 6-item list is already "within a page of the end" and the
	# watcher cascades pages 3,4,... just from arriving. Neutral for unfiltered widgets (a single page
	# already meets the target). See load_cumulative(min_items=...).
	from modules.settings import page_limit
	return page_limit(True)

# A genuine supersede always produces a NON-EMPTY different live label (the user typed more letters:
# "av" -> "avenger"). An EMPTY live label means the search box just isn't readable right now -- focus
# moved off the search window, e.g. into the modal scraping dialog (sources_results) -- NOT that the
# query changed. Treating empty as "superseded" wrongly drops a legitimate build of the current query:
# a watcher-driven pagination refresh that finishes while a scraping dialog is open would publish an
# empty directory and make the whole search widget vanish. So empty live is never a supersede signal.
def _live_supersedes(query, live):
	return bool(live) and live != query

def search_should_abort(query):
	# Debounce gate, called BEFORE any skin-state change / TMDB / metadata work for a text-search build.
	# Waits SEARCH_DEBOUNCE_MS, then returns True if the live search-box text no longer matches this
	# build's query -- a newer keystroke has superseded it, so it should bail cheaply. An empty query or
	# a non-search build (query is None) never debounces; an empty/unreadable live label never aborts.
	from modules.kodi_utils import sleep
	if not query: return False
	live = _search_live_query()
	if _live_supersedes(query, live):
		log('search_should_abort: superseded before wait query="%s" live="%s"' % (query, live))
		return True
	sleep(SEARCH_DEBOUNCE_MS)
	live = _search_live_query()
	if _live_supersedes(query, live):
		log('search_should_abort: superseded after %sms query="%s" live="%s"' % (SEARCH_DEBOUNCE_MS, query, live))
		return True
	return False

def search_is_stale(query):
	# Post-build guard, called right before publishing (add_items/set_head). The build itself takes ~1s,
	# so a newer keystroke may have arrived while it ran. If a NEWER query superseded this build, do NOT
	# publish: stale results would overwrite the live container and corrupt the head/built bridge,
	# jumping the widget to "item N". An empty/unreadable live label is NOT a supersede (see
	# _live_supersedes) -- otherwise a pagination refresh that completes while a modal dialog is open
	# would skip publishing and blank the widget.
	if not query: return False
	live = _search_live_query()
	if _live_supersedes(query, live):
		log('search_is_stale: skip publish query="%s" live="%s"' % (query, live))
		return True
	return False

# --- Strumentazione temporanea per le misure di prestazione (lotto ottimizzazioni) ---
# Una riga di log per costruzione di lista. Volume basso (una per widget per ricostruzione) e ci
# dice l'unica cosa che finora abbiamo stimato invece di misurare: dove finisce il tempo. La riga
# separa il tempo di RISOLUZIONE (pagine TMDb + filtri, quasi tutto da cache dopo il primo giro)
# da quello di COSTRUZIONE (una listitem per elemento: menu contestuale, info tag, artwork), che e'
# la parte incomprimibile per ricostruzione.
# NON si toglie a mano: dal lotto 83 tutto passa dall'interruttore unico di modules/perf.py, che
# legge l'impostazione 'perf.instrumentation'. Qui resta il nome PERF perche' e' letto da una
# quarantina di punti in questo file.
PERF = _perf_enabled()

# Contatore di invocazioni VIVE IN QUESTO INTERPRETE. Con reuselanguageinvoker=false ogni build apre un
# processo Python nuovo, quindi vale sempre 1. Con reuse=true l'interprete sopravvive e il numero
# cresce. E' l'unico modo per sapere se il flag ha davvero effetto: senza, si finirebbe a giudicare da
# quanto "sembra" veloce. Se resta a 1 con il flag attivo, qualcosa impedisce il riuso -- il sospetto
# principale e' il sys.exit(1) che fenlight.py esegue a fine build dei widget.
_INVOCATIONS = [0]

# --- DIAGNOSTICA DELLA CAUSA (lotto 47) --------------------------------------------------------
# Il log diceva CHE una lista era stata ricostruita, mai PERCHE'. Con due ondate di ricostruzioni
# dopo ogni riproduzione (log stick 22/08: mdblist 91378 a +18160 ms e la STESSA a +27545 ms) non
# c'era modo di distinguere le nostre -- ordinate dal token di ricarica mirata -- da quelle che Kodi
# fa per conto suo quando la finestra torna in primo piano. Senza quella distinzione ogni ipotesi sul
# doppione resta indimostrabile, e si finisce a correggere a caso.
# Le domande a cui doveva rispondere hanno gia' risposta (causa=, DOPPIONE, la tempesta post-
# riproduzione sono tutte diagnosi chiuse in OTTIMIZZAZIONI.md). _diag_note() fa una lettura-modifica-
# scrittura di UNA proprieta' CONDIVISA (DIAG_BUILDS_PROP) a ogni singola costruzione: durante l'avvio,
# quando piu' widget si costruiscono in parallelo in interpreti diversi, e' contesa fra processi sulla
# stessa proprieta' di finestra, proprio nella finestra piu' delicata. Stesso criterio gia' applicato a
# PERF_SELFTEST: spenta quando ha gia' dato le risposte che doveva dare. Riaccendibile a mano per una
# diagnosi mirata; non deve piu' pesare sull'uso normale.
DIAG = False
# Le ultime costruzioni, per riconoscere i doppioni. UNA proprieta' con un tetto di voci invece di una
# per chiave: le chiavi cambiano a ogni ricerca e una proprieta' per chiave lascerebbe rifiuti nelle
# sessioni lunghe (stesso difetto gia' corretto con REGISTRY_CAP).
DIAG_BUILDS_PROP = 'fenlight.diag.builds'
DIAG_BUILDS_CAP = 12
# Oltre questa distanza due costruzioni della stessa lista sono due eventi distinti, non un doppione.
# Largo perche' sulla stick fra le due ondate passavano 10 s e l'ondata stessa ne durava 15.
DIAG_DOPPIONE_SECONDS = 45

def _current_query():
	# I parametri di QUESTA invocazione letti da sys.argv, non passati dal chiamante: cosi' la
	# diagnostica non dipende dal fatto che ogni indexer si ricordi di fornirli, e non puo' divergere
	# dal path con cui Kodi ci ha davvero chiamati.
	try:
		import sys as _sys
		if len(_sys.argv) < 3 or not _sys.argv[2]: return {}
		return dict(parse_qsl(_sys.argv[2].lstrip('?'), keep_blank_values=True))
	except: return {}

def _build_cause(query):
	# Il nonce nel path esiste solo se il token l'ha messo refresh_containers_for_ids: quella
	# ricostruzione l'abbiamo ordinata noi. Senza nonce e' Kodi che rilegge il DirectoryProvider da
	# sola -- cosa che fa a ogni ritorno della finestra in primo piano, ed e' l'ipotesi da verificare
	# sulle ondate post-riproduzione.
	# Il nonce resta nel path del contenitore finche' non se ne ordina un altro: nel log del 23/08
	# 'reload=1787487459568' e' rimasto per SEI minuti, e ogni rilettura spontanea di Kodi in quel
	# periodo si presentava come 'ricarica-mirata'. Si confronta con l'ultimo nonce emesso e con
	# l'istante in cui e' stato emesso: oltre la finestra, quel token e' solo un residuo.
	_nonce = query.get(RELOAD_PARAM)
	if _nonce:
		try:
			from time import time
			# Il nonce E' l'istante di emissione in millisecondi: non serve nient'altro per datarlo.
			if 0 < (time() - float(_nonce) / 1000.0) < 60: return 'ricarica-mirata'
			return 'apertura/re-show (token scaduto)'
		except: return 'ricarica-mirata'
	if query.get('new_page') or query.get('paginate_start'): return 'paginazione'
	# UpdateLibrary non lascia niente nel path: senza questo timbro le ricostruzioni che innesca
	# sarebbero indistinguibili dalle re-show spontanee di Kodi, ed e' esattamente la distinzione che
	# serve per sapere quante ondate ci stiamo procurando da soli.
	try:
		from time import time
		from modules.kodi_utils import get_property
		_u = float(get_property('fenlight.diag.updatelibrary') or 0)
		if _u and 0 < (time() - _u) < 30: return 'refresh-globale'
	except: pass
	return 'apertura/re-show'

def _diag_note(t_built):
	"""Coda diagnostica della riga PERF: causa, doppione, riproduzione in corso."""
	if not DIAG: return ''
	try:
		from modules.kodi_utils import get_property, set_property
		query = _current_query()
		causa = _build_cause(query)
		bits = ['causa=%s' % causa]
		key = widget_key(query) if query else ''
		if key:
			raw = get_property(DIAG_BUILDS_PROP) or ''
			rows, prev = [], None
			for entry in raw.split(';'):
				parts = entry.split('|')
				if len(parts) != 3: continue
				if parts[0] == key and prev is None:
					try: prev = (float(parts[1]), parts[2])
					except: prev = None
				else: rows.append(entry)
			rows.append('%s|%s|%s' % (key, t_built, causa))
			set_property(DIAG_BUILDS_PROP, ';'.join(rows[-DIAG_BUILDS_CAP:]))
			if prev:
				delta = t_built - prev[0]
				if 0 < delta < DIAG_DOPPIONE_SECONDS:
					bits.append('DOPPIONE: stessa lista gia' + "'" + ' costruita %.0f ms fa (causa %s)' % (delta * 1000, prev[1]))
		# Una costruzione mentre il video va e' CPU rubata alla decodifica su un dispositivo debole.
		# Non la possiamo rifiutare -- e' Kodi che ce la chiede -- ma va contata.
		# Si legge una proprieta' di finestra, NON getCondVisibility: qui siamo nel mezzo della
		# costruzione, con il thread GUI fermo ad aspettarci, e interrogare la GUI da qui e' la stessa
		# trappola descritta in kodi_utils.end_directory.
		if get_property('fenlight.playback.active') == 'true': bits.append('DURANTE RIPRODUZIONE')
		return ' | ' + ' | '.join(bits)
	except: return ''

# Misura PER FASE dentro la costruzione della singola listitem. Serve a rispondere a una domanda
# precisa: json.loads dell'intero blob (2.00 ms per pagina da 112), le SELECT puntuali (0.53 ms) e le
# build_url (3.16 ms) sommano ~5.7 ms su una costruzione che ne misura ~130. Il 95% sta altrove, e
# "altrove" sono le chiamate all'API C++ di Kodi. Questa misura dice QUALI.
# Ogni elemento fa una sola list.append (atomica sotto GIL, quindi niente lock fra i thread del pool)
# di una tupla di durate; la somma per fase avviene alla fine, nel thread principale.
_ITEM_PHASES = []
# Sotto-fasi dentro movie_meta: (meta_language, lettura di cache). Separate perche' la fase "meta"
# misurata in Kodi (1.5 ms/elemento) e' 60 volte il costo di SELECT + json.loads misurato fuori.
_META_PHASES = []

def phase_reset():
	if PERF:
		del _ITEM_PHASES[:]
		del _META_PHASES[:]

def phase_record(*durations):
	if PERF: _ITEM_PHASES.append(durations)

def phase_record_meta(*durations):
	if PERF: _META_PHASES.append(durations)

# Variante di phase_report che riceve le righe INVECE di leggerle dalle liste globali.
# Serve dove piu' costruzioni girano nello STESSO interprete e nello STESSO momento: 'continua a
# guardare' ne avvia fino a tre in parallelo (film in pausa, episodi in pausa, prossimi episodi) e
# ognuna chiamerebbe phase_reset(), cancellando le misure delle altre. Con le righe accumulate in una
# lista locale alla singola invocazione il conflitto non esiste, e le tre misure restano separate.
def phase_report_rows(kind, labels, rows, extra=''):
	if not PERF: return
	try:
		from modules.kodi_utils import logger
		if not rows: return
		n = len(rows)
		totals = [sum(r[i] for r in rows) for i in range(len(labels))]
		grand = sum(totals) or 1e-9
		# Somma dei tempi di THREAD, non tempo di parete: con il pool a N worker la somma supera
		# la durata reale della costruzione. Il valore utile e' la QUOTA relativa fra le fasi.
		# Il numero di worker va stampato insieme alla misura: senza, confrontare due log di sessioni
		# diverse significa fidarsi di come era impostato il dispositivo in quel momento.
		try:
			from modules.utils import WORKER_COUNT as workers
		except: workers = '?'
		logger('FenLight PERF FASI', '%s | %s elementi | worker %s | somma thread %.0f ms%s | %s'
				% (kind, n, workers, grand * 1000, extra,
					' + '.join('%s %.0fms (%.0f%%)' % (labels[i], totals[i] * 1000, 100.0 * totals[i] / grand)
								for i in range(len(labels)))))
	except: pass

def phase_report(kind, labels):
	if not PERF: return
	try:
		from modules.kodi_utils import logger
		phase_report_rows(kind, labels, list(_ITEM_PHASES))
		mrows = list(_META_PHASES)
		if mrows:
			m_lang = sum(r[0] for r in mrows)
			m_cache = sum(r[1] for r in mrows)
			m_tot = (m_lang + m_cache) or 1e-9
			logger('FenLight PERF META', '%s | %s letture | meta_language %.0fms (%.0f%%) + lettura cache %.0fms (%.0f%%) | %.2f ms/elemento'
					% (kind, len(mrows), m_lang * 1000, 100.0 * m_lang / m_tot,
						m_cache * 1000, 100.0 * m_cache / m_tot, m_tot * 1000 / len(mrows)))
	except: pass

# Autotest UNA TANTUM per costruzione. La domanda a cui deve rispondere adesso e' una sola: il costo
# di una fase e' proporzionale al NUMERO DI CHIAMATE verso il C++ di Kodi, o al NUMERO DI CHIAVI/VOCI
# che ogni chiamata trasporta? Le due risposte portano a correzioni opposte -- consolidare le chiamate
# oppure ridurre il contenuto -- quindi va misurata, non dedotta.
# Sul Mi Stick le tre fasi rimaste (ctxmenu 37%, props 23%, infotag 17%) sono tutte attraversamenti
# verso l'API C++, e valgono il 77% della costruzione.
# Confronto chiave: N setProperty singole contro UNA setProperties con le stesse N chiavi. Se i due
# tempi si somigliano il costo e' per chiave; se la seconda e' molto piu' rapida il costo e' per
# chiamata, e allora conviene accorpare (il menu contestuale si puo' scrivere come proprieta').
# Il vecchio autotest su json ha gia' risposto (acceleratore C presente, ~0.03 ms/blob su Mac) e
# sulla stick costava 130-320 ms per costruzione: rimosso.
# Misurato sulla stick il 22/08: l'autotest costava 42.7 + 31.3 ms di setProperty piu' 5 giri di
# addContextMenuItems a 9.49 ms -- circa 100 ms per OGNI costruzione, pagati anche durante la tempesta
# post-riproduzione, cioe' proprio quando la macchina e' satura. Le risposte che doveva dare le ha
# gia' date (il costo e' per chiamata, non per chiave; sotto contesa tutto si moltiplica per 70-90).
# Resta accendibile a mano quando serve rimisurare, ma non deve piu' pesare sull'uso normale.
PERF_SELFTEST = False

def selftest():
	if not (PERF and PERF_SELFTEST): return
	try:
		from time import perf_counter
		from xbmcgui import ListItem
		from modules.kodi_utils import logger
		N, REP = 30, 5
		props = dict(('fenlight.bench%s' % i, 'valore%s' % i) for i in range(N))
		cm = [('voce %s' % i, 'RunPlugin(plugin://plugin.video.fenlight/?mode=bench&i=%s)' % i) for i in range(7)]

		li = ListItem(offscreen=True)
		t0 = perf_counter()
		for k, v in props.items(): li.setProperty(k, v)
		t1 = perf_counter()

		li2 = ListItem(offscreen=True)
		t2 = perf_counter()
		li2.setProperties(props)
		t3 = perf_counter()

		li3 = ListItem(offscreen=True)
		t4 = perf_counter()
		for _ in range(REP): li3.addContextMenuItems(cm)
		t5 = perf_counter()

		li4 = ListItem(offscreen=True)
		tag = li4.getVideoInfoTag()
		t6 = perf_counter()
		for _ in range(REP):
			tag.setTitle('x'), tag.setPlot('y'), tag.setYear(2020), tag.setRating(7.5), tag.setMpaa('T')
		t7 = perf_counter()

		singola, insieme = (t1 - t0) * 1000, (t3 - t2) * 1000
		ctx, setter = (t5 - t4) * 1000 / REP, (t7 - t6) * 1000 / (REP * 5)
		logger('FenLight PERF API', '%s chiavi: %s setProperty singole %.1f ms (%.3f ms/chiave) contro UNA '
				'setProperties %.1f ms (%.3f ms/chiave) -> accorpare rende %.1fx | addContextMenuItems(7 voci) '
				'%.2f ms/chiamata | setter infotag %.3f ms/chiamata'
				% (N, N, singola, singola / N, insieme, insieme / N,
					(singola / insieme) if insieme else 0, ctx, setter))
	except: pass

def log_network(kind, count, seconds):
	# Voci risolte in rete perche' non servite dal prefetch. Riga distinta da quella del prefetch:
	# li' "gia' in cache" ha un senso, qui no -- sono per definizione tutte assenti dalla cache.
	if not PERF: return
	try:
		from modules.kodi_utils import logger
		logger('FenLight PERF RETE', '%s | %s voci non in cache risolte in rete | %.0f ms (%.0f ms/voce)'
				% (kind, count, seconds * 1000, (seconds * 1000 / count) if count else 0))
	except: pass

def log_prefetch(kind, requested, hits, seconds):
	if not PERF: return
	try:
		from modules.kodi_utils import logger
		logger('FenLight PERF PREFETCH', '%s | %s richiesti, %s gia\' in cache (%.0f%%) | lettura unica %.1f ms'
				% (kind, requested, hits, (100.0 * hits / requested) if requested else 0, seconds * 1000))
	except: pass

def now():
	from time import time
	return time()

def log_build(kind, action, t_start, t_resolved, t_built, count, pages=None, path_pages=None):
	if not PERF: return
	_INVOCATIONS[0] += 1
	try:
		from modules.kodi_utils import logger
		total = t_built - t_start
		per_item = (total / count * 1000) if count else 0
		# path_pages e' il ?pages= arrivato dal path del widget: e' il dato che dice se la ricarica
		# mirata sta reggendo lo stato. Se dopo una riproduzione ricompare vuoto, il token si e' perso.
		try:
			from modules.utils import WORKER_COUNT as workers
		except: workers = '?'
		# La costruzione si stampa in MILLISECONDI: con %.2fs la granularita' era 10 ms su misure che
		# ormai valgono 20-40 ms, quindi il log non avrebbe potuto mostrare un miglioramento anche
		# quando c'era. La risoluzione resta in secondi: li' i tempi sono di rete, ordini di grandezza
		# piu' grandi.
		build_ms = (t_built - t_resolved) * 1000
		# PERF: distanza dall'uscita dal player, quando e' recente. La PRIMA riga che la riporta dopo
		# una chiusura e' la rilettura che fa Kodi per conto suo: e' il numero contro cui tarare il
		# sleep(2000) di run_media_progress, oggi scelto a occhio.
		since_close = ''
		# LOTTO 113: le stesse distanze anche dal Select e da Player.OnPlay. Sono i due estremi della
		# finestra di transizione -- l'unica in cui i widget si ricostruiscono davvero, ora che il
		# cancello e' stato tolto -- e servono a rispondere con dei numeri alla domanda "quanto lavoro
		# di interfaccia cade addosso all'avvio del film?". Tre letture di proprieta', nessuna
		# scrittura: al contrario di _diag_note non c'e' contesa fra i processi che si costruiscono
		# in parallelo, per questo si puo' tenere accesa sempre.
		try:
			from modules.kodi_utils import get_property, SELECT_PROP, PLAYBACK_START_PROP, playback_running
			for _prop, _etichetta, _tetto in ((SELECT_PROP, 'Select', 60), (PLAYBACK_START_PROP, 'OnPlay', 60),
												('fenlight.perf.closefile', 'CloseFile', 30)):
				# il float si protegge da solo: un timbro storpiato non deve far sparire le altre
				# due distanze dalla riga, che e' cio' che succedeva con un try unico attorno al giro.
				try: _c = float(get_property(_prop) or 0)
				except: continue
				if not _c: continue
				_d = t_built - _c
				if 0 < _d < _tetto: since_close += ' | +%.0f ms da %s' % (_d * 1000, _etichetta)
			if playback_running(): since_close += ' | riproduzione in corso'
		except: pass
		logger('FenLight PERF', '%s %s | %s elementi%s%s | worker %s | totale %.2fs = risoluzione %.2fs + costruzione %.0f ms (%.3f ms/elemento) | %.1f ms/elemento totale | inv=%s'
				% (kind, action, count, (' | %s pagine' % pages) if pages else '',
					(' | path_pages=%s' % path_pages) if path_pages not in (None, '', 0, '0') else ' | path_pages=-',
					workers, total, t_resolved - t_start, build_ms, (build_ms / count) if count else 0,
					per_item, _INVOCATIONS[0]) + since_close + _diag_note(t_built))
	except: pass

def make_key(params):
	# IMPRONTA DEL CONTENUTO: quale lista e' questa. Ignora i parametri volatili e la posizione.
	# Non e' piu' l'identita' del widget (vedi widget_key): serve a rispondere a "in questa posizione
	# e' cambiata la lista?", che e' l'unica ragione per cui un conteggio pagine va azzerato.
	if not isinstance(params, dict):
		params = dict(parse_qsl(params, keep_blank_values=True))
	items = sorted((k, v) for k, v in params.items() if k not in _VOLATILE_PARAMS)
	canonical = '&'.join('%s=%s' % (k, v) for k, v in items)
	return md5(canonical.encode('utf-8')).hexdigest()

def position_of(params):
	"""(scope, id contenitore) letti dal path, o (None, None) se la skin non li ha messi.

	Il valore si convalida: deve essere 'scope.id' con scope alfanumerico e id numerico. Un path
	storpiato non deve poter produrre un nome di proprieta' arbitrario.
	"""
	if not isinstance(params, dict):
		params = dict(parse_qsl(params, keep_blank_values=True))
	raw = (params.get(CTL_PARAM) or '').strip()
	if not raw or '.' not in raw: return None, None
	scope, _, cid = raw.rpartition('.')
	if not scope or not cid: return None, None
	if not cid.isdigit(): return None, None
	if not scope.replace('_', '').isalnum(): return None, None
	return scope, cid

def widget_key(params):
	"""IDENTITA' del widget. La posizione quando la skin la fornisce, altrimenti il contenuto.

	La chiave finisce dentro i nomi delle proprieta' (PAGES_PROP e compagnia), quindi con la posizione
	diventano leggibili nel log: 'fenlight.pg.home.502.pages' invece di un md5.

	La RICADUTA sull'impronta del contenuto non e' un ripiego elegante: e' cio' che tiene in piedi i
	contenitori che la skin non genera. Se un widget paginabile arriva senza 'pgctl' la paginazione
	continua a funzionare come prima -- collisioni comprese -- e lo si dice a voce alta in
	diagnostica, invece di spegnersi in silenzio (vedi il lotto 90: un guasto muto e' costato due
	giorni).
	"""
	scope, cid = position_of(params)
	if scope: return '%s.%s' % (scope, cid)
	return make_key(params)

_WARNED_NO_POSITION = set()

def _warn_no_position(params):
	# Una riga per modo, non una per build: e' un guasto di configurazione (file generato della skin
	# non aggiornato, o un <content> scritto a mano), non un evento. Il modo basta a dire QUALE widget
	# guardare.
	try:
		mode = (params.get('mode') if isinstance(params, dict) else None) or '?'
		if mode in _WARNED_NO_POSITION: return
		_WARNED_NO_POSITION.add(mode)
		from modules.kodi_utils import logger
		logger('Fen Light', 'paginazione: il widget "%s" arriva senza "%s" nel path, quindi si identifica '
				'ancora dal contenuto (identificazione collidibile, vedi lotto 91). Il file generato della '
				'skin e\' vecchio rispetto ai suoi .xmltemplate: rigenerarlo alzando "buildv" in '
				'shortcuts/skinvariables-generator.json.' % (mode, CTL_PARAM))
	except: pass

def query_from_path(folderpath):
	# Extracts the query dict from a plugin:// folder path (the part after '?').
	if not folderpath: return {}
	query = folderpath.split('?', 1)[1] if '?' in folderpath else ''
	return dict(parse_qsl(query, keep_blank_values=True))

def _item_url(item):
	# Plugin path di UN elemento della lista passata ad add_items. Gli indexer usano due forme: la tupla
	# (url, listitem, isfolder) oppure la forma con ordinamento di movies/tvshows ((url, li, isf), pos).
	if item is None: return None
	if isinstance(item, (list, tuple)) and item and isinstance(item[0], (list, tuple)):
		item = item[0]
	try: return item[0]
	except: return None

def _first_item_url(items):
	# Extract the first item's plugin path from the list handed to add_items. Indexers use either the
	# add_items tuple (url, listitem, isfolder) or the movies/tvshows custom-order shape ((url, li, isf), pos).
	if not items: return None
	return _item_url(items[0])

# Quanti elementi di testa entrano nella firma del contenitore. UNO NON BASTA, ed e' misurato: nel log
# zd del 25/08 il widget della Home 'Latest releases' (chiave a14a8652) e Trakt Trending nell'hub
# (dd289980) avevano lo stesso primo elemento, byte per byte:
#     plugin://plugin.video.fenlight/?mode=playback.media&media_type=movie&tmdb_id=1084244
# Due liste diverse di due finestre diverse, stesso film in cima -- che per 'ultime uscite' e
# 'di tendenza' e' la norma, non la sfortuna. Stesso URL -> stesso md5 -> UNA sola voce in HEAD_PROP,
# vinta da chi ha costruito per ultimo. Da li' il watcher identificava il contenitore sbagliato e il
# controllo di cambio inquilino azzerava il token del widget SBAGLIATO: Trending crollava da 114
# elementi a 27 e la Home da 100 a 48, a ogni passaggio fra le due finestre. Vedi lotto 91.
# Tre elementi perche' la lista e' append-only: i primi tre non cambiano mai mentre il widget si
# allunga, quindi la firma resta stabile fra una pagina e l'altra -- che e' la condizione per cui
# questo meccanismo esiste. Due liste che condividono i primi TRE titoli nello stesso ordine sono
# la stessa lista.
HEAD_ITEMS = 3

def head_signature(urls):
	# Firma di un contenitore a partire dai path dei suoi primi elementi. La calcolano i due lati:
	# la build dagli elementi appena consegnati, il watcher dalle infolabel. Devono coincidere, quindi
	# la regola sta scritta in un posto solo.
	# Degrada da sola su liste corte (meno di HEAD_ITEMS elementi): con un elemento torna esattamente
	# la firma di prima. Un widget cosi' corto non pagina, quindi non ha niente da perdere.
	urls = [u for u in (urls or []) if u]
	if not urls: return None
	return md5('\n'.join(urls[:HEAD_ITEMS]).encode('utf-8')).hexdigest()

def _head_signature_from_items(items):
	if not items: return None
	return head_signature([_item_url(i) for i in items[:HEAD_ITEMS]])

# Ogni URL di elemento porta 'tmdb_id=' (URL_PLAY, URL_OPTIONS, URL_MARK... in tutti gli indexer),
# quindi gli id si estraggono senza dover conoscere la forma dei dati di ciascuno.
_TMDB_IN_URL = re_compile(r'[?&]tmdb_id=(\d+)')
# LOTTO 119 -- l'identita' a livello EPISODIO. Il tmdb_id di un episodio E' quello della serie: nel
# canale degli id 'S03E04 di X in pausa' e 'la serie X' erano la stessa stringa, quindi un
# avanzamento su un episodio ricaricava OGNI widget che contenesse quella serie -- le serie popolari,
# i preferiti, tutto. L'URL di riproduzione di un episodio (episodes.URL_PLAY) porta gia' stagione ed
# episodio: da li' esce la tripla, che si pubblica ACCANTO al tmdb nudo e non al suo posto.
#   'X'       -> la serie, per gli eventi di livello serie (un episodio visto la fa avanzare)
#   'X:3:4'   -> quel singolo episodio, per gli eventi di avanzamento
# Un widget di serie pubblica solo 'X' e resta cosi' fuori da un paused_at su un episodio; 'continua
# a guardare' pubblica entrambe e risponde a tutti e due i livelli. La forma della tripla ha una
# sola definizione, kodi_utils.episode_uid, condivisa con chi la CHIEDE (apis/trakt_api).
_EPISODE_IN_URL = re_compile(r'[?&]media_type=episode(?=[?&]|$)')
_SEASON_IN_URL = re_compile(r'[?&]season=(\d+)')
_EPNUM_IN_URL = re_compile(r'[?&]episode=(\d+)')

def _episode_uid_from_url(url, tmdb_id):
	# 'season=all' (URL_ALL_EPISODES) e le voci di menu senza S/E non hanno identita' di episodio:
	# tornano None e restano al solo livello serie.
	if not _EPISODE_IN_URL.search(url): return None
	s, e = _SEASON_IN_URL.search(url), _EPNUM_IN_URL.search(url)
	if not s or not e: return None
	from modules.kodi_utils import episode_uid
	return episode_uid(tmdb_id, s.group(1), e.group(1))

# LOTTO 95 -- gli id NASCOSTI dal filtro doppiaggio in attesa di verdetto (vedi modules/dub_queue).
# Vivono in una lista di modulo e non in una proprieta' perche' non devono attraversare i processi:
# chi li mette (dub_keep_mask) e chi li legge (_publish_ids, poche righe di codice piu' tardi) stanno
# nella STESSA invocazione. La filtratura gira sempre prima della costruzione, quindi quando set_head
# passa la lista e' gia' completa.
_DEFERRED_IDS = []
# Contatore separato dalla lista, e VOLUTAMENTE mai azzerato dentro l'invocazione: _DEFERRED_IDS lo
# svuota _publish_ids alla fine, mentre questo deve restare valido per tutta la costruzione. Lo legge
# il riempimento delle pagine -- vedi deferred_count.
_DEFERRED_COUNT = [0]

def defer_ids(ids):
	for i in ids or []:
		if i:
			_DEFERRED_IDS.append(str(i))
			_DEFERRED_COUNT[0] += 1

def deferred_count():
	"""Quanti elementi questa costruzione ha nascosto in attesa del verdetto (lotto 95).

	Serve ai cicli di RIEMPIMENTO -- load_cumulative(min_items) qui, _dub_paginate in trakt_lists --
	che tirano altre pagine grezze finche' non hanno abbastanza SOPRAVVISSUTI. Senza questo conteggio
	un elemento rimandato conta come scartato, e su cache fredda ogni riempimento andrebbe dritto al
	suo tetto (12 pagine in piu', con tutti i metadati che comporta) inseguendo elementi che stanno
	per ricomparire da soli -- trascinando per giunta altri titoli ignoti dentro la coda. Un elemento
	rimandato e' un elemento che sara' li' fra pochi secondi: per il riempimento vale come presente.
	"""
	return _DEFERRED_COUNT[0]

def _publish_ids(key, items):
	# Pubblica gli id di cui questo widget si occupa, per la ricarica mirata. Best-effort: se fallisce,
	# refresh_containers_for_ids non riesce a escludere il widget e lo ricostruisce -- prudente, non rotto.
	try:
		from modules.kodi_utils import set_property
		ids, seen = [], set()
		for item in items or []:
			url = _item_url(item)
			if not url: continue
			m = _TMDB_IN_URL.search(url)
			if not m: continue
			tid = m.group(1)
			if tid not in seen:
				seen.add(tid); ids.append(tid)
			# Livello EPISODIO in aggiunta, mai al posto del livello serie (lotto 119): il tmdb nudo
			# serve ancora a rispondere 'questo widget contiene la serie X?', che e' la domanda giusta
			# quando un episodio viene VISTO.
			euid = _episode_uid_from_url(url, tid)
			if euid and euid not in seen:
				seen.add(euid); ids.append(euid)
		# "Si occupa" comprende cio' che ha NASCOSTO. Un elemento tolto dal filtro doppiaggio non
		# compare fra gli item, quindi senza questa aggiunta il contenitore che lo ha nascosto sarebbe
		# proprio quello che refresh_containers_for_ids salta -- e il verdetto risolto dal servizio non
		# arriverebbe mai a schermo. E' l'unico punto che tiene insieme il punto 3 e la ricarica mirata.
		for tid in _DEFERRED_IDS:
			if tid in seen: continue
			seen.add(tid); ids.append(tid)
		del _DEFERRED_IDS[:]
		set_property(IDS_PROP % key, ','.join(ids))
	except: pass

def _register(key, headhash):
	# Append this build's key to the registry (newest last, no duplicates) and prune the oldest
	# entries past REGISTRY_CAP, clearing each dropped widget's leftover properties. Best-effort:
	# the read-modify-write isn't locked, but a lost/duplicate entry only ever leaves a stale prop
	# behind -- it can never break a live widget's pagination.
	from modules.kodi_utils import get_property, set_property, clear_property
	# headhash puo' essere piu' di una firma (a tre elementi e a uno solo, vedi set_head): si conservano
	# tutte separate da '|', o la pulizia lascerebbe indietro le voci non citate.
	if not isinstance(headhash, (list, tuple)): headhash = [headhash] if headhash else []
	entry = '%s:%s' % (key, '|'.join(h for h in headhash if h))
	raw = get_property(REGISTRY_PROP)
	entries = [e for e in raw.split(',') if e] if raw else []
	if entry in entries: entries.remove(entry)
	entries.append(entry)
	while len(entries) > REGISTRY_CAP:
		old_key, _, old_head = entries.pop(0).partition(':')
		clear_property(PAGES_PROP % old_key)
		clear_property(HASMORE_PROP % old_key)
		clear_property(BUILT_PROP % old_key)
		clear_property(LOADING_PROP % old_key)
		clear_property(LASTBUILD_PROP % old_key)
		clear_property(IDS_PROP % old_key)
		clear_property(ACTION_PROP % old_key)
		for h in old_head.split('|'):
			if h: clear_property(HEAD_PROP % h)
	set_property(REGISTRY_PROP, ','.join(entries))

def set_head(key, items, action=None):
	# Final step of an interactive build (called right after add_items). Publishes:
	#  - the first item's path -> widget key, so the watcher can identify the focused container;
	#  - the count of items actually shown (BUILT_PROP), the watcher's catch-up gate;
	# and clears LOADING here -- not in set_state -- so the watcher can't re-fire in the window
	# between set_state and the new page actually surfacing.
	from modules.kodi_utils import set_property, clear_property
	count = len(items) if items else 0
	set_property(BUILT_PROP % key, str(count))
	# Il tetto si applica QUI e non in set_state: questo e' l'unico punto che conosce quanti elementi
	# sono stati COSTRUITI davvero, cioe' dopo il filtro doppiaggio. Spegnere has_more e' il segnale
	# che il watcher legge per decidere se caricare oltre; applicare invece un tetto a raw_pages
	# accorcerebbe una lista gia' mostrata a ogni ricostruzione, facendo saltare la posizione --
	# esattamente cio' che il paginatore esiste per evitare.
	cap = max_items()
	if count >= cap:
		set_property(HASMORE_PROP % key, 'false')
		from modules.kodi_utils import logger
		logger('Fen Light', 'DIAG paginazione: tetto di %s elementi raggiunto (%s costruiti), il widget non si allunga oltre' % (cap, count))
	url = _first_item_url(items)
	# Due firme, e la seconda e' una rete di sicurezza, non un ripensamento. Quella a tre elementi e'
	# la buona ed e' quella che il watcher prova per prima. Quella a un elemento -- il comportamento di
	# prima, collisioni comprese -- resta pubblicata perche' il watcher legge i suoi tre path da
	# Container(id).ListItemAbsolute(1|2).FolderPath: se in qualche stato quelle infolabel tornassero
	# vuote, senza la seconda firma il contenitore diventerebbe NON identificabile e la paginazione si
	# fermerebbe del tutto. Cosi' il caso peggiore e' tornare a com'era, non peggio.
	headhash = _head_signature_from_items(items)
	headhash_one = head_signature([url]) if url else None
	for h in (headhash, headhash_one):
		if h: set_property(HEAD_PROP % h, key)
	clear_property(LOADING_PROP % key)
	# Fine dichiarata della costruzione (lotto 106): set_head e' l'ultimo passo di una build, chiamato
	# subito dopo add_items. Da qui in poi questo widget non e' piu' in volo.
	mark_build_end(key)
	_publish_ids(key, items)
	if action: set_property(ACTION_PROP % key, str(action))
	_note_head_change(key, url, action)
	_register(key, (headhash, headhash_one))
	# Il censimento (registry_add) passa solo sui contenitori A SCHERMO, e all'avvio i widget spesso
	# finiscono di costruirsi dopo che l'utente ha gia' cambiato finestra: il 28/08 alle 20:18 la Home
	# e' stata lasciata 2 s prima che i suoi widget pubblicassero la testa, quindi 'home:502' non e'
	# mai entrato nel registro. Da li' una ricarica mirata lanciata da un hub trovava 'altre finestre 0',
	# non poteva invalidare i token della Home -- che restava vecchia -- e faceva scattare la rete di
	# sicurezza di kodi_refresh_ids, che riarmava il rinvio: consumato ogni 10 s nella stessa finestra,
	# all'infinito (tre giri nel log delle 20:18-20:19 prima che la sessione finisse).
	# Chi pubblica la propria testa E' per definizione una coppia (finestra, contenitore) nota: non ha
	# senso aspettare che il censimento a schermo se ne accorga. registry_add e' idempotente, quindi il
	# passaggio del censimento resta la rete di recupero se questa scrittura si perde per contesa --
	# read-modify-write su proprieta' condivisa, lo stesso schema del lotto 3, ma qui una volta per
	# costruzione di widget e non per elemento.
	try:
		_scope, _, _cid = key.partition('.')
		if _scope and _cid: registry_add(_scope, _cid)
	except: pass
	log('set_head key=%s built=%s firma=%s first_url=%s' %
		(short(key), count, (headhash[:8] if headhash else '-'), (url[:90] if url else '-')))

def _note_head_change(key, url, action=None):
	"""Se la testa di 'continua a guardare' e' cambiata, chiede al watcher di riportare la riga a 1.

	Perche' serve, misurato sulla stick il 03/09. Alle 16:02:39 un film messo in pausa dal Mac entra
	nel widget IN TESTA (`first_url=...media_type=movie&tmdb_id=1232569`, 7 elementi). Kodi, ricaricando
	un contenitore, conserva l'ELEMENTO su cui eri, non la posizione: l'elemento su cui stava il fuoco
	e' scivolato da 1 a 2 e il fuoco l'ha seguito (`current=1/6` prima, `current=2/7` dopo). La riga si
	disegna a partire dall'elemento col fuoco, quindi il film era li' ma un posto piu' a sinistra,
	fuori campo. Il log lo dimostra due volte con i tasti dell'utente: alle 15:59:37 un `Left` porta
	`current` da 2 a 1 e l'elemento nuovo si vede; alle 16:03:19 `Down`+`Up` non spostano niente dentro
	la riga e infatti resta `2/7`; alle 16:11:58 un `Back` riporta a `1/7` -- 'e' comparso'.

	Vale SOLO per 'continua a guardare', per scelta dell'utente: e' la lista il cui senso e' che la cosa
	piu' recente sta in testa, e un arrivo che atterra fuori campo non serve a niente. Su ogni altro
	widget il fuoco resta dov'e', perche' li' l'ordine non e' una promessa e strattonare chi sta
	scorrendo sarebbe solo un fastidio.

	Alla PRIMA costruzione non si alza niente: non c'e' una testa precedente da confrontare, e un
	contenitore appena nato parte gia' dal primo elemento.
	"""
	if not url: return
	from modules.kodi_utils import set_property, get_property, CONTINUE_WATCHING_ACTION
	precedente = get_property(FIRSTURL_PROP % key)
	set_property(FIRSTURL_PROP % key, url)
	if not precedente or precedente == url: return
	# L'azione arriva dal costruttore quando la passa; se non la passa vale quella gia' pubblicata,
	# che e' la stessa cosa scritta un attimo prima. Il confronto e' per prefisso qualificato, come
	# ovunque: 'continue_watching' copre anche un eventuale 'continue_watching:movie'.
	azione = str(action) if action else get_property(ACTION_PROP % key)
	if not _action_matches(azione, {CONTINUE_WATCHING_ACTION}): return
	rehead_queue(key)

def rehead_queue(key):
	"""Mette questo widget in coda per il riposizionamento. Idempotente.

	Read-modify-write su una proprieta' condivisa, lo stesso schema del lotto 3: in contesa si puo'
	perdere una scrittura. Il danno peggiore e' una riga che resta dov'e' fino alla prossima testa
	nuova -- cioe' il comportamento di prima -- quindi non vale un lucchetto.
	"""
	from modules.kodi_utils import set_property
	coda = rehead_pending()
	if key in coda: return
	coda.append(key)
	set_property(REHEAD_PROP, ','.join(coda))

def rehead_pending():
	"""Le chiavi in attesa di essere riportate a inizio riga, in ordine di arrivo."""
	from modules.kodi_utils import get_property
	return [k for k in (get_property(REHEAD_PROP) or '').split(',') if k]

def rehead_done(key):
	"""Toglie una chiave dalla coda. La chiama il watcher DOPO aver agito."""
	from modules.kodi_utils import set_property, clear_property
	rimaste = [k for k in rehead_pending() if k != key]
	if rimaste: set_property(REHEAD_PROP, ','.join(rimaste))
	else: clear_property(REHEAD_PROP)

def _action_matches(stored, wanted_actions):
	"""L'azione pubblicata da un widget soddisfa una delle azioni richieste?

	Le azioni sono qualificate per tipo di media da chi le pubblica ('trakt_watchlist:movie'), perche'
	lo stesso nome di azione costruisce DUE widget diversi -- la watchlist film e la watchlist serie --
	e aggiungere un film non ha motivo di ricostruire quella delle serie.

	Il confronto e' asimmetrico apposta: una richiesta NON qualificata vale per tutti i qualificatori
	(chi chiede 'trakt_watchlist' vuole entrambi), una richiesta qualificata pretende l'uguaglianza
	esatta. Cosi' i chiamanti che non hanno motivo di distinguere restano scritti come prima.
	"""
	if not stored or not wanted_actions: return False
	if stored in wanted_actions: return True
	return stored.partition(':')[0] in wanted_actions

def refresh_containers_for_ids(ids, actions=()):
	"""Ricostruisce SOLO i contenitori toccati da questi tmdb_id. Torna quanti ne ha ricaricati.

	La regola e' volutamente PRUDENTE: si salta un contenitore soltanto quando si riesce a dimostrare
	che non c'entra -- cioe' lo si e' identificato E il suo elenco di id non contiene nessuno di
	quelli cambiati. Tutto il resto viene ricaricato: un widget che non passa dal paginatore non ha
	ne' chiave ne' elenco, e continua ad aggiornarsi come prima invece di restare fermo.

	ATTENZIONE, e qui il commento precedente era rimasto indietro di un lotto: 'continua a guardare'
	NON e' piu' fra quelli. Dal lotto 114 chiama set_head (continue_watching.py) e quindi pubblica il
	suo elenco, il che ribalta la conseguenza: quando un titolo ENTRA nel widget il suo id non e'
	ancora nell'elenco, la prudenza non lo copre piu' e il contenitore viene SALTATO proprio nel
	momento in cui andrebbe ricostruito. Per quel widget l'AZIONE non e' un affinamento della regola
	per id: e' la condizione perche' funzioni. Vedi CONTINUE_WATCHING_ACTION.

	Le azioni si confrontano per PREFISSO qualificato (vedi _action_matches): 'trakt_watchlist:movie'
	e 'trakt_watchlist:tvshow' sono due widget distinti e vanno colpiti separatamente, ma chi chiede
	'trakt_watchlist' senza qualificatore li prende entrambi.

	Torna 0 se non identifica nessun contenitore Fen Light: il chiamante ricade sul refresh globale,
	quindi il comportamento non puo' essere peggiore di quello di oggi.
	"""
	from modules.kodi_utils import get_property, set_property, getCurrentWindowId
	# Dentro la finestra Video (10025) i controlli 500-528 NON sono widget: sono le viste della
	# finestra stessa (Includes_Views.xml: <views>500,501,...,521,...,528</views>). Il token delle
	# pagine non le governa, quindi impostarlo non ricarica nulla -- ma conterebbe come successo e
	# impedirebbe il fallback globale, che li' e' l'unico modo di rileggere la cartella aperta.
	# Finora il difetto restava latente perche' l'intervallo si ferma a 520 e la vista in uso era la
	# 521: con una vista fra 500 e 520 il refresh sarebbe sparito nel nulla in silenzio.
	try:
		if getCurrentWindowId() == 10025: return 0
	except: pass
	wanted = set(str(i) for i in (ids or []) if i)
	# Le azioni sono la scorciatoia per i widget che cambiano COMPOSIZIONE invece che stato: vanno
	# ricostruiti per quello che SONO, non per quello che contengono.
	wanted_actions = set(str(a) for a in (actions or ()) if a)
	if not wanted and not wanted_actions: return 0
	from time import time
	nonce = '%d' % (time() * 1000)
	# Lo scope si legge UNA volta: la finestra non cambia a meta' di questo ciclo.
	scope = ctl_scope()
	seen_any, hit, hit_other, skipped = False, 0, 0, 0
	identified = set()
	for cid in WIDGET_CONTAINER_IDS:
		key, first_url = container_head(cid, scope)
		if not first_url or 'plugin.video.fenlight' not in first_url: continue
		seen_any = True
		identified.add(str(cid))
		if key and not _action_matches(get_property(ACTION_PROP % key), wanted_actions):
			stored = get_property(IDS_PROP % key)
			# stored vuota = elenco mai pubblicato: non si puo' dimostrare niente, quindi si ricarica.
			if stored and not wanted.intersection(stored.split(',')):
				skipped += 1
				continue
		# Il token vive nel <content> come $INFO[], quindi cambiarne il valore ricarica SOLO questo
		# contenitore. Il numero di pagine va conservato tale e quale -- e' quello che l'utente vede --
		# e il nonce si accoda come parametro a parte: 'reload' e' in _VOLATILE_PARAMS, quindi non
		# entra nella chiave del widget e la paginazione non lo nota.
		pages = (get_property(CTL_PAGES_PROP % (scope, cid)) or '').split('&')[0]
		if not pages: pages = str(raw_pages(key, initial_batch())) if key else str(initial_batch())
		set_property(CTL_PAGES_PROP % (scope, cid), '%s&%s=%s' % (pages, RELOAD_PARAM, nonce))
		hit += 1
	# --- QUESTA finestra, i contenitori che l'infolabel non ha saputo leggere -----------------------
	# container_head interroga una infolabel VIVA, e un contenitore che Kodi non ha ancora popolato non
	# risponde: il `continue' la' sopra lo scartava senza contarlo da nessuna parte -- ne' ricaricato,
	# ne' saltato, ne' seen_any. Non era un contenitore dimostrato estraneo: era un contenitore mai
	# guardato, e l'unico modo di accorgersene era sapere a memoria quanti widget ha quella schermata.
	# Misurato sulla stick il 02/09 alle 21:53:04.698: la Home ha TRE widget, tutti e tre avevano gia'
	# fatto set_head, e il censimento ne ha visti due (`ricaricati=1 saltati=1'). Sul Mac, dove le
	# costruzioni durano decimi di secondo, il conto torna sempre (5 su 5). E' una corsa fra noi e la
	# GUI, e la vince chi ha la macchina lenta -- cioe' si perde proprio dove fa piu' male.
	# La correzione non aspetta e non riprova: NON SERVE l'infolabel. Serviva solo a rispondere
	# 'questo contenitore e' nostro?', e il registro lo sa gia' -- e' esattamente il criterio con cui
	# il giro qui sotto raggiunge le finestre che non sono nemmeno a schermo. Stessa regola del giro
	# a schermo, altra fonte: si salta solo cio' che si dimostra estraneo, il resto si ricarica.
	unresolved, recovered = 0, 0
	for pair in registry_pairs():
		pair_scope, _, cid = pair.partition(':')
		if pair_scope != scope or cid in identified: continue
		key = '%s.%s' % (scope, cid)
		if not get_property(BUILT_PROP % key): continue
		unresolved += 1
		seen_any = True
		if not _action_matches(get_property(ACTION_PROP % key), wanted_actions):
			stored = get_property(IDS_PROP % key)
			# Elenco vuoto = mai pubblicato: non si dimostra niente, quindi si ricarica. Qui, a
			# differenza del giro sulle altre finestre, il contenitore E' a schermo: lasciarlo stare
			# vorrebbe dire lasciare un widget visibile con il dato vecchio.
			if stored and not wanted.intersection(stored.split(',')):
				skipped += 1
				continue
		pages = (get_property(CTL_PAGES_PROP % (scope, cid)) or '').split('&')[0]
		if not pages: pages = str(raw_pages(key, initial_batch()))
		set_property(CTL_PAGES_PROP % (scope, cid), '%s&%s=%s' % (pages, RELOAD_PARAM, nonce))
		hit += 1
		recovered += 1

	# --- le ALTRE finestre -------------------------------------------------------------------------
	# Fin qui si e' guardata solo la finestra a schermo, perche' e' l'unica che le infolabel sanno
	# leggere. Ma un widget della Home che contiene il film appena cambiato e' vecchio anche se in
	# questo momento non si vede, e restava vecchio: dall'hub si aggiornava l'hub, dalla Home la Home.
	# Segnalato il 24/08 -- 'non ha senso che gli effetti siano in due momenti diversi'.
	# Qui la decisione si prende per TUTTE le finestre censite, nello stesso istante. Il contenuto non
	# si ricostruisce subito per quelle non a schermo -- Kodi non puo' ricostruire un contenitore che
	# non esiste ancora -- ma il loro path e' gia' cambiato, quindi la prima volta che la finestra
	# torna a schermo Kodi legge il path nuovo. L'utente non vede mai un valore vecchio, e non si paga
	# nulla per finestre che non guarda.
	for pair in registry_pairs():
		other_scope, _, cid = pair.partition(':')
		if other_scope == scope: continue
		# LOTTO 92: la chiave di un contenitore in un'ALTRA finestra ora si compone, non si cerca --
		# prima si leggeva CTL_KEY_PROP, che era la chiave scritta dal censimento del watcher e valeva
		# solo per le finestre gia' visitate. Adesso la posizione basta da se'. Si procede solo se
		# quella posizione ha davvero costruito qualcosa: un widget senza 'pgctl' (path non generato
		# dalla skin) non pubblica stato sotto la chiave di posizione e qui non e' raggiungibile --
		# resta comunque raggiunto dal giro sulla finestra a schermo, qui sopra.
		key = '%s.%s' % (other_scope, cid)
		if not get_property(BUILT_PROP % key): continue
		if not _action_matches(get_property(ACTION_PROP % key), wanted_actions):
			stored = get_property(IDS_PROP % key)
			if stored and not wanted.intersection(stored.split(',')): continue
			if not stored: continue  # mai pubblicato: qui non si puo' verificare nulla e non si vede niente
		pages = (get_property(CTL_PAGES_PROP % (other_scope, cid)) or '').split('&')[0]
		if not pages: pages = str(raw_pages(key, initial_batch()))
		set_property(CTL_PAGES_PROP % (other_scope, cid), '%s&%s=%s' % (pages, RELOAD_PARAM, nonce))
		hit_other += 1
	LAST_OTHER_HITS[0] = hit_other
	LAST_SEEN_ANY[0] = seen_any
	# 'non_identificati' e 'recuperati' vanno nel log per una ragione precisa: senza di loro questo
	# difetto era invisibile: si vedevano solo 'ricaricati' e 'saltati', e per accorgersi che mancava
	# qualcuno bisognava conoscere a memoria il numero di widget della schermata.
	log('refresh_for_ids ids=%s azioni=%s contenitori=%s ricaricati=%s altre_finestre=%s saltati=%s non_identificati=%s recuperati=%s' %
		(len(wanted), len(wanted_actions), 'trovati' if seen_any else 'NESSUNO', hit, hit_other, skipped,
			unresolved, recovered))
	# Il conteggio restituito resta quello della finestra a schermo: e' cio' che decide il fallback
	# globale del chiamante, e ricadere sul globale perche' l'unico contenitore interessato sta in
	# un'altra finestra sarebbe esattamente il contrario di quello che si vuole.
	return hit

def container_head(cid, scope=None):
	"""Lato watcher: dal contenitore alla chiave del widget che ci sta dentro.

	Torna (chiave, path del primo elemento). La chiave e' None se il contenitore non e' di Fen Light
	o e' vuoto.

	LOTTO 92: la chiave non si DEDUCE piu' dal contenuto, si COMPONE dalla posizione -- che il watcher
	conosce gia' e la build legge dal proprio path. Resta una sola infolabel, e serve solo a rispondere
	'questo contenitore e' nostro?'; non identifica piu' niente. Due letture in meno per giro rispetto
	alla firma a tre elementi, e soprattutto zero possibilita' di scambiare un widget per un altro.

	La ricaduta sulla firma del contenuto copre i contenitori che la skin non genera (o un file
	generato non ancora aggiornato): li' la paginazione continua a funzionare come nel lotto 91.
	"""
	from modules.kodi_utils import get_infolabel, get_property
	first = get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % cid)
	if not first or 'plugin.video.fenlight' not in first: return None, first
	if scope is None: scope = ctl_scope()
	# Il path del PRIMO ELEMENTO non porta pgctl -- e' l'URL di riproduzione di un film, non quello
	# della cartella. La posizione la sa il watcher, ed e' quella che conta.
	key = '%s.%s' % (scope, cid)
	if get_property(BUILT_PROP % key): return key, first
	# Nessuno stato sotto la chiave di posizione: o il widget non ha ancora costruito, o il suo path
	# non porta pgctl. Si prova la vecchia strada prima di rinunciare.
	urls = [first]
	for n in range(1, HEAD_ITEMS):
		url = get_infolabel('Container(%s).ListItemAbsolute(%s).FolderPath' % (cid, n))
		if not url: break
		urls.append(url)
	legacy = get_property(HEAD_PROP % head_signature(urls)) or None
	if not legacy and len(urls) > 1:
		legacy = get_property(HEAD_PROP % head_signature(urls[:1])) or None
	return legacy, first

def is_loading(key):
	# Il flag LOADING contiene il timestamp in cui il watcher ha lanciato la ricostruzione (prima era
	# la stringa 'true'). Qualunque valore non vuoto significa "build in corso": e' il segnale con cui
	# get_pages decide di ricostruire tutte le pagine accumulate invece di ricadere sul lotto iniziale.
	from modules.kodi_utils import get_property
	return bool(get_property(LOADING_PROP % key))

def loading_started(key):
	# Momento in cui il watcher ha marcato questa chiave come "in ricostruzione", per capire da quanto
	# tempo una build e' ferma. Sta nella proprieta' e non solo in memoria del servizio, cosi' il conto
	# regge anche se il servizio riparte a meta' build. 0 = valore vecchio o assente.
	from modules.kodi_utils import get_property
	try: return float(get_property(LOADING_PROP % key))
	except: return 0

def _stamp_build(key):
	# Timbra l'inizio di questa build. Chiamata da get_pages, cioe' una volta per costruzione: il costo
	# e' una setProperty, ed e' l'unico modo di sapere DALL'ESTERNO che una build e' davvero partita.
	from modules.kodi_utils import set_property
	from time import time
	now = str(time())
	try: set_property(LASTBUILD_PROP % key, now)
	except: pass
	# Dichiarazione esplicita di "sto costruendo" (lotto 106), piu' l'iscrizione al censimento fatta
	# QUI e non solo in set_head. Il motivo e' preciso: builds_in_flight() enumera le coppie censite,
	# quindi un contenitore che si iscrive solo alla FINE della propria costruzione sarebbe invisibile
	# proprio mentre sta costruendo -- cioe' l'unico momento in cui la marca conta.
	try:
		set_property(INFLIGHT_PROP % key, now)
		_scope, _, _cid = key.partition('.')
		if _scope and _cid: registry_add(_scope, _cid)
	except: pass

def mark_build_start(key):
	# Inizio dichiarato di una costruzione, per i widget che NON passano da get_pages -- oggi
	# 'continua a guardare', che non e' paginato e quindi non chiama get_pages: senza questa
	# dichiarazione sarebbe l'unico dei tre widget della Home invisibile a builds_in_flight(), ed e'
	# anche il piu' lento.
	_stamp_build(key)

def mark_build_end(key):
	# Fine dichiarata. Una sola definizione di "fine", usata sia qui sia da set_head.
	from modules.kodi_utils import clear_property
	try: clear_property(INFLIGHT_PROP % key)
	except: pass

def builds_in_flight():
	# Chi sta costruendo in questo momento, per nome. Torna una lista di chiavi, vuota quando non c'e'
	# niente in volo -- che e' la condizione che il canale dei rinvii aspetta.
	# Le chiavi si ricavano dal censimento: registry_add riceve 'scope' e 'cid' ottenuti spezzando la
	# chiave sul primo punto, quindi la coppia 'scope:cid' si ritrasforma nella chiave sostituendo il
	# separatore. Nessun elenco parallelo da tenere allineato.
	from modules.kodi_utils import get_property, clear_property
	from time import time
	vive, adesso = [], time()
	for pair in registry_pairs():
		key = pair.replace(':', '.', 1)
		raw = get_property(INFLIGHT_PROP % key)
		if not raw: continue
		try: started = float(raw)
		except: started = 0
		# Marca orfana: l'invocazione e' morta senza pubblicare la testa. Si cancella qui, cosi' il
		# guasto si ripara da solo invece di bloccare il canale per il resto della sessione.
		if not started or adesso - started > INFLIGHT_MAX_SECONDS:
			clear_property(INFLIGHT_PROP % key)
			continue
		vive.append(key)
	return vive

def last_build(key):
	# Istante dell'ultima build iniziata per questa chiave. 0 = mai vista (o proprieta' ripulita).
	from modules.kodi_utils import get_property
	try: return float(get_property(LASTBUILD_PROP % key))
	except: return 0

def raw_pages(key, default):
	# The accumulated page count for this widget, regardless of state. Used by the watcher to know
	# what to increment from.
	from modules.kodi_utils import get_property
	try: value = int(get_property(PAGES_PROP % key))
	except: value = 0
	return value if value >= default else default

def token_is_stale(params):
	"""Questa build e' nata da un path SORPASSATO? Se si', azzera il token e dice di lasciar perdere.

	LOTTO 160. Al cambio query nella ricerca partivano DUE costruzioni concorrenti. Misurato il
	04/09 passando da "batman" (arrivata a 9 pagine) a "superman":

	    19:22:54.757  provider  query=superman  &pages=9      <- il conteggio della query PRECEDENTE
	    19:22:54.766  parte la build #1
	    19:22:56.393  provider  query=superman  (senza pages) <- reconcile_position ha azzerato il token
	    19:22:56.398  parte la build #2
	    19:23:03.988  build #2 finita  7.381 ms
	    19:23:04.564  build #1 finita  9.528 ms

	Due interpreti Python insieme, su un dispositivo legato a un core, per una sola ricerca. La #1
	e' inutile per intero: nasce con il conteggio di un'altra lista e quando finisce quel conteggio
	e' gia' stato riazzerato dalla #1 stessa.

	PERCHE' SUCCEDE. Il frammento '&pages=N' nel <content> guarda la PROPRIA proprieta', non se
	quella proprieta' appartenga ancora al contenuto che c'e' adesso nel contenitore. Cambiando la
	query cambia il contenuto ma il token sopravvive, e Kodi rilegge il path prima che qualcuno se
	ne accorga: la riconciliazione, per definizione, arriva dopo che la build e' partita. E' la
	stessa famiglia del lotto 7 -- criterio di emissione sbagliato -- in una veste nuova.

	PERCHE' SI PUO' ABORTIRE SENZA LASCIARE IL CONTENITORE VUOTO. Le tre condizioni qui sotto messe
	insieme dicono che una ricarica corretta e' GIA' in arrivo, non che potrebbe esserlo:
	  1. il path porta un '&pages=N': Kodi ci ha chiamati leggendo il token;
	  2. l'impronta del contenuto in questa posizione e' diversa da quella registrata: quel conteggio
	     e' di un'altra lista;
	  3. la proprieta' del token e' ancora valorizzata: azzerandola il path CAMBIA, e un path diverso
	     e' esattamente cio' che fa rileggere la cartella a Kodi.
	Se la (3) non vale il token e' gia' stato azzerato da qualcun altro, il path non cambierebbe,
	nessuna ricarica seguirebbe e abortire lascerebbe il widget vuoto per sempre: in quel caso si
	costruisce normalmente. E' la stessa asimmetria del lotto 111 (vedi il commento nel router):
	nell'API dei plugin non esiste "tieni quello che hai", quindi chiudere una cartella a vuoto si
	fa solo quando si sa che ne arriva subito un'altra.

	Non aggiorna CTL_KEY_PROP: quello resta compito di reconcile_position nella build che costruira'
	davvero. Qui si tocca solo il conteggio, ed e' idempotente.
	"""
	if not isinstance(params, dict):
		params = dict(parse_qsl(params, keep_blank_values=True))
	try: path_pages = int(params.get('pages') or 0)
	except: path_pages = 0
	if path_pages <= 0: return False
	scope, cid = position_of(params)
	if not scope: return False
	from modules.kodi_utils import get_property, clear_property
	if get_property(CTL_KEY_PROP % (scope, cid)) == make_key(params): return False
	ctl_prop = CTL_PAGES_PROP % (scope, cid)
	if not get_property(ctl_prop): return False
	clear_property(ctl_prop)
	clear_property(PAGES_PROP % widget_key(params))
	log('token sorpassato %s.%s: path con pages=%s ma il contenuto e\' cambiato, '
		'build lasciata cadere e token azzerato' % (scope, cid, path_pages))
	return True

def reconcile_position(key, params):
	"""Azzera il conteggio se in questa posizione e' cambiata la lista. Torna il path_pages da usare.

	La chiama get_pages, quindi ogni build passa di qui una volta sola, prima di decidere quante
	pagine caricare. E' il rimpiazzo del controllo di cambio inquilino che stava nel watcher: qui il
	contenuto e' noto per certo, li' era dedotto da cio' che si credeva di vedere a schermo.

	Torna 0 quando resetta -- e non basta azzerare il conteggio per chiave: il path con cui Kodi ci ha
	chiamati porta ancora il '&pages=N' del widget PRECEDENTE (il token e' una proprieta' del
	contenitore, non della lista), e con max() quello vincerebbe da solo. Si azzerano tutti e due.
	"""
	scope, cid = position_of(params)
	path_pages = params.get('pages', 0) if isinstance(params, dict) else 0
	# L'avviso sta QUI e non in widget_key: si arriva a reconcile_position solo dalle quattro build
	# paginate, che sono le uniche per cui la posizione mancante e' davvero un guasto. widget_key la
	# chiamano anche il debounce della ricerca e la diagnostica, su path che non sono widget.
	if not scope:
		_warn_no_position(params)
		return path_pages
	from modules.kodi_utils import get_property, set_property, clear_property
	content = make_key(params)
	prop = CTL_KEY_PROP % (scope, cid)
	if get_property(prop) == content: return path_pages
	# Prima volta o lista cambiata. Non si distingue fra i due casi ed e' voluto: in entrambi il
	# conteggio precedente non descrive quello che stiamo per costruire.
	was = get_property(prop)
	set_property(prop, content)
	clear_property(PAGES_PROP % key)
	clear_property(CTL_PAGES_PROP % (scope, cid))
	log('reconcile %s: contenuto %s -> %s, conteggio azzerato' % (key, short(was) if was else '(nuovo)', short(content)))
	return 0

def get_pages(key, default, path_pages=0, params=None):
	# params: quando c'e', get_pages riconcilia da se' la posizione e IGNORA il path_pages passato --
	# lo rilegge da params, perche' un reset deve poterlo annullare. Vedi reconcile_position.
	if params is not None: path_pages = reconcile_position(key, params)
	# path_pages e' il ?pages=N letto dal path del widget: dice che questa ricostruzione appartiene a
	# un widget GIA' espanso. E' il segnale preferito perche' sta nel path -- non puo' essere tolto
	# sotto i piedi da un timeout mentre la build lavora, e sopravvive al ritorno dalla riproduzione.
	#
	# LOTTO 89 -- qui c'era `min(path_pages, raw_pages(key, default))`, ed era la seconda meta' del
	# guasto della paginazione. Il ragionamento originale era difensivo e sensato solo a meta': "gli id
	# dei contenitori si ripetono fra categorie, quindi il token potrebbe essere di un altro widget".
	# Ma quella difesa ESISTE GIA', e sta dove deve stare -- nel servizio, service.py:348:
	#     if window.getProperty(CTL_KEY_PROP % (scope, widget_id)) != key:
	#         window.setProperty(CTL_KEY_PROP % (scope, widget_id), key)
	#         window.clearProperty(CTL_PAGES_PROP % (scope, widget_id))
	# cioe' quando il contenitore cambia inquilino il token viene azzerato. Il `min()` era una seconda
	# guardia per lo stesso rischio, e in cambio faceva un danno vero: dopo un azzeramento (il widget
	# ricostruito dal path base riparte da 2 e set_state scrive 2 sulla chiave), il conteggio per
	# chiave vale 2 mentre il path dice ancora 4 -- e il `min()` blocca a 2 PROPRIO IL SEGNALE che
	# avrebbe permesso di recuperare. Un anello che si chiude su se' stesso: misurato nel log zc del
	# 25/08, `get_pages path_pages=4 -> pages_to_load=2`, e tre azzeramenti in dieci minuti.
	#
	# Ora il path puo' solo ALZARE, mai abbassare. Non serve riscrivere niente qui: la build carica N
	# pagine e chiama set_state(key, N), quindi il conteggio per chiave si ripara da solo al primo giro.
	# Il rischio residuo di un token sbagliato e' di caricare qualche pagina di troppo, non di perdere
	# elementi -- ed e' comunque limitato da has_more e dal tetto di max_items.
	_stamp_build(key)
	try: path_pages = int(path_pages or 0)
	except: path_pages = 0
	if path_pages > default:
		stored = raw_pages(key, default)
		result = max(path_pages, stored)
		# Limite di ASSURDITA', non di politica. Finche' il `min()` c'era, il conteggio per chiave
		# faceva anche da tetto implicito; togliendolo, un token corrotto nel path diventerebbe un
		# numero di pagine qualunque, e load_cumulative cicla esattamente pages_to_load volte
		# (max_items spegne has_more DOPO la build, non limita quante pagine si chiedono).
		# Il tetto e' max_items pagine: nel caso peggiore una pagina per elemento, quindi non stringe
		# mai su un widget vero -- serve solo a rendere impossibile un ciclo lunghissimo.
		cap = max_items()
		if result > cap:
			log('get_pages key=%s path_pages=%s ASSURDO, limitato a %s' % (short(key), path_pages, cap))
			result = cap
		log('get_pages key=%s path_pages=%s stored=%s -> pages_to_load=%s (default=%s)' % (short(key), path_pages, stored, result, default))
		return result
	return _get_pages_legacy(key, default)

def _get_pages_legacy(key, default):
	# A genuine fresh widget open starts from the initial batch, so re-opening a widget never reloads its
	# whole previously-expanded history at once. The accumulated page count is used only when this rebuild
	# is either a watcher-driven pagination step (LOADING set) or an in-place soft refresh of the live
	# widget (PG_REFRESH set by kodi_refresh: Trakt monitor / periodic WidgetRefresher) -- in both cases
	# the container must keep its current length so the items stay put and the focus is preserved.
	from modules.kodi_utils import get_property
	loading = is_loading(key)
	soft_refresh = get_property(PG_REFRESH_PROP) == 'true'
	result = raw_pages(key, default) if (loading or soft_refresh) else default
	log('get_pages key=%s loading=%s soft_refresh=%s -> pages_to_load=%s (default=%s)' % (short(key), loading, soft_refresh, result, default))
	return result

def set_state(key, pages, has_more):
	# Publishes the cumulative page count and whether more pages exist. LOADING is deliberately NOT
	# cleared here -- set_head clears it after add_items, so the watcher can't re-fire mid-build.
	from modules.kodi_utils import set_property
	set_property(PAGES_PROP % key, str(pages))
	set_property(HASMORE_PROP % key, 'true' if has_more else 'false')
	log('set_state key=%s pages=%s has_more=%s' % (short(key), pages, has_more))

def _id_signature(item):
	# Hashable de-dup key for an id. Plain TMDB ids are ints/strings (hashable as-is); Trakt ids are
	# dicts ({'trakt':..,'tmdb':..,'imdb':..,'slug':..}) -- the same title always carries the same dict,
	# so a tuple of its sorted items is a safe, exact signature (no risk of merging distinct titles).
	if isinstance(item, dict):
		return tuple(sorted((k, str(v)) for k, v in item.items()))
	return item

def load_cumulative(fetch_page, pages_to_load, min_items=0):
	# fetch_page(page_no) -> (ids: list, has_more: bool). Loads cumulative pages 1..N and stops early when a
	# page reports no more. Normally stops at pages_to_load; when min_items > 0 (heavily-filtered text
	# search, whose pages each yield only a few display items) it keeps fetching PAST pages_to_load until the
	# accumulated count reaches min_items -- bounded by _FILL_PAGE_CAP extra pages. This hands back a full
	# screen in a single build instead of letting the watcher discover the shortfall and cascade many tiny
	# load-ahead refreshes just because item 1 of a short list already sits within the runway.
	# Returns (concatenated_ids, has_more, last_loaded_page) -- last_page is the REAL count fetched, so the
	# caller records it (set_state) and the watcher bumps the page count from reality, not from the request.
	# De-duplicates across pages keeping the FIRST occurrence: "live" feeds (Trending/Popular) reorder
	# between requests, so a title loaded on page N can resurface on a later page and would otherwise be
	# shown twice. Dropping only the later (tail) duplicate keeps every already-shown item at its index,
	# so the append-only invariant -- and the focus -- are preserved.
	all_ids, seen, has_more, last_page = [], set(), False, 0
	page_cap = pages_to_load + (_FILL_PAGE_CAP if min_items else 0)
	page_no = 0
	while page_no < page_cap:
		page_no += 1
		ids, has_more = fetch_page(page_no)
		last_page = page_no
		added = 0
		if ids:
			for item in ids:
				sig = _id_signature(item)
				if sig in seen: continue
				seen.add(sig)
				all_ids.append(item)
				added += 1
		log('load_cumulative page=%s items=%s new=%s has_more=%s (total so far=%s, rimandati=%s, min_items=%s)'
			% (page_no, len(ids) if ids else 0, added, has_more, len(all_ids), deferred_count(), min_items))
		if not has_more: break
		# Past the requested pages, stop as soon as the fill target is met (min_items=0 -> stop exactly at
		# pages_to_load, the legacy behavior for every non-search widget). Gli elementi rimandati dal
		# filtro doppiaggio contano come presenti: vedi deferred_count.
		if page_no >= pages_to_load and len(all_ids) + deferred_count() >= min_items: break
	return all_ids, has_more, last_page
