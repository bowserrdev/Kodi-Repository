# -*- coding: utf-8 -*-
# Centralized pagination logic shared by the indexer modules and the WidgetPaginator service.
# Implements interactive "infinite scroll" pagination for home widgets: instead of appending a
# clickable "Next Page" item, the plugin loads N cumulative pages in a single (append-only) build.
# A service-side watcher bumps the page count as the user scrolls and triggers a silent container
# refresh, so the already-loaded items keep their position and the focus is preserved.
from hashlib import md5
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
CTL_PAGES_PROP = 'fenlight.pg.ctl%s.pages'
# Chiave del widget che possiede attualmente quel contenitore. Gli id dei contenitori si ripetono fra
# categorie diverse e una ricerca cambia chiave a ogni query: quando l'identita' cambia il token va
# azzerato, altrimenti il widget nuovo erediterebbe le pagine di quello vecchio.
CTL_KEY_PROP = 'fenlight.pg.ctl%s.key'
# Bounded registry of recently-built widget keys, to clean up stale per-widget properties over long
# sessions (each distinct search query mints a new key and leaks its prop set). Entry = 'key:headhash'.
# Pruning only ever drops the OLDEST entries; the focused widget is always newest, and a pruned widget
# simply republishes from scratch if reopened -- so this is behavior-neutral.
REGISTRY_PROP = 'fenlight.pg.registry'
REGISTRY_CAP = 60

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
		logger('FenLight PERF FASI', '%s | %s elementi | somma thread %.0f ms | %s'
				% (kind, n, grand * 1000,
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
PERF_SELFTEST = True

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
		logger('FenLight PERF', '%s %s | %s elementi%s%s | totale %.2fs = risoluzione %.2fs + costruzione %.2fs | %.1f ms/elemento | inv=%s'
				% (kind, action, count, (' | %s pagine' % pages) if pages else '',
					(' | path_pages=%s' % path_pages) if path_pages not in (None, '', 0, '0') else ' | path_pages=-',
					total, t_resolved - t_start, t_built - t_resolved, per_item, _INVOCATIONS[0]))
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

def _first_item_url(items):
	# Extract the first item's plugin path from the list handed to add_items. Indexers use either the
	# add_items tuple (url, listitem, isfolder) or the movies/tvshows custom-order shape ((url, li, isf), pos).
	if not items: return None
	first = items[0]
	if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
		first = first[0]
	try: return first[0]
	except: return None

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
		if old_head: clear_property(HEAD_PROP % old_head)
	set_property(REGISTRY_PROP, ','.join(entries))

def set_head(key, items):
	# Final step of an interactive build (called right after add_items). Publishes:
	#  - the first item's path -> widget key, so the watcher can identify the focused container;
	#  - the count of items actually shown (BUILT_PROP), the watcher's catch-up gate;
	# and clears LOADING here -- not in set_state -- so the watcher can't re-fire in the window
	# between set_state and the new page actually surfacing.
	from modules.kodi_utils import set_property, clear_property
	count = len(items) if items else 0
	set_property(BUILT_PROP % key, str(count))
	url = _first_item_url(items)
	headhash = md5(url.encode('utf-8')).hexdigest() if url else None
	if headhash:
		set_property(HEAD_PROP % headhash, key)
	clear_property(LOADING_PROP % key)
	_register(key, headhash)
	log('set_head key=%s built=%s first_url=%s' % (short(key), count, (url[:90] if url else '-')))

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
