# -*- coding: utf-8 -*-
# apis.trakt_api NON si importa piu' qui (lotto 51). Era un import a livello di modulo, quindi lo
# pagava CHIUNQUE toccasse watched_status -- compresa la lista stagioni, che di Trakt non chiede
# niente: legge lo stato visto dal database locale. trakt_api sono 1155 righe e si porta dietro
# 'requests' con tutto il suo albero. Misura del 24/08: build_season_list spendeva 2094 ms di
# import per 23 ms di lavoro vero. Ora l'import sta nelle sette funzioni che lo usano davvero.
# LOTTO 126 -- stesso rimedio, applicato al resto della testata. watched_status e' importato a
# livello di modulo da OGNI indexer e dal router, quindi il suo albero lo paga chiunque lo sfiori:
# 'azzera avanzamento' dal menu contestuale costava 423 ms totali, di cui 374 di import, per una
# DELETE su una riga. Le quattro righe che stavano qui tiravano dentro modules.metadata (e con lui
# modules.paginator e caches.meta_cache), caches.main_cache e modules.utils -- nessuno dei quali
# serve a cancellare un segnalibro.
# La mappa e' verificata sull'albero sintattico, non a occhio:
#   metadata + get_datetime -> _map_to_tmdb_episode, active_tvshows_information, mark_movie,
#                              mark_season, mark_tvshow
#   main_cache              -> get_hidden_progress_items, hide_unhide_progress_items
#   sort_for_article        -> i quattro costruttori di elenchi
#   adjust_premiered_date   -> mark_season, mark_tvshow
#   make_thread_list        -> active_tvshows_information
#   datetime                -> get_last_played_value
#   database                -> clear_local_bookmarks
# E due nomi erano MORTI, importati e mai usati: cache_object e get_timestamp.
from caches.base_cache import connect_database
from modules import kodi_utils, settings
# logger = kodi_utils.logger

watched_indicators_function, lists_sort_order, date_offset, nextep_method = settings.watched_indicators, settings.lists_sort_order, settings.date_offset, settings.nextep_method
sleep, progressDialogBG, get_video_database_path = kodi_utils.sleep, kodi_utils.progressDialogBG, kodi_utils.get_video_database_path
notification, kodi_refresh, tmdb_api_key, mpaa_region = kodi_utils.notification, kodi_utils.kodi_refresh, settings.tmdb_api_key, settings.mpaa_region
kodi_refresh_ids = kodi_utils.kodi_refresh_ids
tv_progress_location = settings.tv_progress_location
progress_db_string, indicators_dict = 'fenlight_hidden_progress_items', {0: 'watched_db', 1: 'trakt_db'}
finished_show_check = ('Ended', 'Canceled')

# Stessa logica del lotto 51 qui sopra, applicata a threading e a caches.trakt_cache (lotto 101).
# TUTTI i thread di questo modulo stanno sul percorso di SCRITTURA -- marcare visto, spingere un
# segnalibro su Trakt, ripulire un progresso -- che la costruzione di un widget non tocca mai. Ma
# watched_status e' importato a livello di modulo da ogni indexer, quindi quel percorso di scrittura
# faceva pagare threading (e con lui _weakrefset) a ogni lista costruita. Vale lo stesso per
# trakt_cache, importato per un'unica chiamata dentro il ramo Trakt di mark_watched.
# Vedi la nota in caches/base_cache.py per il perche' threading costi e _thread no.
def _spawn(target, args=()):
	from threading import Thread
	Thread(target=target, args=args).start()

def get_database(watched_indicators=None):
	return connect_database(indicators_dict[watched_indicators or watched_indicators_function()])

# def cache_watched_tvshow_status(function, status_type, watched_indicators=None):
# 	watched_indicators = watched_indicators or watched_indicators_function()
# 	dbcon = get_database(watched_indicators)
# 	cache = dbcon.execute('SELECT media_id, status FROM watched_status WHERE db_type = ?', (status_type,)).fetchone()
# 	if cache is not None:
# 		expiration, result = cache
# 		if int(expiration) > get_timestamp(): return eval(result)
# 		clear_cache_watched_tvshow_status(watched_indicators, (status_type,))
# 	result = function(status_type)
# 	dbcon.execute('INSERT OR REPLACE INTO watched_status VALUES (?, ?, ?)', (status_type, get_timestamp(12), repr(result)))
# 	return result or []

# def clear_cache_watched_tvshow_status(watched_indicators=None, status_types=('watched', 'progress')):
# 	try:
# 		watched_indicators = watched_indicators or watched_indicators_function()
# 		dbcon = get_database()
# 		for status in status_types: dbcon.execute('DELETE FROM watched_status WHERE db_type = ?', (status,))
# 		dbcon.execute('VACUUM')
# 		return True
# 	except: return False

def hide_unhide_progress_items(params):
	from caches.main_cache import main_cache
	action, media_id = params['action'], int(params.get('media_id', '0'))
	current_items = main_cache.get(progress_db_string) or []
	if action == 'hide': current_items.append(media_id)
	else: current_items.remove(media_id)
	main_cache.set(progress_db_string, current_items, 1825)
	# L'id e' in mano: si ricaricano i soli contenitori che contengono questo elemento.
	return refresh_container_for(media_id, True)

def get_last_played_value(watched_indicators):
	from datetime import datetime
	if watched_indicators == 0: return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	else: return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

def _map_to_tmdb_episode(tmdb_id, season, episode):
	# NIENTE STAGIONE O EPISODIO: non c'e' niente da mappare, e si esce PRIMA di toccare la rete
	# (lotto 115). Senza questa riga un FILM finiva comunque dentro tvshow_meta, cioe' una chiamata
	# TMDb a /tv/<id_del_film>: nel log del 30/08 due volte, /tv/931285 e /tv/680493, entrambe
	# partite da _push_bookmark_to_trakt con media_type=movie. L'esito non cambiava -- int('') alza
	# ValueError e il vecchio 'except' tornava (season, episode), gli stessi valori che si tornano
	# adesso -- ma il prezzo si pagava lo stesso: una richiesta di rete inutile a ogni segnalibro di
	# un film, cioe' durante la riproduzione e alla chiusura del player, dove la rete e' contesa.
	# La guardia sta QUI e non nel chiamante perche' questa funzione parla di episodi per definizione:
	# cosi' vale anche per _mark_on_trakt (dove oggi e' il chiamante a passare ep_map_for=None per i
	# film) e per qualunque uso futuro.
	from modules import metadata
	from modules.utils import get_datetime
	if season in (None, '') or episode in (None, ''): return season, episode
	try:
		int(season); int(episode)
	except: return season, episode
	try:
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime())
		ep_map = meta.get('tvdb_to_tmdb_ep')
		if ep_map is None:
			from apis.skyhook_api import get_tvdb_to_tmdb_map
			ep_map = get_tvdb_to_tmdb_map(meta.get('tvdb_id'), meta.get('tmdb_season_data_original', []))
		return ep_map.get((int(season), int(episode)), (season, episode))
	except: return season, episode

def make_batch_insert(action, media_type, media_id, season, episode, last_played, title):
	if action == 'mark_as_watched': return (media_type, media_id, season, episode, last_played, title)
	else: return (media_type, media_id, season, episode)

def refresh_container_for(media_id, refresh=True):
	# Quando sappiamo QUALE elemento e' cambiato -- e in tutte le voci del menu contestuale lo sappiamo
	# -- si ricaricano i soli contenitori che lo contengono invece di sparare UpdateLibrary, che
	# ricostruisce ogni widget della schermata. Senza media_id si ricade sul globale.
	# coalesce=False: ogni chiamante e' una voce del menu contestuale, cioe' un comando esplicito.
	# Due comandi consecutivi sullo stesso titolo ('segna come visto' e poi 'segna come non visto')
	# sono due eventi distinti e vanno eseguiti entrambi, altrimenti l'interfaccia resta indietro
	# rispetto a un'operazione che su Trakt e' gia' andata a buon fine.
	# L'AZIONE viaggia sempre (lotto 114): ogni chiamante di questa funzione e' una modifica di stato
	# visto/avanzamento, cioe' esattamente cio' che cambia la COMPOSIZIONE di 'continua a guardare' --
	# un film che entra quando lo metti in pausa, uno che esce quando ne azzeri l'avanzamento. La
	# regola per id non puo' decidere quel caso, perche' in aggiunta l'id non e' ancora nell'elenco
	# del widget e in rimozione l'elenco e' quello di prima.
	if not refresh: return
	if media_id: return kodi_refresh_ids([str(media_id)], (kodi_utils.CONTINUE_WATCHING_ACTION,), coalesce=False)
	kodi_refresh(coalesce=False)

def active_tvshows_information(status_type):
	from modules import metadata
	from modules.utils import get_datetime, make_thread_list
	def _process(item):
		media_id = item['media_id']
		meta = metadata.tvshow_meta('tmdb_id', media_id, api_key, mpaa_region_value, get_datetime())
		watched_status = get_watched_status_tvshow(watched_info[media_id], meta.get('total_aired_eps'))[0]
		airing_status = meta.get('status', '')
		if status_type == 'watched':
			if watched_status == 1:
				if not include_other and airing_status not in finished_show_check: return
				results_append(item)
		else:
			if watched_status == 0: results_append(item)
			elif include_other and airing_status not in finished_show_check: results_append(item)
	results = []
	results_append = results.append
	watched_indicators = watched_indicators_function()
	watched_info = watched_info_tvshow()
	api_key, mpaa_region_value = tmdb_api_key(), mpaa_region()
	data = [v for k, v in watched_info.items()]
	progress_location = tv_progress_location()
	if status_type == 'watched': include_other = progress_location in (0, 2)
	else: include_other = progress_location in (1, 2)
	threads = list(make_thread_list(_process, data))
	[i.join() for i in threads]
	return results

def watched_info_movie(watched_db=None):
	if not watched_db: watched_db = get_database()
	try:
		watched_info = watched_db.execute('SELECT media_id, title, last_played FROM watched WHERE db_type = ?', ('movie',)).fetchall()
		return dict([(i[0], {'media_id': i[0], 'title': i[1], 'last_played': i[2]}) for i in watched_info])
	except: return {}

def get_watched_status_movie(watched_info, media_id):
	if not watched_info: return 0
	try:
		watched = 1 if media_id in watched_info else 0
		return watched
	except: return 0

def get_bookmarks_movie(watched_db=None):
	if not watched_db: watched_db = get_database()
	try:
		info = watched_db.execute('SELECT media_id, resume_point, curr_time, resume_id FROM progress WHERE db_type = ?', ('movie',)).fetchall()
		info = dict([(i[0], {'media_id': i[0], 'resume_point': i[1], 'curr_time': i[2], 'resume_id': i[3]}) for i in info])
	except: info = {}
	return info

def get_progress_status_movie(progress_info, media_id):
	try: percent = str(round(float(progress_info[media_id]['resume_point'])))
	except: percent = None
	return percent

def watched_info_tvshow(watched_db=None):
	if not watched_db: watched_db = get_database()
	try:
		data = watched_db.execute('SELECT media_id, season, episode, title, MAX(last_played), COUNT(*) AS COUNTER FROM watched WHERE db_type = ? GROUP BY media_id',
								('episode',)).fetchall()
		return dict([(i[0], {'media_id': i[0], 'season': i[1], 'episode': i[2], 'title': i[3], 'last_played': i[4], 'total_played': i[5]}) for i in data])
	except: return {}

def get_watched_status_tvshow(watched_info, aired_eps):
	if not watched_info: return 0, 0, aired_eps
	try:
		watched = min(watched_info['total_played'], aired_eps)
		unwatched = aired_eps - watched
		if watched >= aired_eps: playcount = 1
		else: playcount = 0
		return playcount, watched, unwatched
	except: return 0, 0, aired_eps

def get_progress_status_tvshow(watched, aired_eps):
	try: progress = int((float(watched)/aired_eps)*100) or 1
	except: progress = 1
	return progress

def watched_info_season(media_id, watched_db=None):
	if not watched_db: watched_db = get_database()
	try: watched_info = dict(watched_db.execute('SELECT season, COUNT(*) AS COUNTER FROM watched WHERE db_type = ? AND media_id = ? GROUP BY media_id, season',
							('episode', str(media_id))).fetchall())
	except: watched_info = {}
	return watched_info

def get_watched_status_season(watched_info, aired_eps):
	if not watched_info: return 0, 0, aired_eps
	try:
		watched = min(watched_info, aired_eps)
		unwatched = aired_eps - watched
		if watched >= aired_eps: playcount = 1
		else: playcount = 0
		return playcount, watched, unwatched
	except: return 0, 0, aired_eps

def get_progress_status_season(watched, aired_eps):
	try: progress = int((float(watched)/aired_eps)*100)
	except: progress = 0
	return progress

def watched_info_episode(media_id, watched_db=None):
	# Torna un SET, non una lista (lotto 102). Ogni consumatore di questo valore lo usa solo con `in`
	# (get_watched_status_episode e' due righe: `if season_episode in watched_info`), e get_next fa
	# quel controllo per OGNI episodio candidato di OGNI stagione a partire da quella corrente. Con la
	# lista ogni controllo e' una scansione lineare di tutti gli episodi visti della serie: simulato
	# sui dati veri della stick (1087 episodi visti su 22 serie) sono **96.313 confronti di tuple**
	# per passata, contro **969** con il set. I tipi non cambiano: sqlite3 torna gia' tuple di interi.
	if not watched_db: watched_db = get_database()
	try: watched_info = set(watched_db.execute('SELECT season, episode FROM watched WHERE db_type = ? AND media_id = ?', ('episode', str(media_id))).fetchall())
	except: watched_info = set()
	return watched_info

def get_watched_status_episode(watched_info, season_episode):
	if season_episode in watched_info: return 1
	return 0

def get_bookmarks_episode(media_id, season, watched_db=None):
	if not watched_db: watched_db = get_database()
	try:
		info = watched_db.execute('SELECT resume_point, curr_time, resume_id, episode FROM progress WHERE db_type = ? AND media_id = ? AND season = ?',
			('episode', str(media_id), int(season))).fetchall()
		info = dict([(i[3], {'resume_point': i[0], 'curr_time': i[1], 'resume_id': i[2]}) for i in info])
	except: info = {}
	return info

def get_bookmarks_all_episode(media_id, total_seasons, watched_db=None):
	if not watched_db: watched_db = get_database()
	all_seasons_info = {}
	for season in range(1, total_seasons + 1):
		try:
			season_info = get_bookmarks_episode(media_id, season, watched_db)
			all_seasons_info[season] = season_info
		except: pass
	return all_seasons_info

def get_progress_status_episode(progress_info, episode):
	try: percent = str(round(float(progress_info[episode]['resume_point'])))
	except: percent = None
	return percent

def get_progress_status_all_episode(progress_info, season, episode):
	try: percent = str(round(float(progress_info[season][episode]['resume_point'])))
	except: percent = None
	return percent

def clear_local_bookmarks():
	from caches.base_cache import database
	try:
		dbcon = database.connect(get_video_database_path())
		file_ids = dbcon.execute("SELECT idFile FROM files WHERE strFilename LIKE 'plugin.video.fenlight%'").fetchall()
		for i in ('bookmark', 'streamdetails', 'files'): dbcon.executemany("DELETE FROM %s WHERE idFile=?" % i, file_ids)
	except: pass

def _mark_on_trakt(args, cache_media_type, ep_map_for=None):
	# La chiamata di rete la paga un thread di sfondo, non l'interfaccia. Il badge legge la riga
	# LOCALE, che a questo punto e' gia' scritta: aspettare Trakt per aggiornarlo significava tenere
	# ferma l'interfaccia su un dato che era gia' pronto. Stesso schema di _clear_progress_on_trakt.
	# Compromesso accettato esplicitamente: se Trakt fallisce, l'avviso arriva DOPO l'aggiornamento e
	# lo stato locale resta in anticipo su quello remoto fino alla prima sincronizzazione utile.
	# ep_map_for porta la conversione episodio tvdb->tmdb, che a cache fredda e' un'altra chiamata di
	# rete (skyhook): va nel thread anche quella, o meta' del guadagno resterebbe sul percorso caldo.
	from apis.trakt_api import trakt_watched_status_mark
	try:
		if ep_map_for is not None:
			args = tuple(args) + _map_to_tmdb_episode(*ep_map_for)
		if not trakt_watched_status_mark(*args): return notification('Error')
		from caches.trakt_cache import clear_trakt_collection_watchlist_data
		clear_trakt_collection_watchlist_data('watchlist', cache_media_type)
		# Timbro per il monitor Trakt: questo cambiamento l'abbiamo fatto NOI e la riga locale e' gia'
		# scritta. Senza, il monitor lo scambia per una modifica remota e ricostruisce l'intera
		# cronologia -- 6 pagine e 1275 episodi, 4 secondi sul Mi Stick. Vedi trakt_watched_episodes.
		# Il timbro porta anche il TIPO. Con il solo istante, marcare un episodio avrebbe zittito per
		# due minuti anche il controllo sui film: se in quella finestra fosse arrivata una modifica ai
		# film da un altro dispositivo, sarebbe stata saltata -- e persa per sempre, perche'
		# reset_activity ha gia' registrato la nuova attivita' come vista. Il tipo elimina la
		# sovrapposizione: ogni guardia riconosce solo le proprie marcature.
		try:
			from time import time as _now
			kodi_utils.set_property('fenlight.trakt.self_mark', '%s|%s' % (_now(), cache_media_type))
		except: pass
	except: pass

def _clear_progress_on_trakt(media_type, media_id, season, episode, resume_id):
	# L'attesa di un secondo era gia' qui prima: ora la paga un thread di sfondo invece
	# dell'interfaccia. Se fallisce, la riga locale e' comunque gia' andata: il segnalibro remoto
	# viene ripulito alla prima sincronizzazione Trakt utile.
	try:
		sleep(1000)
		# L'IMPORT STA DOPO L'ATTESA, e non e' pignoleria (lotto 126 bis). Prima stava sopra, quindi
		# questo thread cominciava a caricare apis.trakt_api -- con metadata, paginator, utils,
		# main_cache, meta_cache, lists_cache, trakt_cache, piu' re, json, hashlib e unicodedata: 31
		# moduli -- NELLO STESSO ISTANTE in cui l'invocazione principale stava ancora finendo. Con il
		# GIL non e' lavoro parallelo, e' lavoro sottratto. La prova sta nel log della stick del
		# 02/09 alle 16:12: fra gli import contati dall'invocazione compare '40 ms _weakrefset <-
		# threading', e threading in questo percorso lo importa soltanto _spawn -- cioe' il conto
		# della fase di sfondo cadeva dentro la finestra di quella in primo piano.
		# L'attesa di un secondo c'era gia' e non fa niente: e' il posto giusto per pagare l'import,
		# perche' quando finisce l'invocazione e' chiusa da un pezzo.
		from apis.trakt_api import trakt_progress
		trakt_progress('clear_progress', media_type, media_id, 0, season, episode, resume_id)
	except: pass

def erase_bookmark(media_type, media_id, season='', episode='', refresh='false'):
	try:
		watched_indicators = watched_indicators_function()
		watched_db = get_database(watched_indicators)
		resume_id = None
		if watched_indicators == 1:
			# Il resume_id si legge PRIMA della cancellazione, perche' viene dalla riga che stiamo per
			# togliere. E' una lettura locale, costa nulla.
			try:
				if media_type == 'episode': resume_id = get_bookmarks_episode(str(media_id), season, watched_db)[int(episode)]['resume_id']
				else: resume_id = get_bookmarks_movie()[str(media_id)]['resume_id']
			except: resume_id = None
		# Stesso ordine di set_bookmark (lotto 27), qui era ancora rovesciato: si dormiva un secondo, si
		# chiamava Trakt in rete, e solo ALLA FINE si cancellava la riga locale e si aggiornava
		# l'interfaccia. Da li' la sensazione che 'azzera avanzamento' non facesse niente. La riga locale
		# e' il dato che il badge legge: si cancella subito, l'interfaccia si aggiorna subito, e
		# l'allineamento con Trakt lo paga un thread di sfondo.
		watched_db.execute('DELETE FROM progress where db_type = ? and media_id = ? and season = ? and episode = ?', (media_type, media_id, season, episode))
		refresh_container_for(media_id, refresh == 'true')
		if watched_indicators == 1 and resume_id is not None:
			_spawn(_clear_progress_on_trakt, (media_type, media_id, season, episode, resume_id))
	except: pass

def batch_erase_bookmark(watched_indicators, insert_list, action):
	try:
		watched_db = get_database(watched_indicators)
		if action == 'mark_as_watched': modified_list = [(i[0], i[1], i[2], i[3]) for i in insert_list]
		else: modified_list = insert_list
		if watched_indicators == 1:
			def _process():
				from apis.trakt_api import trakt_progress
				for i in insert_list:
					try:
						media_id, season, episode = i[1], i[2], i[3]
						resume_id = get_bookmarks_episode(str(media_id), season, watched_db)[int(episode)]['resume_id']
						sleep(1000)
						trakt_progress('clear_progress', i[0], i[1], 0, i[2], i[3], resume_id)
					except: pass
			_spawn(_process)
		watched_db.executemany('DELETE FROM progress where db_type = ? and media_id = ? and season = ? and episode = ?', modified_list)
	except: pass

def _push_bookmark_to_trakt(media_type, tmdb_id, season, episode, resume_point):
	# Allineamento remoto del segnalibro, fuori dal percorso che fa comparire il badge.
	# NIENTE trakt_sync_activities qui: e' la sincronizzazione completa (scarica liste, progressi e
	# metadati serie) ed e' quella che bloccava tutto per decine di secondi a ogni chiusura del
	# player. Serve a recepire i cambiamenti fatti ALTROVE, ed e' compito del TraktMonitor periodico:
	# quello che abbiamo appena guardato lo sappiamo gia' noi.
	from apis.trakt_api import trakt_progress
	try:
		_ts, _te = _map_to_tmdb_episode(tmdb_id, season, episode)
		resume_id = trakt_progress('set_progress', media_type, tmdb_id, resume_point, _ts, _te) or 0
		if resume_id:
			get_database(1).execute('UPDATE progress SET resume_id = ? WHERE db_type = ? and media_id = ? and season = ? and episode = ?',
									(resume_id, media_type, tmdb_id, season, episode))
	except: pass

def set_bookmark(params):
	# STRUMENTAZIONE (lotto 125). Questa funzione e' misurata a 806-1275 ms sulla stick, ed e' il
	# numero che rende fragile tutta la zona: e' la finestra dentro cui la rilettura spontanea di Kodi
	# puo' arrivare prima del dato. La INSERT non puo' costare tanto, ma la stima e' gia' stata
	# sbagliata una volta ('una manciata di operazioni SQLite'), percio' stavolta si misura invece di
	# dedurre. I sospetti sono le LETTURE DI CONFIGURAZIONE che vengono prima: watched_indicators
	# (proprieta' di finestra o SQLite) e soprattutto trakt_official_status, che fa due
	# getCondVisibility piu' l'apertura delle impostazioni di script.trakt -- cioe' chiede il lock
	# della GUI proprio mentre il thread grafico e' occupato a smontare il player e a rinegoziare
	# l'HDMI. Le fasi si stampano in una riga sola.
	from time import perf_counter as _pc
	_lap = [_pc()]
	_ph = []
	def _lap_ms(_name):
		_n = _pc(); _ph.append('%s %.0f ms' % (_name, (_n - _lap[0]) * 1000)); _lap[0] = _n
	def _report(_esito):
		try: kodi_utils.perf_log('FenLight PERF BOOKMARK', '%s | %s' % (_esito, ' + '.join(_ph)))
		except: pass
	from apis.trakt_api import trakt_official_status
	_lap_ms('import trakt_api')
	try:
		media_type, tmdb_id, curr_time, total_time = params.get('media_type'), params.get('tmdb_id'), params.get('curr_time'), params.get('total_time')
		refresh = False if params.get('from_playback', 'false') == 'true' else True
		title, season, episode = params.get('title'), params.get('season'), params.get('episode')
		adjusted_current_time = float(curr_time) - 5
		resume_point = round(adjusted_current_time/float(total_time)*100,1)
		watched_indicators = watched_indicators_function()
		_lap_ms('watched_indicators')
		if watched_indicators == 1:
			_official = trakt_official_status(media_type)
			_lap_ms('trakt_official_status')
			if _official == False: return _report('uscita anticipata (scrobble delegato a script.trakt)')
			else:
				# Il minuto a cui si e' chiuso e' un dato LOCALE: lo sappiamo gia', e il badge legge
				# solo questa riga. Quindi si scrive SUBITO e l'allineamento con Trakt va in secondo
				# piano. Prima l'ordine era rovesciato -- due chiamate di rete piu' una
				# sincronizzazione Trakt completa, e solo alla fine la riga -- e su un dispositivo
				# debole il badge compariva decine di secondi dopo, con tutti i widget della home in
				# attesa. Il resume_id nasce a 0 e arriva dopo: serve solo a cancellare il segnalibro
				# da remoto (erase_bookmark), non a mostrare il progresso.
				try:
					dbcon = get_database(1)
					_lap_ms('apertura database')
					dbcon.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
						(media_type, tmdb_id, season, episode, str(resume_point), str(curr_time), get_last_played_value(1), 0, title))
					# La riga e' NOSTRA e Trakt non puo' ancora saperlo: si annota, cosi' la
					# riscrittura in blocco non la scambia per una cancellazione remota anche dopo
					# che la spinta asincrona le avra' messo il resume_id vero (lotto 128).
					kodi_utils.note_local_progress_write(media_type, tmdb_id, season, episode)
					_lap_ms('INSERT')
				except: pass
				_spawn(_push_bookmark_to_trakt, (media_type, tmdb_id, season, episode, resume_point))
				_lap_ms('avvio push a Trakt')
		else:
			erase_bookmark(media_type, tmdb_id, season, episode)
			_lap_ms('erase_bookmark')
			last_played = get_last_played_value(watched_indicators)
			dbcon = get_database(watched_indicators)
			_lap_ms('apertura database')
			dbcon.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
						(media_type, tmdb_id, season, episode, str(resume_point), str(curr_time), last_played, 0, title))
			kodi_utils.note_local_progress_write(media_type, tmdb_id, season, episode)
			_lap_ms('INSERT')
		refresh_container_for(tmdb_id, refresh)
		_lap_ms('refresh_container_for')
		_report('scritto')
	except: pass

def mark_movie(params):
	from modules import metadata
	from modules.utils import get_datetime
	action, media_type = params.get('action'), 'movie'
	refresh, from_playback = params.get('refresh', 'true') == 'true', params.get('from_playback', 'false') == 'true'
	if from_playback: refresh = False
	tmdb_id, title = params.get('tmdb_id'), params.get('title')
	# Il titolo finisce nella tabella watched e serve a ordinare la lista "Visti", quindi va scritto.
	# Ma non deve viaggiare nell'URL della voce di menu: e' testo libero, quindi da percent-encodare
	# per ogni elemento di ogni lista costruita. Qui costa una lettura da cache, e solo quando
	# l'utente clicca davvero. Il parametro resta accettato, per le URL gia' in giro.
	if not title and action == 'mark_as_watched':
		try: title = metadata.movie_meta('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime()).get('title', '')
		except: title = ''
	watched_indicators = watched_indicators_function()
	# Prima il locale e l'interfaccia, poi la rete. Vedi _mark_on_trakt.
	watched_status_mark(watched_indicators, media_type, tmdb_id, action, title=title)
	refresh_container_for(tmdb_id, refresh)
	if watched_indicators == 1:
		_spawn(_mark_on_trakt, ((action, 'movies', tmdb_id), media_type))

def mark_tvshow(params):
	from modules import metadata
	from modules.utils import get_datetime, adjust_premiered_date
	title, action, tmdb_id = params.get('title', ''), params.get('action'), params.get('tmdb_id')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	watched_indicators = watched_indicators_function()
	progress_backround = progressDialogBG()
	progress_backround.create('[B]Please Wait..[/B]', '')
	# La rete parte subito ma in PARALLELO al lotto locale, che qui e' lungo (un inserimento per
	# episodio, con dialogo di avanzamento): prima la si aspettava e basta.
	if watched_indicators == 1:
		_spawn(_mark_on_trakt, ((action, 'shows', tmdb_id, tvdb_id), 'tvshow'))
	current_date = get_datetime()
	insert_list = []
	insert_append = insert_list.append
	meta = metadata.tvshow_meta('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime())
	# I metadati servivano comunque qui: il titolo si prende da loro invece di farlo viaggiare
	# percent-encodato nell'URL di ogni voce di ogni lista. Il parametro resta accettato.
	if not title: title = meta.get('title', '')
	season_data = meta['season_data']
	season_data = [i for i in season_data if i['season_number'] > 0]
	total = len(season_data)
	last_played = get_last_played_value(watched_indicators)
	for count, item in enumerate(season_data, 1):
		season_number = item['season_number']
		ep_data = metadata.episodes_meta(season_number, meta)
		for ep in ep_data:
			season_number = ep['season']
			ep_number = ep['episode']
			display = '%s - S%.2dE%.2d' % (title, int(season_number), int(ep_number))
			progress_backround.update(int(float(count)/float(total)*100), '[B]Please Wait..[/B]', display)
			episode_date, premiered = adjust_premiered_date(ep['premiered'], date_offset())
			if episode_date and current_date < episode_date: continue
			insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
	batch_watched_status_mark(watched_indicators, insert_list, action)
	progress_backround.close()
	refresh_container_for(tmdb_id)

def mark_season(params):
	from modules import metadata
	from modules.utils import get_datetime, adjust_premiered_date
	season = int(params.get('season'))
	if season == 0: return notification('Failed')
	insert_list = []
	insert_append = insert_list.append
	action, title, tmdb_id = params.get('action'), params.get('title'), params.get('tmdb_id')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	watched_indicators = watched_indicators_function()
	heading = '[B]Mark Watched %s[/B]' if action == 'mark_as_watched' else '[B]Mark Unwatched %s[/B]'
	# Come mark_tvshow: la rete in parallelo al lotto locale, non davanti.
	if watched_indicators == 1:
		_spawn(_mark_on_trakt, ((action, 'season', tmdb_id, tvdb_id, season), 'tvshow'))
	progress_backround = progressDialogBG()
	progress_backround.create('[B]Please Wait..[/B]', '')
	current_date = get_datetime()
	meta = metadata.tvshow_meta('tmdb_id', tmdb_id, tmdb_api_key(), mpaa_region(), get_datetime())
	ep_data = metadata.episodes_meta(season, meta)
	last_played = get_last_played_value(watched_indicators)
	for count, item in enumerate(ep_data, 1):
		season_number = item['season']
		ep_number = item['episode']
		display = '%s - S%.2dE%.2d' % (title, season_number, ep_number)
		episode_date, premiered = adjust_premiered_date(item['premiered'], date_offset())
		if episode_date and current_date < episode_date: continue
		progress_backround.update(int(float(count) / float(len(ep_data)) * 100), '[B]Please Wait..[/B]', display)
		insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
	batch_watched_status_mark(watched_indicators, insert_list, action)
	progress_backround.close()
	refresh_container_for(tmdb_id)

def mark_episode(params):
	season, episode, title = int(params.get('season')), int(params.get('episode')), params.get('title')
	if season == 0: return notification('Failed')
	action, media_type = params.get('action'), 'episode'
	refresh, from_playback = params.get('refresh', 'true') == 'true', params.get('from_playback', 'false') == 'true'
	if from_playback: refresh = False
	tmdb_id = params.get('tmdb_id')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	watched_indicators = watched_indicators_function()
	# Prima il locale e l'interfaccia, poi la rete. Vedi _mark_on_trakt.
	watched_status_mark(watched_indicators, media_type, tmdb_id, action, season, episode, title)
	refresh_container_for(tmdb_id, refresh)
	if watched_indicators == 1:
		_spawn(_mark_on_trakt, ((action, media_type, tmdb_id, tvdb_id), 'tvshow',
					(tmdb_id, season, episode)))

def watched_status_mark(watched_indicators, media_type='', media_id='', action='', season='', episode='', title=''):
	try:
		last_played = get_last_played_value(watched_indicators)
		dbcon = get_database(watched_indicators)
		if action == 'mark_as_watched':
			dbcon.execute('INSERT OR REPLACE INTO watched VALUES (?, ?, ?, ?, ?, ?)', (media_type, media_id, season, episode, last_played, title))
		elif action == 'mark_as_unwatched':
			dbcon.execute('DELETE FROM watched WHERE (db_type = ? and media_id = ? and season = ? and episode = ?)', (media_type, media_id, season, episode))
		erase_bookmark(media_type, media_id, season, episode)
		# if media_type == 'episode': clear_cache_watched_tvshow_status()
	except: notification('Error')

def batch_watched_status_mark(watched_indicators, insert_list, action):
	try:
		dbcon = get_database(watched_indicators)
		if action == 'mark_as_watched':
			dbcon.executemany('INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)', insert_list)
		elif action == 'mark_as_unwatched':
			dbcon.executemany('DELETE FROM watched WHERE (db_type = ? and media_id = ? and season = ? and episode = ?)', insert_list)
		batch_erase_bookmark(watched_indicators, insert_list, action)
		# clear_cache_watched_tvshow_status()
	except: notification('Error')

def get_next_episodes(nextep_content):
	watched_db = get_database()
	if nextep_content == 0:
		data = watched_db.execute('''WITH cte AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY media_id ORDER BY season DESC, episode DESC) rn FROM watched WHERE db_type == ?)
									SELECT media_id, season, episode, title, last_played FROM cte WHERE rn = 1''', ('episode',)).fetchall()
	else:
		data = watched_db.execute('SELECT media_id, season, episode, title, MAX(last_played), COUNT(*) AS COUNTER FROM watched WHERE db_type = ? GROUP BY media_id',
								('episode',)).fetchall()
	data = [{'media_ids': {'tmdb': int(i[0])}, 'season': int(i[1]), 'episode': int(i[2]), 'title': i[3], 'last_played': i[4]} for i in data]
	data.sort(key=lambda x: (x['last_played']), reverse=True)
	return data
	
def get_next(season, episode, watched_info, season_data, nextep_content):
	if episode == 0: episode = 1
	elif nextep_content == 0:
		try:
			episode_count = next((i['episode_count'] for i in season_data if i['season_number'] == season), None)
			if episode < episode_count: episode = episode + 1
			else:
				season, episode = season + 1, 1
				# La stagione successiva puo' semplicemente NON ESISTERE, e finora nessuno lo
				# controllava (lotto 104). Chi ha finito una serie conclusa arrivava qui con l'ultimo
				# episodio dell'ultima stagione e si portava via una coppia inventata: Breaking Bad
				# stagione 6, I Soprano stagione 7, The Office stagione 10. A valle succedeva questo:
				#   episodes_meta chiedeva quella stagione a TMDb, TMDb rispondeva niente, e la
				#   risposta vuota veniva SCRITTA in cache con 4 giorni di scadenza -- quindi una
				#   richiesta di rete inutile per ogni serie finita, ogni quattro giorni -- e infine
				#   _build scartava l'elemento su 'stagione_vuota'.
				# Nel log del 29/08 alle 02:39 erano **16 elementi su 22** del widget 'continua a
				# guardare', cioe' i due terzi del lavoro, tutti per serie che l'utente ha finito.
				# L'esito per l'utente non cambia (l'elemento spariva prima e sparisce adesso): cambia
				# che ora sparisce subito, senza cache e senza rete.
				if not any(i['season_number'] == season for i in season_data): return None, None
		except: pass
	else:
		try:
			next_episode = 0
			relevant_seasons = [i for i in season_data if i['season_number'] >= season]
			for item in relevant_seasons:
				episode_count, item_season = item['episode_count'], item['season_number']
				if season == item_season:
					if episode >= episode_count:
						item_season, next_episode = None, None
						continue
					episode_range = range(episode + 1, episode_count + 1)
				else: episode_range = range(1, episode_count + 1)
				next_episode = next((i for i in episode_range if not get_watched_status_episode(watched_info, (item_season, i))), None)
				if next_episode: break
			if not next_episode: season, episode = None, None
			season, episode = item_season, next_episode
		except: pass
	return season, episode

def get_in_progress_movies(dummy_arg, page_no):
	from modules.utils import sort_for_article
	dbcon = get_database()
	data = dbcon.execute('SELECT media_id, title, last_played FROM progress WHERE db_type = ?', ('movie',)).fetchall()
	data = [{'media_id': i[0], 'title': i[1], 'last_played': i[2]} for i in data if not i[0] == '']
	if lists_sort_order('progress') == 0: data = sort_for_article(data, 'title')
	else: data = sorted(data, key=lambda x: x['last_played'], reverse=True)
	return data

def get_in_progress_tvshows(dummy_arg, page_no):
	# results = cache_watched_tvshow_status(active_tvshows_information, 'progress')
	from modules.utils import sort_for_article
	results = active_tvshows_information('progress')
	hidden_items = get_hidden_progress_items(watched_indicators_function())
	results = [i for i in results if not int(i['media_id']) in hidden_items]
	if lists_sort_order('progress') == 0: results = sort_for_article(results, 'title')
	else: results = sorted(results, key=lambda x: x['last_played'], reverse=True)
	return results

def get_in_progress_episodes():
	from modules.utils import sort_for_article
	dbcon = get_database()
	data = dbcon.execute('SELECT media_id, season, episode, resume_point, last_played, title FROM progress WHERE db_type = ?', ('episode',)).fetchall()
	if lists_sort_order('progress') == 0: data = sort_for_article(data, 5)
	else: data.sort(key=lambda k: k[4], reverse=True)
	episode_list = [{'media_ids': {'tmdb': i[0]}, 'season': int(i[1]), 'episode': int(i[2]), 'resume_point': float(i[3]), 'last_played': i[4]} for i in data]
	return episode_list

def get_watched_items(media_type, page_no):
	from modules.utils import sort_for_article
	if media_type == 'tvshow': results = active_tvshows_information('watched')
	else: results = [v for k,v in watched_info_movie().items()]
	if lists_sort_order('watched') == 0: results = sort_for_article(results, 'title')
	else: results = sorted(results, key=lambda x: x['last_played'], reverse=True)
	return results

def get_recently_watched(media_type, short_list=1):
	watched_indicators = watched_indicators_function()
	if media_type == 'movie':
		data = sorted([v for k,v in watched_info_movie().items()], key=lambda x: x['last_played'], reverse=True)
		if short_list: data = data[:20]
	else:
		dbcon = get_database(watched_indicators)
		if short_list:
			data = dbcon.execute('SELECT media_id, season, episode, title, last_played FROM watched WHERE db_type = ? ORDER BY last_played DESC', ('episode',)).fetchall()
			data = [{'media_ids': {'tmdb': int(i[0])}, 'season': int(i[1]), 'episode': int(i[2]), 'title': i[3], 'last_played': i[4]}
						for i in data][:20]
		else:
			seen = set()
			seen_add = seen.add
			data = dbcon.execute('SELECT media_id, season, episode, title, last_played FROM watched WHERE db_type = ?', ('episode',)).fetchall()
			data = sorted([{'media_ids': {'tmdb': int(i[0])}, 'season': int(i[1]), 'episode': int(i[2]), 'title': i[3], 'last_played': i[4]}
						for i in sorted(data, key=lambda x: (x[4], x[0], x[1], x[2]), reverse=True) if not (i[0] in seen or seen_add(i[0]))],
						key=lambda x: (x['last_played'], x['media_ids']['tmdb'], x['season'], x['episode']), reverse=True)
	return data

def get_hidden_progress_items(watched_indicators):
	# L'import sta DENTRO il ramo che lo usa, non in cima (lotto 52 bis). Con watched_indicators == 0
	# -- il valore predefinito, 'Fen Light', ed e' quello attivo sulla stick -- questa funzione legge
	# dalla cache locale e Trakt non lo tocca mai: avere l'import in cima caricava comunque
	# apis.trakt_api, cioe' 1155 righe, per un ramo che non lo chiama. E' su questo percorso che si
	# costruisce 'continua a guardare' a ogni avvio.
	from caches.main_cache import main_cache
	try:
		if watched_indicators == 0: return main_cache.get(progress_db_string) or []
		from apis.trakt_api import trakt_get_hidden_items
		return trakt_get_hidden_items('progress_watched')
	except: return []
