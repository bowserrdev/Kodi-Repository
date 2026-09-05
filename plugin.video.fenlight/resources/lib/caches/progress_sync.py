# -*- coding: utf-8 -*-
"""Riconciliazione dell'avanzamento fra il dispositivo e Trakt.

NESSUNA DIPENDENZA: ne' database, ne' Kodi, ne' rete, ne' orologio. Solo la tabella delle
transizioni. E' voluto: questa e' l'unica logica che decide se una riga di 'continua a guardare'
vive o muore, ed e' l'unica che si puo' provare per intero senza accendere niente.

PERCHE' ESISTE. Fino al lotto 132 lo stato di sincronizzazione di una riga non stava scritto da
nessuna parte: veniva indovinato ogni volta da `resume_id`, dall'orologio e da sei guardie
sovrapposte (122: resume_id == 0; 128: finestra di grazia di 120 s; 132: budget di riprove). La
domanda a cui nessuna di quelle sapeva rispondere e' sempre stata la stessa:

    questa riga e' in locale e non nella risposta di Trakt. E' MIA e non ancora pubblicata,
    oppure e' stata CANCELLATA altrove?

Con `resume_id` non si risponde: diventa diverso da zero appena la spinta ritorna -- cioe' prima
che Trakt la elenchi -- e resta diverso da zero dopo che Trakt l'ha cancellata. Con l'orologio si
indovina, e infatti il 03/09 la stick ha resuscitato per due giri di fila un film cancellato dal Mac
trenta secondi prima: la grazia diceva 'e' mia, non ancora pubblicata', la verita' era 'era
pubblicata, poi l'hanno tolta'.

Qui lo stato e' un dato, non una deduzione.
"""

from collections import namedtuple

# --- gli stati ------------------------------------------------------------------------------------
# La riga l'abbiamo VISTA arrivare dentro uno snapshot di Trakt. Da quel momento Trakt e' la verita'
# per questa riga, e la sua assenza da uno snapshot successivo e' una cancellazione.
SYNCED = 'synced'
# L'abbiamo scritta noi e Trakt non l'ha ancora mostrata. La sua assenza non prova niente.
PENDING_PUT = 'pending_put'
# L'abbiamo cancellata noi e Trakt la elenca ancora. Non va reinserita: e' l'errore che rendeva
# inutile una cancellazione remota fallita (il commento in _clear_progress_on_trakt lo dava per
# perso). La riga resta qui, invisibile all'interfaccia, finche' Trakt non conferma.
PENDING_DELETE = 'pending_delete'

# L'UNICA AMBIGUITA' IRRIDUCIBILE, e sta tutta in questa costante.
# 'PENDING_PUT e Trakt non la elenca' e' compatibile con due storie: la risposta e' indietro, oppure
# qualcuno l'ha tolta prima che la vedessimo. Non e' distinguibile, perche' `sync/playback` non porta
# nessun indicatore di freschezza e l'ack della spinta restituisce solo l'id.
# Si limita CONTANDO SNAPSHOT, non secondi: la riga sopravvive a questo numero di risposte che la
# omettono, poi si considera cancellata. Misura del 03/09: fra i due dispositivi la sfasatura era di
# 0,5 s contro un poll da 30 s, quindi un solo giro e' gia' un margine di sessanta volte.
PENDING_PUT_MISSES_ALLOWED = 1

# Le colonne che contano, nell'ordine della tabella. `state` e `misses` sono le due nuove.
Local = namedtuple('Local', 'resume_point curr_time last_played resume_id title state misses')
Remote = namedtuple('Remote', 'resume_point curr_time last_played resume_id title')
Upsert = namedtuple('Upsert', 'key resume_point curr_time last_played resume_id title state misses')
Plan = namedtuple('Plan', 'upserts deletes changed retry_remote_delete retry_push')

def _from_remote(key, r):
	return Upsert(key, r.resume_point, r.curr_time, r.last_played, r.resume_id, r.title, SYNCED, 0)

def reconcile(local, remote, misses_allowed=PENDING_PUT_MISSES_ALLOWED):
	"""(righe locali, snapshot di Trakt) -> il piano di scrittura. Otto celle, nessuna eccezione.

	`local` e `remote` sono dizionari con la stessa chiave: la tripla (media_id, stagione, episodio),
	gia' normalizzata a stringhe da chi legge il database. I valori sono `Local` e `Remote`.

	Torna un `Plan`:
	  upserts             righe da scrivere (INSERT OR REPLACE), stato compreso
	  deletes             chiavi da togliere
	  changed             chiavi il cui AVANZAMENTO e' cambiato per chi guarda lo schermo. Non e'
	                      l'insieme delle scritture: passare da PENDING_PUT a SYNCED con la stessa
	                      percentuale e' una scrittura ma non ha niente da mostrare.
	  retry_remote_delete (chiave, resume_id) di cancellazioni nostre che Trakt non ha ancora
	                      recepito. Chi chiama puo' rilanciare la DELETE remota.
	  retry_push          chiavi scritte da noi che Trakt non ha MAI confermato. Da rispingere.
	"""
	upserts, deletes, changed, retry_remote_delete, retry_push = [], [], set(), [], []
	for key in set(local) | set(remote):
		l, r = local.get(key), remote.get(key)

		# 1. assente in locale, presente su Trakt -> arriva da un altro dispositivo.
		if l is None:
			upserts.append(_from_remote(key, r))
			changed.add(key)
			continue

		state = l.state or SYNCED

		if state == PENDING_DELETE:
			# 6. l'abbiamo cancellata e Trakt concorda: adesso la riga puo' sparire davvero.
			if r is None: deletes.append(key)
			# 7. l'abbiamo cancellata e Trakt la elenca ancora: NON si reinserisce. La cancellazione
			#    remota non e' passata (o non e' ancora propagata) e va richiesta di nuovo.
			elif l.resume_id: retry_remote_delete.append((key, l.resume_id))
			continue

		if r is not None:
			# 2. SYNCED e presente -> si riallinea solo se qualcosa e' diverso davvero.
			# 4. PENDING_PUT e presente -> la spinta e' arrivata. Vince la versione di Trakt, che
			#    porta il resume_id vero, e lo stato diventa SYNCED.
			if state != SYNCED or l.misses or l.resume_point != r.resume_point or l.resume_id != r.resume_id:
				upserts.append(_from_remote(key, r))
			if l.resume_point != r.resume_point: changed.add(key)
			continue

		# 3. SYNCED e assente -> l'avevamo vista su Trakt e ora non c'e' piu': cancellata altrove.
		#    E' la cella che il 03/09 rimetteva la riga invece di toglierla.
		if state == SYNCED:
			deletes.append(key)
			changed.add(key)
			continue

		# 5a. PENDING_PUT, assente, e la spinta non e' MAI stata confermata (nessun resume_id).
		#     Qui non c'e' nessuna ambiguita' da limitare: la riga non e' 'in attesa di comparire su
		#     Trakt', e' proprio non arrivata -- rete assente, token scaduto, errore ingoiato. Non si
		#     consuma nessun tentativo, perche' consumarli significherebbe cancellare in silenzio una
		#     pausa dell'utente per un guasto di rete. Si conserva e si chiede di rispingerla.
		if not l.resume_id:
			retry_push.append(key)
			continue

		# 5b. PENDING_PUT, assente, ma Trakt aveva accettato la spinta: QUESTA e' la cella ambigua.
		#     Vedi PENDING_PUT_MISSES_ALLOWED.
		misses = (l.misses or 0) + 1
		if misses > misses_allowed:
			deletes.append(key)
			changed.add(key)
		else:
			upserts.append(Upsert(key, l.resume_point, l.curr_time, l.last_played,
									l.resume_id, l.title, PENDING_PUT, misses))
	return Plan(upserts, deletes, changed, retry_remote_delete, retry_push)
