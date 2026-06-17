# -*- coding: utf-8 -*-
import sys
from threading import Thread
from apis.mdblist_api import mdblist_get_my_lists, mdblist_get_liked_lists, mdblist_get_list_contents
from indexers.movies import Movies
from indexers.tvshows import TVShows
from indexers.trakt_lists import _dub_filter_items, _dub_paginate
from modules import kodi_utils
from modules import paginator
from modules.utils import paginate_list
from modules.settings import paginate, page_limit

add_dir, external, sleep, get_icon = kodi_utils.add_dir, kodi_utils.external, kodi_utils.sleep, kodi_utils.get_icon
fanart, set_property = kodi_utils.get_addon_fanart(), kodi_utils.set_property
set_content, set_view_mode, end_directory = kodi_utils.set_content, kodi_utils.set_view_mode, kodi_utils.end_directory
make_listitem, build_url, add_items = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.add_items
nextpage_landscape, set_category, home, folder_path = kodi_utils.nextpage_landscape, kodi_utils.set_category, kodi_utils.home, kodi_utils.folder_path
mdblist_icon = 'special://home/addons/plugin.video.fenlight/resources/media/icons/mdblist.png'

def _build_mdblist_lists(params, lists):
	def _process():
		for item in lists:
			try:
				list_id, list_name, item_count = item['id'], item['name'], item['items']
				list_name_display = ' '.join(w.capitalize() for w in list_name.split())
				display = '%s [I](x%s)[/I]' % (list_name_display, str(item_count))
				url = build_url({'mode': 'mdblist.list.build_mdblist_list', 'list_id': str(list_id), 'list_name': list_name})
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': mdblist_icon, 'poster': mdblist_icon, 'thumb': mdblist_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				yield (url, listitem, True)
			except: pass
	handle = int(sys.argv[1])
	try:
		add_items(handle, list(_process()))
	except: pass
	set_content(handle, 'files')
	set_category(handle, params.get('category_name', 'MDBList'))
	end_directory(handle)
	set_view_mode('view.main')

def get_mdblist_lists(params):
	try: lists = mdblist_get_my_lists()
	except: lists = []
	_build_mdblist_lists(params, lists)

def get_mdblist_liked_lists(params):
	try: lists = mdblist_get_liked_lists()
	except: lists = []
	_build_mdblist_lists(params, lists)

def build_mdblist_list(params):
	def _process(function, _list):
		if not _list['list']: return
		item_list_extend(function(_list).worker())
	def _paginate_list(data, page_no, paginate_start):
		if paginate_enabled:
			limit = page_limit(is_home)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_home: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, is_home, content = int(sys.argv[1]), external(), home(), 'movies'
	list_name, list_id = params.get('list_name'), params.get('list_id')
	try:
		threads, item_list = [], []
		item_list_extend = item_list.extend
		paginate_enabled = paginate(is_home)
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		if page_no == 1 and not is_external: set_property('fenlight.exit_params', folder_path())
		result = mdblist_get_list_contents(list_id)
		interactive = paginator.interactive_enabled() and is_external
		paginator.log('mdblist build list_id=%s is_home=%s is_external=%s setting=%s result=%s -> interactive=%s' %
					(list_id, is_home, is_external, paginator.interactive_enabled(), len(result), interactive))
		if interactive:
			pg_key = paginator.make_key(params)
			pages_to_load = paginator.get_pages(pg_key, paginator.initial_batch())
			# Fill past the requested window when the dub filter thins the list (see _dub_paginate).
			# process_list is already dub-filtered here -> no second _dub_filter_items.
			process_list, pages_consumed, has_more = _dub_paginate(result, pages_to_load, is_external)
			paginator.log('mdblist BUILD key=%s pages=%s consumed=%s shown=%s has_more=%s' %
						(paginator.short(pg_key), pages_to_load, pages_consumed, len(process_list), has_more))
			paginator.set_state(pg_key, pages_consumed, has_more)
			all_movies = [i for i in process_list if i['type'] == 'movie']
			all_tvshows = [i for i in process_list if i['type'] == 'show']
		else:
			process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
			all_movies = _dub_filter_items([i for i in process_list if i['type'] == 'movie'], 'movie', is_external)
			all_tvshows = _dub_filter_items([i for i in process_list if i['type'] == 'show'], 'tvshow', is_external)
		movie_list = {'list': [(i['order'], i['media_ids']) for i in all_movies], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['media_ids']) for i in all_tvshows], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows))], key=lambda k: k[1])[0]
		for function, _list in ((Movies, movie_list), (TVShows, tvshow_list)):
			t = Thread(target=_process, args=(function, _list))
			t.start()
			threads.append(t)
		[t.join() for t in threads]
		item_list.sort(key=lambda k: k[1])
		final_items = [i[0] for i in item_list]
		add_items(handle, final_items)
		if interactive: paginator.set_head(pg_key, final_items)
		if not interactive and total_pages > page_no:
			new_page = str(page_no + 1)
			add_dir({'mode': 'mdblist.list.build_mdblist_list', 'list_id': list_id, 'list_name': list_name,
					'paginate_start': str(paginate_start), 'new_page': new_page},
					'Next Page (%s) >>' % new_page, handle, 'nextpage', nextpage_landscape)
	except: pass
	set_content(handle, content)
	set_category(handle, list_name)
	end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': sleep(1000)
		set_view_mode('view.%s' % content, content, is_external)