# -*- coding: utf-8 -*-
"""L'ELENCO DEI FILE di un torrent e il VERDETTO su di esso (lotti 207 e 365, SORGENTI.md).

Lotto 207 -- la dimensione vera del singolo episodio dentro un pacchetto. La taglia che FenLight mostrava era
`pack_size / numero di episodi secondo TMDb`: un'invenzione, entro il +/-10% dal vero 8 volte su 31 sulla stick.
TorBox espone l'elenco dei file nella richiesta che gia' facciamo (`checkcached?format=list&list_files=true`).

Perche' una tabella e non `debrid_cache`. Sono due dati con due vite opposte. "Questo hash e' in cache" scade a
24 h perche' cambia davvero. "Questo hash contiene questi file" non scade mai: l'infohash e' l'impronta del
contenuto, se i file cambiassero cambierebbe l'hash. Si richiedono solo gli hash mai visti.

Lotto 365 -- il contenuto decide per tutti i media. Da qui:
- l'elenco (formato v2) tiene per ogni file (percorso, nome, byte): il percorso serve a riconoscere le cartelle
  `Sample/`, `Featurettes/`. Si tengono i video e gli archivi/eseguibili; un torrent SENZA video si scrive lo
  stesso, con i suoi file: e' il suo verdetto ("non si riproduce"), e prima si richiedeva a ogni ricerca;
- le righe v1 del lotto 207 (nome, byte) si leggono ancora: valgono per l'episodio nei pacchetti;
- il tetto e' a PESO (MAX_BYTE), non a righe: con film ed episodi singoli le righe crescono in fretta, ma un
  torrent a file singolo pesa ~150 byte;
- `verdetti`: l'esito del classificatore (modules/classificatore.py) per hash e domanda. L'elenco non cambia,
  quindi nemmeno il verdetto per la stessa domanda; la chiave contiene la versione delle regole.
"""
import json
import zlib
from caches.base_cache import connect_database

# Prova del 25/09 sera: con 8 MB in chiaro la tabella teneva 785 elenchi (10,4 KB di media), cioe' gli ultimi 3
# minuti di ricerche; una ricerca di film ne impara ~250. Ora gli elenchi si scrivono compressi (zlib: 1,2 KB di
# media, 8,6 volte meno; leggerli costa 18 us sul Mac, solo alla prima classificazione) e il tetto e' 16 MB
# compressi, ~14.000 elenchi. I verdetti non muoiono piu' con l'elenco: hanno il loro tetto, MAX_VERDETTI.
MAX_BYTE = 16 * 1024 * 1024
MAX_VERDETTI = 50000

LEGGI = 'SELECT hash, files FROM pack_files WHERE hash in (%s)'
SCRIVI = 'INSERT OR REPLACE INTO pack_files (hash, files, quando) VALUES (?, ?, ?)'
TOCCA = 'UPDATE pack_files SET quando=? WHERE hash in (%s)'
PESO = 'SELECT coalesce(sum(length(files)), 0) FROM pack_files'
PER_ETA = 'SELECT hash, length(files) FROM pack_files ORDER BY quando DESC'
VERDETTI_CREA = ('CREATE TABLE IF NOT EXISTS verdetti (hash text not null, chiave text not null, esito integer, '
				 'file text, byte integer, quando integer, unique (hash, chiave))')
VERDETTI_LEGGI = 'SELECT hash, esito, file, byte FROM verdetti WHERE chiave = ? AND hash in (%s)'
VERDETTI_SCRIVI = 'INSERT OR REPLACE INTO verdetti (hash, chiave, esito, file, byte, quando) VALUES (?, ?, ?, ?, ?, ?)'
VERDETTI_CONTA = 'SELECT count(*) FROM verdetti'
VERDETTI_POTA = 'DELETE FROM verdetti WHERE rowid NOT IN (SELECT rowid FROM verdetti ORDER BY quando DESC LIMIT ?)'
_verdetti_pronti = [False]
# LOTTO 416 -- l'hash OpenSubtitles dei video (SOTTOTITOLI.md). Tabella a parte: nelle tuple di pack_files il penultimo
# campo e' il nome (contiene_episodio, dimensione_episodio) e un campo in coda li romperebbe. Scritta nello stesso giro
# di scrivi(): TorBox lo da' in `files[].opensubtitles_hash`, gratis. Solo per gli hash letti DOPO il lotto: per gli
# altri resta il calcolo a Range (modules/sottotitoli_rete.py).
OSHASH_CREA = ('CREATE TABLE IF NOT EXISTS oshash_file (hash text not null, nome text not null, oshash text, quando integer, '
			   'unique (hash, nome))')
OSHASH_SCRIVI = 'INSERT OR REPLACE INTO oshash_file (hash, nome, oshash, quando) VALUES (?, ?, ?, ?)'
OSHASH_LEGGI = 'SELECT oshash FROM oshash_file WHERE hash = ? AND nome = ?'
OSHASH_CONTA = 'SELECT count(*) FROM oshash_file'
OSHASH_POTA = 'DELETE FROM oshash_file WHERE rowid NOT IN (SELECT rowid FROM oshash_file ORDER BY quando DESC LIMIT ?)'
MAX_OSHASH = 200000
_oshash_pronti = [False]


def _adesso():
	from time import time
	return int(time())

def _video():
	from modules.classificatore import VIDEO
	return VIDEO

def _archivi():
	from modules.classificatore import ARCHIVI
	return ARCHIVI


def _a_blocchi(dbcon, sql, lista, prima=()):
	"""Una query IN (...) a blocchi da 500: dal lotto 365 arrivano gli hash di TUTTI i risultati (migliaia), e
	SQLite vecchi hanno un tetto di 999 parametri per query."""
	righe = []
	for i in range(0, len(lista), 500):
		parte = lista[i:i + 500]
		righe.extend(dbcon.execute(sql % ', '.join('?' for _ in parte), list(prima) + parte).fetchall())
	return righe

def noti(hash_list):
	"""Gli hash di cui conosciamo gia' l'elenco dei file."""
	if not hash_list: return set()
	try:
		dbcon = connect_database('debridcache_db')
		return set(r[0] for r in _a_blocchi(dbcon, LEGGI, list(hash_list)))
	except: return set()


def _in_tuple(voci):
	"""Una riga letta -> [(percorso, nome, byte)]. La v1 (nome, byte) diventa (nome, nome, byte)."""
	fuori = []
	for v in voci:
		if len(v) == 3: fuori.append((v[0], v[1], v[2]))
		elif len(v) == 2: fuori.append((v[0], v[0], v[1]))
	return fuori

def leggi(hash_list):
	"""hash -> [(percorso, nome, byte), ...] per gli hash richiesti. Silenzioso su qualunque errore."""
	if not hash_list: return {}
	try:
		dbcon = connect_database('debridcache_db')
		fuori = {}
		for h, blob in _a_blocchi(dbcon, LEGGI, list(hash_list)):
			try: fuori[h] = _in_tuple(json.loads(zlib.decompress(blob) if isinstance(blob, bytes) else blob))
			except: pass
		if fuori:
			# `quando` serve solo alla potatura: segna che questi hash servono ancora.
			try: _a_blocchi(dbcon, TOCCA, list(fuori), (_adesso(),))
			except: pass
		return fuori
	except: return {}


def da_torbox(voce):
	"""Una voce di TorBox (con `files`) -> [(percorso, nome, byte)] da conservare: video e archivi; se non ci sono
	video, tutti i file (al piu' 20: bastano a dire cos'e', una colonna sonora, dei sottotitoli)."""
	video, archivi = _video(), _archivi()
	tutti = [((i.get('name') or i.get('short_name') or ''), (i.get('short_name') or ''), int(i.get('size') or 0))
			 for i in (voce.get('files') or [])]
	tenuti = [f for f in tutti if f[1].lower().endswith(video) or f[1].lower().endswith(archivi)]
	if not any(f[1].lower().endswith(video) for f in tenuti): tenuti = tutti[:20]
	return tenuti

def scrivi(voci):
	"""voci: iterabile di dizionari con 'hash' e 'files' come li restituisce TorBox. Ritorna quanti scritti."""
	righe, hashes = [], []
	quando = _adesso()
	for v in voci or []:
		try:
			h = (v.get('hash') or '').lower()
			if not h: continue
			f = da_torbox(v)
			if not f: continue
			righe.append((h, zlib.compress(json.dumps([list(x) for x in f], separators=(',', ':')).encode('utf-8'), 6), quando))
			video = _video()
			for i in v.get('files') or []:
				# per PERCORSO (name), non per nome del file (short_name): due video omonimi in cartelle diverse dello
				# stesso torrent (Disc1/.../00001.m2ts, Disc2/.../00001.m2ts) si scambiavano l'hash (code review 30/09)
				nome, percorso, oh = i.get('short_name') or '', i.get('name') or i.get('short_name') or '', i.get('opensubtitles_hash')
				if oh and nome.lower().endswith(video): hashes.append((h, percorso, oh, quando))
		except: continue
	if not righe: return 0
	try:
		dbcon = connect_database('debridcache_db')
		dbcon.executemany(SCRIVI, righe)
		if hashes:
			try:
				_crea_oshash(dbcon)
				dbcon.executemany(OSHASH_SCRIVI, hashes)
			except: pass
		return len(righe)
	except: return 0


def _crea_oshash(dbcon):
	# Come _crea_verdetti: i debridcache.db esistenti la ricevono al primo uso, non nel controllo di integrita'.
	if _oshash_pronti[0]: return
	dbcon.execute(OSHASH_CREA)
	_oshash_pronti[0] = True


def oshash(info_hash, nome):
	"""L'hash OpenSubtitles del video `nome` (il PERCORSO nel torrent, `name` di TorBox) se TorBox l'ha dato. None
	altrimenti. Le righe scritte prima della correzione, per short_name, qui non si trovano piu': l'hash si calcola."""
	if not info_hash or not nome: return None
	try:
		dbcon = connect_database('debridcache_db')
		_crea_oshash(dbcon)
		r = dbcon.execute(OSHASH_LEGGI, ((info_hash or '').lower(), nome)).fetchone()
		return r[0] if r else None
	except: return None


def nome_per_dimensione(info_hash, dimensione):
	"""Lotto 420 -- il percorso del video del torrent che pesa esattamente `dimensione` byte (il Content-Range del file che
	si riproduce), se e' uno solo. Il resolver non dice quale file ha scelto; la dimensione esatta lo identifica senza
	uno stato in piu'. None se l'elenco non c'e' o se due video pesano uguale."""
	if not info_hash or not dimensione: return None
	h = info_hash.lower()
	video = _video()
	percorsi = [p for p, n, b in leggi([h]).get(h, ()) if b == dimensione and n.lower().endswith(video)]
	return percorsi[0] if len(percorsi) == 1 else None


def manutenzione():
	"""Tiene gli elenchi sotto MAX_BYTE buttando i meno usati di recente, e i verdetti sotto MAX_VERDETTI.

	Non e' una scadenza: una riga vecchia non e' sbagliata, e' solo poco richiesta. Se torna a servire si
	riscarica. Niente VACUUM: riscriverebbe l'intero file per liberare qualche pagina che SQLite riuserebbe
	da sola (lotto 205, i 13,5 secondi di external.db).
	"""
	try:
		dbcon = connect_database('debridcache_db')
		_crea_verdetti(dbcon)
		if dbcon.execute(VERDETTI_CONTA).fetchone()[0] > MAX_VERDETTI: dbcon.execute(VERDETTI_POTA, (MAX_VERDETTI,))
		try:
			_crea_oshash(dbcon)
			if dbcon.execute(OSHASH_CONTA).fetchone()[0] > MAX_OSHASH: dbcon.execute(OSHASH_POTA, (MAX_OSHASH,))
		except: pass
		if dbcon.execute(PESO).fetchone()[0] <= MAX_BYTE: return 0
		somma, via = 0, []
		for h, peso in dbcon.execute(PER_ETA).fetchall():
			somma += peso or 0
			if somma > MAX_BYTE: via.append(h)
		for i in range(0, len(via), 500):
			parte = via[i:i + 500]
			dbcon.execute('DELETE FROM pack_files WHERE hash in (%s)' % ', '.join('?' for _ in parte), parte)
		return len(via)
	except: return 0


def _crea_verdetti(dbcon):
	# La tabella nasce con make_databases (base_cache), ma debridcache.db esistenti ne sono senza fino al riavvio:
	# si crea qui al primo uso. NON sta nel controllo di integrita': li' una tabella mancante fa cancellare il db.
	if _verdetti_pronti[0]: return
	dbcon.execute(VERDETTI_CREA)
	_verdetti_pronti[0] = True

def leggi_verdetti(hash_list, chiave):
	"""hash -> (esito, percorso del file nel torrent, byte) per la domanda `chiave`."""
	if not hash_list: return {}
	try:
		dbcon = connect_database('debridcache_db')
		_crea_verdetti(dbcon)
		return dict((h, (bool(esito), nome, byte)) for h, esito, nome, byte in _a_blocchi(dbcon, VERDETTI_LEGGI, list(hash_list), (chiave,)))
	except: return {}

def scrivi_verdetti(chiave, verdetti):
	"""verdetti: {hash: (esito, file, motivo)} del classificatore; si scrivono solo quelli decisi."""
	righe, quando = [], _adesso()
	for h, (esito, f, motivo) in (verdetti or {}).items():
		if esito is None: continue
		# lotto 387: il PERCORSO (cartella radice compresa), non solo il nome del file: le regole sulla radice (lotti 378,
		# 385, 386) valgono anche dalla seconda ricerca. Prima alla ripetuta si perdevano i nomi offuscati riconosciuti dalla
		# radice ("fsi-oldboy.1080p.mkv") e I sette samurai teneva "The Magnificent Seven 1960"
		righe.append((h, chiave, 1 if esito else 0, f[0] if f else None, f[2] if f else None, quando))
	if not righe: return 0
	try:
		dbcon = connect_database('debridcache_db')
		_crea_verdetti(dbcon)
		dbcon.executemany(VERDETTI_SCRIVI, righe)
		return len(righe)
	except: return 0


def contiene_episodio(files, season, episode, absolute=None):
	"""Il pacchetto contiene un file riproducibile per questo episodio? True, False, o None se non si sa.

	La stessa scelta di resolve_magnet (file_dell_episodio, lotto 362). `files`: tuple il cui penultimo campo e'
	il nome e l'ultimo i byte (v1 o v2).
	"""
	if not files: return None
	try:
		from modules.source_utils import file_dell_episodio
		return bool(file_dell_episodio(files, season, episode, absolute, lambda f: f[-2], lambda f: f[0] if len(f) > 2 else ''))
	except: return None

def dimensione_episodio(files, season, episode, absolute=None):
	"""Byte del file che corrisponde a questo episodio, o None (la stessa scelta del resolver)."""
	try:
		from modules.source_utils import file_dell_episodio
		scelti = file_dell_episodio(files, season, episode, absolute, lambda f: f[-2], lambda f: f[0] if len(f) > 2 else '')
		if scelti: return scelti[0][-1]
	except: pass
	return None
