# -*- coding: utf-8 -*-
import sys
import json
import random
from threading import Thread
from apis import trakt_api
from indexers.movies import Movies
from indexers.tvshows import TVShows
from indexers.seasons import single_seasons
from indexers.episodes import build_single_episode
from modules import kodi_utils
from modules import paginator
from modules.utils import paginate_list
from modules.settings import paginate, page_limit
# logger = kodi_utils.logger

add_dir, external, sleep, get_icon = kodi_utils.add_dir, kodi_utils.external, kodi_utils.sleep, kodi_utils.get_icon
trakt_icon, fanart, add_item, set_property = get_icon('trakt'), kodi_utils.get_addon_fanart(), kodi_utils.add_item, kodi_utils.set_property
set_content, set_sort_method, set_view_mode, end_directory = kodi_utils.set_content, kodi_utils.set_sort_method, kodi_utils.set_view_mode, kodi_utils.end_directory
make_listitem, build_url, add_items = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.add_items
nextpage_landscape, get_property, clear_property, focus_index = kodi_utils.nextpage_landscape, kodi_utils.get_property, kodi_utils.clear_property, kodi_utils.focus_index
set_category, home, folder_path = kodi_utils.set_category, kodi_utils.home, kodi_utils.folder_path
trakt_trending_popular_lists, trakt_get_lists, trakt_search_lists = trakt_api.trakt_trending_popular_lists, trakt_api.trakt_get_lists, trakt_api.trakt_search_lists
trakt_fetch_collection_watchlist, get_trakt_list_contents = trakt_api.trakt_fetch_collection_watchlist, trakt_api.get_trakt_list_contents
trakt_lists_with_media = trakt_api.trakt_lists_with_media

def search_trakt_lists(params):
	def _builder():
		for item in lists:
			try:
				list_key = item['type']
				list_info = item[list_key]
				if list_key == 'officiallist': continue
				item_count = list_info['item_count']
				if list_info['privacy'] == 'private' or item_count == 0: continue
				list_name, user, slug = list_info['name'], list_info['username'], list_info['ids']['slug']
				list_name_upper = list_name.upper()
				if not slug: continue
				cm = []
				cm_append = cm.append
				display = '%s | [I]%s (x%s)[/I]' % (list_name_upper, user, str(item_count))
				url = build_url({'mode': 'trakt.list.build_trakt_list', 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name})
				cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
				cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	handle, search_title = int(sys.argv[1]), ''
	try:
		mode = params.get('mode')
		page = params.get('new_page', '1')
		search_title = params.get('key_id') or params.get('query')
		lists, pages = trakt_search_lists(search_title, page)
		add_items(handle, list(_builder()))
		if pages > page:
			new_page = str(int(page) + 1)
			add_dir({'mode': mode, 'key_id': search_title, 'new_page': new_page}, 'Next Page (%s) >>' % new_page, handle, 'nextpage', nextpage_landscape)
	except: pass
	set_content(handle, 'files')
	set_category(handle, search_title.capitalize())
	end_directory(handle)
	set_view_mode('view.main')

def get_trakt_lists(params):
	def _process():
		for item in lists:
			try:
				if list_type == 'liked_lists': item = item['list']
				cm = []
				cm_append = cm.append
				list_name, user, slug, item_count = item['name'], item['user']['ids']['slug'], item['ids']['slug'], item['item_count']
				list_name_upper = " ".join(w.capitalize() for w in list_name.split())
				mode = 'random.build_trakt_my_lists_contents' if randomize_contents == 'true' else 'trakt.list.build_trakt_list'
				url_params = {'mode': mode, 'user': user, 'slug': slug, 'list_type': list_type, 'list_name': list_name}
				if randomize_contents: url_params['random'] = 'true'
				elif shuffle: url_params['shuffle'] = 'true'
				url = build_url(url_params)
				if list_type == 'liked_lists':
					display = '%s | [I]%s (x%s)[/I]' % (list_name_upper, user, str(item_count))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				else:
					display = '%s [I](x%s)[/I]' % (list_name_upper, str(item_count))
					cm_append(('[B]Make New List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.make_new_trakt_list'})))
					cm_append(('[B]Delete List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.delete_trakt_list', 'user': user, 'list_slug': slug})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	handle = int(sys.argv[1])
	list_type, randomize_contents, shuffle = params['list_type'], params.get('random', 'false'), params.get('shuffle', 'false') == 'true'
	returning_to_list = False
	try:
		lists = trakt_get_lists(list_type)
		if shuffle:
			returning_to_list = 'trakt.list.build_trakt_list' in folder_path()
			if returning_to_list:
				try: lists = json.loads(get_property('fenlight.trakt.lists.order'))
				except: pass
			else:
				random.shuffle(lists)
				set_property('fenlight.trakt.lists.order', json.dumps(lists))
			sort_method = 'none'
		else:
			clear_property('fenlight.trakt.lists.order')
			sort_method = 'label'
		add_items(handle, list(_process()))
	except: pass
	set_content(handle, 'files')
	set_category(handle, params.get('category_name', ''))
	set_sort_method(handle, sort_method)
	end_directory(handle)
	set_view_mode('view.main')
	if shuffle and not returning_to_list: focus_index(0)

def get_trakt_trending_popular_lists(params):
	def _process():
		for _list in lists:
			try:
				cm = []
				cm_append = cm.append
				item = _list['list']
				item_count = item.get('item_count', 0)
				if item_count == 0: continue
				list_name, user, slug = item['name'], item['user']['ids']['slug'], item['ids']['slug']
				list_name_upper = list_name.upper()
				if not slug: continue
				if item['type'] == 'official': user = 'Trakt Official'
				if not user: continue
				display = '%s | [I]%s (x%s)[/I]' % (list_name_upper, user, str(item_count))
				url = build_url({'mode': 'trakt.list.build_trakt_list', 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name})
				listitem = make_listitem()
				if not user == 'Trakt Official':
					cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem.addContextMenuItems(cm)
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				yield (url, listitem, True)
			except: pass
	handle = int(sys.argv[1])
	try:
		page = params.get('new_page', '1')
		new_page = str(int(page) + 1)
		list_type = params['list_type']
		lists = trakt_trending_popular_lists(list_type, page)
		add_items(handle, list(_process()))
		add_dir({'mode': 'trakt.list.get_trakt_trending_popular_lists', 'list_type': 'trending', 'new_page': new_page},
				'Next Page (%s) >>' % new_page, handle, 'nextpage', nextpage_landscape)
	except: pass
	set_content(handle, 'files')
	set_category(handle, params.get('category_name', 'Trakt Lists'))
	end_directory(handle)
	set_view_mode('view.main')

def get_trakt_lists_with_media(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				item_count = item.get('item_count', 0)
				list_name, user, slug = item['name'], item['user']['ids']['slug'], item['ids']['slug']
				list_name_upper = list_name.upper()
				display = '%s | [I]%s (x%s)[/I]' % (list_name_upper, user, str(item_count))
				url = build_url({'mode': 'trakt.list.build_trakt_list', 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name})
				listitem = make_listitem()
				if not user == 'Trakt Official':
					cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem.addContextMenuItems(cm)
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				yield (url, listitem, True)
			except: pass
	handle = int(sys.argv[1])
	try:
		lists = trakt_lists_with_media(params['media_type'], params['imdb_id'])
		add_items(handle, list(_process()))
	except: pass
	set_content(handle, 'files')
	set_category(handle, params.get('category_name', 'Trakt Lists'))
	end_directory(handle)
	set_view_mode('view.main')

# Extra "pages" the dub fill may consume past the requested window before giving up and returning whatever
# it gathered -- the in-memory mirror of paginator._FILL_PAGE_CAP (which bounds the equivalent fetch-page
# fill). A list that is mostly filtered out must not spin through its entire length chasing the target.
_DUB_FILL_PAGE_CAP = 12

def _dub_active(is_external):
	# True only when the dub widget filter applies to this build: a widget (is_external), the toggle on, and
	# the chosen language mapped to a country. Mirrors the gate inside _dub_filter_items.
	if not is_external: return False
	from modules.settings import dub_filter_enabled, dub_filter_country
	return dub_filter_enabled() and bool(dub_filter_country())

def _dub_context():
	from modules.settings import dub_filter_country, tmdb_api_key, mpaa_region
	from modules.utils import get_datetime, get_current_timestamp
	return dub_filter_country(), tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp()

def _dub_keep_chunk(chunk, country, api_key, mpaa, cdate, ctime):
	# Dub-filter one chunk of list items, preserving order. Movies and shows are masked separately (each in a
	# single threaded dub_keep_mask batch); seasons/episodes carry no media to localise and pass through.
	from modules.metadata import dub_keep_mask
	drop = set()
	for media_type, item_type in (('movie', 'movie'), ('tvshow', 'show')):
		group = [(idx, it) for idx, it in enumerate(chunk) if it['type'] == item_type]
		if not group: continue
		ids = [it['media_ids'] for _, it in group]
		mask = dub_keep_mask(media_type, 'trakt_dict', ids, country, api_key, mpaa, cdate, ctime)
		for (idx, _), keep in zip(group, mask):
			if not keep: drop.add(idx)
	return [it for idx, it in enumerate(chunk) if idx not in drop]

def _dub_paginate(result, pages_to_load, is_external):
	# Interactive-widget fill for builders whose full list is already in memory (Trakt/MDbList). Returns
	# (process_list, pages_consumed, has_more). When the dub filter is OFF this is the plain window cut
	# result[:pages_to_load*limit]. When ON it mirrors load_cumulative(min_items=...): keep consuming pages
	# past the requested window -- dropping titles with no localised release -- until a full window of
	# SURVIVORS is gathered, bounded by _DUB_FILL_PAGE_CAP extra pages. So a heavily-filtered list still
	# fills the screen in one build instead of leaving the widget short (which makes the watcher cascade many
	# tiny load-ahead refreshes). pages_consumed is the REAL number of pages taken, so set_state records
	# reality. process_list is already dub-filtered; ORDER PRESERVED (append-only invariant).
	from modules.settings import page_limit
	limit = page_limit(True)
	target = pages_to_load * limit
	if not _dub_active(is_external):
		process = result[:target]
		return process, pages_to_load, len(result) > len(process)
	country, api_key, mpaa, cdate, ctime = _dub_context()
	kept, consumed, total = [], 0, len(result)
	page_cap = pages_to_load + _DUB_FILL_PAGE_CAP
	pages_consumed = 0
	while pages_consumed < page_cap and consumed < total:
		pages_consumed += 1
		chunk = result[consumed:consumed + limit]
		consumed += len(chunk)
		kept.extend(_dub_keep_chunk(chunk, country, api_key, mpaa, cdate, ctime))
		if pages_consumed >= pages_to_load and len(kept) >= target: break
	return kept, pages_consumed, consumed < total

def _dub_filter_items(items, media_type, is_external):
	# Widget "dubbed content" filter for builders that pass per-item {'media_ids':...} dicts to worker()
	# (Trakt lists, MDbList) and so bypass the indexers' fetch_page hook. Drops items with no localised
	# release (streaming or home video) in the chosen language's country, preserving order. Widgets only
	# (is_external), matching the fetch_page hook's scope. No-op when the filter is off / language unmapped.
	# Used by the NON-interactive (legacy Next-Page) path; the interactive path fills via _dub_paginate.
	if not items or not is_external: return items
	from modules.settings import dub_filter_enabled, dub_filter_country, tmdb_api_key, mpaa_region
	if not dub_filter_enabled(): return items
	country = dub_filter_country()
	if not country: return items
	from modules.metadata import dub_keep_mask
	from modules.utils import get_datetime, get_current_timestamp
	ids = [i['media_ids'] for i in items]
	mask = dub_keep_mask(media_type, 'trakt_dict', ids, country, tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())
	return [it for it, keep in zip(items, mask) if keep]

def build_trakt_list(params):
	def _process(function, _list, _type):
		if not _list['list']: return
		if _type in ('movies', 'tvshows'): item_list_extend(function(_list).worker())
		elif _type == 'seasons': item_list_extend(function(_list['list']))
		else: item_list_extend(function('episode.trakt_list', _list['list']))
	def _paginate_list(data, page_no, paginate_start):
		if use_result: total_pages = 1
		elif paginate_enabled:
			limit = page_limit(is_home)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_home: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, is_home, content, list_name = int(sys.argv[1]), external(), home(), 'movies', params.get('list_name')
	try:
		threads, item_list = [], []
		item_list_extend = item_list.extend
		user, slug, list_type = '', '', ''
		paginate_enabled = paginate(is_home)
		use_result = 'result' in params
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		if page_no == 1 and not is_external: set_property('fenlight.exit_params', folder_path())
		if use_result: result = params.get('result', [])
		else:
			user, slug, list_type = params.get('user'), params.get('slug'), params.get('list_type')
			with_auth = list_type == 'my_lists'
			result = get_trakt_list_contents(list_type, user, slug, with_auth)
		interactive = (not use_result) and paginator.interactive_enabled() and is_external
		paginator.log('trakt build list_type=%s name=%s is_home=%s use_result=%s setting=%s paginate_enabled=%s result=%s -> interactive=%s' %
					(params.get('list_type'), list_name, is_home, use_result, paginator.interactive_enabled(), paginate_enabled, len(result), interactive))
		if interactive:
			pg_key = paginator.make_key(params)
			pages_to_load = paginator.get_pages(pg_key, paginator.initial_batch())
			# Fill past the requested window when the dub filter thins the list, so the widget lands full
			# (see _dub_paginate). process_list is already dub-filtered here -> no second _dub_filter_items.
			process_list, pages_consumed, has_more = _dub_paginate(result, pages_to_load, is_external)
			paginator.log('trakt BUILD key=%s pages=%s consumed=%s shown=%s has_more=%s' %
					(paginator.short(pg_key), pages_to_load, pages_consumed, len(process_list), has_more))
			paginator.set_state(pg_key, pages_consumed, has_more)
			all_movies = [i for i in process_list if i['type'] == 'movie']
			all_tvshows = [i for i in process_list if i['type'] == 'show']
		else:
			process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
			all_movies = _dub_filter_items([i for i in process_list if i['type'] == 'movie'], 'movie', is_external)
			all_tvshows = _dub_filter_items([i for i in process_list if i['type'] == 'show'], 'tvshow', is_external)
		all_seasons = [i for i in process_list if i['type'] == 'season']
		all_episodes = [i for i in process_list if i['type'] == 'episode']
		movie_list = {'list': [(i['order'], i['media_ids']) for i in all_movies], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['media_ids']) for i in all_tvshows], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		season_list = {'list': all_seasons}
		episode_list = {'list': all_episodes}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows)), ('seasons', len(all_seasons)), ('episodes', len(all_episodes))], key=lambda k: k[1])[0]
		for item in ((Movies, movie_list, 'movies'), (TVShows, tvshow_list, 'tvshows'),
					(single_seasons, season_list, 'seasons'), (build_single_episode, episode_list, 'episodes')):
			threaded_object = Thread(target=_process, args=item)
			threaded_object.start()
			threads.append(threaded_object)
		[i.join() for i in threads]
		item_list.sort(key=lambda k: k[1])
		if use_result: return [i[0] for i in item_list]
		final_items = [i[0] for i in item_list]
		add_items(handle, final_items)
		if interactive: paginator.set_head(pg_key, final_items)
		if not interactive and total_pages > page_no:
			new_page = str(page_no + 1)
			new_params = {'mode': 'trakt.list.build_trakt_list', 'list_type': list_type, 'list_name': list_name,
							'user': user, 'slug': slug, 'paginate_start': paginate_start, 'new_page': new_page}
			add_dir(new_params, 'Next Page (%s) >>' % new_page, handle, 'nextpage', nextpage_landscape)
	except: pass
	set_content(handle, content)
	set_category(handle, list_name)
	end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': sleep(1000)
		set_view_mode('view.%s' % content, content, is_external)
