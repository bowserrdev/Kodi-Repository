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

	def _get(self, url, params, headers, use_proxy=False):
		try:
			if use_proxy and self._proxy:
				proxies = {'http': self._proxy, 'https': self._proxy}
				resp = requests.Session().get(url, params=params, headers=headers, timeout=(2, 15), proxies=proxies)
			else:
				resp = _session.get(url, params=params, headers=headers, timeout=(2, 15))
			if resp.status_code == 429:
				if use_proxy or not self._proxy:
					log_utils.log('DMM: 429, stopping pagination')
					return None
				return self._get(url, params, headers, use_proxy=True)
			if not resp.ok:
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

		def _fetch_proxy(page, out):
			proxies = {'http': self._proxy, 'https': self._proxy}
			try:
				resp = requests.Session().get(api_url, params=_build_params(page), headers=headers,
											  timeout=(2, 15), proxies=proxies)
				data = resp.json() if resp.ok else None
			except:
				data = None
			if data:
				out.extend(r for r in data.get('results', []) if r.get('hash'))

		page0 = []
		data0 = self._get(api_url, _build_params(0), headers)
		if data0:
			page0.extend(r for r in data0.get('results', []) if r.get('hash'))

		if len(page0) < 30 or not self._proxy:
			return page0

		page1, page2 = [], []
		t1 = Thread(target=_fetch_proxy, args=(1, page1))
		t2 = Thread(target=_fetch_proxy, args=(2, page2))
		t1.start(); t2.start()
		t1.join(); t2.join()
		return page0 + page1 + page2

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

		for item in files:
			try:
				hash, name, seeders, dsize, isize, url = self._parse_item(item)
				if not name or not hash: continue
				if self.min_seeders > seeders: continue
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				if not self.episode_title and self._is_episode_result(name): continue
				self._results.append(self._build_result('dmm', hash, name, name_info, url, seeders, dsize, isize))
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

		for item in files:
			try:
				hash, name, seeders, dsize, isize, url = self._parse_item(item)
				if not name or not hash: continue
				if self.min_seeders > seeders: continue

				episode_start, episode_end, last_season = 0, 0, None
				if not search_series:
					if not bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid: continue
					package = 'season'
				else:
					if not bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, imdb, self.year, self.season_x, name, total_seasons)
						if not valid: continue
					else:
						last_season = total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue

				self._results.append(self._build_pack_result(
					'dmm', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, search_series))
			except:
				source_utils.scraper_error('DMM')

		self._log_stats('DMM', pack=True)
		return self._results