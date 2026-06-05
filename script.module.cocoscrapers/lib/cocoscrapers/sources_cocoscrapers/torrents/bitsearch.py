# -*- coding: utf-8 -*-

import re
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper


class source(BaseTorrentScraper):
	priority = 3
	pack_capable = True
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.base_link = 'https://bitsearch.to'
		self.search_link = '/search?q=%s&sort=size'
		self.min_seeders = 0

	@staticmethod
	def _fetch_rows(page_url):
		try:
			results = client.request(page_url, timeout=7)
			if not results or '/torrent/' not in results: return []
			cards = re.split(r'<div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6', results)
			return [c for c in cards[1:] if 'magnet:' in c]
		except:
			source_utils.scraper_error('BITSEARCH')
			return []

	@staticmethod
	def _parse_row(row):
		try:
			if 'magnet:' not in row: return None
			hash_match = re.search(r'/download/torrent/([A-F0-9]{40})', row, re.I)
			if not hash_match: return None
			hash = hash_match.group(1).lower()
			name_match = re.search(r'href="/torrent/[^"]+"[^>]*>\s*(.*?)\s*</a>', row, re.DOTALL)
			if not name_match: return None
			name = source_utils.clean_name(name_match.group(1).strip())
			url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
			try:
				s = re.search(r'text-green-600[^>]*>.*?<span class="font-medium">(\d+)</span>', row, re.DOTALL)
				seeders = int(s.group(1)) if s else 0
			except: seeders = 0
			try:
				sz = re.search(r'([\d.,]+\s*(?:GB|MB|TB|GiB|MiB))', row)
				dsize, isize = source_utils._size(sz.group(1).strip()) if sz else (0, '')
			except: dsize, isize = 0, ''
			return url, hash, name, seeders, dsize, isize
		except: return None

	def get_sources(self, page_url):
		for row in self._fetch_rows(page_url):
			try:
				parsed = self._parse_row(row)
				if not parsed: continue
				url, hash, name, seeders, dsize, isize = parsed
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				if not self.episode_title and self._is_episode_result(name): continue
				if self.min_seeders > seeders: continue
				self._results.append(self._build_result('bitsearch', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('BITSEARCH')

	def get_sources_packs(self, link):
		for row in self._fetch_rows(link):
			try:
				parsed = self._parse_row(row)
				if not parsed: continue
				url, hash, name, seeders, dsize, isize = parsed
				if self.min_seeders > seeders: continue

				episode_start, episode_end, last_season = 0, 0, None
				if not self.search_series:
					if not self.bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid: continue
					package = 'season'
				else:
					if not self.bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, self.imdb, self.year, self.season_x, name, self.total_seasons)
						if not valid: continue
					else: last_season = self.total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue

				self._results.append(self._build_pack_result(
					'bitsearch', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, self.search_series))
			except:
				source_utils.scraper_error('BITSEARCH')

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		try:
			if 'tvshowtitle' in data: self._init_episode_data(data)
			else: self._init_movie_data(data)
			self._init_filters()
			query = '%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', self.title), self.hdlr)
			base_url = '%s%s' % (self.base_link, self.search_link % quote_plus(query))
			self._run_threads(self.get_sources, [base_url, base_url + '&page=2'])
		except:
			source_utils.scraper_error('BITSEARCH')
		self._log_stats('BITSEARCH')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			self.search_series = search_series
			self.total_seasons = total_seasons
			self.bypass_filter = bypass_filter

			query = re.sub(r'[^A-Za-z0-9\s\.-]+', '', self.title)
			if search_series:
				queries = [query + ' Season', query + ' Complete']
			else:
				queries = [query + ' S%s' % self.season_xx, query + ' Season %s' % self.season_x]
			links = ['%s%s' % (self.base_link, self.search_link % quote_plus(q)) for q in queries]
			self._run_threads(self.get_sources_packs, links)
		except:
			source_utils.scraper_error('BITSEARCH')
		self._log_stats('BITSEARCH', pack=True)
		return self._results