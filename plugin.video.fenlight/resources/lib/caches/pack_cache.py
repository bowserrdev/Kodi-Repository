# -*- coding: utf-8 -*-
"""LOTTO 207 -- la dimensione VERA del singolo episodio dentro un pacchetto.

Il problema. Un pacco non si riproduce: si riproduce un episodio che sta dentro. La dimensione
che FenLight mostrava e filtrava era `pack_size / numero di episodi secondo TMDb`, e non e' una
misura: e' un'invenzione. Misurato sui 31 pacchetti di sola stagione 1 realmente in cache sulla
stick, cade entro il +/-10% dal vero **8 volte su 31**. Il divisore giusto e' 41 per alcuni
torrent della stessa stagione e 20 per altri, perche' meta' dei gruppi mette i due segmenti di un
episodio in un file solo e meta' no: l'informazione non esiste nei metadati.

Dove sta invece. TorBox la espone, e nella richiesta che gia' facciamo:
`POST torrents/checkcached?format=list&list_files=true` restituisce per ogni hash in cache
l'elenco dei file con `short_name` e `size` in byte -- gli stessi campi che `resolve_magnet` usa
gia' con `seas_ep_filter`. Nessuna euristica nuova: qui si conserva l'elenco cosi' com'e' e la
corrispondenza episodio la fa la stessa funzione che la fa al momento di risolvere.

Perche' una tabella e non `debrid_cache`. Sono due dati con due vite opposte. "Questo hash e' in
cache" scade a 24 h perche' cambia davvero. "Questo hash contiene questi file" non scade mai:
l'infohash e' l'impronta del contenuto, se i file cambiassero cambierebbe l'hash. Tenerla
permanente e' cio' che permette di NON richiedere i file al rinnovo delle 24 ore: si richiedono
solo gli hash mai visti, e quasi sempre non ce n'e' nessuno.

Peso. 574 KB per i 55 torrent in cache di una serie molto cercata (misura reale). Il tetto sotto
tiene la tabella limitata buttando le righe toccate meno di recente.
"""
import json
from caches.base_cache import connect_database

# Sopra questo numero di righe la manutenzione taglia le meno recenti. 800 righe sono nell'ordine
# dei 5-8 MB, contro i 53 MB che external.db occupa gia' sulla stessa stick.
MAX_RIGHE = 800
ESTENSIONI = ('.mkv', '.mp4', '.avi', '.m4v', '.ts', '.m2ts', '.mov', '.wmv', '.mpg', '.mpeg')

LEGGI = 'SELECT hash, files FROM pack_files WHERE hash in (%s)'
SCRIVI = 'INSERT OR REPLACE INTO pack_files (hash, files, quando) VALUES (?, ?, ?)'
TOCCA = 'UPDATE pack_files SET quando=? WHERE hash in (%s)'
CONTA = 'SELECT count(*) FROM pack_files'
POTA = 'DELETE FROM pack_files WHERE hash NOT IN (SELECT hash FROM pack_files ORDER BY quando DESC LIMIT ?)'


def _adesso():
	from time import time
	return int(time())


def noti(hash_list):
	"""Gli hash di cui conosciamo gia' l'elenco dei file. Una query sola per tutta la lista."""
	if not hash_list: return set()
	try:
		dbcon = connect_database('debridcache_db')
		righe = dbcon.execute(LEGGI % (', '.join('?' for _ in hash_list)), list(hash_list)).fetchall()
		return set(r[0] for r in righe)
	except: return set()


def leggi(hash_list):
	"""hash -> [(nome, byte), ...] per gli hash richiesti. Silenzioso su qualunque errore."""
	if not hash_list: return {}
	try:
		dbcon = connect_database('debridcache_db')
		righe = dbcon.execute(LEGGI % (', '.join('?' for _ in hash_list)), list(hash_list)).fetchall()
		fuori = {}
		for h, blob in righe:
			try: fuori[h] = json.loads(blob)
			except: pass
		if fuori:
			# `quando` serve solo alla potatura: segna che questi hash servono ancora.
			try: dbcon.execute(TOCCA % (', '.join('?' for _ in fuori)), [_adesso()] + list(fuori))
			except: pass
		return fuori
	except: return {}


def scrivi(voci):
	"""voci: iterabile di dizionari con 'hash' e 'files' come li restituisce TorBox."""
	righe = []
	quando = _adesso()
	for v in voci or []:
		try:
			h = (v.get('hash') or '').lower()
			if not h: continue
			# Solo i file video: il resto (nfo, sottotitoli, campioni) non si riproduce e occuperebbe
			# spazio per niente.
			f = [[i['short_name'], int(i['size'])] for i in (v.get('files') or [])
				 if i.get('short_name', '').lower().endswith(ESTENSIONI)]
			if not f: continue
			righe.append((h, json.dumps(f, separators=(',', ':')), quando))
		except: continue
	if not righe: return 0
	try:
		dbcon = connect_database('debridcache_db')
		dbcon.executemany(SCRIVI, righe)
		return len(righe)
	except: return 0


def manutenzione():
	"""Tiene la tabella sotto MAX_RIGHE buttando le righe toccate meno di recente.

	Non e' una scadenza: una riga vecchia non e' sbagliata, e' solo poco richiesta. Se torna a
	servire si riscarica in una chiamata. Niente VACUUM: riscriverebbe l'intero file per liberare
	qualche pagina che SQLite riuserebbe da sola (lotto 205, i 13,5 secondi di external.db).
	"""
	try:
		dbcon = connect_database('debridcache_db')
		n = dbcon.execute(CONTA).fetchone()[0]
		if n <= MAX_RIGHE: return 0
		dbcon.execute(POTA, (MAX_RIGHE,))
		return n - MAX_RIGHE
	except: return 0


def dimensione_episodio(files, season, episode):
	"""Byte del file che corrisponde a questo episodio, o None.

	La corrispondenza la fa `seas_ep_filter`, la stessa che usa `resolve_magnet` per scegliere quale
	file del pacco sbloccare. Se scegliesse un file diverso da quello di cui mostriamo la
	dimensione, mostreremmo la dimensione di un altro episodio.
	"""
	try:
		from modules.source_utils import seas_ep_filter
		for nome, byte in files:
			if seas_ep_filter(season, episode, nome): return byte
	except: pass
	return None
