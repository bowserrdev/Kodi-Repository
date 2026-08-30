# -*- coding: utf-8 -*-
import json
from caches.base_cache import connect_database
from modules.kodi_utils import sleep, confirm_dialog, close_all_dialog

SELECT = 'SELECT id FROM trakt_data'
DELETE = 'DELETE FROM trakt_data WHERE id=?'
DELETE_LIKE = 'DELETE FROM trakt_data WHERE id LIKE ?'
WATCHED_INSERT = 'INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_UPSERT = 'INSERT OR REPLACE INTO watched VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_LAST_PLAYED = 'SELECT MAX(last_played) FROM watched WHERE db_type = ?'
WATCHED_DELETE = 'DELETE FROM watched WHERE db_type = ?'
PROGRESS_INSERT = 'INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
PROGRESS_DELETE = 'DELETE FROM progress WHERE db_type = ?'
STATUS_INSERT = 'INSERT INTO watched_status VALUES (?, ?, ?)'
STATUS_DELETE = 'DELETE FROM watched_status'
BASE_DELETE = 'DELETE FROM %s'
TC_BASE_GET = 'SELECT data FROM trakt_data WHERE id = ?'
TC_BASE_SET = 'INSERT OR REPLACE INTO trakt_data (id, data) VALUES (?, ?)'
TC_BASE_DELETE = 'DELETE FROM trakt_data WHERE id = ?'
DELETE_LISTS_WITH_MEDIA = 'SELECT id FROM maincache WHERE id LIKE ?'

class TraktCache:
	def get(self, string):
		try:
			dbcon = connect_database('trakt_db')
			row = dbcon.execute(TC_BASE_GET, (string,)).fetchone()
			if row: return json.loads(row[0])
		except: pass
		return None

	def set(self, string, data):
		try:
			dbcon = connect_database('trakt_db')
			dbcon.execute(TC_BASE_SET, (string, json.dumps(data, ensure_ascii=False)))
		except: pass

	def delete(self, string):
		try:
			dbcon = connect_database('trakt_db')
			dbcon.execute(TC_BASE_DELETE, (string,))
		except: pass

trakt_cache = TraktCache()

class TraktWatched:
	def set_bulk_tvshow_status(self, insert_list):
		self._delete(STATUS_DELETE, ())
		self._executemany(STATUS_INSERT, insert_list)

	def set_tvshow_status(self, insert_dict):
		dbcon = connect_database('trakt_db')
		dbcon.execute(TC_BASE_SET, ('trakt_tvshow_status', json.dumps(insert_dict, ensure_ascii=False)))

	def _watched_keys(self, db_type):
		# Chiavi (media_id, stagione, episodio) gia' presenti, normalizzate a stringa: dal database
		# arrivano come INTEGER e dalla lista da inserire spesso come stringa, e un confronto fra i due
		# tipi darebbe ogni riga per cambiata.
		try:
			dbcon = connect_database('trakt_db')
			rows = dbcon.execute('SELECT media_id, season, episode FROM watched WHERE db_type = ?', (db_type,))
			return set((str(r[0]), str(r[1]), str(r[2])) for r in rows)
		except: return None

	def _changed_media_ids(self, db_type, insert_list):
		"""Quali titoli cambiano stato con questa scrittura. None se non e' stato possibile stabilirlo.

		Serve al refresh mirato (lotto 59): l'API di Trakt dice solo che "qualcosa fra gli episodi
		visti e' cambiato", mai quali. Dopo la ricostruzione pero' abbiamo l'insieme prima e quello
		dopo, quindi la differenza la sappiamo calcolare noi. Costo: una SELECT sulla stessa tabella
		che stiamo per riscrivere, trascurabile accanto alle 6 pagine appena scaricate.
		La distinzione fra None (non lo so) e set() (nulla e' cambiato) e' importante: chi chiama deve
		poter ricadere sul refresh globale invece di concludere che non c'e' niente da aggiornare.
		"""
		before = self._watched_keys(db_type)
		if before is None: return None
		after = set()
		for row in insert_list:
			try: after.add((str(row[1]), str(row[2]), str(row[3])))
			except: return None
		return set(key[0] for key in (before ^ after))

	def set_bulk_movie_watched(self, insert_list):
		changed = self._changed_media_ids('movie', insert_list)
		self._delete(WATCHED_DELETE, ('movie',))
		self._executemany(WATCHED_INSERT, insert_list)
		return changed

	def set_bulk_tvshow_watched(self, insert_list):
		changed = self._changed_media_ids('episode', insert_list)
		self._delete(WATCHED_DELETE, ('episode',))
		self._executemany(WATCHED_INSERT, insert_list)
		return changed

	def set_bulk_movie_progress(self, insert_list):
		self._delete(PROGRESS_DELETE, ('movie',))
		self._executemany(PROGRESS_INSERT, insert_list)

	def set_bulk_tvshow_progress(self, insert_list):
		self._delete(PROGRESS_DELETE, ('episode',))
		self._executemany(PROGRESS_INSERT, insert_list)

	def add_tvshow_watched(self, insert_list):
		# used by the incremental sync: keeps the existing rows and refreshes last_played on rewatches
		self._executemany(WATCHED_UPSERT, insert_list)
		# Via incrementale: i titoli toccati sono esattamente quelli inseriti, senza bisogno di diff.
		try: return set(str(row[1]) for row in insert_list)
		except: return None

	def add_movie_watched(self, insert_list):
		# Gemella esatta di add_tvshow_watched, per la via incrementale dei film (lotto 107). Tiene le
		# righe esistenti e aggiorna last_played su una rivisione; i titoli toccati sono per costruzione
		# quelli inseriti, quindi il refresh mirato non ha bisogno di alcun confronto.
		self._executemany(WATCHED_UPSERT, insert_list)
		try: return set(str(row[1]) for row in insert_list)
		except: return None

	def watched_movie_count(self):
		# Quanti film risultano visti in locale. Serve al controllo di completezza della via
		# incrementale (lotto 108): la cronologia racconta gli AGGIUNTI, mai i RIMOSSI, e questo e'
		# l'unico modo di accorgersi di una riga sparita senza riscaricare tutto.
		try:
			dbcon = connect_database('trakt_db')
			return dbcon.execute("SELECT COUNT(*) FROM watched WHERE db_type = 'movie'").fetchone()[0]
		except: return None

	def watched_episode_count(self):
		# Gemella di watched_movie_count. Serve a separare 'in locale non c'e' niente' da 'non lo so':
		# last_watched_episode_date() restituisce None in entrambi i casi, e su quella distinzione si
		# decide se allinearsi a un vuoto di Trakt o lasciare tutto intatto.
		try:
			dbcon = connect_database('trakt_db')
			return dbcon.execute("SELECT COUNT(*) FROM watched WHERE db_type = 'episode'").fetchone()[0]
		except: return None

	def last_watched_movie_date(self):
		try:
			dbcon = connect_database('trakt_db')
			return dbcon.execute(WATCHED_LAST_PLAYED, ('movie',)).fetchone()[0]
		except: return None

	def last_watched_episode_date(self):
		try:
			dbcon = connect_database('trakt_db')
			return dbcon.execute(WATCHED_LAST_PLAYED, ('episode',)).fetchone()[0]
		except: return None

	def has_any_progress(self):
		try:
			dbcon = connect_database('trakt_db')
			return dbcon.execute('SELECT 1 FROM progress LIMIT 1').fetchone() is not None
		except: return False

	def has_progress_deletions(self, db_type, trakt_ids):
		try:
			dbcon = connect_database('trakt_db')
			local_ids = {row[0] for row in dbcon.execute('SELECT resume_id FROM progress WHERE db_type = ?', (db_type,)).fetchall()}
			return bool(local_ids - trakt_ids)
		except: return False

	def _executemany(self, command, insert_list):
		dbcon = connect_database('trakt_db')
		dbcon.executemany(command, insert_list)

	def _delete(self, command, args):
		# VACUUM is intentionally omitted here: called frequently during Trakt sync,
		# it would rewrite the entire DB after each bulk delete. Reclamation happens
		# in clear_all_trakt_cache_data after the full sync completes.
		dbcon = connect_database('trakt_db')
		dbcon.execute(command, args)

trakt_watched_cache = TraktWatched()

def cache_trakt_object(function, string, url):
	cache = trakt_cache.get(string)
	if cache: return cache
	result = function(url)
	trakt_cache.set(string, result)
	return result

def reset_activity(latest_activities):
	string = 'trakt_get_activity'
	try:
		dbcon = connect_database('trakt_db')
		row = dbcon.execute(TC_BASE_GET, (string,)).fetchone()
		cached_data = json.loads(row[0]) if row else default_activities()
		dbcon.execute(DELETE, (string,))
		trakt_cache.set(string, latest_activities)
	except: cached_data = default_activities()
	return cached_data

def restore_activity(previous_activities):
	"""Rimette il segnalibro delle attivita' al valore precedente.

	`reset_activity` lo fa avanzare SUBITO, prima che il lavoro a valle sia stato fatto. Se quel
	lavoro viene poi saltato, il cambiamento risulta gia' visto e non torna mai piu': al giro dopo il
	confronto fra ultimo e memorizzato da 'nessuna modifica'. Questa funzione serve a chi salta il
	lavoro per dichiararlo NON fatto, cosi' il giro successivo lo riprende. Vedi lotto 58.
	"""
	string = 'trakt_get_activity'
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE, (string,))
		trakt_cache.set(string, previous_activities)
		return True
	except: return False

def clear_daily_cache():
	clear_trakt_calendar()
	clear_continue_watching_cache()
	clear_trakt_list_contents_data('my_lists')
	clear_trakt_list_contents_data('liked_lists')
	clear_trakt_list_contents_data('user_lists')

def clear_trakt_hidden_data(list_type):
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE, ('trakt_hidden_items_%s' % list_type,))
	except: pass

def clear_trakt_collection_watchlist_data(list_type, media_type):
	if media_type == 'movies': media_type = 'movie'
	if media_type in ('tvshows', 'shows'): media_type = 'tvshow'
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE, ('trakt_%s_%s' % (list_type, media_type),))
	except: pass

def clear_trakt_calendar():
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE_LIKE, ('trakt_get_my_calendar_%',))
	except: pass

def clear_trakt_list_contents_data(list_type):
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE_LIKE, ('trakt_list_contents_' + list_type + '_%',))
	except: pass

def clear_trakt_list_data(list_type):
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE, ('trakt_%s' % list_type,))
	except: pass

def clear_trakt_recommendations():
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE_LIKE, ('trakt_recommendations_%',))
	except: pass

def clear_trakt_favorites():
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE_LIKE, ('trakt_favorites_%',))
	except: pass

def clear_continue_watching_cache():
	try:
		dbcon = connect_database('trakt_db')
		dbcon.execute(DELETE, ('trakt_continue_watching',))
	except: pass

def clear_all_trakt_cache_data(silent=False, refresh=True):
	try:
		if not silent and not confirm_dialog(): return False
		from caches.main_cache import main_cache
		main_cache_dbcon = connect_database('maincache_db')
		lists_with_media = main_cache_dbcon.execute(DELETE_LISTS_WITH_MEDIA, ('trakt_lists_with_media_%',)).fetchall()
		for item in lists_with_media:
			try: main_cache.delete(item[0])
			except: pass
		main_cache.clean_database()
		dbcon = connect_database('trakt_db')
		for table in ('trakt_data', 'progress', 'watched', 'watched_status'):
			dbcon.execute(BASE_DELETE % table)
		dbcon.execute('VACUUM')
		if refresh:
			from threading import Thread  # pigro, vedi la nota in caches/base_cache.py
			from apis.trakt_api import trakt_sync_activities
			Thread(target=trakt_sync_activities).start()
		return True
	except: return False

def default_activities():
	return {
		'all': '2024-01-22T00:22:21.000Z',
		'movies': {
			'watched_at': '2020-01-01T00:00:01.000Z', 'collected_at': '2020-01-01T00:00:01.000Z',
			'rated_at': '2020-01-01T00:00:01.000Z', 'watchlisted_at': '2020-01-01T00:00:01.000Z',
			'favorited_at': '2020-01-01T00:00:01.000Z', 'recommendations_at': '2020-01-01T00:00:01.000Z',
			'commented_at': '2020-01-01T00:00:01.000Z', 'paused_at': '2020-01-01T00:00:01.000Z',
			'hidden_at': '2020-01-01T00:00:01.000Z'
		},
		'episodes': {
			'watched_at': '2020-01-01T00:00:01.000Z', 'collected_at': '2020-01-01T00:00:01.000Z',
			'rated_at': '2020-01-01T00:00:01.000Z', 'watchlisted_at': '2020-01-01T00:00:01.000Z',
			'commented_at': '2020-01-01T00:00:01.000Z', 'paused_at': '2020-01-01T00:00:01.000Z'
		},
		'shows': {
			'rated_at': '2020-01-01T00:00:01.000Z', 'watchlisted_at': '2020-01-01T00:00:01.000Z',
			'favorited_at': '2020-01-01T00:00:01.000Z', 'recommendations_at': '2020-01-01T00:00:01.000Z',
			'commented_at': '2020-01-01T00:00:01.000Z', 'hidden_at': '2020-01-01T00:00:01.000Z'
		},
		'seasons': {
			'rated_at': '2020-01-01T00:00:01.000Z', 'watchlisted_at': '2020-01-01T00:00:01.000Z',
			'commented_at': '2020-01-01T00:00:01.000Z', 'hidden_at': '2020-01-01T00:00:01.000Z'
		},
		'comments': {
			'liked_at': '2020-01-01T00:00:01.000Z', 'blocked_at': '2020-01-01T00:00:01.000Z'
		},
		'lists': {
			'liked_at': '2020-01-01T00:00:01.000Z', 'updated_at': '2020-01-01T00:00:01.000Z',
			'commented_at': '2020-01-01T00:00:01.000Z'
		},
		'watchlist': {'updated_at': '2020-01-01T00:00:01.000Z'},
		'favorites': {'updated_at': '2020-01-01T00:00:01.000Z'},
		'recommendations': {'updated_at': '2020-01-01T00:00:01.000Z'},
		'collaborations': {'updated_at': '2020-01-01T00:00:01.000Z'},
		'account': {
			'settings_at': '2020-01-01T00:00:01.000Z', 'followed_at': '2020-01-01T00:00:01.000Z',
			'following_at': '2020-01-01T00:00:01.000Z', 'pending_at': '2020-01-01T00:00:01.000Z',
			'requested_at': '2020-01-01T00:00:01.000Z'
		},
		'saved_filters': {'updated_at': '2020-01-01T00:00:01.000Z'},
		'notes': {'updated_at': '2020-01-01T00:00:01.000Z'}
	}