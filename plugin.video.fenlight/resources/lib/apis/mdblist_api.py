# -*- coding: utf-8 -*-
import requests
from caches.main_cache import cache_object
from caches.lists_cache import lists_cache_object
from modules.settings import mdblist_api_key
from modules.kodi_utils import notification

session = requests.Session()
API_ENDPOINT = 'https://api.mdblist.com/%s'
timeout = 20

def call_mdblist(endpoint, params=None):
	if params is None: params = {}
	api_key = mdblist_api_key()
	if not api_key:
		notification('Please set a valid MDBList API Key')
		return None
	params['apikey'] = api_key
	try:
		resp = session.get(API_ENDPOINT % endpoint, params=params, timeout=timeout)
		resp.raise_for_status()
		return resp.json()
	except: return None

def mdblist_get_my_lists():
	def _fetch(dummy):
		return call_mdblist('lists/user/')
	return cache_object(_fetch, 'mdblist_my_lists', 'x', False, 1)

def mdblist_get_liked_lists():
	def _fetch(dummy):
		data = call_mdblist('lists/liked/')
		if isinstance(data, dict): return data.get('lists') or []
		return data or []
	return cache_object(_fetch, 'mdblist_liked_lists', 'x', False, 1)

# Liste che vanno ordinate per data di aggiunta (date added, dal piu' recente) invece che per rank
MDBLIST_DATE_ADDED_LISTS = {'91378'}  # amything/latest-releases-gary

def mdblist_get_list_contents(list_id):
	def _process(lid):
		params = {'unified': 'true', 'limit': 1000}
		by_date_added = str(lid) in MDBLIST_DATE_ADDED_LISTS
		if by_date_added: params.update({'sort': 'added', 'order': 'asc'})
		raw = call_mdblist('lists/%s/items/' % lid, params=params)
		if not raw: return []
		results = []
		for idx, item in enumerate(raw):
			try:
				ids = item['ids']
				results.append({
					'media_ids': {'tmdb': ids.get('tmdb'), 'imdb': ids.get('imdb'), 'tvdb': ids.get('tvdb')},
					'type': item['mediatype'],
					'order': idx if by_date_added else item.get('rank', 0)
				})
			except: pass
		return results
	return lists_cache_object(_process, 'mdblist_list_contents_%s' % list_id, list_id, False, 24)