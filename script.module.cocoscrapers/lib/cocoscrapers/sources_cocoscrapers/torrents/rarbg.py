# -*- coding: utf-8 -*-

import re
from json import loads as jsloads
from urllib.parse import urlencode
from cocoscrapers.modules import client, source_utils, log_utils, cache
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_BASE_LINK = 'https://rargb.to'
_TOKEN_PATH = '/pubapi_v2.php?get_token=get_token&app_id=cocoscrapers'
_SEARCH_PATH = '/pubapi_v2.php'
_CAT_MOVIE = '14;17;44;45;47;48;50;51;52;53'
_CAT_TV = '41;49'


def _fetch_token(base_link):
	try:
		result = client.request('%s%s' % (base_link, _TOKEN_PATH), timeout=5)
		if not result: return None
		return jsloads(result).get('token')
	except: return None


class source(BaseTorrentScraper):
	priority = 2
	pack_capable = True
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.base_link = _BASE_LINK
		self.min_seeders = 0

	def _get_token(self):
		return cache.get(_fetch_token, 0.23, self.base_link)

	def _search(self, search_params, _token_retry=False, _rate_retry=False):
		token = _fetch_token(self.base_link) if _token_retry else self._get_token()
		if not token: return []
		params = dict(search_params)
		params.update({'token': token, 'mode': 'search', 'app_id': 'cocoscrapers',
					   'format': 'json_extended', 'limit': 100, 'ranked': 0})
		try:
			url = '%s%s?%s' % (self.base_link, _SEARCH_PATH, urlencode(params))
			result = client.request(url, timeout=10)
			if not result: return []
			data = jsloads(result)
			error_code = data.get('error_code')
			if error_code == 10 and not _token_retry:
				return self._search(search_params, _token_retry=True)
			if error_code in (4, 5) and not _rate_retry:
				from time import sleep
				sleep(2)
				return self._search(search_params, _rate_retry=True)
			if error_code == 2:
				return []
			return data.get('torrent_results') or []
		except:
			source_utils.scraper_error('RARBG')
			return []

	@staticmethod
	def _parse_item(item):
		try:
			url = item.get('download', '')
			hash_match = re.search(r'btih:([a-fA-F0-9]{40})', url, re.I)
			if not hash_match: return None
			hash = hash_match.group(1).lower()
			name = source_utils.clean_name(item.get('title', ''))
			seeders = int(item.get('seeders') or 0)
			size_bytes = int(item.get('size') or 0)
			dsize, isize = source_utils.convert_size(size_bytes, to='GB') if size_bytes else (0, '')
			return hash, name, seeders, dsize, isize, url
		except: return None

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		try:
			if 'tvshowtitle' in data:
				self._init_episode_data(data)
				search_params = {'search_imdb': data['imdb'], 'category': _CAT_TV,
								 'search_string': self.hdlr}
			else:
				self._init_movie_data(data)
				search_params = {'search_imdb': data['imdb'], 'category': _CAT_MOVIE}
			self._init_filters()
			files = self._search(search_params)
		except:
			source_utils.scraper_error('RARBG')
			self._log_stats('RARBG')
			return self._results

		for item in files:
			try:
				parsed = self._parse_item(item)
				if not parsed: continue
				hash, name, seeders, dsize, isize, url = parsed
				if not name or not hash: continue
				if self.min_seeders > seeders: continue
				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year, self.years): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				if not self.episode_title and self._is_episode_result(name): continue
				self._results.append(self._build_result('rarbg', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('RARBG')

		self._log_stats('RARBG')
		return self._results

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self._reset()
		if not data: return self._results
		try:
			self._init_pack_data(data)
			self._init_filters()
			imdb = data['imdb']
			if search_series:
				search_params = {'search_imdb': imdb, 'category': _CAT_TV}
			else:
				search_params = {'search_imdb': imdb, 'category': _CAT_TV,
								 'search_string': 'S%s' % self.season_xx}
			files = self._search(search_params)
		except:
			source_utils.scraper_error('RARBG')
			self._log_stats('RARBG', pack=True)
			return self._results

		for item in files:
			try:
				parsed = self._parse_item(item)
				if not parsed: continue
				hash, name, seeders, dsize, isize, url = parsed
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
					'rarbg', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, search_series))
			except:
				source_utils.scraper_error('RARBG')

		self._log_stats('RARBG', pack=True)
		return self._results