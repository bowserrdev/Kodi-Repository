# -*- coding: utf-8 -*-

import time
import requests
from threading import Thread, Lock
from cocoscrapers.modules import source_utils, log_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_session = requests.Session()
_BASE_URL = 'https://debridmediamanager.com'
_HEADERS = {
	'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
	'Accept': 'application/json, text/plain, */*',
	'Accept-Language': 'en-US,en;q=0.9',
	'Origin': 'https://debridmediamanager.com',
	'Sec-Fetch-Dest': 'empty',
	'Sec-Fetch-Mode': 'cors',
	'Sec-Fetch-Site': 'same-origin',
}


_CHALLENGE_URL = '%s/api/challenge' % _BASE_URL
# Il client del sito rinnova a 120s; stiamo sotto per non correre sul filo.
_CHALLENGE_TTL = 90

# Lotto 374: le pagine chieste, tutte insieme (0-10, le stesse di prima). Nella passata del 26/09 la pagina 10 era ancora
# piena in 86 ricerche su 208: alzarle e' una scelta a parte (piu' fonti, piu' lettura sulla stick).
PAGINE = 11

_challenge_lock = Lock()
_challenge_cache = {}


def _get_challenge(proxy=None):
	"""Restituisce (dmmProblemKey, solution) chiesti a /api/challenge.

	Da agosto 2026 DMM non usa piu' una proof-of-work calcolabile in locale: il
	`solution` e' un hash firmato dal server. Il token NON e' legato all'IP ne'
	alla sessione, quindi uno solo vale per tutte le pagine e per tutti gli IP
	del proxy rotante: va chiesto una volta e riusato.
	"""
	with _challenge_lock:
		cached = _challenge_cache.get('data')
		if cached and time.time() < cached[2]:
			return cached[0], cached[1]
		# Diretta prima: misurata ~0,23s contro ~0,75s via proxy.
		attempts = [None, proxy] if proxy else [None]
		for attempt_proxy in attempts:
			try:
				proxies = {'http': attempt_proxy, 'https': attempt_proxy} if attempt_proxy else None
				resp = _session.get(_CHALLENGE_URL, headers=_HEADERS, timeout=(2, 15), proxies=proxies)
				if not resp.ok:
					log_utils.log('DMM challenge HTTP %s proxy=%s' % (resp.status_code, bool(attempt_proxy)))
					continue
				data = resp.json()
				key, solution = data.get('token'), data.get('hash')
				if not key or not solution:
					log_utils.log('DMM challenge malformato: %s' % str(data)[:200])
					continue
				_challenge_cache['data'] = (key, solution, time.time() + _CHALLENGE_TTL)
				return key, solution
			except:
				source_utils.scraper_error('DMM')
		return None, None


class source(BaseTorrentScraper):
	priority = 1
	pack_capable = True
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.min_seeders = 0
		proxy = getSetting('proxy.url') if getSetting('proxy.enabled') == 'true' else None
		self._proxy = proxy if proxy else None
		# Fen Light, 28/09: l'indirizzo del proxy porta le credenziali, nel log va solo se e' attivo
		log_utils.log('DMM proxy — enabled: "%s" active: %s' % (getSetting('proxy.enabled'), bool(self._proxy)))

	def _get(self, url, params, headers, use_proxy=False):
		try:
			page = params.get('page', '?')
			if use_proxy and self._proxy:
				proxies = {'http': self._proxy, 'https': self._proxy}
				# lotto 374: la sessione si chiude subito (11 pagine insieme; Kodi sul Mac ha 256 descrittori)
				with requests.Session() as sessione:
					resp = sessione.get(url, params=params, headers=headers, timeout=(2, 15), proxies=proxies)
			else:
				resp = _session.get(url, params=params, headers=headers, timeout=(2, 15))
			if resp.status_code == 429:
				if use_proxy or not self._proxy:
					log_utils.log('DMM: 429 page=%s proxy=%s, stopping pagination' % (page, use_proxy))
					return None
				return self._get(url, params, headers, use_proxy=True)
			if not resp.ok:
				log_utils.log('DMM HTTP %s page=%s proxy=%s' % (resp.status_code, page, use_proxy))
				return None
			return resp.json()
		except:
			source_utils.scraper_error('DMM')
			return None

	def _fetch_pages(self, imdb_id, api_type, season=None):
		api_url = '%s/api/torrents/%s' % (_BASE_URL, api_type)
		frontend_type = 'show' if api_type == 'tv' else 'movie'
		ref_url = '%s/%s/%s' % (_BASE_URL, frontend_type, imdb_id)
		if api_type == 'tv' and season:
			ref_url += '/%s' % season
		headers = dict(_HEADERS)
		headers['Referer'] = ref_url

		def _build_params(page):
			key, solution = _get_challenge(self._proxy)
			if not key:
				return None
			p = {'imdbId': imdb_id, 'dmmProblemKey': key, 'solution': solution,
				 'onlyTrusted': 'false', 'maxSize': 0, 'page': page}
			if api_type == 'tv' and season is not None:
				p['seasonNum'] = season
			return p

		def _fetch_page(page, retries=1):
			for attempt in range(retries + 1):
				params = _build_params(page)
				if params is None:
					log_utils.log('DMM page %s: nessun token di challenge' % page)
					return None
				data = self._get(api_url, params, headers, use_proxy=bool(self._proxy))
				if data is not None:
					raw_count = len(data.get('results', []))
					page_results = []
					for item in data.get('results', []):
						if not item.get('hash'):
							continue
						item = dict(item)
						item['_dmm_page'] = page
						page_results.append(item)
					log_utils.log('DMM page %s raw results: %s (%s with hash) for imdb: %s' % (
						page, raw_count, len(page_results), imdb_id))
					return page_results
				if attempt < retries:
					log_utils.log('DMM page %s failed, retrying' % page)
			log_utils.log('DMM page %s failed after retries for imdb: %s' % (page, imdb_id))
			return None

		results = []
		if not _get_challenge(self._proxy)[0]:
			log_utils.log('DMM: challenge non ottenibile, ricerca annullata')
			return results
		if not self._proxy:
			# direttamente DMM concede una richiesta, poi 429
			log_utils.log('DMM: no proxy configured, page 0 only')
			return _fetch_page(0) or results

		# LOTTO 374 (SORGENTI.md) -- le PAGINE partono insieme. Prima: pagina 0, poi 1-4, 5-7, 8-10 in tre ondate, ognuna
		# ferma sulla piu' lenta (~1 s a ondata via proxy, ~4 s in tutto). Sono le stesse pagine di prima: una pagina oltre
		# la fine e' solo una risposta vuota. I risultati si uniscono in ordine di pagina, come prima.
		esiti = [None] * PAGINE

		def _una(idx):
			esiti[idx] = _fetch_page(idx)

		threads = [Thread(target=_una, args=(idx,)) for idx in range(PAGINE)]
		[t.start() for t in threads]
		[t.join() for t in threads]
		for page_result in esiti:
			if page_result:
				results += page_result
		log_utils.log('DMM pages 0-%s raw results: %s (%s pages with results) for imdb: %s' % (
			PAGINE - 1, len(results), sum(1 for e in esiti if e), imdb_id))
		return results

	@staticmethod
	def _leggi(item):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base). `raw`: il titolo prima di
		clean_name, per gli alias non latini."""
		raw = item.get('title') or item.get('filename') or item.get('name') or ''
		hash = (item.get('hash') or '').lower()
		name = source_utils.clean_name(raw)
		size_mb = float(item.get('fileSize') or 0)
		dsize, isize = source_utils._size('%.2f MB' % size_mb) if size_mb else (0, '')
		return {'hash': hash, 'name': name, 'url': source._magnet(hash, name), 'seeders': 0, 'dsize': dsize,
				'isize': isize, 'raw': raw}

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		is_tv = 'tvshowtitle' in data
		files = []
		try:
			if is_tv:
				self._init_episode_data(data)
				api_type, season = 'tv', self.season_x
			else:
				self._init_movie_data(data)
				api_type, season = 'movie', None
			self._init_filters()
			# lotto 411: le pagine valgono anche per i pacchetti della stessa ricerca (_condivisa)
			files = self._condivisa((data['imdb'], api_type, season), lambda: self._fetch_pages(data['imdb'], api_type, season))
		except:
			source_utils.scraper_error('DMM')

		log_utils.log('DMM: %s raw results for "%s" (imdb=%s)' % (len(files), self.title, data.get('imdb', '?')))
		self._valuta_tutti(files, self._leggi)

		self._log_stats('DMM')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data, search_series, total_seasons, bypass_filter)
			self._init_filters()
			# lotto 411: le stesse pagine della ricerca dell'episodio, o chieste qui se l'episodio era gia' in cache
			files = self._condivisa((data['imdb'], 'tv', self.season_x), lambda: self._fetch_pages(data['imdb'], 'tv', self.season_x))
		except:
			source_utils.scraper_error('DMM')
			self._log_stats('DMM', pack=True)
			return self._results

		log_utils.log('DMM packs: %s raw results for "%s"' % (len(files), self.title))
		self._valuta_tutti(files, self._leggi, pacchetti=True)

		self._log_stats('DMM', pack=True)
		return self._results
