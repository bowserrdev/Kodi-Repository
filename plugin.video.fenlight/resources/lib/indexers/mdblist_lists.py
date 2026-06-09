# -*- coding: utf-8 -*-
import sys
from threading import Thread
from apis.mdblist_api import mdblist_get_my_lists, mdblist_get_list_contents
from indexers.movies import Movies
from indexers.tvshows import TVShows
from modules import kodi_utils
from modules.utils import paginate_list
from modules.settings import paginate, page_limit

add_dir, external, sleep, get_icon = kodi_utils.add_dir, kodi_utils.external, kodi_utils.sleep, kodi_utils.get_icon
fanart, set_property = kodi_utils.get_addon_fanart(), kodi_utils.set_property
set_content, set_view_mode, end_directory = kodi_utils.set_content, kodi_utils.set_view_mode, kodi_utils.end_directory
make_listitem, build_url, add_items = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.add_items
nextpage_landscape, set_category, home, folder_path = kodi_utils.nextpage_landscape, kodi_utils.set_category, kodi_utils.home, kodi_utils.folder_path
mdblist_icon = get_icon('lists')

def get_mdblist_lists(params):
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
		lists = mdblist_get_my_lists()
		add_items(handle, list(_process()))
	except: pass
	set_content(handle, 'files')
	set_category(handle, params.get('category_name', 'MDBList'))
	end_directory(handle)
	set_view_mode('view.main')

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
		process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		all_movies = [i for i in process_list if i['type'] == 'movie']
		all_tvshows = [i for i in process_list if i['type'] == 'show']
		movie_list = {'list': [(i['order'], i['media_ids']) for i in all_movies], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['media_ids']) for i in all_tvshows], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows))], key=lambda k: k[1])[0]
		for function, _list in ((Movies, movie_list), (TVShows, tvshow_list)):
			t = Thread(target=_process, args=(function, _list))
			t.start()
			threads.append(t)
		[t.join() for t in threads]
		item_list.sort(key=lambda k: k[1])
		add_items(handle, [i[0] for i in item_list])
		if total_pages > page_no:
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