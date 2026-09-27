# -*- coding: utf-8 -*-

import re
from cocoscrapers.modules import source_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseStremioScraper

_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
_DEFAULT_BASE = 'https://mediafusion.elfhosted.com'


class source(BaseStremioScraper):
	"""Lotto 412: sources/sources_packs nella base Stremio; qui l'URL (con userdata) e la lettura di una voce."""
	priority = 1
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		userdata = getSetting('mediafusion.userdata')
		if getSetting('mediafusion.usecustomurl') == 'true':
			base = getSetting('mediafusion.customurl').rstrip('/') or _DEFAULT_BASE
		else:
			base = _DEFAULT_BASE
		self.stream_base = '%s/%s' % (base, userdata) if userdata else None

	def _base(self):
		return self.stream_base

	@staticmethod
	def _leggi(file):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base)."""
		url = file.get('url', '')
		hash = next((s for s in url.split('/') if _HASH_RE.match(s)), None)
		if not hash: return None
		hints = file.get('behaviorHints', {})
		name = source_utils.clean_name(hints.get('filename', ''))
		if not name: return None
		dsize, isize = source._taglia_da_byte(hints.get('videoSize', 0))
		return {'hash': hash, 'name': name, 'url': source._magnet(hash, name), 'seeders': 0, 'dsize': dsize, 'isize': isize}
