# -*- coding: utf-8 -*-
import json
from caches import progress_sync
from caches.base_cache import connect_database
from modules.kodi_utils import sleep, confirm_dialog, close_all_dialog, logger

SELECT = 'SELECT id FROM trakt_data'
DELETE = 'DELETE FROM trakt_data WHERE id=?'
DELETE_LIKE = 'DELETE FROM trakt_data WHERE id LIKE ?'
WATCHED_INSERT = 'INSERT OR IGNORE INTO watched VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_UPSERT = 'INSERT OR REPLACE INTO watched VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_LAST_PLAYED = 'SELECT MAX(last_played) FROM watched WHERE db_type = ?'
WATCHED_DELETE = 'DELETE FROM watched WHERE db_type = ?'
PROGRESS_UPSERT = 'INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
PROGRESS_DELETE_ONE = 'DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?'
PROGRESS_SELECT_ALL = ('SELECT media_id, season, episode, resume_point, curr_time, last_played, resume_id, title, '
						'sync_state, misses FROM progress WHERE db_type = ?')
# I lettori che disegnano lo schermo NON devono vedere le righe che stiamo cancellando: sono gia'
# sparite per l'utente, e restano in tabella solo finche' Trakt non conferma. Vedi progress_sync.
PROGRESS_VISIBLE = "sync_state != 'pending_delete'"
STATUS_INSERT = 'INSERT INTO watched_status VALUES (?, ?, ?)'
STATUS_DELETE = 'DELETE FROM watched_status'
BASE_DELETE = 'DELETE FROM %s'
TC_BASE_GET = 'SELECT data FROM trakt_data WHERE id = ?'
TC_BASE_SET = 'INSERT OR REPLACE INTO trakt_data (id, data) VALUES (?, ?)'
TC_BASE_DELETE = 'DELETE FROM trakt_data WHERE id = ?'
DELETE_LISTS_WITH_MEDIA = 'SELECT id FROM maincache WHERE id LIKE ?'

# Cancellazioni nostre che Trakt non ha ancora recepito, raccolte dalla riconciliazione perche' le
# rilanci chi ha il diritto di fare rete (apis.trakt_api). Fino al lotto 133 una DELETE remota fallita
# era una perdita silenziosa: la riga spariva in locale, restava su Trakt e tornava al giro dopo --
# il commento in _clear_progress_on_trakt la dava per persa senza rimedio.
PENDING_REMOTE_DELETES = []
# Scritture nostre che Trakt non ha MAI confermato: la spinta non e' passata (rete assente, token,
# eccezione ingoiata da _push_bookmark_to_trakt). Restano visibili in locale a tempo indeterminato --
# una pausa dell'utente non si cancella per un guasto di rete -- e vanno rispinte.
PENDING_REMOTE_PUSHES = []

def _norm(v):
	"""Stagione ed episodio come stringhe, con None e '' che diventano la stessa cosa.

	La chiave di un film e' (tmdb, '', ''); quella di un episodio (tmdb, '3', '4'). Senza questa
	normalizzazione la stessa riga letta dal database e quella costruita dallo snapshot non si
	riconoscono, e la riconciliazione le tratta come due righe diverse: una da inserire e una da
	cancellare.
	"""
	return '' if v in (None, '') else str(v)

def _uid(db_type, key):
	"""L'identita' che pubblica paginator: il tmdb nudo per i film, 'tmdb:stagione:episodio' per gli episodi."""
	if db_type == 'movie': return key[0]
	from modules.kodi_utils import episode_uid
	return episode_uid(key[0], key[1], key[2])

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

	def _set_bulk_watched(self, db_type, insert_list):
		# Stesso DELETE+INSERT della tabella progress, stessa finestra sporca, stessa cura: qui i
		# lettori sono gli indicatori di visto delle liste. Vedi _atomic.
		def _work():
			changed = self._changed_media_ids(db_type, insert_list)
			self._delete(WATCHED_DELETE, (db_type,))
			self._executemany(WATCHED_INSERT, insert_list)
			return changed
		return self._atomic(_work)

	def set_bulk_movie_watched(self, insert_list):
		return self._set_bulk_watched('movie', insert_list)

	def set_bulk_tvshow_watched(self, insert_list):
		return self._set_bulk_watched('episode', insert_list)

	def _local_progress(self, db_type):
		"""Le righe locali nella forma che vuole progress_sync: {chiave -> Local}.

		Ci sono TUTTE, comprese le pending_delete: la macchina a stati deve poterle vedere per
		decidere, ed e' l'unica che le guarda. Chi disegna usa PROGRESS_VISIBLE.
		"""
		try:
			dbcon = connect_database('trakt_db')
			rows = dbcon.execute(PROGRESS_SELECT_ALL, (db_type,)).fetchall()
		except: return None
		out = {}
		for r in rows:
			out[(str(r[0]), _norm(r[1]), _norm(r[2]))] = progress_sync.Local(
				str(r[3]), r[4], r[5], r[6] or 0, r[7], r[8] or progress_sync.SYNCED, r[9] or 0)
		return out

	def _reconcile_progress(self, db_type, insert_list):
		"""Allinea la tabella allo snapshot di Trakt applicando la tabella delle transizioni.

		Sostituisce la riscrittura in blocco (DELETE di tutto + INSERT della vista di Trakt + secondo
		INSERT delle righe da conservare). Quella aveva bisogno di una transazione per non far vedere
		la tabella vuota (lotto 124) e di due euristiche per non distruggere le scritture locali
		(lotti 122 e 128). Lavorando a DIFFERENZE non c'e' nessun istante in cui la riga manca, e non
		c'e' niente da proteggere: si tocca solo cio' che cambia davvero.

		La transazione resta, e ora costa quasi niente perche' le scritture sono poche.
		"""
		def _work():
			local = self._local_progress(db_type)
			if local is None: return None
			remote = {}
			for row in insert_list or ():
				remote[(str(row[1]), _norm(row[2]), _norm(row[3]))] = progress_sync.Remote(
					str(row[4]), row[5], row[6], row[7], row[8])
			plan = progress_sync.reconcile(local, remote)
			for u in plan.upserts:
				self._execute(PROGRESS_UPSERT, (db_type, u.key[0], u.key[1], u.key[2], u.resume_point,
												u.curr_time, u.last_played, u.resume_id, u.title,
												u.state, u.misses))
			for key in plan.deletes:
				self._execute(PROGRESS_DELETE_ONE, (db_type, key[0], key[1], key[2]))
			self._log_plan(db_type, local, remote, plan)
			if plan.retry_remote_delete: PENDING_REMOTE_DELETES.extend(
					(db_type, k, rid) for k, rid in plan.retry_remote_delete)
			if plan.retry_push: PENDING_REMOTE_PUSHES.extend((db_type, k) for k in plan.retry_push)
			return set(_uid(db_type, key) for key in plan.changed if _uid(db_type, key))
		return self._atomic(_work)

	def _log_plan(self, db_type, local, remote, plan):
		# UNA riga che dice cosa e' successo e PERCHE'. La vecchia DIAG diceva 'da Trakt N, conservate
		# M, prima X -> dopo Y' e per capire una sparizione bisognava dedurla dai conteggi. Qui si
		# leggono le transizioni, che sono la decisione vera.
		try:
			stati = {}
			for l in local.values(): stati[l.state] = stati.get(l.state, 0) + 1
			pezzi = ['da Trakt %s' % len(remote), 'in locale %s%s'
						% (len(local), (' (%s)' % ', '.join('%s %s' % (v, k) for k, v in sorted(stati.items()))) if stati else '')]
			if plan.upserts: pezzi.append('scritte %s' % len(plan.upserts))
			if plan.deletes: pezzi.append('TOLTE %s -> %s' % (len(plan.deletes),
									', '.join('%s' % (k[0] if not k[1] else '%s:%s:%s' % k) for k in plan.deletes[:6])))
			if plan.retry_remote_delete: pezzi.append('cancellazioni remote da rifare %s' % len(plan.retry_remote_delete))
			if plan.retry_push: pezzi.append('spinte mai confermate %s' % len(plan.retry_push))
			if plan.changed: pezzi.append('cambiate %s' % len(plan.changed))
			logger('Fen Light', 'DIAG progress %s: %s' % (db_type, ' | '.join(pezzi)))
		except: pass

	def set_bulk_movie_progress(self, insert_list):
		return self._reconcile_progress('movie', insert_list)

	def set_bulk_tvshow_progress(self, insert_list):
		return self._reconcile_progress('episode', insert_list)

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
			return dbcon.execute('SELECT 1 FROM progress WHERE %s LIMIT 1' % PROGRESS_VISIBLE).fetchone() is not None
		except: return False

	def has_progress_deletions(self, db_type, trakt_ids):
		"""Trakt ha tolto qualcosa che noi abbiamo? Una domanda sola, e la risposta e' nello stato.

		Contano SOLO le righe `synced`: quelle le abbiamo viste arrivare da Trakt, quindi la loro
		assenza dallo snapshot e' una cancellazione. Una `pending_put` non e' mai stata su Trakt per
		quanto ne sappiamo e la sua assenza non prova niente; una `pending_delete` l'abbiamo tolta noi.

		Fino al lotto 132 qui c'erano due esclusioni a tempo (resume_id != 0 del lotto 122 e la
		finestra di grazia del 128) che provavano a ricostruire proprio questa distinzione senza
		averla scritta da nessuna parte.
		"""
		try:
			dbcon = connect_database('trakt_db')
			rows = dbcon.execute("SELECT resume_id FROM progress WHERE db_type = ? AND sync_state = 'synced' AND resume_id != 0",
									(db_type,)).fetchall()
			return bool({r[0] for r in rows} - trakt_ids)
		except: return False

	def _atomic(self, fn):
		"""Esegue fn() in UNA transazione, cosi' nessun altro lettore vede lo stato intermedio.

		IL PROBLEMA (lotto 124). Le riscritture in blocco sono DELETE seguito da INSERT, e la
		connessione e' in autocommit (`isolation_level=None` in caches/base_cache). Ogni istruzione
		quindi si conferma da sola: fra la cancellazione e il reinserimento la tabella e'
		**realmente vuota per chiunque altro la legga**, e a meta' reinserimento e' parziale.
		Chi legge in quel momento sono proprio i costruttori che disegnano lo stato: il pannello
		episodi (get_bookmarks_episode -> nessun badge) e 'continua a guardare'
		(get_in_progress_episodes -> voce mancante).

		Misurato con due connessioni sullo stesso file, WAL, mentre gira una riscrittura da 7 righe:
		38 letture su 200 hanno visto ZERO righe, e la sequenza osservata e' stata 7 -> 0 -> 4 -> 7,
		cioe' anche uno stato PARZIALE. Con la transazione esplicita: 0 letture sporche, sequenza 7.

		E' la spiegazione strutturale dei sintomi intermittenti: non dipende da chi scrive, dipende
		da QUANDO qualcuno legge. Ecco perche' la stessa sequenza di azioni a volte funzionava.

		Ripiego: se la transazione non si puo' aprire (un altro scrittore la tiene oltre il timeout)
		si esegue lo stesso senza. Scrivere con una finestra sporca resta meglio che non scrivere.
		"""
		dbcon = connect_database('trakt_db')
		try: dbcon.execute('BEGIN IMMEDIATE')
		except: return fn()
		try:
			result = fn()
			dbcon.execute('COMMIT')
			return result
		except:
			try: dbcon.execute('ROLLBACK')
			except: pass
			return None

	def _execute(self, command, args):
		dbcon = connect_database('trakt_db')
		dbcon.execute(command, args)

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