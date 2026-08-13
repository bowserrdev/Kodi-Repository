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

def raw_pages(key, default):
	# The accumulated page count for this widget, regardless of state. Used by the watcher to know
	# what to increment from.
	from modules.kodi_utils import get_property
	try: value = int(get_property(PAGES_PROP % key))
	except: value = 0
	return value if value >= default else default

def get_pages(key, default):
	# A genuine fresh widget open starts from the initial batch, so re-opening a widget never reloads its
	# whole previously-expanded history at once. The accumulated page count is used only when this rebuild
	# is either a watcher-driven pagination step (LOADING set) or an in-place soft refresh of the live
	# widget (PG_REFRESH set by kodi_refresh: Trakt monitor / periodic WidgetRefresher) -- in both cases
	# the container must keep its current length so the items stay put and the focus is preserved.
	from modules.kodi_utils import get_property
	loading = get_property(LOADING_PROP % key) == 'true'
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
