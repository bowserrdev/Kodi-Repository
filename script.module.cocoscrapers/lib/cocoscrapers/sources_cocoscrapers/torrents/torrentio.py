# -*- coding: utf-8 -*-

import re
from cocoscrapers.modules import source_utils
from cocoscrapers.modules.control import setting as getSetting
from cocoscrapers.sources_cocoscrapers.base_scraper import BaseStremioScraper

_INFO = re.compile(r'👤.*')
_SIZE_RE = re.compile(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|Gb|MB|MiB|Mb))')


class source(BaseStremioScraper):
	"""Lotto 412: sources/sources_packs nella base Stremio; qui l'URL, il bypass e la lettura di una voce."""
	priority = 1
	hasMovies = True
	hasEpisodes = True

	def __init__(self):
		super().__init__()
		self.base_link = 'https://torrentio.strem.fun'
		self.bypass_filter = getSetting('torrentio.bypass_filter')

	def _base(self):
		return self.base_link

	@property
	def salta_titolo(self):
		return self.bypass_filter == 'true'

	def _bypass_pacchetti(self, bypass_filter):
		return bypass_filter or self.bypass_filter == 'true'

	def _nome_per_titolo(self, nome):
		return nome.replace('.(Archie.Bunker', '')

	def _leggi(self, file):
		"""Una voce della risposta -> candidato (lotto 409: i controlli li fa la classe base). `nome_file`: il file che Torrentio
		indica per l'episodio (lotto 361: il nome del torrent puo' essere un pacchetto a intervallo, "One Piece (0001-1118)");
		`raw`: il titolo prima di clean_name, per gli alias non latini."""
		raw = (file.get('title') or '').split('\n')[0]
		try:
			file_title = file['title'].split('\n')
			file_info = [x for x in file_title if _INFO.match(x)][0]
		except:
			self._log_voce('SKIP [parse failed] raw="%s"' % raw)
			return None
		hash = file.get('infoHash', '')
		name = source_utils.clean_name(file_title[0])
		try: seeders = int(re.search(r'(\d+)', file_info).group(1))
		except: seeders = 0
		try:
			size_match = _SIZE_RE.search(file_info)
			dsize, isize = source_utils._size(size_match.group(0)) if size_match else (0, '')
		except: dsize, isize = 0, ''
		return {'hash': hash, 'name': name, 'url': self._magnet(hash, name), 'seeders': seeders, 'dsize': dsize,
				'isize': isize, 'raw': raw, 'nome_file': source_utils.clean_name(((file.get('behaviorHints') or {}).get('filename')) or '')}
