# -*- coding: utf-8 -*-

import re
from json import dumps as jsdumps, loads as jsloads
from urllib.parse import quote_plus
from cocoscrapers.modules import client, source_utils, log_utils
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseTestoScraper

_API_URL = 'https://api.knaben.org/v1'
# Lotto 368 (SORGENTI.md): Knaben risponde in 0,2 s ma a tratti trasmette a pochi KB/s (1-90 s per la stessa richiesta,
# 26/09; uguale via proxy, quindi e' il servizio). Nei periodi buoni una risposta intera sta sotto i 4 s.
SCADENZA = 10
_BTIH_RE = re.compile(r'btih:([0-9a-fA-F]{40})', re.I)
_JSON_HEADERS = {'Content-Type': 'application/json'}


class source(BaseTestoScraper):
	"""Lotto 412: le query, i thread e la sequenza nella base per testo; qui la richiesta e la lettura di una voce."""
	priority = 3
	hasMovies = True
	hasEpisodes = True

	@staticmethod
	def _build_payload(query, size=300):
		return jsdumps({
			'search_type': '100%',
			'search_field': 'title',
			'query': query,
			'order_by': 'seeders',
			'order_direction': 'desc',
			'size': size,
			'hide_unsafe': True,
			'hide_xxx': True,
			# Lotto 368: solo Film (3000000, anime compresi) e Serie (2000000). Senza, circa un risultato su cinque era
			# audio, libri, giochi o "Other" (prova del 26/09), da scaricare comunque da un servizio lento.
			'categories': [2000000, 3000000]
		})

	@staticmethod
	def _leggi(hit):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base)."""
		hash = hit.get('hash')
		magnet_url = hit.get('magnetUrl')
		if not hash and magnet_url:
			m = _BTIH_RE.search(magnet_url)
			if m: hash = m.group(1)
		if not hash: return None
		name = source_utils.clean_name(hit.get('title', ''))
		if not name: return None
		try: seeders = int(hit.get('seeders') or 0)
		except: seeders = 0
		dsize, isize = source._taglia_da_byte(hit.get('bytes', 0))
		url = magnet_url if magnet_url else 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, quote_plus(name))
		return {'hash': hash, 'name': name, 'url': url, 'seeders': seeders, 'dsize': dsize, 'isize': isize}

	def _fetch_hits(self, query):
		try:
			result = client.request(_API_URL, post=self._build_payload(query),
									headers=_JSON_HEADERS, timeout=10, scadenza=SCADENZA)
			if not result:
				log_utils.log('KNABEN fetch failed: %s' % query)
				return []
			hits = jsloads(result).get('hits', [])
			log_utils.log('KNABEN query "%s": %s hits' % (query, len(hits)))
			return hits
		except:
			source_utils.scraper_error('KNABEN')
			return []
