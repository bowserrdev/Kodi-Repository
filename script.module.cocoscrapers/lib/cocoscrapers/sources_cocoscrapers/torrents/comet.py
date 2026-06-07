# -*- coding: utf-8 -*-

import re
import queue as queue_module
from json import loads as jsloads
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
_SEEDERS_RE = re.compile(r'👤\s*(\d+)')
_DEFAULT_BASE = 'https://comet.elfhosted.com'


class source(BaseTorrentScraper):
	priority = 2
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	_queue = queue_module.SimpleQueue()

	def __init__(self):
		super().__init__()
		self.min_seeders = 0
		userdata = getSetting('comet.userdata')
		if getSetting('comet.usecustomurl') == 'true':
			base = getSetting('comet.customurl').rstrip('/') or _DEFAULT_BASE
		else:
			base = _DEFAULT_BASE
		self.stream_base = '%s/%s' % (base, userdata) if userdata else None
		self.movieSearch_link = '/stream/movie/%s.json'
		self.tvSearch_link = '/stream/series/%s:%s:%s.json'

	@staticmethod
	def _parse_file(file):
		try:
			hints = file.get('behaviorHints', {})
			binge = hints.get('bingeGroup', '')
			hash = binge.split('|')[-1] if binge else ''
			if not _HASH_RE.match(hash):
				return None
			name = source_utils.clean_name(hints.get('filename', ''))
			if not name:
				return None
			try:
				m = _SEEDERS_RE.search(file.get('description', ''))
				seeders = int(m.group(1)) if m else 0
			except:
				seeders = 0
			try:
				sb = int(hints.get('videoSize', 0))
				if sb >= 1024 ** 3:
					dsize, isize = source_utils._size('%.2f GB' % (sb / 1024.0 ** 3))
				elif sb > 0:
					dsize, isize = source_utils._size('%.2f MB' % (sb / 1024.0 ** 2))
				else:
					dsize, isize = 0, ''
			except:
				dsize, isize = 0, ''
			magnet = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
			return hash, name, seeders, dsize, isize, magnet
		except:
			return None

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		if not self.stream_base:
			log_utils.log('COMET: no userdata configured, skipping')
			return self._results
		is_tv = 'tvshowtitle' in data
		files = []
		try:
			if is_tv:
				self._init_episode_data(data)
				url = '%s%s' % (self.stream_base, self.tvSearch_link % (data['imdb'], self.season_x, data['episode']))
			else:
				self._init_movie_data(data)
				url = '%s%s' % (self.stream_base, self.movieSearch_link % data['imdb'])
			self._init_filters()
			log_utils.log('COMET query: %s' % url)
			try:
				results = client.request(url, timeout=10)
				files = jsloads(results)['streams']
			except:
				files = []
		except:
			source_utils.scraper_error('COMET')
		finally:
			if is_tv:
				self._queue.put_nowait(files)
				self._queue.put_nowait(files)

		log_utils.log('COMET: %s raw results for "%s"' % (len(files), self.title))
		for file in files:
			try:
				parsed = self._parse_file(file)
				if not parsed: continue
				hash, name, seeders, dsize, isize, magnet = parsed
				if self.min_seeders > seeders: continue
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				self._append_result(self._build_result('comet', hash, name, name_info, magnet, seeders, dsize, isize))
			except:
				source_utils.scraper_error('COMET')

		self._log_stats('COMET')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		if not self.stream_base:
			log_utils.log('COMET: no userdata configured, skipping')
			return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			files = self._queue.get(timeout=11)
		except:
			source_utils.scraper_error('COMET')
			self._log_stats('COMET', pack=True)
			return self._results

		log_utils.log('COMET packs: %s raw results for "%s"' % (len(files), self.title))
		for file in files:
			try:
				parsed = self._parse_file(file)
				if not parsed: continue
				hash, name, seeders, dsize, isize, magnet = parsed
				if self.min_seeders > seeders: continue

				episode_start, episode_end, last_season = 0, 0, None
				if not search_series:
					package = 'season'
				else:
					last_season = total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				self._append_result(self._build_pack_result(
					'comet', hash, name, name_info, magnet, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, search_series))
			except:
				source_utils.scraper_error('COMET')

		self._log_stats('COMET', pack=True)
		return self._results