# -*- coding: utf-8 -*-
# MISURE DELLE RIPRODUZIONI -- ingresso del wizard della banda (lotto 201).
#
# PERCHE' ESISTE. Le misure della connessione esistono SOLO durante una riproduzione: il wizard non
# puo' misurare su richiesta, perche' per farlo dovrebbe o far aspettare l'utente -- ed e' la sonda
# buttata nei lotti 191-195 -- o indovinare. Quindi questo non e' un comodo, e' l'organo di senso del
# wizard, e resta anche dopo la prima taratura: la portata misurata va da 13,5 a 21,4 Mbit/s e il cdn
# e' gia' cambiato una volta questo mese. Un numero fisso invecchia.
#
# FINESTRA SCORREVOLE, NON ARCHIVIO. Una misura di tre mesi fa, con un altro cdn e un altro wi-fi,
# non descrive piu' niente e sporcherebbe il percentile. Si tengono le ultime MAX_RIGHE.
#
# NULL SIGNIFICA "NON MISURATO". Ogni colonna puo' essere NULL, e il wizard deve distinguere "non
# misurato" da "misurato zero": e' la distinzione che nei lotti 191-198 e' costata due sonde e una
# raccomandazione sbagliata. Chi legge queste righe non deve mai trattare un None come uno zero.
from caches.base_cache import connect_database

MAX_RIGHE = 50

COLONNE = ('quando', 'cdn', 'dimensione', 'durata', 'bitrate', 'salti', 'portata_prima',
		   'portata_dopo',
		   # Lotto 212: quanto e' solida la misura -- campioni del tratto piu' lungo dentro la banda
		   # utile del buffer, e punti percentuali coperti (negativi se la cache calava). Una coppia
		   # per misura (lotto 215): la misura DOPO il salto e' spesso la migliore delle due, perche'
		   # il buffer riparte da vuoto e ha tutto lo spazio davanti per salire.
		   'portata_campioni_prima', 'portata_punti_prima',
		   'portata_campioni_dopo', 'portata_punti_dopo',
		   # Lotto 217/218: quanti campioni del tratto vincente erano sotto il pavimento. E' un
		   # INVARIANTE e deve valere zero -- vedi portata_contaminata() in fondo a questo file.
		   'portata_secchi_prima', 'portata_secchi_dopo',
		   # Lotto 219: la durata della finestra in secondi. Non si ricava dai campioni (il passo
		   # non e' costante) ed e' cio' che distingue una raffica di apertura da una misura
		   # sostenuta. Vedi sostenuta() in fondo al file.
		   'portata_secondi_prima', 'portata_secondi_dopo',
		   # Lotto 221: quanto la finestra e' monotona. Una misura presa su un'andata-e-ritorno
		   # descrive due regimi opposti e non ne descrive nessuno.
		   'portata_direzione_prima', 'portata_direzione_dopo',
		   'cache_media_prima', 'cache_max_prima', 'cache_media_dopo',
		   'cache_max_dopo', 'secondi_a_secco', 'campioni',
		   # Lotto 202: la forma del flusso, non la sua velocita'. Una riga con esito non NULL e' una
		   # riproduzione che NON e' avvenuta -- va letta come un guasto, non come una misura di banda,
		   # e il wizard deve escluderla dal percentile.
		   'larghezza', 'altezza', 'codec', 'esito',
		   # Identita' della sorgente. 'nome' non dice niente sulla banda ed e' li' per un'altra
		   # domanda: quale pacco o quale gruppo di rilascio ha funzionato, per riscegliere lo stesso.
		   # 'dimensione_dichiarata' si legge solo insieme a 'provider' e 'pacchetto': vedi base_cache.
		   'nome', 'dimensione_dichiarata', 'provider', 'pacchetto',
		   # Lotto 222: la sonda della linea presa PRIMA di questa riproduzione. Vedi base_cache per
		   # il senso di ciascuna, e bersaglio() qui sotto per 'link'.
		   'sonda_mbps', 'sonda_lorda', 'sonda_secondi', 'sonda_ttfb', 'sonda_byte',
		   'sonda_offset', 'sonda_quota', 'sonda_cpu', 'sonda_eta', 'sonda_cdn',
		   # Lotto 240: la forma della curva. `sonda_mbps` resta il numero che ha DECISO; questi
		   # dicono come e' stato ottenuto, e sono cio' che mancava per verificare una taratura.
		   # Lotto 245: `sonda_buco` -> `sonda_avvallamento`, ed e' un'altra grandezza -- vedi
		   # sonda_linea._avvallamento e il rifacimento in base_cache.
		   'sonda_media', 'sonda_coda', 'sonda_centro', 'sonda_salita', 'sonda_avvallamento',
		   'sonda_campioni', 'sonda_fonte',
		   # Lotto 244: lo stato del link wi-fi al momento della riproduzione. Non viene dalla
		   # sonda e si scrive anche quando la sonda non c'e' stata -- vedi player._campi_sonda.
		   'rete_qualita', 'rete_segnale', 'link',
		   # Lotto 255: il segnale DURANTE la finestra di regime, campionato al passo della curva.
		   # Va letto insieme a `sonda_salita`: sono due prima/dopo sullo stesso intervallo, ed e'
		   # la coincidenza fra i due che questa raccolta deve accertare. Vedi base_cache.
		   'sonda_rssi_inizio', 'sonda_rssi_fine', 'sonda_rssi_min',
		   # Lotto 258: gli indizi sulla CREDIBILITA' della misura, non sul suo valore. Nessuno di
		   # questi decide niente: sono la raccolta che deve dire se il caso del 12/09 -- una sonda
		   # a 17,32 Mbit/s su una linea che dava 55 e 62, con ttfb tripla, ripiego del lettore e
		   # dimensione dichiarata sbagliata di 13 volte, tutti e tre insieme -- e' un caso isolato
		   # o una firma. Vedi base_cache per il perche' di ciascuna.
		   'sonda_lettore', 'sonda_ripiego', 'sonda_stato', 'sonda_dim_attesa', 'sonda_dim_vera',
		   'sonda_letti_secondi')


def registra(**campi):
	"""Scrive una riga e pota la finestra. Non solleva mai: una misura persa non deve poter
	disturbare la chiusura di una riproduzione."""
	try:
		valori = [campi.get(_c) for _c in COLONNE]
		dbcon = connect_database('playback_db')
		dbcon.execute('INSERT INTO playback_stats (%s) VALUES (%s)'
					  % (', '.join(COLONNE), ', '.join('?' * len(COLONNE))), valori)
		# La potatura sta qui e non in una pulizia periodica: e' una riga di SQL su una tabella da
		# cinquanta righe, e cosi' non esiste un percorso in cui la tabella cresce senza limite.
		dbcon.execute('DELETE FROM playback_stats WHERE id NOT IN '
					  '(SELECT id FROM playback_stats ORDER BY id DESC LIMIT ?)', (MAX_RIGHE,))
		dbcon.commit()
		return True
	except: return False


def recenti(limite=MAX_RIGHE):
	"""Le ultime righe, dalla piu' recente. Lista di dizionari, valori mancanti a None."""
	try:
		dbcon = connect_database('playback_db')
		righe = dbcon.execute('SELECT %s FROM playback_stats ORDER BY id DESC LIMIT ?'
							  % ', '.join(COLONNE), (limite,)).fetchall()
		return [dict(zip(COLONNE, _r)) for _r in righe]
	except: return []


def quante():
	try:
		dbcon = connect_database('playback_db')
		return dbcon.execute('SELECT COUNT(*) FROM playback_stats').fetchone()[0]
	except: return 0


def svuota():
	try:
		dbcon = connect_database('playback_db')
		dbcon.execute('DELETE FROM playback_stats')
		dbcon.commit()
		return True
	except: return False


# ---- LISTA NERA -------------------------------------------------------------------------------
# Rete di sicurezza per cio' che la sonda dell'intestazione NON riesce a leggere: contenitori che non
# parsiamo, moov in coda al file, guasti che non c'entrano con la dimensione del fotogramma. Vive in
# una tabella a parte perche' playback_stats si pota a 50 righe (vedi base_cache).
#
# La chiave e' provider|nome e non il link: il link risolto cambia a ogni tentativo -- lo stesso file
# e' arrivato come .../dld/f6445631-... e poi .../dld/f2f629a4-... -- mentre il nome no.

def chiave(item):
	try:
		if not item: return None
		nome = item.get('name') or item.get('display_name')
		if not nome: return None
		return '%s|%s' % (item.get('scrape_provider') or '?', nome)
	except: return None


def boccia(ch, nome=None, provider=None, motivo=None):
	"""Segna una sorgente come non riproducibile. Va chiamata PRIMA di fermare il player: se il
	guasto e' quello dell'08/09, dopo il player non c'e' piu' nessun processo che possa scrivere."""
	try:
		if not ch: return False
		from time import time as _adesso
		dbcon = connect_database('playback_db')
		vecchie = dbcon.execute('SELECT volte FROM sorgenti_bocciate WHERE chiave = ?', (ch,)).fetchone()
		dbcon.execute('INSERT OR REPLACE INTO sorgenti_bocciate (chiave, nome, provider, quando, motivo, volte) '
					  'VALUES (?, ?, ?, ?, ?, ?)',
					  (ch, nome, provider, int(_adesso()), motivo, (vecchie[0] if vecchie else 0) + 1))
		dbcon.commit()
		return True
	except: return False


def bocciata(ch):
	"""Il motivo se e' in lista nera, None altrimenti. Nel dubbio None: un errore di lettura del
	database non deve togliere all'utente una sorgente buona."""
	try:
		if not ch: return None
		riga = connect_database('playback_db').execute(
			'SELECT motivo FROM sorgenti_bocciate WHERE chiave = ?', (ch,)).fetchone()
		return (riga[0] or 'sconosciuto') if riga else None
	except: return None


def bocciate():
	try:
		righe = connect_database('playback_db').execute(
			'SELECT chiave, nome, provider, quando, motivo, volte FROM sorgenti_bocciate ORDER BY quando DESC').fetchall()
		return [dict(zip(('chiave','nome','provider','quando','motivo','volte'), _r)) for _r in righe]
	except: return []


def riabilita(ch=None):
	"""Senza argomenti svuota la lista. Serve all'utente, e serve a noi quando una bocciatura si
	rivela sbagliata: una lista nera senza modo di tornare indietro e' una trappola."""
	try:
		dbcon = connect_database('playback_db')
		if ch: dbcon.execute('DELETE FROM sorgenti_bocciate WHERE chiave = ?', (ch,))
		else: dbcon.execute('DELETE FROM sorgenti_bocciate')
		dbcon.commit()
		return True
	except: return False


# LOTTO 217 -- LA REGOLA, IN CODICE E NON IN PROSA.
#
# La capacita' si misura come `bitrate + variazione del buffer nel tempo`, e la formula vale finche'
# il buffer e' libero di muoversi. Ha DUE bordi dove non lo e': sopra il tetto Kodi si strozza da
# solo, a ZERO il buffer non puo' scendere oltre e smette di registrare il deficit.
#
# Il lotto 217 chiude il secondo bordo dentro il campionatore: i campioni a zero escono dalla banda
# esattamente come quelli sopra il tetto, quindi `portata_prima` e `portata_dopo` arrivano qui gia'
# pulite. NON serve piu' una regola che separi le misure buone dalle contaminate, e la quota su
# `secondi_a_secco` che avevo proposto era la forma sbagliata: sui dati veri avrebbe bocciato Devil
# Wears Prada (26 campioni a zero su 52, ma erano il punto da cui la risalita partiva) insieme a
# The Mandalorian, che invece era davvero fame.
#
# `portata_secchi_prima`/`_dopo` restano come INVARIANTE, non come dato da interpretare: e' il numero di campioni a
# zero rimasti dentro il tratto vincente e **deve valere zero**. Se un giorno non lo fosse, la
# guardia sul pavimento si e' rotta e le portate di quel periodo non sono misure.


# LOTTO 242 -- LA CAPACITA' CHE QUESTA LINEA HA MOSTRATO DI RECENTE, per quando non c'e' una
# misura di adesso.
#
# PERCHE' SERVE, e il numero e' 94. L'11/09 alle 04:30 la sonda e' stata scartata (uno stallo di
# 2,5 s all'inizio aveva lasciato solo 2,9 s di regime, sotto SECONDI_MINIMI) e il filtro ha
# ripiegato sui **50 Mbit/s** dell'impostazione, su una linea che ne faceva 12-20. Ha fatto passare
# un file da 12,7 Mbit/s e la riproduzione ha fatto **94 secondi a secco**.
#
# In archivio, in quel momento, c'erano quattro portate misurate da venti minuti prima: 13,8 / 7,6 /
# 6,0 / 8,8. La loro mediana e' 8,2, cioe' `line_speed` 6,6 -- e quel file sarebbe stato rifiutato.
# Il dato per non sbagliare c'era gia', scritto da noi, e nessuno lo leggeva.
#
# E DEMOLISCE UNA PREMESSA scritta dentro le guardie della sonda: "scartare costa un ripiego
# sull'impostazione dell'utente -- un numero conservativo e noto". Su questo dispositivo
# l'impostazione non e' conservativa, e' quattro volte la linea. Tutta l'asimmetria con cui
# QUOTA_MINIMA e SECONDI_MINIMI sono state tarate ("si scarta con generosita'") poggiava su
# quell'assunto. Con questo ripiego l'assunto torna vero, e quelle guardie tornano difendibili.
#
# LA MEDIANA, non un percentile basso: `line_speed = capacita / MARGINE` il suo margine ce l'ha
# gia'. Applicarne un secondo qui lo conterebbe due volte -- e' l'errore che il lotto 208 ha tolto
# dal filtro della dimensione.
#
# LOTTO 244 -- LE SONDE, NON LE PORTATE, e la correzione arriva da una misura che prima non c'era.
#
# Il 242 usava `misure_di_capacita`, cioe' le portate, perche' era gia' l'unica definizione di
# "misura utilizzabile" e di `sonda_mbps` non c'erano ancora abbastanza righe. Adesso ce ne sono, e
# dicono che le due cose non sono paragonabili. Nella sessione dell'11/09 alle 15:xx, stessa linea,
# stessi minuti:
#
#     tre sonde su TRE NODI DIVERSI   46,31  46,37  46,47    -> escursione 0,3%
#     le portate della stessa sessione 24,5 ... 46,3         -> escursione 89%
#
# PERCHE' LA PORTATA NON E' UNA CAPACITA'. Si misura come `bitrate + crescita del buffer`, e Kodi
# riempie a tutta velocita' solo finche' ha fame. Con `cache_media` al 96-99% su TUTTE le righe, su
# un film leggero non chiede mai tutta la linea: misura il FILM, non la connessione. Il confronto
# con la sonda, presa nello stesso minuto, lo mostra senza ambiguita':
#
#     b/s 0,31 -> portata/sonda 1,06     b/s 0,22 -> 0,91
#     b/s 0,26 -> 1,00                   b/s 0,12 -> 0,57
#                                        b/s 0,11 -> 0,53
#
# Sui dati di quella finestra la mediana delle portate dava 42,6 su una linea da 46,4 (-8%), quella
# delle sonde 46,31 (-0%). E l'errore peggiora con una serata di film leggeri, perche' ogni film
# leggero aggiunge un pavimento travestito da misura.
#
# Le portate RESTANO in archivio e `misure_di_capacita` resta dov'e': servono a tarare MARGINE, che
# e' una domanda diversa -- li' interessa proprio cio' che il player ha ottenuto, non cio' che la
# linea poteva dare.
FINESTRA_RIPIEGO = 6 * 3600


def capacita_recente(finestra=FINESTRA_RIPIEGO, adesso=None):
	"""Mbit/s: la mediana delle SONDE dell'ultima `finestra`. None se non ce ne sono.

	Si escludono le righe con `esito`, come fa `misure_di_capacita`: una riproduzione che non e'
	avvenuta non descrive una linea. La sonda pero' e' presa PRIMA della riproduzione, quindi resta
	valida anche quando il film e' poi fallito per altro -- ma su questo preferisco la prudenza
	all'astuzia, e la regola uguale per tutti.

	La finestra e' un GIUDIZIO e non una misura: il 10/09 la linea stava a 44 Mbit/s alle 23:51 e a
	10 alle 03:20, tre ore e mezza dopo, quindi sei ore e' gia' larga -- ma stringerla vuol dire
	ricadere sull'impostazione, che e' il caso che questo codice esiste per evitare.

	LOTTO 249 -- UNA SONDA, UN VOTO. Il difetto era segnalato da due lotti e non corretto.
	Una misura presa una volta sola puo' finire su PIU' righe: la bacheca la riusa entro
	ETA_BACHECA, e ogni riproduzione che ne nasce se la porta in archivio. Nell'archivio dell'11/09
	diciassette righe con sonda portavano TREDICI sonde distinte -- una contata tre volte, due
	contate due volte. La mediana pesava quella sonda per tre, cioe' dava piu' voce a chi aveva
	fatto piu' tentativi a ridosso della stessa misura, che e' l'esatto contrario di quello che
	una mediana serve a fare.

	L'identita' e' il valore stesso: `sonda_mbps` nasce da un conteggio di byte diviso per un
	perf_counter: due misure indipendenti non producono lo stesso float a quindici cifre. Non
	serve una chiave nuova in tabella, e soprattutto non serve riscrivere lo schema.
	"""
	try:
		from time import time as _ora
		_adesso = adesso if adesso is not None else _ora()
		_v = sorted({_r['sonda_mbps'] for _r in recenti()
					 if (_r.get('quando') or 0) >= _adesso - finestra
					 and not _r.get('esito') and _r.get('sonda_mbps')})
		if not _v: return None
		_n = len(_v)
		return _v[_n // 2] if _n % 2 else (_v[_n // 2 - 1] + _v[_n // 2]) / 2.0
	except: return None


def portata_contaminata(riga):
	"""True se il tratto vincente contiene campioni sotto il pavimento: non deve mai accadere.

	NULL non e' contaminazione nota: e' assenza del dato.
	"""
	return any((riga.get(_c) or 0) > 0 for _c in ('portata_secchi_prima', 'portata_secchi_dopo'))


def misure_di_capacita(righe):
	"""Le portate utilizzabili dal wizard. Lista di float.

	Due filtri, e sono i due che contano. `esito` non NULL vuol dire che la riproduzione non e'
	avvenuta o si e' guastata (lotto 202): quelle righe non misurano una linea, misurano un guasto.
	`portata_contaminata` non dovrebbe mai essere vera, ed e' li' perche' una guardia che nessuno
	controlla non e' una guardia.
	"""
	_fuori = []
	for _r in righe:
		if _r.get('esito') or portata_contaminata(_r): continue
		for _c in ('portata_prima', 'portata_dopo'):
			if _r.get(_c) is not None: _fuori.append(_r[_c])
	return _fuori


def margine(riga):
	"""portata / bitrate: quante volte la linea copriva cio' che il film chiedeva. None se manca.

	E' il numero su cui il wizard decide, piu' della portata da sola. Una portata di 43 Mbit/s non
	dice niente finche' non si sa che il film ne chiedeva 43: The Mandalorian (10/09) ha margine
	1,00 ed e' rimasto senza buffer per 109 secondi. E' quella riga -- non le dieci facili a
	margine 3 -- a dire quanto margine serve davvero.
	"""
	_b = riga.get('bitrate')
	if not _b: return None
	_p = [riga.get(_c) for _c in ('portata_prima', 'portata_dopo')]
	_p = [_x for _x in _p if _x is not None]
	return (min(_p) / _b) if _p else None


# LOTTO 219 -- QUANTO E' SOSTENUTA UNA MISURA.
#
# Su quattro riproduzioni indipendenti la portata scende al crescere della finestra:
#
#     4,4 s -> 47,5 Mbit/s | 15,8 s -> 46,2 | 48,3 s -> 43,2 | 117 s -> 44,3
#
# Non e' rumore, e' il modo in cui la misura viene presa. La finestra corta e' quasi sempre il
# riempimento iniziale, cioe' il momento in cui il collegamento si apre e il cdn manda una raffica;
# la finestra lunga e' la linea che regge davvero. Michael (11/09) ha misurato 46,2 Mbit/s su 15,8
# secondi e poi e' rimasto a secco per 51 secondi con un film da 35,95: un wizard che avesse preso
# quel 46,2 avrebbe concluso che la linea copre 36 Mbit/s con margine, e si sbagliava.
SECONDI_SOSTENUTA = 30.0


def sostenuta(riga, fase='_prima'):
	"""(portata, secondi) se la misura di quella fase e' sostenuta; (None, secondi) altrimenti.

	Non si BUTTA una finestra corta -- dice comunque che in quel momento la linea andava cosi' -- ma
	non va mediata insieme a una lunga. Il wizard deve poter chiedere le une o le altre.
	"""
	_sf = '_prima' if fase == '_prima' else '_dopo'
	_sec = riga.get('portata_secondi' + _sf)
	_p = riga.get('portata' + _sf)
	if _p is None or _sec is None: return None, _sec
	return (_p if _sec >= SECONDI_SOSTENUTA else None), _sec


def misure_sostenute(righe):
	"""Le portate misurate su finestre lunghe: quelle su cui si puo' fondare una soglia."""
	_fuori = []
	for _r in righe:
		if _r.get('esito') or portata_contaminata(_r): continue
		for _f in ('_prima', '_dopo'):
			_p, _ = sostenuta(_r, _f)
			if _p is not None: _fuori.append(_p)
	return _fuori


# LOTTO 228 -- DUE RIGHE POSSONO PORTARE UNA SOLA SONDA, e per il wizard non sono due punti.
#
# La sonda vive nel servizio e misura ogni RIMISURA secondi; una riproduzione che parte prima della
# sonda successiva scrive in archivio la misura precedente. E' giusto -- una misura di sette minuti
# fa descrive ancora la linea -- ma se due riproduzioni consecutive prendono la STESSA sonda, il
# rapporto bitrate/sonda che ne esce ha lo stesso denominatore, e contarli come due campioni
# indipendenti gonfia la fiducia in un numero che e' stato misurato una volta.
#
# Il 10/09 e' successo al primo giro: le righe 2 e 3 dell'archivio hanno sonda_mbps, sonda_cpu,
# sonda_byte e sonda_offset identici, e solo sonda_eta diverso (-1 e 406 s).


def impronta_sonda(riga):
	"""Cio' che identifica UNA sonda. None se la riga non ne ha una.

	Non si usa `sonda_mbps` da solo: due sonde diverse possono dare lo stesso numero su una linea
	stabile -- ed e' proprio quello che vogliamo che accada. L'impronta sono i byte letti, la cpu
	spesa e l'offset, che due letture distinte non hanno mai uguali.
	"""
	if not riga.get('sonda_mbps'): return None
	return (riga.get('sonda_byte'), riga.get('sonda_cpu'), riga.get('sonda_offset'))


def coppie_indipendenti(righe):
	"""Una riga per sonda: la piu' vicina nel tempo alla misura, cioe' con `sonda_eta` minore.

	Si tiene la piu' fresca e non la prima incontrata perche' e' quella in cui la linea aveva meno
	tempo per cambiare fra la misura e la riproduzione che la verifica.
	"""
	_per_sonda = {}
	for _r in righe:
		_i = impronta_sonda(_r)
		if _i is None: continue
		_eta = _r.get('sonda_eta')
		_eta = 10 ** 9 if _eta is None else abs(_eta)
		_gia = _per_sonda.get(_i)
		if _gia is None or _eta < _gia[0]: _per_sonda[_i] = (_eta, _r)
	return [_v[1] for _v in _per_sonda.values()]


def rapporto_sonda(riga):
	"""bitrate / sonda_mbps: quanta parte della banda misurata il film si e' preso. None se manca.

	E' il numero su cui si tara il margine. Ordinato su venti-trenta righe indipendenti, separa le
	riproduzioni sane dalle sofferenti: quel confine e' 1/MARGINE, e da li' in poi la logica e'
	`line_speed = sonda / MARGINE` senza piu' bisogno di questo archivio.
	"""
	_b, _s = riga.get('bitrate'), riga.get('sonda_mbps')
	return (_b / _s) if (_b and _s) else None

# LOTTO 259 -- IL MARGINE SI MISURA, NON SI SCEGLIE.
#
# `rapporto_sonda` qui sopra dice da tre lotti che il confine da cercare e' 1/MARGINE. Adesso
# l'archivio ha abbastanza righe per cercarlo davvero, e la domanda giusta non e' "di quanto ha
# sbagliato la sonda" ma "a quale frazione della soglia i film cominciano a restare a secco":
# quella si legge su OGNI riga, anche su quelle senza `portata_prima` -- che al 13/09 sono 7 su 26,
# e comprendono le due riproduzioni peggiori mai registrate, il cui buffer non e' mai salito
# abbastanza da poter misurare una capacita'.
#
# Il margine che sarebbe servito a RIFIUTARE una riga e' `sonda_mbps / bitrate`: la soglia vale
# `sonda / margine`, quindi la riga viene esclusa quando `margine > sonda / bitrate`.
SECONDI_STALLO = 5.0


def ha_stallato(riga):
	"""Se quella riproduzione e' rimasta a secco davvero, non solo durante il riempimento iniziale.

	Cinque secondi separano le due popolazioni senza ambiguita' sui dati veri: l'avvio normale
	segna 0 o 1 s -- e' il buffer che si riempie prima del primo fotogramma -- mentre gli stalli
	misurati stanno a 6, 10, 27, 29, 31, 44, 44 e 175 s. Fra 1 e 6 non c'e' nessuna riga.
	"""
	try: return (riga.get('secondi_a_secco') or 0) > SECONDI_STALLO
	except: return False


def margini_necessari(righe):
	"""I margini che sarebbero serviti a rifiutare le riproduzioni finite a secco. Lista ordinata.

	L'unita' e' la RIPRODUZIONE e non la sonda, al contrario di `coppie_indipendenti`: li' si
	misurava una linea e la stessa misura contata due volte falsava la mediana, qui si conta un
	esito e due film diversi sono due prove diverse anche se la sonda era la stessa. Resta vero che
	due esiti nati dalla stessa misura ne condividono l'errore: e' il motivo per cui la soglia
	minima di righe piu' avanti non e' uno.

	Si escludono le righe con `esito`, come ovunque in questo file: una riproduzione che non e'
	avvenuta non ha un buffer da giudicare.
	"""
	_fuori = []
	for _r in righe or ():
		try:
			if _r.get('esito'): continue
			if not ha_stallato(_r): continue
			_b, _s = _r.get('bitrate'), _r.get('sonda_mbps')
			if not _b or not _s: continue
			_fuori.append(_s / _b)
		except: continue
	return sorted(_fuori)


def righe_giudicabili(righe):
	"""Quante righe possono dire qualcosa sul margine: hanno sonda, bitrate e non sono guasti."""
	_n = 0
	for _r in righe or ():
		try:
			if not _r.get('esito') and _r.get('bitrate') and _r.get('sonda_mbps'): _n += 1
		except: continue
	return _n

