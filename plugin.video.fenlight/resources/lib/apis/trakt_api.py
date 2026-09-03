# -*- coding: utf-8 -*-
import json
import time
# Vedi la nota in caches/base_cache.py: threading.Lock E' _thread.allocate_lock, e _thread e'
# builtin. Qui serviva solo refresh_lock.
from _thread import allocate_lock as Lock
from caches import trakt_cache
from caches.settings_cache import get_setting, set_setting
from caches.main_cache import cache_object
from caches.lists_cache import lists_cache_object
from modules import kodi_utils, settings
from modules.metadata import movie_meta_external_id, tvshow_meta_external_id
from modules.utils import sort_list, sort_for_article, make_thread_list, get_datetime, timedelta, replace_html_codes, copy2clip, title_key, jsondate_to_datetime as js2date

# 'requests' e la Session si creano alla PRIMA richiesta, non all'import (lotto 51). Erano a livello
# di modulo, quindi chiunque importasse trakt_api pagava l'albero di requests (urllib3, certifi, ssl,
# http.client, email) anche solo per leggere lo stato visto dal database locale. Misura del 24/08:
# build_season_list spendeva 2094 ms di import per 23 ms di lavoro. La Session resta una sola per
# interprete, esattamente come prima -- cambia solo QUANDO nasce.
_session = [None]

def _get_session():
	if _session[0] is None:
		from modules.kodi_utils import import_requests
		_session[0] = import_requests('trakt_api').Session()
	return _session[0]
sleep, with_media_removals, get_property = kodi_utils.sleep, kodi_utils.with_media_removals, kodi_utils.get_property
logger, notification, xbmc_player, confirm_dialog = kodi_utils.logger, kodi_utils.notification, kodi_utils.xbmc_player, kodi_utils.confirm_dialog
kodi_dialog, addon_installed, addon_enabled, addon = kodi_utils.kodi_dialog, kodi_utils.addon_installed, kodi_utils.addon_enabled, kodi_utils.addon
path_check, get_icon, clear_property, remove_keys = kodi_utils.path_check, kodi_utils.get_icon, kodi_utils.clear_property, kodi_utils.remove_keys
execute_builtin, select_dialog, kodi_refresh = kodi_utils.execute_builtin, kodi_utils.select_dialog, kodi_utils.kodi_refresh
kodi_refresh_ids = kodi_utils.kodi_refresh_ids
progress_dialog, external, trakt_user_active, show_unaired_watchlist = kodi_utils.progress_dialog, kodi_utils.external, settings.trakt_user_active, settings.show_unaired_watchlist
lists_sort_order, trakt_client, trakt_secret, tmdb_api_key = settings.lists_sort_order, settings.trakt_client, settings.trakt_secret, settings.tmdb_api_key
clear_all_trakt_cache_data, cache_trakt_object, clear_trakt_calendar = trakt_cache.clear_all_trakt_cache_data, trakt_cache.cache_trakt_object, trakt_cache.clear_trakt_calendar
trakt_watched_cache, reset_activity, clear_trakt_list_contents_data = trakt_cache.trakt_watched_cache, trakt_cache.reset_activity, trakt_cache.clear_trakt_list_contents_data
restore_activity = trakt_cache.restore_activity
# Alzato dalle guardie self_mark quando saltano una ricostruzione: dice a trakt_sync_activities che il
# segnalibro delle attivita' NON puo' avanzare, perche' c'e' del lavoro non fatto. Vedi lotto 58.
_SYNC_DEFERRED = [False]
# Qui vivevano PROGRESS_RETRY_PROP e PROGRESS_RETRY_MAX (lotto 132): la riprova quando
# last_activities diceva 'cambiato' e sync/playback tornava identico. RIMOSSI dal lotto 133.
# Erano l'ennesima deduzione a tempo su uno stato che non era scritto: e infatti sbagliavano da
# soli -- 'azzera avanzamento' e' proprio il caso in cui l'attivita' cambia e la tabella no, perche'
# il lavoro l'abbiamo gia' fatto noi in locale, e la riprova scattava a vuoto su ENTRAMBE le
# macchine (log del 03/09, 03:29:54 e 03:30:25). Adesso una risposta vecchia non fa danni da sola:
# la riconciliazione tocca solo cio' che cambia, e una riga `synced` assente dallo snapshot e' una
# cancellazione qualunque sia stato il motivo dell'attivita'.
clear_daily_cache = trakt_cache.clear_daily_cache
clear_trakt_collection_watchlist_data, clear_trakt_hidden_data = trakt_cache.clear_trakt_collection_watchlist_data, trakt_cache.clear_trakt_hidden_data
# LOTTO 119: qui vivevano anche clear_trakt_recommendations, clear_trakt_list_data e
# clear_trakt_favorites. Erano usate SOLO dai rami della sincronizzazione ora rimossi (vedi la nota
# 'strumenti morti' in trakt_sync_activities): le funzioni restano in caches/trakt_cache per chi le
# chiama da altrove, ma qui non ha piu' senso legarle a ogni import del modulo.
empty_setting_check = (None, 'empty_setting', '')
standby_date = '2050-01-01T01:00:00.000Z'
res_format = '%Y-%m-%dT%H:%M:%S.%fZ'
API_ENDPOINT = 'https://api.trakt.tv/%s'
refresh_lock = Lock()
history_page_limit = 250
timeout = 20
EXPIRY_1_DAY, EXPIRY_1_WEEK = 24, 168

def no_client_key():
	notification('Please set a valid Trakt Client ID Key')
	return None

def no_secret_key():
	notification('Please set a valid Trakt Client Secret Key')
	return None

def call_trakt(path, params=None, data=None, is_delete=False, with_auth=True, method=None, pagination=False, page_no=1):
	def send_query():
		resp = None
		if with_auth:
			try:
				token = get_setting('fenlight.trakt.token')
				if token and token not in empty_setting_check:
					try:
						expires_at = float(get_setting('fenlight.trakt.expires', '0'))
						if expires_at > 0 and time.time() > (expires_at - 86400): trakt_refresh_token()
					except: pass
					token = get_setting('fenlight.trakt.token')
				if token and token not in empty_setting_check: headers['Authorization'] = 'Bearer ' + token
			except: pass
		try:
			if method:
				if method == 'post':
					resp = _get_session().post(API_ENDPOINT % path, headers=headers, timeout=timeout)
				elif method == 'delete':
					resp = _get_session().delete(API_ENDPOINT % path, headers=headers, timeout=timeout)
				elif method == 'sort_by_headers':
					resp = _get_session().get(API_ENDPOINT % path, params=params, headers=headers, timeout=timeout)
			elif data is not None:
				resp = _get_session().post(API_ENDPOINT % path, json=data, headers=headers, timeout=timeout)
			elif is_delete: resp = _get_session().delete(API_ENDPOINT % path, headers=headers, timeout=timeout)
			else: resp = _get_session().get(API_ENDPOINT % path, params=params, headers=headers, timeout=timeout)
			if resp.status_code not in (401, 429): resp.raise_for_status()
		except Exception as e: return logger('Trakt Error', str(e))
		return resp
	if params is None: params = {}
	CLIENT_ID = trakt_client()
	if CLIENT_ID in empty_setting_check: return no_client_key()
	headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': CLIENT_ID}
	if pagination: params['page'] = page_no
	response = send_query()
	try: status_code = response.status_code
	except: return None
	if status_code == 401:
		logger('FenLight Trakt', 'received 401 for path=%s - attempting token refresh' % path)
		refreshed = trakt_refresh_token() if with_auth else False
		if refreshed:
			response = send_query()
			try: status_code = response.status_code
			except: return None
		elif refreshed is None:
			# transient failure (no network, Trakt unreachable): the stored tokens may still be good,
			# so fail quietly instead of asking the user to authorize again.
			return logger('FenLight Trakt', 'token refresh could not be completed for path=%s - not prompting' % path)
		if status_code == 401:
			if not xbmc_player().isPlaying():
				if with_auth and confirm_dialog(heading='Authorize Trakt', text='You must authenticate with Trakt. Do you want to authenticate now?') and trakt_authenticate():
					response = send_query()
				else: pass
			else: return None
	elif status_code == 429:
		retry_headers = response.headers
		if 'Retry-After' in retry_headers:
			sleep(1000 * int(retry_headers.get('Retry-After', 5)))
			response = send_query()
	try:
		response.encoding = 'utf-8'
		result = response.json()
	except: return None
	resp_headers = response.headers
	if method == 'sort_by_headers' and 'X-Sort-By' in resp_headers and 'X-Sort-How' in resp_headers:
		try: result = sort_list(resp_headers['X-Sort-By'], resp_headers['X-Sort-How'], result)
		except: pass
	if pagination: return (result, resp_headers['X-Pagination-Page-Count'])
	else: return result

def trakt_get_device_code():
	CLIENT_ID = trakt_client()
	if CLIENT_ID in empty_setting_check: return no_client_key()
	data = {'client_id': CLIENT_ID}
	result = call_trakt('oauth/device/code', data=data, with_auth=False)
	if not result or 'device_code' not in result:
		error = (result or {}).get('error_description') or (result or {}).get('error') or 'no response from Trakt'
		logger('FenLight Trakt', 'device code request FAILED: %s' % error)
		notification('Trakt: %s' % error, 4000)
		return None
	return result

def trakt_get_device_token(device_codes):
	CLIENT_ID = trakt_client()
	if CLIENT_ID in empty_setting_check: return no_client_key()
	CLIENT_SECRET = trakt_secret()
	if CLIENT_SECRET in empty_setting_check: return no_secret_key()
	result = None
	try:
		headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': CLIENT_ID}
		data = {'code': device_codes['device_code'], 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
		start = time.time()
		expires_in = device_codes['expires_in']
		sleep_interval = device_codes['interval']
		user_code = str(device_codes['user_code'])
		try: copy2clip(user_code)
		except: pass
		content = '[CR]Navigate to: [B]%s[/B][CR]Enter the following code: [B]%s[/B]' % (str(device_codes['verification_url']), user_code)
		progressDialog = progress_dialog('Trakt Authorize', get_icon('trakt_qrcode'))
		progressDialog.update(content, 0)
		try:
			time_passed = 0
			while not progressDialog.iscanceled() and time_passed < expires_in:
				sleep(max(sleep_interval, 1)*1000)
				response = _get_session().post(API_ENDPOINT % 'oauth/device/token', data=json.dumps(data), headers=headers, timeout=timeout)
				status_code = response.status_code
				if status_code == 200:
					result = response.json()
					break
				elif status_code == 400:
					time_passed = time.time() - start
					progress = int(100 * time_passed/expires_in)
					progressDialog.update(content, progress)
				else:
					logger('FenLight Trakt', 'device token poll returned %s: %s' % (status_code, response.text[:200]))
					break
		except Exception as e: logger('FenLight Trakt', 'device token poll error: %s' % e)
		try: progressDialog.close()
		except: pass
	except Exception as e: logger('FenLight Trakt', 'device token request FAILED: %s' % e)
	return result

def trakt_refresh_token():
	CLIENT_ID = trakt_client()
	if CLIENT_ID in empty_setting_check: return False
	CLIENT_SECRET = trakt_secret()
	if CLIENT_SECRET in empty_setting_check: return False
	refresh_token = get_setting('fenlight.trakt.refresh')
	if not refresh_token or refresh_token in empty_setting_check or refresh_token == '0': return False
	with refresh_lock:
		# Trakt rotates the refresh token on use, so a concurrent call may already have replaced it.
		if get_setting('fenlight.trakt.refresh') != refresh_token: return True
		return _trakt_refresh_token(CLIENT_ID, CLIENT_SECRET, refresh_token)

def _trakt_refresh_token(CLIENT_ID, CLIENT_SECRET, refresh_token):
	data = {
		'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
		'grant_type': 'refresh_token', 'refresh_token': refresh_token}
	response = call_trakt("oauth/token", data=data, with_auth=False)
	if response and 'access_token' in response:
		# the refresh token is single use, so store the replacement first: a crash after this point
		# still leaves a usable token pair behind.
		set_setting('trakt.refresh', response["refresh_token"])
		set_setting('trakt.token', response["access_token"])
		expires_in = int(response.get('expires_in', 604800))
		set_setting('trakt.expires', str(time.time() + expires_in))
		logger('FenLight Trakt', 'token refresh SUCCESS - new token valid for %s seconds' % expires_in)
		return True
	error = response.get('error') if isinstance(response, dict) else None
	if error in ('invalid_grant', 'invalid_client'):
		logger('FenLight Trakt', 'token refresh REJECTED (%s) - the account must be authorized again' % error)
		return False
	logger('FenLight Trakt', 'token refresh could not be completed - Trakt unreachable or unexpected response: %s' % str(response)[:120])
	return None

def trakt_authenticate(dummy=''):
	code = trakt_get_device_code()
	if not code: return False
	token = trakt_get_device_token(code)
	if token:
		set_setting('trakt.token', token["access_token"])
		set_setting('trakt.refresh', token["refresh_token"])
		set_setting('trakt.expires', str(time.time() + int(token.get('expires_in', 604800))))
		set_setting('watched_indicators', '1')
		sleep(1000)
		try:
			user = call_trakt('/users/me')
			set_setting('trakt.user', str(user['username']))
		except: pass
		notification('Trakt Account Authorized', 3000)
		trakt_sync_activities(force_update=True)
		return True
	notification('Trakt Error Authorizing', 3000)
	return False

def trakt_revoke_authentication(dummy=''):
	set_setting('trakt.user', 'empty_setting')
	set_setting('trakt.expires', '')
	set_setting('trakt.token', '')
	set_setting('trakt.refresh', '')
	set_setting('watched_indicators', '0')
	clear_all_trakt_cache_data(silent=True, refresh=False)
	notification('Trakt Account Authorization Reset', 3000)
	CLIENT_ID = trakt_client()
	if CLIENT_ID in empty_setting_check: return no_client_key()
	CLIENT_SECRET = trakt_secret()
	if CLIENT_SECRET in empty_setting_check: return no_secret_key()
	data = {'token': get_setting('fenlight.trakt.token'), 'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET}
	response = call_trakt("oauth/revoke", data=data, with_auth=False)

def trakt_movies_trending(page_no):
	string = 'trakt_movies_trending_%s' % page_no
	params = {'path': 'movies/trending/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_movies_trending_recent(page_no):
	current_year = get_datetime().year
	years = '%s-%s' % (str(current_year-1), str(current_year))
	string = 'trakt_movies_trending_recent_%s' % page_no
	params = {'path': 'movies/trending/%s', 'params': {'limit': 20, 'years': years}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_movies_top10_boxoffice(page_no):
	string = 'trakt_movies_top10_boxoffice'
	params = {'path': 'movies/boxoffice/%s', 'pagination': False}
	return lists_cache_object(get_trakt, string, params)

def trakt_movies_most_watched(page_no):
	string = 'trakt_movies_most_watched_%s' % page_no
	params = {'path': 'movies/watched/daily/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_movies_most_favorited(page_no):
	string = 'trakt_movies_most_favorited%s' % page_no
	params = {'path': 'movies/favorited/daily/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_recommendations(media_type):
	string = 'trakt_recommendations_%s' % (media_type)
	params = {'path': '/recommendations/%s', 'path_insert': media_type, 'with_auth': True,
			'params': {'limit': 50, 'ignore_collected': 'true', 'ignore_watchlisted': 'true'}, 'pagination': False}
	return cache_trakt_object(get_trakt, string, params)

def trakt_tv_trending(page_no):
	string = 'trakt_tv_trending_%s' % page_no
	params = {'path': 'shows/trending/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_tv_trending_recent(page_no):
	current_year = get_datetime().year
	years = '%s-%s' % (str(current_year-1), str(current_year))
	string = 'trakt_tv_trending_recent_%s' % page_no
	params = {'path': 'shows/trending/%s', 'params': {'limit': 20, 'years': years}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_tv_most_watched(page_no):
	string = 'trakt_tv_most_watched_%s' % page_no
	params = {'path': 'shows/watched/daily/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_tv_most_favorited(page_no):
	string = 'trakt_tv_most_favorited_%s' % page_no
	params = {'path': 'shows/favorited/daily/%s', 'params': {'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_tv_certifications(certification, page_no):
	string = 'trakt_tv_certifications_%s_%s' % (certification, page_no)
	params = {'path': 'shows/collected/all%s', 'params': {'certifications': certification, 'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params, expiration= EXPIRY_1_WEEK)

def trakt_anime_trending(page_no):
	string = 'trakt_anime_trending_%s' % page_no
	params = {'path': 'shows/trending/%s', 'params': {'genres': 'anime', 'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_anime_trending_recent(page_no):
	current_year = get_datetime().year
	years = '%s-%s' % (str(current_year-1), str(current_year))
	string = 'trakt_anime_trending_recent_%s' % page_no
	params = {'path': 'shows/trending/%s', 'params': {'genres': 'anime', 'limit': 20, 'years': years}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_anime_most_watched(page_no):
	string = 'trakt_anime_most_watched_%s' % page_no
	params = {'path': 'shows/watched/daily/%s', 'params': {'genres': 'anime', 'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_anime_most_favorited(page_no):
	string = 'trakt_anime_most_favorited_%s' % page_no
	params = {'path': 'shows/favorited/daily/%s', 'params': {'genres': 'anime', 'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params)

def trakt_anime_certifications(certification, page_no):
	string = 'trakt_anime_certifications_%s_%s' % (certification, page_no)
	params = {'path': 'shows/collected/all%s', 'params': {'certifications': certification, 'genres': 'anime', 'limit': 20}, 'page_no': page_no}
	return lists_cache_object(get_trakt, string, params, expiration= EXPIRY_1_WEEK)

def trakt_get_hidden_items(list_type):
	def _get_trakt_ids(item):
		tmdb_id = get_trakt_tvshow_id(item['show']['ids'])
		results_append(tmdb_id)
	def _process(params):
		hidden_data = get_trakt(params)
		threads = list(make_thread_list(_get_trakt_ids, hidden_data))
		[i.join() for i in threads]
		return results
	results = []
	results_append = results.append
	string = 'trakt_hidden_items_%s' % list_type
	params = {'path': 'users/hidden/%s', 'path_insert': list_type, 'params': {'limit': 1500, 'type': 'show'}, 'with_auth': True, 'pagination': False}
	return cache_trakt_object(_process, string, params)

def trakt_watched_status_mark(action, media, media_id, tvdb_id=0, season=None, episode=None, key='tmdb'):
	if action == 'mark_as_watched': url, result_key = 'sync/history', 'added'
	else: url, result_key = 'sync/history/remove', 'deleted'
	if media == 'movies':
		success_key = 'movies'
		data = {'movies': [{'ids': {key: media_id}}]}
	else:
		success_key = 'episodes'
		if media == 'episode': data = {'shows': [{'seasons': [{'episodes': [{'number': int(episode)}], 'number': int(season)}], 'ids': {key: media_id}}]}
		elif media =='shows': data = {'shows': [{'ids': {key: media_id}}]}
		else: data = {'shows': [{'ids': {key: media_id}, 'seasons': [{'number': int(season)}]}]}#season
	result = call_trakt(url, data=data)
	if not result: return logger('FenLight Trakt', 'watched status update FAILED for %s %s' % (media, media_id))
	success = result.get(result_key, {}).get(success_key, 0) > 0
	if not success:
		if media != 'movies' and tvdb_id != 0 and key != 'tvdb': return trakt_watched_status_mark(action, media, tvdb_id, 0, season, episode, 'tvdb')
	return success

def trakt_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh_trakt=False):
	if action == 'clear_progress':
		url = 'sync/playback/%s' % resume_id
		result = call_trakt(url, is_delete=True)
	else:
		url = 'scrobble/pause'
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}}, 'episode': {'season': int(season), 'number': int(episode)}, 'progress': float(percent)}
		try: resume_id = (call_trakt(url, data=data) or {}).get('id', 0)
		except: resume_id = 0
	if refresh_trakt: trakt_sync_activities()
	return resume_id

def trakt_scrobble_start(media, media_id, season=None, episode=None, progress=0.0):
	try:
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(progress)}
		else: data = {'show': {'ids': {'tmdb': media_id}}, 'episode': {'season': int(season), 'number': int(episode)}, 'progress': float(progress)}
		call_trakt('scrobble/start', data=data)
	except: pass

def trakt_scrobble_stop(media, media_id, percent, season=None, episode=None):
	try:
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}}, 'episode': {'season': int(season), 'number': int(episode)}, 'progress': float(percent)}
		call_trakt('scrobble/stop', data=data)
	except: pass

def trakt_collection_lists(media_type, list_type=None):
	data = trakt_fetch_collection_watchlist('collection', media_type)
	if list_type == 'recent':
		data.sort(key=lambda k: k['collected_at'], reverse=True)
		data = data[:20]
	return data

def trakt_watchlist_lists(media_type, list_type=None):
	data = trakt_fetch_collection_watchlist('watchlist', media_type)
	if list_type == 'recent':
		data.sort(key=lambda k: k['collected_at'], reverse=True)
		data = data[:20]
	return data

def trakt_collection(media_type, dummy_arg):
	data = trakt_fetch_collection_watchlist('collection', media_type)
	sort_order = lists_sort_order('collection')
	if sort_order == 0: data = sort_for_article(data, 'title')
	elif sort_order == 1: data.sort(key=lambda k: k['collected_at'], reverse=True)
	else: data.sort(key=lambda k: k['released'], reverse=True)
	return data

def trakt_watchlist(media_type, dummy_arg):
	data = trakt_fetch_collection_watchlist('watchlist', media_type)
	if not show_unaired_watchlist():
		current_date = get_datetime()
		str_format = '%Y-%m-%d' if media_type in ('movie', 'movies') else res_format
		data = [i for i in data if i.get('released', None) and js2date(i.get('released'), str_format, remove_time=True) <= current_date]
	sort_order = lists_sort_order('watchlist')
	if sort_order == 0: data = sort_for_article(data, 'title')
	elif sort_order == 1: data.sort(key=lambda k: k['collected_at'], reverse=True)
	else: data.sort(key=lambda k: k.get('released'), reverse=True)
	return data

def trakt_fetch_collection_watchlist(list_type, media_type):
	def _process(params):
		data = get_trakt(params)
		if list_type == 'watchlist': data = [i for i in data if i['type'] == key]
		return [{'media_ids': {'tmdb': i[key]['ids'].get('tmdb', ''), 'imdb': i[key]['ids'].get('imdb', ''), 'tvdb': i[key]['ids'].get('tvdb', '')}, 'title': i[key]['title'],
				'collected_at': i.get(collected_at), 'released': i[key].get(r_key) if i[key].get(r_key) else ('2050-01-01' if media_type in ('movie', 'movies') else standby_date)}
				for i in data]
	key, r_key, string_insert = ('movie', 'released', 'movie') if media_type in ('movie', 'movies') else ('show', 'first_aired', 'tvshow')
	collected_at = 'listed_at' if list_type == 'watchlist' else 'collected_at' if media_type in ('movie', 'movies') else 'last_collected_at'
	string = 'trakt_%s_%s' % (list_type, string_insert)
	path = 'sync/%s/%s?extended=full'
	params = {'path': path, 'path_insert': (list_type, media_type), 'with_auth': True, 'pagination': False}
	return cache_trakt_object(_process, string, params)

def _tmdb_ids_from_data(data):
	# I dati spediti a Trakt hanno forma {'movies'|'shows': [{'ids': {'tmdb'|'imdb'|'tvdb': id}}]}.
	# Al refresh mirato servono i soli tmdb_id, perche' sono quelli che paginator pubblica per ogni
	# contenitore. Se l'elemento era identificato per imdb o tvdb la lista esce vuota e il chiamante
	# resta sul refresh globale: nessun caso peggiora rispetto a prima.
	ids = []
	try:
		for items in data.values():
			for item in items:
				tmdb_id = item.get('ids', {}).get('tmdb')
				if tmdb_id: ids.append(str(tmdb_id))
	except: pass
	return ids

def _refresh_for_data(data):
	# Togliere un titolo da una lista cambia i widget che quel titolo lo contengono, non tutti gli
	# altri. Dentro una finestra di directory (my_lists, watchlist, collection) il sondaggio dei
	# contenitori 500-520 non trova nulla e kodi_refresh_ids ricade da sola sul globale, che li' e'
	# proprio quello che serve per rileggere la cartella aperta.
	ids = _tmdb_ids_from_data(data)
	if ids: kodi_refresh_ids(ids, coalesce=False)
	else: kodi_refresh(coalesce=False)

def _refresh_watchlist(data):
	# Due insiemi diversi di contenitori, e servono entrambi:
	#  - per ID: i widget che gia' mostrano il titolo, la cui voce di menu deve passare da "Aggiungi"
	#    a "Rimuovi" (o viceversa);
	#  - per AZIONE: il widget della watchlist, che cambia composizione. In AGGIUNTA il suo elenco di
	#    id non contiene ancora il titolo, quindi la regola per id lo scarterebbe proprio mentre va
	#    ricostruito -- ed e' esattamente il motivo per cui "aggiungi" non era istantaneo.
	# coalesce=False: e' sempre un comando dell'utente. Vedi kodi_refresh in kodi_utils.
	# L'azione e' QUALIFICATA per tipo di media (lotto 119): la watchlist sono due widget e i dati
	# spediti a Trakt dicono gia' quale dei due e' stato toccato -- 'movies' e/o 'shows'. Aggiungere un
	# film non ha motivo di ricostruire la watchlist delle serie.
	actions = set()
	try:
		if data.get('movies'): actions.add(kodi_utils.qualify_action(kodi_utils.WATCHLIST_ACTION, 'movie'))
		if data.get('shows'): actions.add(kodi_utils.qualify_action(kodi_utils.WATCHLIST_ACTION, 'tvshow'))
	except: pass
	# Se i dati non dicono di che tipo sono, si torna al nome nudo: non qualificato vuol dire
	# 'entrambi i widget', cioe' il comportamento di prima. Vedi paginator._action_matches.
	if not actions: actions.add(kodi_utils.WATCHLIST_ACTION)
	kodi_refresh_ids(_tmdb_ids_from_data(data), tuple(sorted(actions)), coalesce=False)

def add_to_list(user, slug, data):
	result = call_trakt('/users/%s/lists/%s/items' % (user, slug), data=data)
	if result['existing']['movies'] + result['existing']['shows'] > 0: return notification('Already In List', 3000)
	if result['added']['movies'] + result['added']['shows'] == 0: return notification('Error', 3000)
	notification('Success', 3000)
	trakt_sync_activities()
	return result

def remove_from_list(user, slug, data):
	result = call_trakt('/users/%s/lists/%s/items/remove' % (user, slug), data=data)
	if result['deleted']['movies'] + result['deleted']['shows'] == 0: return notification('Error', 3000)
	notification('Success', 3000)
	trakt_sync_activities()
	if path_check('my_lists') or external(): _refresh_for_data(data)
	return result

def add_to_watchlist(data, refresh=True):
	result = call_trakt('/sync/watchlist', data=data)
	if result['existing']['movies'] + result['existing']['shows'] > 0: return notification('Already In List', 3000)
	if result['added']['movies'] + result['added']['shows'] == 0: return notification('Error', 3000)
	notification('Success', 3000)
	trakt_sync_activities()
	# Simmetrico a remove_from_watchlist: prima qui non c'era alcun refresh, quindi togliere un titolo
	# aggiornava subito il widget e aggiungerlo no. refresh=False quando chiama watchlist_toggle, che
	# deve invalidare la cache PRIMA di ricostruire.
	if refresh and (path_check('trakt_watchlist') or external()): _refresh_watchlist(data)
	return result

def remove_from_watchlist(data, refresh=True):
	result = call_trakt('/sync/watchlist/remove', data=data)
	if result['deleted']['movies'] + result['deleted']['shows'] == 0: return notification('Error', 3000)
	notification('Success', 3000)
	trakt_sync_activities()
	if refresh and (path_check('trakt_watchlist') or external()): _refresh_watchlist(data)
	return result

def watchlist_tmdb_ids(media_type='movies'):
	# Insieme dei tmdb_id gia' in watchlist, letto una volta sola per costruzione di lista (come
	# watched_info e bookmarks). Passa da cache_trakt_object, quindi e' una lettura da SQLite:
	# nessuna chiamata di rete per elemento.
	try: return {str(i['media_ids']['tmdb']) for i in trakt_fetch_collection_watchlist('watchlist', media_type) if i['media_ids'].get('tmdb')}
	except: return set()

def watchlist_toggle(params):
	# Voce unica del menu contestuale: aggiunge o toglie dalla watchlist a seconda di dov'e' gia'.
	# Sostituisce il gestore liste completo, che chiedeva quale lista prima di fare qualsiasi cosa.
	if not trakt_user_active(): return notification('No Active Trakt Account', 3500)
	media_type = params.get('media_type', 'movie')
	key = 'movies' if media_type == 'movie' else 'shows'
	try: media_id = int(params['tmdb_id'])
	except: return notification('Error', 3000)
	data = {key: [{'ids': {'tmdb': media_id}}]}
	# refresh=False: la ricostruzione la ordina questa funzione, DOPO l'invalidazione della cache.
	# Nell'ordine opposto il widget si ridisegnerebbe leggendo ancora la watchlist vecchia. Finora la
	# rimozione funzionava perche' trakt_sync_activities ripuliva la cache in tempo: una corsa vinta,
	# non una garanzia.
	if params.get('in_watchlist') == 'true': remove_from_watchlist(data, refresh=False)
	else: add_to_watchlist(data, refresh=False)
	clear_trakt_collection_watchlist_data('watchlist', key)
	# Non piu' un kodi_refresh globale (ricostruirebbe TUTTI i widget per una sola etichetta), ma
	# nemmeno l'attesa della prossima ricostruzione naturale: mirato, e quindi immediato.
	_refresh_watchlist(data)

def add_to_collection(data, multi=False):
	result = call_trakt('/sync/collection', data=data)
	if not multi:
		if result['existing']['movies'] + result['existing']['episodes'] > 0: return notification('Already In List', 3000)
		if result['added']['movies'] + result['added']['episodes'] == 0: return notification('Error', 3000)
		notification('Success', 3000)
		trakt_sync_activities()
	return result

def remove_from_collection(data):
	result = call_trakt('/sync/collection/remove', data=data)
	if result['deleted']['movies'] + result['deleted']['episodes'] == 0: return notification('Error', 3000)
	notification('Success', 3000)
	trakt_sync_activities()
	if path_check('trakt_collection') or external(): _refresh_for_data(data)
	return result

def hide_unhide_progress_items(params):
	action, media_type, media_id, list_type = params['action'], params['media_type'], params['media_id'], params['section']
	media_type = 'movies' if media_type in ('movie', 'movies') else 'shows'
	url = 'users/hidden/%s' % list_type if action == 'hide' else 'users/hidden/%s/remove' % list_type
	data = {media_type: [{'ids': {'tmdb': media_id}}]}
	call_trakt(url, data=data)
	trakt_sync_activities()
	# Nascondere o riesporre un titolo nel 'continua a guardare' tocca il widget che lo contiene:
	# l'id ce l'abbiamo gia' nei parametri, non c'e' motivo di ricostruire l'intera home.
	# Con l'azione (lotto 114) il widget si ricostruisce anche quando il titolo RIENTRA, cioe' quando
	# il suo id non e' ancora nell'elenco pubblicato.
	kodi_refresh_ids([media_id], (kodi_utils.CONTINUE_WATCHING_ACTION,), coalesce=False)

def trakt_search_lists(search_title, page_no):
	def _process(dummy_arg):
		return call_trakt('search', params={'type': 'list', 'fields': 'name,description', 'query': search_title, 'limit': 50}, pagination=True, page_no=page_no)
	string = 'trakt_search_lists_%s_%s' % (search_title, page_no)
	return cache_object(_process, string, 'dummy_arg', False, 4)

def trakt_favorites(media_type, dummy_arg):
	def _process(params):
		return [{'media_ids': {'tmdb': i[i['type']]['ids'].get('tmdb', ''), 'imdb': i[i['type']]['ids'].get('imdb', ''), 'tvdb': i[i['type']]['ids'].get('tvdb', '')}} \
					for i in get_trakt(params)]
	media_type = 'movies' if media_type in ('movie', 'movies') else 'shows'
	string = 'trakt_favorites_%s' % media_type
	params = {'path': 'users/me/favorites/%s/%s', 'path_insert': (media_type, 'title'), 'with_auth': True, 'pagination': False}
	return cache_trakt_object(_process, string, params)

def trakt_lists_with_media(media_type, imdb_id):
	def _process(foo):
		data = [i for i in get_trakt(params) if i['item_count'] > 0 and i['ids']['slug'] not in ('', 'None', None) and i['privacy'] == 'public']
		return [remove_keys(i, with_media_removals) for i in data]
	results = []
	results_append = results.append
	template = '[B]%02d. [I]%s - %s likes[/I]'
	media_type = 'movies' if media_type in ('movie', 'movies') else 'shows'
	string = 'trakt_lists_with_media_%s' % imdb_id
	params = {'path': '%s/%s/lists/personal', 'path_insert': (media_type, imdb_id), 'params': {'limit': 100}, 'pagination': False}
	return cache_object(_process, string, 'foo', False, 168)

def get_trakt_list_contents(list_type, user, slug, with_auth):
	def _process(params):
		results = []
		results_append = results.append
		for c, i in enumerate(get_trakt(params)):
			try:
				_type = i['type']
				if _type in ('movie', 'show'): data = {'media_ids': i[_type]['ids'], 'title': i[_type]['title'], 'type': _type, 'order': c}
				elif _type == 'season':
					data = {'tmdb_id': i['show']['ids']['tmdb'], 'season': i[_type]['number'], 'type': _type, 'custom_order': c}
				elif _type == 'episode':
					data = {'media_ids': i['show']['ids'], 'title': i['show']['title'], 'type': _type, 'season': i[_type]['season'], 'episode': i[_type]['number'], 'custom_order': c}
				results_append(data)
			except: pass
		return results
	string = 'trakt_list_contents_%s_%s_%s' % (list_type, user, slug)
	if user == 'Trakt Official': params = {'path': 'lists/%s/items', 'path_insert': slug, 'params': {'extended':'full'}, 'method': 'sort_by_headers'}
	else: params = {'path': 'users/%s/lists/%s/items', 'path_insert': (user, slug), 'params': {'extended':'full'}, 'with_auth': with_auth, 'method': 'sort_by_headers'}
	return cache_trakt_object(_process, string, params)

def trakt_trending_popular_lists(list_type, page_no):
	string = 'trakt_%s_user_lists_%s' % (list_type, page_no)
	params = {'path': 'lists/%s', 'path_insert': list_type, 'params': {'limit': 50}, 'page_no': page_no}
	return cache_object(get_trakt, string, params, False)

def trakt_get_lists(list_type):
	if list_type == 'my_lists':
		string = 'trakt_my_lists'
		path = 'users/me/lists%s'
	elif list_type == 'liked_lists':
		string = 'trakt_liked_lists'
		path = 'users/likes/lists%s'
	params = {'path': path, 'params': {'limit': 1000}, 'pagination': False, 'with_auth': True}
	return cache_trakt_object(get_trakt, string, params)

def get_trakt_list_selection(list_choice=None):
	my_lists = [{'name': item['name'], 'display': '[B]PERSONAL:[/B] [I]%s[/I]' % item['name'].upper(), 'user': item['user']['ids']['slug'], 'slug': item['ids']['slug']} \
																											for item in trakt_get_lists('my_lists')]
	my_lists.sort(key=lambda k: k['name'])
	if list_choice == 'nav_edit':
		liked_lists = [{'name': item['list']['name'], 'display': '[B]LIKED:[/B] [I]%s[/I]' % item['list']['name'].upper(), 'user': item['list']['user']['ids']['slug'],
								'slug': item['list']['ids']['slug']} for item in trakt_get_lists('liked_lists')]
		liked_lists.sort(key=lambda k: (k['display']))
		my_lists.extend(liked_lists)
	else:
		my_lists.insert(0, {'name': 'Collection', 'display': '[B][I]COLLECTION [/I][/B]', 'user': 'Collection', 'slug': 'Collection'})
		my_lists.insert(0, {'name': 'Watchlist', 'display': '[B][I]WATCHLIST [/I][/B]',  'user': 'Watchlist', 'slug': 'Watchlist'})
	list_items = [{'line1': item['display']} for item in my_lists]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Select', 'narrow_window': 'true'}
	selection = select_dialog(my_lists, **kwargs)
	if selection == None: return None
	return selection

def make_new_trakt_list(params):
	list_title = kodi_dialog().input('')
	if not list_title: return
	list_name = kodi_utils.unquote(list_title)
	data = {'name': list_name, 'privacy': 'private', 'allow_comments': False}
	call_trakt('users/me/lists', data=data)
	trakt_sync_activities()
	notification('Success', 3000)
	# Comando esplicito dell'utente: mai accorpato. Vedi kodi_refresh in kodi_utils.
	kodi_refresh(coalesce=False)

def delete_trakt_list(params):
	user = params['user']
	list_slug = params['list_slug']
	if not confirm_dialog(): return
	url = 'users/%s/lists/%s' % (user, list_slug)
	call_trakt(url, is_delete=True)
	trakt_sync_activities()
	notification('Success', 3000)
	# Comando esplicito dell'utente: mai accorpato. Vedi kodi_refresh in kodi_utils.
	kodi_refresh(coalesce=False)

def trakt_add_to_list(params):
	tmdb_id, tvdb_id, imdb_id, media_type = params['tmdb_id'], params['tvdb_id'], params['imdb_id'], params['media_type']
	if media_type == 'movie':
		key, media_key, media_id = ('movies', 'tmdb', int(tmdb_id))
	else:
		key = 'shows'
		media_ids = [(tmdb_id, 'tmdb'), (imdb_id, 'imdb'), (tvdb_id, 'tvdb')]
		media_id, media_key = next(item for item in media_ids if item[0] not in ('None', None, ''))
		if media_id in (tmdb_id, tvdb_id): media_id = int(media_id)
	selected = get_trakt_list_selection()
	if selected is not None:
		data = {key: [{'ids': {media_key: media_id}}]}
		if selected['user'] == 'Watchlist': add_to_watchlist(data)
		elif selected['user'] == 'Collection': add_to_collection(data)
		else:
			user = selected['user']
			slug = selected['slug']
			add_to_list(user, slug, data)

def trakt_remove_from_list(params):
	tmdb_id, tvdb_id, imdb_id, media_type = params['tmdb_id'], params['tvdb_id'], params['imdb_id'], params['media_type']
	if media_type == 'movie':
		key, media_key, media_id = ('movies', 'tmdb', int(tmdb_id))
	else:
		key = 'shows'
		media_ids = [(tmdb_id, 'tmdb'), (imdb_id, 'imdb'), (tvdb_id, 'tvdb')]
		media_id, media_key = next(item for item in media_ids if item[0] not in ('None', None, ''))
		if media_id in (tmdb_id, tvdb_id): media_id = int(media_id)
	selected = get_trakt_list_selection()
	if selected is not None:
		data = {key: [{'ids': {media_key: media_id}}]}
		if selected['user'] == 'Watchlist': remove_from_watchlist(data)
		elif selected['user'] == 'Collection': remove_from_collection(data)
		else:
			user = selected['user']
			slug = selected['slug']
			remove_from_list(user, slug, data)

def trakt_like_a_list(params):
	user = params['user']
	list_slug = params['list_slug']
	refresh = params.get('refresh', 'true') == 'true'
	try:
		call_trakt('/users/%s/lists/%s/like' % (user, list_slug), method='post')
		notification('Success - Trakt List Liked', 3000)
		trakt_sync_activities()
		if refresh: kodi_refresh(coalesce=False)
		return True
	except:
		notification('Error', 3000)
		return False

def trakt_unlike_a_list(params):
	user = params['user']
	list_slug = params['list_slug']
	refresh = params.get('refresh', 'true') == 'true'
	try:
		call_trakt('/users/%s/lists/%s/like' % (user, list_slug), method='delete')
		notification('Success - Trakt List Unliked', 3000)
		trakt_sync_activities()
		if refresh: kodi_refresh(coalesce=False)
		return True
	except:
		notification('Error', 3000)
		return False

def get_trakt_movie_id(item):
	if item['tmdb']: return item['tmdb']
	tmdb_id = None
	api_key = tmdb_api_key()
	if item['imdb']:
		try:
			meta = movie_meta_external_id('imdb_id', item['imdb'], api_key)
			tmdb_id = meta['id']
		except: pass
	return tmdb_id

def get_trakt_tvshow_id(item):
	if item['tmdb']: return item['tmdb']
	tmdb_id = None
	api_key = tmdb_api_key()
	if item['imdb']:
		try: 
			meta = tvshow_meta_external_id('imdb_id', item['imdb'], api_key)
			tmdb_id = meta['id']
		except: tmdb_id = None
	if not tmdb_id:
		if item['tvdb']:
			try: 
				meta = tvshow_meta_external_id('tvdb_id', item['tvdb'], api_key)
				tmdb_id = meta['id']
			except: tmdb_id = None
	return tmdb_id

_SYNC_PAGE_LIMIT = 100   # massimo per pagina consentito da Trakt su questi endpoint
_SYNC_PAGE_CAP = 200     # freno di sicurezza: 20.000 elementi, ben oltre qualsiasi libreria reale

def _get_all_sync_pages(path, with_auth=True):
	# Trakt ha iniziato a paginare gli endpoint sync/watched/*. Chiamandoli con pagination=False si
	# ottiene SOLO la prima pagina, cioe' i 100 titoli piu' recenti: tutto il resto della cronologia
	# spariva dalla cache e i film visti piu' indietro nel tempo perdevano il badge "visto", senza alcuna
	# discriminante visibile. E' la stessa classe di cambiamento che aveva gia' colpito la ripartizione
	# stagioni/episodi di sync/watched/shows.
	#
	# Se l'endpoint NON e' paginato, la prima pagina contiene gia' tutto e page_count vale 1: il ciclo
	# fa una sola richiesta e il comportamento resta identico a prima. La modifica e' quindi sicura in
	# entrambi gli scenari. Se gli header di paginazione mancano del tutto si ripiega sulla chiamata
	# secca storica.
	items, page_no, page_count = [], 1, 1
	while page_no <= page_count and page_no <= _SYNC_PAGE_CAP:
		try: response = call_trakt(path, params={'limit': _SYNC_PAGE_LIMIT}, with_auth=with_auth, pagination=True, page_no=page_no)
		except Exception: response = None
		if not response:
			# Prima pagina fallita: si ripiega sulla chiamata secca storica. Se fallisce anche quella
			# non e' un account senza nulla, e' un GUASTO, e va detto a chi chiama: None, non [].
			# Con `or []` i due casi finivano sullo stesso valore e la guardia del chiamante trattava
			# un account legittimamente vuoto come una risposta sospetta, senza far mai avanzare il
			# segnalibro. Misurato il 30/08 sul profilo Maurizio: dopo la riautorizzazione di Trakt
			# (16:12:24, account senza niente di visto) ogni giro rileggeva 0 elementi, non avanzava,
			# e ordinava un UpdateLibrary globale -- 12 ricostruzioni complete della home in 7 minuti,
			# finite solo quando il primo film visto ha dato al segnalibro qualcosa su cui appoggiarsi.
			if page_no == 1:
				fallback = call_trakt(path, with_auth=with_auth, pagination=False)
				if fallback is None:
					logger('FenLight Trakt', '%s: richiesta FALLITA' % path)
					return None
				return fallback
			break
		page_items, pages = response
		if page_items: items.extend(page_items)
		try: page_count = int(pages)
		except: page_count = page_no
		page_no += 1
	logger('FenLight Trakt', '%s: %s elementi su %s pagine' % (path, len(items), min(page_count, _SYNC_PAGE_CAP)))
	return items

# Quanto resta valido il timbro di "questa modifica e' nostra". Stretto apposta: se scade si
# ricostruisce come prima, quindi il caso peggiore e' il comportamento vecchio, mai un dato perso.
# Finestra entro cui una marcatura fatta da noi puo' RIMANDARE una ricostruzione (non piu' annullarla:
# vedi restore_activity e lotto 58). Poiche' ora il lavoro rimandato viene comunque svolto alla
# scadenza, questa costante non decide piu' "cosa si perde" ma solo "quanto si aspetta": era 120 s,
# cioe' fino a 2 minuti di ritardo per una modifica fatta dall'app Trakt. A 45 s si conserva
# l'accorpamento di piu' marcature consecutive -- il motivo per cui la guardia esiste -- e si dimezza
# abbondantemente l'attesa nel caso peggiore.
TRAKT_SELF_MARK_SECONDS = 45

def self_mark_recent(cache_media_type=None):
	"""Vero se la marcatura appena fatta da NOI e' abbastanza recente. Senza tipo: una qualsiasi.

	Con gli indicatori Trakt, watched_status_mark scrive nello stesso database che le sincronizzazioni
	qui sotto ricostruiscono (indicators_dict: 1 -> trakt_db). Quindi ogni nostra marcatura fa
	scattare l'attivita' remota che ci sveglia, e il rebuild integrale ricalcola un dato che in locale
	e' gia' esatto. Il tipo va confrontato o la guardia di un tipo zittirebbe quella dell'altro.
	"""
	try:
		raw = get_property('fenlight.trakt.self_mark') or ''
		if not raw: return False
		parts = raw.split('|')
		stamp = float(parts[0])
		kind = parts[1] if len(parts) > 1 else ''
		# Timbro vecchio stile (solo l'istante): non sapendo il tipo non si puo' escludere niente.
		# cache_media_type None = "una marcatura qualsiasi", che e' cio' che serve al monitor: li' la
		# domanda non e' quale database ricostruire, ma se c'e' qualcosa di nuovo DA MOSTRARE.
		if cache_media_type and kind and kind != cache_media_type: return False
		return (time.time() - stamp) < TRAKT_SELF_MARK_SECONDS
	except: return False

def trakt_indicators_movies():
	# I film sono stati fino al lotto 107 l'unico percorso senza via incrementale: nessun confronto con
	# la cronologia, solo il rebuild integrale a ogni cambio di attivita'. Nel log della stick del
	# 22/08 alle 23:16:13 sono state scaricate 6 pagine per ottenere '599 da Trakt, 599 in cache,
	# 0 scartati' -- cioe' per non cambiare una riga -- e per giunta mentre la stessa CPU stava
	# costruendo la lista stagioni. Il rebuild resta qui sotto come strada di riserva, e serve ancora:
	# e' l'unica che si accorge delle RIMOZIONI.
	if self_mark_recent('movie'):
		_SYNC_DEFERRED[0] = True
		return logger('FenLight Trakt', 'watched movies: rebuild RIMANDATO, la modifica sembra nostra -- segnalibro attivita' + "'" + ' NON avanzato')
	# VIA INCREMENTALE (lotto 107), gemella di quella che le serie hanno gia' in trakt_indicators_tv.
	# La cronologia arriva dal piu' recente al piu' vecchio: tutto cio' che sta sopra il play piu'
	# recente gia' in locale e' esattamente cio' che e' cambiato. Se il confine cade DENTRO la prima
	# pagina, allora tutto il resto lo abbiamo gia', e non c'e' niente da ricostruire.
	# Il guardiano `len(new_plays) < len(history)` non e' un dettaglio: se la prima pagina fosse tutta
	# nuova non sapremmo se la seconda ne contiene altre, e salteremmo dei play. In quel caso si passa
	# dal rebuild come prima.
	# Le RIMOZIONI non compaiono nella cronologia (togliere un film da "visti" non aggiunge un play):
	# quando non c'e' nessun play nuovo si cade sul rebuild completo, che e' l'unico modo di accorgersi
	# di una riga sparita. Il caso peggiore resta quindi il comportamento di prima.
	# Misura che motiva tutto questo: nel log del 29/08 alle 03:25 la sincronizzazione ha scaricato
	# 6 pagine, '599 da Trakt, 599 in cache, 0 scartati', ~10 s di rete, per scoprire UN titolo
	# cambiato -- ed e' il pezzo piu' grosso dei 21 s che separano l'avvio dall'allineamento a Trakt.
	try: _first = call_trakt('sync/history/movies', params={'limit': history_page_limit}, with_auth=True, pagination=True, page_no=1)
	except: _first = None
	if _first:
		_history = list(_first[0] or [])
		_last_synced = trakt_watched_cache.last_watched_movie_date()
		_new_plays = [i for i in _history if i.get('watched_at', '') > _last_synced] if _last_synced else []
		if _new_plays and len(_new_plays) < len(_history):
			_rows = []
			# DAL PIU' VECCHIO AL PIU' RECENTE. La cronologia arriva al contrario, e per i film la
			# chiave della tabella e' (tipo, id, '', ''): due visioni dello stesso film finiscono sulla
			# STESSA riga, e WATCHED_UPSERT e' un INSERT OR REPLACE. Inserendoli nell'ordine di arrivo
			# l'ultimo a vincere sarebbe il piu' VECCHIO, e last_played resterebbe indietro -- cioe'
			# proprio il valore che al giro successivo decide cosa e' nuovo.
			for _item in reversed(_new_plays):
				try:
					_movie = _item['movie']
					_tmdb_id = get_trakt_movie_id(_movie['ids'])
					if not _tmdb_id: continue
					_rows.append(('movie', _tmdb_id, '', '', _item['watched_at'], _movie['title']))
				except: pass
			if _rows:
				# CONTROLLO DI COMPLETEZZA (lotto 108). La cronologia racconta solo cio' che e' stato
				# AGGIUNTO: se nella stessa finestra un film e' stato visto e un altro TOLTO dai visti,
				# i play nuovi ci sono, la via incrementale scatta, e la rimozione non verrebbe notata
				# mai piu' -- il giro dopo le attivita' non cambiano e non si guarda piu' indietro.
				# Il conto remoto lo si ottiene con UNA richiesta da un solo elemento: con limit=1
				# l'intestazione X-Pagination-Page-Count vale esattamente il numero di film visti.
				# Se i due conti non coincidono, o se la richiesta non riesce, si passa dal rebuild:
				# il caso peggiore resta il comportamento di prima, mai un dato sbagliato.
				_remote_count = None
				try:
					_probe = call_trakt('sync/watched/movies', params={'limit': 1}, with_auth=True, pagination=True, page_no=1)
					if _probe: _remote_count = int(_probe[1])
				except: _remote_count = None
				if _remote_count is not None:
					_changed = trakt_watched_cache.add_movie_watched(_rows)
					_local_count = trakt_watched_cache.watched_movie_count()
					if _local_count == _remote_count:
						logger('FenLight Trakt', 'watched movies: %s play nuovi aggiunti, nessun rebuild (via incrementale) | %s visti, coincide con Trakt' % (len(_rows), _local_count))
						return _changed
					logger('FenLight Trakt', 'watched movies: via incrementale INSUFFICIENTE, %s in locale contro %s su Trakt -- si ricostruisce' % (_local_count, _remote_count))
				else:
					logger('FenLight Trakt', 'watched movies: conto remoto non disponibile, si ricostruisce per sicurezza')
		try:
			if not _last_synced: _why = 'nessuna cronologia locale'
			elif not _new_plays: _why = 'nessun play piu' + "'" + ' recente del piu' + "'" + ' recente locale (rimozioni?)'
			else: _why = 'prima pagina tutta nuova (%s su %s)' % (len(_new_plays), len(_history))
			logger('FenLight Trakt', 'watched movies: rebuild completo, motivo: %s | ultimo locale=%s' % (_why, _last_synced))
		except: pass
	# Due canali silenziosi facevano sparire il badge "visto" da un sottoinsieme apparentemente casuale
	# di film, senza lasciare traccia nel log: get_trakt_movie_id restituisce None quando l'id TMDb non
	# e' risolvibile (e il film veniva saltato), e pool.submit non rilancia mai le eccezioni sollevate
	# dentro _process (il Future non viene letto). Ora entrambi finiscono in un conteggio loggato.
	dropped = []
	def _process(item):
		try:
			movie = item['movie']
			tmdb_id = get_trakt_movie_id(movie['ids'])
			if not tmdb_id:
				dropped.append('%s ids=%s' % (movie.get('title'), movie.get('ids')))
				return
			insert_append(('movie', tmdb_id, '', '', item['last_watched_at'], movie['title']))
		except Exception as e:
			dropped.append('%s -> %s' % ((item.get('movie') or {}).get('title'), e))
	insert_list = []
	insert_append = insert_list.append
	result = _get_all_sync_pages('sync/watched/movies')
	if result is None:
		# set_bulk_movie_watched esegue DELETE + INSERT: pubblicare una lista vuota azzererebbe l'intera
		# cache dei visti e farebbe sparire TUTTI i badge fino alla sincronizzazione successiva. Un errore
		# di rete arriva qui come None; una risposta 200 con lista vuota e' indistinguibile da "non ho
		# visto nulla", ma su un account gia' popolato e' quasi sempre un guasto: meglio non toccare nulla.
		# Non basta lasciare intatta la cache: va anche RIMANDATO il segnalibro delle attivita'.
		# Senza questa riga (lotto 88) reset_activity ha gia' fatto avanzare il segnalibro all'inizio
		# di trakt_sync_activities, quindi il giro dopo il confronto dice 'nessuna modifica' e il
		# cambiamento non viene piu' richiesto MAI PIU'. Misurato il 25/08: cache dei film visti ferma
		# all'8 agosto mentre Trakt dichiarava un'attivita' del 25, e 17 'No Changes Needed' di fila.
		# Un guasto momentaneo di rete diventava una perdita permanente.
		_SYNC_DEFERRED[0] = True
		logger('FenLight Trakt', 'watched movies: richiesta FALLITA, cache intatta e segnalibro NON avanzato')
		return
	# Vuoto CERTO (HTTP 200 con zero elementi). Sono due situazioni diverse e la cache locale le separa:
	#  - anche in locale non c'e' niente -> l'account non ha davvero film visti. Allinearsi non perde
	#    nulla e soprattutto fa AVANZARE il segnalibro, unico modo perche' la sincronizzazione converga.
	#    set_bulk su una cache gia' vuota restituisce un insieme vuoto, che il chiamante pubblica come
	#    '-' -> nessuna ricostruzione. E' il caso che il 30/08 ha prodotto 12 UpdateLibrary globali.
	#  - in locale ci sono dei visti -> un vuoto da Trakt e' quasi sempre un guasto (vedi la nota sopra):
	#    non si tocca niente, esattamente come prima. Il confronto e' con 0 e non con la verita' di
	#    watched_movie_count perche' la funzione restituisce None quando il conteggio NON e' disponibile,
	#    e in quel caso l'unica scelta prudente e' non toccare la cache.
	if not result:
		# Vuoto CERTO: la richiesta e' RIUSCITA e Trakt dichiara zero film visti. Da quando i guasti
		# tornano come None (vedi _get_all_sync_pages) questo caso non e' piu' ambiguo e va preso per
		# buono: ci si allinea, e soprattutto il segnalibro AVANZA. Il sospetto di "e' quasi sempre un
		# guasto" nasceva proprio dal fatto che `or []` faceva arrivare qui anche gli errori: tolta
		# quella confusione alla radice, tenere anche la diffidenza qui NON proteggerebbe piu' niente e
		# reintrodurrebbe il ciclo -- un account svuotato non convergerebbe mai, ogni giro tornerebbe
		# 'rebuild completo' con UpdateLibrary globale (30/08: 12 ricostruzioni della home in 7 minuti).
		# Azzerare una cache popolata e' la risposta giusta a una cronologia cancellata su Trakt. Se
		# invece fosse un 200 anomalo il danno e' transitorio e si ripara da solo: la sincronizzazione
		# successiva riscarica l'elenco vero e i badge tornano. La perdita PERMANENTE che la nota del
		# lotto 88 temeva era quella del segnalibro, ed e' il ramo None qui sopra a impedirla.
		logger('FenLight Trakt', 'watched movies: Trakt non ha film visti, cache allineata a vuoto (ne conteneva %s)' % trakt_watched_cache.watched_movie_count())
	make_thread_list(_process, result)
	logger('FenLight Trakt', 'watched movies: %s da Trakt, %s in cache, %s scartati%s'
			% (len(result), len(insert_list), len(dropped), (' -> %s' % dropped[:10]) if dropped else ''))
	return trakt_watched_cache.set_bulk_movie_watched(insert_list)

def trakt_indicators_tv():
	# Trakt no longer returns the seasons/episodes breakdown in sync/watched/shows, so the watched episodes
	# are rebuilt from the play history (250 per page). The newest page is fetched first: when it only holds
	# plays that are newer than what is already stored, those are appended and the rebuild is skipped.
	remap_cache = {}
	def _episode_remap(tmdb_id):
		# looked up once per show, not once per play
		if tmdb_id in remap_cache: return remap_cache[tmdb_id]
		try:
			from modules.metadata import tvshow_meta as _tm
			from modules.settings import mpaa_region as _mr
			_meta = _tm('tmdb_id', tmdb_id, tmdb_api_key(), _mr(), get_datetime())
			remap_cache[tmdb_id] = _meta.get('tmdb_to_tvdb_ep', {}) if _meta else {}
		except: remap_cache[tmdb_id] = {}
		return remap_cache[tmdb_id]
	def _make_row(item, tmdb_id, title, ep_remap):
		season_no, episode_no = item['episode']['season'], item['episode']['number']
		tvdb_s, tvdb_e = ep_remap.get((season_no, episode_no), (season_no, episode_no))
		return ('episode', tmdb_id, tvdb_s, tvdb_e, item['watched_at'], title)
	def _process_show(item):
		show = item['show']
		trakt_id = show['ids'].get('trakt')
		tmdb_id = get_trakt_tvshow_id(show['ids'])
		if not tmdb_id or not trakt_id: return
		shows_info[trakt_id] = (tmdb_id, show['title'], item.get('reset_at') or None, _episode_remap(tmdb_id))
	def _get_history_page(page_no):
		params = {'path': 'sync/history/episodes%s', 'params': {'limit': history_page_limit}, 'with_auth': True, 'pagination': True, 'page_no': page_no}
		try: history_extend(get_trakt(params) or [])
		except: logger('FenLight Trakt', 'watched history page %s FAILED' % page_no)
	try: first_page = call_trakt('sync/history/episodes', params={'limit': history_page_limit}, with_auth=True, pagination=True, page_no=1)
	except: first_page = None
	if not first_page:
		# Vedi la nota gemella in trakt_indicators_movies (lotto 88): senza rimandare il segnalibro,
		# questo guasto momentaneo diventa una perdita permanente. Nel log zb questa riga compare due
		# volte, ed e' li' che gli episodi visti hanno smesso di aggiornarsi.
		_SYNC_DEFERRED[0] = True
		return logger('FenLight Trakt', 'watched history request FAILED - episodi intatti, segnalibro NON avanzato')
	history = list(first_page[0] or [])
	history_extend = history.extend
	try: page_count = int(first_page[1])
	except: page_count = 1
	# Trakt returns the history newest first, so anything above the newest stored play is what changed.
	last_synced = trakt_watched_cache.last_watched_episode_date()
	new_plays = [i for i in history if i.get('watched_at', '') > last_synced] if last_synced else []
	if new_plays and len(new_plays) < len(history):
		insert_list = []
		for item in new_plays:
			try:
				tmdb_id = get_trakt_tvshow_id(item['show']['ids'])
				if not tmdb_id: continue
				insert_list.append(_make_row(item, tmdb_id, item['show']['title'], _episode_remap(tmdb_id)))
			except: pass
		if insert_list:
			_changed = trakt_watched_cache.add_tvshow_watched(insert_list)
			logger('FenLight Trakt', 'watched episodes sync: %s new plays added, no rebuild needed' % len(insert_list))
			return _changed
	# Con gli indicatori Trakt, watched_status_mark scrive nello STESSO database che
	# last_watched_episode_date() legge (indicators_dict: 1 -> trakt_db). Quindi dopo una nostra
	# marcatura il piu' recente locale E' gia' la marcatura stessa, nessun play remoto risulta piu'
	# recente, new_plays esce vuota e si finisce sul rebuild completo. Log della stick del 22/08:
	# 'ultimo locale=2026-08-22T11:12:54.000Z', cioe' la riga scritta due secondi dopo la chiusura
	# del player. Ogni marcatura si autoinnescava un rebuild da 6 pagine.
	# Il timbro dice che il cambiamento e' nostro ed e' gia' applicato in locale: non c'e' niente da
	# ricostruire. Vale anche per le rimozioni, perche' anche quelle le scrive gia' il percorso locale.
	# Finestra stretta: se scade, si ricostruisce come prima. Le modifiche fatte da un ALTRO
	# dispositivo portano play piu' recenti, quindi passano dalla via incrementale qui sopra.
	if not new_plays and last_synced and self_mark_recent('tvshow'):
		_SYNC_DEFERRED[0] = True
		return logger('FenLight Trakt', 'watched episodes: rebuild RIMANDATO, la modifica sembra nostra -- segnalibro attivita' + "'" + ' NON avanzato')
	# full rebuild: no stored history, plays were removed, or more new plays than a single page holds
	# PERF: il rebuild completo scarica 6 pagine di cronologia e ricostruisce 1274 episodi. Sul Mi
	# Stick costa 2-6 s di rete e CPU, e nel log del 22/08 e' partito a OGNI marcatura mentre la via
	# incrementale e' scattata una volta sola in tutta la sessione. Qui si registra PERCHE' si e'
	# finiti sul rebuild: senza questo dato la causa si puo' solo indovinare, e le tre ipotesi
	# plausibili (nessun play nuovo / play rimossi / prima pagina tutta nuova) portano a correzioni
	# diverse.
	try:
		if not last_synced: _why = 'nessuna cronologia locale'
		elif not new_plays: _why = 'nessun play piu' + "'" + ' recente del piu' + "'" + ' recente locale (rimozioni?)'
		else: _why = 'prima pagina tutta nuova (%s su %s)' % (len(new_plays), len(history))
		logger('FenLight Trakt', 'rebuild completo, motivo: %s | ultimo locale=%s | pagine=%s' % (_why, last_synced, page_count))
	except: pass
	shows_info = {}
	# Anche qui la chiamata era limitata alla prima pagina: oltre le 100 serie, gli episodi di quelle
	# escluse venivano scartati dal filtro shows_info, pur essendo presenti nella cronologia.
	shows = _get_all_sync_pages('sync/watched/shows')
	if shows is None:
		# Prima di questa guardia un guasto su sync/watched/shows cadeva su set_bulk_tvshow_watched([]),
		# cioe' DELETE di tutti gli episodi visti: un errore di rete cancellava la cronologia delle serie.
		# E' la stessa distinzione della gemella sui film, che qui mancava del tutto.
		_SYNC_DEFERRED[0] = True
		return logger('FenLight Trakt', 'watched shows: richiesta FALLITA, episodi intatti e segnalibro NON avanzato')
	if not shows:
		# Come per i film: riuscita con zero elementi e' un dato, non un sospetto. Il guasto e' il ramo
		# None qui sopra, che prima non esisteva affatto e lasciava che un errore di rete cadesse qui
		# dentro cancellando l'intera cronologia degli episodi.
		logger('FenLight Trakt', 'watched shows: Trakt non ha serie viste, episodi allineati a vuoto (ne conteneva %s)' % trakt_watched_cache.watched_episode_count())
		return trakt_watched_cache.set_bulk_tvshow_watched([])
	make_thread_list(_process_show, shows)
	if page_count > 1: make_thread_list(_get_history_page, range(2, page_count + 1))
	watched_episodes = {}
	for item in history:
		try:
			info = shows_info.get(item['show']['ids'].get('trakt'))
			if not info: continue
			tmdb_id, title, reset_at, ep_remap = info
			watched_at = item['watched_at']
			if reset_at and watched_at < reset_at: continue
			key = (item['episode']['season'], item['episode']['number'], tmdb_id)
			if key in watched_episodes and watched_episodes[key][4] >= watched_at: continue
			watched_episodes[key] = _make_row(item, tmdb_id, title, ep_remap)
		except: pass
	insert_list = list(watched_episodes.values())
	logger('FenLight Trakt', 'watched episodes rebuild: %s shows, %s history plays over %s pages, %s episodes' \
			% (len(shows), len(history), page_count, len(insert_list)))
	return trakt_watched_cache.set_bulk_tvshow_watched(insert_list)

def trakt_playback_progress():
	params = {'path': 'sync/playback%s', 'with_auth': True, 'pagination': False}
	return get_trakt(params)

def trakt_comments(media_type, imdb_id):
	def _process(foo):
		data = get_trakt(params)
		for count, item in enumerate(data, 1):
			try:
				rating = '%s/10 - ' % item['user_rating'] if item['user_rating'] else ''
				comment = template % \
				(count, rating, item['user']['username'].upper(), js2date(item['created_at'], date_format, True).strftime('%d %B %Y'), replace_html_codes(item['comment']))
				if item['spoiler']: comment = spoiler_template + comment
				all_comments_append(comment)
			except: pass
		return all_comments
	all_comments = []
	all_comments_append = all_comments.append
	template, spoiler_template, date_format = '[B]%02d. [I]%s%s - %s[/I][/B][CR][CR]%s', '[B][COLOR red][CONTAINS SPOILERS][/COLOR][CR][/B]', '%Y-%m-%dT%H:%M:%S.000Z'
	media_type = 'movies' if media_type in ('movie', 'movies') else 'shows'
	string = 'trakt_comments_%s %s' % (media_type, imdb_id)
	params = {'path': '%s/%s/comments', 'path_insert': (media_type, imdb_id), 'params': {'limit': 1000, 'sort': 'likes'}, 'pagination': False}
	return cache_object(_process, string, 'foo', False, 168)

def trakt_progress_movies(progress_info):
	def _process(item):
		tmdb_id = get_trakt_movie_id(item['movie']['ids'])
		if not tmdb_id: return
		obj = ('movie', str(tmdb_id), '', '', str(round(item['progress'], 1)), 0, item['paused_at'], item['id'], item['movie']['title'])
		insert_append(obj)
	insert_list = []
	insert_append = insert_list.append
	progress_items = [i for i in progress_info  if i['type'] == 'movie' and i['progress'] > 1]
	# Torna QUALI film hanno cambiato avanzamento, per la ricarica mirata (lotto 119). Anche il caso
	# 'nessun film in corso' e' un cambiamento da mostrare -- e' l'ultimo film che ESCE da 'continua a
	# guardare' -- quindi passa dallo stesso calcolo invece di uscire a mani vuote.
	if not progress_items: return trakt_watched_cache.set_bulk_movie_progress([])
	threads = list(make_thread_list(_process, progress_items))
	[i.join() for i in threads]
	return trakt_watched_cache.set_bulk_movie_progress(insert_list)

def trakt_progress_tv(progress_info):
	def _process_show(show):
		tmdb_id = get_trakt_tvshow_id(show['ids'])
		if not tmdb_id: return
		try:
			from modules.metadata import tvshow_meta as _tm
			from modules.settings import mpaa_region as _mr
			_meta = _tm('tmdb_id', tmdb_id, tmdb_api_key(), _mr(), get_datetime())
			_ep_remap = _meta.get('tmdb_to_tvdb_ep', {}) if _meta else {}
		except: _ep_remap = {}
		shows_info[show['ids'].get('trakt')] = (tmdb_id, _ep_remap)
	def _process():
		for p_item in progress_items:
			try:
				# matched on the trakt id: two different shows can share the same title
				info = shows_info.get(p_item['show']['ids'].get('trakt'))
				if not info: continue
				tmdb_id, ep_remap = info
				season, ep_num = p_item['episode']['season'], p_item['episode']['number']
				tvdb_s, tvdb_e = ep_remap.get((season, ep_num), (season, ep_num))
				if tvdb_s > 0: yield ('episode', str(tmdb_id), tvdb_s, tvdb_e, str(round(p_item['progress'], 1)),
									0, p_item['paused_at'], p_item['id'], p_item['show']['title'])
			except: pass
	shows_info = {}
	progress_items = [i for i in progress_info if i['type'] == 'episode' and i['progress'] > 1]
	# Gemella di trakt_progress_movies: torna le triple 'tmdb:stagione:episodio' cambiate, non i soli
	# id di serie. Vedi kodi_utils.episode_uid per il perche' della tripla.
	if not progress_items: return trakt_watched_cache.set_bulk_tvshow_progress([])
	all_shows = {i['show']['ids'].get('trakt'): i['show'] for i in progress_items}
	make_thread_list(_process_show, list(all_shows.values()))
	return trakt_watched_cache.set_bulk_tvshow_progress(list(_process()))

OFFICIAL_STATUS_PROP = 'fenlight.trakt.official_status.%s'

def trakt_official_status(media_type):
	"""script.trakt sta gia' facendo lui lo scrobble di questo tipo di media?

	LA RISPOSTA E' MEMORIZZATA, e non e' un'ottimizzazione opportunistica (lotto 125). Misurato sulla
	stick il 02/09 alle 14:22: questa funzione da sola e' costata 2347 ms dei 2380 della scrittura
	dello stato locale -- la INSERT ne ha presi 1. Il motivo non e' il lavoro che fa, e' QUANDO lo fa:
	addon_installed e addon_enabled sono due getCondVisibility, cioe' chiedono il lock della GUI, e
	set_bookmark gira alla chiusura del player, mentre il thread grafico smonta il decoder, rinegozia
	l'HDMI e ricostruisce la finestra. Il costo e' contesa, non calcolo.
	E' una domanda di CONFIGURAZIONE: quale addon e' installato, abilitato, autorizzato e con quali
	preferenze di scrobble. Non cambia durante una riproduzione, quindi non ha nessun motivo di
	essere posta nell'unico istante in cui costa. Il valore lo semina il servizio a intervalli
	tranquilli (vedi service.refresh_official_status); qui resta il calcolo diretto come ripiego per
	la primissima chiamata, se il servizio non ha ancora girato.
	La conseguenza da tenere presente: cambiando le impostazioni di script.trakt il valore vecchio
	resta valido finche' il servizio non rigira. E' un ciclo del TraktMonitor, non una sessione.
	"""
	key = 'movie' if media_type in ('movie', 'movies') else 'episode'
	cached = kodi_utils.get_property(OFFICIAL_STATUS_PROP % key)
	if cached: return cached == 'true'
	return compute_official_status(media_type, store=True)

def compute_official_status(media_type, store=False):
	result = _compute_official_status(media_type)
	if store:
		key = 'movie' if media_type in ('movie', 'movies') else 'episode'
		try: kodi_utils.set_property(OFFICIAL_STATUS_PROP % key, 'true' if result else 'false')
		except: pass
	return result

def _compute_official_status(media_type):
	if not addon_installed('script.trakt'): return True
	if not addon_enabled('script.trakt'): return True
	trakt_addon = addon('script.trakt')
	try: authorization = trakt_addon.getSetting('authorization')
	except: authorization = ''
	if authorization == '': return True
	try: exclude_http = trakt_addon.getSetting('ExcludeHTTP')
	except: exclude_http = ''
	if exclude_http in ('true', ''): return True
	media_setting = 'scrobble_movie' if media_type in ('movie', 'movies') else 'scrobble_episode'
	try: scrobble = trakt_addon.getSetting(media_setting)
	except: scrobble = ''
	if scrobble in ('false', ''): return True
	return False

def trakt_get_my_calendar(recently_aired, current_date):
	def _process(dummy):
		data = get_trakt(params)
		data = [{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
				'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']} \
									for i in data if i['episode']['season'] > 0]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(recently_aired, current_date)
	string = 'trakt_get_my_calendar_%s_%s' % (start, finish)
	params = {'path': 'calendars/my/shows/%s/%s', 'path_insert': (start, finish), 'with_auth': True, 'pagination': False}
	return cache_trakt_object(_process, string, params)

def trakt_calendar_days(recently_aired, current_date):
	if recently_aired: start, finish = (current_date - timedelta(days=14)).strftime('%Y-%m-%d'), '14'
	else:
		previous_days = int(get_setting('fenlight.trakt.calendar_previous_days', '0'))
		future_days = int(get_setting('fenlight.trakt.calendar_future_days', '7'))
		start = (current_date - timedelta(days=previous_days)).strftime('%Y-%m-%d')
		finish = str(previous_days + future_days)
	return start, finish

def make_trakt_slug(name):
	import re
	name = name.strip()
	name = name.lower()
	name = re.sub('[^a-z0-9_]', '-', name)
	name = re.sub('--+', '-', name)
	return name

def trakt_get_activity():
	params = {'path': 'sync/last_activities%s', 'with_auth': True, 'pagination': False}
	return get_trakt(params)

def get_trakt(params):
	result = call_trakt(params['path'] % params.get('path_insert', ''), params=params.get('params', {}), data=params.get('data'), is_delete=params.get('is_delete', False),
						with_auth=params.get('with_auth', False), method=params.get('method'), pagination=params.get('pagination', True), page_no=params.get('page_no'))
	return result[0] if params.get('pagination', True) else result

def _publish_changed(changed_ids, changed_actions, changed_unknown):
	"""Pubblica COSA e' cambiato, perche' il monitor ricarichi i soli contenitori interessati.

	Due proprieta', due criteri diversi, e vanno lette insieme (service.TraktMonitor):

	  fenlight.trakt.changed_ids      ''  = non lo sappiamo          -> ricostruzione globale
	                                  '-' = lo sappiamo, nessun id   -> nessun id da colpire
	                                  ... = le identita' cambiate    -> mirato per contenuto
	  fenlight.trakt.changed_actions  ''  = nessuna azione
	                                  ... = i widget che cambiano COMPOSIZIONE

	Il '-' e' un'AFFERMAZIONE, non un'assenza, ed e' esattamente qui che il lotto 59 sbagliava: lo
	pubblicava anche quando i rami che avevano lavorato non alimentavano changed_ids -- l'avanzamento,
	la watchlist -- cioe' dichiarava 'non e' cambiato niente' per un cambiamento vero. Il monitor gli
	credeva e non ricostruiva nulla. Ora ogni ramo vivo alimenta almeno uno dei due canali, e
	changed_unknown resta l'unico modo di dire 'non lo so'.

	Le identita' possono contenere ':' (livello episodio, kodi_utils.episode_uid): la separazione e'
	sulla virgola e le due cose non si confondono.
	"""
	try:
		_ids = '' if changed_unknown else (','.join(sorted(str(i) for i in changed_ids if i)) or '-')
		_actions = ','.join(sorted(str(a) for a in changed_actions if a))
		kodi_utils.set_property('fenlight.trakt.changed_ids', _ids)
		kodi_utils.set_property('fenlight.trakt.changed_actions', _actions)
		if changed_unknown:
			logger('FenLight Trakt', 'cambiamento di natura ignota: si ricostruisce tutto')
		else:
			logger('FenLight Trakt', 'titoli cambiati: %d%s | azioni: %s'
					% (len(changed_ids), (' -> %s' % sorted(changed_ids)[:10]) if changed_ids else '',
						_actions or 'nessuna'))
	except: pass

# Quante riparazioni remote per giro. Il tetto esiste perche' un guasto prolungato di rete puo'
# accumularne parecchie, e ripartire con una raffica di chiamate sarebbe il modo peggiore di
# rientrare: si smaltiscono poche per volta, e quello che resta torna al giro dopo.
REMOTE_REPAIRS_PER_CYCLE = 5

def _drain_remote_repairs():
	"""Ripete le chiamate a Trakt che la riconciliazione ha scoperto mancanti (lotto 133).

	Due code, due guasti diversi, entrambi silenziosi fino a ieri:
	  PENDING_REMOTE_DELETES  l'utente ha azzerato l'avanzamento, la DELETE remota non e' passata e
	                          Trakt elenca ancora il segnalibro. Senza questa ripetizione la riga
	                          resterebbe `pending_delete` per sempre e Trakt non lo saprebbe mai.
	  PENDING_REMOTE_PUSHES   l'utente ha messo in pausa, la spinta non e' mai stata confermata
	                          (rete assente, token, eccezione ingoiata). La riga resta visibile in
	                          locale -- non si cancella la pausa di qualcuno per un guasto di rete --
	                          e va rispinta finche' non passa.
	"""
	deletes = [trakt_cache.PENDING_REMOTE_DELETES.pop(0) for _ in range(min(len(trakt_cache.PENDING_REMOTE_DELETES), REMOTE_REPAIRS_PER_CYCLE))]
	pushes = [trakt_cache.PENDING_REMOTE_PUSHES.pop(0) for _ in range(min(len(trakt_cache.PENDING_REMOTE_PUSHES), REMOTE_REPAIRS_PER_CYCLE))]
	if not deletes and not pushes: return
	from threading import Thread
	from caches.base_cache import connect_database
	def _work():
		for db_type, key, resume_id in deletes:
			try:
				trakt_progress('clear_progress', db_type, key[0], 0, key[1], key[2], resume_id)
				logger('Fen Light', 'cancellazione remota ripetuta per %s %s' % (db_type, key[0]))
			except Exception as e: logger('Fen Light', 'cancellazione remota di %s FALLITA di nuovo: %s' % (key[0], e))
		for db_type, key in pushes:
			try:
				row = connect_database('trakt_db').execute(
					'SELECT resume_point FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?',
					(db_type, key[0], key[1], key[2])).fetchone()
				if not row: continue
				resume_id = trakt_progress('set_progress', db_type, key[0], float(row[0]), key[1], key[2]) or 0
				if resume_id:
					connect_database('trakt_db').execute(
						'UPDATE progress SET resume_id = ? WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?',
						(resume_id, db_type, key[0], key[1], key[2]))
					logger('Fen Light', 'spinta ripetuta e confermata per %s %s' % (db_type, key[0]))
			except Exception as e: logger('Fen Light', 'spinta ripetuta di %s FALLITA: %s' % (key[0], e))
	Thread(target=_work).start()

def trakt_sync_activities(force_update=False):
	# def clear_watched_tvshow_cache():
	# 	from modules.watched_status import clear_cache_watched_tvshow_status
	# 	clear_cache_watched_tvshow_status(watched_indicators=1)
	def clear_properties(media_type):
		for item in ((True, True), (True, False), (False, True), (False, False)): clear_property('1_%s_%s_%s_watched' % (media_type, item[0], item[1]))
	def _get_timestamp(date_time):
		return int(time.mktime(date_time.timetuple()))
	def _compare(latest, cached):
		try: result = _get_timestamp(js2date(latest, res_format)) > _get_timestamp(js2date(cached, res_format))
		except: result = True
		return result
	def _check_daily_expiry():
		return int(time.time()) >= int(get_setting('fenlight.trakt.next_daily_clear', '0'))
	if force_update: clear_all_trakt_cache_data(silent=True, refresh=False)
	elif _check_daily_expiry():
		clear_daily_cache()
		set_setting('trakt.next_daily_clear', str(int(time.time()) + (24*3600)))
	if not trakt_user_active() and not force_update: return 'no account'
	try: latest = trakt_get_activity()
	except: return 'failed'
	if not latest: return 'failed'
	cached = reset_activity(latest)
	# reset_activity fa avanzare il segnalibro "visto fino a qui" QUI, prima che il lavoro sia fatto.
	# Se una guardia self_mark salta poi una ricostruzione, il cambiamento risulta gia' visto e non
	# torna mai piu': il giro dopo il confronto da 'not needed', per sempre. Misurato il 24/08 (log q1,
	# 14:24:40 e 14:25:16): due 'success', cioe' due cambiamenti veri arrivati da Trakt, entrambi
	# consumati e persi. Il flag viene azzerato qui e riletto in fondo. Vedi lotto 58.
	_SYNC_DEFERRED[0] = False
	if not _compare(latest['all'], cached['all']):
		if trakt_watched_cache.has_any_progress():
			progress_info = trakt_playback_progress()
			if progress_info is not None:
				movie_ids = {i['id'] for i in progress_info if i['type'] == 'movie'}
				ep_ids = {i['id'] for i in progress_info if i['type'] == 'episode'}
				movie_deleted = trakt_watched_cache.has_progress_deletions('movie', movie_ids)
				ep_deleted = trakt_watched_cache.has_progress_deletions('episode', ep_ids)
				changed_ids, changed_unknown = set(), False
				if movie_deleted:
					clear_properties('movie')
					_ids = trakt_progress_movies(progress_info)
					if _ids is None: changed_unknown = True
					else: changed_ids |= _ids
				if ep_deleted:
					clear_properties('episode')
					_ids = trakt_progress_tv(progress_info)
					if _ids is None: changed_unknown = True
					else: changed_ids |= _ids
				if movie_deleted or ep_deleted:
					# Un titolo USCITO dall'avanzamento cambia la composizione di 'continua a guardare':
					# l'id da solo non basta, perche' il widget lo mostra ancora e la regola per id lo
					# troverebbe -- ma solo finche' non e' stato ricostruito da qualcun altro. L'azione
					# lo copre in entrambe le direzioni. Vedi kodi_utils.CONTINUE_WATCHING_ACTION.
					_publish_changed(changed_ids, {kodi_utils.CONTINUE_WATCHING_ACTION}, changed_unknown)
					return 'success'
		return 'not needed'
	refresh_movies_progress, refresh_shows_progress = False, False
	cached_movies, latest_movies = cached['movies'], latest['movies']
	cached_shows, latest_shows = cached['shows'], latest['shows']
	cached_episodes, latest_episodes = cached['episodes'], latest['episodes']
	# LOTTO 119 -- STRUMENTI MORTI RIMOSSI. Qui c'erano sei confronti in piu': 'recommendations',
	# 'favorites', 'collected_at' (film e serie) e le liste 'updated_at'/'liked_at'. Sono funzioni che
	# questa installazione non usa: nessun widget le mostra e nessuna schermata legge quelle cache,
	# quindi non c'era niente da invalidare e tanto meno da ricostruire. Sei _compare in meno a ogni
	# poll da 30 s, e -- soprattutto -- sei rami in meno capaci di dichiarare 'e' cambiato qualcosa'
	# senza saper dire cosa, che e' il modo in cui un refresh mirato degenera in globale.
	# Restano i tre eventi che governano widget veri: visto, avanzamento, watchlist.
	# Raccolta di cosa e' cambiato, per il refresh mirato. Due canali distinti e non intercambiabili:
	#  - changed_ids: CHI e' cambiato. Colpisce i widget che gia' lo contengono.
	#  - changed_actions: QUALE widget cambia composizione. Colpisce il widget per quello che E',
	#    ed e' l'unico criterio che funziona quando il titolo non e' ANCORA nella lista (un film che
	#    entra in 'continua a guardare', un titolo aggiunto alla watchlist da un altro dispositivo).
	# `None` da una ricostruzione significa "non so quali", e allora si ricade sul refresh globale:
	# e' diverso da un insieme vuoto, che significa "nessun titolo e' cambiato davvero".
	changed_ids, changed_actions, changed_unknown = set(), set(), False
	# NASCONDI/RIESPONI una serie dal 'continua a guardare'. Spostato qui sotto perche' anche questo
	# ramo deve DICHIARARE cosa ha toccato: prima invalidava la cache e usciva muto, quindi se era
	# l'unico cambiamento del giro il payload finiva a '-' e il widget non si ricostruiva mai --
	# lo stesso difetto dell'avanzamento, sullo stesso widget. Solo l'azione e nessun id: nascondere
	# TOGLIE la serie dalla lista e riesporla ce la rimette, e in nessuno dei due casi l'id da solo
	# risponde alla domanda giusta. Trakt non dice QUALE serie e' stata nascosta.
	if _compare(latest_shows['hidden_at'], cached_shows['hidden_at']):
		clear_properties('episode')
		clear_trakt_hidden_data('progress_watched')
		changed_actions.add(kodi_utils.CONTINUE_WATCHING_ACTION)
	if _compare(latest_movies['watched_at'], cached_movies['watched_at']):
		clear_properties('movie')
		# L'AZIONE ACCOMPAGNA GLI ID (lotto 134). Segnare un film come visto lo fa USCIRE da 'continua
		# a guardare': e' un cambiamento di COMPOSIZIONE, e la regola per id da sola non lo copre --
		# per la stessa ragione, parola per parola, gia' scritta in watched_status.refresh_container_for
		# e nel ramo dell'avanzamento qui sotto. Il percorso LOCALE l'azione la mandava da sempre;
		# questo, che e' il percorso di cio' che arriva DA UN ALTRO DISPOSITIVO, no.
		changed_actions.add(kodi_utils.CONTINUE_WATCHING_ACTION)
		_ids = trakt_indicators_movies()
		if _ids is None: changed_unknown = True
		else: changed_ids |= _ids
	if _compare(latest_episodes['watched_at'], cached_episodes['watched_at']):
		clear_properties('episode')
		# QUI IL BUCO ERA PIU' GRAVE CHE PER I FILM (lotto 134). Segnare visto un episodio fa entrare
		# in 'continua a guardare' l'episodio SUCCESSIVO, che e' un elemento DIVERSO da quello
		# marcato: il suo id non e' fra i cambiati e non e' ancora nell'elenco pubblicato dal widget,
		# quindi nessuna regola per id puo' trovarlo. Serve l'azione, e mancava.
		# Misurato il 03/09 alle 04:53: episodio segnato visto sulla stick, dove il percorso locale
		# manda l'azione e il prossimo episodio compare subito. Sul Mac arriva da qui --
		# 'titoli cambiati: 1 -> [330320] | azioni: nessuna' -- e il prossimo episodio non e' mai
		# entrato in 'continua a guardare'.
		changed_actions.add(kodi_utils.CONTINUE_WATCHING_ACTION)
		# Livello SERIE, ed e' voluto: un episodio VISTO fa avanzare la serie, quindi si aggiornano i
		# widget che contengono la serie -- badge, prossimo episodio, 'continua a guardare' (che
		# pubblica anche il tmdb nudo di ogni episodio, vedi paginator._publish_ids).
		_ids = trakt_indicators_tv()
		if _ids is None: changed_unknown = True
		else: changed_ids |= _ids
	# La WATCHLIST sono DUE widget, non uno: quello dei film e quello delle serie, costruiti dalla
	# stessa azione 'trakt_watchlist' da due classi diverse. Trakt li distingue gia' con due
	# timestamp separati, e fin qui la distinzione si perdeva: aggiungere un film da un altro
	# dispositivo ricostruiva anche la watchlist delle serie. Qui ognuno colpisce il proprio.
	# Solo l'AZIONE, e nessun id: l'evento e' 'la lista e' cambiata', e il titolo entrato non e'
	# ancora nell'elenco pubblicato dal widget -- la regola per id lo scarterebbe.
	if _compare(latest_movies['watchlisted_at'], cached_movies['watchlisted_at']):
		clear_trakt_collection_watchlist_data('watchlist', 'movie')
		changed_actions.add(kodi_utils.qualify_action(kodi_utils.WATCHLIST_ACTION, 'movie'))
	if _compare(latest_shows['watchlisted_at'], cached_shows['watchlisted_at']):
		clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
		changed_actions.add(kodi_utils.qualify_action(kodi_utils.WATCHLIST_ACTION, 'tvshow'))
	if _compare(latest_movies['paused_at'], cached_movies['paused_at']): refresh_movies_progress = True
	if _compare(latest_episodes['paused_at'], cached_episodes['paused_at']): refresh_shows_progress = True
	progress_info = None
	if not (refresh_movies_progress and refresh_shows_progress):
		progress_info = trakt_playback_progress()
		if progress_info is not None:
			if not refresh_movies_progress:
				trakt_ids = {i['id'] for i in progress_info if i['type'] == 'movie'}
				if trakt_watched_cache.has_progress_deletions('movie', trakt_ids): refresh_movies_progress = True
			if not refresh_shows_progress:
				trakt_ids = {i['id'] for i in progress_info if i['type'] == 'episode'}
				if trakt_watched_cache.has_progress_deletions('episode', trakt_ids): refresh_shows_progress = True
	if refresh_movies_progress or refresh_shows_progress:
		if progress_info is None: progress_info = trakt_playback_progress()
		# L'AVANZAMENTO era il buco: questi due rami ricostruivano la tabella progress e non
		# dichiaravano NIENTE, quindi il payload usciva '-' -- 'lo sappiamo, non e' cambiato nulla' --
		# ed era falso. Un film lasciato a meta' su un altro dispositivo arrivava nel database della
		# stick e non compariva mai a schermo (log del 01/09, 20:04:45). Ora i due costruttori tornano
		# le identita' che hanno davvero cambiato avanzamento, calcolate sul prima/dopo della tabella.
		# L'azione accompagna sempre gli id, perche' 'continua a guardare' cambia COMPOSIZIONE:
		# in aggiunta il titolo non e' ancora nella lista, in rimozione l'elenco e' quello di prima.
		changed_actions.add(kodi_utils.CONTINUE_WATCHING_ACTION)
		if refresh_movies_progress:
			clear_properties('movie')
			# Identita' di livello FILM: il tmdb nudo.
			_ids = trakt_progress_movies(progress_info)
			if _ids is None: changed_unknown = True
			else: changed_ids |= _ids
		if refresh_shows_progress:
			clear_properties('episode')
			# Identita' di livello EPISODIO ('tmdb:stagione:episodio'): un episodio in pausa non e' la
			# sua serie, e non deve ricostruire ogni widget che contenga quella serie.
			_ids = trakt_progress_tv(progress_info)
			if _ids is None: changed_unknown = True
			else: changed_ids |= _ids
	# Le richieste che la riconciliazione ha prodotto: cancellazioni remote non recepite e spinte mai
	# confermate. Fuori dalla transazione e fuori dal percorso che disegna, in un thread.
	_drain_remote_repairs()
	# Qualcosa e' stato rimandato: il segnalibro torna indietro, cosi' il prossimo giro riprende il
	# lavoro invece di trovare 'nessuna modifica'. La guardia self_mark diventa cosi' un RINVIO e non
	# piu' un cestino: al massimo ritarda di una finestra self_mark, non perde piu' niente.
	if _SYNC_DEFERRED[0]:
		_SYNC_DEFERRED[0] = False
		restore_activity(cached)
	_publish_changed(changed_ids, changed_actions, changed_unknown)
	return 'success'
