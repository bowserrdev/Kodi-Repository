# -*- coding: utf-8 -*-
# Dedicated cache for the widget "dubbed content" filter (see modules.settings.dub_filter_*).
#
# Stores, per (country, media_type, tmdb_id), a single boolean: does a localised release exist in that
# country (streaming via TMDb/JustWatch, OR home video via blu-ray.com). Once known, the filter applies
# instantly with zero network on subsequent builds.
#
# ASYMMETRIC TTL (the key design point):
#  - AVAILABLE (True): once a localised/dubbed edition exists it effectively never disappears, so cache it
#    for a long time.
#  - UNAVAILABLE (False): a recent title may still get a release later, so cache it briefly and re-check.
#
# THREE-STATE reads: get_availability returns True/False for a live cache hit, or None for a miss/expired
# entry (the caller must then look it up). BaseCache.get already returns the stored bool on a hit and None
# on miss/expiry, so a cached False is distinguishable from a miss. Inconclusive lookups (network errors)
# must NOT be cached, so the next build retries them.
from caches.base_cache import BaseCache, get_timestamp

EXPIRY_AVAILABLE = 24 * 180   # hours (~180 days)
EXPIRY_UNAVAILABLE = 24 * 7   # hours (~7 days)

GET_ALL = 'SELECT id FROM dubcache'
DELETE_ALL = 'DELETE FROM dubcache'
CLEAN = 'DELETE FROM dubcache WHERE CAST(expires AS INT) <= ?'

class DubCache(BaseCache):
	def __init__(self):
		BaseCache.__init__(self, 'dub_db', 'dubcache')

	def _key(self, country, media_type, tmdb_id):
		return 'dub_%s_%s_%s' % (country, media_type, tmdb_id)

	def get_availability(self, country, media_type, tmdb_id):
		# True/False on a live cache hit, None on miss/expired.
		return self.get(self._key(country, media_type, tmdb_id))

	def set_availability(self, country, media_type, tmdb_id, available):
		expiration = EXPIRY_AVAILABLE if available else EXPIRY_UNAVAILABLE
		self.set(self._key(country, media_type, tmdb_id), bool(available), expiration)

	def delete_all(self):
		try:
			dbcon = self.manual_connect('dub_db')
			for i in dbcon.execute(GET_ALL):
				self.delete_memory_cache(str(i[0]))
			dbcon.execute(DELETE_ALL)
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = self.manual_connect('dub_db')
			dbcon.execute(CLEAN, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

dub_cache = DubCache()
