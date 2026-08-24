# -*- coding: utf-8 -*-
import json
from caches.base_cache import connect_database, get_timestamp
from modules.kodi_utils import clear_property

all_tables = ('metadata', 'season_metadata', 'function_cache')
id_types = ('tmdb_id', 'imdb_id', 'tvdb_id')
season_prop, media_prop = 'fenlight.meta_season_%s', 'fenlight.%s_%s_%s'
GET_MOVIE_SHOW = 'SELECT meta, expires FROM metadata WHERE db_type = ? AND %s = ?'
GET_MOVIE_SHOW_MANY = 'SELECT %s, meta, expires FROM metadata WHERE db_type = ? AND %s IN (%s)'
GET_SEASON = 'SELECT meta, expires FROM season_metadata WHERE tmdb_id = ?'
GET_FUNCTION = 'SELECT string_id, data, expires FROM function_cache WHERE string_id = ?'
GET_ALL = 'SELECT db_type, tmdb_id FROM metadata'
GET_ALL_SEASON = 'SELECT tmdb_id FROM season_metadata'
SET_MOVIE_SHOW = 'INSERT OR REPLACE INTO metadata VALUES (?, ?, ?, ?, ?, ?)'
SET_SEASON = 'INSERT INTO season_metadata VALUES (?, ?, ?)'
SET_FUNCTION = 'INSERT INTO function_cache VALUES (?, ?, ?)'
DELETE_MOVIE_SHOW = 'DELETE FROM metadata WHERE db_type = ? AND %s = ?'
DELETE_SEASON = 'DELETE FROM season_metadata WHERE tmdb_id = ?'
DELETE_SEASON_ALL = 'DELETE FROM season_metadata WHERE tmdb_id LIKE ?'
DELETE_FUNCTION = 'DELETE FROM function_cache WHERE string_id = ?'
DELETE_ALL = 'DELETE FROM %s'
CLEAN = 'DELETE from %s WHERE CAST(expires AS INT) <= ?'
string = str

# Lo strato di cache "in memoria" che stava qui teneva il metadato completo di ogni titolo dentro una
# proprieta' di Window(10000), in JSON. Serviva perche' ogni build del widget e' un processo Python
# nuovo (reuselanguageinvoker=false) e un dizionario non sopravviverebbe -- ma SQLite sopravvive
# ugualmente, e in WAL la lettura e' gia' servita dalla cache di pagina del sistema. In cambio quello
# strato costava: crescita ILLIMITATA (nessuno rimuoveva le voci finche' Kodi non si chiudeva, quindi
# megabyte di stringhe su un dispositivo da 1 GB) e un json.dumps + setProperty per OGNI elemento a
# ogni ricostruzione. Rimosso: la lettura passa direttamente da SQLite.
class MetaCache:
	def get(self, media_type, id_type, media_id, current_time=None):
		try:
			media_id = string(media_id)
			if not current_time: current_time = get_timestamp()
			meta = None
			dbcon = connect_database('metacache_db')
			row = dbcon.execute(GET_MOVIE_SHOW % id_type, (media_type, media_id)).fetchone()
			if row:
				meta, expiry = json.loads(row[0]), row[1]
				if expiry < current_time:
					# Marcatore diagnostico (lotto 53): distingue "mai scritto in cache" da
					# "scritto e poi cancellato perche' gia' scaduto alla lettura successiva".
					try:
						from modules.kodi_utils import logger
						logger('FenLight CACHE SCADUTA', '%s %s=%s | scaduto da %s s' % (media_type, id_type, media_id, current_time - expiry))
					except: pass
					self.delete(media_type, id_type, media_id, meta=meta)
					meta = None
		except: meta = None
		return meta

	def get_many(self, media_type, id_type, media_ids, current_time=None):
		# UNA query per l'intera lista invece di una per elemento, da eseguire in sequenza fuori dal
		# pool di thread. Misurato dentro Kodi: la stessa lettura costa 0.036 ms/elemento in
		# sequenza e 1.0-1.7 ms sotto il pool a 6-10 worker -- non perche' sia lenta, ma per
		# l'effetto convoglio sul GIL (sqlite3 lo rilascia durante execute e per riprenderlo aspetta
		# un passaggio di consegne, fino a 5 ms). Le voci scadute NON vengono restituite: cadono sul
		# percorso normale, che le cancella e le riscarica.
		results = {}
		if not media_ids: return results
		try:
			if not current_time: current_time = get_timestamp()
			dbcon = connect_database('metacache_db')
			media_ids = list(media_ids)
			# SQLite limita il numero di parametri per statement: la lista va spezzata.
			for start in range(0, len(media_ids), 500):
				chunk = media_ids[start:start + 500]
				query = GET_MOVIE_SHOW_MANY % (id_type, id_type, ', '.join('?' for _ in chunk))
				for row in dbcon.execute(query, [media_type] + chunk):
					if row[2] < current_time: continue
					try: results[string(row[0])] = json.loads(row[1])
					except: pass
		except: pass
		return results

	def get_season(self, prop_string):
		try:
			current_time = get_timestamp()
			meta = None
			dbcon = connect_database('metacache_db')
			row = dbcon.execute(GET_SEASON, (prop_string,)).fetchone()
			if row:
				meta, expiry = json.loads(row[0]), row[1]
				if expiry < current_time:
					self.delete_season(prop_string)
					meta = None
		except: meta = None
		return meta

	def set(self, media_type, id_type, meta, expiration=168, current_time=None):
		try:
			dbcon = connect_database('metacache_db')
			meta_get = meta.get
			expires = (current_time + (expiration * 3600)) if current_time else get_timestamp(expiration)
			dbcon.execute(SET_MOVIE_SHOW, (media_type, string(meta_get('tmdb_id')), meta_get('imdb_id'), string(meta_get('tvdb_id')), json.dumps(meta, ensure_ascii=False), expires))
		except Exception as _e:
			# Marcatore diagnostico (lotto 53): era `pass`. Se la scrittura in cache fallisce qui,
			# l'elemento viene riscaricato dalla rete a ogni avvio senza lasciare traccia.
			try:
				from modules.kodi_utils import logger
				logger('FenLight CACHE SET FALLITA', '%s tmdb=%s | %s: %s' % (media_type, meta.get('tmdb_id'), type(_e).__name__, _e))
			except: pass

	def set_season(self, prop_string, meta, expiration=168):
		try:
			dbcon = connect_database('metacache_db')
			expires = get_timestamp(expiration)
			dbcon.execute(SET_SEASON, (prop_string, json.dumps(meta, ensure_ascii=False), int(expires)))
		except: pass

	def delete(self, media_type, id_type, media_id, meta=None):
		try:
			dbcon = connect_database('metacache_db')
			dbcon.execute(DELETE_MOVIE_SHOW % id_type, (media_type, media_id))
			for item in id_types:
				self.delete_memory_cache(media_type, item, meta[item])
			if media_type == 'tvshow':
				self.delete_all_seasons(media_id)
		except: return

	def delete_season(self, prop_string):
		try:
			dbcon = connect_database('metacache_db')
			dbcon.execute(DELETE_SEASON, (prop_string,))
			self.delete_memory_cache_season(prop_string)
		except: return

	def delete_memory_cache(self, media_type, id_type, media_id):
		try: clear_property(media_prop % (media_type, id_type, media_id))
		except: pass

	def delete_memory_cache_season(self, prop_string):
		try: clear_property(season_prop % prop_string)
		except: pass

	def get_function(self, prop_string):
		try:
			dbcon = connect_database('metacache_db')
			current_time = get_timestamp()
			row = dbcon.execute(GET_FUNCTION, (prop_string,)).fetchone()
			if row:
				if row[2] > current_time:
					return json.loads(row[1])
				dbcon.execute(DELETE_FUNCTION, (prop_string,))
		except: pass
		return None

	def set_function(self, prop_string, result, expiration=24):
		try:
			dbcon = connect_database('metacache_db')
			expires = get_timestamp(expiration)
			dbcon.execute(SET_FUNCTION, (prop_string, json.dumps(result, ensure_ascii=False), expires))
		except: pass

	def delete_all_seasons(self, media_id):
		media_id = string(media_id)
		try:
			dbcon = connect_database('metacache_db')
			# Single query removes all season rows for this show regardless of season number or language suffix.
			dbcon.execute(DELETE_SEASON_ALL, (media_id + '_%',))
		except: pass
		# Window properties are per-session; clear the common English-language range.
		# Non-English suffixed props expire naturally on Kodi restart.
		for season in range(1, 51):
			self.delete_memory_cache_season('%s_%s' % (media_id, season))

	def delete_all(self):
		try:
			dbcon = connect_database('metacache_db')
			for i in dbcon.execute(GET_ALL):
				try: self.delete_memory_cache(string(i[0]), 'tmdb_id', string(i[1]))
				except: pass
			for i in dbcon.execute(GET_ALL_SEASON):
				try: self.delete_memory_cache_season(string(i[0]))
				except: pass
			for table in all_tables:
				dbcon.execute(DELETE_ALL % table)
			dbcon.execute('VACUUM')
		except: return

	def clean_database(self):
		try:
			dbcon = connect_database('metacache_db')
			for table in ('metadata', 'function_cache', 'season_metadata'):
				dbcon.execute(CLEAN % table, (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

meta_cache = MetaCache()

def cache_function(function, prop_string, url, expiration=720, json_response=True):
	data = meta_cache.get_function(prop_string)
	if data: return data
	result = function(url).json() if json_response else function(url)
	meta_cache.set_function(prop_string, result, expiration=expiration)
	return result

def delete_meta_cache(silent=False):
	from modules.kodi_utils import confirm_dialog
	try:
		if not silent and not confirm_dialog(): return False
		meta_cache.delete_all()
		return True
	except: return False