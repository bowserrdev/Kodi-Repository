# -*- coding: utf-8 -*-
import sys
from apis.mdblist_api import mdblist_get_my_lists, mdblist_get_liked_lists
from indexers.movies import Movies
from indexers.tvshows import TVShows
from modules import sorgenti
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
		_t0 = paginator.now()
		# LOTTO 333 -- come ogni riga paginata, la PREPARA il servizio: qui non si legge la lista e non si va
		# in rete. Il servizio legge la lista intera, la giudica a passi e scrive in `widgets.db` cio' che va
		# mostrato, nell'ordine di consegna (regola del 16/09: chi c'era resta dov'era, i nuovi in coda).
		interactive = is_external
		paginator.log('mdblist build list_id=%s is_home=%s is_external=%s -> preparata=%s' % (list_id, is_home, is_external, interactive))
		if interactive:
			pg_key = paginator.widget_key(params)
			kodi_utils.vieta_rete('mdblist %s' % list_id)
			kodi_utils.tappa('mdblist.sorgente')
			pronta, passi = paginator.passo_pronto(params, pg_key, 'mdblist')
			kodi_utils.tappa('mdblist.pagine')
			process_list = paginator.voci_miste(pronta.voci if pronta else ())
			paginator.log('mdblist BUILD key=%s passi=%s voci=%s' % (paginator.short(pg_key), passi, len(process_list)))
			paginator.set_state(pg_key, pronta.passi if pronta else 0, bool(pronta and pronta.fine and not pronta.altri))
		else:
			result = sorgenti.lista_mdblist(params)
			kodi_utils.tappa('mdblist.sorgente')
			process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		all_movies = [i for i in process_list if i['type'] == 'movie']
		all_tvshows = [i for i in process_list if i['type'] == 'show']
		# Confine reale fra le due fasi. Prima qui si passava _t0 anche come "risolto", quindi la riga
		# PERF diceva sempre "risoluzione 0.00s" e sommava il filtro doppiaggio dentro "costruzione":
		# una lista di serie a 198 elementi risultava costruita in 9.79s con il 100% dei metadati gia'
		# in cache, il che era impossibile e infatti non era vero.
		_t_resolved = paginator.now()
		kodi_utils.tappa('mdblist.risoluzione')
		movie_list = {'list': [(i['order'], i['media_ids']) for i in all_movies], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['media_ids']) for i in all_tvshows], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		if interactive:
			for _l in (movie_list, tvshow_list): _l.update(preparata=True, pg_key=pg_key, pg_params=params)
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows))], key=lambda k: k[1])[0]
		from threading import Thread  # pigro, vedi la nota in caches/base_cache.py
		for function, _list in ((Movies, movie_list), (TVShows, tvshow_list)):
			t = Thread(target=_process, args=(function, _list))
			t.start()
			threads.append(t)
		[t.join() for t in threads]
		kodi_utils.tappa('mdblist.uniti')
		item_list.sort(key=lambda k: k[1])
		final_items = [i[0] for i in item_list]
		add_items(handle, final_items)
		if interactive:
			paginator.set_head(pg_key, final_items, None, params, preparata=True)
			kodi_utils.tappa('mdblist.testa')
			paginator.log_build('mdblist', 'mdblist %s' % list_id, _t0, _t_resolved, paginator.now(), len(final_items),
						passi, params.get('pages'))
		if not interactive and total_pages > page_no:
			new_page = str(page_no + 1)
			add_dir({'mode': 'mdblist.list.build_mdblist_list', 'list_id': list_id, 'list_name': list_name,
					'paginate_start': str(paginate_start), 'new_page': new_page},
					'Next Page (%s) >>' % new_page, handle, 'nextpage', nextpage_landscape)
	except Exception as e:
		# LOTTO 329 -- MAI silenzioso, come in movies.py: con `except: pass` una costruzione che esplodeva
		# consegnava a Kodi una riga vuota e nel log non restava niente. E' cosi' che il disimballaggio
		# sbagliato del 327 e' arrivato sulla stick senza che nessuno lo vedesse.
		import traceback
		kodi_utils.logger('FenLight BUILD FALLITA', 'mdblist: %s\n%s' % (e, traceback.format_exc()))
	set_content(handle, content)
	set_category(handle, list_name)
	end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': sleep(1000)
		set_view_mode('view.%s' % content, content, is_external)