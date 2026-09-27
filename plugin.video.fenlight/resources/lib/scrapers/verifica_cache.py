# -*- coding: utf-8 -*-
"""LOTTO 364 -- il controllo cache di TorBox a ogni provider che finisce (SORGENTI.md).

Prima: external.py aspettava che TUTTI gli scraper avessero finito, univa i risultati e solo allora chiedeva a
TorBox cosa fosse in cache (TB_check): 1,4 s di mediana e fino a 4,3 s in coda a tutto, misurato il 25/09 su 67
ricerche. Gli scraper veloci (Torrentio 0,3 s, MediaFusion 0,6 s) avevano finito da secondi e i loro hash
aspettavano quelli lenti (DMM 4,2 s, Knaben 5,6 s di media).

Ora ogni provider, appena ha i suoi risultati, li consegna qui; la domanda a TorBox parte subito, a blocchi, in
parallelo agli scraper ancora al lavoro. Alla fine resta da aspettare, di solito, solo l'ultimo blocco.

Lo stesso lavoro di TB_check, nello stesso ordine: la cache locale (`debrid_data`, 24 h) prima, poi TorBox per
gli ignoti, e il verdetto scritto in `debrid_data`. Cambia QUANDO, non COSA.

LOTTO 365 -- dopo la risposta leggera di un blocco, per gli hash IN CACHE il cui elenco dei file non e' in
pack_files parte la richiesta con `list_files`, a blocchi da 100 (misurato il 25/09: 1,0 s di mediana a blocco,
1,9 s al 90° percentile, quasi indipendente da quanti hash o file). Si aspettano al piu' TETTO_ELENCHI secondi dopo
la fine del controllo cache; cio' che arriva dopo si scrive comunque in pack_files per la ricerca successiva (il
thread sopravvive alla fine dell'invocazione: verificato il 25/09, 67 ricerche su 67).
"""
import time
from threading import Lock, Semaphore, Thread
from modules.debrid import query_local_cache, add_to_local_cache
from modules.kodi_utils import logger

BLOCCO = 200      # hash per richiesta: come i blocchi usati nel test del 25/09, tutti riusciti
PARALLELO = 4     # richieste insieme al piu'
BLOCCO_ELENCHI = 100
TETTO_ELENCHI = 2.0
# LOTTO 370 -- dopo gli scraper i blocchi in volo si aspettano fino a MARGINE (sopra il 99° percentile misurato, 1,5 s);
# poi solo se qualcuno in attesa copre una fascia che nessuna sorgente in cache copre gia' (external._copertura).
MARGINE = 2.5


def risposta_buona(r):
	"""Lotto 387: una risposta di checkcached da cui si puo' scrivere un verdetto."""
	return isinstance(r, dict) and bool(r.get('success')) and isinstance(r.get('data'), list)


class VerificaTorBox:
	def __init__(self):
		self._lock = Lock()
		self._posti = Semaphore(PARALLELO)
		self._visti = set()
		self._in_cache = set()
		self._fili = []
		self._blocco_di = {}      # filo -> hash del suo blocco (lotto 370)
		self.lasciati = set()
		self._fili_elenchi = []
		self.elenchi = {}         # hash -> [(percorso, nome, byte)] arrivati in questa ricerca
		self.richieste = 0
		self.ms_richieste = []
		self.ms_elenchi = []

	def consegna(self, hash_list):
		"""Gli hash di un provider. Ritorna subito: le richieste partono in thread."""
		nuovi = []
		with self._lock:
			for h in hash_list or []:
				h = (h or '').lower()
				if h and h not in self._visti:
					self._visti.add(h)
					nuovi.append(h)
		if not nuovi: return
		try: noti = query_local_cache(nuovi) or []
		except: noti = []
		noti_tb = dict((x[0], x[2]) for x in noti if x[1] == 'tb')
		gia_in_cache = [h for h, v in noti_tb.items() if v == 'True']
		with self._lock: self._in_cache.update(gia_in_cache)
		# Lotto 365: chi e' gia' noto in cache non passa da TorBox, ma il suo elenco puo' mancare.
		self._chiedi_elenchi(gia_in_cache)
		ignoti = [h for h in nuovi if h not in noti_tb]
		for i in range(0, len(ignoti), BLOCCO):
			blocco = ignoti[i:i + BLOCCO]
			filo = Thread(target=self._chiedi, args=(blocco,), name='VerificaTorBox')
			with self._lock:
				self._fili.append(filo)
				self._blocco_di[filo] = blocco
			filo.start()

	def _chiedi(self, blocco):
		with self._posti:
			avvio = time.time()
			try:
				from apis.torbox_api import TorBoxAPI
				risultati = TorBoxAPI().check_cache(blocco)
			except: risultati = None
			ms = int((time.time() - avvio) * 1000)
			# Lotto 387: si scrive un verdetto solo da una risposta BUONA (success e l'elenco). Prima una risposta d'errore
			# (un 429, `success: false`) finiva nell'except e scriveva "non in cache" per 24 h tutto il blocco. Ora e' come
			# nessuna risposta: niente scritto, per questa ricerca non in cache, si richiedera'.
			if not risposta_buona(risultati):
				with self._lock: self.richieste += 1; self.ms_richieste.append(ms)
				return
			in_cache = set((i.get('hash') or '').lower() for i in risultati['data'] if isinstance(i, dict))
			verdetti = [(h, 'True' if h in in_cache else 'False') for h in blocco]
			try: add_to_local_cache(verdetti, 'tb')
			except: pass
			with self._lock:
				self._in_cache.update(h for h in blocco if h in in_cache)
				self.richieste += 1
				self.ms_richieste.append(ms)
		self._chiedi_elenchi([h for h in blocco if h in in_cache])

	def _chiedi_elenchi(self, in_cache):
		"""Lotto 365: l'elenco dei file per chi e' in cache e non ce l'ha. Parte fuori dal posto appena lasciato."""
		if not in_cache: return
		try:
			from caches import pack_cache
			noti = pack_cache.noti(in_cache)
			ignoti = [h for h in in_cache if h not in noti]
		except: return
		for i in range(0, len(ignoti), BLOCCO_ELENCHI):
			filo = Thread(target=self._elenco, args=(ignoti[i:i + BLOCCO_ELENCHI],), name='ElenchiTorBox')
			with self._lock: self._fili_elenchi.append(filo)
			filo.start()

	def _elenco(self, blocco):
		with self._posti:
			avvio = time.time()
			try:
				from apis.torbox_api import TorBoxAPI
				dati = (TorBoxAPI().check_cache_files(blocco) or {}).get('data') or []
			except: dati = []
			ms = int((time.time() - avvio) * 1000)
		try:
			from caches import pack_cache
			pack_cache.scrivi(dati)
			arrivati = dict(((v.get('hash') or '').lower(), pack_cache.da_torbox(v)) for v in dati if v.get('hash'))
			pack_cache.manutenzione()
		except: arrivati = {}
		with self._lock:
			self.elenchi.update((h, f) for h, f in arrivati.items() if f)
			self.ms_elenchi.append(ms)

	def attendi_elenchi(self, tetto=TETTO_ELENCHI):
		"""Lotto 365: gli elenchi in volo, al piu' `tetto` secondi da adesso (chiamata dopo attendi(), cioe' alla fine
		del controllo cache). Chi non arriva resta in volo e scrive pack_cache per la prossima ricerca."""
		fine = time.time() + tetto
		while True:
			with self._lock: vivi = [f for f in self._fili_elenchi if f.is_alive()]
			resto = fine - time.time()
			if not vivi or resto <= 0: break
			vivi[0].join(resto)
		with self._lock:
			in_ritardo = len([f for f in self._fili_elenchi if f.is_alive()])
			return dict(self.elenchi), in_ritardo

	def attendi(self, hash_list, copertura=None):
		"""Al posto di TB_check: consegna chi non e' passato da consegna(), aspetta i blocchi in volo e dice chi
		e' in cache. Stessa firma d'uso: lista degli hash in cache.

		Lotto 370: `copertura(in_attesa, in_cache) -> bool` (external._copertura). Passato MARGINE, se dice che chi e'
		ancora in attesa non aggiunge fasce nuove, non si aspetta piu': per questa ricerca quegli hash valgono "non
		in cache". I blocchi continuano e scrivono debrid_data per la ricerca dopo."""
		avvio = time.time()
		self.consegna(hash_list)
		lasciati = set()
		while True:
			with self._lock: vivi = [f for f in self._fili if f.is_alive()]
			if not vivi: break
			trascorso = time.time() - avvio
			if copertura is not None and trascorso >= MARGINE:
				with self._lock:
					in_attesa = set(h for f in vivi for h in self._blocco_di.get(f, ()))
					gia = set(self._in_cache)
				try: basta = copertura(in_attesa, gia)
				except: basta = False
				if basta:
					lasciati = in_attesa
					break
				vivi[0].join(0.1)
			else: vivi[0].join(max(0.05, MARGINE - trascorso) if copertura is not None else None)
		with self._lock:
			in_cache = [h for h in hash_list if (h or '').lower() in self._in_cache]
			richieste, ms = self.richieste, list(self.ms_richieste)
		try:
			logger('FenLight VERIFICA', 'TorBox: %d hash, %d in cache | %d richieste durante la ricerca (%s ms) | '
				   'attesa dopo gli scraper %d ms%s' % (len(self._visti), len(in_cache), richieste,
				   ','.join(str(x) for x in ms) or '-', int((time.time() - avvio) * 1000),
				   (' | non aspettati %d hash: fasce gia coperte' % len(lasciati)) if lasciati else ''))
		except: pass
		self.lasciati = lasciati
		return in_cache
