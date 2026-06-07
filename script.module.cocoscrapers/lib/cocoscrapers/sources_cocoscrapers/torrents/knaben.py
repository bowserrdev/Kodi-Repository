# -*- coding: utf-8 -*-

import re
from json import dumps as jsdumps, loads as jsloads
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_API_URL = 'https://api.knaben.org/v1'
_BTIH_RE = re.compile(r'btih:([0-9a-fA-F]{40})', re.I)
_JSON_HEADERS = {'Content-Type': 'application/json'}


class source(BaseTorrentScraper):
	priority = 3
	pack_capable = True
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.min_seeders = 0

	@staticmethod
	def _build_payload(query, size=300):
		return jsdumps({
			'search_type': '100%',
			'search_field': 'title',
			'query': query,
			'order_by': 'seeders',
			'order_direction': 'desc',
			'size': size,
			'hide_unsafe': True,
			'hide_xxx': True
		})

	@staticmethod
	def _parse_hit(hit):
		try:
			hash = hit.get('hash')
			magnet_url = hit.get('magnetUrl')
			if not hash and magnet_url:
				m = _BTIH_RE.search(magnet_url)
				if m:
					hash = m.group(1)
			if not hash:
				return None
			name = source_utils.clean_name(hit.get('title', ''))
			if not name:
				return None
			seeders = hit.get('seeders') or 0
			try:
				sb = int(hit.get('bytes', 0))
				if sb >= 1024 ** 3:
					dsize, isize = source_utils._size('%.2f GB' % (sb / 1024.0 ** 3))
				elif sb > 0:
					dsize, isize = source_utils._size('%.2f MB' % (sb / 1024.0 ** 2))
				else:
					dsize, isize = 0, ''
			except:
				dsize, isize = 0, ''
			magnet = magnet_url if magnet_url else 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, quote_plus(name))
			return hash, name, seeders, dsize, isize, magnet
		except:
			return None

	def _fetch_hits(self, query):
		try:
			result = client.request(_API_URL, post=self._build_payload(query),
									headers=_JSON_HEADERS, timeout=10)
			if not result:
				return []
			return jsloads(result).get('hits', [])
		except:
			source_utils.scraper_error('KNABEN')
			return []

	def _get_sources(self, query):
		for hit in self._fetch_hits(query):
			try:
				parsed = self._parse_hit(hit)
				if not parsed:
					continue
				hash, name, seeders, dsize, isize, magnet = parsed
				if self.min_seeders > seeders:
					continue
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years):
					continue
				if not self.episode_title and self._is_episode_result(name):
					continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					continue
				self._append_result(self._build_result('knaben', hash, name, name_info, magnet, seeders, dsize, isize))
			except:
				source_utils.scraper_error('KNABEN')

	def _get_sources_packs(self, query):
		for hit in self._fetch_hits(query):
			try:
				parsed = self._parse_hit(hit)
				if not parsed:
					continue
				hash, name, seeders, dsize, isize, magnet = parsed
				if self.min_seeders > seeders:
					continue

				episode_start, episode_end, last_season = 0, 0, None
				if not self._search_series:
					if not self._bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid:
							continue
					package = 'season'
				else:
					if not self._bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, self.imdb, self.year, self.season_x, name, self._total_seasons)
						if not valid:
							continue
					else:
						last_season = self._total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					continue
				self._append_result(self._build_pack_result(
					'knaben', hash, name, name_info, magnet, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, self._search_series))
			except:
				source_utils.scraper_error('KNABEN')

	def sources(self, data, hostDict):
		self._reset()
		if not data:
			return self._results
		try:
			is_tv = 'tvshowtitle' in data
			if is_tv:
				self._init_episode_data(data)
				hdlr_search = 'S%s' % self.season_xx
			else:
				self._init_movie_data(data)
				hdlr_search = self.hdlr
			self._init_filters()
			queries = []
			for st in self.search_titles:
				st_clean = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st).strip()
				if st_clean:
					queries.append('%s %s' % (st_clean, hdlr_search))
			queries = list(dict.fromkeys(queries))
			log_utils.log('KNABEN queries: %s' % queries)
		except:
			source_utils.scraper_error('KNABEN')
			return self._results

		self._run_threads(self._get_sources, queries)
		self._log_stats('KNABEN')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data:
			return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			self._search_series = search_series
			self._total_seasons = total_seasons
			self._bypass_filter = bypass_filter
			queries = []
			for st in self.search_titles:
				base = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st).strip()
				if not base:
					continue
				if search_series:
					queries += ['%s Season' % base, '%s Complete' % base]
				else:
					queries += ['%s S%s' % (base, self.season_xx), '%s Season %s' % (base, self.season_x)]
			queries = list(dict.fromkeys(queries))
		except:
			source_utils.scraper_error('KNABEN')
			return self._results

		self._run_threads(self._get_sources_packs, queries)
		self._log_stats('KNABEN', pack=True)
		return self._results