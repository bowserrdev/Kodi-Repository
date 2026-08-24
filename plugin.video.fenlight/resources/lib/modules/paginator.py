# -*- coding: utf-8 -*-
# Centralized pagination logic shared by the indexer modules and the WidgetPaginator service.
# Implements interactive "infinite scroll" pagination for home widgets: instead of appending a
# clickable "Next Page" item, the plugin loads N cumulative pages in a single (append-only) build.
# A service-side watcher bumps the page count as the user scrolls and triggers a silent container
# refresh, so the already-loaded items keep their position and the focus is preserved.
from hashlib import md5
from re import compile as re_compile
from urllib.parse import parse_qsl
from caches.settings_cache import get_setting

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
# Chiave del widget che possiede attualmente quel contenitore. Gli id dei contenitori si ripetono fra
# categorie diverse e una ricerca cambia chiave a ogni query: quando l'identita' cambia il token va
# azzerato, altrimenti il widget nuovo erediterebbe le pagine di quello vecchio.
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
# I contenitori dei widget della skin. Arctic Fuse li numera 501-504 (verificato nel file generato e
# in Includes_Search.xml); il margine copre una riconfigurazione della home senza dover ritoccare qui.
# Sondarli costa una getInfoLabel ciascuno e avviene UNA volta per refresh, non in un ciclo.
WIDGET_CONTAINER_IDS = tuple(range(500, 521))
# Nome del parametro nonce accodato al token del contenitore per forzarne la ricarica. E' gia' in
# _VOLATILE_PARAMS, quindi non entra nella chiave del widget e la paginazione non se ne accorge.
RELOAD_PARAM = 'reload'

# Params that change between cumulative reloads of the SAME widget and must not affect its key.
_VOLATILE_PARAMS = ('new_page', 'paginate_start', 'refreshed', 'pages', 'reload', 'reload_property')

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
PG_DEBUG = False

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
	try: value = int(get_setting('fenlight.paginate.lookahead', '1'))
	except: value = 1
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
# la parte incomprimibile per ricostruzione. Da togliere quando le ottimizzazioni sono chiuse.
PERF = True

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
		key = make_key(query) if query else ''
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

def phase_report(kind, labels):
	if not PERF: return
	try:
		from modules.kodi_utils import logger
		rows = list(_ITEM_PHASES)
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
		logger('FenLight PERF FASI', '%s | %s elementi | worker %s | somma thread %.0f ms | %s'
				% (kind, n, workers, grand * 1000,
					' + '.join('%s %.0fms (%.0f%%)' % (labels[i], totals[i] * 1000, 100.0 * totals[i] / grand)
								for i in range(len(labels)))))
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
		try:
			from modules.kodi_utils import get_property
			_c = float(get_property('fenlight.perf.closefile') or 0)
			if _c:
				_d = t_built - _c
				if 0 < _d < 30: since_close = ' | +%.0f ms da CloseFile' % (_d * 1000)
		except: pass
		logger('FenLight PERF', '%s %s | %s elementi%s%s | worker %s | totale %.2fs = risoluzione %.2fs + costruzione %.0f ms (%.3f ms/elemento) | %.1f ms/elemento totale | inv=%s'
				% (kind, action, count, (' | %s pagine' % pages) if pages else '',
					(' | path_pages=%s' % path_pages) if path_pages not in (None, '', 0, '0') else ' | path_pages=-',
					workers, total, t_resolved - t_start, build_ms, (build_ms / count) if count else 0,
					per_item, _INVOCATIONS[0]) + since_close + _diag_note(t_built))
	except: pass

def make_key(params):
	# Builds a stable per-widget key from the identifying params, ignoring volatile ones, so that
	# the indexer (from its own params) and the watcher (from Container.FolderPath) compute the same key.
	if not isinstance(params, dict):
		params = dict(parse_qsl(params, keep_blank_values=True))
	items = sorted((k, v) for k, v in params.items() if k not in _VOLATILE_PARAMS)
	canonical = '&'.join('%s=%s' % (k, v) for k, v in items)
	return md5(canonical.encode('utf-8')).hexdigest()

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

# Ogni URL di elemento porta 'tmdb_id=' (URL_PLAY, URL_OPTIONS, URL_MARK... in tutti gli indexer),
# quindi gli id si estraggono senza dover conoscere la forma dei dati di ciascuno.
_TMDB_IN_URL = re_compile(r'[?&]tmdb_id=(\d+)')

def _publish_ids(key, items):
	# Pubblica gli id contenuti da questo widget, per la ricarica mirata. Best-effort: se fallisce,
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
			if tid in seen: continue
			seen.add(tid); ids.append(tid)
		set_property(IDS_PROP % key, ','.join(ids))
	except: pass

def _register(key, headhash):
	# Append this build's key to the registry (newest last, no duplicates) and prune the oldest
	# entries past REGISTRY_CAP, clearing each dropped widget's leftover properties. Best-effort:
	# the read-modify-write isn't locked, but a lost/duplicate entry only ever leaves a stale prop
	# behind -- it can never break a live widget's pagination.
	from modules.kodi_utils import get_property, set_property, clear_property
	entry = '%s:%s' % (key, headhash or '')
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
		clear_property(IDS_PROP % old_key)
		clear_property(ACTION_PROP % old_key)
		if old_head: clear_property(HEAD_PROP % old_head)
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
	headhash = md5(url.encode('utf-8')).hexdigest() if url else None
	if headhash:
		set_property(HEAD_PROP % headhash, key)
	clear_property(LOADING_PROP % key)
	_publish_ids(key, items)
	if action: set_property(ACTION_PROP % key, str(action))
	_register(key, headhash)
	log('set_head key=%s built=%s first_url=%s' % (short(key), count, (url[:90] if url else '-')))

def refresh_containers_for_ids(ids, actions=()):
	"""Ricostruisce SOLO i contenitori toccati da questi tmdb_id. Torna quanti ne ha ricaricati.

	La regola e' volutamente PRUDENTE: si salta un contenitore soltanto quando si riesce a dimostrare
	che non c'entra -- cioe' lo si e' identificato E il suo elenco di id non contiene nessuno di
	quelli cambiati. Tutto il resto viene ricaricato. Cosi' un widget che non passa dal paginatore
	(continua a guardare non chiama set_head, quindi non ha ne' chiave ne' elenco) continua ad
	aggiornarsi come prima, invece di restare fermo: e' proprio quello che DEVE cambiare a fine film.

	Torna 0 se non identifica nessun contenitore Fen Light: il chiamante ricade sul refresh globale,
	quindi il comportamento non puo' essere peggiore di quello di oggi.
	"""
	from modules.kodi_utils import get_property, set_property, get_infolabel, getCurrentWindowId
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
	for cid in WIDGET_CONTAINER_IDS:
		first_url = get_infolabel('Container(%s).ListItemAbsolute(0).FolderPath' % cid)
		if not first_url or 'plugin.video.fenlight' not in first_url: continue
		seen_any = True
		key = head_lookup(first_url)
		if key and get_property(ACTION_PROP % key) not in wanted_actions:
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
		key = get_property(CTL_KEY_PROP % (other_scope, cid))
		if not key: continue
		if get_property(ACTION_PROP % key) not in wanted_actions:
			stored = get_property(IDS_PROP % key)
			if stored and not wanted.intersection(stored.split(',')): continue
			if not stored: continue  # mai pubblicato: qui non si puo' verificare nulla e non si vede niente
		pages = (get_property(CTL_PAGES_PROP % (other_scope, cid)) or '').split('&')[0]
		if not pages: pages = str(raw_pages(key, initial_batch()))
		set_property(CTL_PAGES_PROP % (other_scope, cid), '%s&%s=%s' % (pages, RELOAD_PARAM, nonce))
		hit_other += 1
	LAST_OTHER_HITS[0] = hit_other
	log('refresh_for_ids ids=%s azioni=%s contenitori=%s ricaricati=%s altre_finestre=%s saltati=%s' %
		(len(wanted), len(wanted_actions), 'trovati' if seen_any else 'NESSUNO', hit, hit_other, skipped))
	# Il conteggio restituito resta quello della finestra a schermo: e' cio' che decide il fallback
	# globale del chiamante, e ricadere sul globale perche' l'unico contenitore interessato sta in
	# un'altra finestra sarebbe esattamente il contrario di quello che si vuole.
	return hit

def head_lookup(first_url):
	# Watcher side: resolve the focused container's first-item path back to its widget key.
	if not first_url: return None
	from modules.kodi_utils import get_property
	return get_property(HEAD_PROP % md5(first_url.encode('utf-8')).hexdigest()) or None

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

def raw_pages(key, default):
	# The accumulated page count for this widget, regardless of state. Used by the watcher to know
	# what to increment from.
	from modules.kodi_utils import get_property
	try: value = int(get_property(PAGES_PROP % key))
	except: value = 0
	return value if value >= default else default

def get_pages(key, default, path_pages=0):
	# path_pages e' il ?pages=N letto dal path del widget: dice che questa ricostruzione appartiene a
	# un widget GIA' espanso. E' il segnale preferito perche' sta nel path -- non puo' essere tolto
	# sotto i piedi da un timeout mentre la build lavora, e sopravvive al ritorno dalla riproduzione.
	#
	# Non ci si fida ciecamente: gli id dei contenitori si ripetono fra categorie diverse, quindi un
	# altro widget con lo stesso id potrebbe aver lasciato lI' il suo token. Il conteggio autorevole
	# resta quello indicizzato per chiave del widget, e si prende il minore dei due: se questa chiave
	# non ha pagine accumulate, raw_pages torna il default e il token altrui viene ignorato.
	try: path_pages = int(path_pages or 0)
	except: path_pages = 0
	if path_pages > default:
		result = min(path_pages, raw_pages(key, default))
		log('get_pages key=%s path_pages=%s -> pages_to_load=%s (default=%s)' % (short(key), path_pages, result, default))
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
		log('load_cumulative page=%s items=%s new=%s has_more=%s (total so far=%s, min_items=%s)' % (page_no, len(ids) if ids else 0, added, has_more, len(all_ids), min_items))
		if not has_more: break
		# Past the requested pages, stop as soon as the fill target is met (min_items=0 -> stop exactly at
		# pages_to_load, the legacy behavior for every non-search widget).
		if page_no >= pages_to_load and len(all_ids) >= min_items: break
	return all_ids, has_more, last_page
