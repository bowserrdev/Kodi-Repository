# -*- coding: utf-8 -*-
# INTERRUTTORE UNICO della strumentazione (lotto 83).
#
# Perche' un modulo a se' e non una costante in paginator: paginator importa kodi_utils a livello di
# modulo, quindi kodi_utils non puo' importare paginator senza creare un ciclo -- e tre delle righe di
# misura (INVOCAZIONE, IMPORT, CONSEGNA) stanno proprio in kodi_utils. Questo file e' una FOGLIA:
# a livello di modulo importa solo xbmc e xbmcgui -- moduli C dell'API di Kodi, non codice Fen Light --
# cosi' chiunque puo' prenderlo senza cicli e senza trascinarsi dietro un albero. Costa un file in
# piu' per invocazione (~6-8 ms a cache calda), che e' il prezzo di poter spegnere tutto il resto.
#
# La lettura dell'impostazione avviene UNA volta per invocazione e viene tenuta in memoria: con
# reuselanguageinvoker=false ogni invocazione e' un interprete nuovo, quindi "una volta per
# interprete" e "una volta per invocazione" sono la stessa cosa.
#
# Cio' che NON viene spento: le chiamate perf_counter() sparse nei costruttori. Sono letture di
# orologio, ordini di grandezza sotto quello che misurano, e toglierle vorrebbe dire smontare la
# struttura a fasi per rimetterla la prossima volta che serve.
import xbmc, xbmcgui

SETTING_ID = 'fenlight.perf.instrumentation'
_STATE = []

def enabled():
	# L'interruttore si legge dalla PROPRIETA' DI FINESTRA, non dal database (lotto 161).
	# sync_settings, all'avvio del servizio, rispecchia OGNI impostazione in una proprieta' di
	# Window(10000) -- e' SettingsCache.set_memory_cache -- e get_setting stesso la consulta per
	# prima. Passare dal database significava importare caches.settings_cache e con lui
	# caches.base_cache e sqlite3: 93 ms sulla stick, piu' i 36 di datetime che sqlite3.dbapi2 si
	# tira dietro. Un prezzo pagato da CHIUNQUE importi paginator, perche' li' due costanti di
	# modulo (PG_DEBUG e PERF) chiamano questa funzione durante l'import. Nell'invocazione che il
	# lotto 160 lascia cadere -- 697 ms totali, 636 di import, per confrontare due stringhe -- era
	# la voce piu' cara, ed era l'INTERRUTTORE della strumentazione a pagarla: spegnerla costava
	# quanto tenerla accesa.
	# Una lettura di proprieta' e' la stessa traversata verso la GUI che il codice fa centinaia di
	# volte per costruzione (get_property in kodi_utils e' esattamente questa riga).
	if _STATE: return _STATE[0]
	try:
		raw = xbmcgui.Window(10000).getProperty(SETTING_ID)
		if raw: value = raw == 'true'
		else:
			# Rispecchiamento non ancora avvenuto (avvio molto precoce, prima che il servizio abbia
			# chiamato sync_settings): si paga il database una volta e si ricade nel caso di prima.
			from caches.settings_cache import get_setting
			value = get_setting(SETTING_ID, 'true') == 'true'
	except:
		# Se le impostazioni non sono leggibili (avvio molto precoce, database in creazione) si
		# resta accesi: una riga di log in piu' non fa danno, una misura persa si.
		value = True
	_STATE.append(value)
	return value

def log(heading, message):
	if not enabled(): return
	try: xbmc.log('###%s###: %s' % (heading, message), 1)
	except: pass

# --------------------------------------------------------------------------------------------
# Memoria. System.FreeMemory e' l'unico numero di memoria che Kodi espone a Python senza permessi
# di sistema, e sull'Android non rootato della stick e' anche l'unico ottenibile: /proc/meminfo
# e' leggibile ma riporta la memoria della MACCHINA, non quella concessa al processo, e dumpsys
# richiede adb. Torna una stringa tipo '123MB'.
# ATTENZIONE all'interpretazione: e' memoria libera di SISTEMA. Android la tiene deliberatamente
# bassa (la RAM inutilizzata e' RAM sprecata), quindi il valore assoluto dice poco. Quello che dice
# molto e' la DERIVATA: se scende monotonicamente durante una sessione e non risale mai, qualcosa
# non viene rilasciato.
def free_memory_mb():
	try:
		raw = xbmc.getInfoLabel('System.FreeMemory') or ''
		digits = ''.join(c for c in raw if c.isdigit())
		return int(digits) if digits else -1
	except: return -1

def memory_suffix():
	# Coda da appendere a una riga esistente. Vuota quando la strumentazione e' spenta o il numero
	# non e' leggibile, cosi' il chiamante non deve mettere condizioni attorno.
	if not enabled(): return ''
	free = free_memory_mb()
	return '' if free < 0 else ' | memoria libera %s MB' % free

# --------------------------------------------------------------------------------------------
# LOTTO 246 -- DOVE VA LA CPU, per thread. E' la misura che mancava a tutte le altre.
#
# Il commento di PerfSampler dice che su questo Android non rootato carico e temperatura sono
# negati all'app, e resta vero: /proc/loadavg e le zone termiche appartengono ad altri. Ma
# /proc/self -- il PROPRIO processo -- e' sempre leggibile, anche da untrusted_app, e Kodi e' UN
# processo solo: la GUI, il player, i JobWorker e tutti i sotto-interpreti Python stanno li' dentro.
# Quindi il censimento per thread non ha bisogno di permessi che non abbiamo.
#
# LA DOMANDA CHE DEVE CHIUDERE. `_log_invocation_cpu` in kodi_utils sa dire che il thread ha ATTESO
# invece di macinare, e lo dice da dieci lotti; non ha mai potuto dire ASPETTANDO CHI. L'11/09 la
# stessa build di lista e' passata da 1052 a 5642 ms di parete con la cpu propria quasi ferma
# (510 -> 863 ms), e due sonde su cinque sono state buttate perche' la quota era scesa al 36% e al
# 54% con UN SOLO interprete Python vivo -- cioe' la contesa non veniva da noi, e il log taceva.
#
# NON DECIDE NIENTE. Si stampa e basta, come `_avvallamento` del 245.
CLOCK_TICK = [0.0]

def _tick():
	if not CLOCK_TICK[0]:
		try:
			import os
			CLOCK_TICK[0] = float(os.sysconf('SC_CLK_TCK')) or 100.0
		except: CLOCK_TICK[0] = 100.0
	return CLOCK_TICK[0]

def _cpu_di(percorso):
	"""(nome, secondi totali, stato, secondi in spazio UTENTE) da /proc/<pid>/stat, o None.

	LOTTO 248 -- UTENTE E SISTEMA SEPARATI, e li stiamo gia' leggendo entrambi per sommarli. Il
	thread principale di Kodi tiene l'80% di un core sulla Home e il 24% col video a schermo intero:
	e' la skin che disegna, non un lavoro di fondo. Ma "disegnare" puo' voler dire due cose molto
	diverse -- calcolare in spazio utente (condizioni di visibilita', layout, animazioni) oppure
	chiamate di sistema (invio alla GPU, lettura di texture dalla flash) -- e il rimedio cambia.

	LOTTO 247 -- LO STATO ERA GIA' LI' E NON LO GUARDAVA NESSUNO. E' il campo subito dopo il nome,
	cioe' uno di quelli che si saltavano per arrivare a utime: 'R' vuol dire pronto o in esecuzione,
	'S' addormentato, 'D' bloccato su I/O. Contare gli 'R' e' l'unica misura che distingue una
	macchina SATURA da una macchina CONTESA, e le due vogliono rimedi opposti.

	IL NOME PUO' CONTENERE SPAZI E PARENTESI -- '(Chrome_IOThread)', e su Kodi i thread Java hanno
	nomi con punti. Si taglia sull'ULTIMA parentesi chiusa, che e' l'unico modo corretto di leggere
	questo file: splittando sugli spazi si sbaglierebbe il campo su qualunque thread dal nome
	composto, cioe' proprio su quelli interessanti.
	"""
	try:
		with open(percorso, 'rb') as _f: _riga = _f.read().decode('utf-8', 'replace')
		_testa, _, _coda = _riga.rpartition(')')
		_nome = _testa.partition('(')[2]
		_campi = _coda.split()
		# Dopo la parentesi il primo campo e' lo stato (campo 3): utime e' il 14, stime il 15.
		_u, _s = int(_campi[11]), int(_campi[12])
		return _nome, (_u + _s) / _tick(), _campi[0], _u / _tick()
	except: return None


# LOTTO 248 -- `conta_pronti` E' STATA TOLTA, e vale la pena dire perche'.
#
# Il 247 l'aveva scritta per campionare i pronti PIU' SPESSO del censimento. Ma leggeva gli stessi
# cinquanta file, quindi costava esattamente quanto lui: 53 ms di mediana e fino a 1875 ms, misurati
# l'11/09. Chiamata a ogni giro da 2 s ha prodotto da sola i tredici ritardi del ciclo che poi
# denunciava -- lo strumento accusava la macchina del proprio peso. `censimento_cpu` il conto dei
# pronti lo restituisce gia', nello stesso passaggio e senza costo aggiuntivo: due funzioni per lo
# stesso numero allo stesso prezzo sono un invito a rifare l'errore.

def fps():
	"""I fotogrammi al secondo che Kodi sta disegnando, o None.

	LOTTO 248 -- LA PROVA DIRETTA SULLA SKIN. Il thread principale tiene l'80% di un core sulla Home
	e il 24% col video a schermo intero: e' la GUI che disegna, non un lavoro di fondo. Se i
	fotogrammi sono sessanta mentre nessuno tocca niente, quell'80% e' rendering continuo e il
	rimedio sta nella skin -- animazioni sempre vive, regioni sporche che coprono tutto lo schermo.
	Se invece i fotogrammi sono pochi e la cpu resta alta, il tempo se ne va altrove.
	"""
	try:
		_v = xbmc.getInfoLabel('System.FPS') or ''
		return float(_v.replace(',', '.')) if _v else None
	except: return None


def censimento_cpu(radice='/proc/self'):
	"""(secondi cpu del processo, {tid: (nome, secondi, stato)}, quanti thread, quanti pronti) -- o None.

	LOTTO 247 -- il conto dei pronti torna DA QUI e non da una seconda passata: gli stati li stiamo
	gia' leggendo, e ripetere cinquanta aperture di file per un numero che abbiamo in mano sarebbe
	pagare due volte -- ed e' anche il motivo per cui una funzione a parte per i soli pronti non
	esiste piu': costava lo stesso e serviva a rifare lo stesso errore (lotto 248).

	Il totale del processo si legge da <radice>/stat e NON e' la somma dei thread vivi: comprende
	anche quelli gia' morti. La differenza fra i due e' il tempo speso da thread nati e finiti
	dentro la finestra, e si dichiara invece di sparire -- vedi `divario_cpu`.

	`radice` e' un parametro e non una costante perche' senza di lui questa funzione si puo' provare
	solo sulla macchina che si sta misurando: con un albero finto le prove girano anche sul Mac, che
	/proc non ce l'ha.
	"""
	try:
		import os
		_p = _cpu_di(os.path.join(radice, 'stat'))  # (nome, secondi, stato)
		if _p is None: return None
		# Il thread PRINCIPALE e' quello il cui tid coincide col pid del processo: e' il capo del
		# gruppo di thread, e su Kodi e' quello che avvia l'applicazione e gira il ciclo GUI.
		# Saperlo qui evita di doverlo indovinare dal log ogni volta.
		_main = str(os.getpid())
		_per_thread, _pronti = {}, 0
		_task = os.path.join(radice, 'task')
		for _tid in os.listdir(_task):
			_v = _cpu_di(os.path.join(_task, _tid, 'stat'))
			if _v is None: continue
			_per_thread[_tid] = _v
			if _v[2] == 'R': _pronti += 1
		return _p[1], _per_thread, len(_per_thread), _pronti, _main
	except: return None

def divario_cpu(prima, dopo, parete, pronti=None, fps=None, quanti=6, minimo_ms=20.0, tid_per_nome=3):
	"""(riga di riepilogo, riga dei colpevoli) fra due censimenti. ('', '') se non si puo' dire.

	Si aggrega PER NOME e non per tid: dodici JobWorker da 40 ms sono un fatto solo, e dodici righe
	da leggere sarebbero rumore. Il conteggio resta accanto al nome.

	LOTTO 247 -- E ACCANTO AL NOME CI VANNO I TID, che e' cio' che mancava per chiudere
	l'identificazione. Su questa build Kodi non imposta il `comm` dei propri thread e su Linux un
	thread EREDITA il nome da chi lo crea: `JobWorker`, `VideoPlayer`, `FileCache`,
	`LanguageInvoker` -- che Kodi stampa nel proprio log -- nel kernel finiscono tutti sotto il nome
	del creatore. Il 11/09 il censimento ha trovato la famiglia colpevole (`Thread-3`, presente in
	TUTTI e tredici i ritardi del ciclo, fino al 207% di un core) e non ha potuto nominarne i membri.

	Il tid invece e' univoco E GIA' STAMPATO DA KODI: ogni riga del suo log porta `T:<tid>` nel
	prefisso. Con i tid qui dentro il confronto diventa meccanico -- si cerca il numero nel log e si
	vede che cosa quel thread stava facendo.

	Si stampano solo i primi `tid_per_nome` di ciascuna famiglia, i piu' pesanti: elencarne diciassette
	renderebbe la riga illeggibile, e i primi tre bastano a dire da dove viene la famiglia.
	"""
	try:
		if not prima or not dopo or not parete or parete <= 0: return '', ''
		_p_tot, _p_th = prima[0], prima[1]
		_d_tot, _d_th, _n = dopo[0], dopo[1], dopo[2]
		_per_nome = {}
		# LOTTO 249 -- IL PRIMO CONSUMATORE, non il capofila del processo.
		#
		# Il lotto 248 prendeva per "principale" il thread con tid == getpid(). Su Linux e' il
		# capofila del gruppo, e li' la scelta sarebbe giusta. SU ANDROID NO: Kodi e' una
		# NativeActivity, il capofila e' il thread Java dell'Activity -- `comm` = org.xbmc.kodi --
		# e il ciclo applicativo in C++ gira in un thread DIVERSO, creato da quello. Misura del
		# log delle 19:33 dell'11/09: il capofila (15996) stava al 3%, e il thread applicativo
		# (16014, quello che scrive `Starting Kodi`, `HandleKey`, `Loading skin file`) all'85%.
		# La riga con utente/sistema -- l'unica che distingue il calcolo della skin dalle chiamate
		# di sistema del disegno -- descriveva quindi il thread sbagliato, al 3% di un core.
		#
		# Qui non si indovina piu' chi conta: si riporta CHI HA CONSUMATO DI PIU'. E' la definizione
		# stessa di "il thread che interessa", non dipende dalla piattaforma, e sopravvive a un
		# cambio di build. `censimento_cpu` continua a restituire il capofila in coda alla tupla:
		# non e' inutile, e' il dato che ha permesso di scoprire questa differenza.
		_capo = None
		for _tid, _v in _d_th.items():
			_nome, _sec = _v[0], _v[1]
			_before = _p_th.get(_tid)
			# Un thread assente dal primo censimento e' nato dentro la finestra: tutto il suo tempo
			# e' stato speso qui, quindi il riferimento e' zero e non si salta.
			_stesso = _before and _before[0] == _nome
			_delta = _sec - (_before[1] if _stesso else 0.0)
			if _delta <= 0: continue
			_e = _per_nome.setdefault(_nome, [0.0, 0, []])
			_e[0] += _delta; _e[1] += 1; _e[2].append((_delta, _tid))
			# Il primo consumatore si tiene da parte, con utente e sistema separati: merita una
			# riga sua invece di stare annegato dentro una famiglia da diciassette omonimi.
			if len(_v) > 3 and (_capo is None or _delta > _capo[2]):
				_du = _v[3] - (_before[3] if (_stesso and len(_before) > 3) else 0.0)
				_capo = (_tid, _nome, _delta, max(_du, 0.0))
		_tot = _d_tot - _p_tot
		_somma = sum(_v[0] for _v in _per_nome.values())
		# `pronti` arriva dal CHIAMANTE e non dal censimento, ed e' voluto: e' una misura
		# istantanea, va campionata a ogni giro del servizio (2 s) e non una volta ogni quindici,
		# se no non vedrebbe proprio le raffiche che deve smascherare.
		_pronti = ' | %s' % pronti if pronti else ''
		_riepilogo = ('%.1f s di finestra | processo %.0f%% (%.0f ms) | %d thread%s'
					  % (parete, _tot / parete * 100, _tot * 1000, _n, _pronti))
		_ordinati = sorted(_per_nome.items(), key=lambda kv: -kv[1][0])[:quanti]
		_pezzi = []
		for _nome, (_s, _c, _tidi) in _ordinati:
			if _s * 1000 < minimo_ms: continue
			_top = sorted(_tidi, reverse=True)[:tid_per_nome]
			_elenco = ' '.join('%s:%.0f' % (_t, _d * 1000) for _d, _t in _top)
			if _c > len(_top): _elenco += ' +%d' % (_c - len(_top))
			_pezzi.append('%s%s %.0f%% (%.0f ms) [%s]'
						  % (_nome, ' x%d' % _c if _c > 1 else '', _s / parete * 100, _s * 1000, _elenco))
		if _capo:
			_t, _nm, _d, _u = _capo
			_riepilogo += (' | capo %s %s al %.0f%% (utente %.0f%% / sistema %.0f%%)'
						   % (_t, _nm, _d / parete * 100,
							  _u / parete * 100, (_d - _u) / parete * 100))
			# Il costo PER FOTOGRAMMA, che e' la forma in cui la domanda ha una risposta netta: il
			# bilancio a 60 fotogrammi al secondo e' 16,7 ms, e sopra quella soglia la finestra non
			# puo' arrivare a 60 per costruzione, qualunque cosa stia facendo. Serve la frequenza
			# misurata e non quella nominale, se no si dividerebbe per un numero mai raggiunto.
			if fps:
				try:
					_fotogrammi = float(fps) * parete
					if _fotogrammi >= 1:
						_riepilogo += ' | %.1f ms di cpu per fotogramma' % (_d * 1000 / _fotogrammi)
				except Exception: pass
		# Thread nati E morti dentro la finestra: il processo li ha pagati, il censimento finale non
		# li vede. Dichiararlo e' cio' che impedisce di leggere l'elenco come se fosse completo.
		_perso = _tot - _somma
		if _perso * 1000 >= minimo_ms:
			_pezzi.append('non attribuito %.0f%% (%.0f ms, thread gia\' finiti)'
						  % (_perso / parete * 100, _perso * 1000))
		return _riepilogo, ' | '.join(_pezzi) or 'nessun thread sopra %.0f ms' % minimo_ms
	except: return '', ''
