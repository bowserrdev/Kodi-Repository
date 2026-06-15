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

# Params that change between cumulative reloads of the SAME widget and must not affect its key.
_VOLATILE_PARAMS = ('new_page', 'paginate_start', 'refreshed', 'pages', 'reload', 'reload_property')

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
	if url:
		set_property(HEAD_PROP % md5(url.encode('utf-8')).hexdigest(), key)
	clear_property(LOADING_PROP % key)
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
	# A fresh widget open (or the periodic WidgetRefresher rebuild) starts from the initial batch.
	# Only a watcher-driven pagination refresh (LOADING flag set) uses the accumulated page count,
	# so re-opening a widget never loads its whole previously-expanded history at once.
	from modules.kodi_utils import get_property
	loading = get_property(LOADING_PROP % key) == 'true'
	result = raw_pages(key, default) if loading else default
	log('get_pages key=%s loading=%s -> pages_to_load=%s (default=%s)' % (short(key), loading, result, default))
	return result

def set_state(key, pages, has_more):
	# Publishes the cumulative page count and whether more pages exist. LOADING is deliberately NOT
	# cleared here -- set_head clears it after add_items, so the watcher can't re-fire mid-build.
	from modules.kodi_utils import set_property
	set_property(PAGES_PROP % key, str(pages))
	set_property(HASMORE_PROP % key, 'true' if has_more else 'false')
	log('set_state key=%s pages=%s has_more=%s' % (short(key), pages, has_more))

def load_cumulative(fetch_page, pages_to_load):
	# fetch_page(page_no) -> (ids: list, has_more: bool). Stops early when a page reports no more.
	# Returns (concatenated_ids, has_more, last_loaded_page).
	all_ids, has_more, last_page = [], False, 0
	for page_no in range(1, pages_to_load + 1):
		ids, has_more = fetch_page(page_no)
		last_page = page_no
		count = len(ids) if ids else 0
		if ids: all_ids.extend(ids)
		log('load_cumulative page=%s items=%s has_more=%s (total so far=%s)' % (page_no, count, has_more, len(all_ids)))
		if not has_more: break
	return all_ids, has_more, last_page
