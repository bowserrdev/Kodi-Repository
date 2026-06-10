# -*- coding: utf-8 -*-
from caches.base_cache import connect_database, get_timestamp

GET_MANY = 'SELECT * FROM debrid_data WHERE hash in (%s)'
SET_MANY = 'INSERT INTO debrid_data VALUES (?, ?, ?, ?)'
REMOVE_MANY = 'DELETE FROM debrid_data WHERE hash=?'
CLEAR = 'DELETE FROM debrid_data'
CLEAR_DEBRID = 'DELETE FROM debrid_data WHERE debrid=?'
CLEAN = 'DELETE from debrid_data WHERE CAST(expires AS INT) <= ?'

class DebridCache:
	def get_many(self, hash_list):
		try:
			dbcon = connect_database('debridcache_db')
			current_time = get_timestamp()
			cache_data = dbcon.execute(GET_MANY % (', '.join('?' for _ in hash_list)), hash_list).fetchall()
			if cache_data:
				if cache_data[0][3] > current_time: return cache_data
				self.remove_many(cache_data)
		except: pass
		return None

	def set_many(self, hash_list, debrid):
		try:
			dbcon = connect_database('debridcache_db')
			expires = get_timestamp(24)
			dbcon.executemany(SET_MANY, [(i[0], debrid, i[1], expires) for i in hash_list])
		except: pass

	def remove_many(self, old_cached_data):
		try:
			dbcon = connect_database('debridcache_db')
			dbcon.executemany(REMOVE_MANY, [(str(i[0]),) for i in old_cached_data])
		except: pass

	def clear_debrid_results(self, debrid):
		try:
			dbcon = connect_database('debridcache_db')
			dbcon.execute(CLEAR_DEBRID, (debrid,))
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clear_cache(self):
		try:
			dbcon = connect_database('debridcache_db')
			dbcon.execute(CLEAR)
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = connect_database('debridcache_db')
			dbcon.execute(CLEAN, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

debrid_cache = DebridCache()