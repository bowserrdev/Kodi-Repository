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

def mdblist_get_list_contents(list_id):
	def _process(lid):
		raw = call_mdblist('lists/%s/items/' % lid, params={'unified': 'true', 'limit': 1000})
		if not raw: return []
		results = []
		for item in raw:
			try:
				ids = item['ids']
				results.append({
					'media_ids': {'tmdb': ids.get('tmdb'), 'imdb': ids.get('imdb'), 'tvdb': ids.get('tvdb')},
					'type': item['mediatype'],
					'order': item.get('rank', 0)
				})
			except: pass
		return results
	return lists_cache_object(_process, 'mdblist_list_contents_%s' % list_id, list_id, False, 24)