# -*- coding: utf-8 -*-
import sys
from time import perf_counter as _perf
from modules import kodi_utils, settings, paginator
from modules.metadata import tvshow_meta
from modules.utils import get_datetime, adjust_premiered_date, make_thread_list
from modules.watched_status import get_database, watched_info_season, get_watched_status_season, get_progress_status_season
# logger = kodi_utils.logger

poster_empty, cast_label, set_category, home = kodi_utils.empty_poster, kodi_utils.cast_label, kodi_utils.set_category, kodi_utils.home
add_items, set_content, end_directory, set_view_mode = kodi_utils.add_items, kodi_utils.set_content, kodi_utils.end_directory, kodi_utils.set_view_mode
make_listitem, build_url, external, date_offset_info, tmdb_api_key = kodi_utils.make_listitem, kodi_utils.build_url, kodi_utils.external, settings.date_offset, settings.tmdb_api_key
watched_indicators_info, widget_hide_watched, show_specials, mpaa_region = settings.watched_indicators, settings.widget_hide_watched, settings.show_specials, settings.mpaa_region
string, run_plugin, unaired_label, tmdb_poster = str, 'RunPlugin(%s)', '[COLOR red][I]%s[/I][/COLOR]', 'https://image.tmdb.org/t/p/w780%s'
# Vedi il commento in movies.py: URL per formattazione diretta invece che con build_url/urlencode.
# Il poster non viaggia piu' in options_params -- options_menu_choice lo rilegge dai metadati, che
# ha gia' in mano: era un URL da percent-encodare per ogni stagione, per un'icona che si vede solo
# se l'utente apre davvero il menu.
# ATTENZIONE: qualunque parametro di testo libero deve tornare a passare da build_url. Per questo
# le voci mark_season restano su build_url: portano ancora il titolo della serie.
_BASE = 'plugin://plugin.video.fenlight/?'
URL_EPISODE_LIST = _BASE + 'mode=build_episode_list&tmdb_id=%s&season=%s'
URL_EXTRAS = _BASE + 'mode=extras_menu_choice&tmdb_id=%s&media_type=tvshow&is_external=%s'
URL_OPTIONS = _BASE + 'mode=options_menu_choice&content=season&tmdb_id=%s&is_external=%s'
URL_REFRESH_WIDGETS = _BASE + 'mode=refresh_widgets&user=true'
view_mode, content_type = 'view.seasons', 'seasons'
season_name_str = 'Season %s'

def build_season_list(params):
	def _process():
		total_aired_eps, episode_count = meta_get('total_aired_eps'), 0
		for item in season_data:
			try:
				_p0 = _perf()
				cm = []
				cm_append = cm.append
				listitem = make_listitem()
				set_properties = listitem.setProperties
				item_get = item.get
				overview, poster_path, air_date = item_get('overview'), item_get('poster_path'), item_get('air_date')
				season_number, aired_eps = item_get('season_number'), item_get('episode_count')
				season_name = item_get('name', None)
				season_special = season_number == 0
				title = item_get('name', None) or season_name_str % season_number
				if custom_order is not None: title = '%s - %s' % (show_title, title)
				poster = (poster_path if poster_path.startswith('http') else tmdb_poster % poster_path) if poster_path is not None else show_poster
				thumb = poster or show_landscape or show_fanart
				try: year = air_date.split('-')[0]
				except: year = show_year or '2050'
				plot = overview or show_plot
				try: premiered = adjust_premiered_date(air_date, adjust_hours)[1]
				except: premiered = ''
				unaired = aired_eps == 0
				if unaired or season_special:
					progress, playcount, total_watched, total_unwatched = 0, 0, 0, aired_eps
					if unaired: title = unaired_label % title
					else: title = 'Specials'
				else:
					if season_number < total_seasons:
						episode_count += aired_eps
					else: aired_eps = total_aired_eps - episode_count
					playcount, watched, unwatched = get_watched_status_season(watched_info.get(season_number, None), aired_eps)
					progress = get_progress_status_season(watched, aired_eps)
				visible_progress = 0 if progress == 100 else progress
				# panel_nonce: vedi kodi_utils.PANEL_RELOAD_PROP. Nella vista "Combined" il pannello
				# episodi si aggancia a questa URL tramite $INFO[Container(52X).ListItem.FolderPath]:
				# senza il nonce un Container.Refresh ricostruisce le stagioni ma lascia il pannello
				# -- e quindi i badge degli episodi -- fermo su quello di prima.
				url_params = URL_EPISODE_LIST % (tmdb_id, season_number) + panel_nonce
				# extras_params non e' piu' una voce di menu (come nei film e nelle serie) ma resta
				# pubblicato come proprieta': lo legge il tasto rapido di custom_keys.py.
				extras_params = URL_EXTRAS % (tmdb_id, is_external)
				options_params = URL_OPTIONS % (tmdb_id, is_external)
				cm_append(('[B]Opzioni[/B]', run_plugin % options_params))
				if playcount:
					if hide_watched: continue
				elif not unaired and not season_special:
						cm_append(('[B]Segna come visto[/B]', run_plugin % build_url({'mode': 'watched_status.mark_season', 'action': 'mark_as_watched',
															'title': show_title, 'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_number})))
				if progress:
					cm_append(('[B]Segna come non visto[/B]', run_plugin % build_url({'mode': 'watched_status.mark_season', 'action': 'mark_as_unwatched',
														'title': show_title, 'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_number})))
				_p1 = _perf()
				set_properties({'watchedepisodes': string(watched), 'unwatchedepisodes': string(unwatched)})
				set_properties({'totalepisodes': string(aired_eps), 'watchedprogress': string(visible_progress),
								'fenlight.extras_params': extras_params, 'fenlight.options_params': options_params,
								'fenlight.cast': cast_names})
				# "Refresh" e' il superset di "Reload": tenuta solo quella, come nei film.
				if is_external:
					cm_append(('[B]Aggiorna widget[/B]', run_plugin % URL_REFRESH_WIDGETS))
				_p2 = _perf()
				info_tag = listitem.getVideoInfoTag()
				info_tag.setMediaType('season'), info_tag.setTitle(title), info_tag.setOriginalTitle(orig_title), info_tag.setTvShowTitle(show_title), info_tag.setIMDBNumber(imdb_id)
				info_tag.setSeason(season_number), info_tag.setPlot(plot), info_tag.setDuration(episode_run_time), info_tag.setPlaycount(playcount), info_tag.setGenres(genre)
				info_tag.setUniqueIDs({'imdb': imdb_id, 'tmdb': str_tmdb_id, 'tvdb': str_tvdb_id})
				info_tag.setTvShowStatus(status), info_tag.setFirstAired(premiered), info_tag.setStudios(studio), info_tag.setYear(int(year))
				info_tag.setRating(rating), info_tag.setVotes(votes), info_tag.setMpaa(mpaa), info_tag.setCountries(country), info_tag.setTrailer(trailer)
				_p3 = _perf()
				listitem.setLabel(title)
				_p4 = _perf()
				listitem.setArt({'poster': poster, 'season.poster': poster, 'fanart': show_fanart, 'clearlogo': show_clearlogo, 'landscape': show_landscape, 'thumb': thumb,
								'icon': show_landscape, 'tvshow.poster': poster, 'tvshow.clearlogo': show_clearlogo})
				_p5 = _perf()
				listitem.addContextMenuItems(cm)
				paginator.phase_record(_p1 - _p0, _p2 - _p1, _p3 - _p2, _p4 - _p3, _p5 - _p4, _perf() - _p5)
				yield (url_params, listitem, True)
			except: pass
	handle, is_external, is_home, category_name = int(sys.argv[1]), external(), home(), 'Season'
	_t0 = paginator.now()
	# single_seasons chiama questa funzione in PARALLELO, una volta per stagione: azzerare li' le fasi
	# cancellerebbe le misure di una lista che un altro thread sta ancora costruendo. Su quella strada
	# non si riporta nulla, quindi non si azzera nulla.
	if params.get('custom_order', None) is None: paginator.phase_reset()
	fanart_empty = kodi_utils.addon_fanart()
	# Letto UNA volta per costruzione: e' lo stesso valore per tutte le stagioni della lista.
	_nonce = kodi_utils.get_property(kodi_utils.PANEL_RELOAD_PROP)
	panel_nonce = ('&reload=%s' % _nonce) if _nonce else ''
	watched_indicators, adjust_hours, hide_watched = watched_indicators_info(), date_offset_info(), is_home and widget_hide_watched()
	current_date = get_datetime()
	watched_title = 'Trakt' if watched_indicators == 1 else 'Fen Light'
	meta = tvshow_meta('tmdb_id', params['tmdb_id'], tmdb_api_key(), mpaa_region(), current_date)
	meta_get = meta.get
	tmdb_id, tvdb_id, imdb_id, show_title, show_year = meta_get('tmdb_id'), meta_get('tvdb_id'), meta_get('imdb_id'), meta_get('title'), meta_get('year') or '2050'
	orig_title, status, show_plot = meta_get('original_title', ''), meta_get('status'), meta_get('plot')
	str_tmdb_id, str_tvdb_id, rating, genre = string(tmdb_id), string(tvdb_id), meta_get('rating'), meta_get('genre')
	cast, mpaa, votes, trailer, studio, country = meta_get('cast', []), meta_get('mpaa'), meta_get('votes'), string(meta_get('trailer')), meta_get('studio'), meta_get('country')
	# Il cast e' quello della serie: uguale per tutte le stagioni, quindi si compone UNA volta qui
	# invece che dentro il ciclo. Vedi kodi_utils.cast_label.
	cast_names = cast_label(cast)
	episode_run_time, season_data, total_seasons = meta_get('duration'), meta_get('season_data'), meta_get('total_seasons')
	show_poster, show_fanart = meta_get('poster') or poster_empty, meta_get('fanart') or fanart_empty
	show_clearlogo, show_landscape = meta_get('clearlogo') or '', meta_get('landscape') or ''
	custom_order = params.get('custom_order', None)
	if show_specials(): season_data.sort(key=lambda i: (i['season_number'] == 0, i['season_number']))
	elif custom_order is not None: season_data = [i for i in season_data if i['season_number'] == params['season']]
	else:
		season_data = [i for i in season_data if not i['season_number'] == 0]
		season_data.sort(key=lambda k: k['season_number'])
	watched_info = watched_info_season(tmdb_id, get_database(watched_indicators))
	# Qui finisce la RISOLUZIONE (una sola lettura di tvshow_meta per l'intera lista) e comincia la
	# costruzione. Le stagioni non hanno un prefetch: i metadati della serie coprono tutte le voci.
	_t1 = paginator.now()
	list_items = list(_process())
	# La strada custom_order e' single_seasons, che chiama questa funzione una volta PER stagione:
	# loggarla stamperebbe una riga per stagione invece di una per lista.
	if custom_order is not None: return (list_items[0], custom_order)
	paginator.log_build('seasons', show_title, _t0, _t1, paginator.now(), len(list_items))
	paginator.phase_report('seasons %s' % show_title, ('prep+cm', 'props', 'infotag', 'setLabel', 'setArt', 'ctxmenu'))
	add_items(handle, list_items)
	category_name = show_title
	set_content(handle, content_type)
	set_category(handle, category_name)
	# RITIRATO il cacheToDisc=False incondizionato di a1edbba (lotto 50). Il baratto era stato prezzato
	# a "30-100 ms di rilettura al ritorno", ma quei millisecondi erano il PERF 'totale', cioe' la sola
	# COSTRUZIONE. Il log di debug del 23/08 misura l'invocazione intera: build_episode_list 15,99 s e
	# 20,41 s. Sbagliato di oltre 200 volte, e non era il solo prezzo: senza cache, tornando dal player
	# Kodi non ha la cartella da ripristinare, il path arriva vuoto ('CDirectoryProvider[]: refreshing',
	# 'GetDirectory - Error getting ' alle 22:41:15) e si ricade sul genitore. Da li' i tre difetti
	# segnalati dall'utente: pagina vuota dopo il player, "segna come visto" senza effetto a schermo,
	# menu contestuale sulla serie invece che sull'episodio -- perche' a schermo c'era davvero la serie.
	# Questo e' un TAMPONE, non la soluzione: il badge "episodi rimanenti" puo' tornare a restare
	# vecchio finche' non si riapre la serie. La soluzione vera e' invalidare la cache in modo MIRATO
	# quando siamo noi a cambiare lo stato visto, non spegnerla sempre per tutti.
	end_directory(handle, cacheToDisc=False if is_external else True)
	set_view_mode(view_mode, content_type, is_external)

def single_seasons(seasons_list):
	def _process(item): season_results_append(build_season_list(item))
	season_results = []
	season_results_append = season_results.append
	threads = make_thread_list(_process, seasons_list)
	[i.join() for i in threads]
	return [i for i in season_results if i]