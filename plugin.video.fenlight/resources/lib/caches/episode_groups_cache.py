# -*- coding: utf-8 -*-
import json
from caches.base_cache import connect_database

SET = 'INSERT OR REPLACE INTO groups_data VALUES (?, ?)'
GET = 'SELECT data FROM groups_data WHERE tmdb_id = ?'
DELETE = 'DELETE FROM groups_data WHERE tmdb_id=?'
DELETE_ALL = 'DELETE FROM groups_data'

class EpisodeGroupsCache:
	def get(self, tmdb_id):
		try:
			row = connect_database('episode_groups_db').execute(GET, (str(tmdb_id),)).fetchone()
			if row: return json.loads(row[0])
		except: pass
		return {}

	def set(self, tmdb_id, data):
		try:
			connect_database('episode_groups_db').execute(SET, (str(tmdb_id), json.dumps(data, ensure_ascii=False)))
		except: pass

	def delete(self, tmdb_id):
		try:
			dbcon = connect_database('episode_groups_db')
			dbcon.execute(DELETE, (str(tmdb_id),))
			dbcon.execute('VACUUM')
		except: pass

	def clear_cache(self):
		try:
			dbcon = connect_database('episode_groups_db')
			dbcon.execute(DELETE_ALL)
			dbcon.execute('VACUUM')
		except: pass

episode_groups_cache = EpisodeGroupsCache()