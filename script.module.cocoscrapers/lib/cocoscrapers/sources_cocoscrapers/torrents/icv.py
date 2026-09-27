# -*- coding: utf-8 -*-

import re
from urllib.parse import unquote
from cocoscrapers.modules import source_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseStremioScraper

_HASH_RE = re.compile(r'^[0-9a-fA-F]{40}$')
_BTIH_RE = re.compile(r'btih[:=]([0-9a-fA-F]{40})', re.I)
_DEFAULT_BASE = 'https://icv.stremio-italia.eu'


class source(BaseStremioScraper):
	"""Lotto 412: sources/sources_packs nella base Stremio; qui l'URL (con userdata) e la lettura di una voce."""
	priority = 1
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		userdata = (getSetting('icv.userdata') or '').strip().strip('/')
		if getSetting('icv.usecustomurl') == 'true':
			base = (getSetting('icv.customurl') or '').rstrip('/') or _DEFAULT_BASE
		else:
			base = _DEFAULT_BASE
		self.stream_base = '%s/%s' % (base, userdata) if userdata else base

	def _base(self):
		return self.stream_base

	@staticmethod
	def _hash_from_file(file):
		hash = file.get('infoHash') or file.get('_meta', {}).get('infoHash') or ''
		if _HASH_RE.match(hash):
			return hash
		try:
			match = _BTIH_RE.search(unquote(file.get('url', '')))
			return match.group(1) if match else ''
		except:
			return ''

	@staticmethod
	def _leggi(file):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base). `raw`: il titolo dello stream, per
		gli alias non latini."""
		hash = source._hash_from_file(file)
		if not _HASH_RE.match(hash): return None
		hints = file.get('behaviorHints', {})
		name = source_utils.clean_name(hints.get('filename') or file.get('filename') or '')
		if not name: return None
		try: seeders = int(file.get('_meta', {}).get('seeders', 0))
		except: seeders = 0
		dsize, isize = source._taglia_da_byte(hints.get('videoSize') or file.get('size') or 0)
		return {'hash': hash, 'name': name, 'url': source._magnet(hash, name), 'seeders': seeders, 'dsize': dsize,
				'isize': isize, 'raw': file.get('title', '')}
