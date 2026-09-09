# -*- coding: utf-8 -*-
# MISURE DELLE RIPRODUZIONI -- ingresso del wizard della banda (lotto 201).
#
# PERCHE' ESISTE. Le misure della connessione esistono SOLO durante una riproduzione: il wizard non
# puo' misurare su richiesta, perche' per farlo dovrebbe o far aspettare l'utente -- ed e' la sonda
# buttata nei lotti 191-195 -- o indovinare. Quindi questo non e' un comodo, e' l'organo di senso del
# wizard, e resta anche dopo la prima taratura: la portata misurata va da 13,5 a 21,4 Mbit/s e il cdn
# e' gia' cambiato una volta questo mese. Un numero fisso invecchia.
#
# FINESTRA SCORREVOLE, NON ARCHIVIO. Una misura di tre mesi fa, con un altro cdn e un altro wi-fi,
# non descrive piu' niente e sporcherebbe il percentile. Si tengono le ultime MAX_RIGHE.
#
# NULL SIGNIFICA "NON MISURATO". Ogni colonna puo' essere NULL, e il wizard deve distinguere "non
# misurato" da "misurato zero": e' la distinzione che nei lotti 191-198 e' costata due sonde e una
# raccomandazione sbagliata. Chi legge queste righe non deve mai trattare un None come uno zero.
from caches.base_cache import connect_database

MAX_RIGHE = 50

COLONNE = ('quando', 'cdn', 'dimensione', 'durata', 'bitrate', 'salti', 'portata_prima',
		   'portata_dopo', 'cache_media_prima', 'cache_max_prima', 'cache_media_dopo',
		   'cache_max_dopo', 'secondi_a_zero', 'campioni',
		   # Lotto 202: la forma del flusso, non la sua velocita'. Una riga con esito non NULL e' una
		   # riproduzione che NON e' avvenuta -- va letta come un guasto, non come una misura di banda,
		   # e il wizard deve escluderla dal percentile.
		   'larghezza', 'altezza', 'codec', 'esito',
		   # Identita' della sorgente. 'nome' non dice niente sulla banda ed e' li' per un'altra
		   # domanda: quale pacco o quale gruppo di rilascio ha funzionato, per riscegliere lo stesso.
		   # 'dimensione_dichiarata' si legge solo insieme a 'provider' e 'pacchetto': vedi base_cache.
		   'nome', 'dimensione_dichiarata', 'provider', 'pacchetto')


def registra(**campi):
	"""Scrive una riga e pota la finestra. Non solleva mai: una misura persa non deve poter
	disturbare la chiusura di una riproduzione."""
	try:
		valori = [campi.get(_c) for _c in COLONNE]
		dbcon = connect_database('playback_db')
		dbcon.execute('INSERT INTO playback_stats (%s) VALUES (%s)'
					  % (', '.join(COLONNE), ', '.join('?' * len(COLONNE))), valori)
		# La potatura sta qui e non in una pulizia periodica: e' una riga di SQL su una tabella da
		# cinquanta righe, e cosi' non esiste un percorso in cui la tabella cresce senza limite.
		dbcon.execute('DELETE FROM playback_stats WHERE id NOT IN '
					  '(SELECT id FROM playback_stats ORDER BY id DESC LIMIT ?)', (MAX_RIGHE,))
		dbcon.commit()
		return True
	except: return False


def recenti(limite=MAX_RIGHE):
	"""Le ultime righe, dalla piu' recente. Lista di dizionari, valori mancanti a None."""
	try:
		dbcon = connect_database('playback_db')
		righe = dbcon.execute('SELECT %s FROM playback_stats ORDER BY id DESC LIMIT ?'
							  % ', '.join(COLONNE), (limite,)).fetchall()
		return [dict(zip(COLONNE, _r)) for _r in righe]
	except: return []


def quante():
	try:
		dbcon = connect_database('playback_db')
		return dbcon.execute('SELECT COUNT(*) FROM playback_stats').fetchone()[0]
	except: return 0


def svuota():
	try:
		dbcon = connect_database('playback_db')
		dbcon.execute('DELETE FROM playback_stats')
		dbcon.commit()
		return True
	except: return False


# ---- LISTA NERA -------------------------------------------------------------------------------
# Rete di sicurezza per cio' che la sonda dell'intestazione NON riesce a leggere: contenitori che non
# parsiamo, moov in coda al file, guasti che non c'entrano con la dimensione del fotogramma. Vive in
# una tabella a parte perche' playback_stats si pota a 50 righe (vedi base_cache).
#
# La chiave e' provider|nome e non il link: il link risolto cambia a ogni tentativo -- lo stesso file
# e' arrivato come .../dld/f6445631-... e poi .../dld/f2f629a4-... -- mentre il nome no.

def chiave(item):
	try:
		if not item: return None
		nome = item.get('name') or item.get('display_name')
		if not nome: return None
		return '%s|%s' % (item.get('scrape_provider') or '?', nome)
	except: return None


def boccia(ch, nome=None, provider=None, motivo=None):
	"""Segna una sorgente come non riproducibile. Va chiamata PRIMA di fermare il player: se il
	guasto e' quello dell'08/09, dopo il player non c'e' piu' nessun processo che possa scrivere."""
	try:
		if not ch: return False
		from time import time as _adesso
		dbcon = connect_database('playback_db')
		vecchie = dbcon.execute('SELECT volte FROM sorgenti_bocciate WHERE chiave = ?', (ch,)).fetchone()
		dbcon.execute('INSERT OR REPLACE INTO sorgenti_bocciate (chiave, nome, provider, quando, motivo, volte) '
					  'VALUES (?, ?, ?, ?, ?, ?)',
					  (ch, nome, provider, int(_adesso()), motivo, (vecchie[0] if vecchie else 0) + 1))
		dbcon.commit()
		return True
	except: return False


def bocciata(ch):
	"""Il motivo se e' in lista nera, None altrimenti. Nel dubbio None: un errore di lettura del
	database non deve togliere all'utente una sorgente buona."""
	try:
		if not ch: return None
		riga = connect_database('playback_db').execute(
			'SELECT motivo FROM sorgenti_bocciate WHERE chiave = ?', (ch,)).fetchone()
		return (riga[0] or 'sconosciuto') if riga else None
	except: return None


def bocciate():
	try:
		righe = connect_database('playback_db').execute(
			'SELECT chiave, nome, provider, quando, motivo, volte FROM sorgenti_bocciate ORDER BY quando DESC').fetchall()
		return [dict(zip(('chiave','nome','provider','quando','motivo','volte'), _r)) for _r in righe]
	except: return []


def riabilita(ch=None):
	"""Senza argomenti svuota la lista. Serve all'utente, e serve a noi quando una bocciatura si
	rivela sbagliata: una lista nera senza modo di tornare indietro e' una trappola."""
	try:
		dbcon = connect_database('playback_db')
		if ch: dbcon.execute('DELETE FROM sorgenti_bocciate WHERE chiave = ?', (ch,))
		else: dbcon.execute('DELETE FROM sorgenti_bocciate')
		dbcon.commit()
		return True
	except: return False
