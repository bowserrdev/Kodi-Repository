# -*- coding: utf-8 -*-

import re
from difflib import SequenceMatcher
from json import dumps as jsdumps, loads as jsloads
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils, cleantitle
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_API_URL = 'https://api.knaben.org/v1'
_BTIH_RE = re.compile(r'btih:([0-9a-fA-F]{40})', re.I)
_JSON_HEADERS = {'Content-Type': 'application/json'}
_YEAR_RE = re.compile(r'(?:19|20)\d{2}')
_VIDEO_RE = re.compile(
	r'(\.(?:mkv|mp4|avi|m2ts|ts|mov|wmv|mpg|mpeg|divx)\b|'
	r'\b(?:bluray|bdrip|brrip|web-dl|webdl|webrip|dvdrip|dvd9|dvd5|hdrip|hdtv|tvrip|remux|workprint|x264|x265|h264|h265|hevc|xvid)\b)',
	re.I)
_TITLE_MARKER_RE = re.compile(
	r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op|'
	r'\.(?:mkv|mp4|avi|m2ts|ts|mov|wmv|mpg|mpeg|divx)\b|'
	r'\b(?:uhd|hdr|sdr|dv|dovi|bluray|blu-ray|bdrip|brrip|bdremux|web-dl|webdl|webrip|dvdrip|dvd9|dvd5|hdrip|hdtv|tvrip|remux|workprint|x264|x265|h264|h265|hevc|xvid)\b',
	re.I)
_TOKEN_RE = re.compile(r'[a-z0-9]+', re.I)


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
			try:
				seeders = int(hit.get('seeders') or 0)
			except:
				seeders = 0
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
				log_utils.log('KNABEN fetch failed: %s' % query)
				return []
			hits = jsloads(result).get('hits', [])
			log_utils.log('KNABEN query "%s": %s hits' % (query, len(hits)))
			return hits
		except:
			source_utils.scraper_error('KNABEN')
			return []

	def _check_movie_result(self, name):
		try:
			result_years = _YEAR_RE.findall(name)
			if not result_years:
				return False, 'year missing'
			if not any(y in self.years for y in result_years):
				return False, 'year out of range'
			if not _VIDEO_RE.search(name):
				return False, 'video marker missing'

			title_list = []
			for item in source_utils.aliases_to_array(self.aliases):
				try:
					title_list.append(item.replace('&', 'and'))
				except:
					pass
			title_list.append(self.title.replace('&', 'and'))

			name_title = _YEAR_RE.sub(' ', name.replace('&', 'and'))
			name_title = _TITLE_MARKER_RE.split(name_title, 1)[0]
			clean_result = cleantitle.get(name_title)
			result_tokens = [t.lower() for t in _TOKEN_RE.findall(name_title)]
			clean_titles = []
			title_token_lists = []
			for t in title_list:
				clean_title = cleantitle.get(t)
				if not clean_title: continue
				clean_titles.append(clean_title)
				title_tokens = [x.lower() for x in _TOKEN_RE.findall(t.replace('&', 'and'))]
				if title_tokens: title_token_lists.append(title_tokens)
				t_lower = t.strip().lower()
				for article in ('the ', 'a ', 'an '):
					if t_lower.startswith(article):
						clean_titles.append(cleantitle.get(t[len(article):]))
						article_tokens = [x.lower() for x in _TOKEN_RE.findall(t[len(article):])]
						if article_tokens: title_token_lists.append(article_tokens)

			for title_tokens in title_token_lists:
				if len(title_tokens) == 1:
					token = title_tokens[0]
					if result_tokens == title_tokens or (result_tokens and result_tokens[-1] == token):
						return True, ''
					continue
				for idx in range(0, len(result_tokens) - len(title_tokens) + 1):
					if result_tokens[idx:idx + len(title_tokens)] == title_tokens:
						return True, ''
			if self.year in result_years and _VIDEO_RE.search(name):
				fuzzy_titles = [t for t in clean_titles if t and len(t) >= 8]
				if not fuzzy_titles:
					return False, 'title mismatch'
				best_ratio = max(SequenceMatcher(None, t, clean_result).ratio() for t in fuzzy_titles)
				if best_ratio >= 0.62:
					log_utils.log('KNABEN KEPT [exact year + video fuzzy title %.2f]: "%s"' % (best_ratio, name))
					return True, ''
				return False, 'title mismatch fuzzy=%.2f' % best_ratio
			return False, 'title mismatch'
		except:
			source_utils.scraper_error('KNABEN')
			return False, 'title/year check error'

	def _get_sources(self, query):
		for hit in self._fetch_hits(query):
			try:
				parsed = self._parse_hit(hit)
				if not parsed:
					continue
				hash, name, seeders, dsize, isize, magnet = parsed
				log_utils.log('KNABEN RAW: "%s" | hash=%s | seeders=%s' % (name, hash, seeders))
				if self.min_seeders > seeders:
					log_utils.log('KNABEN SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue
				if self.episode_title:
					if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year):
						log_utils.log('KNABEN SKIP [title mismatch]: "%s"' % name)
						continue
				else:
					valid, reason = self._check_movie_result(name)
					if not valid:
						log_utils.log('KNABEN SKIP [%s]: "%s"' % (reason, name))
						continue
				if not self.episode_title and self._is_episode_result(name):
					log_utils.log('KNABEN SKIP [episode in movie search]: "%s"' % name)
					continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('KNABEN SKIP [lang]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('KNABEN SKIP [undesirable tag]: "%s"' % name)
					continue
				log_utils.log('KNABEN KEPT: "%s" | hash=%s' % (name, hash))
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
				log_utils.log('KNABEN RAW (pack): "%s" | hash=%s | seeders=%s' % (name, hash, seeders))
				if self.min_seeders > seeders:
					log_utils.log('KNABEN SKIP [seeders=%s < min=%s]: "%s"' % (seeders, self.min_seeders, name))
					continue

				episode_start, episode_end, last_season = 0, 0, None
				if not self._search_series:
					if not self._bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(
							self.title, self.aliases, self.year, self.season_x, name)
						if not valid:
							log_utils.log('KNABEN SKIP [filter_season_pack]: "%s"' % name)
							continue
					package = 'season'
				else:
					if not self._bypass_filter:
						valid, last_season = source_utils.filter_show_pack(
							self.title, self.aliases, self.imdb, self.year, self.season_x, name, self._total_seasons)
						if not valid:
							log_utils.log('KNABEN SKIP [filter_show_pack]: "%s"' % name)
							continue
					else:
						last_season = self._total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio):
					log_utils.log('KNABEN SKIP [lang]: "%s"' % name)
					continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables):
					log_utils.log('KNABEN SKIP [undesirable tag]: "%s"' % name)
					continue
				log_utils.log('KNABEN KEPT (pack=%s): "%s" | hash=%s' % (package, name, hash))
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
			else:
				self._init_movie_data(data)
			self._init_filters()
			queries = []
			for st in self.search_titles:
				st_clean = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st).strip()
				if not st_clean:
					continue
				q = '%s %s' % (st_clean, self.hdlr) if is_tv else st_clean
				queries.append(q)
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
			for query in queries:
				log_utils.log('KNABEN pack query: %s' % query)
		except:
			source_utils.scraper_error('KNABEN')
			return self._results

		self._run_threads(self._get_sources_packs, queries)
		self._log_stats('KNABEN', pack=True)
		return self._results
