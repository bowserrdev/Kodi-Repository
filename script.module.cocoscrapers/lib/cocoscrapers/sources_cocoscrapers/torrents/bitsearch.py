# -*- coding: utf-8 -*-

import re
from difflib import SequenceMatcher
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils, cleantitle
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTorrentScraper

_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
_BTIH_RE = re.compile(r'btih[:=]([0-9a-fA-F]{40})', re.I)
_TORRENT_LINK_RE = re.compile(r'href="/torrent/[^"]+"', re.I)
_YEAR_RE = re.compile(r'(?:19|20)\d{2}')
_QUALITY_RE = re.compile(r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op', re.I)
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
		self.base_link = 'https://bitsearch.to'
		self.search_link = '/search?q=%s&sort=size'
		self.min_seeders = 0
		self._headers = {'Accept-Language': 'en-US,en;q=0.9'}

	@staticmethod
	def _fetch_rows(page_url, headers):
		try:
			response = client.request(page_url, timeout=7, headers=headers, output='extended')
			if not response:
				log_utils.log('BITSEARCH fetch failed: %s' % page_url)
				return []
			results, status, response_headers = response
			if status != '200':
				log_utils.log('BITSEARCH fetch status=%s url=%s' % (status, page_url))
				return []
			if not results or '/torrent/' not in results:
				log_utils.log('BITSEARCH no torrent markers: len=%s url=%s' % (len(results or ''), page_url))
				return []

			matches = list(_TORRENT_LINK_RE.finditer(results))
			if matches:
				rows = []
				for idx, match in enumerate(matches):
					end = matches[idx + 1].start() if idx + 1 < len(matches) else len(results)
					rows.append(results[match.start():end])
				return rows

			cards = re.split(r'<div class="[^"]*(?:bg-white|shadow|border)[^"]*"', results)
			rows = [c for c in cards[1:] if '/torrent/' in c]
			log_utils.log('BITSEARCH fallback card split: %s rows len=%s url=%s' % (len(rows), len(results), page_url))
			return rows
		except:
			source_utils.scraper_error('BITSEARCH')
			return []

	@staticmethod
	def _parse_row(row):
		try:
			hash_match = re.search(r'/download/torrent/([A-F0-9]{40})', row, re.I)
			if hash_match:
				hash = hash_match.group(1).lower()
			else:
				hash_match = _BTIH_RE.search(row)
				hash = hash_match.group(1).lower() if hash_match else ''
			if not _HASH_RE.match(hash): return None
			name_match = re.search(r'href="/torrent/[^"]+"[^>]*>\s*(.*?)\s*</a>', row, re.DOTALL)
			if not name_match: return None
			name = source_utils.clean_name(client.cleanHTML(name_match.group(1)).strip())
			url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
			try:
				s = re.search(r'text-green-600[^>]*>.*?<span class="font-medium">(\d+)</span>', row, re.DOTALL)
				seeders = int(s.group(1)) if s else 0
			except: seeders = 0
			try:
				sz = re.search(r'(\d+(?:[.,]\d+)*\s*(?:GB|MB|TB|GiB|MiB)\b)', row)
				dsize, isize = source_utils._size(sz.group(1).strip()) if sz else (0, '')
			except: dsize, isize = 0, ''
			return url, hash, name, seeders, dsize, isize
		except: return None

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
					log_utils.log('BITSEARCH KEPT [exact year + video fuzzy title %.2f]: "%s"' % (best_ratio, name))
					return True, ''
				return False, 'title mismatch fuzzy=%.2f' % best_ratio
			return False, 'title mismatch'
		except:
			source_utils.scraper_error('BITSEARCH')
			return False, 'title/year check error'

	def get_sources(self, page_url):
		rows = self._fetch_rows(page_url, self._headers)
		log_utils.log('BITSEARCH page "%s": %s rows' % (page_url, len(rows)))
		parse_failures = 0
		for row in rows:
			try:
				parsed = self._parse_row(row)
				if not parsed:
					parse_failures += 1
					continue
				url, hash, name, seeders, dsize, isize = parsed
				if not name or not hash: continue
				log_utils.log('BITSEARCH RAW: "%s" | hash=%s | seeders=%s' % (name, hash, seeders))
				if self.episode_title:
					if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year):
						log_utils.log('BITSEARCH SKIP [title mismatch]: "%s"' % name)
						continue
				else:
					valid, reason = self._check_movie_result(name)
					if not valid:
						log_utils.log('BITSEARCH SKIP [%s]: "%s"' % (reason, name))
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
				self._append_result(self._build_result('bitsearch', hash, name, name_info, url, seeders, dsize, isize))
			except:
				source_utils.scraper_error('BITSEARCH')
		if parse_failures:
			log_utils.log('BITSEARCH parse failures: %s/%s url=%s' % (parse_failures, len(rows), page_url))

	def get_sources_packs(self, link):
		rows = self._fetch_rows(link, self._headers)
		log_utils.log('BITSEARCH pack page "%s": %s rows' % (link, len(rows)))
		parse_failures = 0
		for row in rows:
			try:
				parsed = self._parse_row(row)
				if not parsed:
					parse_failures += 1
					continue
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
				self._append_result(self._build_pack_result(
					'bitsearch', hash, name, name_info, url, seeders, dsize, isize,
					package, episode_start, episode_end, last_season, self.search_series))
			except:
				source_utils.scraper_error('BITSEARCH')
		if parse_failures:
			log_utils.log('BITSEARCH pack parse failures: %s/%s url=%s' % (parse_failures, len(rows), link))

	def sources(self, data, hostDict):
		self._reset()
		if not data: return self._results
		try:
			is_tv = 'tvshowtitle' in data
			if is_tv: self._init_episode_data(data)
			else: self._init_movie_data(data)
			self._init_filters()
			pages = []
			for idx, st in enumerate(self.search_titles):
				st_clean = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st).strip()
				if not st_clean:
					continue
				q = '%s %s' % (st_clean, self.hdlr) if is_tv else st_clean
				base = '%s%s' % (self.base_link, self.search_link % quote_plus(q))
				log_utils.log('BITSEARCH query[%s]: %s' % (idx, base))
				pages.append(base)
				if st == self._paginate_title:
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
				q = re.sub(r'[^A-Za-z0-9\s\.-]+', '', st).strip()
				if not q:
					continue
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
