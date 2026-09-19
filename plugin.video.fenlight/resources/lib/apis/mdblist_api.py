# -*- coding: utf-8 -*-
from caches.lists_cache import lists_cache_object
from modules.settings import mdblist_api_key
from modules.kodi_utils import notification

# Vedi trakt_api (lotto 51): 'requests' e la Session nascono alla prima richiesta, non all'import.
# Qui pesava su ogni costruzione di lista mdblist, cioe' su tre dei quattro widget dell'avvio.
_session = [None]

def _get_session():
	if _session[0] is None:
		from modules.kodi_utils import import_requests
		_session[0] = import_requests('mdblist_api').Session()
	return _session[0]
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
		resp = _get_session().get(API_ENDPOINT % endpoint, params=params, timeout=timeout)
		resp.raise_for_status()
		return resp.json()
	except: return None

# L'ELENCO delle liste (mie e piaciute) si scarica a ogni apertura, senza cache. Stava in main_cache per
# un'ora come i contenuti, ma a differenza di Trakt MDBList non ha un segnale di attivita' che la
# invalidi: una lista appena piaciuta sul sito restava invisibile fino alla scadenza. E' una chiamata
# sola, fatta solo quando l'utente apre la cartella; la cache resta sui contenuti delle liste.
def mdblist_get_my_lists():
	return call_mdblist('lists/user/') or []

def mdblist_get_liked_lists():
	data = call_mdblist('lists/liked/')
	if isinstance(data, dict): return data.get('lists') or []
	return data or []

# Liste che vanno ordinate per data di aggiunta (date added, dal piu' recente) invece che per rank
MDBLIST_DATE_ADDED_LISTS = {'91378'}  # amything/latest-releases-gary

def mdblist_get_list_contents(list_id):
	def _process(lid):
		params = {'unified': 'true', 'limit': 1000}
		by_date_added = str(lid) in MDBLIST_DATE_ADDED_LISTS
		if by_date_added: params.update({'sort': 'added', 'order': 'asc'})
		raw = call_mdblist('lists/%s/items/' % lid, params=params)
		# DUE ESITI CHE SI SOMIGLIANO E NON VANNO CONFUSI (lotto 120). call_mdblist torna None per
		# QUALUNQUE eccezione -- timeout, 5xx, limite di frequenza, DNS -- e una lista vuota quando la
		# lista e' davvero vuota. Finche' i due finivano insieme in 'return []', un singolo errore di
		# rete veniva messo in cache per 24 ore come se fosse la risposta giusta: il widget restava
		# 'nessun risultato' per un giorno intero, sullo stesso account su cui gli altri dispositivi
		# vedevano la lista piena. Misurato sulla stick il 01/09: 'mdblist_list_contents_2194' con due
		# byte di dati ('[]') scritti alle 14:17 e validi fino alle 14:17 del giorno dopo, mentre sul
		# Mac la stessa lista rispondeva 300 elementi.
		# None risale fino a lists_cache_object, che NON mette in cache i fallimenti: il giro dopo si
		# riprova. La lista vuota vera resta una risposta e continua a essere memorizzata.
		if raw is None: return None
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
	# 'or []': i chiamanti fanno len() su questo valore e non devono conoscere la distinzione fra
	# fallimento e lista vuota -- a loro serve solo una lista. La distinzione e' servita alla cache.
	results = lists_cache_object(_process, 'mdblist_list_contents_%s' % list_id, list_id, False, 24) or []
	# LISTE SENZA RANK (lotto 301). Le liste statiche non classificate ('A24', 'Psychological
	# Thrillers') hanno "rank": null su ogni elemento: get('rank', 0) rende il default solo se la chiave
	# manca, quindi l'ordine era None. La build ordina per quel valore, None < None e' un TypeError, e
	# l'except di build_mdblist_list consegnava una cartella vuota: 'nessun risultato' su una lista da
	# 181 elementi. Basta un None per rompere l'ordinamento, quindi in quel caso vale la posizione data
	# dall'API per tutti. Si corregge DOPO la cache e non dentro _process: le voci scritte dal codice
	# vecchio restano valide 24 ore, e il widget non deve aspettare che scadano.
	if any(i.get('order') is None for i in results):
		for idx, i in enumerate(results): i['order'] = idx
	return results