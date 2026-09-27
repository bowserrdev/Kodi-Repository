# -*- coding: utf-8 -*-
"""I risultati di ogni provider per titolo (external.db, results_data).

LOTTO 369 (SORGENTI.md) -- si salva il risultato dello SCRAPER, non quello lavorato da process_sources (che rigira
alla lettura), senza il magnet quando e' del suo stesso hash (si ricostruisce), e la riga e' compressa (zlib). Nella
prova del 25/09 sera: 41 MB per 25 titoli; cosi' 3,6 MB. Le righe dei formati vecchi (JSON in chiaro, gia' lavorate;
zlib senza versione, con le etichette ASCII: lotto 387) si leggono come scadute.
"""
import json
import zlib
from caches.base_cache import connect_database, get_timestamp

MAGNET = 'magnet:?xt=urn:btih:%s&dn=%s'

def _compatta(results):
	"""Via il magnet se e' del suo hash: si ricostruisce. Anche i tracker: servono solo a chi scarica, e con TorBox
	si usano solo torrent gia' in cache (osservazione dell'utente, 26/09)."""
	fuori = []
	for i in results or []:
		try:
			h, u = (i.get('hash') or '').lower(), i.get('url') or ''
			if h and u.lower().startswith('magnet:') and ('btih:' + h) in u.lower():
				i = dict(i); i.pop('url', None)
		except: pass
		fuori.append(i)
	return fuori

# LOTTO 387 -- la versione del formato della riga. Le righe senza versione hanno le etichette di cocoscrapers ridotte ad ASCII
# ("Сталкер 1979" -> "1979"): si leggono come scadute, cosi' la correzione vale su ogni dispositivo senza cancellare a mano.
FORMATO = 2

def _riga(results):
	return {'v': FORMATO, 'r': _compatta(results)}

def _risultati(blob):
	"""I risultati di una riga compressa, o None se e' di un formato vecchio."""
	try: d = json.loads(zlib.decompress(blob))
	except Exception: return None
	if isinstance(d, dict) and d.get('v') == FORMATO: return _espandi(d.get('r') or [])
	return None

def _espandi(results):
	for i in results:
		if 'url' not in i and i.get('hash'): i['url'] = MAGNET % (i['hash'], i.get('name') or '')
	return results

SELECT_RESULTS = 'SELECT results, expires FROM results_data WHERE provider = ? AND db_type = ? AND tmdb_id = ? AND title = ? AND year = ? AND season = ? AND episode = ?'
DELETE_RESULTS = 'DELETE FROM results_data WHERE provider = ? AND db_type = ? AND tmdb_id = ? AND title = ? AND year = ? AND season = ? AND episode = ?'
INSERT_RESULTS = 'INSERT OR REPLACE INTO results_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
SINGLE_DELETE = 'DELETE FROM results_data WHERE db_type=? AND tmdb_id=?'
FULL_DELETE = 'DELETE FROM results_data'
CLEAN = 'DELETE from results_data WHERE CAST(expires AS INT) <= ?'

class ExternalCache:
	def leggi(self, source, media_type, tmdb_id, title, year, season, episode):
		"""(risultati, True) o (None, False). `grezzi` (lotto 369): i risultati dello scraper, da passare da process_sources."""
		try:
			row = connect_database('external_db').execute(SELECT_RESULTS, (source, media_type, tmdb_id, title, year, season, episode)).fetchone()
			if row:
				risultati = _risultati(row[0]) if isinstance(row[0], bytes) and row[1] > get_timestamp() else None
				if risultati is not None: return risultati, True
				self.delete(source, media_type, tmdb_id, title, season, episode)
		except: pass
		return None, False

	def set(self, source, media_type, tmdb_id, title, year, season, episode, results, expire_time):
		"""`results`: quelli dello scraper, PRIMA di process_sources."""
		try:
			expires = get_timestamp(expire_time)
			blob = zlib.compress(json.dumps(_riga(results), ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 6)
			connect_database('external_db').execute(INSERT_RESULTS, (source, media_type, tmdb_id, title, year, season, episode, blob, int(expires)))
		except: pass

	def delete(self, source, media_type, tmdb_id, title, season, episode):
		try:
			connect_database('external_db').execute(DELETE_RESULTS, (source, media_type, tmdb_id, title, season, episode))
		except: pass

	def delete_cache_single(self, media_type, tmdb_id):
		"""Cancella i risultati esterni di UN titolo. Niente VACUUM (lotto 205).

		VACUUM riscrive l'intero file da capo, e su questa macchina external.db pesa 53 MB: misurati
		l'08/09 **13,5 secondi di rotellina** per cancellare una riga. Non serviva a niente -- SQLite
		riusa da solo le pagine liberate, e VACUUM serve solo a rimpicciolire il file su disco. Resta
		dov'e' giusto che sia, cioe' nello svuotamento totale qui sotto.
		"""
		try:
			connect_database('external_db').execute(SINGLE_DELETE, (media_type, tmdb_id))
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

	def togli_scadute(self):
		"""Lotto 369: le righe scadute, all'avvio del servizio. Senza VACUUM (lotto 205): SQLite riusa le pagine."""
		try: return connect_database('external_db').execute(CLEAN, (get_timestamp(),)).rowcount
		except: return 0

external_cache = ExternalCache()