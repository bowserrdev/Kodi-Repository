# -*- coding: utf-8 -*-
"""Torrentio: esiste una release digitale PULITA di un film? (lotto 435, regola U3 di FILTRO-USCITA.md)

Quello che conta per l'utente non e' "uscito in digitale" ma "esiste una sorgente che non sia una copia dal cinema"
(decisione del 30/09): un titolo uscito ma senza sorgenti e' comunque inutile. Torrentio risponde a questa domanda con
UNA richiesta per id IMDb, senza ambiguita' sul titolo: 0,09 s di mediana contro 0,30 di blu-ray.com (Mac, 30/09).
E' l'URL pubblico, senza configurazione, lo stesso che usa lo scraper; non dipende da cocoscrapers.

Cose misurate che la forma del modulo rispecchia (30/09):
  - il limite e' per IP, ~50 richieste NON in cache al minuto qualunque sia il parallelismo, poi 429. Sul 429 la
    richiesta si ripete dal proxy dell'utente: lo fa http_client per tutti i SERVER_COL_PROXY, Torrentio compreso.
    Un 429 anche da li' e' "non so", mai "no";
  - l'etichetta di qualita' sta nella seconda riga di `name` ('Torrentio\\nCAM', 'Torrentio\\nTeleSync HDR',
    'Torrentio\\n1080p'); quando Torrentio non riconosce la qualita' `name` e' solo 'Torrentio';
  - le voci SENZA etichetta possono essere camrip (Kubot, 2014: "(camrip)" nel nome, nessuna etichetta): per loro
    decide il riconoscitore di Fen Light (source_utils.get_release_quality). Su quelle etichettate vince l'etichetta:
    il riconoscitore cerca '.cam.' e il film "Cam" (2018) sarebbe CAM anche in WEB-DL, mentre Torrentio da' gia' la
    precedenza giusta (Hope, "1080p.HDCAM" -> CAM);
  - fuori anche gli screener (decisione dell'utente: solo release digitali pulite).
"""
import threading

_URL = 'https://torrentio.strem.fun/stream/movie/%s.json'
_TIMEOUT = 8.0
# Le etichette di Torrentio delle copie non pulite: riprese in sala, telesync, telecine, screener.
SPORCHE = ('CAM', 'TeleSync', 'TeleCine', 'SCR')
# Le stesse per il riconoscitore di Fen Light, sulle voci senza etichetta.
SPORCHE_NOME = ('CAM', 'TELE', 'SCR')
# La sentinella: The Matrix ha copie pulite in ogni catalogo; se Torrentio non ne da' nessuna, i suoi "no" non valgono.
_SENTINELLA = 'tt0133093'
_SENTINELLA_PROP = 'fenlight.torrentio.sentinella'

_session = None
_lock = threading.Lock()

def _get_session():
	"""Pigra (lotto 52: niente rete all'import) e sotto lucchetto: la chiamano i thread del preparatore insieme."""
	global _session
	if _session is None:
		with _lock:
			if _session is None:
				from modules.kodi_utils import import_requests
				_session = import_requests('torrentio_api').Session()
	return _session

def _log(message):
	try:
		from modules.kodi_utils import logger
		logger('FenLight TORRENTIO', message)
	except Exception: pass

def _voci(imdb_id):
	"""Le voci di Torrentio per il film. Solleva se la risposta non e' quella di Torrentio: 429 anche dal proxy, errore,
	corpo che non e' JSON o senza 'streams'. `{"streams": []}` e' una risposta: nessuna voce."""
	response = _get_session().get(_URL % imdb_id, timeout=_TIMEOUT)
	if response.status_code != 200: raise IOError('HTTP %s' % response.status_code)
	voci = response.json().get('streams')
	if not isinstance(voci, list): raise ValueError('risposta senza "streams"')
	return voci

def pulita(voce):
	"""Una voce e' una release digitale pulita? Vedi l'intestazione: vince l'etichetta, se c'e'."""
	nome = (voce.get('name') or '').split('\n', 1)
	etichetta = nome[1].strip() if len(nome) > 1 else ''
	if etichetta: return not etichetta.startswith(SPORCHE)
	from modules.source_utils import get_release_quality, release_info_format
	torrent = (voce.get('title') or '').split('\n', 1)[0]
	return get_release_quality(release_info_format(torrent)) not in SPORCHE_NOME

def sorgente_pulita(imdb_id):
	"""U3: True se Torrentio ha almeno una release pulita del film, False se non ne ha (e la sentinella risponde), None
	se non si e' potuto sapere. Un None non e' un "no": chi chiama passa a U4 (blu-ray.com)."""
	if not imdb_id: return None
	try: voci = _voci(imdb_id)
	except Exception as e:
		_log('%s: non accertato -- %s: %s' % (imdb_id, type(e).__name__, str(e)[:120]))
		return None
	if any(pulita(v) for v in voci if isinstance(v, dict)): return True
	from modules.sentinella import viva
	if not viva(_SENTINELLA_PROP, lambda: any(pulita(v) for v in _voci(_SENTINELLA) if isinstance(v, dict)),
				'"%s"' % _SENTINELLA, 'FenLight TORRENTIO'):
		_log('%s: nessuna release pulita, ma la sentinella non risponde: non accertato' % imdb_id)
		return None
	return False
