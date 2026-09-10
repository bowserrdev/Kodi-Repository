# -*- coding: utf-8 -*-
"""'Continua a guardare' torna in testa quando arriva un titolo nuovo -- e SOLO allora.

LA REGOLA, che e' dell'utente:

  arriva un titolo nuovo e la riga NON ha il fuoco  ->  la riga si riporta sul primo elemento, cosi'
                                                        il titolo nuovo si vede, e al rientro il fuoco
                                                        ci sta sopra a prescindere da dove fosse
  arriva un titolo nuovo e la riga HA il fuoco      ->  non si muove niente: chi sta scegliendo non si
                                                        strattona. Il debito resta e si salda quando
                                                        esce dalla riga.

PERCHE' SERVE. Le righe della skin sono <control type="fixedlist"> senza <focusposition>
(Includes_Lists.xml: List_Core, List_Landscape_Row), quindi la posizione di riposo dell'elemento a
fuoco e' il primo posto a sinistra e la riga si disegna a partire da li'. Quando un titolo entra in
testa, Kodi conserva l'ELEMENTO su cui eri, non la posizione: quello scivola a destra di un posto e
il titolo nuovo finisce fuori campo a sinistra. A schermo non cambia niente -- si intravede una
striscia di poster e basta -- ed e' esattamente il difetto che l'utente ha fotografato il 09/09.

PERCHE' IL CONFRONTO CON LA TESTA ATTESA NON E' UN ORNAMENTO. E' l'unica cosa che distingue due
situazioni identiche a vedersi: con il debito aperto e il cursore su 1 puo' voler dire

    'la lista nuova non e' ancora arrivata, il contenitore mostra ancora quella vecchia'   -> aspetta
    'la lista nuova e' arrivata e il primo elemento e' gia' quello giusto'                 -> fatto

e chiedere solo al cursore non permette di sceglierne una. Il difetto del 09/09 e' nato proprio li':
la coda del lotto 138 veniva svuotata al primo giro in cui il cursore segnava 1, che sulla stick
capitava PRIMA che Kodi scambiasse la lista (set_head pubblica prima di end_directory, e il
contenitore si aggiorna un fotogramma dopo). Consumato il debito contro la lista vecchia, quando poi
il cursore scivolava su 2 non c'era piu' nessuno a riportarlo indietro. Nel log delle 21:23 non c'e'
nemmeno una riga di quel meccanismo: era gia' finito.

Il confronto e' fra stringhe uguali byte per byte, verificato e non supposto: Kodi conserva il path
del ListItem verbatim. Log del 09/09, stesso film, due strade diverse:

    21:15:35.900  CPythonInvoker(19):  ?mode=playback.media&media_type=movie&tmdb_id=1315303
    21:23:08.490  set_head ... first_url=plugin://plugin.video.fenlight/?mode=playback.media&media_type=movie&tmdb_id=1315303

Quindi o il confronto e' sempre vero o e' sempre falso: non c'e' nessuna finestra temporale in cui
puo' andare in un modo o nell'altro, che e' la condizione richiesta -- comportamento sempre identico.

PERCHE' NON STA IN paginator.py. 'Continua a guardare' non e' un widget paginato: non chiama
get_pages, non ha pagine, nel log dichiara hasmore=False. Questa regola vale per quella riga sola.
Stava dentro il paginatore per un incidente di percorso -- set_head passava di li' -- e da quella
convivenza sono arrivati un controllo sull'azione, una proprieta' in piu' e una coda con due
committenti che non si somigliano. La coda fenlight.pg.rehead resta al suo unico proprietario
legittimo, reconcile_position, con la sua semantica (e il gate della skin dei lotti 165/167) intatta.

PERCHE' IL LAVORO LO FA IL SERVIZIO E NON IL PLUGIN. Quando la build finisce, Kodi non ha ancora
popolato il contenitore, quindi un comando lanciato dal plugin cadrebbe sulla lista vecchia; e
leggere Container(N).CurrentItem o muovere il cursore dal thread di un'invocazione vuol dire chiamate
grafiche da dove il lotto 111 le ha vietate. Il watcher gira gia' a 0,3 s, ha davanti i cancelli
giusti (riproduzione, dialogo modale) e vede il fuoco: il consumo sta li', in service.py.
"""

# La testa dell'ULTIMA costruzione: il path del primo elemento. La scrive il costruttore a ogni giro,
# e il confronto con quella precedente e' cio' che risponde a 'e' arrivato qualcosa di nuovo?'.
# E' anche il BERSAGLIO che il servizio aspetta di vedere in cima prima di dichiarare chiuso il
# debito: un dato solo, uno scrittore solo. Se una build successiva cambia ancora la testa, il
# bersaglio si aggiorna da se' e il servizio insegue la piu' recente senza una riga in piu'.
HEAD_PROP = 'fenlight.cw.head.%s'
# Le righe che devono ancora essere riportate in testa: UNA proprieta' con dentro le chiavi separate
# da virgola. Come per la coda del lotto 138, e per la stessa ragione: il watcher deve poter chiedere
# 'c'e' lavoro?' a ogni giro con UNA lettura servita dalla memoria, e nel 99,9% dei giri la risposta
# e' una stringa vuota.
PENDING_PROP = 'fenlight.cw.pending'

# Quanto si aspetta prima di ripetere un Control.Move che non ha morso. Lo scorrimento della riga
# dura 400 ms (List_Core: <scrolltime tween="quadratic">400</scrolltime>), quindi a 1,5 s un comando
# arrivato ha gia' finito di muoversi da un pezzo: se il cursore e' ancora oltre il primo, quel
# comando non e' arrivato. E' anche cio' che rende impossibile l'avvolgimento -- due Control.Move in
# volo insieme, con il secondo che parte da un cursore gia' a 1, manderebbero la riga IN FONDO
# (CGUIFixedListContainer::MoveUp avvolge quando e' gia' in testa).
RIPETI = 1.5
# Quante volte lo si ripete prima di rinunciare. Serve perche' executebuiltin non risponde niente:
# l'unico modo di sapere se un comando ha morso e' rileggere l'effetto al giro dopo (lotto 137 bis,
# dove a mancare era una parola nel builtin e il difetto e' stato muto per un lotto intero).
TENTATIVI = 3

def note_head(key, items):
	"""Il costruttore di 'continua a guardare' dichiara la sua testa. Apre un debito se e' cambiata.

	Alla PRIMA costruzione non apre niente: non c'e' una testa precedente da confrontare, e un
	contenitore appena nato parte gia' dal primo elemento.

	Ricostruzioni con la stessa testa non aprono niente e non chiudono niente -- e questo copre da
	solo il doppione misurato il 09/09, dove un singolo film in pausa faceva ricostruire la riga due
	volte (21:23:08 e 21:23:11, stessa firma): la seconda passa di qui e non tocca il debito aperto
	dalla prima.
	"""
	if not key: return
	url = _first_url(items)
	if not url: return
	from modules.kodi_utils import get_property, set_property
	precedente = get_property(HEAD_PROP % key)
	set_property(HEAD_PROP % key, url)
	if not precedente or precedente == url: return
	_open(key)

def head_of(key):
	"""Il bersaglio: quale path deve trovarsi in cima a questa riga."""
	from modules.kodi_utils import get_property
	return get_property(HEAD_PROP % key)

def pending():
	"""Le righe con un debito aperto, in ordine di arrivo."""
	from modules.kodi_utils import get_property
	return [k for k in (get_property(PENDING_PROP) or '').split(',') if k]

def _open(key):
	"""Apre il debito. Idempotente.

	Read-modify-write su una proprieta' condivisa fra il processo del plugin e quello del servizio,
	lo stesso schema del lotto 3: in contesa si puo' perdere una scrittura. Il danno peggiore e' una
	riga che resta dov'e' fino al titolo nuovo successivo -- cioe' il comportamento di prima -- e
	succede una volta per costruzione di questo solo widget, non per elemento. Non vale un lucchetto.
	"""
	from modules.kodi_utils import set_property
	aperti = pending()
	if key in aperti: return
	aperti.append(key)
	set_property(PENDING_PROP, ','.join(aperti))

def done(key):
	"""Chiude il debito. La chiama il servizio DOPO aver visto la riga in testa e ferma."""
	from modules.kodi_utils import set_property, clear_property
	rimasti = [k for k in pending() if k != key]
	if rimasti: set_property(PENDING_PROP, ','.join(rimasti))
	else: clear_property(PENDING_PROP)

def hold(fuoco_prima, fuoco_ora):
	"""La riga va lasciata stare a questo giro? E' il cancello del fuoco, e vale la pena isolarlo.

	La domanda NON e' 'ha il fuoco adesso' ma 'ce l'aveva gia' al giro scorso', e la differenza e' un
	caso reale: chi rientra in Home da un hub trova il fuoco atterrato dove l'aveva lasciato, che puo'
	essere proprio questa riga -- e con 'adesso' non vedrebbe mai il titolo nuovo, cioe' il difetto da
	cui e' partito tutto. Con 'al giro scorso':

	  stai dentro la riga da prima             il fuoco c'era anche al giro scorso   -> si aspetta
	  ci arrivi ora da un'altra riga           al giro scorso non c'era              -> si riporta in testa
	  la finestra non era nemmeno a schermo    per definizione non aveva il fuoco    -> si agisce

	'fuoco_prima' e' None solo alla prima occhiata a un debito appena nato: li' non c'e' un giro
	scorso e vale l'adesso, cioe' un titolo che arriva mentre stai nella riga non ti sposta niente.
	"""
	return fuoco_ora if fuoco_prima is None else fuoco_prima

def step(attesa, vista, current, scrolling, mosso_da, tentativi, adesso):
	"""Cosa fare, a questo giro, per una riga con un debito aperto. Funzione PURA.

	Sta qui e non dentro il ciclo del servizio per la ragione del lotto 139: un ramo che nessuno puo'
	provare e' un ramo che prima o poi sbaglia in silenzio -- e questa famiglia di correzioni ha gia'
	sbagliato tre volte cosi'. Le quattro risposte sono tutto cio' che il chiamante puo' fare.

	  'attendi'  non fare niente
	  'muovi'    ordina il Control.Move e segna il momento
	  'fatto'    la riga e' in testa e ferma: chiudi il debito
	  'mollo'    il comando non morde: chiudi il debito e scrivilo nel log

	Il cancello del fuoco NON sta qui: e' il chiamante che non arriva nemmeno a chiamare questa
	funzione mentre la riga ha il fuoco. Qui dentro si decide solo l'inseguimento del bersaglio.

	'vista' vuota vuol dire contenitore non leggibile -- finestra non a schermo, o build in corso --
	e ricade da sola nel primo ramo: il debito resta aperto e si salda quando quella finestra torna.
	"""
	if not attesa or vista != attesa: return 'attendi'   # la lista nuova non e' ancora a schermo
	if current < 1: return 'attendi'                     # contenitore non ancora leggibile
	if current == 1: return 'attendi' if scrolling else 'fatto'
	if mosso_da is None: return 'muovi'
	if adesso - mosso_da < RIPETI: return 'attendi'      # lo scorrimento dura 400 ms
	return 'muovi' if tentativi < TENTATIVI else 'mollo'

def _first_url(items):
	"""Path del primo elemento della lista consegnata ad add_items.

	Stessa forma che legge paginator._item_url: la tupla (url, listitem, isfolder), oppure la forma
	con ordinamento ((url, li, isf), posizione). 'Continua a guardare' usa la prima, ma il codice
	regge tutte e due perche' costa due righe e la forma e' cambiata gia' una volta.
	"""
	if not items: return None
	primo = items[0]
	if isinstance(primo, (list, tuple)) and primo and isinstance(primo[0], (list, tuple)):
		primo = primo[0]
	try: return primo[0]
	except: return None
