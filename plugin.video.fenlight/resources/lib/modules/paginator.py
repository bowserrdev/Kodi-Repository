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

# Params that change between cumulative reloads of the SAME widget and must not affect its key.
_VOLATILE_PARAMS = ('new_page', 'paginate_start', 'refreshed', 'pages', 'reload', 'reload_property')

# Verbose diagnostic logging for the interactive pagination flow. Grep the Kodi log for FENLIGHT_PG.
# Set PG_DEBUG = False (or delete the log() calls) once the feature is verified.
PG_DEBUG = True

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
	from modules.kodi_utils import set_property, clear_property
	set_property(PAGES_PROP % key, str(pages))
	set_property(HASMORE_PROP % key, 'true' if has_more else 'false')
	clear_property(LOADING_PROP % key)
	log('set_state key=%s pages=%s has_more=%s loading=cleared' % (short(key), pages, has_more))

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
