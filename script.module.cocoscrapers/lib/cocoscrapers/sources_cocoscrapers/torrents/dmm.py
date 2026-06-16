# -*- coding: utf-8 -*-

import math
import time
import secrets
import requests
import queue as queue_module
from threading import Thread
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


class _DMMCrypto:
	SALT = 'debridmediamanager.com%%fe7#td00rA3vHz%VmI'

	@staticmethod
	def _js_imul(a, b):
		return (a * b) & 0xFFFFFFFF

	@staticmethod
	def _urshift(val, n):
		return (val & 0xFFFFFFFF) >> n

	@staticmethod
	def _hash_func(s):
		i = 0xdeadbeef ^ len(s)
		t = 0x41c6ce57 ^ len(s)
		for ch in s:
			l = ord(ch)
			xi = _DMMCrypto._js_imul(i ^ l, 0x9e3779b1)
			i = ((xi << 5) & 0xFFFFFFFF | _DMMCrypto._urshift(xi, 27)) & 0xFFFFFFFF
			xt = _DMMCrypto._js_imul(t ^ l, 0x5f356495)
			t = ((xt << 5) & 0xFFFFFFFF | _DMMCrypto._urshift(xt, 27)) & 0xFFFFFFFF
		i = (i + _DMMCrypto._js_imul(t, 0x5d588b65)) & 0xFFFFFFFF
		t = (t + _DMMCrypto._js_imul(i, 0x78a76a79)) & 0xFFFFFFFF
		return format(_DMMCrypto._urshift(i ^ t, 0), 'x')

	@staticmethod
	def solve():
		rand_hex = format(secrets.randbits(32), 'x')
		key = '%s-%s' % (rand_hex, int(time.time()))
		ha = _DMMCrypto._hash_func(key)
		hb = _DMMCrypto._hash_func('%s-%s' % (_DMMCrypto.SALT, rand_hex))
		half = math.floor(len(ha) / 2)
		interleaved = ''.join(ha[x] + hb[x] for x in range(half))
		return key, interleaved + hb[half:][::-1] + ha[half:][::-1]


class source(BaseTorrentScraper):
	priority = 1
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	_queue = queue_module.SimpleQueue()

	def __init__(self):
		super().__init__()
		self.min_seeders = 0
		proxy = getSetting('proxy.url') if getSetting('proxy.enabled') == 'true' else None
		self._proxy = proxy if proxy else None
		log_utils.log('DMM proxy — enabled: "%s" url: "%s" active: "%s"' % (
    		getSetting('proxy.enabled'), getSetting('proxy.url'), str(self._proxy)))

	def _get(self, url, params, headers, use_proxy=False):
		try:
			page = params.get('page', '?')
			if use_proxy and self._proxy:
				proxies = {'http': self._proxy, 'https': self._proxy}
				resp = requests.Session().get(url, params=params, headers=headers, timeout=(2, 15), proxies=proxies)
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
			key, solution = _DMMCrypto.solve()
			p = {'imdbId': imdb_id, 'dmmProblemKey': key, 'solution': solution,
				 'onlyTrusted': 'false', 'maxSize': 0, 'page': page}
			if api_type == 'tv' and season is not None:
				p['seasonNum'] = season
			return p

		def _fetch_page(page, retries=1):
			for attempt in range(retries + 1):
				data = self._get(api_url, _build_params(page), headers, use_proxy=bool(self._proxy))
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
		page_results = _fetch_page(0)
		if page_results is None:
			log_utils.log('DMM pagination stopped on failed page: 0')
			return results
		results += page_results
		if not self._proxy:
			log_utils.log('DMM pagination stopped after page 0: no proxy configured')
			return results

		# Batch a dimensione predefinita: 5 + 3 + 3 = max 11 pagine totali (pagina 0 inclusa).
		# Primo batch da 4 (pagine 1-4) per completare le 5 pagine iniziali, poi batch da 3.
		batch_sizes = [4, 3, 3]
		page = 1
		for batch_size in batch_sizes:
			pages = list(range(page, page + batch_size))
			batch_results = [None] * len(pages)

			def _fetch_batch_page(idx, batch_page):
				batch_results[idx] = _fetch_page(batch_page)

			threads = [Thread(target=_fetch_batch_page, args=(idx, batch_page)) for idx, batch_page in enumerate(pages)]
			[t.start() for t in threads]
			[t.join() for t in threads]

			batch_total = sum(len(page_result or []) for page_result in batch_results)
			log_utils.log('DMM batch pages %s-%s raw results: %s for imdb: %s' % (
				pages[0], pages[-1], batch_total, imdb_id))
			if batch_total == 0:
				log_utils.log('DMM pagination stopped on empty batch: pages %s-%s' % (pages[0], pages[-1]))
				break
			for page_result in batch_results:
				if page_result:
					results += page_result
			page += batch_size
		return results

	@staticmethod
	def _parse_item(item):
		hash = (item.get('hash') or '').lower()
		name = source_utils.clean_name(
			item.get('title') or item.get('filename') or item.get('name') or '')
		seeders = 0
		size_mb = float(item.get('fileSize') or 0)
		dsize, isize = source_utils._size('%.2f MB' % size_mb) if size_mb else (0, '')
		url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
		return hash, name, seeders, dsize, isize, url

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
			files = self._fetch_pages(data['imdb'], api_type, season)
		except:
			source_utils.scraper_error('DMM')
		finally:
			if is_tv:
				self._queue.put_nowait(files)
				self._queue.put_nowait(files)

		log_utils.log('DMM: %s raw results for "%s" (imdb=%s)' % (len(files), self.title, data.get('imdb', '?')))
		for item in files:
			try:
				raw_title = item.get('title') or item.get('filename') or item.get('name') or ''
				page = item.get('_dmm_page', '?')
				log_utils.log('DMM RAW page=%s: raw="%s" | hash=%s | fileSize=%s' % (
					page, raw_title, item.get('hash', '?'), item.get('fileSize', '?')))
				hash, name, seeders, dsize, isize, url = self._parse_item(item)
				if not name or not hash:
					log_utils.log('DMM SKIP [empty after clean_name] raw="%s"' % raw_title)
					continue
				log_utils.log('DMM PARSED page=%s: "%s" | hash=%s | size=%s' % (page, name, hash, isize or '?'))
				if self.min_seeders > seeders:
					log_utils.log('DMM SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years):
					if not self._check_title_raw(raw_title):
						log_utils.log('DMM SKIP [title mismatch]: "%s"' % name)
						continue
					log_utils.log('DMM KEPT [non-ASCII title]: "%s"' % raw_title)
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('DMM SKIP [language filter]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('DMM SKIP [undesirable tag]: "%s"' % name)
					continue
				if not self.episode_title and self._is_episode_result(name):
					log_utils.log('DMM SKIP [episode in movie search]: "%s"' % name)
					continue
				log_utils.log('DMM KEPT: "%s" | hash=%s' % (name, hash))
				self._append_result(self._build_result('dmm', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('DMM')

		self._log_stats('DMM')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			imdb = data['imdb']
			files = self._queue.get(timeout=12)
		except:
			source_utils.scraper_error('DMM')
			self._log_stats('DMM', pack=True)
			return self._results

		log_utils.log('DMM packs: %s raw results for "%s"' % (len(files), self.title))
		for item in files:
			try:
				raw_title = item.get('title') or item.get('filename') or item.get('name') or ''
				page = item.get('_dmm_page', '?')
				log_utils.log('DMM RAW PACK page=%s: raw="%s" | hash=%s | fileSize=%s' % (
					page, raw_title, item.get('hash', '?'), item.get('fileSize', '?')))
				hash, name, seeders, dsize, isize, url = self._parse_item(item)
				if not name or not hash:
					log_utils.log('DMM SKIP [empty after clean_name] raw="%s"' % raw_title)
					continue
				if self.min_seeders > seeders:
					log_utils.log('DMM SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue

				episode_start, episode_end, last_season = 0, 0, None
				if not search_series:
					if not bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid:
							log_utils.log('DMM SKIP [filter_season_pack]: "%s"' % name)
							continue
					package = 'season'
				else:
					if not bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, imdb, self.year, self.season_x, name, total_seasons)
						if not valid:
							log_utils.log('DMM SKIP [filter_show_pack]: "%s"' % name)
							continue
					else:
						last_season = total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('DMM SKIP [language filter]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('DMM SKIP [undesirable tag]: "%s"' % name)
					continue

				log_utils.log('DMM KEPT (pack=%s): "%s" | hash=%s' % (package, name, hash))
				self._append_result(self._build_pack_result(
					'dmm', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, search_series))
			except:
				source_utils.scraper_error('DMM')

		self._log_stats('DMM', pack=True)
		return self._results
