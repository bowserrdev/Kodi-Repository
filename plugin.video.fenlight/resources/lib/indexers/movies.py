# -*- coding: utf-8 -*-
import sys
from time import perf_counter as _perf
from modules import kodi_utils, settings
from modules import paginator, sorgenti
from modules.metadata import movie_meta, movieset_meta
from modules.metadata import movie_meta_prefetch, meta_prefetch_key
from modules.utils import get_datetime, make_thread_list, get_current_timestamp, paginate_list, jsondate_to_datetime
from modules.watched_status import get_database, watched_info_movie, get_watched_status_movie, get_bookmarks_movie, get_progress_status_movie
logger = kodi_utils.logger

make_listitem, build_url, nextpage_landscape = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.nextpage_landscape
string, external, add_items, add_dir, get_property = str, kodi_utils.external, kodi_utils.add_items, kodi_utils.add_dir, kodi_utils.get_property
set_content, end_directory, set_view_mode, folder_path = kodi_utils.set_content, kodi_utils.end_directory, kodi_utils.set_view_mode, kodi_utils.folder_path
poster_empty, set_property = kodi_utils.empty_poster, kodi_utils.set_property
sleep, cast_label, set_category = kodi_utils.sleep, kodi_utils.cast_label, kodi_utils.set_category
add_item, home = kodi_utils.add_item, kodi_utils.home
watched_indicators, widget_hide_next_page = settings.watched_indicators, settings.widget_hide_next_page
media_open_action, page_limit, paginate = settings.media_open_action, settings.page_limit, settings.paginate
tmdb_api_key, mpaa_region = settings.tmdb_api_key, settings.mpaa_region
run_plugin = 'RunPlugin(%s)'
# URL della singola voce costruite per FORMATTAZIONE DIRETTA invece che con build_url/urlencode.
# Misurato sul Mac: le otto build_url di un elemento costano 32,67 us, le stesse stringhe formattate
# 0,92 us -- 35 volte meno, e il risultato e' identico byte per byte. Su una lista da 249 elementi
# sono 8,1 ms degli 9 ms che il log attribuisce alla fase prep+cm.
# Funziona perche' qui dentro NON C'E' NULLA DA PERCENT-ENCODARE: interi (tmdb_id), id imdb 'tt...',
# booleani, e per il resto letterali. urlencode scansionava comunque ogni carattere di ogni valore.
# ATTENZIONE: qualunque valore di testo libero -- titoli, nomi di raccolte, URL di poster -- deve
# continuare a passare da build_url. Messo qui, si romperebbe al primo spazio o '&' nel testo.
_BASE = 'plugin://plugin.video.fenlight/?'
URL_PLAY = _BASE + 'mode=playback.media&media_type=movie&tmdb_id=%s'
URL_EXTRAS = _BASE + 'mode=extras_menu_choice&media_type=movie&tmdb_id=%s&is_external=%s'
URL_OPTIONS = _BASE + 'mode=options_menu_choice&content=movie&tmdb_id=%s&is_external=%s'
URL_MORE_LIKE_THIS = _BASE + 'mode=build_movie_list&action=imdb_more_like_this&key_id=%s&name_id=%s&is_external=%s'
URL_PLAYBACK_CHOICE = _BASE + 'mode=playback_choice&media_type=movie&meta=%s'
URL_MARK = _BASE + 'mode=watched_status.mark_movie&action=%s&tmdb_id=%s'
URL_WATCHLIST_TOGGLE = _BASE + 'mode=trakt.watchlist_toggle&media_type=movie&tmdb_id=%s&in_watchlist=%s'
URL_ERASE_BOOKMARK = _BASE + 'mode=watched_status.erase_bookmark&media_type=movie&tmdb_id=%s&refresh=true'
URL_REFRESH_WIDGETS = _BASE + 'mode=refresh_widgets&user=true'
URL_EXIT_MEDIA_MENU = _BASE + 'mode=navigator.exit_media_menu'
# LOTTO 331 -- le azioni stanno in modules/sorgenti.py, con le sorgenti che le leggono. Qui restano i nomi
# che usano i rami a pagina singola (lotto 335).
_AZIONI = sorgenti.AZIONI['movie']
main, special, personal, trakt_main, trakt_personal = _AZIONI['main'], _AZIONI['special'], _AZIONI['personal'], \
	_AZIONI['trakt_main'], _AZIONI['trakt_personal']
# meta_list_dict e' stato rimosso (lotto 110): era costruito qui a ogni import e non lo leggeva
# NESSUNO. Le liste dei menu Discover stanno in indexers/random_lists.py, che ha le proprie copie
# (movie_meta_list_dict / tvshow_meta_list_dict); da fuori di questo file si importa solo Movies.
# Era l'unico motivo per cui movies.py caricava modules.meta_lists, 494 righe di sole tabelle.
view_mode, content_type = 'view.movies', 'movies'

class Movies:
	def __init__(self, params):
		self.params = params
		self.params_get = self.params.get
		self.category_name = self.params_get('category_name', None) or self.params_get('name', None) or 'Movies'
		self.id_type, self.list, self.action = self.params_get('id_type', 'tmdb_id'), self.params_get('list', []), self.params_get('action', None)
		self.items, self.new_page, self.total_pages, self.is_external, self.is_home = [], {}, None, external(), home()
		# LOTTO 333 -- `preparata`: questa istanza costruisce gli elementi di una lista mista che il servizio ha
		# preparato (Trakt, MDbList). Vale la stessa regola delle righe paginate: niente rete, schede scadute
		# servite, mancanti segnalate -- per conto della lista (pg_key, pg_params), non di questa istanza.
		self.interactive = bool(self.params_get('preparata'))
		if self.interactive: self.pg_key, self.pg_params = self.params['pg_key'], self.params['pg_params']
		# Popolato da worker() prima del pool; vuoto significa solo "nessuna anticipazione", non errore.
		self.meta_prefetch = {}
		self.widget_hide_next_page = self.is_home and widget_hide_next_page()
		self.custom_order = self.params_get('custom_order', 'false') == 'true'
		self.paginate_start = int(self.params_get('paginate_start', '0'))
		self.append = self.items.append
		self.movieset_list_active = False
		self.fanart_empty = kodi_utils.addon_fanart()
		# Text-search hub builds are debounced + guarded against stale (out-of-order) completion; for any
		# other build search_query is None and these guards are no-ops. See paginator.search_should_abort.
		self.search_query = self.params_get('query') if (self.action == 'tmdb_movies_search_filtered' and self.params_get('search_hub')) else None


	# LOTTO 119. Vedi la nota al punto di chiamata di set_head.
	PG_MEDIA_TYPE = 'movie'
	# L'identita' di un elemento, per tutto il sistema, e' la coppia (tipo, id TMDb): la stessa che sta
	# nel database. Qui il tipo e' fisso -- questa classe costruisce film.
	PG_TIPO = paginator.TIPI['movie']

	def pg_action(self):
		"""L'azione pubblicata per la ricarica mirata, qualificata per tipo di media.

		Non e' self.action perche' lo stesso nome di azione costruisce due widget diversi a seconda
		della classe che lo esegue. None resta None: un widget senza azione continua a essere deciso
		dal solo elenco degli id, come prima.
		"""
		if not self.action: return None
		return '%s:%s' % (self.action, self.PG_MEDIA_TYPE)

	def fetch_list(self):
		handle = int(sys.argv[1])
		_t0 = paginator.now()
		try:
			try: page_no = int(self.params_get('new_page', '1'))
			except: page_no = self.params_get('new_page')
			if page_no == 1 and not self.is_external: set_property('fenlight.exit_params', folder_path())
			# LOTTO 333 -- una riga paginata la PREPARA il servizio (modules/preparatore.py): qui non si legge
			# nessuna sorgente e non si va in rete, si legge dal database cio' che il servizio ha deciso. Se
			# non basta, passo_pronto lo chiede e aspetta la risposta.
			paginata = self.is_external and sorgenti.paginabile('movie', self.params)
			# `function` serve solo ai rami a pagina singola; None quando l'azione non ha una funzione
			# omonima (lotto 85: 'tmdb_movies_sets' si risolve piu' sotto). Vedi sorgenti.funzione_api.
			function = None if paginata else sorgenti.funzione_api('movie', self.action)
			paginator.log('movies fetch_list action=%s is_home=%s is_external=%s -> preparata=%s' %
						(self.action, self.is_home, self.is_external, paginata))
			if paginata:
				self.interactive = True
				kodi_utils.vieta_rete('movies %s' % self.action)
				self.pg_key, self.pg_params = paginator.widget_key(self.params), self.params
				# Dal database arrivano numeri TMDb, qualunque fosse la forma degli id della sorgente.
				self.id_type = 'tmdb_id'
				kodi_utils.tappa('movies.sorgente')
				paginator.log('movies BUILD action=%s key=%s params=%s' % (self.action, paginator.short(self.pg_key),
						{k: self.params.get(k) for k in ('mode', 'action', 'category_name', 'key_id', 'url', 'query') if self.params.get(k)}))
				pronta, self._pg_pages = paginator.passo_pronto(self.params, self.pg_key, 'movie', self.pg_action())
				kodi_utils.tappa('movies.pagine')
				self.list = [tmdb for _tipo, tmdb in (pronta.voci if pronta else ())]
				paginator.set_state(self.pg_key, pronta.passi if pronta else 0, bool(pronta and pronta.fine and not pronta.altri))
			elif self.action in main:
				data = function(page_no)
				self.list = [i['id'] for i in data['results']]
				if data['total_pages'] > page_no: self.new_page = {'new_page': string(data['page'] + 1)}
			elif self.action in special:
				key_id = self.params_get('key_id') or self.params_get('query')
				if not key_id: return
				data = function(key_id, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['total_pages'] > page_no: self.new_page = {'new_page': string(data['page'] + 1), 'key_id': key_id}
			elif self.action in personal:
				data = function('movie', page_no)
				if self.action == 'recent_watched_movies': total_pages = 1
				else: data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['media_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
			elif self.action in trakt_main:
				self.id_type = 'trakt_dict'
				data = function(page_no)
				try: self.list = [i['movie']['ids'] for i in data]
				except: self.list = [i['ids'] for i in data]
				if self.action not in ('trakt_movies_top10_boxoffice', 'trakt_recommendations'): self.new_page = {'new_page': string(page_no + 1)}
			elif self.action in trakt_personal:
				self.id_type = 'trakt_dict'
				data = function('movies', page_no)
				if self.action in ('trakt_collection_lists', 'trakt_watchlist_lists', 'trakt_favorites'): total_pages = 1
				else: data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['media_ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
				except: pass
			elif self.action == 'trakt_recommendations':
				self.id_type = 'trakt_dict'
				data = function('movies')
				data, total_pages = self.paginate_list(data, page_no)
				self.list = [i['ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'paginate_start': self.paginate_start}
				except: pass
			elif self.action == 'tmdb_movies_discover':
				url = self.params_get('url')
				data = function(url, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['total_pages'] > page_no: self.new_page = {'url': url, 'new_page': string(data['page'] + 1)}
			elif self.action  == 'tmdb_movies_sets':
				self.movieset_list_active = True
				data = sorted(movieset_meta(self.params_get('key_id'), tmdb_api_key())['parts'], key=lambda k: k['release_date'] or '2050')
				self.list = [i['id'] for i in data]
			elif self.action == 'imdb_more_like_this':
				if self.params_get('get_imdb'):
					self.params['key_id'] = movie_meta('tmdb_id', self.params_get('key_id'), tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())['imdb_id']
				self.id_type = 'imdb_id'
				self.list = function(self.params_get('key_id'))
				# Il titolo del film di partenza si risolve QUI, una volta, da cache: nell'URL della voce
				# costava una percent-codifica per ogni elemento di ogni lista costruita.
				self._resolve_more_like_this_name()
			_t1 = paginator.now()
			kodi_utils.tappa('movies.risoluzione')
			items = self.worker()
			paginator.log_build('movies', self.action, _t0, _t1, paginator.now(), len(items) if items else 0,
						getattr(self, '_pg_pages', None), self.params_get('pages'))
			if self.search_query and paginator.search_is_stale(self.search_query):
				# A newer keystroke arrived while this build ran: drop the result so it can't overwrite
				# the live container / head bridge. The directory is closed empty in the tail below.
				pass
			else:
				add_items(handle, items)
				# AZIONE QUALIFICATA PER TIPO DI MEDIA (lotto 119). 'trakt_watchlist' e' lo stesso nome di
				# azione per DUE widget distinti -- la watchlist dei film la costruisce questa classe,
				# quella delle serie la gemella in indexers/tvshows.py -- e finche' l'azione pubblicata era il nome nudo
				# i due erano indistinguibili: aggiungere un film ricostruiva anche la watchlist delle
				# serie. Il qualificatore lo aggiunge chi COSTRUISCE, che e' l'unico a sapere con
				# certezza di che tipo e' il proprio widget. Chi chiede senza qualificatore li prende
				# ancora entrambi: vedi paginator._action_matches.
				if self.interactive:
					paginator.set_head(self.pg_key, items, self.pg_action(), self.params, preparata=True)
					kodi_utils.tappa('movies.testa')
				if self.new_page and not self.widget_hide_next_page:
						self.new_page.update({'mode': 'build_movie_list', 'action': self.action, 'category_name': self.category_name})
						add_dir(self.new_page, 'Next Page (%s) >>' % self.new_page['new_page'], handle, 'nextpage', nextpage_landscape)
		except Exception as e:
			# MAI silenzioso: una build che esplode chiude la directory VUOTA, e il container
			# torna a ricostruirsi da capo -- e' il meccanismo per cui "spariscono le pagine
			# dopo la prima". Senza questo log il fallimento e' invisibile.
			import traceback
			logger('FenLight BUILD FALLITA', 'movies action=%s: %s\n%s' % (self.action, e, traceback.format_exc()))
		set_content(handle, content_type)
		set_category(handle, self.category_name)
		end_directory(handle, cacheToDisc=False if self.is_external else True)
		if not self.is_external:
			if self.params_get('refreshed') == 'true': sleep(1000)
			set_view_mode(view_mode, content_type, self.is_external)
		
	def build_movie_content(self, _position, _id):
		try:
			_t0 = _perf()
			# Prima il lotto gia' letto in sequenza fuori dal pool; solo chi manca paga la lettura
			# singola qui dentro (e, se non e' in cache, la rete -- che e' il caso in cui i thread
			# servono davvero).
			_pk = meta_prefetch_key(self.id_type, _id)
			meta = self.meta_prefetch.get(_pk) if _pk else None
			if meta is None:
				# Una riga preparata non scarica: la scheda che manca la chiede al servizio (lotto 333).
				if self.interactive:
					self._mancanti.append(_id); return
				meta = movie_meta(self.id_type, _id, self.tmdb_api_key, self.mpaa_region, self.current_date, self.current_time)
			if not meta or 'blank_entry' in meta: return
			_t1 = _perf()
			listitem = make_listitem()
			cm = []
			cm_append = cm.append
			set_properties = listitem.setProperties
			clearprog_params, watched_status_params = '', ''
			meta_get = meta.get
			premiered = meta_get('premiered')
			title, year = meta_get('title'), meta_get('year') or '2050'
			tmdb_id, imdb_id = meta_get('tmdb_id'), meta_get('imdb_id')
			str_tmdb_id = string(tmdb_id)
			poster, fanart, clearlogo, landscape = meta_get('poster') or poster_empty, meta_get('fanart') or self.fanart_empty, meta_get('clearlogo') or '', meta_get('landscape') or ''
			thumb = poster or landscape or fanart
			movieset_id, movieset_name = meta_get('extra_info').get('collection_id', None), meta_get('extra_info').get('collection_name', None)
			first_airdate = jsondate_to_datetime(premiered, '%Y-%m-%d', True)
			if not first_airdate or self.current_date < first_airdate: unaired = True
			else: unaired = False
			progress = get_progress_status_movie(self.bookmarks, str_tmdb_id)
			playcount = get_watched_status_movie(self.watched_info, str_tmdb_id)
			play_params = URL_PLAY % tmdb_id
			# options_params e' sia voce di menu sia tasto rapido. extras_params e more_like_this_params
			# non sono piu' voci, ma restano perche' custom_keys.py li legge dalle proprieta' della listitem.
			extras_params = URL_EXTRAS % (tmdb_id, self.is_external)
			# Il poster non viaggia piu' nell'URL: options_menu_choice legge gia' i metadati per conto suo
			# e da li' ricava anche l'immagine. Era un URL da ~70 caratteri da percent-encodare per ogni
			# elemento di ogni lista, per un'icona che si vede solo se l'utente apre davvero il menu.
			options_params = URL_OPTIONS % (tmdb_id, self.is_external)
			# Stessa logica per il titolo: si passa name_id e il nome della lista si compone all'apertura.
			more_like_this_params = URL_MORE_LIKE_THIS % (imdb_id, tmdb_id, self.is_external)
			belongs_to_movieset = 'true' if all([movieset_id, movieset_name]) else 'false'
			movieset_active = self.open_movieset and belongs_to_movieset == 'true'
			if self.open_extras or movieset_active: cm_append(('[B]Riproduci[/B]', run_plugin % play_params))
			if movieset_active: url_params = build_url({'mode': 'open_movieset_choice', 'key_id': movieset_id, 'name': movieset_name, 'is_external': self.is_external})
			elif self.open_extras: url_params = extras_params
			else: url_params = play_params
			cm_append(('[B]Opzioni[/B]', run_plugin % options_params))
			cm_append(('[B]Opzioni di riproduzione[/B]', run_plugin % (URL_PLAYBACK_CHOICE % tmdb_id)))
			# Il titolo non viaggia piu' nell'URL: mark_movie lo rilegge dai metadati (una lettura da cache,
			# e solo quando l'utente clicca davvero) prima di scriverlo nella tabella watched.
			if playcount:
				cm_append(('[B]Segna come non visto[/B]', run_plugin % (URL_MARK % ('mark_as_unwatched', tmdb_id))))
			elif not unaired:
				cm_append(('[B]Segna come visto[/B]', run_plugin % (URL_MARK % ('mark_as_watched', tmdb_id))))
			in_watchlist = str_tmdb_id in self.watchlist_ids
			cm_append((('[B]Rimuovi dalla watchlist[/B]' if in_watchlist else '[B]Aggiungi alla watchlist[/B]'),
						run_plugin % (URL_WATCHLIST_TOGGLE % (tmdb_id, 'true' if in_watchlist else 'false'))))
			if progress:
				cm_append(('[B]Azzera avanzamento[/B]', run_plugin % (URL_ERASE_BOOKMARK % tmdb_id)))
			# "Refresh" e' il superset di "Reload": alza fenlight.refresh_widgets, che i widget random leggono
			# per rigenerare una selezione nuova, e poi chiama comunque kodi_refresh. Tenuto solo quello.
			if self.is_external:
				cm_append(('[B]Aggiorna widget[/B]', run_plugin % URL_REFRESH_WIDGETS))
			else: cm_append(('[B]Esci dalla lista[/B]', run_plugin % URL_EXIT_MEDIA_MENU))
			_t2 = _perf()
			info_tag = listitem.getVideoInfoTag()
			info_tag.setMediaType('movie'), info_tag.setTitle(title), info_tag.setOriginalTitle(meta_get('original_title')), info_tag.setGenres(meta_get('genre'))
			info_tag.setDuration(meta_get('duration')), info_tag.setPlaycount(playcount), info_tag.setPlot(meta_get('plot'))
			info_tag.setUniqueIDs({'imdb': imdb_id, 'tmdb': str_tmdb_id}), info_tag.setIMDBNumber(imdb_id), info_tag.setPremiered(premiered)
			info_tag.setYear(int(year)), info_tag.setRating(meta_get('rating')), info_tag.setVotes(meta_get('votes')), info_tag.setMpaa(meta_get('mpaa'))
			info_tag.setCountries(meta_get('country')), info_tag.setTrailer(meta_get('trailer'))
			info_tag.setTagLine(meta_get('tagline')), info_tag.setStudios(meta_get('studio'))
			info_tag.setWriters(meta_get('writer')), info_tag.setDirectors(meta_get('director'))
			_t3 = _perf()
			# Niente setCast: la skin del cast legge solo i nomi, e li riceve come proprieta'.
			# Vedi kodi_utils.cast_label.
			cast_names = cast_label(meta_get('cast'))
			_t4 = _perf()
			if progress: info_tag.setResumePoint(float(progress))
			listitem.setLabel(title)
			_t5 = _perf()
			listitem.addContextMenuItems(cm)
			_t6 = _perf()
			listitem.setArt({'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo, 'landscape': landscape, 'thumb': thumb})
			_t7 = _perf()
			# UNA sola setProperties invece di due o tre: erano gia' tutte proprieta' dello stesso
			# listitem, quindi il dizionario si compone in Python (costo nullo) e si attraversa il
			# confine verso il C++ una volta sola.
			# hide_add_remove_favourite: TOGLIE 'Aggiungi ai preferiti' dal menu contestuale, ed e' un
			# aggancio ufficiale di Kodi, non un trucco. In xbmc/ContextMenus.cpp (branch Omega, cioe'
			# la 21 che gira sulla stick) CAddRemoveFavourite::IsVisible comincia con:
			#     if (item.GetProperty("hide_add_remove_favourite").asBoolean()) return false;
			# Serve perche' i preferiti di Kodi sono un elenco suo, scollegato da quelli di Fen Light:
			# la voce c'era sempre e non portava da nessuna parte.
			#
			# LE ALTRE DUE VOCI DI KODI NON SI POSSONO TOGLIERE, e sta scritto qui perche' nessuno ci
			# riprovi fra sei mesi:
			#  - 'Segna come gia' visto' (CVideoMarkWatched) compare per qualunque elemento non-cartella
			#    con un video info tag e playcount 0. Nessuna proprieta' la disattiva; l'unico modo
			#    sarebbe non mettere il video info tag, cioe' lasciare la skin senza metadati.
			#  - 'Informazioni' (CVideoInfo) idem: la sua IsVisible parte da HasVideoInfoTag().
			# E il vecchio rimedio non c'e' piu': il parametro `replaceItems` di addContextMenuItems e'
			# deprecato da Krypton e in Omega e' IGNORATO -- il corpo della funzione non lo legge
			# nemmeno, scrive solo le proprieta' contextmenulabel(N)/contextmenuaction(N).
			_props = {'fenlight.extras_params': extras_params, 'fenlight.options_params': options_params,
						'belongs_to_collection': belongs_to_movieset, 'fenlight.more_like_this_params': more_like_this_params,
						'hide_add_remove_favourite': 'true'}
			if cast_names: _props['fenlight.cast'] = cast_names
			if progress: _props['WatchedProgress'] = progress
			extra_ratings = meta_get('extra_ratings')
			if extra_ratings:
				for _k, _n in (('imdb', 'IMDb_Rating'), ('metascore', 'MetaCritic_Rating'), ('tomatometer', 'RottenTomatoes_Rating'), ('tomatousermeter', 'RottenTomatoes_UserMeter')):
					_r = extra_ratings.get(_k, {})
					_v = _r.get('rating', '').replace('%', '')
					if _v: _props[_n] = _v
					_i = _r.get('icon', '')
					if _i: _props[_n + '_Icon'] = _i
				_tmdb = meta_get('rating')
				if _tmdb: _props['TMDb_Rating'] = str(_tmdb)
			set_properties(_props)
			paginator.phase_record(_t1 - _t0, _t2 - _t1, _t3 - _t2, _t4 - _t3, _t5 - _t4, _t6 - _t5, _t7 - _t6, _perf() - _t7)
			self.append(((url_params, listitem, False), _position))
		except: pass

	def worker(self):
		kodi_utils.tappa('movies.worker_in')
		# LOTTO 324 -- da qui in poi questa costruzione ha in mano visti, segnalibri e watchlist, e
		# quindi COPRE qualunque cambiamento di stato arrivato fin qui: una ricarica mirata per id
		# non serve piu'. Il timbro va prima delle letture, non dopo: cio' che conta e' che tutto
		# quello che si legge da questo istante in avanti sia gia' aggiornato.
		paginator.marca_stato_letto()
		self.current_date, self.current_time, self.watched_indicators = get_datetime(), get_current_timestamp(), watched_indicators()
		self.tmdb_api_key, self.mpaa_region = tmdb_api_key(), mpaa_region()
		self.watched_title = 'Trakt' if self.watched_indicators == 1 else 'Fen Light'
		watched_db = get_database(self.watched_indicators)
		self.watched_info, self.bookmarks = watched_info_movie(watched_db), get_bookmarks_movie(watched_db)
		# Watchlist Trakt: UNA lettura da cache per costruzione (come watched_info e bookmarks),
		# non una per elemento. Serve a decidere se la voce di menu dice Aggiungi o Rimuovi.
		if self.watched_indicators == 1:
			# import pigro: senza Trakt attivo non si paga il caricamento di trakt_api (requests, ecc.)
			# a ogni costruzione di lista -- e con reuselanguageinvoker=false si pagherebbe davvero ogni volta.
			from apis.trakt_api import watchlist_tmdb_ids
			self.watchlist_ids = watchlist_tmdb_ids('movies')
		else: self.watchlist_ids = set()
		self.window_command = 'ActivateWindow(Videos,%s,return)' if self.is_external else 'Container.Update(%s)'
		open_action = media_open_action('movie')
		self.open_movieset = open_action in (2, 3) and not self.movieset_list_active
		self.open_extras = open_action in (1, 3)
		paginator.phase_reset()
		kodi_utils.tappa('movies.preparato')
		# UNA lettura per l'intera lista, in sequenza. Vedi meta_cache.get_many.
		_pf0 = _perf()
		_ids = [i[1] for i in self.list] if self.custom_order else list(self.list)
		# LOTTO 333 -- una riga preparata serve anche le schede SCADUTE (le rinnova il servizio): meglio un
		# dato di qualche giorno che un titolo che sparisce o una costruzione che va in rete.
		self._scadute, self._mancanti = [], []
		try: self.meta_prefetch = movie_meta_prefetch(self.id_type, _ids, self.current_time,
													self._scadute if self.interactive else None)
		except: self.meta_prefetch = {}
		paginator.log_prefetch('movies %s' % self.action, len(self.list), len(self.meta_prefetch), _perf() - _pf0)
		# I thread SOLO per chi deve andare in rete: li' l'attesa e' I/O, il GIL e' rilasciato per
		# millisecondi veri e il parallelismo funziona davvero.
		kodi_utils.tappa('movies.prefetch')
		if not self.interactive:
			self._resolve_missing(_ids)
			kodi_utils.tappa('movies.rete')
		# La costruzione, invece, e' in SEQUENZA. Misurato sul Mi Stick: la stessa singola chiamata
		# addContextMenuItems costa 0.2 ms nel thread principale e 14.9 ms dentro il pool a 6 worker --
		# 74 volte tanto. Tolta la lettura dei metadati (lotto 14), nel pool non restava nulla che
		# beneficiasse dei thread: solo Python e chiamate all'API C++, che il GIL serializza comunque.
		# I worker non parallelizzavano, si facevano la coda a vicenda sul passaggio di consegne del GIL.
		if self.custom_order:
			for _position, _id in self.list: self.build_movie_content(_position, _id)
		else:
			for _position, _id in enumerate(self.list): self.build_movie_content(_position, _id)
			self.items.sort(key=lambda k: k[1])
			self.items = [i[0] for i in self.items]
		kodi_utils.tappa('movies.elementi')
		if self.interactive:
			tipo = self.PG_TIPO
			paginator.segnala_schede(self.pg_key, self.pg_params, 'movie', [(tipo, int(t)) for t in self._scadute],
									[(tipo, paginator.tmdb_di(t)) for t in self._mancanti if paginator.tmdb_di(t)])
		paginator.phase_report('movies %s' % self.action, ('meta', 'prep+cm', 'infotag', 'cast', 'setLabel', 'ctxmenu', 'setArt', 'props'))
		paginator.selftest()
		return self.items

	def _resolve_more_like_this_name(self):
		# name_id e' il tmdb_id del film da cui la lista e' partita. Sostituisce il vecchio parametro
		# 'name', che portava il titolo gia' composto: una stringa di testo libero, quindi da
		# percent-encodare, moltiplicata per ogni elemento di ogni lista. Se manca (URL vecchia
		# ancora in giro, o widget salvato) resta il 'name' che c'era prima: nessuna regressione.
		name_id = self.params_get('name_id')
		if not name_id or self.params_get('name') or self.params_get('category_name'): return
		try:
			meta = movie_meta('tmdb_id', name_id, tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp())
			if meta and meta.get('title'): self.category_name = 'More Like This based on %s' % meta['title']
		except: pass

	def _resolve_missing(self, ids):
		# Voci non servite dal prefetch (assenti, scadute, o con id non risolvibile): vanno chieste alla
		# rete. Risolte QUI, prima della costruzione, cosi' che build_movie_content non faccia mai I/O e
		# possa girare in sequenza. Il risultato entra nello stesso dizionario del prefetch: l'assegnazione
		# a un dizionario e' atomica sotto GIL, quindi non serve un lock fra i thread.
		missing = []
		prefetch_get = self.meta_prefetch.get
		for media_id in ids:
			key = meta_prefetch_key(self.id_type, media_id)
			if key and prefetch_get(key) is None: missing.append((key, media_id))
		if not missing: return
		def _fetch(entry):
			key, media_id = entry
			try:
				meta = movie_meta(self.id_type, media_id, self.tmdb_api_key, self.mpaa_region, self.current_date, self.current_time)
				if meta: self.meta_prefetch[key] = meta
			except: pass
		_t0 = _perf()
		threads = list(make_thread_list(_fetch, missing))
		[i.join() for i in threads]
		paginator.log_network('movies %s' % self.action, len(missing), _perf() - _t0)

	def paginate_list(self, data, page_no):
		if paginate(self.is_home):
			limit = page_limit(self.is_home)
			data, total_pages = paginate_list(data, page_no, limit, self.paginate_start)
			if self.is_home: self.paginate_start = limit
		else: total_pages = 1
		return data, total_pages
