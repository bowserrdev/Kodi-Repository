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
		self._headers = {'Accept-Language': 'en-US,en;q=0.9'}

	@staticmethod
	def _fetch_rows(page_url, headers):
		try:
			results = client.request(page_url, timeout=7, headers=headers)
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
		rows = self._fetch_rows(page_url, self._headers)
		log_utils.log('BITSEARCH page "%s": %s rows' % (page_url, len(rows)))
		for row in rows:
			try:
				parsed = self._parse_row(row)
				if not parsed: continue
				url, hash, name, seeders, dsize, isize = parsed
				if not name or not hash: continue
				log_utils.log('BITSEARCH RAW: "%s" | hash=%s | seeders=%s' % (name, hash, seeders))
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year):
					log_utils.log('BITSEARCH SKIP [title mismatch]: "%s"' % name)
					continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('BITSEARCH SKIP [undesirable tag]: "%s"' % name)
					continue
				if not self.episode_title and self._is_episode_result(name):
					log_utils.log('BITSEARCH SKIP [episode in movie search]: "%s"' % name)
					continue
				if self.min_seeders > seeders:
					log_utils.log('BITSEARCH SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue
				log_utils.log('BITSEARCH KEPT: "%s" | hash=%s' % (name, hash))
				self._results.append(self._build_result('bitsearch', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('BITSEARCH')

	def get_sources_packs(self, link):
		rows = self._fetch_rows(link, self._headers)
		log_utils.log('BITSEARCH pack page "%s": %s rows' % (link, len(rows)))
		for row in rows:
			try:
				parsed = self._parse_row(row)
				if not parsed: continue
				url, hash, name, seeders, dsize, isize = parsed
				if not name or not hash: continue
				if self.min_seeders > seeders: continue

				episode_start, episode_end, last_season = 0, 0, None
				if not self.search_series:
					if not self.bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid:
							log_utils.log('BITSEARCH SKIP [filter_season_pack]: "%s"' % name)
							continue
					package = 'season'
				else:
					if not self.bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, self.imdb, self.year, self.season_x, name, self.total_seasons)
						if not valid:
							log_utils.log('BITSEARCH SKIP [filter_show_pack]: "%s"' % name)
							continue
					else: last_season = self.total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('BITSEARCH SKIP [undesirable tag]: "%s"' % name)
					continue

				log_utils.log('BITSEARCH KEPT (pack=%s): "%s" | hash=%s' % (package, name, hash))
				self._results.append(self._build_pack_result(
					'bitsearch', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, self.search_series))
			except:
				source_utils.scraper_error('BITSEARCH')

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		try:
			is_tv = 'tvshowtitle' in data
			if is_tv: self._init_episode_data(data)
			else: self._init_movie_data(data)
			self._init_filters()
			cat = '3' if is_tv else '2'
			pages = []
			for idx, st in enumerate(self.search_titles):
				q = '%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', st), self.hdlr)
				base = '%s%s&category=%s' % (self.base_link, self.search_link % quote_plus(q), cat)
				log_utils.log('BITSEARCH query[%s]: %s' % (idx, base))
				pages.append(base)
				if idx == 0:
					pages += [base + '&page=%s' % p for p in range(2, 5)]
			self._run_threads(self.get_sources, list(dict.fromkeys(pages)))
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

			queries = []
			for st in self.search_titles:
				q = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st)
				if search_series:
					queries += [q + ' Season', q + ' Complete']
				else:
					queries += [q + ' S%s' % self.season_xx, q + ' Season %s' % self.season_x]
			links = list(dict.fromkeys(['%s%s&category=3' % (self.base_link, self.search_link % quote_plus(q)) for q in queries]))
			for lnk in links:
				log_utils.log('BITSEARCH pack query: %s' % lnk)
			self._run_threads(self.get_sources_packs, links)
		except:
			source_utils.scraper_error('BITSEARCH')
		self._log_stats('BITSEARCH', pack=True)
		return self._results