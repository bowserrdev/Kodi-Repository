# -*- coding: utf-8 -*-
"""Lotto 420 (SOTTOTITOLI.md) -- i sottotitoli sincronizzati gia' decisi per un file.

Chiave = hash OpenSubtitles del file (o infohash:dimensione se l'hash non c'e') + lingua. Una riga dice:
- il sottotitolo accettato (file_id) e il suo testo GIA' ALLINEATO, compresso: una ripresa lo applica subito, senza
  ricerca, download ne' allineamento (verifica V3);
- i file_id gia' rifiutati per quel file, per non riscaricarli (ogni download costa quota).

Il testo sta nel database e non come percorso di un file in special://temp: un file temporaneo che sparisce
costerebbe un download alla ripresa. Compresso un srt pesa ~25-35 KB: MAX_RIGHE ne tiene ~6 MB, cioe' le ultime
200 riproduzioni con sottotitoli automatici; una ripresa dopo la potatura rifa' il giro, non sbaglia.
Tabella in playback.db, creata al primo uso e da make_databases, fuori dal controllo di integrita' (li' una tabella
mancante fa cancellare il database), come verdetti e oshash_file.
"""
import json
import zlib
from caches.base_cache import connect_database

MAX_RIGHE = 200
CREA = ('CREATE TABLE IF NOT EXISTS sottotitoli (chiave text not null, lingua text not null, file_id integer, srt blob, '
		'esito text, rifiutati text, quando integer, unique (chiave, lingua))')
LEGGI = 'SELECT file_id, srt, esito, rifiutati FROM sottotitoli WHERE chiave = ? AND lingua = ?'
SCRIVI = ('INSERT OR REPLACE INTO sottotitoli (chiave, lingua, file_id, srt, esito, rifiutati, quando) '
		  'VALUES (?, ?, ?, ?, ?, ?, ?)')
POTA = 'DELETE FROM sottotitoli WHERE rowid NOT IN (SELECT rowid FROM sottotitoli ORDER BY quando DESC LIMIT ?)'
_pronta = [False]


def _db():
	dbcon = connect_database('playback_db')
	if not _pronta[0]:
		dbcon.execute(CREA)
		_pronta[0] = True
	return dbcon


def leggi(chiave, lingua):
	"""{'file_id', 'srt' (testo o None), 'esito' (dict), 'rifiutati' (set)} o None."""
	if not chiave or not lingua: return None
	try:
		r = _db().execute(LEGGI, (chiave, lingua)).fetchone()
		if not r: return None
		return {'file_id': r[0], 'srt': zlib.decompress(r[1]).decode('utf-8') if r[1] else None,
				'esito': json.loads(r[2] or '{}'), 'rifiutati': set(json.loads(r[3] or '[]'))}
	except: return None


def scrivi(chiave, lingua, file_id=None, srt=None, esito=None, rifiutati=()):
	"""Sostituisce la riga. `esito`: i numeri per il log (metodo, copertura, precisione, buchi). Potatura per eta'."""
	if not chiave or not lingua: return False
	try:
		from time import time
		dbcon = _db()
		dbcon.execute(SCRIVI, (chiave, lingua, file_id, zlib.compress(srt.encode('utf-8'), 6) if srt else None,
							   json.dumps(esito or {}), json.dumps(sorted(rifiutati or ())), int(time())))
		dbcon.execute(POTA, (MAX_RIGHE,))
		return True
	except: return False
