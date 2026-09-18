# -*- coding: utf-8 -*-
"""La voce "Aggiungi/Rimuovi dalla watchlist" che dice sempre lo stato vero (18/09/2026).

IL DIFETTO. La voce del menu contestuale la scrive il costruttore della lista, una volta, quando la riga
si costruisce: e' una fotografia dell'appartenenza alla watchlist in quel momento. Dal lotto 312 un
clic sulla watchlist ricostruisce solo il widget della watchlist (le altre righe con lo stesso titolo
costavano centinaia di elementi per un'etichetta), quindi nelle altre righe la fotografia invecchia:
l'azione resta giusta -- watchlist_toggle rilegge l'appartenenza al clic -- ma l'etichetta mente.

DA DOVE SI CORREGGE. Dall'elemento che si porta dietro uno stato che cambia. Kodi analizza le etichette
delle voci di un addon come quelle della skin: ContextMenuManager.cpp:307-311 le passa cosi' come sono,
GUIDialogContextMenu.cpp:140 le da' a CGUIButtonControl::SetLabel, che finisce in
CGUIInfoLabel::SetLabel -> Parse (GUIInfoLabel.cpp:38-41): `$INFO[...]` si risolve, e il pulsante lo
rivaluta a ogni giro di rendering. Quindi la voce non scrive il proprio testo, lo CHIEDE:

    [B]$INFO[Window(Home).Property(fenlight.cm.watchlist)][/B]

e la proprieta' la tiene giusta il watcher del servizio. Una proprieta' sola, non una per titolo: dice
lo stato dell'elemento a fuoco, che e' l'unico su cui il menu si puo' aprire.

DOVE VALE. Ovunque, per costruzione: ogni elemento film o serie di Fen Light porta l'etichetta viva, e
il watcher legge `Container(<System.CurrentControlID>).ListItem.*`. Entrambe le infolabel si risolvono
contro la finestra o il dialogo in primo piano, quindi riga di home, hub o ricerca, righe della scheda
informazioni e cartelle di Fen Light sono lo stesso caso. NON `ListItem.*` senza contenitore: nella
scheda informazioni (DialogVideoInfo) quello e' il titolo della scheda, non l'elemento a fuoco nelle sue
righe -- misurato sul Mac il 18/09, il watcher ricalcolava sempre il film della scheda. Fino al 18/09
sera il contenitore era quello della riga seguita dal paginatore, e la scheda, modale, restava fuori.
L'unico momento in cui la proprieta' NON si tocca e' col menu contestuale aperto: deve restare quella
dell'elemento su cui il menu si e' aperto (vedi service.py, CONTEXT_MENU_DIALOG).

QUANDO SI RICALCOLA. Quando cambia l'elemento a fuoco, e quando cambia la watchlist. Il secondo segnale
e' un file in addon_data scritto da trakt_api.rinnova_watchlist, che e' il punto da cui passa OGNI
cambio -- clic, sincronizzazione con Trakt, "segna come visto" -- e che gira in interpreti diversi dal
servizio. Un file e non una proprieta' di finestra perche' il watcher lo legge a ogni giro, e
getProperty prende il lock grafico (vedi settings_cache, lotto 323); aprire un file di pochi byte no.

L'insieme della watchlist si legge dalla copia in cache, MAI dalla rete: il watcher e' il ciclo del
paginatore e una chiamata a Trakt lo fermerebbe. Una copia mancante vale "vuota" ma non si ricorda,
cosi' il primo giro dopo che una costruzione l'ha riempita la ritrova.
"""
import os

PROP = 'fenlight.cm.watchlist'
LABEL_IN = 'Rimuovi dalla mia lista'
LABEL_OUT = 'Aggiungi alla mia lista'
DYNAMIC_LABEL = '[B]$INFO[Window(Home).Property(%s)][/B]' % PROP
STAMP_FILE = 'watchlist.stamp'
MEDIA_TYPES = {'movie': 'movie', 'tvshow': 'tvshow'}


def _stamp_path():
	from modules.kodi_utils import addon_profile
	return os.path.join(addon_profile(), STAMP_FILE)


def bump():
	"""La watchlist e' cambiata. Lo chiama rinnova_watchlist, in qualunque interprete giri."""
	from time import time
	try:
		with open(_stamp_path(), 'w', encoding='utf-8') as handle: handle.write(repr(time()))
	except Exception: pass


def read_stamp():
	try:
		with open(_stamp_path(), 'r', encoding='utf-8') as handle: return handle.read()
	except Exception: return ''


def cached_ids(media_type):
	"""tmdb_id della watchlist dalla copia in cache, senza rete. None se la copia non c'e'."""
	from caches.trakt_cache import trakt_cache
	data = trakt_cache.get('trakt_watchlist_%s' % media_type)
	# None = copia assente; [] = watchlist vuota, che e' un dato vero e si ricorda (un account nuovo
	# la ha vuota: senza questa distinzione si rileggerebbe il database a ogni spostamento del fuoco).
	if data is None: return None
	return {str(i['media_ids']['tmdb']) for i in data if i.get('media_ids', {}).get('tmdb')}


class Tracker:
	"""Stato del watcher: quale elemento ha gia' servito e con quale versione della watchlist."""

	def __init__(self, loader=cached_ids, stamp_reader=read_stamp, log=None):
		self.loader, self.stamp_reader, self.log = loader, stamp_reader, log
		self.item, self.stamp, self.sets = None, None, {}

	def update(self, control_id, get_infolabel, window):
		"""Un giro del watcher. Torna l'etichetta scritta, o None se non c'era niente da fare.

		`control_id` e' System.CurrentControlID, gia' letto dal watcher. Una lettura a giro, il path
		dell'elemento a fuoco in quel controllo: e' la chiave per capire se l'elemento e' cambiato, e a
		differenza del tmdb_id distingue anche un film e una serie con lo stesso numero (le due
		numerazioni TMDb sono indipendenti). Tipo e tmdb_id si chiedono solo quando qualcosa e' cambiato.
		Un controllo che non e' un contenitore (pulsanti) e un elemento che non e' un film o una serie con
		tmdb_id (episodi, cartelle, voci del menu) non toccano la proprieta'."""
		if not control_id: return None
		item = 'Container(%s).ListItem.' % control_id
		path = get_infolabel(item + 'FolderPath')
		if not path: return None
		stamp = self.stamp_reader()
		if path == self.item and stamp == self.stamp: return None
		if stamp != self.stamp: self.sets.clear(); self.stamp = stamp
		self.item = path
		media_type = MEDIA_TYPES.get(get_infolabel(item + 'DBType'))
		if not media_type: return None
		tmdb_id = get_infolabel(item + 'UniqueID(tmdb)')
		if not tmdb_id: return None
		ids, copia = self.sets.get(media_type), 'memoria'
		if ids is None:
			ids = self.loader(media_type)
			if ids is None: ids, copia = set(), 'ASSENTE'
			else: self.sets[media_type], copia = ids, 'cache'
		label = LABEL_IN if str(tmdb_id) in ids else LABEL_OUT
		if window.getProperty(PROP) != label: window.setProperty(PROP, label)
		# Una riga per ogni ricalcolo, solo con la strumentazione accesa (il servizio passa paginator.log):
		# succede a ogni cambio di elemento, e le righe di log sono sincrone sul thread che le scrive.
		if self.log: self.log('watchlist_label %s %s -> %s | copia %s (%d titoli) | segnale %s'
								% (media_type, tmdb_id, label, copia, len(ids), (self.stamp or '-')[:14]))
		return label
