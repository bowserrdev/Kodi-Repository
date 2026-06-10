# -*- coding: utf-8 -*-
import json
from caches.base_cache import connect_database, get_timestamp

SELECT_RESULTS = 'SELECT results, expires FROM results_data WHERE provider = ? AND db_type = ? AND tmdb_id = ? AND title = ? AND year = ? AND season = ? AND episode = ?'
DELETE_RESULTS = 'DELETE FROM results_data WHERE provider = ? AND db_type = ? AND tmdb_id = ? AND title = ? AND year = ? AND season = ? AND episode = ?'
INSERT_RESULTS = 'INSERT OR REPLACE INTO results_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
SINGLE_DELETE = 'DELETE FROM results_data WHERE db_type=? AND tmdb_id=?'
FULL_DELETE = 'DELETE FROM results_data'
CLEAN = 'DELETE from results_data WHERE CAST(expires AS INT) <= ?'

class ExternalCache:
	def get(self, source, media_type, tmdb_id, title, year, season, episode):
		try:
			row = connect_database('external_db').execute(SELECT_RESULTS, (source, media_type, tmdb_id, title, year, season, episode)).fetchone()
			if row:
				if row[1] > get_timestamp():
					return json.loads(row[0])
				self.delete(source, media_type, tmdb_id, title, season, episode)
		except: pass
		return None

	def set(self, source, media_type, tmdb_id, title, year, season, episode, results, expire_time):
		try:
			expires = get_timestamp(expire_time)
			connect_database('external_db').execute(INSERT_RESULTS, (source, media_type, tmdb_id, title, year, season, episode, json.dumps(results or [], ensure_ascii=False), int(expires)))
		except: pass

	def delete(self, source, media_type, tmdb_id, title, season, episode):
		try:
			connect_database('external_db').execute(DELETE_RESULTS, (source, media_type, tmdb_id, title, season, episode))
		except: pass

	def delete_cache_single(self, media_type, tmdb_id):
		try:
			connect_database('external_db').execute(SINGLE_DELETE, (media_type, tmdb_id))
			connect_database('external_db').execute('VACUUM')
			return True
		except: return False

	def clear_cache(self):
		try:
			dbcon = connect_database('external_db')
			dbcon.execute(FULL_DELETE)
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = connect_database('external_db')
			dbcon.execute(CLEAN, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

external_cache = ExternalCache()