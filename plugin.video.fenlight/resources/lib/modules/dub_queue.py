# -*- coding: utf-8 -*-
# Coda dei verdetti del filtro doppiaggio (lotto 95, punto 3 del piano concordato).
#
# IL PROBLEMA. dub_keep_mask deve decidere, per ogni elemento di un widget, se una versione italiana
# esiste. Con il verdetto in cache la risposta e' istantanea; senza, serve la rete -- e finora quella
# rete si pagava DENTRO la costruzione, con l'utente fermo davanti a un widget che non compare. Il
# lotto 94 ha portato il costo di un'interrogazione da ~4,85 s a ~0,18 s, quindi non e' piu' il tappo
# che era, ma 0,18 s per decine di titoli restano lavoro sul percorso interattivo.
#
# LA SCELTA DELL'UTENTE, alla lettera: *"intanto NON farlo comparire ed eventualmente aggiornare il
# widget e metterlo solo se esiste la versione italiana"*. Cioe' FAIL CLOSED durante la costruzione --
# l'opposto del fail open che il filtro usa per gli esiti inconcludenti. La differenza e' che qui non
# si e' concluso "non c'e'": si e' deciso di non chiedere ancora. Nascondere e' reversibile, mostrare
# un titolo mai doppiato no.
#
# COME. La costruzione mette l'elemento in questa coda e lo nasconde; il servizio (DubResolver in
# service.py) la svuota quando la stick e' ferma, scrive i verdetti in dub_cache e -- se qualcosa e'
# risultato disponibile -- ordina UNA ricarica mirata dei soli contenitori interessati. Alla ricarica
# successiva quegli elementi hanno il verdetto in cache e compaiono senza toccare la rete.
#
# DOVE VIVE. In una proprieta' di Window(10000), non in memoria di modulo e non su disco:
#  - in memoria non puo' stare, perche' con reuselanguageinvoker=false ogni costruzione e' un
#    processo nuovo e il servizio e' un processo ANCORA diverso: non condividono niente;
#  - su disco (una tabella in dub.db) costerebbe I/O sulla eMMC lenta proprio nel punto che stiamo
#    cercando di alleggerire.
# Le proprieta' di finestra sono l'unica memoria condivisa a costo zero di questo addon.
#
# FORMATO. Testo piatto, non JSON: l'accodamento e' una concatenazione di stringhe, senza analisi
# sintattica. Un record per elemento, campi separati da US (\x1f), record separati da RS (\x1e) --
# caratteri di controllo che non compaiono in un titolo. Il costo di accodamento e' quindi una
# lettura e una scrittura di proprieta', qualunque sia la lunghezza della coda.
#
# LA CORSA, e perche' non fa danno. Due costruzioni che finiscono insieme fanno entrambe
# leggi-modifica-scrivi sulla stessa proprieta' e una delle due puo' perdere i propri record. La
# conseguenza e' che quegli elementi restano nascosti fino alla prossima costruzione di quel
# widget -- che li riaccodera', perche' il verdetto in cache continua a mancare. E' un ritardo che si
# ripara da solo, non una perdita: non vale un lock fra processi.
from modules.kodi_utils import get_property, set_property, clear_property

QUEUE_PROP = 'fenlight.dub.queue'
# Istante dell'ultimo accodamento. Il servizio aspetta che la coda sia FERMA da qualche secondo prima
# di lavorarla: finche' i widget si stanno ancora costruendo, accodano -- e mettersi a fare rete in
# mezzo a un'ondata di costruzioni e' esattamente la raffica che il tetto di 3 script e le note sui
# crash dicono di evitare.
STAMP_PROP = 'fenlight.dub.queue.ts'

_US, _RS = '\x1f', '\x1e'
# Tetto ai record in coda. Serve solo a impedire che una navigazione lunga su cache fredda gonfi una
# proprieta' di finestra senza limite; i record oltre il tetto non si perdono davvero, perche' la
# ricostruzione successiva del loro widget li riaccoda.
CAP = 400

def _split(raw):
	return [r for r in raw.split(_RS) if r] if raw else []

def enqueue(entries):
	"""entries: iterabile di (media_type, tmdb_id, title, year, verify). Torna quanti ne ha accodati."""
	records = []
	for media_type, tmdb_id, title, year, verify in entries:
		if not tmdb_id: continue
		records.append(_US.join((str(media_type), str(tmdb_id), str(title or ''),
								str(year or ''), '1' if verify else '0')))
	if not records: return 0
	try:
		existing = _split(get_property(QUEUE_PROP))
		# Deduplica sulla coppia (tipo, tmdb): lo stesso titolo compare spesso in piu' widget della
		# stessa schermata, e interrogarlo una volta sola e' metà del guadagno.
		seen = set()
		for r in existing:
			parts = r.split(_US)
			if len(parts) > 1: seen.add((parts[0], parts[1]))
		fresh = []
		for r in records:
			parts = r.split(_US)
			pair = (parts[0], parts[1])
			if pair in seen: continue
			seen.add(pair); fresh.append(r)
		if not fresh: return 0
		queue = existing + fresh
		if len(queue) > CAP: queue = queue[-CAP:]
		set_property(QUEUE_PROP, _RS.join(queue))
		from time import time
		set_property(STAMP_PROP, str(time()))
		return len(fresh)
	except Exception:
		return 0

def pending_count():
	try: return len(_split(get_property(QUEUE_PROP)))
	except Exception: return 0

def last_enqueue():
	try: return float(get_property(STAMP_PROP) or 0)
	except Exception: return 0.0

def drain(limit):
	"""Prende in carico fino a `limit` record e li TOGLIE dalla coda.

	Prenderli in carico significa esattamente questo: se il servizio muore a meta' lotto quei record
	sono persi, e la prossima costruzione del widget li riaccoda. Lasciarli in coda finche' non sono
	risolti costerebbe una riscrittura per record e aprirebbe la possibilita' di lavorarli due volte.
	"""
	try:
		queue = _split(get_property(QUEUE_PROP))
		if not queue: return []
		batch, rest = queue[:limit], queue[limit:]
		if rest: set_property(QUEUE_PROP, _RS.join(rest))
		else: clear_property(QUEUE_PROP)
		out = []
		for record in batch:
			parts = record.split(_US)
			if len(parts) != 5: continue
			media_type, tmdb_id, title, year, verify = parts
			out.append((media_type, tmdb_id, title or None, year or None, verify == '1'))
		return out
	except Exception:
		return []

def requeue(entries):
	"""Rimette in testa cio' che un lotto interrotto (riproduzione avviata, abort) non ha risolto."""
	if not entries: return
	try:
		records = [_US.join((str(m), str(i), str(t or ''), str(y or ''), '1' if v else '0'))
					for m, i, t, y, v in entries]
		existing = _split(get_property(QUEUE_PROP))
		queue = records + existing
		if len(queue) > CAP: queue = queue[:CAP]
		set_property(QUEUE_PROP, _RS.join(queue))
	except Exception: pass

def clear():
	try:
		clear_property(QUEUE_PROP); clear_property(STAMP_PROP)
	except Exception: pass
