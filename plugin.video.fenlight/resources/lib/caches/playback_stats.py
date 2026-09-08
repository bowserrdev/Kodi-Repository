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
		   'cache_max_dopo', 'secondi_a_zero', 'campioni')


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
