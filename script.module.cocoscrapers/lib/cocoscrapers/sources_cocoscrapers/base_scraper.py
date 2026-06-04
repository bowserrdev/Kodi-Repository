# -*- coding: utf-8 -*-

import re
from threading import Thread
from time import time
from cocoscrapers.modules import source_utils
from cocoscrapers.modules import log_utils


class BaseTorrentScraper:
	priority = 99
	pack_capable = False
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		self._reset()

	def _reset(self):
		self._results = []
		self._items = []
		self.item_totals = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'CAM': 0}
		self._start_time = time()

	# ------------------------------------------------------------------ #
	# Data init helpers
	# ------------------------------------------------------------------ #

	def _init_episode_data(self, data):
		self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
		self.episode_title = data['title']
		self.hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode']))
		self.year = data['year']
		self.aliases = data['aliases']
		self.season_x = data['season']
		self.season_xx = self.season_x.zfill(2)
		self.years = None

	def _init_movie_data(self, data):
		self.title = data['title'].replace('&', 'and').replace('/', ' ').replace('$', 's')
		self.episode_title = None
		self.hdlr = data['year']
		self.year = data['year']
		self.aliases = data['aliases']
		self.years = [str(int(self.year) - 1), str(self.year), str(int(self.year) + 1)]

	def _init_pack_data(self, data):
		self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
		self.aliases = data['aliases']
		self.imdb = data['imdb']
		self.year = data['year']
		self.season_x = data['season']
		self.season_xx = self.season_x.zfill(2)

	def _init_filters(self):
		self.undesirables = source_utils.get_undesirables()
		self.check_foreign_audio = source_utils.check_foreign_audio()

	# ------------------------------------------------------------------ #
	# Threading helper
	# ------------------------------------------------------------------ #

	def _run_threads(self, func, items):
		threads = [Thread(target=func, args=(i,)) for i in items]
		[t.start() for t in threads]
		[t.join() for t in threads]

	# ------------------------------------------------------------------ #
	# Result builders — also update item_totals
	# ------------------------------------------------------------------ #

	def _build_result(self, provider, hash, name, name_info, url, seeders, dsize, isize):
		quality, info = source_utils.get_release_quality(name_info, url)
		if isize: info.insert(0, isize)
		self.item_totals[quality] += 1
		return {
			'provider': provider, 'source': 'torrent', 'seeders': seeders,
			'hash': hash, 'name': name, 'name_info': name_info,
			'quality': quality, 'language': 'en', 'url': url,
			'info': ' | '.join(info), 'direct': False, 'debridonly': True, 'size': dsize
		}

	def _build_pack_result(self, provider, hash, name, name_info, url, seeders, dsize, isize,
							package, episode_start=0, episode_end=0, last_season=None, search_series=False):
		quality, info = source_utils.get_release_quality(name_info, url)
		if isize: info.insert(0, isize)
		self.item_totals[quality] += 1
		item = {
			'provider': provider, 'source': 'torrent', 'seeders': seeders,
			'hash': hash, 'name': name, 'name_info': name_info,
			'quality': quality, 'language': 'en', 'url': url,
			'info': ' | '.join(info), 'direct': False, 'debridonly': True,
			'size': dsize, 'package': package
		}
		if search_series and last_season is not None:
			item['last_season'] = last_season
		elif episode_start:
			item.update({'episode_start': episode_start, 'episode_end': episode_end})
		return item

	# ------------------------------------------------------------------ #
	# Episode filter — per movie queries che restituiscono TV results
	# ------------------------------------------------------------------ #

	_EP_STRINGS = [r'[.-]s\d{2}e\d{2}([.-]?)', r'[.-]s\d{2}([.-]?)', r'[.-]season[.-]?\d{1,2}[.-]?']

	def _is_episode_result(self, name):
		return any(re.search(p, name.lower()) for p in self._EP_STRINGS)

	# ------------------------------------------------------------------ #
	# Stats logging
	# ------------------------------------------------------------------ #

	def _log_stats(self, name, pack=False):
		label = '%s(pack)' % name if pack else name
		logged = False
		for q, count in self.item_totals.items():
			if count > 0:
				log_utils.log('#STATS - %s found %s %s' % (label, count, q))
				logged = True
		if not logged:
			log_utils.log('#STATS - %s found nothing' % label)
		log_utils.log('#STATS - %s took %.2fs' % (label, time() - self._start_time))