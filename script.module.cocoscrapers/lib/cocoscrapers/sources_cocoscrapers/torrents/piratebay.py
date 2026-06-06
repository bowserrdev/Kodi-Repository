# -*- coding: utf-8 -*-

import re
from json import loads as jsloads
from urllib.parse import quote
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper


class source(BaseTorrentScraper):
	priority = 2
	pack_capable = True
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.base_link = 'https://apibay.org'
		self.search_link = '/q.php?q=%s&cat=0'
		self.min_seeders = 0

	def _fetch(self, url):
		try:
			results = client.request(url, output='extended', timeout=5)
			if not results: return []
			if results[1] not in ('200', '201'):
				log_utils.log('PIRATEBAY: Failed query (%s): %s' % (url, results))
				return []
			return jsloads(results[0])
		except:
			source_utils.scraper_error('PIRATEBAY')
			return []

	def get_sources(self, url):
		files = self._fetch(url)
		for file in files:
			try:
				hash = file['info_hash']
				name = source_utils.clean_name(file['name'])
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				if not self.episode_title and self._is_episode_result(name): continue
				url_magnet = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
				try: seeders = int(file['seeders'])
				except: seeders = 0
				if self.min_seeders > seeders: continue
				try: dsize, isize = source_utils.convert_size(float(file['size']), to='GB')
				except: dsize, isize = 0, ''
				self._results.append(self._build_result('piratebay', hash, name, name_info, url_magnet, seeders, dsize, isize))
			except:
				source_utils.scraper_error('PIRATEBAY')

	def get_sources_packs(self, link):
		files = self._fetch(link)
		for file in files:
			try:
				hash = file['info_hash']
				name = source_utils.clean_name(file['name'])

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
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue

				url_magnet = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
				try: seeders = int(file['seeders'])
				except: seeders = 0
				if self.min_seeders > seeders: continue
				try: dsize, isize = source_utils.convert_size(float(file['size']), to='GB')
				except: dsize, isize = 0, ''

				self._results.append(self._build_pack_result(
					'piratebay', hash, name, name_info, url_magnet, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, self.search_series))
			except:
				source_utils.scraper_error('PIRATEBAY')

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		try:
			if 'tvshowtitle' in data: self._init_episode_data(data)
			else: self._init_movie_data(data)
			self.title = self.title.replace('·', '-')
			self._init_filters()
			links = list(dict.fromkeys([
				'%s%s' % (self.base_link, self.search_link % quote('%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', t), self.hdlr)))
				for t in self.search_titles]))
			self._run_threads(self.get_sources, links)
		except:
			source_utils.scraper_error('PIRATEBAY')
		self._log_stats('PIRATEBAY')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data)
			self.title = self.title.replace('·', '-')
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
			links = list(dict.fromkeys(['%s%s' % (self.base_link, self.search_link % quote(q)) for q in queries]))
			self._run_threads(self.get_sources_packs, links)
		except:
			source_utils.scraper_error('PIRATEBAY')
		self._log_stats('PIRATEBAY', pack=True)
		return self._results