# -*- coding: utf-8 -*-
from caches.meta_cache import meta_cache
from modules.kodi_utils import make_session

SKYHOOK_URL = 'https://skyhook.sonarr.tv/v1/tvdb/shows/en/%s'
EXPIRY_7_DAYS = 168
invalid_tvdb = ('', 'None', None, 0, '0')
finished_statuses = ('Ended', 'Canceled')

# Session pigra (lotto 51 bis): era `session = make_session('https://skyhook.sonarr.tv')` a livello di modulo, e make_session()
# fa `import requests` al suo interno -- quindi ogni modulo che importava questo file
# caricava l'albero di requests SENZA nessuna istruzione `import requests` visibile.
# E' il motivo per cui la prima correzione non aveva prodotto alcun guadagno misurabile.
_session = [None]

def _get_session():
	if _session[0] is None: _session[0] = make_session('https://skyhook.sonarr.tv')
	return _session[0]

def _fetch_raw(tvdb_id):
	cache_key = 'skyhook_raw_%s' % tvdb_id
	data = meta_cache.get_function(cache_key)
	if data: return data
	try:
		response = _get_session().get(SKYHOOK_URL % tvdb_id, timeout=15)
		if response.status_code != 200: return None
		data = response.json()
		meta_cache.set_function(cache_key, data, expiration=EXPIRY_7_DAYS)
		return data
	except: return None

def get_skyhook_season_data(tvdb_id, tmdb_season_data=None):
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	try:
		all_episodes = data.get('episodes', [])
		tmdb_poster_map = {s['season_number']: s.get('poster_path') for s in tmdb_season_data if s.get('poster_path')} if tmdb_season_data else {}
		season_list = []
		for s in data.get('seasons', []):
			snum = s['seasonNumber']
			season_eps = [e for e in all_episodes if e.get('seasonNumber') == snum]
			poster = tmdb_poster_map.get(snum) or next((i['url'] for i in s.get('images', []) if i.get('coverType') == 'Poster'), None)
			first_ep = season_eps[0] if season_eps else None
			season_list.append({
				'season_number': snum,
				'episode_count': len(season_eps),
				'poster_path': poster,
				'air_date': first_ep.get('airDate', '') if first_ep else '',
				'name': s.get('name', None),
				'overview': '',
				'id': snum
			})
		season_list.sort(key=lambda x: x['season_number'])
		return season_list or None
	except: return None

def get_skyhook_episodes(tvdb_id, season, meta):
	if tvdb_id in invalid_tvdb: return None
	data = _fetch_raw(tvdb_id)
	if not data: return None
	try:
		season = int(season)
		finished = meta.get('status', '') in finished_statuses
		total_seasons = meta.get('total_seasons', 1)
		if season == 1: season_type = 'premiere_finale' if (total_seasons == 1 and finished) else 'premiere'
		else: season_type = 'finale' if (total_seasons == season and finished) else ''
		raw_eps = sorted([e for e in data.get('episodes', []) if e.get('seasonNumber') == season],
						 key=lambda x: x.get('episodeNumber', 0))
		if not raw_eps: return None
		result = []
		midseason_premiere = False
		for ep in raw_eps:
			ep_num = ep.get('episodeNumber', 0)
			finale_type = ep.get('finaleType', '')
			if ep_num == 1:
				episode_type = 'series_premiere' if 'premiere' in season_type else 'season_premiere'
			elif midseason_premiere:
				episode_type, midseason_premiere = 'mid_season_premiere', False
			elif finale_type == 'series':
				episode_type = 'series_finale'
			elif finale_type == 'season':
				episode_type = 'series_finale' if 'finale' in season_type else 'season_finale'
			elif finale_type == 'mid_season':
				episode_type, midseason_premiere = 'mid_season_finale', True
			else:
				episode_type = ''
			runtime = ep.get('runtime')
			result.append({
				'writer': [], 'director': [], 'mediatype': 'episode',
				'episode_type': episode_type,
				'episode_id': ep.get('tvdbId'),
				'title': ep.get('title', ''),
				'plot': ep.get('overview') or '',
				'duration': int(runtime) * 60 if runtime else 30 * 60,
				'premiered': ep.get('airDate', ''),
				'season': season,
				'episode': ep_num,
				'rating': 0,
				'votes': 0,
				'thumb': ep.get('image'),
				'guest_stars': []
			})
		return result or None
	except: return None

def get_tvdb_to_tmdb_map(tvdb_id, tmdb_season_data):
	if tvdb_id in invalid_tvdb: return {}
	data = _fetch_raw(tvdb_id)
	if not data: return {}
	try:
		tvdb_eps = sorted(
			[e for e in data.get('episodes', []) if e.get('seasonNumber', 0) > 0 and e.get('absoluteEpisodeNumber')],
			key=lambda x: x['absoluteEpisodeNumber']
		)
		tmdb_eps = []
		for s in sorted(tmdb_season_data, key=lambda x: x['season_number']):
			snum = s.get('season_number', 0)
			if snum == 0: continue
			for ep in range(1, s.get('episode_count', 0) + 1):
				tmdb_eps.append((snum, ep))
		mapping = {}
		for i, tvdb_ep in enumerate(tvdb_eps):
			if i >= len(tmdb_eps): break
			tvdb_key = (tvdb_ep['seasonNumber'], tvdb_ep['episodeNumber'])
			tmdb_val = tmdb_eps[i]
			if tvdb_key != tmdb_val:
				mapping[tvdb_key] = tmdb_val
		return mapping
	except: return {}