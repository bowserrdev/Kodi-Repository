# -*- coding: utf-8 -*-
"""LOTTI 332-334 -- il preparatore: l'unico che va in rete per le righe paginate.

LA REGOLA (decisa il 16/09). La costruzione di una riga legge dal database e basta; tutto cio' che
serve per decidere COSA mostrare -- le pagine della sorgente, le schede dei titoli, i verdetti sul
doppiaggio -- lo fa il servizio, qui, prima che la costruzione ne abbia bisogno o mentre lei aspetta.

Il problema che toglie. Fino al 331 la costruzione leggeva la sorgente e, per ogni titolo senza scheda
o senza verdetto, lo NASCONDEVA e lo mandava al servizio: nelle pagine profonde un passo mostrava 3-8
titoli su 20 (log del 16/09), e i nascosti tornavano a gruppi con ricostruzioni intere della riga.
Qui un titolo entra nella lista solo quando e' pronto, e un passo e' PIENO: venti titoli, o la fine della
sorgente. Nessun tetto di pagine (specifica del 16/09; il tetto del 332 dava passi da 8, 1, 0 titoli
nella ricerca, e una ricarica della riga per ognuno).

IL DIALOGO (paginator.passo_pronto dall'altra parte):
    costruzione  --pgpasso {chiave, parametri, tipo, passi, ricomponi, posizione, istante, ...}-->  preparatore
    costruzione  <--pgpronto {chiave, esito: ok | fallito | superata}--  preparatore
    costruzione  --pgscadute {...}-->  preparatore           (schede servite scadute o mancanti)
    tutti        <--pgservizio--  preparatore                (sono partito: chi aspettava rimandi)
Il messaggio sveglia, il database decide: chi aspetta, al risveglio, rilegge `widgets.db`.
Il BATTITO: il preparatore scrive l'istante in paginator.SERVIZIO_PROP a ogni pagina e a ogni lavoro. Chi
aspetta smette di aspettare solo se il battito tace per paginator.LIMITE_ATTESA: un passo lungo (una
ricerca che il filtro svuota) non e' un servizio morto.

UN THREAD SOLO scrive `widgets.db`, ed e' questo: anche le consegne spedite dalle costruzioni (pgdb)
passano da qui. La rete invece va a un gruppo di al massimo RETE_IN_PARALLELO richieste -- pagine della
sorgente e giudizi dei titoli, mai insieme. Le pagine lette insieme sono al piu' FINESTRA_PAGINE: e' un'altra
domanda (quanto leggere in anticipo), e ha un'altra risposta.

LE PRIORITA':
    P0  un passo che una costruzione sta aspettando (e le consegne, che sono istantanee)
    P1  l'anticipo della riga a fuoco
    P2  lavoro di fondo: verdetti in attesa, schede da rinnovare
Fra una finestra di pagine e l'altra un lavoro CEDE il turno a chiunque aspetti con priorita' piu' alta, e a
chi aspetta con priorita' UGUALE se, alla resa vista finora, gli mancano piu' di PAGINE_PER_TURNO pagine; poi torna
in coda: il suo stato e' tutto nel database. Cosi' una ricerca lunga non tiene ferme le altre righe, e le righe
normali, che finiscono in poche pagine, si servono in ordine d'arrivo invece che a turno (lotto 353).
Una costruzione piu' recente per la stessa POSIZIONE con un'altra lista (la ricerca mentre si digita)
SUPERA la vecchia: la vecchia smette al primo turno, e chi la aspettava lo sa.

NIENTE SILENZI: ogni lavoro P0 finisce con una risposta, anche quando fallisce.
"""
import heapq
import json
import sys
from threading import Thread, Condition
from time import time as _ora
from urllib.parse import parse_qsl

from modules import paginator, sorgenti
from modules.kodi_utils import logger, set_property, clear_property

# LOTTO 341 -- era 3, e la ragione scritta qui era "sulla stick le raffiche di rete sono una causa nota di
# riavvio". Non lo erano: i riavvii della Mi Stick venivano dall'alimentatore guasto (cold_boot del 31/08, poi
# confermato). Il tetto non proteggeva niente e serializzava i giudizi: una pagina da 20 titoli ne giudicava 3
# alla volta, cioe' sette attese di rete in fila invece di una.
# 20 e' una pagina TMDb intera: dentro una pagina non c'e' altro da mettere in parallelo. Ed e' anche il punto
# oltre il quale TMDb non restituisce di piu', misurato il 24/09 dal Mac con schede complete (append come
# metadata.py): 20 insieme -> 14-26 richieste/s, 0,46 s l'una, nessun 429; 40 insieme -> 13-22 richieste/s,
# 1,02 s l'una. Raddoppiare fa solo aspettare di piu' ciascuno. Il limite dichiarato di TMDb e' "intorno alle
# 40 richieste al secondo": un 429 conta per l'interruttore di http_client, e tre di fila chiudono TMDb per
# tutti per 30 s -- per questo non si sale oltre la misura.
RETE_IN_PARALLELO = 20
# Le pagine della sorgente lette in anticipo, quando la resa dice che una non basta. Resta 3, e non per la rete:
# ogni pagina letta porta 20 titoli da giudicare, e con 20 pagine una ricerca che il filtro svuota ne
# giudicherebbe 400 per trovarne pochi. Le pagine in piu' non si buttano, ma costano comunque i loro giudizi.
FINESTRA_PAGINE = 3
P0, P1, P2 = 0, 1, 2
# LOTTO 353 -- quando un lavoro cede il turno a chi aspetta con la sua stessa priorita': quando, alla resa vista
# finora, gli mancano piu' di PAGINE_PER_TURNO pagine. Prima cedeva dopo ogni finestra (la regola "a turno"): con tre
# righe in attesa ognuna riceveva una pagina a giro e finivano tutte tardi, e Kodi, che costruisce al piu' tre righe
# insieme, faceva partire la quarta solo quando una delle tre finiva. Hub Film sulla stick il 25/09: 502 e 503 pronte
# a 11 e 12 s invece di 5 e 9 (modello sugli orari del log, che lo riproduce entro un secondo).
# Si decide sulla STIMA e non sul numero di pagine gia' lette: la prima versione (cedere dopo tre pagine) faceva
# tenere il turno per quattro pagine a una riga da 3 titoli su 20, e le righe arrivate dopo la aspettavano (Mac,
# Home del 25/09 01:35, home.503). Una riga normale ne ha per 1-3 pagine e finisce; una che il filtro svuota si
# riconosce dalla prima pagina e lascia passare le altre.
PAGINE_PER_TURNO = 3
# LOTTO 356 -- il titolo lento non ferma la pagina. La pagina aspetta i suoi titoli finche' non ha risposto
# QUOTA_PAGINA di loro, poi concede ai restanti al piu' altrettanto tempo (mai meno di ATTESA_CODA_MINIMA): chi non
# ha risposto passa IN ATTESA, la pagina risponde, e il preparatore va avanti. La richiesta lenta intanto finisce
# da se' e lascia scheda e verdetto nella cache; quando e' finita il giro delle attese riprende il titolo dalla
# cache e lo mette fra i pronti: entra nel passo dopo, in coda a cio' che la riga mostra (regola del 16/09).
# Misurato il 25/09 sul Mac: una richiesta a blu-ray.com da 4,7 s (pagina da 6,2 s invece di ~1,7) e una a IMDb da
# 4,0 s (pagina da 4,1 invece di ~0,7), e con un preparatore solo le aspettavano tutte le righe. La regola e'
# relativa e non un tempo fisso: una pagina lenta TUTTA (connessioni fredde, stick) non perde nessuno.
QUOTA_PAGINA = 0.75
ATTESA_CODA_MINIMA = 1.0
# I passi pronti in piu' che la riga a fuoco tiene davanti a se'.
ANTICIPO_PASSI = 1

def _log(msg):
	logger('Fen Light', 'PREPARATORE %s' % msg)

# --- la sorgente di una lista, e l'identita' dei suoi elementi --------------------------------------------

def _tipo_media(voce):
	"""'movie' | 'tvshow' per un elemento di lista mista (Trakt, MDbList); None per stagioni ed episodi."""
	nome = voce.get('type') if isinstance(voce, dict) else None
	if nome == 'movie': return 'movie'
	if nome == 'show': return 'tvshow'
	return None

class Lista:
	"""Una lista da preparare: i suoi parametri, la sua sorgente, e come si legge un suo elemento."""
	def __init__(self, chiave, parametri, tipo, azione, esterna, posizione):
		self.chiave, self.parametri, self.tipo, self.azione = chiave, parametri, tipo, azione
		self.esterna, self.posizione = esterna, posizione
		self.params = dict(parse_qsl(parametri, keep_blank_values=True))
		self.id = None
		self._sorgente = None

	def sorgente(self):
		if self._sorgente is None:
			self._sorgente = sorgenti.sorgente(self.tipo, self.params) or False
		return self._sorgente or None

	def filtrata(self):
		s = self.sorgente()
		return bool(self.esterna and s and s.filtrabile)

	def voce(self, grezza, id_type):
		"""(media_type, id_type, id, firma_nota) di un elemento grezzo. firma_nota e' None se il tmdb non si sa ancora."""
		if self.tipo in ('movie', 'tvshow'):
			media_type = self.tipo
			ident = grezza
		else:
			media_type = _tipo_media(grezza)
			if media_type is None: return None
			ident = grezza.get('media_ids') or {}
			id_type = 'trakt_dict'
		return media_type, id_type, ident, firma_nota(media_type, id_type, ident)

def firma_nota(media_type, id_type, ident):
	"""(tipo, tmdb) quando l'id della sorgente lo porta gia'; None se lo dira' solo la scheda."""
	tmdb = paginator.tmdb_di(ident) if id_type in ('tmdb_id', 'trakt_dict') else None
	return (paginator.TIPI[media_type], tmdb) if tmdb else None

# --- il giudizio di UN titolo: scheda, poi verdetto --------------------------------------------------------

PRONTO, SCARTO, ATTESA = 'pronto', 'scarto', 'attesa'
# Le fonti esterne dei filtri "uscito" e "doppiato" (lotto 348): se una ha l'interruttore aperto, l'utente lo sa.
FONTI_FILTRI = ('m.blu-ray.com', 'apis.justwatch.com', 'www.themoviedb.org')

class Contesto:
	"""Le impostazioni che un giudizio legge. Si leggono una volta per lavoro, non per titolo.

	LOTTO 348 -- i filtri sono `uscita` (uscito in digitale da qualche parte) e, sotto di lui, `lingue` (doppiato in
	almeno una): il doppiato senza l'uscito non vale, come nella finestra delle impostazioni. Prima c'era `paese`.
	"""
	def __init__(self):
		from modules.settings import tmdb_api_key, mpaa_region, dub_filter_enabled, dub_filter_languages, meta_language, release_filter_enabled
		from modules.utils import get_datetime, get_current_timestamp
		self.api_key, self.mpaa = tmdb_api_key(), mpaa_region()
		self.uscita = release_filter_enabled()
		self.lingue = dub_filter_languages() if self.uscita and dub_filter_enabled() else ()
		self.lingua = meta_language()
		self.data, self.ora = get_datetime(), get_current_timestamp()

	def impronta(self):
		return '%s|%s|%s' % ('uscita' if self.uscita else '', ','.join(self.lingue), self.lingua)

def scheda(media_type, id_type, ident, ctx):
	"""La scheda del titolo. Una scheda scaduta si riscarica e si sovrascrive (meta_cache.get, lotto 334)."""
	from modules.metadata import movie_meta, tvshow_meta
	funzione = movie_meta if media_type == 'movie' else tvshow_meta
	try: meta = funzione(id_type, ident, ctx.api_key, ctx.mpaa, ctx.data, ctx.ora)
	except Exception as e:
		_log('scheda %s %s non ottenuta: %r' % (media_type, ident, e)); return None
	return meta

def verdetto(media_type, tmdb, meta, ctx):
	"""True / False / None (inconcludente): il titolo passa i filtri accesi? La regola e' in modules/uscita.

	Prima "uscito", che costa meno (quasi sempre la scheda l'ha gia' deciso), poi il doppiato, solo se chiesto e solo
	per un titolo uscito. Una domanda TMDb sola per le due regole (uscita.DatiTmdb).
	"""
	from modules import uscita
	domanda = uscita.DatiTmdb(media_type, tmdb, ctx.api_key)
	v = uscita.verdetto(media_type, tmdb, meta, ctx, domanda)
	if not v or not ctx.lingue: return v
	return uscita.doppiato(media_type, tmdb, meta, ctx.lingue, ctx, domanda)

def giudica(media_type, id_type, ident, filtrata, ctx, ammetti=None):
	"""(esito, firma, scheda). La scheda PRIMA del verdetto: scaricandola arrivano gratis anche i verdetti dei filtri
	(modules/uscita.registra_da_scheda), che chiudono la maggior parte dei casi senza altre richieste.

	Una scheda che non arriva non e' un titolo inesistente: la rete puo' non aver risposto. Il titolo
	resta IN ATTESA e si riprova (se la sua firma si sa gia'); lo si scarta solo quando TMDb dice che non
	esiste (blank_entry). `ammetti` e' la regola in piu' della sorgente (Discover), decisa sulla scheda.
	"""
	try:
		meta = scheda(media_type, id_type, ident, ctx)
		if meta is None:
			nota = firma_nota(media_type, id_type, ident)
			return (ATTESA, nota, None) if nota else (SCARTO, None, None)
		if meta.get('blank_entry') or not meta.get('tmdb_id'): return SCARTO, None, None
		firma = (paginator.TIPI[media_type], int(meta['tmdb_id']))
		if ammetti is not None and not ammetti(meta): return SCARTO, firma, meta
		if not filtrata or not ctx.uscita: return PRONTO, firma, meta
		# Il "no" scarta, il "non so" rimette in attesa: un titolo senza verdetto non compare finche' non ce l'ha.
		try: v = verdetto(media_type, int(meta['tmdb_id']), meta, ctx)
		except Exception as e:
			_log('verdetto tmdb=%s fallito: %r' % (meta.get('tmdb_id'), e)); v = None
		if v is None: return ATTESA, firma, meta
		return (PRONTO if v else SCARTO), firma, meta
	except Exception as e:
		# Un difetto nel giudizio di UN titolo non ferma la pagina: il titolo si scarta e il log lo dice.
		_log('giudizio %s %s fallito: %r' % (media_type, ident, e))
		return SCARTO, None, None

# --- la misura di una pagina (lotto 351) ------------------------------------------------------------------------

def _cronometrato(*argomenti):
	"""giudica(), e quanto ci ha messo. giudica non solleva: ogni difetto di un titolo diventa uno SCARTO."""
	inizio = _ora()
	esito = giudica(*argomenti)
	return esito, _ora() - inizio

def _mediana(valori):
	ordinati = sorted(valori)
	return ordinati[len(ordinati) // 2] if ordinati else 0.0

def _misura_pagina(voci, cronometrati, giudizi, registro):
	"""La riga MISURA: il tempo dei giudizi di una pagina, e dove e' andato.

	Serve a una domanda sola: la pagina aspetta TMDb o un titolo lento? Se il titolo piu' lento dura quasi quanto la
	pagina e la mediana e' bassa, e' la coda (un titolo); se tutti durano quasi quanto la pagina e le attese di un
	posto crescono, e' la velocita' di un host. Per host: richieste, mediana e massimo, e la somma delle attese di un
	posto sotto il tetto dell'host (http_client.connessioni_per) e della finestra del sito di TMDb (justwatch_api).
	"""
	if not cronometrati: return 'giudizi 0'
	tempi = [secondi for _esito, secondi in cronometrati]
	lento = max(range(len(tempi)), key=tempi.__getitem__)
	(esito, firma, _meta), _s = cronometrati[lento]
	chi = 'tmdb=%s' % firma[1] if firma else '%s %s' % (voci[lento][0], voci[lento][2])
	ordinati = sorted(tempi)
	parti = ['giudizi %d in %.2f s: min %.2f med %.2f p90 %.2f max %.2f (%s %s)' % (len(tempi), giudizi, ordinati[0],
		_mediana(tempi), ordinati[min(len(ordinati) - 1, int(len(ordinati) * 0.9))], ordinati[-1], chi, esito)]
	host = {}
	for genere, nome, secondi in list(registro):
		h = host.setdefault(nome, {'richiesta': [], 'posto': 0.0, 'finestra': 0.0})
		if genere == 'richiesta': h['richiesta'].append(secondi)
		else: h[genere] += secondi
	for nome in sorted(host, key=lambda k: -len(host[k]['richiesta'])):
		h = host[nome]
		r = h['richiesta']
		testo = '%s %d rich.' % (nome, len(r))
		if r: testo += ' med %.2f max %.2f' % (_mediana(r), max(r))
		if h['posto'] >= 0.01: testo += ' attesa posto %.2f s' % h['posto']
		if h['finestra'] >= 0.01: testo += ' attesa finestra %.2f s' % h['finestra']
		parti.append(testo)
	return ' | '.join(parti)

# --- il preparatore ------------------------------------------------------------------------------------------

def _pagine_mancanti(mancano, lette, presi):
	"""Le pagine che, alla resa vista finora (`presi` titoli pronti in `lette` pagine), bastano per `mancano` titoli.
	None se la resa non si sa ancora: nessuna pagina letta, o nessun titolo preso."""
	if not presi: return None
	return -(-mancano * lette // presi)

def _finestra(mancano, lette, presi):
	"""Quante pagine leggere insieme: quelle che, alla resa vista finora, bastano per `mancano` titoli (1..FINESTRA_PAGINE)."""
	stima = _pagine_mancanti(mancano, lette, presi)
	if stima is None: return FINESTRA_PAGINE if lette else 1
	return max(1, min(FINESTRA_PAGINE, stima))

def _lungo(mancano, lette, presi):
	"""Il lavoro ne ha ancora per piu' di un turno? Mai prima di aver letto una pagina: due lavori pari non si cedono
	il turno a vicenda senza leggere niente. Dopo, lungo se la stima supera PAGINE_PER_TURNO, o se non si sa (zero
	titoli presi: una ricerca che il filtro svuota)."""
	if not lette: return False
	stima = _pagine_mancanti(mancano, lette, presi)
	return stima is None or stima > PAGINE_PER_TURNO

class Lavoro:
	__slots__ = ('priorita', 'genere', 'chiave', 'dati')
	def __init__(self, priorita, genere, chiave, dati):
		self.priorita, self.genere, self.chiave, self.dati = priorita, genere, chiave, dati

class Interrotto(Exception):
	"""Il lavoro cede il turno: torna in coda e riprendera' da dove dice il database."""

class Superata(Exception):
	"""Nella posizione di questo passo e' stata chiesta un'altra lista, dopo di lui."""

class Preparatore:
	def __init__(self, rete=None):
		self._coda, self._seq = [], 0
		self._cond = Condition()
		self._rete = rete   # un esecutore con submit(); None = in linea (prove)
		self._impronta = None
		self._fermo = False
		# posizione -> (istante, chiave) della richiesta PIU' RECENTE per quella posizione. Vedi Superata.
		self._ultima = {}
		# Titoli rimasti in attesa nel lavoro in corso, e se l'interruttore di blu-ray.com e' gia' stato
		# segnalato per l'apertura attuale. Vedi _segnala_interruttore.
		self._attese_lavoro = 0
		self._interruttore_segnalato = False
		# LOTTO 356 -- le firme dei titoli rimasti oltre la scadenza di una pagina, con la richiesta ancora in volo: il
		# giro delle attese non li rigiudica finche' non tornano (sarebbero richieste doppie).
		self._in_volo = set()
		# LOTTO 351 -- la riga MISURA di ogni pagina, con la strumentazione accesa (modules/perf). Vedi _misura_pagina.
		try:
			from modules.perf import enabled
			self._misura = enabled()
		except Exception: self._misura = False

	# --- ingresso (dal thread delle notifiche) ---
	def accoda(self, lavoro):
		with self._cond:
			if lavoro.genere == 'passo':
				# Un passo per la stessa lista si FONDE con quello gia' in coda: vale il passo piu' alto, e una
				# ricomposizione chiesta da uno dei due. Chi aspetta riceve comunque la sua risposta.
				for _p, _s, altro in self._coda:
					if altro.genere == 'passo' and altro.chiave == lavoro.chiave:
						altro.dati['passi'] = max(altro.dati.get('passi') or 0, lavoro.dati.get('passi') or 0)
						altro.dati['ricomponi'] = lavoro.dati.get('ricomponi') or altro.dati.get('ricomponi')
						return
			elif lavoro.genere != 'consegna' and any(altro.genere == lavoro.genere and altro.chiave == lavoro.chiave
													for _p, _s, altro in self._coda):
				return
			self._seq += 1
			heapq.heappush(self._coda, (lavoro.priorita, self._seq, lavoro))
			self._cond.notify()

	def ricevi(self, metodo, dati):
		"""Smista un messaggio arrivato a onNotification. Torna True se era per il preparatore."""
		try: carico = json.loads(dati) if isinstance(dati, str) else dati
		except Exception:
			_log('messaggio illeggibile (%s)' % metodo); return True
		if metodo == paginator.MESSAGGIO_PASSO:
			posizione = carico.get('posizione')
			if posizione:
				# Vale l'istante in cui la costruzione e' NATA, non l'ordine di arrivo: dopo un riavvio del servizio le
				# costruzioni in attesa rimandano la richiesta in un ordine qualunque, e la ricerca vecchia non deve
				# sorpassare quella nuova.
				nuova = (carico.get('istante') or 0, carico.get('chiave'))
				with self._cond:
					if nuova[0] >= self._ultima.get(posizione, (0, None))[0]: self._ultima[posizione] = nuova
			self.accoda(Lavoro(P0, 'passo', carico.get('chiave'), carico))
		elif metodo == paginator.MESSAGGIO_DB:
			self.accoda(Lavoro(P0, 'consegna', None, carico))
		elif metodo == paginator.MESSAGGIO_SCADUTE:
			self.accoda(Lavoro(P2, 'schede', carico.get('chiave'), carico))
		elif metodo == paginator.MESSAGGIO_ANTICIPO:
			self.accoda(Lavoro(P1, 'anticipo', carico.get('chiave'), carico))
		else: return False
		return True

	def _aspetta(self, secondi):
		"""Attende fino a `secondi`, o meno se arriva un lavoro o l'arresto. Torna True se e' stato fermato.

		Niente xbmc.Monitor in questo thread (lotto 17/09, crash alla chiusura di Kodi sul Mac): Kodi mette le
		notifiche di OGNI Monitor nella sua coda globale e le consegna solo quando il thread che l'ha creato
		chiama waitForAbort. Questo thread aspetta quasi sempre su _cond, quindi la coda cresceva senza che
		nessuno la svuotasse, e all'uscita del processo Kodi distruggeva quelle callback con l'interprete gia'
		chiuso (segfault in RetardedAsyncCallbackHandler). L'arresto arriva gia' da ferma(), che il servizio
		chiama quando il suo Monitor principale vede l'abort."""
		with self._cond:
			if not self._fermo: self._cond.wait(secondi)
			return self._fermo

	def ferma(self):
		with self._cond:
			self._fermo = True
			self._cond.notify()
		if self._rete is not None:
			try: self._rete.shutdown(wait=False)
			except Exception: pass

	# --- il ciclo ---
	def _prossimo(self):
		with self._cond:
			while not self._coda and not self._fermo:
				# LOTTO 343 -- senza lavoro la rete del servizio si ferma: e' il momento di chiudere le connessioni
				# rimaste ferme, invece di tenerle finche' il server non le chiude lui. Se non ce ne sono si aspetta
				# come prima, senza svegliarsi. http_client si guarda solo se e' gia' stato importato: se non lo
				# e', connessioni non ce ne possono essere.
				rete = sys.modules.get('modules.http_client')
				if rete is None or not rete.connessioni_ferme():
					self._cond.wait()
				elif not self._cond.wait(rete.SCADENZA_FERME):
					rete.chiudi_connessioni_ferme()
			if self._fermo: return None
			return heapq.heappop(self._coda)[2]

	def _batti(self):
		set_property(paginator.SERVIZIO_PROP, '%d' % (_ora() * 1000))

	def _cedi(self, lista, priorita, anche_uguali):
		"""Prima di ogni finestra di pagine: il lavoro continua, cede il turno, o e' stato superato.

		Si cede sempre a chi ha priorita' piu' alta. A chi ha la STESSA solo se il lavoro e' lungo (_lungo, lotto 353;
		prima dopo ogni finestra): una riga normale finisce prima che cominci la successiva.
		"""
		soglia = priorita if anche_uguali else priorita - 1
		with self._cond:
			if self._fermo: raise Interrotto()
			if self._superata(lista): raise Superata()
			if any(p <= soglia for p, _s, _l in self._coda): raise Interrotto()

	def _superata(self, lista):
		ultima = self._ultima.get(lista.posizione) if lista.posizione else None
		return ultima is not None and ultima[1] != lista.chiave

	def run(self):
		self._batti()
		paginator.invia(paginator.MESSAGGIO_SERVIZIO, {})
		_log('avviato')
		try:
			while True:
				lavoro = self._prossimo()
				if lavoro is None: break
				if self._in_pausa(lavoro):
					# Il lavoro torna in coda e il ciclo riguarda la coda dopo un secondo, o prima se arriva un altro
					# lavoro: cosi' un lavoro di fondo fermo per la ricerca sorgenti non tiene in ostaggio un passo
					# arrivato dopo di lui, che ha la precedenza e verra' preso per primo. In pausa il servizio e'
					# vivo: batte.
					self.accoda(lavoro)
					self._batti()
					if self._aspetta(1): break
					continue
				self.esegui(lavoro)
		finally:
			clear_property(paginator.SERVIZIO_PROP)
			_log('fermato')

	def _in_pausa(self, lavoro):
		"""Perche' questo lavoro non deve partire adesso, o '' se puo'.

		Le regole erano quelle del DubResolver, che questo preparatore sostituisce:
		  - durante la riproduzione non si fa niente: la rete e la cpu servono al film (e le costruzioni
		    sono comunque ferme, vedi l'interfaccia che muore durante la riproduzione);
		  - con il dispositivo in pausa (salvaschermo, sospensione) nemmeno;
		  - durante la ricerca delle sorgenti (lotto 238) si ferma il lavoro di FONDO. Un passo che una riga
		    sta aspettando passa lo stesso: fermarlo vorrebbe dire tenerla ferma per tutta la ricerca.
		"""
		from modules.kodi_utils import playback_active, search_running, get_property
		if playback_active(): return 'riproduzione'
		if get_property('fenlight.pause_services') == 'true': return 'servizi in pausa'
		if lavoro.priorita != P0 and search_running(): return 'ricerca sorgenti'
		return ''

	def esegui(self, lavoro):
		t0 = _ora()
		self._attese_lavoro = 0
		try:
			if lavoro.genere == 'consegna':
				from caches import widgets_cache
				if widgets_cache.ricevi(lavoro.dati): widgets_cache.checkpoint()
				return
			ctx = Contesto()
			self._controlla_impronta(ctx)
			if lavoro.genere == 'passo': self.passo(lavoro.dati, ctx)
			elif lavoro.genere == 'anticipo': self.anticipo(lavoro.dati, ctx)
			elif lavoro.genere == 'attese': self.attese(lavoro.dati, ctx)
			elif lavoro.genere == 'schede': self.schede(lavoro.dati, ctx)
		except Interrotto:
			self.accoda(lavoro)
			_log('%s %s cede il turno' % (lavoro.genere, paginator.short(lavoro.chiave or '')))
			return
		except Superata:
			paginator.invia(paginator.MESSAGGIO_PRONTO, {'chiave': lavoro.chiave, 'esito': 'superata'})
			_log('passo %s superato da una lista piu\' recente nella stessa posizione' % paginator.short(lavoro.chiave or ''))
			return
		except Exception as e:
			import traceback
			_log('%s %s FALLITO: %r\n%s' % (lavoro.genere, paginator.short(lavoro.chiave or ''), e, traceback.format_exc()))
			if lavoro.genere == 'passo':
				paginator.invia(paginator.MESSAGGIO_PRONTO, {'chiave': lavoro.chiave, 'esito': 'fallito'})
			return
		finally:
			self._batti()
		if lavoro.genere != 'consegna':
			_log('%s %s fatto in %.2f s' % (lavoro.genere, paginator.short(lavoro.chiave or ''), _ora() - t0))
			self._segnala_interruttore()

	def _segnala_interruttore(self):
		# Richiesta dell'utente (era nel DubResolver, lotto 97): *"magari una notifica che avvisa l'utente che
		# la rete non ha risposto per il filtro doppiaggio"*. Una volta per apertura dell'interruttore, e solo
		# se in questo lavoro qualche titolo e' davvero rimasto in attesa.
		# LOTTO 348 -- era il solo www.blu-ray.com, che dopo il passaggio non interroga piu' nessuno: la notifica non
		# sarebbe partita mai. Le fonti esterne dei filtri sono FONTI_FILTRI.
		try:
			from modules.http_client import breaker_state
			aperti = [(host, restano) for host, (aperto, restano) in ((h, breaker_state(h)) for h in FONTI_FILTRI) if aperto]
			if not aperti:
				self._interruttore_segnalato = False   # richiuso: la prossima apertura torna a essere una notizia
				return
			if self._interruttore_segnalato or not self._attese_lavoro: return
			host, restano = aperti[0]
			from modules.kodi_utils import notification
			notification('Filtri dei widget: %s non risponde, riprovo fra %s min. '
						'Alcuni titoli restano nascosti.' % (host, max(1, restano // 60)), 6000)
			self._interruttore_segnalato = True
		except Exception: pass

	def _controlla_impronta(self, ctx):
		# Filtri (uscita, lingue del doppiato) o lingua delle schede cambiati: cio' che e' preparato e non consegnato e' stato
		# deciso con l'altra impostazione. Si confronta un fatto, a ogni lavoro -- nessun orologio.
		impronta = ctx.impronta()
		if self._impronta is not None and impronta != self._impronta:
			from caches import widgets_cache
			widgets_cache.svuota_preparato()
			_log('impostazioni cambiate (%s -> %s): preparato buttato' % (self._impronta, impronta))
		self._impronta = impronta

	# --- i lavori ---
	def _lista(self, dati):
		from caches import widgets_cache
		lista = Lista(dati.get('chiave'), dati.get('parametri') or '', dati.get('tipo'), dati.get('azione') or '',
					bool(dati.get('esterna', True)), dati.get('posizione') or '')
		lista.id = widgets_cache.apri_lista(lista.chiave, lista.parametri, lista.azione)
		if lista.id is None: raise RuntimeError('lista non aperta (sessione assente?)')
		return lista

	def passo(self, dati, ctx):
		from caches import widgets_cache as W
		lista = self._lista(dati)
		with self._cond:
			if self._superata(lista): raise Superata()
		if lista.tipo == 'trakt':
			# Una lista Trakt con stagioni o episodi non si prepara: il database identifica solo film e serie
			# (dieci episodi della stessa serie hanno lo stesso id TMDb). La costruisce la build, per intero.
			s = lista.sorgente()
			mista = bool(s) and not paginator.lista_identificabile(s.tutti)
			W.segna_mista(lista.id, mista)
			if mista:
				paginator.invia(paginator.MESSAGGIO_PRONTO, {'chiave': lista.chiave, 'esito': 'ok'})
				_log('passo %s: lista MISTA (stagioni/episodi), la costruisce la build' % paginator.short(lista.chiave))
				return
		stato = W.stato_lista(lista.id)
		nonce = dati.get('ricomponi') or ''
		if nonce and nonce != stato.ricarica:
			self.ricomponi(lista, stato, nonce, ctx)
			stato = W.stato_lista(lista.id)
		passi = int(dati.get('passi') or 0)
		quanto = paginator.passo()
		serve = max(0, passi - stato.passi) * quanto
		if serve: self.prepara(lista, stato, serve, ctx, P0)
		assegnati = W.assegna_passi(lista.id, passi, quanto)
		paginator.invia(paginator.MESSAGGIO_PRONTO, {'chiave': lista.chiave, 'esito': 'ok'})
		_log('passo %s passi %s->%s assegnati=%s' % (paginator.short(lista.chiave), stato.passi, passi, assegnati))
		if stato.attese or self._attese_lavoro:
			self.accoda(Lavoro(P2, 'attese', lista.chiave, dict(dati, passi=0, ricomponi='', posizione='')))

	def anticipo(self, dati, ctx):
		from caches import widgets_cache as W
		lista = self._lista(dict(dati, posizione=''))
		stato = W.stato_lista(lista.id)
		self.prepara(lista, stato, ANTICIPO_PASSI * paginator.passo(), ctx, P1)

	def prepara(self, lista, stato, serve, ctx, priorita):
		"""Legge la sorgente finche' i preparati sono almeno `serve`, o la sorgente finisce.

		A FINESTRE: quando la sorgente dichiara la sua ultima pagina se ne possono leggere fino a
		FINESTRA_PAGINE insieme, poi si giudicano in ordine. Quante, lo dice la RESA misurata in questo lavoro:
		una riga normale da' un titolo per voce e si legge una pagina per volta, una ricerca che il filtro svuota
		(il 16/09 "more": un titolo ogni cinque pagine, 180 ms l'una) ne legge tre.
		Si GIUDICA solo finche' serve: appena i preparati bastano, le pagine lette in piu' non si giudicano e non si
		salvano, e il passo dopo le rilegge. Leggere costa poco, giudicare no (una scheda e un verdetto per titolo,
		0,6-1 s a pagina nella misura 351), e ritardava la risposta: Mac, 25/09 01:35, home.502 aveva 44 titoli su 40
		alla pagina 3 e ha giudicato anche la 4 (lotto 353).
		"""
		from caches import widgets_cache as W
		s = lista.sorgente()
		if s is None: raise RuntimeError('nessuna sorgente per %s' % lista.parametri)
		noti = set(stato.elementi) | set(stato.pronti) | set(stato.attese)
		pronti, pagina, fine = len(stato.pronti), stato.pagina, stato.fine
		filtrata = lista.filtrata()
		ultima = None   # la sorgente la dichiara alla prima lettura di questo lavoro
		lette, presi = 0, 0
		while pronti < serve and not fine:
			self._cedi(lista, priorita, anche_uguali=_lungo(serve - pronti, lette, presi))
			fino = pagina + 1 if ultima is None else min(pagina + _finestra(serve - pronti, lette, presi), ultima)
			finestra = list(range(pagina + 1, fino + 1))
			inizio = _ora()
			letture = self._in_parallelo(s.leggi, [(n,) for n in finestra])
			lettura = _ora() - inizio
			for n, (grezzi, ultima) in zip(finestra, letture):
				grezzi = grezzi or []
				nuovi_pronti, nuove_attese, misura = self._giudica_pagina(lista, s, grezzi, filtrata, noti, ctx)
				fine = not sorgenti.continua(n, grezzi, ultima)
				W.salva_pagina(lista.id, nuovi_pronti, nuove_attese, n, fine)
				pronti += len(nuovi_pronti)
				pagina, lette, presi = n, lette + 1, presi + len(nuovi_pronti)
				self._batti()
				_log('pagina %s di %s: letti=%s pronti=%s attese=%s (pronti in tutto %s/%s) fine=%s'
					% (n, paginator.short(lista.chiave), len(grezzi), len(nuovi_pronti), len(nuove_attese), pronti, serve, fine))
				if misura:
					# La lettura e' della finestra intera: si scrive sulla sua prima pagina.
					_log('MISURA pagina %s di %s: lettura %s | %s' % (n, paginator.short(lista.chiave),
						'%.2f s (%s pagine)' % (lettura, len(finestra)) if n == finestra[0] else 'con la pagina %s' % finestra[0], misura))
				if fine or pronti >= serve: break

	def _giudica_pagina(self, lista, s, grezzi, filtrata, noti, ctx):
		voci = []
		for g in grezzi:
			v = lista.voce(g, s.id_type)
			if v is None: continue
			if v[3] is not None and v[3] in noti: continue
			voci.append(v)
		registro = None
		if self._misura:
			from modules import http_client
			registro = []
			http_client.registra(registro)
		inizio = _ora()
		try: cronometrati, tardivi = self._giudizi_con_scadenza([(v[0], v[1], v[2], filtrata, ctx, s.ammetti) for v in voci])
		finally:
			if registro is not None: http_client.registra(None)
		giudizi = _ora() - inizio
		# Un titolo oltre la scadenza aspetta come chi non ha ancora un verdetto. Senza tmdb nella sorgente pero' la sua
		# firma la dira' solo la scheda, e in attesa non si puo' mettere: lui si aspetta.
		in_attesa = []
		for i, futuro in sorted(tardivi.items()):
			nota = voci[i][3]
			if nota is None: cronometrati[i] = futuro.result()
			else:
				cronometrati[i] = ((ATTESA, (nota[0], int(nota[1])), None), giudizi)
				in_attesa.append(((nota[0], int(nota[1])), futuro))
		if in_attesa:
			self._segui_tardivi(lista, in_attesa)
			_log('pagina di %s: %s titoli oltre la scadenza (%.2f s), in attesa: %s' % (paginator.short(lista.chiave),
				len(in_attesa), giudizi, ','.join(str(f[1]) for f, _ in in_attesa)))
		esiti = [esito for esito, _secondi in cronometrati]
		misura = _misura_pagina(voci, cronometrati, giudizi, registro) if registro is not None else ''
		if misura and in_attesa: misura += ' | tardivi %d' % len(in_attesa)
		pronti, attese = [], []
		for esito, firma, meta in esiti:
			if firma is None or firma in noti: continue
			noti.add(firma)
			if esito == PRONTO: pronti.append((firma, meta))
			elif esito == ATTESA: attese.append(firma)
		# L'ordine della sorgente, o quello che la sorgente chiede sulle schede (Discover per voto): dentro la
		# pagina, cosi' cio' che e' gia' consegnato non si muove mai.
		if s.ordine is not None: pronti.sort(key=lambda coppia: s.ordine(coppia[1]))
		self._attese_lavoro += len(attese)
		return [firma for firma, _meta in pronti], attese, misura

	def _giudizi_con_scadenza(self, argomenti):
		"""I giudizi di una pagina, cronometrati, senza aspettare il piu' lento (lotto 356, vedi QUOTA_PAGINA).

		Torna (risultati, tardivi): nei risultati, nell'ordine degli argomenti, None per chi e' oltre la scadenza; i
		tardivi sono {indice: futuro}, e il futuro continua da se'. Senza una rete vera (in linea, o i finti delle
		prove) si aspettano tutti, come prima.
		"""
		from concurrent.futures import Future, wait, FIRST_COMPLETED
		if self._rete is None: return [_cronometrato(*a) for a in argomenti], {}
		futuri = [self._rete.submit(_cronometrato, *a) for a in argomenti]
		if not futuri or not isinstance(futuri[0], Future): return [f.result() for f in futuri], {}
		inizio = _ora()
		quota = -(-len(futuri) * int(QUOTA_PAGINA * 100) // 100)
		in_corso = set(futuri)
		while in_corso and len(futuri) - len(in_corso) < quota:
			_fatti, in_corso = wait(in_corso, return_when=FIRST_COMPLETED)
		if in_corso: _fatti, in_corso = wait(in_corso, timeout=max(ATTESA_CODA_MINIMA, _ora() - inizio))
		risultati, tardivi = [], {}
		for i, futuro in enumerate(futuri):
			if futuro in in_corso:
				risultati.append(None); tardivi[i] = futuro
			else: risultati.append(futuro.result())
		return risultati, tardivi

	def _segui_tardivi(self, lista, in_attesa):
		"""I titoli oltre la scadenza restano in volo; quando l'ultimo di questa pagina torna, un giro delle attese
		li riprende dalla cache (lotto 356)."""
		dati = {'chiave': lista.chiave, 'parametri': lista.parametri, 'tipo': lista.tipo, 'azione': lista.azione,
				'esterna': lista.esterna, 'passi': 0, 'ricomponi': '', 'posizione': ''}
		restano = [len(in_attesa)]
		def tornato(firma):
			with self._cond:
				self._in_volo.discard(firma)
				restano[0] -= 1
				ultimo = restano[0] == 0
			if ultimo: self.accoda(Lavoro(P2, 'attese', lista.chiave, dict(dati)))
		with self._cond: self._in_volo.update(firma for firma, _f in in_attesa)
		for firma, futuro in in_attesa: futuro.add_done_callback(lambda _f, firma=firma: tornato(firma))

	def _in_parallelo(self, funzione, argomenti):
		# L'ORDINE dei risultati e' quello degli argomenti, qualunque sia l'ordine in cui la rete risponde. Le
		# eccezioni risalgono al lavoro: giudica le intercetta da se', una pagina non letta no.
		if self._rete is None: return [funzione(*a) for a in argomenti]
		futuri = [self._rete.submit(funzione, *a) for a in argomenti]
		return [f.result() for f in futuri]

	def _presenti(self, lista, stato):
		"""Ricomposizione: (presenti, nuovi_nella_parte_gia_letta). Vedi ricomponi."""
		s = lista.sorgente()
		if s is None: raise RuntimeError('nessuna sorgente per %s' % lista.parametri)
		presenti, nuovi = set(), []
		noti = set(stato.elementi) | set(stato.pronti) | set(stato.attese)
		intera = lista.tipo in ('mdblist', 'trakt') or s.intera
		pagina, ancora = 0, True
		while ancora and (intera or pagina < stato.pagina):
			pagina += 1
			grezzi, ultima = s.leggi(pagina)
			grezzi = grezzi or []
			ancora = sorgenti.continua(pagina, grezzi, ultima)
			for g in grezzi:
				v = lista.voce(g, s.id_type)
				if v is None: continue
				if v[3] is not None:
					presenti.add(v[3])
					if v[3] in noti: continue
				if pagina <= stato.pagina: nuovi.append(v)
		return presenti, nuovi

	def ricomponi(self, lista, stato, nonce, ctx):
		"""La COMPOSIZIONE e' cambiata (un titolo aggiunto o tolto da una lista dell'utente).

		Si rilegge la parte della sorgente gia' letta: chi non c'e' piu' sparisce, chi e' nuovo entra
		SUBITO in coda alla lista (regola del 16/09: le consegne si accodano, niente si sposta). Per le
		liste intere la presenza si decide sull'intera lista: una sola aggiunta in cima sposta tutto di
		una posizione, e un titolo scivolato oltre la parte letta non e' un titolo tolto.
		"""
		from caches import widgets_cache as W
		presenti, nuovi = self._presenti(lista, stato)
		# Un titolo senza tmdb nella sorgente si riconosce solo dalla scheda: la sua firma entra fra i
		# presenti dopo il giudizio.
		s = lista.sorgente()
		esiti = self._in_parallelo(giudica, [(v[0], v[1], v[2], lista.filtrata(), ctx, s.ammetti) for v in nuovi])
		noti = set(stato.elementi) | set(stato.pronti) | set(stato.attese)
		entrano, attese = [], []
		for esito, firma, _meta in esiti:
			if firma is None: continue
			presenti.add(firma)
			if firma in noti: continue
			noti.add(firma)
			if esito == PRONTO: entrano.append(firma)
			elif esito == ATTESA: attese.append(firma)
		self._attese_lavoro += len(attese)
		tolti = W.ricomponi_lista(lista.id, presenti, nonce)
		W.accoda_elementi(lista.id, entrano)
		if attese: W.salva_pagina(lista.id, [], attese, stato.pagina, stato.fine)
		_log('ricomposizione %s: tolti=%s entrati=%s in attesa=%s' % (paginator.short(lista.chiave), tolti, len(entrano), len(attese)))

	def attese(self, dati, ctx):
		"""I titoli senza verdetto di una lista: si riprova, una volta per passo servito."""
		from caches import widgets_cache as W
		lista = self._lista(dati)
		stato = W.stato_lista(lista.id)
		if not stato.attese: return
		promossi, bocciati = [], []
		nomi = dict((v, k) for k, v in paginator.TIPI.items())
		filtrata = lista.filtrata()
		# Lotto 356: chi ha ancora la richiesta in volo (oltre la scadenza di una pagina) si riprende quando torna.
		with self._cond: in_volo = set(self._in_volo)
		ordinate = sorted(f for f in stato.attese if f not in in_volo)
		if not ordinate: return
		# Niente `ammetti`: chi aspetta un verdetto la regola della sorgente l'ha gia' passata.
		esiti = self._in_parallelo(giudica, [(nomi[t], 'tmdb_id', tmdb, filtrata, ctx, None) for t, tmdb in ordinate])
		for firma, (esito, _f, _meta) in zip(ordinate, esiti):
			if esito == PRONTO: promossi.append(firma)
			elif esito == SCARTO: bocciati.append(firma)
		self._attese_lavoro += len(ordinate) - len(promossi) - len(bocciati)
		if not promossi and not bocciati: return
		# Una lista FINITA non avra' un passo che li prenda: entrano gia' in lista, e la riga si ricarica.
		subito = stato.fine and not stato.pronti
		W.esiti_attese(lista.id, promossi, bocciati, subito)
		_log('attese %s: promossi=%s bocciati=%s restano=%s%s' % (paginator.short(lista.chiave), len(promossi), len(bocciati),
			len(ordinate) - len(promossi) - len(bocciati), ' (lista finita: in lista subito)' if subito and promossi else ''))
		if subito and promossi: paginator.ricarica_posizioni(W.posizioni_di(lista.id))

	def schede(self, dati, ctx):
		"""Schede servite scadute (si riscaricano e si sovrascrivono) o mancanti (si scaricano, e la riga si ricarica)."""
		from caches import widgets_cache as W
		nomi = dict((v, k) for k, v in paginator.TIPI.items())
		scadute = [tuple(x) for x in dati.get('scadute') or []]
		mancanti = [tuple(x) for x in dati.get('mancanti') or []]
		# Nessuna cancellazione: una scheda scaduta si riscarica leggendola (meta_cache.get la tratta come
		# assente) e si sovrascrive solo a download riuscito. Una costruzione che legge nel frattempo la trova.
		esiti = self._in_parallelo(giudica, [(nomi[t], 'tmdb_id', tmdb, False, ctx, None) for t, tmdb in scadute + mancanti])
		ottenute = [f for (e, f, _m) in esiti[len(scadute):] if e == PRONTO]
		_log('schede %s: rinnovate=%s mancanti=%s ottenute=%s' % (paginator.short(dati.get('chiave') or ''),
			len(scadute), len(mancanti), len(ottenute)))
		if ottenute and dati.get('chiave'):
			lista = self._lista(dict(dati, posizione=''))
			paginator.ricarica_posizioni(W.posizioni_di(lista.id))

def avvia():
	"""Lato SERVIZIO: crea e fa partire il preparatore. Torna l'istanza (per smistarle i messaggi)."""
	from concurrent.futures import ThreadPoolExecutor
	from caches.base_cache import usa_connessioni_condivise
	# LOTTO 342 -- questi thread aspettano la rete: niente connessioni proprie ai database (vedi base_cache).
	p = Preparatore(ThreadPoolExecutor(max_workers=RETE_IN_PARALLELO, thread_name_prefix='FL:rete',
									   initializer=usa_connessioni_condivise))
	t = Thread(target=p.run, name='FL:preparatore')
	t.daemon = True
	t.start()
	return p
