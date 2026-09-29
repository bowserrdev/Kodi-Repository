# -*- coding: utf-8 -*-
"""Lotto 416 (SOTTOTITOLI.md) -- il client di OpenSubtitles (API REST v1) per i sottotitoli sincronizzati.

Rispetto al codice di prima (modules/auto_subtitles.py):
- niente login (29/09, decisione dell'utente): basta la chiave API, anonima. Col token di login il download si conta
  sull'UTENTE (20 al giorno per un account gratuito); senza, sull'APPLICAZIONE della chiave (100 al giorno per una
  chiave da sviluppatore): verificato sulla stessa chiave, contatore `count_uid_...` contro `app_ud_...`. Prima il
  token si salvava in `fenlight.autosub.token` e si rileggeva da `autosub.token`: ogni download rifaceva il login;
- su 429 si aspetta e si riprova una volta;
- una ricerca sola: la lingua dell'utente per imdb (o per serie, stagione ed episodio) con l'hash del file, che marca
  `moviehash_match` sui sottotitoli legati a QUEL file; la ricerca non consuma quota;
- la quota restante si legge dalla risposta di /download (`remaining`): esaurita, si smette per la sessione;
- candidati(): esclusi solo-parti-straniere, traduzioni automatiche, sottotitoli su piu' file e pezzi "CDn" (tutti
  presenti nel corpus: "Il Gladiatore CD3" e' elencato come sottotitolo a se'), poi l'ordine di oggi.
"""
import re
from caches.settings_cache import get_setting
from modules.kodi_utils import make_session, get_property, set_property, sleep

BASE = 'https://api.opensubtitles.com/api/v1/'
USER_AGENT = 'FenLight/1.0'
QUOTA_PROP = 'fenlight.autosub.quota'       # 'finita' fino a riavvio di Kodi, quando /download dice 406 o remaining 0
TIMEOUT = 15
PEZZO_CD = re.compile(r'\bcd\s?\d\b', re.I)
_sessione = [None]


def _session():
	if _sessione[0] is None: _sessione[0] = make_session(BASE)
	return _sessione[0]


def candidati(risultati, lingua):
	"""I sottotitoli scaricabili nella lingua `lingua` (codice a due lettere di OpenSubtitles), nell'ordine in cui
	provarli: legati all'hash, trusted, voti, valutazione, download (la chiave di prima, che sul corpus accetta al
	primo tentativo 164 file su 170). -> [(file_id, attributi)]"""
	fuori = []
	for x in risultati or []:
		a = x.get('attributes') or {}
		if (a.get('language') or '').lower() != lingua.lower(): continue
		files = a.get('files') or []
		if len(files) != 1 or not files[0].get('file_id'): continue
		if a.get('foreign_parts_only') or a.get('ai_translated') or a.get('machine_translated'): continue
		if PEZZO_CD.search('%s %s' % (a.get('release') or '', files[0].get('file_name') or '')): continue
		fuori.append((files[0]['file_id'], a))
	fuori.sort(key=lambda fa: (bool(fa[1].get('moviehash_match')), bool(fa[1].get('from_trusted')), fa[1].get('votes') or 0,
							   fa[1].get('ratings') or 0, fa[1].get('download_count') or 0), reverse=True)
	return fuori


def legati_al_file(risultati, escludi=()):
	"""I sottotitoli di QUALUNQUE lingua legati all'hash del file (ripiego del lotto 421 quando il file non ha un
	riferimento incorporato). -> [(file_id, attributi)]"""
	return [(fid, a) for fid, a in ((((x.get('attributes') or {}).get('files') or [{}])[0].get('file_id'), x.get('attributes') or {})
									for x in risultati or [])
			if fid and a.get('moviehash_match') and (a.get('language') or '') not in escludi and len(a.get('files') or []) == 1]


class OpenSubtitlesAPI:
	def __init__(self):
		self.chiave = get_setting('fenlight.autosub.api_key', '')
		if self.chiave == 'empty_setting': self.chiave = ''

	def pronto(self):
		return bool(self.chiave)

	def _intestazioni(self):
		# Nessun Authorization: la chiave e' anonima (vedi in testa).
		return {'Api-Key': self.chiave, 'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Content-Type': 'application/json'}

	def _richiesta(self, metodo, percorso, params=None, corpo=None):
		"""La risposta, o None. 429: un secondo di attesa e un secondo tentativo."""
		for tentativo in (0, 1):
			try:
				r = _session().request(metodo, BASE + percorso, params=params, json=corpo, headers=self._intestazioni(), timeout=TIMEOUT)
			except Exception: return None
			if r.status_code == 429 and not tentativo:
				sleep(1000); continue
			return r
		return r

	def cerca(self, lingue, imdb_id=None, serie_imdb=None, stagione=None, episodio=None, moviehash=None, pagine=2):
		"""Tutti i sottotitoli nelle `lingue` (codici a due lettere) per il film o l'episodio, con `moviehash_match`
		sui legati al file. Gratis. -> lista di risultati (vuota se la rete non risponde)."""
		params = {'languages': ','.join(sorted(set(l.lower() for l in lingue if l)))}
		if serie_imdb:
			params.update({'parent_imdb_id': int(str(serie_imdb).replace('tt', '')), 'season_number': int(stagione), 'episode_number': int(episodio)})
		elif imdb_id:
			params['imdb_id'] = int(str(imdb_id).replace('tt', ''))
		else:
			return []
		if moviehash: params['moviehash'] = moviehash
		tutti = []
		for pagina in range(1, pagine + 1):
			params['page'] = pagina
			# in ordine alfabetico: l'API rimanda con un redirect le richieste coi parametri in altro ordine
			r = self._richiesta('GET', 'subtitles', params=dict(sorted(params.items())))
			if r is None or r.status_code != 200: break
			try: d = r.json() or {}
			except Exception: break
			tutti += d.get('data') or []
			if pagina >= (d.get('total_pages') or 1): break
		return tutti

	def scarica(self, file_id):
		"""(byte dell'srt o None, download restanti o None, motivo). Consuma quota."""
		if get_property(QUOTA_PROP) == 'finita': return None, 0, 'quota finita'
		r = self._richiesta('POST', 'download', corpo={'file_id': file_id, 'sub_format': 'srt'})
		if r is None: return None, None, 'rete'
		if r.status_code == 406:
			set_property(QUOTA_PROP, 'finita')
			return None, 0, 'quota finita'
		if r.status_code != 200: return None, None, 'download %s' % r.status_code
		try: d = r.json() or {}
		except Exception: return None, None, 'risposta illeggibile'
		restanti = d.get('remaining')
		if restanti is not None and restanti <= 0: set_property(QUOTA_PROP, 'finita')
		if not d.get('link'): return None, restanti, 'senza link'
		try:
			x = _session().get(d['link'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=TIMEOUT)
			if x.status_code != 200 or not x.content: return None, restanti, 'cdn %s' % x.status_code
			return x.content, restanti, None
		except Exception:
			return None, restanti, 'cdn'
