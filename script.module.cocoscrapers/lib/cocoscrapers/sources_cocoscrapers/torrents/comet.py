# -*- coding: utf-8 -*-

import re
from cocoscrapers.modules import source_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseStremioScraper

_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
_SEEDERS_RE = re.compile(r'👤\s*(\d+)')
_DEFAULT_BASE = 'https://comet.elfhosted.com'


class source(BaseStremioScraper):
	"""Lotto 412: sources/sources_packs nella base Stremio; qui l'URL (con userdata) e la lettura di una voce."""
	priority = 2
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		userdata = getSetting('comet.userdata')
		if getSetting('comet.usecustomurl') == 'true':
			base = getSetting('comet.customurl').rstrip('/') or _DEFAULT_BASE
		else:
			base = _DEFAULT_BASE
		self.stream_base = '%s/%s' % (base, userdata) if userdata else None

	def _base(self):
		return self.stream_base

	@staticmethod
	def _leggi(file):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base)."""
		hints = file.get('behaviorHints', {})
		binge = hints.get('bingeGroup', '')
		hash = binge.split('|')[-1] if binge else ''
		if not _HASH_RE.match(hash): return None
		name = source_utils.clean_name(hints.get('filename', ''))
		if not name: return None
		try:
			m = _SEEDERS_RE.search(file.get('description', ''))
			seeders = int(m.group(1)) if m else 0
		except: seeders = 0
		dsize, isize = source._taglia_da_byte(hints.get('videoSize', 0))
		return {'hash': hash, 'name': name, 'url': source._magnet(hash, name), 'seeders': seeders, 'dsize': dsize, 'isize': isize}
