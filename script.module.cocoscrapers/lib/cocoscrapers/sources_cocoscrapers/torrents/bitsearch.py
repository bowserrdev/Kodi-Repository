# -*- coding: utf-8 -*-

import re
from json import loads as jsloads
from threading import Thread
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTestoScraper

# Fen Light, lotto 408 (SORGENTI.md): l'API JSON di bitsearch.eu al posto della pagina HTML (bitsearch.to, due parser, uno di
# riserva per quando la pagina cambiava). Le categorie (https://bitsearch.eu/api) non si chiedono al server: la maggior parte
# dei torrent sta in "Altro > Video" (Ratatouille 60 su 100, contro 24 in "Film"; Stranger Things S02 66 contro 19 in "Serie"),
# e l'API accetta una categoria per richiesta. Servono al contrario: fuori subito cio' che non puo' essere un video.
# Ordine per seeders (i piu' diffusi sono i piu' probabili in cache su TorBox) e fino a PAGINE pagine da 100: ogni ordine da'
# una fetta diversa (Ratatouille 2007: 50-58 release col titolo giusto per ordine, 105 unendoli, 27/09).
_API_URL = 'https://bitsearch.eu/api/v1/search?q=%s&sort=seeders&limit=100&page=%d'
PAGINE = 3
# Fuori le categorie che non possono essere video: 5 software, 6 giochi, 7 musica, 8 audiolibri, 9 ebook, 10 XXX. Le
# sottocategorie di 1 "Altro" no: le assegna bitsearch dal contenuto e sbagliano ("Ratatouille.2007.1080p.BluRay.x265-RARBG" in
# "Programmi", altri film in "Immagini" e "Database", 27/09); decide il classificatore sui file
_CATEGORIE_NON_VIDEO = (5, 6, 7, 8, 9, 10)
_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
SCADENZA = 10
# Limitati o giu' (richiesta dell'utente, 27/09): il limite gratuito e' di 200 richieste al giorno per IP e risponde 429: si
# cambia IP, cioe' si ripete dal proxy configurato (rotante: un IP nuovo a ogni richiesta), fino a CAMBI_IP volte. Ogni altra
# risposta (5xx, 403, JSON rotto) o nessuna risposta (timeout, connessione) vuol dire API giu': ci si ferma per tutta la
# ricerca, niente altre richieste ne' dirette ne' dal proxy.
CAMBI_IP = 3


def _video(hit):
	return hit.get('category') not in _CATEGORIE_NON_VIDEO


class source(BaseTestoScraper):
	"""Lotto 412: le query, i thread e la sequenza nella base per testo; qui le pagine dell'API, limitati o giu', e la lettura."""
	priority = 3
	hasMovies = True
	hasEpisodes = True
	# lotto 408: anche i film con l'anno. Solo il titolo, un titolo comune ("The One", "Guardians": 10.000 risultati) seppelliva le
	# release giuste; con l'anno ne arrivano di piu' per tutti i titoli provati
	anno_nei_film = True

	def _reset(self):
		super()._reset()
		self._giu = False          # lo stato "API giu'" vale per una ricerca

	def _chiedi(self, query, pagina):
		"""(risultati, altre pagine?) di una pagina; [] se limitati senza scampo o se l'API e' giu'."""
		if self._giu: return [], False
		url, proxy = _API_URL % (quote_plus(query), pagina), None
		for cambio in range(CAMBI_IP + 1):
			risposta = client.request(url, proxy=proxy, timeout=7, scadenza=SCADENZA, output='extended')
			if risposta is None:
				return self._fermati('nessuna risposta (timeout o connessione)', query)
			testo, stato, _intestazioni = risposta
			if stato == '429':
				# client.request ripete gia' dal proxy un 429 diretto: qui arriva il 429 del proxy, si chiede un altro IP
				proxy = client._get_configured_proxy()
				if not proxy:
					log_utils.log('BITSEARCH limitato (429) e nessun proxy configurato: "%s" p%d' % (query, pagina))
					return [], False
				log_utils.log('BITSEARCH limitato (429), cambio IP %d/%d: "%s" p%d' % (cambio + 1, CAMBI_IP, query, pagina))
				continue
			if stato != '200':
				return self._fermati('HTTP %s' % stato, query)
			try: dati = jsloads(testo)
			except: return self._fermati('risposta non JSON', query)
			risultati = [h for h in dati.get('results') or [] if _video(h)]
			log_utils.log('BITSEARCH "%s" p%d: %s risultati, %s fuori categoria' % (query, pagina, len(dati.get('results') or []),
						  len(dati.get('results') or []) - len(risultati)))
			return risultati, bool((dati.get('pagination') or {}).get('hasNext'))
		log_utils.log('BITSEARCH limitato anche dopo %d cambi di IP: "%s" p%d' % (CAMBI_IP, query, pagina))
		return [], False

	def _fermati(self, motivo, query):
		if not self._giu: log_utils.log('BITSEARCH API giu\' (%s) su "%s": nessun\'altra richiesta in questa ricerca' % (motivo, query))
		self._giu = True
		return [], False

	def _fetch_hits(self, query):
		"""Le pagine di una ricerca: la prima, poi le altre insieme se la prima dice che ce ne sono."""
		risultati, altre = self._chiedi(query, 1)
		if altre and PAGINE > 1:
			pagine = {}
			fili = [Thread(target=lambda n: pagine.__setitem__(n, self._chiedi(query, n)[0]), args=(n,)) for n in range(2, PAGINE + 1)]
			[f.start() for f in fili]
			[f.join() for f in fili]
			for n in sorted(pagine): risultati += pagine[n]
		return risultati

	@staticmethod
	def _leggi(hit):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base)."""
		hash = (hit.get('infohash') or '').lower()
		if not _HASH_RE.match(hash): return None
		name = source_utils.clean_name(hit.get('title') or '')
		try: seeders = int(hit.get('seeders') or 0)
		except: seeders = 0
		try:
			dsize = round(int(hit.get('size') or 0) / 1073741824.0, 2)
			isize = '%.2f GB' % dsize if dsize else ''
		except: dsize, isize = 0, ''
		return {'hash': hash, 'name': name, 'url': source._magnet(hash, name), 'seeders': seeders, 'dsize': dsize, 'isize': isize}
