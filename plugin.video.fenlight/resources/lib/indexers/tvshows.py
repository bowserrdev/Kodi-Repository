# -*- coding: utf-8 -*-
import sys
from time import perf_counter as _perf
from modules import meta_lists
from modules import kodi_utils, settings
from modules import paginator
from modules.metadata import tvshow_meta, discover_filter_sort, discover_imdb_sort_from_url, discover_min_rating_from_url, dub_filter
from modules.metadata import tvshow_meta_prefetch, meta_prefetch_key
from modules.utils import manual_function_import, get_datetime, make_thread_list, get_current_timestamp, paginate_list
from modules.watched_status import get_database, watched_info_tvshow, get_watched_status_tvshow, get_progress_status_tvshow
logger = kodi_utils.logger

string, external, add_items, add_dir = str, kodi_utils.external, kodi_utils.add_items, kodi_utils.add_dir
sleep, add_item, cast_label, home, tmdb_api_key = kodi_utils.sleep, kodi_utils.add_item, kodi_utils.cast_label, kodi_utils.home, settings.tmdb_api_key
set_category, make_listitem, build_url, set_property = kodi_utils.set_category, kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.set_property
set_content, end_directory, set_view_mode, folder_path = kodi_utils.set_content, kodi_utils.end_directory, kodi_utils.set_view_mode, kodi_utils.folder_path
poster_empty, nextpage_landscape = kodi_utils.empty_poster, kodi_utils.nextpage_landscape
media_open_action, default_all_episodes, page_limit, paginate = settings.media_open_action, settings.default_all_episodes, settings.page_limit, settings.paginate
widget_hide_next_page, widget_hide_watched, watched_indicators = settings.widget_hide_next_page, settings.widget_hide_watched, settings.watched_indicators
mpaa_region = settings.mpaa_region
run_plugin, container_update = 'RunPlugin(%s)', 'Container.Update(%s)'
# Vedi il commento in movies.py: URL per formattazione diretta invece che con build_url/urlencode.
# Sulle serie il guadagno e' maggiore perche' un elemento costruisce piu' URL, e ben sette di esse
# portavano testo libero (titolo o URL del poster) che urlencode doveva percent-encodare a ogni giro.
# Ora quel testo non viaggia piu': i gestori lo rileggono dai metadati, che avevano gia' in mano o
# che leggono da cache una volta sola, quando l'utente apre davvero la voce.
# ATTENZIONE: qualunque nuovo parametro di testo libero deve tornare a passare da build_url.
_BASE = 'plugin://plugin.video.fenlight/?'
URL_EXTRAS = _BASE + 'mode=extras_menu_choice&tmdb_id=%s&media_type=tvshow&is_external=%s&is_anime=%s'
URL_OPTIONS = _BASE + 'mode=options_menu_choice&content=tvshow&tmdb_id=%s&is_external=%s&is_anime=%s'
URL_MORE_LIKE_THIS = _BASE + 'mode=build_tvshow_list&action=imdb_more_like_this&key_id=%s&name_id=%s&is_external=%s'
URL_SEASON_LIST = _BASE + 'mode=build_season_list&tmdb_id=%s'
URL_ALL_EPISODES = _BASE + 'mode=build_episode_list&tmdb_id=%s&season=all'
URL_MARK_TVSHOW = _BASE + 'mode=watched_status.mark_tvshow&action=%s&tmdb_id=%s&tvdb_id=%s'
URL_WATCHLIST_TOGGLE = _BASE + 'mode=trakt.watchlist_toggle&media_type=tvshow&tmdb_id=%s&in_watchlist=%s'
URL_REFRESH_WIDGETS = _BASE + 'mode=refresh_widgets&user=true'
URL_EXIT_MEDIA_MENU = _BASE + 'mode=navigator.exit_media_menu'
main = ('tmdb_tv_popular', 'tmdb_tv_popular_today', 'tmdb_tv_premieres', 'tmdb_tv_airing_today','tmdb_tv_on_the_air','tmdb_tv_upcoming',
'tmdb_anime_popular', 'tmdb_anime_popular_recent', 'tmdb_anime_premieres', 'tmdb_anime_upcoming', 'tmdb_anime_on_the_air')
special = ('tmdb_tv_languages', 'tmdb_tv_networks', 'tmdb_tv_providers', 'tmdb_tv_year', 'tmdb_tv_decade', 'tmdb_tv_recommendations', 'tmdb_tv_genres',
'tmdb_tv_search', 'tmdb_tv_search_filtered', 'tmdb_tv_keyword_results', 'tmdb_tv_keyword_results_direct', 'tmdb_anime_year', 'tmdb_anime_decade', 'tmdb_anime_genres',
'tmdb_anime_providers', 'tmdb_anime_search')
personal = {'in_progress_tvshows': ('modules.watched_status', 'get_in_progress_tvshows'), 'favorites_tvshows': ('modules.favorites', 'get_favorites'),
'favorites_anime_tvshows': ('modules.favorites', 'get_favorites'), 'watched_tvshows': ('modules.watched_status', 'get_watched_items')}
trakt_main = ('trakt_tv_trending', 'trakt_tv_trending_recent', 'trakt_tv_most_watched', 'trakt_tv_most_favorited',
'trakt_anime_trending', 'trakt_anime_trending_recent', 'trakt_anime_most_watched', 'trakt_anime_most_favorited')
trakt_special = ('trakt_tv_certifications', 'trakt_anime_certifications')
trakt_personal = ('trakt_collection', 'trakt_watchlist', 'trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites')
view_mode, content_type = 'view.tvshows', 'tvshows'
internal_nav_check = ('build_season_list', 'build_episode_list')
# Actions the "dubbed content" filter must NEVER touch: the user's own personal lists (in-progress,
# watched, favorites, Trakt collection/watchlist/favorites). Everything else (tmdb/trakt/anime discovery,
# searches) is filtered. continue_watching / next-episode bypass this path (they call worker() directly).
dub_filter_excluded = set(personal) | set(trakt_personal)

class TVShows:
	def __init__(self, params):
		self.params = params
		self.params_get = self.params.get
		self.category_name = self.params_get('category_name', None) or self.params_get('name', None) or 'TV Shows'
		self.id_type, self.list, self.action = self.params_get('id_type', 'tmdb_id'), self.params_get('list', []), self.params_get('action', None)
		self.items, self.new_page, self.total_pages, self.is_external, self.is_home = [], {}, None, external(), home()
		self.interactive = False
		# Popolato da worker() prima del pool; vuoto significa solo "nessuna anticipazione", non errore.
		self.meta_prefetch = {}
		self.widget_hide_next_page = self.is_home and widget_hide_next_page()
		self.widget_hide_watched = self.is_home and widget_hide_watched()
		self.custom_order = self.params_get('custom_order', 'false') == 'true'
		self.paginate_start = int(self.params_get('paginate_start', '0'))
		self.append = self.items.append
		try: self.is_anime = '_anime_' in self.action
		except: self.is_anime = False
		self.fanart_empty = kodi_utils.addon_fanart()
		# Text-search hub builds are debounced + guarded against stale (out-of-order) completion; for any
		# other build search_query is None and these guards are no-ops. See paginator.search_should_abort.
		self.search_query = self.params_get('query') if (self.action == 'tmdb_tv_search_filtered' and self.params_get('search_hub')) else None

	def fetch_list(self):
		handle = int(sys.argv[1])
		_t0 = paginator.now()
		try:
			is_random = self.params_get('random', 'false') == 'true'
			try: page_no = int(self.params_get('new_page', '1'))
			except: page_no = self.params_get('new_page')
			if page_no == 1 and not self.is_external:
				folderpath = folder_path()
				if not any([x in folderpath for x in internal_nav_check]): set_property('fenlight.exit_params', folderpath)
			if self.action in personal: var_module, import_function = personal[self.action]
			else: var_module, import_function = 'apis.%s_api' % self.action.split('_')[0], self.action
			# Vedi la nota gemella in movies.py (lotto 85): senza questa inizializzazione un import
			# fallito lascia il nome non assegnato e la riga dopo solleva UnboundLocalError, chiudendo
			# la directory vuota. Qui non e' ancora stato osservato in un log, ma il codice e' identico.
			function = None
			try: function = manual_function_import(var_module, import_function)
			except: pass
			fetch_page = self.build_fetch_page(function) if (function and paginator.interactive_enabled() and self.is_external and not is_random) else None
			if fetch_page and settings.dub_filter_enabled() and self.action not in dub_filter_excluded:
				fetch_page = self._apply_dub_filter(fetch_page)
			paginator.log('tvshows fetch_list action=%s is_home=%s is_external=%s random=%s setting=%s -> interactive=%s' %
						(self.action, self.is_home, self.is_external, is_random, paginator.interactive_enabled(), bool(fetch_page)))
			if fetch_page:
				self.interactive = True
				self.pg_key = paginator.widget_key(self.params)
				paginator.log('tvshows BUILD action=%s key=%s params=%s' % (self.action, paginator.short(self.pg_key),
						{k: self.params.get(k) for k in ('mode', 'action', 'category_name', 'key_id', 'url', 'query') if self.params.get(k)}))
				pages_to_load = paginator.get_pages(self.pg_key, paginator.initial_batch(), params=self.params)
				# Fill every build to a full screen: server- or post-build filtering (text search, advanced
				# search) can thin a TMDB page down to a few items, so keep loading until a page's worth is
				# gathered. Neutral for unfiltered widgets (a single page already meets the target).
				min_items = paginator.fill_target()
				self.list, has_more, _last = paginator.load_cumulative(fetch_page, pages_to_load, min_items)
				paginator.set_state(self.pg_key, _last, has_more)
			elif self.action in main:
				data = function(page_no)
				self.list = [i['id'] for i in data['results']]
				if not is_random and  data['total_pages'] > page_no: self.new_page = {'new_page': string(page_no + 1)}
			elif self.action in special:
				key_id = self.params_get('key_id') or self.params_get('query')
				if not key_id: return
				data = function(key_id, page_no)
				self.list = [i['id'] for i in data['results']]
				if not is_random and data['total_pages'] > page_no: self.new_page = {'new_page': string(page_no + 1), 'key_id': key_id}
			elif self.action in personal:
				data = function('anime' if self.is_anime else 'tvshow', page_no)
				data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['media_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
			elif self.action in trakt_main:
				self.id_type = 'trakt_dict'
				data = function(page_no)
				try: self.list = [i['show']['ids'] for i in data]
				except: self.list = [i['ids'] for i in data]
				if not is_random and self.action != 'trakt_recommendations': self.new_page = {'new_page': string(page_no + 1)}
			elif self.action in trakt_special:
				self.id_type = 'trakt_dict'
				key_id = self.params_get('key_id', None)
				if not key_id: return
				data = function(key_id, page_no)
				self.list = [i['show']['ids'] for i in data]
				if not is_random: self.new_page = {'new_page': string(page_no + 1), 'key_id': key_id}
			elif self.action in trakt_personal:
				self.id_type = 'trakt_dict'
				data = function('shows', page_no)
				if self.action in ('trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'): total_pages = 1
				else: data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['media_ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
				except: pass
			elif self.action == 'trakt_recommendations':
				self.id_type = 'trakt_dict'
				data = function('shows')
				data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
				except: pass
			elif self.action == 'tmdb_tv_discover':
				url = self.params_get('url')
				data = function(url, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['total_pages'] > page_no: self.new_page = {'url': url, 'new_page': string(data['page'] + 1)}
			elif self.action == 'imdb_more_like_this':
				if self.params_get('get_imdb'):
					self.params['key_id'] = tvshow_meta('tmdb_id', self.params_get('key_id'), tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())['imdb_id']
				self.id_type = 'imdb_id'
				self.list = function(self.params_get('key_id'))
			# Il nome della lista si risolve QUI, una volta, da cache. Nell'URL della voce costava una
			# percent-codifica del titolo per ogni elemento di ogni lista costruita.
			self._resolve_list_name()
			_t1 = paginator.now()
			items = self.worker()
			paginator.log_build('tvshows', self.action, _t0, _t1, paginator.now(), len(items) if items else 0,
						getattr(self, '_pg_pages', None), self.params_get('pages'))
			if self.search_query and paginator.search_is_stale(self.search_query):
				# A newer keystroke arrived while this build ran: drop the result so it can't overwrite
				# the live container / head bridge. The directory is closed empty in the tail below.
				pass
			else:
				add_items(handle, items)
				if self.interactive: paginator.set_head(self.pg_key, items, self.action)
				if self.new_page and not self.widget_hide_next_page:
							self.new_page.update({'mode': 'build_tvshow_list', 'action': self.action, 'category_name': self.category_name})
							add_dir(self.new_page, 'Next Page (%s) >>' % self.new_page['new_page'], handle, 'nextpage', nextpage_landscape)
		except Exception as e:
			# MAI silenzioso: una build che esplode chiude la directory VUOTA, e il container
			# torna a ricostruirsi da capo -- e' il meccanismo per cui "spariscono le pagine
			# dopo la prima". Senza questo log il fallimento e' invisibile.
			import traceback
			logger('FenLight BUILD FALLITA', 'tvshows action=%s: %s\n%s' % (self.action, e, traceback.format_exc()))
		set_content(handle, content_type)
		set_category(handle, self.category_name)
		end_directory(handle, cacheToDisc=False if self.is_external else True)
		if not self.is_external:
			if self.params_get('refreshed') == 'true': sleep(1000)
			set_view_mode(view_mode, content_type, self.is_external)

	def build_tvshow_content(self, _position, _id):
		try:
			_b0 = _perf()
			# Vedi Movies.build_movie_content: prima il lotto letto in sequenza fuori dal pool.
			_pk = meta_prefetch_key(self.id_type, _id, 'tvshow')
			meta = self.meta_prefetch.get(_pk) if _pk else None
			if meta is None:
				meta = tvshow_meta(self.id_type, _id, self.tmdb_api_key, self.mpaa_region, self.current_date, self.current_time)
			if not meta or 'blank_entry' in meta: return
			_b1 = _perf()
			cm = []
			cm_append = cm.append
			listitem = make_listitem()
			set_properties = listitem.setProperties
			meta_get = meta.get
			premiered = meta_get('premiered')
			trailer, title, year = meta_get('trailer'), meta_get('title'), meta_get('year') or '2050'
			tvdb_id, imdb_id = meta_get('tvdb_id'), meta_get('imdb_id')
			poster, fanart, clearlogo, landscape = meta_get('poster') or poster_empty, meta_get('fanart') or self.fanart_empty, meta_get('clearlogo') or '', meta_get('landscape') or ''
			thumb = poster or landscape or fanart
			tmdb_id, total_seasons, total_aired_eps = meta_get('tmdb_id'), meta_get('total_seasons'), meta_get('total_aired_eps')
			unaired = total_aired_eps == 0
			if unaired: progress, playcount, total_watched, total_unwatched = 0, 0, 0, total_aired_eps
			else:
				playcount, total_watched, total_unwatched = get_watched_status_tvshow(self.watched_info.get(string(tmdb_id), None), total_aired_eps)
				if total_watched: progress = get_progress_status_tvshow(total_watched, total_aired_eps)
				else: progress = 0
				visible_progress = '0' if progress == 100 else progress
			extras_params = URL_EXTRAS % (tmdb_id, self.is_external, self.is_anime)
			options_params = URL_OPTIONS % (tmdb_id, self.is_external, self.is_anime)
			more_like_this_params = URL_MORE_LIKE_THIS % (imdb_id, tmdb_id, self.is_external)
			if self.all_episodes:
				if self.all_episodes == 1 and total_seasons > 1: url_params = URL_SEASON_LIST % tmdb_id
				else: url_params = URL_ALL_EPISODES % tmdb_id
			else: url_params = URL_SEASON_LIST % tmdb_id
			# Stesse voci dei film (vedi movies.py). Extras e le navigazioni secondarie non sono piu'
			# voci di menu: extras_params e more_like_this_params restano pubblicate come proprieta',
			# quindi i tasti rapidi di custom_keys.py continuano a funzionare. Da undici voci a cinque,
			# e addContextMenuItems si paga per OGNI serie costruita.
			if self.open_extras:
				cm_append(('[B]Sfoglia[/B]', container_update % url_params))
				url_params = extras_params
			cm_append(('[B]Opzioni[/B]', run_plugin % options_params))
			if playcount:
				if self.widget_hide_watched: return
			elif not unaired:
				cm_append(('[B]Segna come visto[/B]',
							run_plugin % (URL_MARK_TVSHOW % ('mark_as_watched', tmdb_id, tvdb_id))))
			if progress:
				cm_append(('[B]Segna come non visto[/B]',
							run_plugin % (URL_MARK_TVSHOW % ('mark_as_unwatched', tmdb_id, tvdb_id))))
			in_watchlist = string(tmdb_id) in self.watchlist_ids
			cm_append((('[B]Rimuovi dalla watchlist[/B]' if in_watchlist else '[B]Aggiungi alla watchlist[/B]'),
						run_plugin % (URL_WATCHLIST_TOGGLE % (tmdb_id, 'true' if in_watchlist else 'false'))))
			set_properties({'watchedepisodes': string(total_watched), 'unwatchedepisodes': string(total_unwatched)})
			set_properties({'watchedprogress': visible_progress, 'totalepisodes': string(total_aired_eps), 'totalseasons': string(total_seasons)})
			# "Refresh" e' il superset di "Reload": alza fenlight.refresh_widgets e poi chiama comunque
			# kodi_refresh. Tenuta solo quella, come nei film.
			if self.is_external:
				cm_append(('[B]Aggiorna widget[/B]', run_plugin % URL_REFRESH_WIDGETS))
			else: cm_append(('[B]Esci dalla lista[/B]', run_plugin % URL_EXIT_MEDIA_MENU))
			_b2 = _perf()
			listitem.setLabel(title)
			_b3 = _perf()
			listitem.addContextMenuItems(cm)
			_b4 = _perf()
			listitem.setArt({'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo, 'landscape': landscape, 'thumb': thumb, 'icon': landscape,
							'tvshow.poster': poster, 'tvshow.clearlogo': clearlogo})
			_b5 = _perf()
			info_tag = listitem.getVideoInfoTag()
			info_tag.setMediaType('tvshow'), info_tag.setTitle(title), info_tag.setTvShowTitle(title), info_tag.setOriginalTitle(meta_get('original_title'))
			info_tag.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)}), info_tag.setIMDBNumber(imdb_id)
			info_tag.setPlot(meta_get('plot')), info_tag.setPlaycount(playcount), info_tag.setGenres(meta_get('genre')), info_tag.setYear(int(year))
			info_tag.setTagLine(meta_get('tagline')), info_tag.setStudios(meta_get('studio')), info_tag.setWriters(meta_get('writer')), info_tag.setDirectors(meta_get('director'))
			info_tag.setVotes(meta_get('votes')), info_tag.setMpaa(meta_get('mpaa')), info_tag.setDuration(meta_get('duration')), info_tag.setCountries(meta_get('country'))
			info_tag.setTrailer(meta_get('trailer')), info_tag.setPremiered(premiered)
			info_tag.setTvShowStatus(meta_get('status')), info_tag.setRating(meta_get('rating'))
			# Niente setCast: la skin del cast legge solo i nomi. Vedi kodi_utils.cast_label.
			_b6 = _perf()
			_cast_props = {'fenlight.extras_params': extras_params, 'fenlight.options_params': options_params,
							'fenlight.more_like_this_params': more_like_this_params}
			cast_names = cast_label(meta_get('cast'))
			if cast_names: _cast_props['fenlight.cast'] = cast_names
			set_properties(_cast_props)
			extra_ratings = meta_get('extra_ratings')
			if extra_ratings:
				_rp = {}
				for _k, _n in (('imdb', 'IMDb_Rating'), ('metascore', 'MetaCritic_Rating'), ('tomatometer', 'RottenTomatoes_Rating'), ('tomatousermeter', 'RottenTomatoes_UserMeter')):
					_r = extra_ratings.get(_k, {})
					_v = _r.get('rating', '').replace('%', '')
					if _v: _rp[_n] = _v
					_i = _r.get('icon', '')
					if _i: _rp[_n + '_Icon'] = _i
				_tmdb = meta_get('rating')
				if _tmdb: _rp['TMDb_Rating'] = str(_tmdb)
				if _rp: set_properties(_rp)
			paginator.phase_record(_b1 - _b0, _b2 - _b1, _b3 - _b2, _b4 - _b3, _b5 - _b4, _b6 - _b5, _perf() - _b6)
			self.append(((url_params, listitem, self.is_folder), _position))
		except: pass

	def worker(self):
		self.current_date, self.current_time = get_datetime(), get_current_timestamp()
		self.tmdb_api_key, self.mpaa_region = tmdb_api_key(), mpaa_region()
		self.all_episodes, self.open_extras = default_all_episodes(), media_open_action('tvshow') == 1
		self.is_folder = False if self.open_extras else True
		self.watched_indicators = watched_indicators()
		self.watched_title = 'Trakt' if self.watched_indicators == 1 else 'Fen Light'
		self.watched_info = watched_info_tvshow(get_database(self.watched_indicators))
		# Watchlist Trakt: UNA lettura da cache per costruzione, non una per elemento. Serve solo a
		# decidere se la voce dice Aggiungi o Rimuovi. Import pigro: senza Trakt attivo non si paga il
		# caricamento di trakt_api a ogni lista, e con reuselanguageinvoker=false si pagherebbe davvero.
		if self.watched_indicators == 1:
			from apis.trakt_api import watchlist_tmdb_ids
			self.watchlist_ids = watchlist_tmdb_ids('shows')
		else: self.watchlist_ids = set()
		self.window_command = 'ActivateWindow(Videos,%s,return)' if self.is_external else 'Container.Update(%s)'
		paginator.phase_reset()
		# UNA lettura per l'intera lista, in sequenza. Vedi meta_cache.get_many.
		_pf0 = _perf()
		_ids = [i[1] for i in self.list] if self.custom_order else list(self.list)
		try: self.meta_prefetch = tvshow_meta_prefetch(self.id_type, _ids, self.current_time)
		except: self.meta_prefetch = {}
		paginator.log_prefetch('tvshows %s' % self.action, len(self.list), len(self.meta_prefetch), _perf() - _pf0)
		self._resolve_missing(_ids)
		# Costruzione in SEQUENZA: vedi la nota in Movies.worker -- sotto il pool le chiamate all'API
		# C++ costano fino a 74 volte tanto per l'effetto convoglio sul GIL, e qui non c'e' piu' I/O.
		if self.custom_order:
			for _position, _id in self.list: self.build_tvshow_content(_position, _id)
		else:
			for _position, _id in enumerate(self.list): self.build_tvshow_content(_position, _id)
			self.items.sort(key=lambda k: k[1])
			self.items = [i[0] for i in self.items]
		paginator.phase_report('tvshows %s' % self.action,
							('meta', 'prep+cm', 'setLabel', 'ctxmenu', 'setArt', 'infotag', 'cast+props'))
		return self.items

	# Prefisso del nome lista per azione: name_id porta solo il tmdb_id della serie di partenza,
	# il testo si compone qui. Sostituisce i vecchi parametri 'name'/'category_name', che portavano
	# la frase gia' fatta -- testo libero, quindi da percent-encodare, per ogni elemento di ogni lista.
	_LIST_NAME_PREFIX = {'imdb_more_like_this': 'More Like This based on %s', 'tmdb_tv_recommendations': 'Recommended based on %s'}

	def _resolve_list_name(self):
		# Se manca name_id (URL vecchia ancora in giro, widget salvato) resta il nome che c'era prima.
		name_id = self.params_get('name_id')
		if not name_id or self.params_get('name') or self.params_get('category_name'): return
		prefix = self._LIST_NAME_PREFIX.get(self.action)
		if not prefix: return
		try:
			meta = tvshow_meta('tmdb_id', name_id, tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())
			if meta and meta.get('title'): self.category_name = prefix % meta['title']
		except: pass

	def _resolve_missing(self, ids):
		# Vedi Movies._resolve_missing: i thread restano solo dove il tempo e' attesa di rete.
		missing = []
		prefetch_get = self.meta_prefetch.get
		for media_id in ids:
			key = meta_prefetch_key(self.id_type, media_id, 'tvshow')
			if key and prefetch_get(key) is None: missing.append((key, media_id))
		if not missing: return
		def _fetch(entry):
			key, media_id = entry
			try:
				meta = tvshow_meta(self.id_type, media_id, self.tmdb_api_key, self.mpaa_region, self.current_date, self.current_time)
				if meta: self.meta_prefetch[key] = meta
			except: pass
		_t0 = _perf()
		threads = list(make_thread_list(_fetch, missing))
		[i.join() for i in threads]
		paginator.log_network('tvshows %s' % self.action, len(missing), _perf() - _t0)

	def paginate_list(self, data, page_no):
		if paginate(self.is_home):
			limit = page_limit(self.is_home)
			data, total_pages = paginate_list(data, page_no, limit, self.paginate_start)
			if self.is_home: self.paginate_start = limit
		else: total_pages = 1
		return data, total_pages

	def _apply_dub_filter(self, fetch_page):
		# Wraps an interactive fetch_page so each page's ids are filtered to those with a localised release
		# (streaming or home video) in the chosen language's country. Applied per page so the paginator's
		# fill (min_items) keeps loading until a full screen of survivors is gathered. self.id_type is read
		# here (after build_fetch_page has set it, e.g. 'trakt_dict' for Trakt lists) so meta resolves right.
		country = settings.dub_filter_country()
		if not country: return fetch_page
		api_key, mpaa, cdate, ctime = tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp()
		def wrapped(page_no):
			ids, has_more = fetch_page(page_no)
			ids = dub_filter('tvshow', self.id_type, ids, country, api_key, mpaa, cdate, ctime)
			return ids, has_more
		return wrapped

	def build_fetch_page(self, function):
		# Returns fetch_page(page_no) -> (ids, has_more) for interactive (cumulative) widget pagination,
		# or None for non-paginable/single-page actions (which fall back to the legacy single-page path).
		action = self.action
		limit = page_limit(True)
		if action in main:
			def fetch_page(page_no):
				data = function(page_no)
				return [i['id'] for i in data['results']], data['total_pages'] > page_no
			return fetch_page
		if action in special:
			key_id = self.params_get('key_id') or self.params_get('query')
			if not key_id: return None
			def fetch_page(page_no):
				data = function(key_id, page_no)
				return [i['id'] for i in data['results']], data['total_pages'] > page_no
			return fetch_page
		if action == 'tmdb_tv_discover':
			url = self.params_get('url')
			# Advanced search: re-qualify each TMDb page via IMDb (drop low-vote junk) and, when sorting by
			# rating / no sort, re-order the page by IMDb rating (direction from the URL's sort_by). The
			# music-video filter is movies-only.
			imdb_sort, min_rating = discover_imdb_sort_from_url(url), discover_min_rating_from_url(url)
			api_key, mpaa, cdate, ctime = tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp()
			def fetch_page(page_no):
				data = function(url, page_no)
				ids = [i['id'] for i in data['results']]
				ids = discover_filter_sort('tvshow', ids, imdb_sort, min_rating, api_key, mpaa, cdate, ctime)
				return ids, data['total_pages'] > page_no
			return fetch_page
		if action in personal:
			full = [i['media_id'] for i in function('anime' if self.is_anime else 'tvshow', 1)]
			def fetch_page(page_no):
				return full[(page_no - 1) * limit:page_no * limit], len(full) > page_no * limit
			return fetch_page
		if action in trakt_main:
			self.id_type = 'trakt_dict'
			def fetch_page(page_no):
				data = function(page_no)
				try: ids = [i['show']['ids'] for i in data]
				except: ids = [i['ids'] for i in data]
				return ids, bool(ids)
			return fetch_page
		if action in trakt_special:
			key_id = self.params_get('key_id', None)
			if not key_id: return None
			self.id_type = 'trakt_dict'
			def fetch_page(page_no):
				data = function(key_id, page_no)
				return [i['show']['ids'] for i in data], bool(data)
			return fetch_page
		if action in trakt_personal:
			if action in ('trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'): return None
			self.id_type = 'trakt_dict'
			full = [i['media_ids'] for i in function('shows', 1)]
			def fetch_page(page_no):
				return full[(page_no - 1) * limit:page_no * limit], len(full) > page_no * limit
			return fetch_page
		if action == 'trakt_recommendations':
			self.id_type = 'trakt_dict'
			full = [i['ids'] for i in function('shows')]
			def fetch_page(page_no):
				return full[(page_no - 1) * limit:page_no * limit], len(full) > page_no * limit
			return fetch_page
		return None
