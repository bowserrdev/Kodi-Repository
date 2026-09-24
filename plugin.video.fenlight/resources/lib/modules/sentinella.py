# -*- coding: utf-8 -*-
"""La sentinella: prima di credere a un "no" di una fonte esterna, si chiede qualcosa che c'e' di sicuro.

Nata in apis/bluray_api.py (lotti 93-94, per catalogo dal 340), spostata qui col lotto 345 perche' ora le fonti
sono due, blu-ray.com e JustWatch, e la regola e' una: un guasto sistemico (indice cambiato, schema cambiato, ip
bandito) svuota ogni risposta, e il filtro nasconderebbe in blocco tutto senza una riga di log. Un "no" vale solo se
la fonte, interrogata su un titolo che c'e' di sicuro, risponde. Costa una domanda ogni mezz'ora per fonte, e solo
quando capita davvero un "no".
"""
TTL = 1800
_MEMORIA = {}

def _io():
	# Le proprieta' di finestra sono l'unica memoria condivisa fra le invocazioni: con reuselanguageinvoker=false
	# ogni build e' un processo nuovo, quindi una variabile di modulo non sopravviverebbe. Import ritardato e
	# protetto: il modulo deve restare importabile fuori da Kodi.
	try:
		from modules.kodi_utils import get_property, set_property
		return get_property, set_property
	except Exception:
		return (lambda k: _MEMORIA.get(k, ''), lambda k, v: _MEMORIA.__setitem__(k, v))

def viva(chiave, domanda, nome, fonte):
	"""True se la fonte risponde, False se non risponde o non si e' potuto stabilire.

	`chiave` e' la proprieta' in cui si ricorda l'esito per TTL secondi; `domanda()` interroga la fonte sul titolo
	sicuro e restituisce qualcosa di vero se lo trova (puo' sollevare); `nome` descrive la sentinella nel log,
	`fonte` e' l'etichetta del log.
	"""
	from time import time
	get_property, set_property = _io()
	try:
		stato, scadenza = (get_property(chiave) or '').split('|')
		if time() < float(scadenza): return stato == 'ok'
	except Exception:
		pass
	try:
		viva = bool(domanda())
	except Exception:
		return False   # non si e' potuto stabilire: non si trasforma un dubbio in un "no"
	set_property(chiave, '%s|%s' % ('ok' if viva else 'ko', time() + TTL))
	if not viva:
		try:
			from modules.kodi_utils import logger
			logger(fonte, 'SENTINELLA FALLITA per %s: la domanda di controllo non trova cio\' che c\'e\' di sicuro. La fonte '
				'non sta rispondendo, quindi i suoi "no" NON valgono e i verdetti restano inconcludenti finche\' non '
				'torna.' % nome)
		except Exception: pass
	return viva
