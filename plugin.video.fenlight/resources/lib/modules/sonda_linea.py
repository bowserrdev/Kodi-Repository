# -*- coding: utf-8 -*-
# SONDA DELLA LINEA -- lotto 222. Fase 4.
#
# COSA MISURA, e in cosa differisce da tutto cio' che c'e' stato prima. Non misura il buffer di
# Kodi: misura la LINEA, con una richiesta nostra, su byte nostri, col nostro orologio. Nessuno dei
# due bordi che hanno tenuto occupati gli otto lotti da 214 a 221 -- sopra il tetto Kodi si strozza
# da solo, sotto il pavimento il buffer non puo' scendere -- perche' qui non c'e' nessun buffer.
#
# QUANDO PARTE (lotto 230, e le tre collocazioni precedenti erano tutte sbagliate). Subito dopo che
# TorBox ha detto quali sorgenti sono in cache, prima che il filtro della dimensione decida.
# L'utente aspetta qualche secondo in piu' e in cambio il filtro decide su un numero misurato adesso.
# QUANTO in piu' non e' piu' un numero fisso dal lotto 243: si legge finche' la finestra di regime e'
# lunga SECONDI_REGIME, il che su linea sana fa i soliti sei secondi e su linea che stalla allunga --
# perche' una misura che non c'e' costa all'utente molto piu' dei secondi che si risparmiano.
#
# Perche' proprio li', e non altrove:
#   - lotto 222, DENTRO lo scraping: gli scraper sono richieste piccole e la banda e' ferma, vero;
#     ma la CPU no. Tutti i sotto-interpreti di Kodi si dividono un core, e la sonda prendeva il 10-25%
#     di quel core dichiarando 8,0 e 26,0 Mbit/s su una linea da 45. Misurava se stessa.
#   - lotto 225, NEL SERVIZIO: puo' aspettare un momento con la CPU libera, ma non sa mai quando
#     l'utente fara' partire un film. Tre sonde su quattro sono state abbandonate a meta'.
#   - QUI la CPU e' libera (gli scraper hanno finito), la rete e' libera (la risoluzione non e'
#     ancora partita), e soprattutto la misura arriva **quando serve**, non quando capita.
#
# SU QUALE FILE. Sulla prima sorgente in cache nell'ordine dell'autoplay -- ma LOTTO 240: fra quelle
# che il filtro della dimensione terrebbe, non fra tutte. Prima del 240 il bersaglio era il primo
# dell'ordine di autoplay sulla lista NON ancora filtrata, che e' quasi sempre il remux piu' grosso,
# cioe' proprio quello che il filtro sta per togliere: l'offset della sonda cadeva fuori dalla fascia
# 10-25% del file riprodotto 11 volte su 16, prova che si stava misurando un altro file.
# Il link risolto per sondarla viene riusato per riprodurla: cosi' una parte dell'attesa non e'
# aggiunta, e' anticipata. E il nodo che misuriamo e' lo stesso che consegnera' il film.
#
# ATTENZIONE -- IL PRECEDENTE NEGATIVO. modules/band_probe.py e' la sonda dei lotti 191-195,
# staccata perche' non prediceva: il 07/09 dichiarava 3,39 Mbit/s e mezzo secondo dopo Kodi, sullo
# STESSO nodo, ne consegnava 11,16. Sappiamo adesso che quel numero era un artefatto di CPU, non del
# cdn. Ma la sua obiezione di fondo -- "misuri una connessione diversa da quella che riproduce" --
# qui non si applica proprio: e' la stessa sorgente, lo stesso nodo, lo stesso lettore.
#
# SOLO MISURA E FILTRO. La sonda non scarta niente da sola: produce una capacita', e chi filtra la
# divide per MARGINE. Quel margine e' l'unico numero ancora da guadagnare sui dati.
import http.client
from random import uniform
from time import monotonic as orologio, perf_counter, process_time, thread_time, time as adesso

# LOTTO 224 -- 256 KB, non 8. Il controllo dal Mac ha letto lo STESSO link con lo STESSO codice a
# 212-224 Mbit/s a qualunque profondita', mentre sulla stick la stessa sonda leggeva 3-4: il collo
# di bottiglia non e' ne' il cdn ne' il link, e' la lettura dentro il processo di Kodi. A 8 KB per
# giro una linea da 46 Mbit/s costa 700 iterazioni al secondo di ciclo Python -- ognuna con una
# allocazione, una copia e un rilascio del GIL -- dentro un interprete dove nello stesso momento
# venti thread di scraper stanno analizzando JSON. A 256 KB i giri diventano 22 e si legge con
# readinto() dentro un buffer riusato, quindi senza allocare.
# Il passo grosso non toglie risoluzione dove serve: 256 KB a 46 Mbit/s sono 45 ms, contro un
# bucket di 500. Su una linea da 3 Mbit/s sono 700 ms, e li' la curva e' grossolana -- ma una linea
# da 3 Mbit/s la sonda la riconosce comunque.
PASSO = 262144
BUCKET = 0.5              # passo della curva
# LOTTO 230 -- I TRE NUMERI CHE COSTANO TEMPO ALL'UTENTE, e vengono dalle curve vere.
#
# QUANTO DURA LA FINESTRA. Facendo scorrere una finestra di lunghezza L dentro le quattro curve
# misurate e confrontandola col regime dell'intera curva, l'errore e':
#     1 s -> 37% peggiore, 7,0% medio | 2 s -> 23% / 5,3% | 3 s -> 16% / 4,8%
#     4 s -> 11% / 4,0%  |  5 s -> 8,6% / 3,5%  |  8 s -> 4,9% / 2,3%  |  10 s -> 4,7% / 1,8%
# Sopra i sei secondi la curva e' piatta e si paga attesa per niente. Cinque secondi, deciso
# dall'utente: 8,6% nel caso peggiore, 3,5% tipico. E gli errori sono quasi tutti VERSO IL BASSO,
# cioe' una finestra corta sottostima -- sbaglia dalla parte prudente.
#
# QUANTO DURA LA RAMPA. Il primo pezzo da PASSO byte e' gia' scartato prima che parta il cronometro,
# e quello si porta via quasi tutta la salita del tcp: nel primo secondo dopo di lui le quattro
# curve stanno a -0%, -0%, -13%, -12% dal regime. Un secondo basta; i due del lotto 222 erano
# attesa regalata.
SECONDI_SALITA = 1.0
SECONDI_MINIMI = 4.0      # meno di cosi' di regime non e' una misura: si dichiara None
# LOTTO 243 -- LA FINESTRA SI PRENDE, NON SI SPERA.
#
# Fino al 242 qui c'era `SECONDI_TOTALI = 6.0`: un budget di OROLOGIO. Ma la grandezza che serve non
# e' "sei secondi di lettura", e' "cinque secondi di osservazione DOPO la rampa" -- e le due
# coincidono solo se la rampa dura davvero un secondo. Quando non dura un secondo si finisce
# l'orologio prima di avere il dato, e la misura si butta.
#
# IL CONTO, che e' quello che rende il difetto inevitabile e non sfortunato. 6,0 di budget meno 1,0
# di rampa fa 5,0, e ne servono 4,0 (SECONDI_MINIMI): **un secondo di margine**. `base` e' il primo
# campione a t >= SECONDI_SALITA, quindi basta UNA lettura che vada a cavallo fra 1,0 s e 2,0 s --
# cioe' 256 KB sotto i 2 Mbit/s -- e base slitta oltre i 2,0: finestra sotto i 4,0, niente regime.
#
# E' successo. L'11/09 alle 04:30, Nosferatu:
#
#     curva  0.6:0.2 3.1:1.8 3.8:2.0 4.3:3.0 4.8:4.0 5.4:5.0 5.9:6.0
#            ^^^^^^^ ^^^^^^^ una lettura sola da 2,5 s (0,84 Mbit/s): base slitta a 3,1
#     -> finestra 2,9 s < 4,0 -> REGIME ? -> il filtro ripiega -> 94 SECONDI a secco
#
# E il numero c'era ed era buono: ricalcolato dalla curva vale 13,60 Mbit/s, contro i 14,9-22,4 che
# la riproduzione ha poi consegnato.
#
# ADESSO si legge finche' la finestra oltre la rampa non e' lunga SECONDI_REGIME. Cinque, che e'
# esattamente quello che 6,0 - 1,0 produceva prima: **su linea sana questo lotto non cambia niente**
# -- le tre sonde dell'11/09 alle 13:57 hanno chiuso a 4,9 / 5,0 / 5,0 s di regime dentro i 6,0 s di
# budget -- e allunga solo quando la rampa o uno stallo spingono `base` piu' in la'.
#
# DOVE FINISCE, visto che non c'e' piu' un tetto a orologio. I limiti veri ci sono gia' e sono tre,
# ed erano sempre stati quelli giusti: il TIMEOUT del socket (8 s per singola operazione: una
# lettura che non torna muore da sola, quindi `base` non puo' cadere oltre ~9 s e il caso peggiore
# reale sta intorno ai 15), BYTE_MASSIMI, e l'utente che annulla. Un tetto a orologio non e' un
# limite: e' una scommessa sul fatto che la linea sia veloce.
# CAVEAT che non nascondo: col lettore di Kodi il primo dei tre non e' nostro -- CCurlFile ha i
# timeout di Kodi, che non controlliamo.
SECONDI_REGIME = 5.0      # quanta osservazione oltre la rampa si porta a casa, sempre
# LOTTO 257 -- LA FINESTRA NON E' PIU' FISSA. Si smette quando la misura ha smesso di muoversi
# (vedi _tratto_stabile), e questo e' il tetto oltre il quale si smette comunque. Su linea pulita si
# esce prima dei 5 s di prima; su linea che non si stabilizza si legge fino a qui invece di
# dichiarare un numero preso da un tratto che non descrive niente.
# Il valore NON e' misurato: nessuna delle 46 curve in archivio arriva oltre i ~7 s, perche' prima
# la sonda si fermava li'. E' una scommessa ragionevole da verificare al prossimo log.
SECONDI_MASSIMI = 10.0
# LOTTO 240 -- LA RAMPA NON DURA UN SECONDO QUANDO LA LINEA E' LENTA, e la finestra fissa
# sottostima proprio dove il filtro fa piu' danno.
#
# SECONDI_SALITA = 1,0 viene dalle quattro curve del lotto 230, prese tutte su una linea da 45
# Mbit/s: nel primo secondo dopo il pezzo scartato stavano a -0%, -0%, -13%, -12% dal regime, cioe'
# erano piatte. L'11/09 alle 03:20, con la stick agganciata al 5 GHz a -72 dBm (Android: "acceptable
# but not qualified", e l'AP a 2,4 GHz stava a -54), le curve sono un'altra cosa -- ANCORA IN SALITA
# quando la finestra finisce:
#
#     riga 14   1o terzo  7,2 | 2o terzo  5,6 | 3o terzo 16,0 Mbit/s    coda/centro 2,86
#     riga 15   1o terzo  8,8 | 2o terzo 12,0 | 3o terzo 19,2 Mbit/s    coda/centro 1,60
#
# Lo slow start di TCP cresce per RTT, non per secondo, e a -72 dBm le ritrasmissioni tengono giu'
# la finestra molto piu' a lungo: la rampa si allunga ESATTAMENTE quando la linea e' peggiore, cioe'
# quando il filtro sta per decidere sul serio.
#
# E il numero giusto la sonda ce l'ha gia' in mano -- lo sta diluendo dentro la propria rampa:
#
#                      media su 5 s   coda della curva   portata vera della riproduzione
#     riga 14             10,48            15,24                    15,3
#     riga 15             15,36            17,45                    19,4
#
# Quindi: se la curva sta ancora salendo alla fine della finestra, la finestra e' finita troppo
# presto e la media non descrive nessun regime -- si dichiara la coda. Se e' piatta non cambia
# niente, ed e' la proprieta' che rende questo lotto verificabile: SU LINEA SANA DEVE ESSERE UN
# NON-EVENTO. Le undici sonde del 10/09 avevano portata/sonda con mediana 1,00: curve piatte.
#
# Non si allunga la finestra: su linea veloce si pagherebbe attesa per un numero gia' giusto.
#
# 1,30 e' EMPIRICO come QUOTA_MINIMA, e lo dico: le due curve in salita misurate stanno a 1,60 e
# 2,86, una curva piatta sta intorno a 1,0, e il vuoto in mezzo non l'ha ancora visitato nessuno.
# L'ASIMMETRIA decide da che parte sbagliare, ed e' ROVESCIATA rispetto a QUOTA_MINIMA: li' si
# scartava con generosita' perche' il ripiego era un numero conservativo noto, qui alzare la misura
# ammette file piu' grossi. Quindi si corregge con parsimonia -- soglia alta, e mai verso il basso.
#
# LOTTO 245 -- 1,30 NON E' MAI SCATTATA DOVE SERVIVA, e adesso le misure sono due.
#
# Il 1,30 veniva da due curve a 1,60 e 2,86 e da un vuoto in mezzo che "non l'ha ancora visitato
# nessuno". Nel frattempo il vuoto e' stato visitato, due volte, e in entrambe la coda aveva
# ragione e la soglia le ha impedito di parlare:
#
#     11/09 15:53  Incendies   coda/centro 1,15   media 41,85 | coda 44,94 | linea vera 46,7
#     11/09 (prec) Nosferatu   coda/centro 1,16   la coda era il numero buono
#
# Errore della media 10%, errore della coda 4%: sulla stessa riga, nella stessa direzione.
# E le curve PIATTE misurate nella stessa sessione stanno a 0,98 - 1,05 - 1,09. Quindi il confine
# fra "piatta" e "ancora in salita" cade fra 1,09 e 1,15, non a 1,30.
#
# 1,12 ci sta in mezzo: sopra la piu' inclinata delle curve piatte osservate (1,086), sotto
# entrambi i casi in cui la correzione serviva. Il rischio di sbagliare per eccesso resta
# limitato da cio' che la coda puo' dichiarare di troppo: sulle quattro righe del 11/09 la coda
# supera la portata vera al massimo del 6% (Pianist, 48,42 contro 45,7) e quella riga a 1,054
# NON scatta comunque. La guardia `coda > regime` resta: la correzione puo' solo smettere di
# diluire la misura nella rampa, mai abbassarla.
SECONDI_CODA = 2.0        # l'ultimo tratto di curva che descrive il regime raggiunto
SALITA_SOSPETTA = 1.12    # coda/centro oltre il quale la curva non si era ancora appiattita
# LOTTO 249 -- E LA REGOLA SPECULARE, PER LE CURVE CHE SCENDONO.
#
# Diciassette sonde in archivio, `sonda_salita` da 0,80 a 1,09: SALITA_SOSPETTA non e' MAI scattata,
# nemmeno una volta. L'unico scostamento vero osservato va nell'altro verso -- la riga a 0,80
# (coda 35,6 contro centro 44,6) -- e li' si e' dichiarata la media, 40,3, cioe' un numero piu' alto
# di quanto la linea stesse dando negli ultimi due secondi.
#
# Perche' e' il verso che conta di piu', e non una simmetria messa per eleganza: la taratura va
# fatta sulla riproduzione SOSTENUTA. Una curva che scende dice esattamente che la linea non ha
# tenuto il ritmo con cui era partita -- congestione, oppure il burst iniziale di TCP che rientra --
# e in quel caso la media e' gonfiata proprio dal tratto che non si ripetera'. La coda e' il tratto
# piu' recente e il piu' rappresentativo di cio' che la riproduzione otterra' per ore.
#
# 0,89 e' 1/1,12: la stessa distanza dal centro, dall'altra parte. Sulle diciassette righe scatta
# una volta sola, su quella a 0,80; la seconda piu' bassa e' 0,92 e resta ferma.
#
# ATTENZIONE, l'asimmetria e' voluta ed e' l'opposto di quella del lotto 240: quella regola poteva
# solo ALZARE (guardia `coda > regime`), questa puo' solo ABBASSARE (`coda < regime`). Nessuna delle
# due puo' rendere il filtro piu' permissivo per sbaglio, che e' l'invariante da tenere.
DISCESA_SOSPETTA = 0.89   # coda/centro sotto il quale la curva stava calando: vale la coda
# LOTTO 254 -- UN PAVIMENTO PROVATO E RITIRATO, e la ragione vale piu' del codice.
#
# Il caso, 12/09 alle 05:58: coda/centro 0,155, la regola dichiara 1,49 Mbit/s contro una media di
# 6,52, il filtro scende a 1,2 e all'utente tocca un file 720x544. La portata misurata durante quella
# riproduzione: 5,73. La sonda aveva letto il 26% della linea vera, e la media (6,52) sarebbe stata
# quasi esatta.
#
# Avevo aggiunto un pavimento (DISCESA_STALLO = 0,50): sotto, "non e' un calo ma uno stallo, vale la
# media". Sulla curva vera funzionava: l'ultimo campione copre 2,8 s per 0,5 MB, cioe' uno stallo
# netto in coda dopo un tratto regolare a 1,0-1,5 MB/s.
#
# MA NON DISTINGUE I DUE CASI. La curva di prova del lotto 240 -- che scende
# 2,8/2,8/2,8/2,0/2,0/1,0/1,0/0,5/0,5/0,3/0,3 -- ha rapporto 0,363 e col pavimento smetteva di
# scattare; eppure li' il calo e' progressivo e finisce su un ALTOPIANO STABILE, cioe' la coda E' il
# ritmo nuovo ed e' esattamente il caso per cui la regola esiste. Nemmeno `avvallamento` separa i
# due: copre la coda in entrambi.
#
# Un solo caso reale, e una regola che riclassifica male un caso plausibile. Stringere il pavimento a
# 0,30 farebbe passare tutti e due, ma sarebbe adattare un parametro a due punti, non scrivere una
# regola. Si ritira e si raccolgono altri casi.
#
# IL DATO CHE IL CASO HA PRODOTTO, e che resta: il rapporto sonda/portata per fonte, su 23 righe di
# archivio, vale `media` 1,01 (n=19), `coda` 0,84 (n=2), `coda_in_calo` 0,42 (n=2). E per velocita'
# di linea: 1,07 sopra i 30 Mbit/s (n=15), 0,60 sotto (n=8). La sonda e' ben tarata sulla linea
# veloce e legge basso su quella lenta -- ed e' li' che va guardata la prossima volta. (`portata` e'
# un limite INFERIORE della linea, quindi un rapporto sotto 1 e' prova certa di sottostima; sopra 1
# e' ambiguo, perche' il buffer puo' essersi riempito e Kodi ha smesso di chiedere.)
# LOTTO 254 -- E UN PAVIMENTO, perche' un CROLLO non e' un CALO.
#
# Il caso, 12/09 alle 05:58: coda/centro 0,155, la regola dichiara 1,49 Mbit/s contro una media di
# 6,52. Il filtro e' sceso a 1,2 e all'utente e' toccato un file 720x544. La portata misurata durante
# quella riproduzione: **5,73 Mbit/s**. La sonda aveva letto il 26% della linea vera.
#
# La regola della discesa nasce per dire "la linea non ha tenuto il ritmo con cui era partita", e a
# quello serve. Ma una coda che vale il 15% del centro non e' una linea che cala: e' uno STALLO
# dentro la finestra, e gli stalli hanno gia' il loro strumento -- `avvallamento`. Su uno stallo la
# media, che lo comprende, e' lo stimatore migliore; la coda misura solo il fondo del buco.
#
# 0,50: sotto, si e' in territorio di stallo e vale la media. Sopra (fino a 0,89) e' un calo vero e
# la coda resta il numero giusto. Sulle due righe in archivio: 0,155 torna alla media (portata vera
# 5,73 contro 6,52 dichiarati, rapporto 1,14) e 0,716 resta sulla coda, che li' era giusta.
#
# TARATO SU DUE RIGHE, e lo dico. Il rapporto sonda/portata per fonte oggi vale: `media` 1,01 su 19
# righe, `coda` 0,84 su 2, `coda_in_calo` 0,42 su 2 -- cioe' e' proprio questa regola quella che
# sottostima di piu', ed e' l'unica con un pavimento.
# LOTTO 245 -- QUANTO IN BASSO DEVE ANDARE UN TRATTO PER CHIAMARSI AVVALLAMENTO.
#
# Frazione del ritmo MEDIO della finestra, non di quello dichiarato: se si misurasse contro il
# regime dichiarato, questo strumento cambierebbe valore a seconda che la regola della coda sia
# scattata o no, e i due cambiamenti di questo lotto non sarebbero piu' separabili nel log.
#
# 0,70 separa cio' che e' stato misurato l'11/09: le tre curve sane toccano un minimo di 0,76 -
# 0,80 - 0,83 del proprio ritmo medio, quella contaminata scende a 0,61. Il margine e' stretto e
# lo dico, ma questo numero NON DECIDE NIENTE -- si scrive in archivio e basta -- quindi un falso
# positivo costa una colonna imprecisa, non una sorgente scartata.
FRAZIONE_AVVALLAMENTO = 0.70
BYTE_MASSIMI = 160 * 1024 * 1024   # tetto duro, per non restare attaccati a una linea velocissima
TIMEOUT = 8               # per singola operazione di socket
REDIRECT = 4

# LOTTO 230 -- L'ABBANDONO NON HA PIU' UNA CODA DA SALVARE.
#
# Fino al lotto 229 la sonda girava in sfondo e poteva essere sorpresa da un film che partiva: gli
# ultimi secondi erano concorrenza nostra e si scartavano (`CODA_ABBANDONO`), tenendo il resto.
# Adesso la sonda e' SINCRONA e sta dentro la ricerca sorgenti: mentre legge, nessuna riproduzione
# puo' partire, perche' e' lo stesso thread che la farebbe partire.
#
# Resta un solo motivo per mollare: l'utente che annulla la ricerca. E li' la misura non serve piu' a
# nessuno, quindi non si salva niente -- si smette di leggere e basta.
# DOVE si legge dentro il file. Non in testa, e non e' piu' una questione di velocita' del cdn (il
# lotto 227 ha dimostrato che la profondita' non conta): e' che la testa e' proprio la parte che il
# film sta per leggere. Sondarla la scalderebbe nel nodo di bordo, la riproduzione partirebbe piu'
# veloce del normale, e la TARATURA DEL MARGINE ne uscirebbe falsata verso il basso -- cioe' verso
# il meno sicuro. Si legge fra il 10% e il 25%: lontano dall'inizio, dentro la parte che il film
# attraversera' comunque.
FRAZIONE_MIN, FRAZIONE_MAX = 0.10, 0.25

# IL MARGINE. La sonda misura una CAPACITA'; `line_speed` e' cio' che un film puo' chiedere senza
# soffrire, ed e' piu' basso -- 24 MB di buffer sono meno di cinque secondi a 40 Mbit/s, e un cdn non
# consegna liscio.
#
# QUESTO NUMERO NON E' ANCORA GUADAGNATO SUI DATI, ed e' l'unica cosa che resta da fare. Viene da due
# indizi: la curva di salute misurata sulla stick (fluida fino a ~34 Mbit/s, in affanno da ~40, su
# una linea che la sonda misura a ~46) e il rapporto portata/sonda osservato, 1,04-1,08. Entrambi
# collocano il margine fra 1,15 e 1,4; 1,25 sta in mezzo ed e' prudente.
#
# Si tara cosi': ogni riproduzione lascia in archivio `bitrate` e `sonda_mbps`; si ordina il loro
# rapporto (playback_stats.rapporto_sonda) su venti-trenta righe indipendenti e si guarda dove le
# righe sane finiscono e cominciano quelle sofferenti. Quel confine e' 1/MARGINE.
MARGINE = 1.25

# LOTTO 259 -- E ADESSO SI TARA DAVVERO, dall'archivio invece che a mano.
#
# Il paragrafo qui sopra dice da tre lotti come si sarebbe fatto. Al 13/09 l'archivio ha 26 righe e
# 8 stalli, e la risposta si legge: il margine che sarebbe servito a rifiutare ciascuna riproduzione
# finita a secco vale 1,25 1,26 1,27 1,42 1,42 1,64 1,66 1,73. Con MARGINE a 1,25 nessuno degli otto
# viene evitato; a 1,73 nessuno passa.
#
# PERCHE' CALCOLARLO E NON SCEGLIERLO. Il valore giusto dipende dalla rete, e la rete cambia sotto
# di noi: sulla 2,4 GHz di casa servirebbe 1,66, sul 5 GHz debole 1,73, e la stick salta banda da
# sola. Una costante scritta qui sarebbe giusta per una sola delle due, e sbagliata l'altra meta'
# del tempo. Un numero rifatto sulle ultime cinquanta riproduzioni segue la rete che c'e'.
#
# COSA COSTA, e va detto: su quelle 26 righe salire a 1,73 avrebbe bloccato 6 riproduzioni andate
# bene su 18. Non sono film non visti -- e' una sorgente piu' piccola al posto di una grande -- ma
# e' qualita' persa, ed e' il prezzo della politica STALLI_TOLLERATI = 0.
STALLI_TOLLERATI = 0
# Sotto queste due soglie non si calcola niente e si resta su MARGINE. La prima perche' un archivio
# corto descrive un pomeriggio, non una linea; la seconda perche' senza stalli non si sa DOVE sia il
# confine -- si sa solo che non lo si e' ancora incontrato, che e' un'altra cosa e non autorizza a
# muovere niente.
RIGHE_MINIME_MARGINE = 20
STALLI_MINIMI_MARGINE = 3
# Il tetto esiste perche' un archivio raccolto tutto su una rete rotta chiederebbe un margine che
# rende il filtro inutile. Il pavimento e' MARGINE stesso: se il calcolo chiede meno vuol dire che
# gli stalli osservati sono gia' coperti, non che si possa allargare -- allargare sarebbe
# estrapolare in territorio non provato.
MARGINE_MASSIMO = 2.0
# Il margine deve SUPERARE il rapporto, non uguagliarlo: con l'uguaglianza la riga che ha stallato
# ripasserebbe identica.
MARGINE_EPSILON = 0.01

# LOTTO 253 -- E UN MARGINE CHE CRESCE QUANDO LA LINEA SINGHIOZZA.
#
# IL CASO, del 12/09 alle 05:17. La sonda dichiara 10,42 Mbit/s, la soglia diventa 8,3, un file da
# 8,09 passa per un soffio: la riproduzione tiene la cache all'1% di media e resta a secco per 81
# secondi. La portata misurata durante quella riproduzione e' 8,1 -- la sonda aveva sovrastimato del
# 28%, e il margine effettivo e' stato 1,00.
#
# Il segnale c'era, sulla stessa riga di log: il 41% della finestra di misura era un AVVALLAMENTO.
# Lo misuriamo dal lotto 245, lo scriviamo e lo archiviamo, e poi dichiaravamo la media lo stesso.
#
# Il meccanismo NON e' un errore sistematico, e' VARIANZA: su una linea che singhiozza cinque secondi
# sono un campione troppo corto, e la media di quei cinque secondi non predice i minuti successivi.
# Quindi non si corregge la stima verso il basso -- si riconosce che quella stima VALE MENO e si
# pretende piu' margine proprio dove la linea e' instabile.
#
# SOLO SULLA MEDIA NUDA, e questa e' la parte che i dati hanno insegnato. Quando una delle due regole
# della coda e' scattata la stima e' GIA' stata spostata verso il tratto piu' recente, e sommarci la
# penalita' la conterebbe due volte. Con la penalita' applicata a tutti, la riga Aliens del 12/09
# (fonte `coda_in_calo`, instabilita' 36%, riproduzione andata LISCIA) sarebbe stata rifiutata a
# torto. Applicandola alla sola `media`, le tre righe di quel giorno escono tutte e tre giuste.
#
# PESO 0,5 e non 1,0: su Coco basta un margine di 1,29 per rifiutare quel file, e 0,5 lo porta a 1,51
# -- abbastanza da prendere il caso osservato con margine, non tanto da svuotare l'elenco appena la
# linea fa un singhiozzo. Con instabilita' 1,0 (tutta la finestra in avvallamento) il margine arriva
# a 1,875, che e' un tetto ragionevole e non serve troncarlo.
#
# TARATO SU UN SOLO FALLIMENTO. Va rivisto quando l'archivio ne avra' altri: e' un giudizio, e lo dico.
PESO_INSTABILITA = 0.5

# LOTTO 225 -- QUANTA CPU RIUSCIAMO A OTTENERE ADESSO. E' la misura che mancava, e senza di lei
# ogni numero di questa sonda e' ambiguo.
#
# Su questo Android il Python di Kodi vive in UN processo e tutti i sotto-interpreti si dividono UN
# core: la quota di ciascuno e' circa 1/N (misurato il 08/09: 6 interpreti -> 16%, 4 -> 25%, da solo
# -> 86%). La sonda decifra TLS, quindi legge al massimo ~90-100 Mbit/s con un core intero: con un
# quarto di core il tetto scende a 25 e la sonda misura se stessa invece della linea.
#
# E il rapporto cpu/tempo della sonda NON basta a distinguere i due casi: se leggiamo 26 Mbit/s
# perche' la linea fa 26, la cpu consumata e' la stessa che se ne leggessimo 26 perche' abbiamo un
# quarto di core. I due casi hanno la stessa firma. L'unico modo di separarli e' misurare la quota
# disponibile con un ciclo che NON fa I/O -- questo -- e confrontarla.
QUOTA_CAMPIONE = 0.05     # secondi di cpu da bruciare per avere una lettura
QUOTA_ATTESA_MAX = 1.5    # se non li ottiene entro qui, la macchina e' occupata e tanto basta
# LOTTO 226 -- 0,75 e non 0,55, e il numero viene da una misura. La prima sonda buona (10/09,
# 42,77 Mbit/s) ha consumato 97 ms di cpu per MB: tetto 82,7 Mbit/s con un core intero, quindi
# 45,5 con la quota minima di allora. Ha letto 42,77 contro un tetto di 45,5: **2,7 Mbit/s di
# margine**, cioe' era gia' quasi contro il muro -- e infatti la riproduzione, subito dopo, ha
# misurato 45,4. Il numero era un pavimento travestito da misura.
# Con 0,75 il tetto effettivo sale a ~62 Mbit/s, che lascia spazio vero sopra una linea da 45.
# Il prezzo e' che la sonda parte piu' di rado; ma il servizio non ha nessuno che lo aspetta, e una
# sonda in meno costa molto meno di una sonda che mente.
# LOTTO 238 -- QUESTA COSTANTE ERA DICHIARATA E NON USATA DA NESSUNO, e nel frattempo il caso che
# doveva coprire e' successo davvero. Il 10/09 alle 22:02, sulla stick, con quota 27%:
#
#     REGIME 6.62 Mbit/s   (la stessa linea, due minuti dopo: 46,23)
#     curva  0.8 1.0 1.2 1.8 2.0 2.5 3.0 3.2 3.8 4.2 4.5 4.8    <- a scatti, 3x fra bucket vicini
#     cpu    consumo 9% | quota 27% | processo 185%
#
# La misura e' stata PUBBLICATA: il filtro ha lavorato con line_speed 5,3 e la lista delle sorgenti
# si e' svuotata. _limitata_da_cpu non l'ha fermata perche' cerca consumo/quota >= 0,95 e li' era
# 0,33: il suo presupposto e' che la fame di cpu si veda come consumo ALTO.
#
# PER UN THREAD CHE FA I/O NON E' COSI'. Il GIL conteso non toglie cicli, toglie OCCASIONI: fra due
# recv() il thread aspetta di riprendere il lucchetto, il socket non viene svuotato, la finestra TCP
# si chiude. Portata e consumo crollano INSIEME, e il loro rapporto resta innocente. La prova che
# non e' un tetto di decifratura: 27% di 74 Mbit/s fa 20, e la sonda ne ha letti 6,62, un terzo.
# Nessun prodotto tetto x quota spiega quel numero -- l'unica grandezza che separa quella sonda
# dalle altre cinque della serata e' la quota nuda.
#
# 0,60 e' EMPIRICO e non lo nascondo: le sei sonde della serata stanno a 27, 70, 74(*), 76, 78, 80,
# 81, 86, 87, 95 di quota e la soglia sta nel vuoto fra 27 e 70, verso l'alto. Sotto non ci sono
# misure buone da difendere; sopra non ce ne sono di cattive da scartare. Il vuoto in mezzo non l'ha
# mai visitato nessuno.
# L'ASIMMETRIA decide da che parte sbagliare: scartare costa un ripiego sull'impostazione dell'utente
# -- un numero conservativo e noto -- mentre tenere una misura falsa svuota la lista o fa stallare un
# film. Quindi si scarta con generosita'.
# Vale per ENTRAMBI i lettori, e questa e' una scelta prudente non una misura: anche il lettore di
# Kodi legge dentro un ciclo Python, quindi anche lui dipende da quanto spesso quel thread viene
# schedulato. Che CCurlFile lo assorba meglio e' plausibile e non l'ho verificato.
QUOTA_MINIMA = 0.60
# QUANDO UNA LETTURA E' LIMITATA DALLA CPU, e perche' la risposta dipende da CHI ha letto.
#
#   Lettore di KODI: decifra in C++ col GIL rilasciato, quindi il GIL non lo tocca. L'unico modo in
#     cui puo' essere limitato e' saturare un core: `consumo` (cpu del thread / tempo) vicino a 1.
#   Lettore PYTHON: puo' essere limitato in DUE modi -- il core saturo, e il GIL conteso dagli altri
#     interpreti. Il secondo non si vede dal consumo (0,10 puo' voler dire "linea lentissima" o
#     "un decimo di core"): si vede solo confrontando il consumo con la quota disponibile.
#
# Un solo numero non copre i due casi, e usarne uno solo li' dove non vale e' il modo in cui una
# misura sbagliata passa per buona.
CONSUMO_SOSPETTO = 0.85     # sopra: e' un minimo, si avvisa
CONSUMO_LIMITE = 0.95       # sopra: non e' una misura


def perf_modulo():
	"""`modules.perf` importato alla prima richiesta. Non a livello di modulo: perf tira dentro
	xbmc e xbmcgui, e questo file lo importano anche le prove, che non hanno l'API di Kodi."""
	from modules import perf
	return perf


def quota_cpu(campione=QUOTA_CAMPIONE):
	"""Frazione di un core che questo thread riesce a ottenere adesso, 0..1.

	Ciclo occupato puro, niente rete: e' esattamente la grandezza che la sonda non puo' dedurre da
	se stessa. Costa `campione` secondi di cpu -- 50 ms -- e li spende una volta per sonda.
	"""
	try:
		_t0, _c0 = orologio(), thread_time()
		_scade = _t0 + QUOTA_ATTESA_MAX
		while thread_time() - _c0 < campione:
			if orologio() > _scade: break
		_w = orologio() - _t0
		return ((thread_time() - _c0) / _w) if _w > 0 else 0.0
	except: return 1.0    # non misurabile: non si blocca la sonda per uno strumento rotto


# LA SONDA SI ABBANDONA APPENA UN FILM PARTE, e non e' una cortesia: la banda che prende e' quella
# che il film sta usando. Cio' che e' stato letto PRIMA dell'avvio resta valido: si tronca, non si
# butta via del tutto: chi ha annullato non vuole una misura. Chi la chiama passa `molla`.


# ---- i due lettori --------------------------------------------------------------------------
# LOTTO 227 -- LEGGERE CON KODI, NON CON PYTHON, e la ragione e' un numero.
#
# La prima sonda buona ha consumato 97 ms di cpu per MB: il modulo `ssl` di Python su questa stick
# decifra AES a **10,3 MB/s**, cioe' 82 Mbit/s con un core intero e basta. Non e' un problema di
# GIL da aggirare mettendoci piu' thread: e' proprio il costo della decifratura, e su quattro core
# non si distribuisce -- una connessione sola vive in un thread solo.
#
# Kodi lo stesso https lo legge a 46 Mbit/s mentre riproduce. Quindi il lettore giusto ce l'abbiamo
# gia' in casa: `xbmcvfs.File` e' la stessa CCurlFile che apre il film. Tre vantaggi, e il terzo e'
# quello che conta di piu':
#   1. decifra in C++, con il GIL RILASCIATO: un core libero diventa davvero utilizzabile;
#   2. usa la libreria TLS di Kodi, che sulla piattaforma puo' avere l'accelerazione hardware che
#      il Python di Kodi non ha;
#   3. e' **lo stesso percorso di codice che riprodurra' il film**. Una sonda che misura la strada
#      vera vale piu' di una che ne misura una parallela: e' l'obiezione con cui e' morta la sonda
#      dei lotti 191-195, e qui cade da sola.
#
# Il lettore Python resta come RIPIEGO e come banco di prova: e' quello che le prove sanno guidare
# con una rete finta, e se un giorno xbmcvfs non aprisse un link la sonda non deve sparire.
#
# Cosa si perde: con xbmcvfs non si vede il nodo finale dopo i redirect, quindi `cdn` e' l'host
# chiesto e non quello che ha risposto. E non si vede lo stato HTTP: un link scaduto si presenta
# come "non si apre", che per noi vuol dire la stessa cosa.

def _limitata_da_cpu(esito):
	"""Il motivo per cui questa lettura non e' una misura della linea, o None.

	INVARIANTE, nello spirito di portata_secchi: una lettura fatta senza cpu NON descrive la linea e
	non deve poter arrivare al wizard travestita da tale. Il 10/09 due sonde hanno dichiarato 26,0 e
	8,01 Mbit/s su una linea da 45: erano esattamente 0,25 e 0,10 del tetto di decifratura.
	"""
	try:
		# LOTTO 238 -- PRIMA DI TUTTO IL RESTO: con troppo poca cpu disponibile la lettura non
		# descrive la linea, e non serve sapere che cosa stesse occupando la macchina. E' l'unica
		# guardia che non ha bisogno di una diagnosi, ed e' per questo che sta in cima.
		_quota = esito.get('quota')
		if _quota is not None and _quota < QUOTA_MINIMA:
			return 'cpu contesa (quota %.0f%%, sotto il %.0f%% minimo)' % (_quota * 100, QUOTA_MINIMA * 100)
		_sec, _cpu = esito.get('secondi') or 0, esito.get('cpu')
		if not _sec or _cpu is None: return None
		_consumo = _cpu / _sec
		# Un thread non puo' superare un core: consumo vicino a 1 vuol dire che il core e' il
		# vincolo, e vale per QUALUNQUE lettore.
		if _consumo >= CONSUMO_LIMITE:
			return 'cpu satura (%.0f%% di un core)' % (_consumo * 100)
		# Solo per il lettore Python: il GIL. Col lettore di Kodi la quota misura una cosa che non
		# c'entra -- il tempo di Python -- e confrontarla col consumo darebbe rapporti sopra 1.
		if esito.get('lettore') == '_LettorePython':
			if _quota and _consumo / _quota >= CONSUMO_LIMITE:
				return 'GIL conteso (%.0f%% di quota, consumata tutta)' % (_quota * 100)
		return None
	except: return None


def _host(url):
	"""L'host chiesto. Col lettore di Kodi non si vede quello che risponde dopo i redirect."""
	try:
		from modules.http_client import _split_url
		return _split_url(url)[1]
	except: return None


def _apri_lettore(url, offset, lettore_classe, fuori):
	"""Chi legge, e la scelta e' cambiata al lotto 232 su una misura.

	Il lotto 227 aveva scelto il lettore di Kodi perche' decifra in C++ e costa meno cpu: 78 ms per
	MB contro 96, cioe' un tetto di 107 Mbit/s contro 82. Vero, ma il ttfb spezzato in tre (lotto
	231) ha mostrato il conto vero:

	    apertura 1098 ms  +  POSIZIONAMENTO 2263 ms  +  primo pezzo 102 ms

	`xbmcvfs.File` non sa aprire gia' a un offset: si apre, e poi si fa `seek()`, che su un file http
	e' una seconda richiesta con un secondo handshake. Il posizionamento da solo si mangia il 55-72%
	dell'attesa, e l'attesa e' tempo che l'utente paga SENZA misurare.

	Il lettore Python la Range la mette nella PRIMA richiesta: un giro solo, ttfb misurato 604-1077
	ms. Costa il 23% di cpu in piu', ma su una linea da 47 Mbit/s il consumo passa dal 45% al 55% di
	un core -- dentro la quota misurata (76-95%) e con `_limitata_da_cpu` a fare da guardia.

	Serve pero' conoscere l'offset PRIMA di aprire, quindi la dimensione va saputa in anticipo: la
	da' `item['size']` dello scraper. Quando non c'e' si ripiega sul lettore di Kodi, che la
	dimensione la sa dopo l'apertura e paga il seek. Stesso ripiego se la Range non viene onorata --
	`item['size']` e' stato trovato sbagliato di 25 volte (lotto 192), e un offset oltre la fine del
	file torna 416.
	"""
	if lettore_classe is not None: return lettore_classe(url, offset)
	if offset is not None:
		try: return _LettorePython(url, offset)
		except Exception as e: fuori['ripiego'] = 'Python: %s: %s' % (type(e).__name__, e)
	return _LettoreKodi(url, offset)


class _LettoreKodi:
	"""Il lettore di Kodi. `leggi(n)` torna quanti byte sono arrivati."""
	def __init__(self, url, offset=None):
		import xbmcvfs
		self.f = xbmcvfs.File(url)
		try: self.dimensione = self.f.size() or None
		except: self.dimensione = None

	def posiziona(self, offset):
		"""LOTTO 240 -- e su un ramo intero questo metodo non veniva chiamato affatto.

		`_apri_lettore` ripiega qui quando il lettore Python non riesce ad aprire gia' all'offset, ed
		e' un ramo che ci si ASPETTA di percorrere: `item['size']` e' stato trovato sbagliato di 25
		volte (lotto 192), e nei dati del 10/09 dichiarava 28,17 GB per un file da 20,37 e 36,48 per
		uno da 14,49. Ma in `misura` la chiamata stava dentro `if offset is None`, che sul ripiego e'
		falso: si leggeva da BYTE 0 e si dichiarava in archivio l'offset che si sarebbe voluto.

		Due danni, e il secondo e' il peggiore. Si scalda nel nodo di bordo proprio la parte che il
		film sta per leggere -- che e' la ragione per cui FRAZIONE_MIN/MAX esistono -- e la taratura
		di MARGINE ne esce falsata VERSO IL BASSO, cioe' verso il meno sicuro. E `sonda_offset`
		mente, quindi a posteriori non si puo' piu' nemmeno accorgersene.

		Torna l'offset EFFETTIVO. Se la dimensione dichiarata mentiva verso l'alto l'offset cade
		oltre la fine del file: si ricalcola sulla dimensione VERA, che questo lettore -- a
		differenza dell'altro -- la sa, invece di leggere zero byte e buttare via la sonda.
		"""
		if not offset: return offset
		if self.dimensione and offset >= self.dimensione: offset = offset_per(self.dimensione)
		self.f.seek(offset, 0)
		return offset

	def leggi(self, quanti):
		_b = self.f.readBytes(quanti)
		return len(_b) if _b else 0

	def chiudi(self):
		try: self.f.close()
		except: pass


class _LettorePython:
	"""http.client a mano. Ripiego, e l'unico che le prove sanno guidare."""
	def __init__(self, url, offset=None):
		self.offset = offset or 0
		self.conn, self.resp, self.host = _apri(url, self.offset)
		if self.resp is None: raise IOError('nessuna risposta')
		self.stato = self.resp.status
		# Con un offset chiesto, 200 vuol dire che la Range NON e' stata onorata e staremmo leggendo
		# la testa del file -- proprio cio' che non vogliamo scaldare. 416 vuol dire che l'offset era
		# oltre la fine, cioe' che `item['size']` mentiva. Entrambi si rifiutano: se ne occupa il
		# ripiego, che apre con Kodi e cerca.
		if self.offset and self.stato != 206: raise IOError('range non onorata (stato %s)' % self.stato)
		if self.stato not in (200, 206): raise IOError('stato %s' % self.stato)
		self.dimensione = self._totale()
		self.vista = memoryview(bytearray(PASSO))

	def _totale(self):
		"""La dimensione VERA dal Content-Range, che la stessa richiesta porta a casa gratis."""
		try:
			_cr = self.resp.getheader('Content-Range')
			if _cr and '/' in _cr:
				_coda = _cr.rsplit('/', 1)[1].strip()
				if _coda.isdigit(): return int(_coda)
			return int(self.resp.getheader('Content-Length') or 0) or None
		except: return None

	def posiziona(self, offset):
		# L'offset e' gia' nella Range della prima richiesta e qui non si puo' riposizionare: cio'
		# che e' stato davvero chiesto e' `self.offset`, e si torna quello (lotto 240).
		return self.offset

	def leggi(self, quanti):
		return self.resp.readinto(self.vista[:quanti])

	def chiudi(self):
		try:
			if self.conn: self.conn.close()   # senza drenare: si abbandona
		except: pass


def _apri(url, offset):
	"""(conn, resp) con Range dall'offset. Redirect seguiti a mano: urllib tirerebbe dentro email.*."""
	from modules.http_client import _split_url
	giri = REDIRECT
	while True:
		scheme, host, port, percorso = _split_url(url)
		cls = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
		conn = cls(host, port, timeout=TIMEOUT)
		conn.request('GET', percorso, headers={'Range': 'bytes=%d-' % offset,
											   'Accept-Encoding': 'identity',
											   'User-Agent': 'Mozilla/5.0', 'Connection': 'close'})
		resp = conn.getresponse()
		if resp.status in (301, 302, 303, 307, 308) and giri > 0:
			dove = resp.getheader('Location')
			conn.close()
			if not dove: return None, None, host
			if dove.startswith('/'): dove = '%s://%s:%s%s' % (scheme, host, port, dove)
			url, giri = dove, giri - 1
			continue
		return conn, resp, host


def _da(curva, quando):
	"""Il primo campione a `quando` o dopo. None se la curva finisce prima."""
	for _t, _b in curva:
		if _t >= quando: return (_t, _b)
	return None


def _fino(curva, quando):
	"""L'ultimo campione a `quando` o prima. None se la curva comincia dopo."""
	_ultimo = None
	for _t, _b in curva:
		if _t > quando: break
		_ultimo = (_t, _b)
	return _ultimo


def _ritmo(inizio, fine):
	"""Mbit/s fra due campioni (secondi, byte). None se il tratto non esiste."""
	try:
		if not inizio or not fine: return None
		dt, db = fine[0] - inizio[0], fine[1] - inizio[1]
		if dt <= 0 or db <= 0: return None
		return (db * 8.0) / dt / 1000000.0
	except: return None


def _avvallamento(curva, base, fine, riferimento):
	"""Il tratto continuo piu' lungo, DENTRO la finestra di regime, in cui la linea ha consegnato
	meno di FRAZIONE_AVVALLAMENTO del ritmo medio. In secondi; 0.0 se non ce n'e' nessuno.

	LOTTO 245 -- SOSTITUISCE `_buco`, CHE MISURAVA DUE COSE SBAGLIATE.

	1. CONTAVA LA RAMPA COME UN BUCO. Partiva da `_prima = 0.0`, quindi il primo intervallo era
	   quello fra l'istante zero e il primo campione -- che non e' una pausa, e' l'inizio della
	   misura. Sulle quattro righe dell'11/09 `sonda_buco` vale 0,54 - 0,55 - 0,55 - 0,56: e'
	   sempre e solo il primo bucket. Una colonna che su linea sana riporta una costante di
	   campionamento e non un fatto della linea.

	2. VEDEVA SOLO I VUOTI, NON I RALLENTAMENTI. La sonda di Incendies (11/09 15:53) ha avuto un
	   bucket a ~26 Mbit/s fra 2,1 e 2,6 s, con i vicini a 36-48. I byte continuavano ad arrivare,
	   quindi nessun intervallo si allungava e `_buco` non ha visto niente -- ma quel tratto ha
	   tirato la media da ~45 a 41,85, cioe' 10% sotto i 46,7 che la linea ha poi consegnato
	   davvero alla riproduzione. Era l'unica riga delle quattro in cui la misura era sbagliata, ed
	   era proprio quella che lo strumento non sapeva raccontare.

	Uno stallo vero e' il caso limite di un rallentamento (ritmo zero), quindi questa misura
	contiene la precedente invece di affiancarla.

	DENTRO LA FINESTRA e non su tutta la curva: prima di `base` c'e' la rampa, che e' lenta per
	costruzione e che il regime gia' scarta. Misurarla qui vorrebbe dire ritrovarsi di nuovo con
	una costante al posto di un fatto.

	COME IL `_buco` DEL 240, NON DECIDE NIENTE: si scrive in archivio e basta. Cambiare insieme lo
	strumento e la regola che se ne serve renderebbe illeggibile il log della prossima tornata.
	"""
	try:
		if not curva or not base or not fine: return None
		if not riferimento or riferimento <= 0: return None
		_soglia = riferimento * FRAZIONE_AVVALLAMENTO
		_punti = [_p for _p in curva if base[0] <= _p[0] <= fine[0]]
		if not _punti or _punti[0][0] > base[0]: _punti.insert(0, base)
		if _punti[-1][0] < fine[0]: _punti.append(fine)
		_max, _corrente = 0.0, 0.0
		for _i in range(1, len(_punti)):
			_dt = _punti[_i][0] - _punti[_i - 1][0]
			if _dt <= 0: continue
			# `_ritmo` torna None quando non e' arrivato NIENTE: e' lo stallo, il caso peggiore,
			# e deve contare come sotto soglia -- non saltato.
			_r = _ritmo(_punti[_i - 1], _punti[_i])
			if _r is None or _r < _soglia:
				_corrente += _dt
				if _corrente > _max: _max = _corrente
			else:
				_corrente = 0.0
		return _max
	except: return None


def _stabile(seg):
	"""Il rapporto fra il ritmo della seconda meta' del tratto e quello della prima, o None.

	E' la stessa grandezza di `salita` (coda/centro), ma serve a un'altra domanda. Prima decideva
	QUALE dei due numeri dichiarare, e questo era il difetto: su una curva rumorosa il rapporto non
	distingue una rampa vera da uno stallo seguito da una raffica, e sbagliava fino a 3 volte in
	entrambi i versi (lotti 249-255). Adesso decide soltanto SE un tratto e' piatto -- e quando non
	lo e' si legge di piu', invece di indovinare.
	"""
	if len(seg) < 3: return None
	_m = _fino(seg, (seg[0][0] + seg[-1][0]) / 2.0)
	if _m is None or _m is seg[0] or _m is seg[-1]: return None
	_r1, _r2 = _ritmo(seg[0], _m), _ritmo(_m, seg[-1])
	if not _r1 or not _r2: return None
	return _r2 / _r1


def _tratto_stabile(curva, base_quando):
	"""Il tratto PIU' LUNGO che finisce con la curva, lungo almeno SECONDI_MINIMI e piatto. O None.

	Si cresce all'INDIETRO dalla fine, e questo generalizza le due regole della coda invece di
	sceglierne una: se la curva saliva, il tratto si ferma dove finisce la rampa e si dichiara
	l'altopiano (era `coda`); se calava e poi si e' assestata, si ferma dove finisce la discesa ed e'
	di nuovo l'altopiano (era `coda_in_calo`); se non c'e' nessun altopiano lungo abbastanza -- uno
	stallo, una raffica -- non si dichiara nessun tratto e si ripiega sulla media, che e' l'unico
	numero onesto quando un regime non c'e'.
	La prova su 46 curve vere: su linea pulita il numero non cambia di un decimale (33 curve), e i
	due casi che sapevamo sbagliati si raddrizzano -- 1,50 -> 6,46 con portata vera 5,73, e
	5,72 -> 17,23 con portata vera 17,9.
	"""
	try:
		_dentro = [_c for _c in curva if _c[0] >= base_quando]
		_migliore = None
		for _k in range(3, len(_dentro) + 1):
			_seg = _dentro[-_k:]
			if _seg[-1][0] - _seg[0][0] < SECONDI_MINIMI: continue
			_r = _stabile(_seg)
			if _r is not None and DISCESA_SOSPETTA <= _r <= SALITA_SOSPETTA: _migliore = _seg
		return _migliore
	except Exception: return None


def offset_per(dimensione):
	"""Dove aprire la lettura: fra FRAZIONE_MIN e FRAZIONE_MAX del file. Vedi le costanti."""
	try:
		if not dimensione: return 0
		return int(dimensione * uniform(FRAZIONE_MIN, FRAZIONE_MAX))
	except: return 0


def misura(url, offset=None, molla=None, lettore_classe=None, dimensione=None):
	"""Legge finche' la finestra oltre la rampa e' lunga SECONDI_REGIME. Non solleva mai.

	`molla` e' una funzione senza argomenti: quando torna True la lettura si abbandona (oltre il
	pavimento utile). Serve al servizio, che vive in un altro interprete e non condivide _FERMA.
	"""
	# Tutti i campi si dichiarano QUI, anche quelli che verranno riempiti in fondo: su un percorso
	# di errore la funzione esce prima, e chi legge il risultato non deve dover indovinare quali
	# chiavi esistono. None vuol dire 'non misurato', mai 'misurato zero'.
	fuori = {'ok': False, 'stato': None, 'ttfb': None, 'byte': 0, 'secondi': 0.0,
			 'lorda': None, 'regime': None, 'regime_secondi': 0.0, 'offset': offset,
			 'cdn': None, 'curva': [], 'chiuso': None, 'errore': None,
			 # LOTTO 240 -- la forma della curva, non solo la sua media. `regime` resta il numero
			 # che decide; questi dicono COME e' stato ottenuto, ed e' cio' che mancava per poter
			 # verificare una taratura invece di crederci.
			 'regime_media': None, 'regime_fonte': None, 'coda': None, 'centro': None,
			 # LOTTO 253 -- `instabilita` si DICHIARA qui, come tutti gli altri. La prima stesura la
			 # creava solo dentro il ramo del regime, quindi una sonda che non arriva a dichiarare
			 # un regime tornava un dizionario senza quella chiave: test_222 -- "il risultato
			 # dichiara tutti i suoi campi" -- l'ha presa subito. Chi legge un esito deve trovare
			 # le stesse chiavi sempre, altrimenti ogni lettore ha bisogno di un `.get` difensivo.
			 'salita': None, 'avvallamento': None, 'instabilita': None, 'campioni': 0,
			 # LOTTO 255 -- LA RADIO ACCANTO ALLA CURVA. Le 26 sonde in archivio si separano in due
			 # popolazioni senza sovrapposizione guardando `rete_segnale`: -55 dBm -> 40-48 Mbit/s,
			 # -69 dBm -> 1,5-14,8, CON GLI STESSI HOST CDN in entrambi i gruppi. Quindi non c'erano
			 # una linea veloce e una lenta, c'era una linea sola vista attraverso due stati della
			 # radio -- e le regole della coda scattano 4 volte su 8 a radio debole e 0 su 18 a
			 # radio sana, perche' `salita` a -55 dBm dista 0,056 da 1 e a -69 dista 0,298.
			 #
			 # DENTRO LA CURVA L'INFORMAZIONE NON C'E', ed e' provato: la curva sintetica di
			 # test_240 -- discesa progressiva verso un altopiano VERO, dove la coda e' la risposta
			 # giusta -- ha avvallamento 2,50, e il caso reale in cui la coda ha sbagliato di brutto
			 # (dichiarato 1,49 contro 5,73 di portata vera) ha 2,82. Stesso numero. Ne' `salita`,
			 # ne' `avvallamento`, ne' coda/media distinguono un rallentamento vero da un
			 # affievolimento del wi-fi: sono due cose che alla curva sembrano identiche.
			 # Per questo qui non si aggiunge NESSUNA regola -- si aggiunge una MISURA, che e' cio'
			 # che mancava. Vedi DISCESA_STALLO nel lotto 254 per cosa succede a fare il contrario.
			 'radio': [], 'rssi_inizio': None, 'rssi_fine': None, 'rssi_min': None,
			 'cpu': None, 'cpu_processo': None, 'quota': None, 'quando': None, 'censo': None,
			 'lettore': None, 'ripiego': None, 'ripiegato': 0,
			 't_apertura': None, 't_posizione': None, 't_primo': None,
			 'dimensione_attesa': dimensione, 'dimensione_vera': None}
	lettore = None
	try:
		t0 = perf_counter()
		fuori['cdn'] = _host(url)
		# L'offset PRIMA di aprire, se la dimensione la sappiamo gia': e' cio' che permette di
		# mettere la Range nella prima richiesta invece di aprire e poi cercare.
		if offset is None and dimensione: offset = offset_per(dimensione)
		lettore = _apri_lettore(url, offset, lettore_classe, fuori)
		fuori['lettore'] = lettore.__class__.__name__
		# LOTTO 258 -- in bacheca ci va la BANDIERA, non il messaggio: i campi sono separati
		# da '|' e il testo di un'eccezione non e' sotto il nostro controllo. Il perche' del
		# ripiego resta nel log, dove serve a leggere un caso; qui serve a contarli.
		fuori['ripiegato'] = 1 if fuori.get('ripiego') else 0
		# LOTTO 231 -- il ttfb spezzato in tre. Passando al lettore di Kodi e' salito da 0,6-1,1 s a
		# 1,5-3,4: sono secondi che l'utente paga SENZA misurare, e prima di rimediare bisogna sapere
		# quale dei tre pezzi li consuma. L'apertura e il posizionamento sono due giri di rete
		# distinti -- xbmcvfs non sa aprire gia' all'offset -- e il primo pezzo e' il terzo.
		fuori['t_apertura'] = (perf_counter() - t0) * 1000
		# L'offset lo decide la dimensione che il lettore dichiara: cosi' non serve conoscerla prima
		# e non si dipende da cosa c'e' in archivio.
		_t = perf_counter()
		if offset is None:
			offset = offset_per(getattr(lettore, 'dimensione', None))
		# LOTTO 240 -- FUORI dall'if. Dentro, sul ripiego da Python a Kodi, non veniva chiamato da
		# nessuno e la sonda leggeva dalla testa del file dichiarando l'offset che voleva: vedi
		# _LettoreKodi.posiziona. Il lettore torna l'offset EFFETTIVO, che e' quello che va in
		# archivio -- puo' differire da quello chiesto se la dimensione dichiarata mentiva.
		try:
			_effettivo = lettore.posiziona(offset)
			if _effettivo is not None: offset = _effettivo
		except: pass
		fuori['t_posizione'] = (perf_counter() - _t) * 1000
		fuori['offset'] = offset
		fuori['dimensione_vera'] = getattr(lettore, 'dimensione', None)
		_t = perf_counter()
		# Il ttfb resta un numero SEPARATO: e' latenza, non banda, e mescolarlo ai byte e' il modo
		# in cui la v1 sbagliava di 11-17 volte. Col lettore di Kodi comprende anche il primo pezzo,
		# perche' e' li' che la richiesta parte davvero -- e quel pezzo non si conta.
		if lettore.leggi(PASSO) <= 0:
			fuori['errore'] = 'nessun byte all apertura'
			return fuori
		fuori['t_primo'] = (perf_counter() - _t) * 1000
		fuori['ttfb'] = (perf_counter() - t0) * 1000
		fuori['stato'] = getattr(lettore, 'stato', 206)
		# LOTTO 246 -- E ASPETTANDO CHI. `cpu_processo` dice gia' che il processo era pieno mentre
		# noi eravamo fermi, ma non ha mai potuto dire per colpa di chi: l'11/09 due sonde su cinque
		# sono state buttate con la quota al 36% e al 54% e UN SOLO interprete Python vivo, quindi
		# la contesa non veniva da noi e il log taceva.
		#
		# PRIMA che il cronometro parta, e non e' un dettaglio: il censimento legge un file per
		# thread -- sessanta e piu' su Kodi -- e messo dopo `t1` quel costo finirebbe dentro
		# `trascorso` e dentro `cpu`, cioe' abbasserebbe la portata misurata e alzerebbe il consumo.
		# Uno strumento che sposta la misura a cui e' attaccato non serve a niente.
		try: _censo0, _censo_t0 = perf_modulo().censimento_cpu(), perf_counter()
		except Exception: _censo0, _censo_t0 = None, None
		letti, t1, prossimo = 0, perf_counter(), BUCKET
		trascorso, curva = 0.0, []
		# LOTTO 243 -- l'istante di `base` serve DENTRO il ciclo per sapere quando fermarsi, e si
		# calcola con la stessa regola che `_da(curva, SECONDI_SALITA)` applichera' dopo: il primo
		# campione a SECONDI_SALITA o oltre. Stessa regola in un posto solo, cosi' "ci si ferma
		# quando la finestra e' piena" e' una conseguenza e non una coincidenza fra due formule.
		_base = None
		# LAVORO O ATTESA. thread_time e' il tempo di CPU di QUESTO thread, process_time quello di
		# tutto il processo: insieme dicono quale delle tre spiegazioni regge, invece di sceglierla
		# a naso. Molta cpu propria = si sta decifrando e copiando, e il rimedio e' leggere a pezzi
		# piu' grossi. Poca cpu propria ma processo pieno = il GIL e' occupato dagli scraper e noi
		# aspettiamo il turno. Poca di entrambe = si aspetta la rete davvero.
		_cpu0, _proc0 = thread_time(), process_time()
		# LOTTO 255 -- il primo campione PRIMA del ciclo, cosi' la serie comincia insieme al
		# cronometro e non al primo bucket. `stato_rete` legge /proc/net/wireless: un file di tre
		# righe, qualche decina di microsecondi. Dodici letture su sei secondi sono lo 0,007% della
		# finestra -- sotto qualunque soglia che conti -- ed e' la ragione per cui questo campione
		# puo' stare DENTRO il ciclo cronometrato mentre il censimento dei thread (un file per
		# thread, sessanta e piu') ha dovuto stare fuori.
		radio = []
		_r = stato_rete()[1]
		if _r is not None: radio.append((0.0, _r))
		while True:
			# LOTTO 243 -- l'errore di lettura si prende QUI, non dall'except in fondo.
			#
			# Senza il tetto a orologio, il timeout del socket diventa il modo NORMALE in cui una
			# sonda su linea rotta finisce. Ma l'except in fondo alla funzione salta tutto il
			# calcolo del regime: una sonda che avesse gia' i suoi cinque secondi buoni in mano li
			# butterebbe via per l'ultima lettura andata a vuoto. Qui invece si chiude il ciclo come
			# per qualunque altro motivo, e cio' che e' stato letto resta una misura -- che e' lo
			# stesso principio per cui `chiuso` esiste.
			try:
				quanti = lettore.leggi(PASSO)
			except Exception as _e:
				fuori['chiuso'] = 'lettura interrotta (%s)' % type(_e).__name__
				break
			if not quanti:
				fuori['chiuso'] = 'fine del flusso'
				break
			letti += quanti
			trascorso = perf_counter() - t1
			if trascorso >= prossimo:
				curva.append((trascorso, letti))
				# LOTTO 255 -- la radio si campiona QUI e non nella curva: `curva` e' fatta di
				# coppie (secondi, byte) e ci sono tre funzioni che indicizzano `[0]` e `[1]` su di
				# lei. Una lista parallela non tocca niente di cio' che gia' funziona.
				_r = stato_rete()[1]
				if _r is not None: radio.append((trascorso, _r))
				if _base is None and trascorso >= SECONDI_SALITA: _base = trascorso
				# LOTTO 240 -- un bucket DA ADESSO, non il prossimo confine della griglia. Se una
				# lettura dura piu' di un bucket -- uno stallo: l'11/09 la riga 16 ha prodotto 7
				# campioni per 6,4 s di lettura -- `prossimo += BUCKET` lasciava la soglia indietro
				# e i giri successivi campionavano a raffica per recuperare, falsando la forma
				# della curva proprio nel punto che c'era da leggere.
				# Nemmeno risalire alla griglia basta: il confine successivo puo' cadere venti
				# millisecondi dopo lo stallo, e allora la raffica e' di un campione solo ma c'e'
				# lo stesso (misurato: campioni a 3,48 s e 3,53 s). La griglia non serve piu' a
				# nessuno da quando la curva porta i propri tempi -- serve solo che due campioni
				# distino almeno un bucket, e questo lo garantisce.
				prossimo = trascorso + BUCKET
			# LOTTO 257 -- LA FINESTRA E' ADATTIVA. Prima si leggeva SECONDI_REGIME e basta: su linea
			# pulita erano secondi spesi per confermare cio' che era gia' evidente, su linea che
			# ancora saliva erano troppo pochi e la media usciva diluita dalla rampa -- che e' il
			# problema che le regole della coda tamponavano. Adesso si smette quando c'e' un tratto
			# piatto lungo abbastanza, e se non arriva si legge fino a SECONDI_MASSIMI.
			if _base is not None and trascorso - _base >= SECONDI_MINIMI:
				if _tratto_stabile(curva, _base) is not None:
					fuori['chiuso'] = 'regime stabile raggiunto'
					break
				if trascorso - _base >= SECONDI_MASSIMI:
					fuori['chiuso'] = 'tetto di tempo senza un regime stabile'
					break
			if letti >= BYTE_MASSIMI:
				fuori['chiuso'] = 'tetto di byte'
				break
			if molla is not None and molla():
				fuori['chiuso'] = 'abbandonata: ricerca annullata'
				break
		fuori['byte'], fuori['secondi'], fuori['curva'] = letti, trascorso, curva
		fuori['radio'] = radio
		fuori['cpu'] = thread_time() - _cpu0
		fuori['cpu_processo'] = process_time() - _proc0
		# Si chiude PRIMA di quota_cpu(), che brucia cpu di proposito: comprenderla nel censimento
		# vorrebbe dire vedere noi stessi in cima all'elenco dei colpevoli.
		#
		# La finestra e' quella VERA fra i due censimenti, non `trascorso`: i due non coincidono --
		# il primo censimento sta prima del cronometro -- e usare il numero sbagliato gonfierebbe
		# tutte le percentuali senza che si veda.
		try:
			if _censo0 is not None:
				_censo_parete = perf_counter() - _censo_t0
				_censo1 = perf_modulo().censimento_cpu()
				# LOTTO 247 -- i thread PRONTI ai due estremi della finestra. Due campioni non sono
				# una serie e non lo fingo: dicono se la macchina era contesa all'inizio, alla fine,
				# o tutte e due le volte. La serie fitta la tiene il servizio, che campiona ogni 2 s.
				_pr = 'pronti %s all\'inizio, %s alla fine' % (_censo0[3], _censo1[3]) \
					  if (len(_censo0) > 3 and _censo1 and len(_censo1) > 3) else None
				# LOTTO 252 -- e ANCHE GLI FPS, che e' la domanda aperta sulla sonda.
				# Il costo della GUI si converte in frequenza: dimezzato il lavoro per fotogramma
				# (lotto 251) Kodi e' passato da 30 a 50 fotogrammi al secondo e la cpu e' scesa
				# solo del 20%. Quindi "quanto disturbo ha avuto la sonda" non e' una percentuale
				# di core, e' un numero di fotogrammi: Kodi disegna su richiesta -- col video a
				# schermo intero fa esattamente 23-24, cioe' il ritmo del film -- e durante la
				# ricerca ne fa 43-52, che e' il numero da spiegare.
				# Costa una lettura di infolabel, e mette quota e fotogrammi sulla STESSA riga,
				# che e' l'unico modo per correlarli fra sessioni diverse.
				fuori['censo'] = perf_modulo().divario_cpu(
					_censo0, _censo1, _censo_parete, pronti=_pr, fps=perf_modulo().fps())
		except Exception: pass
		# LOTTO 228 -- l'istante della misura e' la fine della LETTURA, non la fine della funzione.
		# quota_cpu() qui sotto puo' bruciare fino a QUOTA_ATTESA_MAX, e timbrando dopo di lei la
		# sonda risultava piu' vecchia di quanto fosse: sulla riga 2 del 10/09 `sonda_eta` e' uscita
		# **-1**, cioe' una misura presa dopo la riproduzione che doveva descrivere.
		fuori['quando'] = adesso()
		# La quota si rilegge DOPO, non prima: quella prima dice se valeva la pena partire, questa
		# dice se cio' che abbiamo letto e' una misura della linea o una misura di noi stessi.
		fuori['quota'] = quota_cpu()
		if letti <= 0 or trascorso <= 0:
			fuori['errore'] = 'nessun byte letto'
			return fuori
		fuori['ok'] = True
		fuori['lorda'] = (letti * 8.0) / trascorso / 1000000.0
		# REGIME: solo il tratto dopo la salita. Se non si e' andati abbastanza oltre la salita non
		# c'e' nessun regime da dichiarare e si lascia None -- 'non misurato' non e' 'misurato zero',
		# ed e' la distinzione che nei lotti 191-198 e' costata due sonde.
		base = _da(curva, SECONDI_SALITA)
		# Chi ha annullato non vuole una misura: si esce senza regime, e il motivo resta leggibile.
		_fine = None if (fuori['chiuso'] or '').startswith('abbandonata') else (trascorso, letti)
		fuori['campioni'] = len(curva)
		if base and _fine and _fine[0] - base[0] >= SECONDI_MINIMI:
			fuori['regime_media'] = _ritmo(base, _fine)
			# Contro la MEDIA e non contro cio' che verra' dichiarato: vedi FRAZIONE_AVVALLAMENTO.
			fuori['avvallamento'] = _avvallamento(curva, base, _fine, fuori['regime_media'])
			# LOTTO 253 -- la frazione di finestra passata in avvallamento, calcolata QUI perche' e'
			# l'unico punto in cui si ha la finestra PIENA. Sotto, le regole della coda riscrivono
			# `regime_secondi` con la durata della sola coda (2-3 s): dividere per quella darebbe
			# il 90% su una riga in cui l'avvallamento copriva il 36% della misura vera.
			_finestra = _fine[0] - base[0]
			fuori['instabilita'] = (fuori['avvallamento'] / _finestra) if _finestra > 0 else 0.0
			# LOTTO 255 -- sulla STESSA finestra su cui si calcolano media, centro e coda, per la
			# stessa ragione per cui `instabilita` si calcola qui: un numero che descrive un altro
			# intervallo non si puo' mettere accanto a `salita` e confrontare.
			# Solo tre valori in archivio, non la serie: `rssi_inizio`/`rssi_fine` sono l'andamento
			# -- confrontabili riga per riga con `salita`, che e' anche lui un prima/dopo -- e
			# `rssi_min` dice se c'e' stato un tuffo in mezzo, che due estremi da soli perdono.
			# La serie intera va nel log, dove si fa l'analisi; in archivio starebbe stretta e non
			# risponderebbe a una domanda in piu'.
			_dentro = [_v for _t, _v in radio if base[0] <= _t <= _fine[0]]
			if _dentro:
				fuori['rssi_inizio'], fuori['rssi_fine'] = _dentro[0], _dentro[-1]
				fuori['rssi_min'] = min(_dentro)
			# LOTTO 257 -- IL NUMERO VIENE DAL TRATTO PIATTO, non dalla finestra intera ne' da una
			# delle sue meta'. `media` resta in archivio come diagnosi: e' cio' che il codice di
			# prima avrebbe dichiarato, e serve a misurare quanto questo lotto ha cambiato invece
			# di crederci.
			_tratto = _tratto_stabile(curva, base[0])
			if _tratto:
				fuori['regime'], fuori['regime_fonte'] = _ritmo(_tratto[0], _tratto[-1]), 'stabile'
				fuori['regime_secondi'] = _tratto[-1][0] - _tratto[0][0]
			else:
				# Nessun altopiano: la media e' l'unico numero onesto, e `instabilita` fa allargare
				# il margine (lotto 253). La fonte lo dichiara, cosi' dal log si distingue una
				# misura presa su una linea ferma da una presa su una linea che ballava.
				fuori['regime'], fuori['regime_fonte'] = fuori['regime_media'], 'media_instabile'
				fuori['regime_secondi'] = _finestra
			# LOTTO 240 -- LA CURVA STA ANCORA SALENDO? Il tratto finale contro quello centrale.
			# `_fino` e non `_da`: la coda deve essere lunga ALMENO SECONDI_CODA, non al piu'. Con
			# `_da` la riga 15 dell'11/09 perdeva il bucket piu' veloce dentro il centro e il
			# rapporto usciva 1,03 invece di 1,56 -- cioe' la correzione non sarebbe scattata
			# proprio dove serviva.
			# LOTTO 257 -- coda, centro e salita restano CALCOLATE ma non decidono piu' niente.
			# Sono la diagnosi: permettono di rileggere una riga vecchia con lo stesso metro e di
			# verificare a posteriori che il tratto piatto sia stato scelto bene. Le due regole che
			# stavano qui -- `coda` e `coda_in_calo` -- sono state ritirate: su 8 accensioni note
			# 3 giuste, 1 innocua e 4 dannose, con errori fino a 3 volte in ENTRAMBI i versi, mentre
			# la media nuda non ha mai sbagliato piu' di 1,4 volte e sempre dal lato sicuro.
			# Il loro scopo era giusto (la rampa diluisce la media) ma lo strumento no: coda/centro
			# non distingue una rampa da uno stallo seguito da una raffica. Vedi _tratto_stabile,
			# che risolve lo stesso problema leggendo di piu' invece di scegliere fra due numeri.
			_inizio_coda = _fino(curva, _fine[0] - SECONDI_CODA)
			if _inizio_coda and _inizio_coda[0] >= base[0]:
				fuori['coda'] = _ritmo(_inizio_coda, _fine)
				fuori['centro'] = _ritmo(base, _inizio_coda)
				if fuori['coda'] and fuori['centro']:
					fuori['salita'] = fuori['coda'] / fuori['centro']
		# INVARIANTE, nello spirito di portata_secchi: una lettura fatta senza cpu NON e' una misura
		# della linea, e non deve poter arrivare al wizard travestita da tale. Il 10/09 due sonde
		# hanno dichiarato 26,0 e 8,0 Mbit/s su una linea da 43: la prima aveva il 25% di un core, la
		# seconda il 10%, e i due numeri sono esattamente 0,25 e 0,10 del tetto di decifratura.
		_perche = _limitata_da_cpu(fuori)
		if _perche:
			# `regime_fonte` cade con `regime` (lotto 240): non e' stata dichiarata ne' la media ne'
			# la coda, non e' stato dichiarato niente. Media, centro e coda invece RESTANO -- sono
			# la diagnosi di cosa e' successo, ed e' proprio quando la misura si butta che servono.
			fuori['regime'], fuori['regime_secondi'], fuori['regime_fonte'] = None, 0.0, None
			fuori['errore'] = _perche
	except Exception as e:
		fuori['errore'] = '%s: %s' % (type(e).__name__, e)
	finally:
		# Sempre, e senza drenare: si abbandona il resto del file invece di scaricarlo. Un lettore
		# lasciato aperto tiene un socket e, con quello di Kodi, una CCurlFile.
		try:
			if lettore is not None: lettore.chiudi()
		except: pass
	return fuori


def misura_sorgente(url, molla=None, dimensione=None):
	"""Misura la linea sul link appena risolto e pubblica il risultato. Restituisce l'esito.

	E' l'unico ingresso: la chiama sources.process_results sulla prima sorgente in cache dell'ordine
	di autoplay, subito prima di applicare il filtro della dimensione.
	"""
	if not url:
		_riga_log('non eseguita: nessun link da sondare')
		return None
	esito = misura(url, None, molla, dimensione=dimensione)
	esito.setdefault('quando', adesso())
	pubblica(esito)
	_registra_log(esito, None)
	return esito


def _perche_margine(instabilita, fonte):
	"""Il pezzo di riga che dice PERCHE' il margine non e' quello di base. Vuoto se lo e'.

	Senza, una soglia piu' severa del solito sarebbe indistinguibile da un bug: il log deve poter
	dire da solo che quel numero viene da una linea instabile e non da un conto sbagliato.
	"""
	try:
		# LOTTO 259 -- si chiede il margine PRIMA di leggerne la spiegazione, invece di fidarsi che
		# qualcuno l'abbia gia' calcolato: `soglia()` le mette nella stessa riga di formato e oggi
		# l'ordine di valutazione basta, ma e' una garanzia che non deve dipendere da dove la si
		# scrive. Costa niente: il valore e' in memoria dopo la prima volta.
		_margine_base()
		_d = ', misurato su %s' % _MARGINE_BASATO_SU if _MARGINE_BASATO_SU else ''
		# LOTTO 257 -- 'media_instabile' e' la nuova fonte di ripiego e va penalizzata come 'media'.
		# 'media' resta per le righe in archivio scritte prima di questo lotto.
		if fonte not in ('media', 'media_instabile') or not instabilita: return _d
		return _d + (', linea instabile: %.0f%% della finestra in avvallamento' % (instabilita * 100))
	except: return ''


_MARGINE_CACHE = None
_MARGINE_BASATO_SU = None


def _margine_base():
	"""MARGINE, o il valore misurato sull'archivio quando ce n'e' abbastanza per dirlo.

	Non solleva e non blocca mai: qualunque cosa vada storta si torna alla costante, cioe' al
	comportamento di prima di questo lotto. Il risultato si tiene per la durata dell'interprete --
	`soglia()` chiama `margine_per` tre volte per giro, e l'archivio non cambia nel frattempo.
	"""
	global _MARGINE_CACHE
	global _MARGINE_BASATO_SU
	try:
		if _MARGINE_CACHE is not None: return _MARGINE_CACHE
		# I due globali si azzerano INSIEME: separarli lascerebbe la spiegazione di un calcolo
		# riuscito accanto a un margine che invece e' ripiegato sulla costante, e il log direbbe
		# una cosa falsa proprio nel caso in cui serve a capire cosa e' successo.
		_MARGINE_CACHE, _MARGINE_BASATO_SU = MARGINE, None
		from caches.playback_stats import recenti, margini_necessari, righe_giudicabili
		_righe = recenti()
		if righe_giudicabili(_righe) < RIGHE_MINIME_MARGINE: return _MARGINE_CACHE
		_n = margini_necessari(_righe)
		if len(_n) < STALLI_MINIMI_MARGINE: return _MARGINE_CACHE
		# `_n` cresce: tollerarne k vuol dire lasciar passare i k piu' esigenti, quindi si prende
		# il primo escluso partendo dal fondo.
		_i = len(_n) - 1 - max(0, int(STALLI_TOLLERATI))
		if _i < 0: return _MARGINE_CACHE
		_MARGINE_CACHE = max(MARGINE, min(MARGINE_MASSIMO, _n[_i] + MARGINE_EPSILON))
		# Senza questa riga nel log, una soglia improvvisamente severa e' indistinguibile da un
		# guasto: deve poter dire da sola su quante riproduzioni e quanti stalli si e' basata.
		_MARGINE_BASATO_SU = '%d riproduzioni, %d a secco' % (righe_giudicabili(_righe), len(_n))
	except: pass
	return _MARGINE_CACHE


def margine_per(instabilita=0.0, fonte=None):
	"""Il margine da usare per QUESTA misura. MARGINE se la misura non e' sospetta.

	Cresce con l'instabilita' e SOLO sulla media nuda: vedi PESO_INSTABILITA per il perche' e per il
	caso che lo ha imposto. `fonte` None vuol dire "non lo so" -- e' il caso dell'archivio, dove la
	mediana di molte sonde ha gia' mediato la varianza -- e li' non si penalizza.
	"""
	try:
		# LOTTO 257 -- vale per 'media' (righe in archivio di prima) e per 'media_instabile' (la
		# nuova fonte di ripiego). Il tratto 'stabile' NON si penalizza: la sua piattezza e' stata
		# verificata, non supposta -- ed e' la differenza rispetto al lotto 253, dove l'esenzione
		# delle fonti della coda era un'ipotesi.
		_b = _margine_base()
		if fonte not in ('media', 'media_instabile') or not instabilita: return _b
		return _b * (1.0 + PESO_INSTABILITA * max(0.0, min(1.0, float(instabilita))))
	except: return MARGINE


def line_speed_da(capacita, instabilita=0.0, fonte=None):
	"""La soglia da applicare al filtro, a partire dalla capacita' misurata. None se non c'e'.

	Una riga sola, ed e' il punto d'arrivo di tutta la fase 4: `line_speed = capacita / margine`.
	"""
	try:
		return (capacita / margine_per(instabilita, fonte)) if capacita else None
	except: return None


# LOTTO 242 -- UNA SOLA DEFINIZIONE DELLA SOGLIA, e prima erano due che divergevano.
#
# `sources._line_speed` guardava solo la misura della ricerca in corso e poi l'impostazione;
# `player._linea_utile` guardava la bacheca senza nessun limite d'eta' e poi l'impostazione. I due
# cancelli decidevano sullo stesso film con numeri diversi ogni volta che la sonda non partiva --
# e il 10/09 e' successo: le righe 12 e 13 sono state giudicate dal player con una misura di
# QUATTRO MINUTI prima presa su un altro titolo, mentre il filtro delle dimensioni, nella stessa
# ricerca, usava l'impostazione scritta a mano.
#
# LA SCALA, dal piu' fresco al piu' vecchio, e ogni gradino e' una misura vera finche' si puo':
#   1. la sonda di QUESTA ricerca -- misurata adesso, sulla sorgente che sta per partire;
#   2. la bacheca, se non e' piu' vecchia di ETA_BACHECA -- e' l'ultima sonda buona di questa
#      sessione di Kodi, quindi la stessa rete e (quasi sempre) lo stesso nodo;
#   3. l'archivio: la mediana delle portate misurate nelle ultime ore. Sopravvive al riavvio, ed e'
#      il gradino che mancava -- l'11/09 alle 04:30 la bacheca era vuota perche' Kodi era appena
#      partito, e si e' caduti dritti sull'impostazione;
#   4. l'impostazione. Che NON e' un pavimento prudente: su questa stick vale 50 su una linea da
#      12-20, ed e' il numero che ha lasciato passare il film dei 94 secondi a secco.
#
# ETA_BACHECA e' un giudizio, e lo dico: dieci minuti sono "questa navigazione". Piu' in la' una
# mediana di molte misure (gradino 3) descrive la linea meglio di un singolo punto vecchio.
ETA_BACHECA = 600


# LOTTO 250 -- I QUATTRO MODI DI `results.filter_size_method`, e perche' la sonda ne vuole uno suo.
#
# Fino al 249 la sonda partiva SEMPRE: nessuno dei tre punti che la avviano guardava questa
# impostazione. Chi aveva il filtro su Off o su Use Size pagava lo stesso i cinque-sei secondi di
# lettura a ogni riproduzione e non ne otteneva niente -- il cancello del player esce subito con
# 'cancello banda non attivo' per i modi 0 e 2, e `filter_results` non chiama `_line_speed`.
# Costo puro, per la maggioranza degli utenti.
#
# I tre modi esistenti restano quello che sono e NON cambiano comportamento. Il quarto e' nuovo:
#   0 Off        nessun filtro sulla dimensione
#   1 Use Line Speed   il tetto si calcola sul numero SCRITTO A MANO in results.line_speed
#   2 Use Size   il tetto e' una dimensione fissa in MB
#   3 Auto       il tetto si calcola sulla linea MISURATA dalla sonda poco prima di riprodurre
#
# Il 3 si aggiunge IN CODA, non si rinumera: i valori gia' salvati sui dispositivi continuano a
# significare la stessa cosa e non serve nessuna migrazione.
#
# La distinzione fra 1 e 3 e' esattamente quella che l'utente paga: col 1 il numero e' fisso e la
# riproduzione parte subito, col 3 il numero e' vero e costa l'attesa della sonda. E' una scelta
# sua, e prima non gliela stavamo dando.
MODO_OFF, MODO_LINEA, MODO_DIMENSIONE, MODO_AUTO = 0, 1, 2, 3


def modo():
	"""Il valore di results.filter_size_method, come intero. MODO_OFF se illeggibile.

	Nel dubbio si torna OFF e non AUTO: un'impostazione che non si riesce a leggere non e' un
	consenso a spendere sei secondi dell'utente a ogni riproduzione.
	"""
	try:
		from caches.settings_cache import get_setting
		return int(get_setting('fenlight.results.filter_size_method', '0') or 0)
	except: return MODO_OFF


def soglia(capacita_corrente=None, instabilita=0.0, fonte=None):
	"""(Mbit/s, da dove viene). L'UNICO posto in cui si decide la soglia del filtro.

	La provenienza si restituisce perche' finisca nel log: senza, una riga di scarto non dice se il
	numero contro cui la sorgente e' stata giudicata era misurato adesso, misurato prima o scritto a
	mano, e non si puo' piu' verificare a posteriori se il cancello ha tolto roba buona.

	LOTTO 250 -- LA SCALA E' DEL MODO AUTO, e sta qui e non nei due chiamanti per la ragione del
	lotto 242: il filtro dell'elenco e il cancello del player devono giudicare lo stesso film con
	lo STESSO numero. Mettendo la distinzione dentro l'unica funzione che decide, restano d'accordo
	per costruzione invece che per convenzione.

	Col modo 1 il numero e' l'impostazione e basta: l'utente ha chiesto un valore fisso, e servirgli
	una mediana dell'archivio al posto suo sarebbe disattendere proprio la scelta che ha fatto.
	"""
	if modo() == MODO_LINEA: return _impostati()
	_v = line_speed_da(capacita_corrente, instabilita, fonte)
	if _v: return _v, ('dalla sonda (%.1f Mbit/s misurati / %.2f%s)'
					   % (capacita_corrente, margine_per(instabilita, fonte),
						  _perche_margine(instabilita, fonte)))
	try:
		_m = letta()
		if _m and _m.get('regime'):
			_eta = adesso() - (_m.get('quando') or 0)
			# L'instabilita' viaggia in bacheca insieme alla misura: il cancello del player legge di
			# qui, e senza di lei giudicherebbe la stessa sonda con un margine diverso dal filtro --
			# esattamente la divergenza che il lotto 242 aveva chiuso.
			_i, _f = _m.get('instabilita') or 0.0, _m.get('regime_fonte')
			_v = line_speed_da(_m['regime'], _i, _f)
			if _v and 0 <= _eta <= ETA_BACHECA:
				return _v, ('dalla bacheca (%.1f Mbit/s di %.0f s fa / %.2f%s)'
							% (_m['regime'], _eta, margine_per(_i, _f), _perche_margine(_i, _f)))
	except: pass
	try:
		from caches.playback_stats import capacita_recente
		_c = capacita_recente()
		_v = line_speed_da(_c)
		if _v: return _v, 'dall\'archivio (%.1f Mbit/s, mediana delle sonde recenti / %.2f)' % (_c, MARGINE)
	except: pass
	return _impostati()


def _impostati():
	try:
		from caches.settings_cache import get_setting
		return float(get_setting('results.line_speed', '25') or 25), 'impostati'
	except: return 0.0, 'impostati'


# LOTTO 244 -- LO STATO DEL LINK, perche' ogni stranezza di questa indagine e' finita li'.
#
# Il 10/09 la linea faceva 44 Mbit/s, l'11/09 alle 03:20 ne faceva 10, alle 13:57 di nuovo 46. Ogni
# volta la spiegazione era la stessa e stava fuori dal nostro codice:
#
#     5 GHz  BSSID ...fa:55  RSSI -72   ("acceptable but not qualified", dice Android)
#     2,4 GHz BSSID ...fa:51 RSSI -55
#
# E ogni volta l'ho scoperto chiedendolo a mano con `dumpsys wifi`, DOPO. In archivio non c'era,
# quindi una riga di ieri non era interpretabile senza di me. Questa colonna chiude quel buco.
#
# DA DOVE. `/proc/net/wireless` e' l'unica fonte che il processo di Kodi puo' leggere su questo
# dispositivo, ed e' verificato non supposto: il file e' 0444 con contesto `proc_net`, e Android 9
# (SDK 28) non applica ancora la restrizione su /proc/net introdotta dalla 10. Il sysfs
# (/sys/class/net/wlan0/) risponde "Permission denied" su tutto, e `dumpsys` a un'app non e'
# accessibile. Se un giorno girasse su Android 10+ la lettura fallisce e le colonne restano NULL --
# che e' il comportamento giusto: "non misurato", mai "misurato zero".
#
# COSA NON SI PUO' AVERE, e va detto perche' e' proprio il dato piu' esplicativo: la BANDA. Non sta
# in /proc/net/wireless, il MAC del gateway in /proc/net/arp e' quello del router (...fa:50) e non
# il BSSID della radio, e il resto e' chiuso. Resta il livello, che su questo apparecchio le due
# bande le separa comunque: -55 sul 2,4 GHz contro -72 sul 5 GHz.
def stato_rete():
	"""(qualita', livello in dBm) del link wi-fi, o (None, None) se non si legge."""
	try:
		with open('/proc/net/wireless') as _f:
			for _riga in _f:
				_p = _riga.split()
				# le due righe d'intestazione non hanno il nome dell'interfaccia con i due punti
				if len(_p) < 4 or not _p[0].endswith(':'): continue
				if _p[0].startswith('p2p'): continue     # l'interfaccia wi-fi diretta, sempre a zero
				return float(_p[2].rstrip('.')), float(_p[3].rstrip('.'))
	except: pass
	return None, None


def _mb(byte):
	return (byte or 0) / 1048576.0


def _riga_log(testo):
	try:
		from modules.perf import log as perf_log
		perf_log('FenLight PERF SONDA', testo)
	except: pass


def _registra_log(esito, nota):
	try:
		from modules.perf import log as perf_log
		if esito is None:
			perf_log('FenLight PERF SONDA', 'non eseguita: %s' % nota)
			return
		if not esito['ok']:
			perf_log('FenLight PERF SONDA', 'FALLITA su %s (%s)'
					 % (esito['cdn'] or '?', esito['errore'] or '?'))
			return
		if esito.get('ripiego'):
			perf_log('FenLight PERF SONDA', 'lettore di Kodi non disponibile, si ripiega su Python '
					 '(%s): il tetto di cpu scende a ~82 Mbit/s' % esito['ripiego'])
		if esito.get('dimensione_vera') and esito.get('dimensione_attesa'):
			_sc = abs(esito['dimensione_vera'] - esito['dimensione_attesa']) / float(esito['dimensione_vera'])
			if _sc > 0.05:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE dimensione: lo scraper diceva %.2f GB, '
						 'il cdn ne dichiara %.2f GB'
						 % (esito['dimensione_attesa'] / 1073741824.0,
							esito['dimensione_vera'] / 1073741824.0))
		perf_log('FenLight PERF SONDA', '  attesa apertura %.0f ms + posizione %.0f ms + primo pezzo %.0f ms'
				 % (esito.get('t_apertura') or 0, esito.get('t_posizione') or 0, esito.get('t_primo') or 0))
		perf_log('FenLight PERF SONDA', '%s | %s | offset %.2f GB | ttfb %4.0f ms | %.1f MB in %.1f s | '
				 'lorda %.2f | REGIME %s Mbit/s [%s] su %.1f s (%s)'
				 % (esito['cdn'] or '?', (esito.get('lettore') or '?').replace('_Lettore', ''),
					esito['offset'] / 1073741824.0, esito['ttfb'] or 0,
					_mb(esito['byte']), esito['secondi'], esito['lorda'],
					'%.2f' % esito['regime'] if esito['regime'] else '?',
					esito.get('regime_fonte') or '-',
					esito['regime_secondi'],
					esito['chiuso'] or '?'))
		# La curva serve a VERIFICARE la taratura di SECONDI_SALITA invece di crederci: se i primi
		# passi sono molto piu' bassi degli altri la rampa e' quella, e se non lo sono va accorciata.
		#
		# LOTTO 240 -- COL TEMPO ACCANTO AL VALORE. Senza, una curva con bucket saltati e'
		# illeggibile: l'11/09 la riga 16 ha stampato 7 campioni per 6,4 s di lettura e non c'era
		# modo di sapere DOVE stesse il buco, che era l'unica cosa che quella riga avesse da dire.
		# Le righe 14 e 15 le ho potute ricostruire solo perche' 12 campioni in 6,1 s implicano il
		# passo 0,5: una fortuna, non un metodo.
		if esito['curva']:
			perf_log('FenLight PERF SONDA', '  curva  %s'
					 % ' '.join('%.1f:%.1f' % (_t, _mb(_b)) for _t, _b in esito['curva']))
			# La riga che rende il lotto 240 verificabile da solo: c'e' sempre la media che il
			# codice di prima avrebbe dichiarato, accanto a cio' che si e' dichiarato adesso.
			_n = lambda _v, _f='%.2f': (_f % _v) if _v is not None else '?'
			perf_log('FenLight PERF SONDA', '  forma  media %s | centro %s | coda %s Mbit/s | '
					 'coda/centro %s (piatto fra %.2f e %.2f) -> dichiarata: %s | %s campioni, '
					 'avvallamento %s s (sotto il %.0f%% della media)'
					 % (_n(esito.get('regime_media')), _n(esito.get('centro')), _n(esito.get('coda')),
						# LOTTO 252 -- TRE decimali, e non e' pignoleria. Il 12/09 la riga ha stampato
						# `coda/centro 0.89 (soglie 1.12 alta / 0.89 bassa) -> dichiarata: media`, che
						# si legge come una regola che non e' scattata sulla propria soglia. Il valore
						# vero era 0,8930 e la regola ha fatto benissimo a non scattare, ma a due
						# decimali i due casi sono indistinguibili -- e sarebbe stata una caccia al
						# fantasma dentro un log di due mesi fa.
						_n(esito.get('salita'), '%.3f'), SALITA_SOSPETTA, DISCESA_SOSPETTA,
						esito.get('regime_fonte') or 'nessuna (misura buttata)',
						esito.get('campioni'), _n(esito.get('avvallamento'), '%.1f'),
						FRAZIONE_AVVALLAMENTO * 100))
		# LOTTO 255 -- LA RADIO, sotto la curva e con gli stessi tempi, perche' la domanda e' se i
		# due andamenti coincidono e si risponde guardandoli incolonnati. La serie sta SOLO qui: in
		# archivio ci vanno i tre riassunti sulla finestra di regime.
		# Vuota vuol dire che /proc/net/wireless non si e' letto -- ethernet, o non Android -- e non
		# vuol dire segnale zero: la riga allora non si stampa affatto.
		# LOTTO 257 -- quanto e' lungo il tratto che ha deciso, e quanto si e' letto in tutto. Senza,
		# `regime_secondi` in archivio non si sa se sia una finestra intera o un altopiano ritagliato.
		if esito.get('regime_fonte'):
			perf_log('FenLight PERF SONDA', '  finestra  dichiarati %.1f s di %.1f s letti (%s)%s'
					 % (esito.get('regime_secondi') or 0, esito.get('secondi') or 0,
						esito['regime_fonte'],
						' -- nessun tratto piatto lungo almeno %.0f s' % SECONDI_MINIMI
						if esito['regime_fonte'] == 'media_instabile' else ''))
		if esito.get('radio'):
			_r = [_v for _t, _v in esito['radio']]
			perf_log('FenLight PERF SONDA', '  radio  %s'
					 % ' '.join('%.1f:%.0f' % (_t, _v) for _t, _v in esito['radio']))
			perf_log('FenLight PERF SONDA', '  segnale nella finestra di regime: %s -> %s dBm '
					 '(minimo %s) | sull intera lettura %.0f .. %.0f, escursione %.0f dB'
					 % (_n(esito.get('rssi_inizio'), '%.0f'), _n(esito.get('rssi_fine'), '%.0f'),
						_n(esito.get('rssi_min'), '%.0f'), min(_r), max(_r), max(_r) - min(_r)))
		if esito.get('cpu') is not None and esito['secondi'] > 0:
			_consumo = esito['cpu'] / esito['secondi']
			_quota = esito.get('quota')
			_tetto = (esito['byte'] * 8.0 / esito['cpu'] / 1000000.0) if esito['cpu'] else 0
			perf_log('FenLight PERF SONDA', '  cpu    consumo %.0f%% | quota %s | processo %.0f%% | '
					 'tetto %.0f Mbit/s con un core intero (%.0f ms per MB)'
					 % (_consumo * 100, ('%.0f%%' % (_quota * 100)) if _quota is not None else '?',
						esito['cpu_processo'] / esito['secondi'] * 100, _tetto,
						esito['cpu'] / (esito['byte'] / 1048576.0) * 1000 if esito['byte'] else 0))
		# LOTTO 246 -- chi ha consumato la cpu DURANTE la lettura. La riga sopra dice quanta ne e'
		# stata usata, questa dice da chi: senza, una sonda buttata per quota bassa resta un fatto
		# senza causa e non si puo' lavorare sulla causa.
		if esito.get('censo') and esito['censo'][0]:
			perf_log('FenLight PERF SONDA', '  chi      %s' % esito['censo'][0])
			perf_log('FenLight PERF SONDA', '           %s' % esito['censo'][1])
			# Il numero che dice se abbiamo misurato la linea o il muro.
			if _consumo > CONSUMO_SOSPETTO:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE consumo al %.0f%% di un core: il regime '
						 'e un MINIMO, la linea puo essere piu veloce' % (_consumo * 100))
			elif esito.get('lettore') == '_LettorePython' and _quota and _consumo / _quota > CONSUMO_SOSPETTO:
				perf_log('FenLight PERF SONDA', '  ATTENZIONE consumata il %.0f%% della quota di GIL: '
						 'il regime e un MINIMO' % (_consumo / _quota * 100))
	except: pass


# ---- la bacheca ---------------------------------------------------------------------------------
# LOTTO 225 -- chi MISURA e chi USA la misura non sono piu' lo stesso interprete. La sonda vive nel
# servizio, dove puo' aspettare un momento con un core libero; il player, che scrive la riga in
# archivio, e' un'invocazione che nasce e muore. L'unica memoria condivisa fra interpreti che non
# costa un database e' la proprieta' di Window(10000), che e' anche cio' che perf.py usa per
# l'interruttore della strumentazione.
#
# Una proprieta' sola con i campi separati da barra, non nove: leggere e' una traversata verso la
# GUI e non ha senso pagarla nove volte per un dato che si scrive tutto insieme.
BACHECA = 'fenlight.sonda.misura'
# LOTTO 240 -- i sei campi della forma viaggiano di qui, perche' chi scrive la riga in archivio e'
# il player e la bacheca e' l'unica memoria fra i due interpreti. `letta()` rifiuta una proprieta'
# con un numero di campi diverso, quindi una bacheca scritta dalla versione di prima non viene
# letta a meta': torna None e si ripiega, che e' il comportamento giusto.
_CAMPI_BACHECA = ('regime', 'lorda', 'regime_secondi', 'ttfb', 'byte', 'offset', 'quota', 'cpu',
				  'quando', 'cdn', 'regime_media', 'coda', 'centro', 'salita', 'avvallamento',
				  'campioni', 'regime_fonte', 'instabilita',
				  # LOTTO 255 -- passano di qui perche' chi scrive la riga in archivio e' il player,
				  # in un altro interprete. Una bacheca scritta dalla versione di prima ha un numero
				  # di campi diverso e `letta()` la rifiuta intera: e' il comportamento giusto, e non
				  # va scambiato per un guasto al primo avvio dopo l'aggiornamento.
				  'rssi_inizio', 'rssi_fine', 'rssi_min',
				  # LOTTO 258 -- perche' una misura possa essere SCARTATA a posteriori invece
				  # che creduta. Il 12/09 la sonda di Inception ha dato 17,32 Mbit/s dove
				  # quattro minuti prima e dodici dopo la stessa linea dava 55 e 62, e i tre
				  # indizi c'erano tutti -- ttfb 3514 ms contro 544-1414, ripiego del lettore,
				  # dimensione dichiarata 36,42 GB contro 2,75 reali -- ma vivevano solo nel
				  # log, quindi non erano correlabili con niente. `secondi` e' la lettura
				  # INTERA, che non si ricava da `regime_secondi`: su Pulp valevano 9,6 e 4,7.
				  'lettore', 'ripiegato', 'stato', 'dimensione_attesa', 'dimensione_vera',
				  'secondi')


def pubblica(esito):
	"""Mette l'ultima misura buona in bacheca. Una misura senza regime NON si pubblica: sostituirebbe
	una buona con una che non dice niente."""
	try:
		if not esito or not esito.get('regime'): return False
		import xbmcgui
		xbmcgui.Window(10000).setProperty(BACHECA, '|'.join(
			('' if esito.get(_c) is None else str(esito.get(_c))) for _c in _CAMPI_BACHECA))
		return True
	except: return False


def letta():
	"""La misura in bacheca, o None. La chiama il player quando scrive la riga."""
	try:
		import xbmcgui
		_grezzo = xbmcgui.Window(10000).getProperty(BACHECA)
		if not _grezzo: return None
		_pezzi = _grezzo.split('|')
		if len(_pezzi) != len(_CAMPI_BACHECA): return None
		_fuori = dict(zip(_CAMPI_BACHECA, _pezzi))
		for _c in ('regime', 'lorda', 'regime_secondi', 'ttfb', 'quota', 'cpu', 'quando',
				   'regime_media', 'coda', 'centro', 'salita', 'avvallamento', 'instabilita',
				   'rssi_inizio', 'rssi_fine', 'rssi_min'):
			_fuori[_c] = float(_fuori[_c]) if _fuori[_c] else None
		for _c in ('secondi',):
			_fuori[_c] = float(_fuori[_c]) if _fuori[_c] else None
		for _c in ('byte', 'offset', 'campioni', 'ripiegato', 'stato',
				   'dimensione_attesa', 'dimensione_vera'):
			_fuori[_c] = int(_fuori[_c]) if _fuori[_c] else None
		return _fuori if _fuori.get('regime') else None
	except: return None
