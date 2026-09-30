# -*- coding: utf-8 -*-
"""La voce "Segna come visto / Segna come non visto" della stagione, che dice sempre lo stato vero (lotto 433).

IL DIFETTO. Dal lotto 427 la lista stagioni non si ricostruisce piu' a ogni "segna come visto": lo stato che
cambia lo porta il pannello episodi. La voce del menu contestuale della stagione pero' la scriveva il
costruttore, una volta: una fotografia dello stato visto in quel momento, che sarebbe invecchiata alla prima
marcatura. Per non mentire il 427 aveva messo SEMPRE entrambe le voci. Funziona, ma non e' coerente con gli
episodi, che (ricostruiti a ogni cambio) mostrano la voce giusta sola.

DA DOVE SI CORREGGE. Con lo stesso trucco della voce della watchlist (modules/watchlist_label.py): la voce non
scrive il proprio testo, lo CHIEDE --

    [B]$INFO[Window(Home).Property(fenlight.cm.stagione)][/B]

-- e la proprieta' la tiene giusta il watcher del servizio per la stagione a fuoco. L'AZIONE non si fida
dell'etichetta: watched_status.mark_season con action=alterna rilegge lo stato al clic, con la stessa regola.

LA REGOLA, una sola (tutti_visti): "Segna come non visto" se gli episodi visti della stagione coprono tutti
quelli usciti, altrimenti "Segna come visto". E' la regola con cui la lista stagioni dichiara una stagione vista
(watched_status.get_watched_status_season: playcount 1 quando i visti arrivano agli usciti), e gli usciti sono
il `totalepisodes` della voce, cioe' watched_status.episodi_usciti_stagione.

QUANDO SI RICALCOLA. Quando cambia l'elemento a fuoco, e quando cambiano i visti. Il secondo segnale e' un file
in addon_data (STAMP_FILE), toccato da ogni scrittura dei visti: le marcature locali (watched_status) e le
fotografie di Trakt scritte davvero (caches.trakt_cache). Un file e non una proprieta' di finestra per la
stessa ragione della watchlist: il watcher lo legge a ogni giro, e getProperty prende il lock grafico.
"""
import os

PROP = 'fenlight.cm.stagione'
LABEL_VISTO = 'Segna come visto'
LABEL_NON_VISTO = 'Segna come non visto'
DYNAMIC_LABEL = '[B]$INFO[Window(Home).Property(%s)][/B]' % PROP
STAMP_FILE = 'visti.stamp'


def tutti_visti(visti, usciti):
	"""La stagione e' tutta vista? `visti` sono le righe viste della stagione, `usciti` gli episodi usciti."""
	return bool(usciti) and visti >= usciti


def _stamp_path():
	from modules.kodi_utils import addon_profile
	return os.path.join(addon_profile(), STAMP_FILE)


def bump():
	"""I visti sono cambiati. Lo chiama chi li scrive, in qualunque interprete giri."""
	from time import time
	try:
		with open(_stamp_path(), 'w', encoding='utf-8') as handle: handle.write(repr(time()))
	except Exception: pass


def read_stamp():
	try:
		with open(_stamp_path(), 'r', encoding='utf-8') as handle: return handle.read()
	except Exception: return ''


def conta_visti(tmdb_id, season):
	"""Le righe viste di una stagione, dal database degli indicatori in uso. None se non si puo' sapere."""
	try:
		from modules.watched_status import get_database
		return get_database().execute("SELECT COUNT(*) FROM watched WHERE db_type = 'episode' AND media_id = ? AND season = ?",
										(str(tmdb_id), int(season))).fetchone()[0]
	except Exception: return None


class Tracker:
	"""Stato del watcher: quale stagione ha gia' servito e con quale versione dei visti."""

	def __init__(self, loader=conta_visti, stamp_reader=read_stamp, log=None):
		self.loader, self.stamp_reader, self.log = loader, stamp_reader, log
		self.item, self.stamp = None, None

	def update(self, control_id, get_infolabel, window):
		"""Un giro del watcher. Torna l'etichetta scritta, o None se non c'era niente da fare.

		Come watchlist_label.Tracker: il path dell'elemento a fuoco dice se e' cambiato; tipo, tmdb_id, stagione e
		usciti si chiedono solo allora. Un elemento che non e' una stagione con tmdb_id non tocca la proprieta'.
		"""
		if not control_id: return None
		item = 'Container(%s).ListItem.' % control_id
		path = get_infolabel(item + 'FolderPath')
		if not path: return None
		stamp = self.stamp_reader()
		if path == self.item and stamp == self.stamp: return None
		self.item, self.stamp = path, stamp
		if get_infolabel(item + 'DBType') != 'season': return None
		tmdb_id, season = get_infolabel(item + 'UniqueID(tmdb)'), get_infolabel(item + 'Season')
		try: usciti = int(get_infolabel(item + 'Property(totalepisodes)') or 0)
		except ValueError: usciti = 0
		if not tmdb_id or not season or not usciti: return None
		visti = self.loader(tmdb_id, season)
		if visti is None: return None
		label = LABEL_NON_VISTO if tutti_visti(visti, usciti) else LABEL_VISTO
		if window.getProperty(PROP) != label: window.setProperty(PROP, label)
		if self.log: self.log('visti_label stagione %s S%s -> %s | visti %s su %s | segnale %s'
								% (tmdb_id, season, label, visti, usciti, (self.stamp or '-')[:14]))
		return label
