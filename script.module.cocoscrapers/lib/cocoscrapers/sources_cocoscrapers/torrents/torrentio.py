# -*- coding: utf-8 -*-

import re
import queue as queue_module
from json import loads as jsloads
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_INFO = re.compile(r'👤.*')
_SIZE_RE = re.compile(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|Gb|MB|MiB|Mb))')


class source(BaseTorrentScraper):
	priority = 1
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	_queue = queue_module.SimpleQueue()

	def __init__(self):
		super().__init__()
		self.base_link = 'https://torrentio.strem.fun'
		self.movieSearch_link = '/stream/movie/%s.json'
		self.tvSearch_link = '/stream/series/%s:%s:%s.json'
		self.min_seeders = 0
		self.bypass_filter = getSetting('torrentio.bypass_filter')

	@staticmethod
	def _parse_file(file):
		try:
			file_title = file['title'].split('\n')
			file_info = [x for x in file_title if _INFO.match(x)][0]
			hash = file.get('infoHash', '')
			name = source_utils.clean_name(file_title[0])
			url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
			try: seeders = int(re.search(r'(\d+)', file_info).group(1))
			except: seeders = 0
			try:
				size_match = _SIZE_RE.search(file_info)
				dsize, isize = source_utils._size(size_match.group(0)) if size_match else (0, '')
			except: dsize, isize = 0, ''
			return hash, name, seeders, dsize, isize, url
		except: return None

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		is_tv = 'tvshowtitle' in data
		files = []
		try:
			if is_tv:
				self._init_episode_data(data)
				url = '%s%s' % (self.base_link, self.tvSearch_link % (data['imdb'], self.season_x, data['episode']))
			else:
				self._init_movie_data(data)
				url = '%s%s' % (self.base_link, self.movieSearch_link % data['imdb'])
			self._init_filters()
			log_utils.log('TORRENTIO query: %s' % url)
			try:
				results = client.request(url, timeout=10)
				files = jsloads(results)['streams']
			except: files = []
		except:
			source_utils.scraper_error('TORRENTIO')
		finally:
			if is_tv:
				self._queue.put_nowait(files)
				self._queue.put_nowait(files)

		log_utils.log('TORRENTIO: %s raw results for "%s"' % (len(files), self.title))
		for file in files:
			try:
				raw_title = (file.get('title') or '').split('\n')[0]
				parsed = self._parse_file(file)
				if not parsed:
					log_utils.log('TORRENTIO SKIP [parse failed] raw="%s"' % raw_title)
					continue
				hash, name, seeders, dsize, isize, url = parsed
				if not name or not hash:
					log_utils.log('TORRENTIO SKIP [empty after clean_name] raw="%s"' % raw_title)
					continue
				log_utils.log('TORRENTIO RAW: "%s" | hash=%s | seeders=%s' % (name, hash, seeders))
				if self.min_seeders > seeders:
					log_utils.log('TORRENTIO SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue
				if self.bypass_filter == 'false':
					if not source_utils.check_title(self.title, self.aliases, name.replace('.(Archie.Bunker', ''), self.hdlr, self.year, self.years):
						if not self._check_title_raw(raw_title):
							log_utils.log('TORRENTIO SKIP [title mismatch]: "%s"' % name)
							continue
						log_utils.log('TORRENTIO KEPT [non-ASCII title]: "%s"' % raw_title)
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('TORRENTIO SKIP [language filter]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('TORRENTIO SKIP [undesirable tag]: "%s"' % name)
					continue
				log_utils.log('TORRENTIO KEPT: "%s" | hash=%s' % (name, hash))
				self._append_result(self._build_result('torrentio', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('TORRENTIO')

		self._log_stats('TORRENTIO')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			imdb = data['imdb']
			files = self._queue.get(timeout=11)
			if self.bypass_filter == 'true': bypass_filter = True
		except:
			source_utils.scraper_error('TORRENTIO')
			self._log_stats('TORRENTIO', pack=True)
			return self._results

		log_utils.log('TORRENTIO packs: %s raw results for "%s"' % (len(files), self.title))
		for file in files:
			try:
				raw_title = (file.get('title') or '').split('\n')[0]
				parsed = self._parse_file(file)
				if not parsed:
					log_utils.log('TORRENTIO SKIP [parse failed] raw="%s"' % raw_title)
					continue
				hash, name, seeders, dsize, isize, url = parsed
				if not name or not hash:
					log_utils.log('TORRENTIO SKIP [empty after clean_name] raw="%s"' % raw_title)
					continue
				if self.min_seeders > seeders:
					log_utils.log('TORRENTIO SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue

				episode_start, episode_end, last_season = 0, 0, None
				if not search_series:
					if not bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name.replace('.(Archie.Bunker', ''))
						if not valid:
							log_utils.log('TORRENTIO SKIP [filter_season_pack]: "%s"' % name)
							continue
					package = 'season'
				else:
					if not bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, imdb, self.year, self.season_x, name.replace('.(Archie.Bunker', ''), total_seasons)
						if not valid:
							log_utils.log('TORRENTIO SKIP [filter_show_pack]: "%s"' % name)
							continue
					else: last_season = total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('TORRENTIO SKIP [language filter]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('TORRENTIO SKIP [undesirable tag]: "%s"' % name)
					continue

				log_utils.log('TORRENTIO KEPT (pack=%s): "%s" | hash=%s' % (package, name, hash))
				self._append_result(self._build_pack_result(
					'torrentio', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, search_series))
			except:
				source_utils.scraper_error('TORRENTIO')

		self._log_stats('TORRENTIO', pack=True)
		return self._results