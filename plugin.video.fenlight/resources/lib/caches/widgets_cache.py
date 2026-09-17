# -*- coding: utf-8 -*-
"""LOTTO 311 -- lo strato dati delle liste dei widget (fase 2 del blocco B).

  liste      una lista: impronta del contenuto, parametri per rifarla, passi coperti, stato della sorgente
  elementi   i suoi id, un id per riga, in ordine di CONSEGNA -- si aggiunge solo in coda
  pronti     titoli preparati e non ancora consegnati (lotto 332)
  attese     titoli senza verdetto sul doppiaggio, o la cui scheda non e' arrivata
  consegne   quale lista sta in quale posizione
  meta       sessione corrente e precedente e versione dello schema

DAL LOTTO 332 QUI SI DECIDE COSA MOSTRARE, e lo decide uno solo: il preparatore del servizio
(modules/preparatore.py), che e' l'unico a scrivere. Le costruzioni leggono (`pronta`) e spediscono.

L'ordine degli elementi e' quello deciso il 16/09: la parte gia' consegnata non si tocca, e ogni
aggiunta -- passo nuovo, titolo con verdetto arrivato tardi, titolo aggiunto a una lista -- va in coda,
in ordine cronologico. Nessuna eccezione deve uscire da questo modulo verso una costruzione.
"""
from time import time as _time
from modules import kodi_utils

SESSIONE_PROP = 'fenlight.widgets.sessione'
# Il formato del messaggio e la tabella dei tipi stanno in paginator, con chi li prepara: una build
# non deve importare QUESTO modulo per spedire (lotto 316). Qui si legge, non si ridefinisce.
from modules.paginator import TIPI, TIPI_NOME, MESSAGGIO_DB as MESSAGGIO

# LOTTO 332 -- le PRAGMA valgono per CONNESSIONE, e le connessioni sono per thread (base_cache). Qui c'era
# un segnalibro unico per processo: il secondo thread del servizio apriva la sua connessione senza chiavi
# esterne, e le cancellazioni a cascata di `liste` non avrebbero toccato niente. Latente finche' nel
# servizio scriveva un thread solo.
from threading import local as _local
_pronte = _local()

def _log(msg):
	kodi_utils.logger('Fen Light', 'WIDGETS_DB %s' % msg)

def _con():
	from caches.base_cache import connect_database
	dbcon = connect_database('widgets_db')
	if getattr(_pronte, 'con', None) is not dbcon:
		# Le chiavi esterne in SQLite vanno accese per connessione, e servono per la cancellazione a
		# cascata: la pulizia di una sessione e' una DELETE sola su `liste`.
		dbcon.execute('PRAGMA foreign_keys = ON')
		# LOTTO 314 -- niente fsync per QUESTO file. widgets.db si rifa' sempre leggendo le sorgenti:
		# non c'e' niente da proteggere da un'interruzione di corrente, e un fsync su questa flash
		# costa decine di millisecondi. Gli altri database di Fen Light restano su synchronous NORMAL.
		dbcon.execute('PRAGMA synchronous = OFF')
		# I checkpoint del giornale li decide lo scrittore (il servizio), non li subisce una build.
		dbcon.execute('PRAGMA wal_autocheckpoint = 0')
		_pronte.con = dbcon
	return dbcon

def _con_tabelle():
	"""Connessione con le tabelle garantite.

	Le tabelle le crea il servizio (`make_databases`), ma una build puo' arrivare prima: all'avvio i
	widget partono mentre i servizi stanno ancora salendo. Invece di pagare nove CREATE IF NOT EXISTS
	a ogni invocazione, si prova a lavorare e si creano solo se il database dice che non ci sono.
	"""
	dbcon = _con()
	try:
		dbcon.execute('SELECT 1 FROM liste LIMIT 1').fetchone()
	except Exception:
		from caches.base_cache import WIDGETS_CREATE
		for comando in WIDGETS_CREATE: dbcon.execute(comando)
		_log('tabelle create')
	return dbcon

def _verifica_schema(dbcon):
	"""Lato SERVIZIO: se lo schema su disco non e' quello del codice, si butta e si rifa'.

	Questo database e' una cache -- ogni riga si puo' ricostruire leggendo le sorgenti -- quindi non si
	migra: migrare costa codice che vive per sempre per un dato che si riottiene gratis. Senza il
	controllo, invece, un cambio di colonne resterebbe SILENZIOSO: le scritture fallirebbero a ogni
	consegna (e le liste smetterebbero di crescere senza che nessuno lo dica) oppure si leggerebbe una
	colonna che nel frattempo vuol dire un'altra cosa.

	Lo fa il servizio, all'avvio, prima di qualunque build: e' l'unico scrittore, quindi qui non c'e'
	corsa. Una build che arrivasse prima leggerebbe lo schema vecchio e ne ricaverebbe una lista vuota,
	che e' il caso gia' previsto (si riparte da pagina 1).
	"""
	from caches.base_cache import WIDGETS_SCHEMA, WIDGETS_CREATE
	if leggi_meta('schema', dbcon) == WIDGETS_SCHEMA: return
	vecchio = leggi_meta('schema', dbcon)
	dbcon.execute('BEGIN IMMEDIATE')
	try:
		for tabella in ('consegne', 'attese', 'pronti', 'elementi', 'liste', 'meta'):
			dbcon.execute('DROP TABLE IF EXISTS %s' % tabella)
		for comando in WIDGETS_CREATE: dbcon.execute(comando)
		scrivi_meta('schema', WIDGETS_SCHEMA, dbcon)
		dbcon.execute('COMMIT')
	except Exception:
		dbcon.execute('ROLLBACK'); raise
	_log('schema %s -> %s: database rifatto' % (vecchio or '(nessuno)', WIDGETS_SCHEMA))

def sessione():
	return kodi_utils.get_property(SESSIONE_PROP) or ''

def avvia_sessione():
	"""Chiamata dal servizio all'avvio. Torna l'id della sessione nuova, o '' se qualcosa va storto.

	Tre cose, in quest'ordine: si pubblica subito l'id (le build lo leggono da una proprieta', senza
	aprire niente), si sposta la sessione corrente a precedente, si butta tutto il resto. Le consegne
	sono per definizione della sessione in corso -- i contenitori si ricostruiscono da capo -- quindi
	si svuotano e non hanno bisogno di portarsi dietro una colonna con la sessione.
	"""
	try:
		# Microsecondi, non millisecondi: l'id deve essere UNICO, e due aperture ravvicinate nello stesso
		# millisecondo darebbero lo stesso id -- con quello, la pulizia terrebbe per sempre una sessione
		# che crede corrente. Trovato dalla prova del lotto 311.
		nuova = '%x' % int(_time() * 1000000)
		kodi_utils.set_property(SESSIONE_PROP, nuova)
		dbcon = _con_tabelle()
		_verifica_schema(dbcon)
		precedente = leggi_meta('sessione_corrente')
		dbcon.execute('BEGIN IMMEDIATE')
		try:
			scrivi_meta('sessione_precedente', precedente, dbcon)
			scrivi_meta('sessione_corrente', nuova, dbcon)
			dbcon.execute('DELETE FROM consegne')
			tenute = [i for i in (nuova, precedente) if i]
			dbcon.execute('DELETE FROM liste WHERE sessione NOT IN (%s)' % ','.join('?' for _ in tenute), tenute)
			dbcon.execute('COMMIT')
		except Exception:
			dbcon.execute('ROLLBACK'); raise
		rimaste = dbcon.execute('SELECT count(*) FROM liste').fetchone()[0]
		_log('sessione %s (precedente %s), liste tenute %s' % (nuova, precedente or '-', rimaste))
		return nuova
	except Exception as e:
		_log('avvio sessione fallito: %r' % e)
		return ''

def leggi_meta(chiave, dbcon=None):
	try:
		riga = (dbcon or _con_tabelle()).execute('SELECT valore FROM meta WHERE chiave = ?', (chiave,)).fetchone()
		return riga[0] if riga else ''
	except Exception: return ''

def scrivi_meta(chiave, valore, dbcon=None):
	(dbcon or _con_tabelle()).execute('INSERT OR REPLACE INTO meta VALUES (?, ?)', (chiave, valore or ''))

def _lista_id(dbcon, chiave, parametri, azione, sessione_id):
	riga = dbcon.execute('SELECT id, sessione FROM liste WHERE chiave = ?', (chiave,)).fetchone()
	if riga is None:
		dbcon.execute('INSERT INTO liste (chiave, parametri, azione, sessione, aggiornata) VALUES (?, ?, ?, ?, ?)',
					(chiave, parametri or '', azione or '', sessione_id, _time()))
		return dbcon.execute('SELECT id FROM liste WHERE chiave = ?', (chiave,)).fetchone()[0], True
	lista_id, sua_sessione = riga
	if sua_sessione != sessione_id:
		# LOTTO 327 -- una lista della sessione precedente si RIFA', non si adotta.
		# Qui la si adottava com'era, "opzione (b) dell'avvio", ma a meta': lista() -- che e' chi la
		# legge -- risponde solo per la sessione corrente, quindi la PRIMA costruzione della sessione
		# ripartiva da pagina 1, e solo la sua registrazione adottava la riga vecchia. Il risultato,
		# misurato sulla stick il 16/09 alle 16:37: riga Horror 53 elementi al primo giro, 562 al
		# secondo (tutta la lista della sessione delle 14), con il puntatore di pagina riscritto a 4
		# dalla prima costruzione -- e il passo successivo ha riletto 32 pagine di TMDb trovando zero
		# titoli nuovi, perche' erano tutti gia' li'. All'utente: "ha caricato tantissimi elementi
		# all'inizio", poster che non facevano in tempo a caricarsi.
		# Servire la sessione precedente resta la specifica (opzione b), ma si fa INTERA nella fase 5,
		# con chi la riconvalida. Fino ad allora vale cio' che lista() gia' dichiara: si riparte.
		dbcon.execute('DELETE FROM elementi WHERE lista_id = ?', (lista_id,))
		dbcon.execute('DELETE FROM attese WHERE lista_id = ?', (lista_id,))
		dbcon.execute('DELETE FROM pronti WHERE lista_id = ?', (lista_id,))
		dbcon.execute('UPDATE liste SET sessione = ?, azione = ?, elementi = 0, ultima_pagina = 0, fine = 0, '
					'ricarica = \'\', passi = 0, mista = 0 WHERE id = ?', (sessione_id, azione or '', lista_id))
	return lista_id, False

def registra(chiave, parametri, azione, posizione, voci):
	"""Una riga NON preparata dal servizio ('continua a guardare') ha consegnato questa lista. Torna l'id o None.

	voci : [(tipo, tmdb)] nell'ordine consegnato. E' la lista INTERA -- quelle righe si ricostruiscono
	       sempre per intero -- quindi SOSTITUISCE la precedente: un titolo uscito dalla riga esce anche
	       da qui, e la domanda "chi contiene questo titolo" resta vera.
	LOTTO 332 -- le righe paginate non passano piu' di qui: i loro elementi li scrive il preparatore.
	"""
	if not chiave: return None
	sessione_id = sessione()
	if not sessione_id:
		# Il servizio non ha ancora aperto la sessione: senza di lei non si sa a quale sessione
		# appartiene questa lista, e una riga senza sessione non si potrebbe mai buttare.
		_log('registra saltata: nessuna sessione (posizione %s)' % posizione)
		return None
	try:
		def lavoro(dbcon):
			lista_id = _lista_id(dbcon, chiave, parametri, azione, sessione_id)[0]
			dbcon.execute('DELETE FROM elementi WHERE lista_id = ?', (lista_id,))
			visti, righe = set(), []
			for tipo, tmdb in voci:
				if (tipo, tmdb) in visti: continue
				visti.add((tipo, tmdb))
				righe.append((tipo, tmdb))
			_accoda(dbcon, 'elementi', lista_id, righe, passo=1)
			_conta_elementi(dbcon, lista_id)
			if posizione:
				dbcon.execute('INSERT OR REPLACE INTO consegne (posizione, lista_id, aggiornata) VALUES (?, ?, ?)',
							(posizione, lista_id, _time()))
			return lista_id
		return _transazione(lavoro)
	except Exception as e:
		_log('registra fallita (posizione %s): %r' % (posizione, e))
		return None

# ---------------------------------------------------------------------------------------------------
# LOTTO 314 -- UNO SCRITTORE SOLO.
#
# Le build non scrivono piu': spediscono al servizio cosa hanno consegnato. Tre ragioni, tutte
# misurate sulla stick il 16/09:
#   - ogni build e' un interprete nuovo, quindi una connessione nuova: apertura del file, commit e
#     soprattutto il checkpoint del giornale WAL, che SQLite fa quando l'ultima connessione si chiude.
#     Con 78 build in dodici minuti erano 78 aperture e altrettanti checkpoint, per 30-50 ms a build;
#   - tre build insieme si contendevano la scrittura ('database is locked', 01:22:54);
#   - un solo scrittore rende l'ordine delle scritture una proprieta' del codice, non della fortuna.
# Se una notifica si perde, il database resta indietro di una consegna e la build successiva lo
# riallinea: degrada, non si rompe.
def ricevi(dati):
	"""Lato SERVIZIO: scrive cio' che una build ha spedito. Torna quante consegne ha registrato.

	LOTTO 332 -- due forme. Una riga PREPARATA dal servizio (film, serie, liste Trakt e MDbList) spedisce
	solo "questa lista sta in questa posizione": i suoi elementi li ha scritti il servizio stesso. Le
	altre ('continua a guardare') spediscono ancora cio' che hanno consegnato.
	"""
	try:
		import json
		carico = json.loads(dati) if isinstance(dati, str) else dati
		if isinstance(carico, dict): carico = [carico]
	except Exception as e:
		_log('messaggio illeggibile: %r' % e); return 0
	fatte = 0
	for voce in carico or []:
		try:
			if voce.get('preparata'):
				esito = registra_consegna(voce.get('chiave'), voce.get('parametri'), voce.get('azione'), voce.get('posizione'))
				if esito: fatte += 1
				continue
			esito = registra(voce.get('chiave'), voce.get('parametri'), voce.get('azione'), voce.get('posizione'),
							[(v[0], v[1]) for v in voce.get('voci') or []])
			if esito: fatte += 1
			_log('consegna %s voci=%s' % (voce.get('posizione') or '-', len(voce.get('voci') or [])))
		except Exception as e:
			_log('consegna non registrata: %r' % e)
	return fatte

def checkpoint():
	"""Lato SERVIZIO: porta il giornale dentro il database. Da chiamare quando non c'e' altro da fare.

	L'autocheckpoint e' spento (vedi _con): senza questa chiamata il giornale crescerebbe per tutta la
	sessione, e il conto lo pagherebbe chi lo chiude -- cioe' di nuovo una build.
	"""
	try: _con_tabelle().execute('PRAGMA wal_checkpoint(PASSIVE)')
	except Exception as e: _log('checkpoint fallito: %r' % e)

# ---------------------------------------------------------------------------------------------------
# LOTTO 332 -- LA COSTRUZIONE LEGGE, IL SERVIZIO PREPARA.
#
# Una riga paginata non legge piu' nessuna sorgente e non va in rete: legge da qui (`pronta`) cio' che il
# servizio ha gia' deciso. Quando non basta lo chiede al servizio e aspetta (paginator.passo_pronto).
# Il servizio e' l'unico che scrive queste righe, da un thread solo (modules/preparatore.py).

from collections import namedtuple as _namedtuple
# passi   i passi COPERTI: `elementi` contiene tutto cio' che quei passi dovevano consegnare
# voci    [(tipo, tmdb)] nell'ordine di consegna
# fine    la sorgente ha dichiarato la fine
# altri   ci sono titoli preparati e non ancora consegnati
# ricarica il nonce dell'ultima ricomposizione eseguita
# mista   lista Trakt con stagioni o episodi: il database non li sa identificare, la costruisce la build
Pronta = _namedtuple('Pronta', 'passi voci fine altri ricarica mista')

def pronta(chiave):
	"""Lato BUILD -- lo stato di una lista preparata, per la sessione corrente. None se non c'e'.

	Una connessione e una transazione per tutte le domande: e' una lettura sulla strada dell'utente.
	Solo la sessione corrente: una lista della sessione precedente si rifa' (fase 5 per servirla).
	"""
	if not chiave: return None
	try:
		sessione_id = sessione()
		if not sessione_id: return None
		dbcon = _con_tabelle()
		riga = dbcon.execute('SELECT id, passi, fine, ricarica, mista FROM liste WHERE chiave = ? AND sessione = ?',
							(chiave, sessione_id)).fetchone()
		if not riga: return None
		lista_id, passi, fine, ricarica, mista = riga
		voci = dbcon.execute('SELECT tipo, tmdb FROM elementi WHERE lista_id = ? ORDER BY ordine', (lista_id,)).fetchall()
		altri = dbcon.execute('SELECT 1 FROM pronti WHERE lista_id = ? LIMIT 1', (lista_id,)).fetchone() is not None
		return Pronta(int(passi or 0), voci, bool(fine), altri, ricarica or '', bool(mista))
	except Exception as e:
		_log('lettura lista pronta fallita (%s): %r' % (chiave, e)); return None

# --- lato SERVIZIO -----------------------------------------------------------------------------------

# Lo stato di lavoro di una lista, come lo vede il preparatore.
#   pagina   l'ultima pagina (o fetta) della sorgente gia' letta
#   elementi / pronti  liste ordinate di (tipo, tmdb);  attese  insieme di (tipo, tmdb)
Stato = _namedtuple('Stato', 'id passi pagina fine ricarica elementi pronti attese')

def _transazione(lavoro):
	dbcon = _con_tabelle()
	dbcon.execute('BEGIN IMMEDIATE')
	try:
		esito = lavoro(dbcon)
		dbcon.execute('COMMIT')
		return esito
	except Exception:
		dbcon.execute('ROLLBACK'); raise

def apri_lista(chiave, parametri, azione):
	"""La lista di questa chiave nella sessione corrente, creata se manca. Torna l'id, o None."""
	sessione_id = sessione()
	if not chiave or not sessione_id: return None
	return _transazione(lambda dbcon: _lista_id(dbcon, chiave, parametri, azione, sessione_id)[0])

def stato_lista(lista_id):
	dbcon = _con_tabelle()
	passi, pagina, fine, ricarica = dbcon.execute('SELECT passi, ultima_pagina, fine, ricarica FROM liste WHERE id = ?',
												(lista_id,)).fetchone()
	elementi = [tuple(r) for r in dbcon.execute('SELECT tipo, tmdb FROM elementi WHERE lista_id = ? ORDER BY ordine', (lista_id,))]
	pronti = [tuple(r) for r in dbcon.execute('SELECT tipo, tmdb FROM pronti WHERE lista_id = ? ORDER BY ordine', (lista_id,))]
	attese = set(tuple(r) for r in dbcon.execute('SELECT tipo, tmdb FROM attese WHERE lista_id = ?', (lista_id,)))
	return Stato(lista_id, int(passi or 0), int(pagina or 0), bool(fine), ricarica or '', elementi, pronti, attese)

def _accoda(dbcon, tabella, lista_id, coppie, passo=None):
	ordine = dbcon.execute('SELECT coalesce(max(ordine), 0) FROM %s WHERE lista_id = ?' % tabella, (lista_id,)).fetchone()[0]
	righe = []
	for tipo, tmdb in coppie:
		ordine += 1
		righe.append((lista_id, ordine, tipo, tmdb) if passo is None else (lista_id, ordine, tipo, tmdb, passo))
	if not righe: return
	if passo is None: dbcon.executemany('INSERT INTO %s (lista_id, ordine, tipo, tmdb) VALUES (?, ?, ?, ?)' % tabella, righe)
	else: dbcon.executemany('INSERT INTO %s (lista_id, ordine, tipo, tmdb, passo) VALUES (?, ?, ?, ?, ?)' % tabella, righe)

def _conta_elementi(dbcon, lista_id):
	dbcon.execute('UPDATE liste SET elementi = (SELECT count(*) FROM elementi WHERE lista_id = ?), aggiornata = ? WHERE id = ?',
				(lista_id, _time(), lista_id))

def salva_pagina(lista_id, pronti, attese, pagina, fine):
	"""Il frutto di una pagina letta: i preparati in coda, i senza verdetto in attesa, e il segno di lettura."""
	def lavoro(dbcon):
		_accoda(dbcon, 'pronti', lista_id, pronti)
		if attese:
			dbcon.executemany('INSERT OR IGNORE INTO attese (lista_id, tipo, tmdb) VALUES (?, ?, ?)',
							[(lista_id, t, i) for t, i in attese])
		dbcon.execute('UPDATE liste SET ultima_pagina = ?, fine = ? WHERE id = ?', (int(pagina), 1 if fine else 0, lista_id))
	_transazione(lavoro)

def assegna_passi(lista_id, fino_a, quanto):
	"""Porta la lista a `fino_a` passi coperti: ogni passo prende i primi `quanto` preparati. Torna gli assegnati.

	Il chiamante ha gia' preparato cio' che poteva. Se i preparati non bastano la sorgente e' finita, o il
	tetto di pagine e' stato raggiunto: il passo si copre con cio' che c'e', e il successivo riparte da li'.
	"""
	def lavoro(dbcon):
		passi = dbcon.execute('SELECT passi FROM liste WHERE id = ?', (lista_id,)).fetchone()[0] or 0
		assegnati = 0
		while passi < fino_a:
			passi += 1
			righe = dbcon.execute('SELECT ordine, tipo, tmdb FROM pronti WHERE lista_id = ? ORDER BY ordine LIMIT ?',
								(lista_id, quanto)).fetchall()
			if righe:
				dbcon.execute('DELETE FROM pronti WHERE lista_id = ? AND ordine <= ?', (lista_id, righe[-1][0]))
				_accoda(dbcon, 'elementi', lista_id, [(r[1], r[2]) for r in righe], passo=passi)
				assegnati += len(righe)
		dbcon.execute('UPDATE liste SET passi = ? WHERE id = ?', (passi, lista_id))
		_conta_elementi(dbcon, lista_id)
		return assegnati
	return _transazione(lavoro)

def accoda_elementi(lista_id, coppie):
	"""Titoli che entrano SUBITO nella lista, in coda: quelli nuovi di una ricomposizione, e i verdetti
	arrivati tardi su una lista finita. Prendono il passo corrente, cosi' si vedono gia' con quello."""
	if not coppie: return
	def lavoro(dbcon):
		passi = dbcon.execute('SELECT passi FROM liste WHERE id = ?', (lista_id,)).fetchone()[0] or 0
		_accoda(dbcon, 'elementi', lista_id, coppie, passo=max(1, passi))
		_conta_elementi(dbcon, lista_id)
	_transazione(lavoro)

def ricomponi_lista(lista_id, presenti, nonce):
	"""Via cio' che la sorgente non contiene piu', e il nonce di questa ricomposizione. Torna i tolti."""
	presenti = set(presenti)
	def lavoro(dbcon):
		tolti = 0
		for tabella in ('elementi', 'pronti', 'attese'):
			for tipo, tmdb in dbcon.execute('SELECT tipo, tmdb FROM %s WHERE lista_id = ?' % tabella, (lista_id,)).fetchall():
				if (tipo, tmdb) in presenti: continue
				dbcon.execute('DELETE FROM %s WHERE lista_id = ? AND tipo = ? AND tmdb = ?' % tabella, (lista_id, tipo, tmdb))
				if tabella == 'elementi': tolti += 1
		dbcon.execute('UPDATE liste SET ricarica = ? WHERE id = ?', (str(nonce or ''), lista_id))
		_conta_elementi(dbcon, lista_id)
		return tolti
	return _transazione(lavoro)

def esiti_attese(lista_id, promossi, bocciati, subito):
	"""I verdetti arrivati per chi aspettava. `subito`: la lista e' finita, i promossi entrano gia' in lista."""
	def lavoro(dbcon):
		for tipo, tmdb in list(promossi) + list(bocciati):
			dbcon.execute('DELETE FROM attese WHERE lista_id = ? AND tipo = ? AND tmdb = ?', (lista_id, tipo, tmdb))
		if subito:
			passi = dbcon.execute('SELECT passi FROM liste WHERE id = ?', (lista_id,)).fetchone()[0] or 0
			_accoda(dbcon, 'elementi', lista_id, promossi, passo=max(1, passi))
			_conta_elementi(dbcon, lista_id)
		else:
			_accoda(dbcon, 'pronti', lista_id, promossi)
	_transazione(lavoro)

def registra_consegna(chiave, parametri, azione, posizione):
	"""Una riga preparata e' stata consegnata in questa posizione. Torna l'id della lista, o None."""
	if not chiave or not posizione: return None
	sessione_id = sessione()
	if not sessione_id: return None
	try:
		def lavoro(dbcon):
			lista_id = _lista_id(dbcon, chiave, parametri, azione, sessione_id)[0]
			if azione: dbcon.execute('UPDATE liste SET azione = ? WHERE id = ?', (azione, lista_id))
			dbcon.execute('INSERT OR REPLACE INTO consegne (posizione, lista_id, aggiornata) VALUES (?, ?, ?)',
						(posizione, lista_id, _time()))
			return lista_id
		return _transazione(lavoro)
	except Exception as e:
		_log('consegna non registrata (%s): %r' % (posizione, e)); return None

def segna_mista(lista_id, mista):
	_transazione(lambda dbcon: dbcon.execute('UPDATE liste SET mista = ? WHERE id = ?', (1 if mista else 0, lista_id)))

def posizioni_di(lista_id):
	"""Le posizioni in cui questa lista e' stata consegnata nella sessione."""
	try: return [r[0] for r in _con_tabelle().execute('SELECT posizione FROM consegne WHERE lista_id = ?', (lista_id,))]
	except Exception as e:
		_log('posizioni della lista %s non lette: %r' % (lista_id, e)); return []

def liste_con_attese():
	"""Le liste della sessione che hanno titoli in attesa di verdetto."""
	try: return [r[0] for r in _con_tabelle().execute('SELECT DISTINCT a.lista_id FROM attese a JOIN liste l ON l.id = a.lista_id '
													'WHERE l.sessione = ?', (sessione(),))]
	except Exception: return []

def svuota_preparato():
	"""Il paese o la lingua sono cambiati: cio' che e' preparato e non consegnato non vale piu'."""
	def lavoro(dbcon):
		dbcon.execute('DELETE FROM pronti')
		dbcon.execute('DELETE FROM attese')
	_transazione(lavoro)

def posizioni_per_id(coppie):
	"""Le posizioni che DIPENDONO da uno di questi titoli. coppie: [(tipo, tmdb)].

	Dipendere vuol dire due cose, e la seconda ce l'ha insegnata la sessione in ombra del 16/09:
	  - la lista CONTIENE il titolo (`elementi`);
	  - la lista lo STA ASPETTANDO (`attese`): un titolo senza verdetto sul doppiaggio non e' ancora un
	    elemento, ma quando il verdetto arriva quella riga va ricostruita. Senza questa meta', alle
	    03:03 il database rispondeva "nessuna posizione" mentre il meccanismo vecchio ricaricava --
	    giustamente -- la riga della ricerca (due righe 'OMBRA ... solo_vero=[1105.502]').

	`tipo` None vuol dire "qualunque tipo": e' il caso della modalita' ombra, perche' chi chiede la
	ricarica oggi passa solo il numero. Dalla fase 5 il tipo arriva da chi scrive (sa benissimo se ha
	segnato un film o una serie) e la query smette di poter colpire il widget sbagliato."""
	if not coppie: return set()
	try:
		dbcon = _con_tabelle()
		fuori = set()
		# A blocchi: SQLite ha un tetto ai parametri di una query, e le ricariche di Trakt possono
		# portare centinaia di id.
		coppie = list(coppie)
		for inizio in range(0, len(coppie), 200):
			blocco = coppie[inizio:inizio + 200]
			condizioni = ' OR '.join('e.tmdb = ?' if t is None else '(e.tipo = ? AND e.tmdb = ?)' for t, _ in blocco)
			valori = [v for t, i in blocco for v in ((i,) if t is None else (t, i))]
			for tabella in ('elementi', 'attese'):
				righe = dbcon.execute('SELECT DISTINCT c.posizione FROM consegne c JOIN %s e ON e.lista_id = c.lista_id '
									'WHERE %s' % (tabella, condizioni), valori).fetchall()
				fuori.update(r[0] for r in righe)
		return fuori
	except Exception as e:
		_log('query posizioni fallita: %r' % e); return set()

def posizioni_per_azione(azioni):
	"""Le posizioni la cui lista e' di uno di questi tipi ('trakt_watchlist:movie', 'continue_watching').

	Il confronto e' per prefisso qualificato, la stessa regola di paginator._action_matches: chi chiede
	'trakt_watchlist' senza qualificatore prende film e serie.
	"""
	azioni = [str(a) for a in (azioni or ()) if a]
	if not azioni: return set()
	try:
		dbcon = _con_tabelle()
		righe = dbcon.execute('SELECT c.posizione, l.azione FROM consegne c JOIN liste l ON l.id = c.lista_id '
							'WHERE l.azione IS NOT NULL AND l.azione != ""').fetchall()
		fuori = set()
		for posizione, azione in righe:
			for voluta in azioni:
				if azione == voluta or azione.startswith(voluta + ':') or voluta.startswith(azione + ':'):
					fuori.add(posizione); break
		return fuori
	except Exception as e:
		_log('query azioni fallita: %r' % e); return set()

def ombra(coppie, azioni, colpite):
	"""MODALITA' OMBRA (fase 2): confronta la risposta del database con la ricarica vera.

	`colpite` sono le posizioni che il meccanismo di oggi ha davvero ricaricato. Qui non si ricarica
	niente: si scrive una riga di log con le due risposte e la differenza, e quella differenza e'
	l'unica cosa che ci interessa leggere nelle prossime sessioni.
	"""
	try:
		da_id = posizioni_per_id(coppie)
		da_azione = posizioni_per_azione(azioni)
		attese_db = da_id | da_azione
		colpite = set(colpite or ())
		solo_db = sorted(attese_db - colpite)
		solo_vero = sorted(colpite - attese_db)
		_log('OMBRA id=%s azioni=%s | db=%s vero=%s | solo_db=%s solo_vero=%s%s'
			% (len(coppie or ()), ','.join(azioni or ()) or '-', sorted(attese_db) or '-', sorted(colpite) or '-',
				solo_db or '-', solo_vero or '-', '' if (not solo_db and not solo_vero) else '  <-- DIFFERENZA'))
	except Exception as e:
		_log('ombra fallita: %r' % e)
