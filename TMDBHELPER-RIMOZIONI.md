# Rimozione riferimenti TMDbHelper dalla skin

Registro delle funzionalità disattivate durante la pulizia dei riferimenti morti a
`plugin.video.themoviedb.helper`. Serve come specifica di ciò che l'helper addon dovrà
ricostruire, senza doverlo ricavare dal `git log`.

**Nessuna delle voci qui elencate era funzionante al momento della rimozione**: le proprietà
che le pilotavano erano popolate dal servizio ListItemMonitor di TMDbHelper, assente in questa
installazione. Le condizioni erano quindi permanentemente false.

## Metodo

Due esiti possibili per ogni variabile, mai una cancellazione cieca:

- **Eliminata** — nessun consumatore in tutto l'albero della skin, né statico né dinamico.
- **Collassata sul fallback** — la variabile ha un `<value>` finale incondizionato ed è ancora
  raggiungibile. Poiché la proprietà pilota è sempre vuota, oggi ricade *sempre* su quel
  fallback: mantenerlo solo lui produce output identico byte per byte.

### Attenzione ai riferimenti dinamici

Un controllo dei consumatori basato solo su `$VAR[Nome]` letterale **non è sufficiente**.
[Includes_Info.xml](skin.arctic.fuse.3/1080i/Includes_Info.xml) costruisce nomi di variabile a
runtime:

```xml
<param name="label">$VAR[Label_$PARAM[service]_Status]$VAR[Label_$PARAM[service]_StatusDate, ,]</param>
<param name="icon">$VAR[Image_$PARAM[service]_Status]</param>
```

con `service` ∈ {`ListItem`, `Player`}. Sei nomi risultano quindi orfani a una ricerca testuale
pur essendo vivi. Prima di eliminare una variabile va sempre verificata anche l'espansione dei
`$VAR[...$PARAM...]`.

---

## Lotto 1 — Stato serie/film (`ListItem.Status`, `Player.Status`)

Proprietà TMDbHelper coinvolte: `ListItem.Status`, `Player.Status`, `ListItem.Next_Aired*`,
`ListItem.Last_Aired*`, `Player.Next_Aired`, `Player.Last_Aired`, `ListItem.Premiered*`,
`Player.Premiered`, `ListItem.Birthday`, `ListItem.Monitor.TMDb_Type`, `ListItem.base_dbtype`,
`Player.base_dbtype`.

Riferimenti morti rimossi: **113**.

### Eliminate (orfane)

| Variabile | File | Cosa mostrava |
|---|---|---|
| `Image_DialogInfo_Status` | Includes_Images.xml | icona calendario per lo stato, nella scheda info |
| `Label_ListItem_NextAired_Header` | Includes_Labels.xml | intestazione "Prossimo episodio" / "Ultimo andato in onda" / "Prima TV" |
| `Label_ListItem_NextAired` | Includes_Labels.xml | data estesa del prossimo/ultimo episodio |
| `Label_Overlay_Premiered` | Includes_Labels.xml | riga data nell'overlay; unico consumatore delle due precedenti, a sua volta orfano |

### Collassate sul fallback (raggiunte dinamicamente da Includes_Info.xml)

| Variabile | Valore mantenuto | Cosa mostrava prima |
|---|---|---|
| `Image_ListItem_Status` | `flags/$VAR[Color_Directory]/status/calendar-day.png` | icona diversa per Returning/Ended/Canceled/Released/Planned |
| `Image_Player_Status` | `flags/$VAR[Color_Directory]/status/calendar-day.png` | come sopra, per il media in riproduzione |
| `Label_ListItem_Status` | `$LOCALIZE[13205]` (Sconosciuto) | "In corso" / "Terminata" / "Cancellata" / "In produzione" / "Prevista", più le varianti "Nuova stagione"/"Nuovo episodio" basate su Next_Aired |
| `Label_Player_Status` | `$LOCALIZE[13205]` (Sconosciuto) | come sopra, per il media in riproduzione |
| `Label_ListItem_StatusDate` | `$LOCALIZE[1446]` (Sconosciuto) | data del prossimo/ultimo episodio, o data di uscita per i film |
| `Label_Player_StatusDate` | `$LOCALIZE[1446]` (Sconosciuto) | come sopra, per il media in riproduzione |

### Da ricostruire nell'helper

Una sola proprietà per lo stato, più le date di messa in onda:

- `Status` — valori attesi dalla skin: `Returning Series`, `Ended`, `Canceled`, `Released`,
  `In Production`, `Post Production`, `Planned`
- `Next_Aired`, `Next_Aired.Long`, `Next_Aired.Season`, `Next_Aired.Episode`,
  `Next_Aired.Days_Until_Aired`
- `Last_Aired`, `Last_Aired.Long`, `Last_Aired.Days_From_Aired`
- `Premiered`, `Premiered_Long`

TMDb le espone tutte su `/tv/{id}` (`status`, `next_episode_to_air`, `last_episode_to_air`) e
`/movie/{id}` (`status`, `release_date`), quindi bastano le chiamate che l'helper farà comunque.

**Nota:** la riga "Stato" nel pannello info è emessa solo con l'impostazione skin
`TMDbHelper.EnableData` attiva ([Includes_Info.xml:254](skin.arctic.fuse.3/1080i/Includes_Info.xml#L254)).
Con quella attiva, oggi mostra in permanenza "Sconosciuto" più l'icona calendario: era così
anche prima di questa pulizia.

---

## Lotto 2 — Variabili ibride (crew, studio, lingua, path parametriche)

Variabili che contengono **sia** una riga FenLight viva **sia** righe TMDbHelper morte. A
differenza del lotto 1 qui non si eliminano variabili: si rimuovono singole righe `<value>` e la
variabile resta viva e funzionante.

Riferimenti morti rimossi: **153** su 45 righe, in 9 variabili.

### Perché è neutro

La condizione di ogni riga rimossa interroga solo proprietà che nessuno scrive, quindi non può
mai essere vera. Una riga che non può mai corrispondere non contribuisce al risultato **a
prescindere dalla sua posizione** nella variabile.

Prima di procedere sono state cercate le due forme di riga che *non* sarebbero state neutre:

- **condizione mista** (`!String.IsEmpty(FenLight.X) + String.IsEqual(TMDbHelper.Y,z)`);
- **condizione viva ma valore morto** — la riga corrisponde, restituisce vuoto e blocca le righe
  successive; rimuoverla farebbe emergere una riga sottostante.

Zero occorrenze di entrambe. Una guardia nello script fallisce se una riga da rimuovere contiene
un riferimento TMDbHelper *vivo*.

| Variabile | File | Righe tolte | Cosa resta |
|---|---|---|---|
| `Label_FromDirector` | Includes_Labels.xml | 10 | riga FenLight + fallback nativo `ListItem.Director` |
| `Label_FromWriter` | Includes_Labels.xml | 10 | idem, su `ListItem.Writer` |
| `Label_FromStudio` | Includes_Labels.xml | 6 | riga FenLight + fallback |
| `Label_Language` | Includes_Labels.xml | 1 | riga FenLight + fallback |
| `Image_OSD_WriterIcon` | Includes_Images.xml | 5 | thumb FenLight |
| `Image_DirectorIcon` | Includes_Images.xml | 5 | thumb FenLight |
| `Path_Param_Query` | Includes_Paths.xml | 2 | 7 righe FenLight |
| `Path_Param_Type` | Includes_Paths.xml | 2 | 3 righe FenLight |
| `Path_VideoInfo_Trailers` | Includes_Paths.xml | 4 | solo il ramo musicvideo (YouTube) |

### Attenzione: `Null.xsp` non è sempre la scelta giusta

Nel fix OSD le path svuotate hanno ricevuto il fallback `Null.xsp`, perché alimentano dei
container. `Path_VideoInfo_Trailers` **no**, ed è deliberato: uno dei suoi consumatori è
`SetProperty(PlayTrailerItems,...)`, e quella proprietà viene testata per vuoto —
[Custom_1122_Dialog_SelectTrailer.xml:6](skin.arctic.fuse.3/1080i/Custom_1122_Dialog_SelectTrailer.xml#L6)
chiude il dialog se è vuota. Con `Null.xsp` la proprietà risulterebbe valorizzata e il selettore
trailer mostrerebbe una lista vuota invece di chiudersi.

Regola: `Null.xsp` per i `<content>` dei container, stringa vuota per le proprietà su cui la skin
fa `String.IsEmpty`.

### Da ricostruire nell'helper

Nulla di nuovo: crew, studio e lingua sono già coperti da FenLight tramite `skin_properties.py`.
Restano da ripristinare i **trailer** per film e serie (`/movie/{id}/videos`, `/tv/{id}/videos`),
oggi limitati ai musicvideo.

---

## Lotto 3 — Reparto crew nella scheda plot (`Label_Overlay_*`)

Riferimenti morti rimossi: **203**.

### La struttura trovata

`Label_Overlay_PlotBox` (consumata da `Dialog_DialogPlot.xml`) è un **aggregatore**: una singola
riga incondizionata che concatena 16 frammenti nella forma `$VAR[nome,prefisso,suffisso]`. In
quella forma Kodi emette il prefisso — l'intestazione di sezione, es. "Fotografia" — **solo se la
variabile non è vuota**. Le variabili crew erano tutte vuote, quindi né i nomi né le intestazioni
comparivano già prima.

Serviva perciò chirurgia a tre livelli diversi, non uno solo:

1. **frammento** — dall'aggregatore sono stati tolti i 10 frammenti morti (bracket matching, sono
   annidati), lasciando i 6 vivi;
2. **variabile** — le 9 variabili rimaste senza consumatori sono state eliminate;
3. **riga** — sulle 6 ibride superstiti sono state tolte solo le righe morte.

| Eliminate | Ridotte alla sola riga viva |
|---|---|
| `Label_Overlay_Production`, `_Sound`, `_ArtDepartment`, `_Cinematography`, `_Editing`, `_AwardsWon`, `_AwardsNominated`, `_Providers`, `_FileDetails`, `Label_Plot_Episode_Type_TMDBHelper` | `Label_Overlay_Directing`, `_Writing`, `_TopCast`, `_Tagline`, `_Critics`, `Label_Plot_TMDbHelper` |

Le ridotte conservano il ramo nativo `!$EXP[Exp_TMDbHelper_IsData]` → `$INFO[ListItem.Director]`,
`ListItem.Plot`, ecc. `Label_Overlay_Title` è rimasta intatta: la sua seconda riga usa
`base_label`, che è viva (la scrive il blur service).

### Due grafie per la stessa proprietà

Nel codice convivono **`TMDbHelper.`** (987 occorrenze) e **`TMDBHelper.`** (40). Le window
property di Kodi sono case-insensitive, quindi sono la stessa proprietà: `TMDBHelper.ListItem.base_plot`
è morta esattamente come `TMDbHelper.ListItem.base_plot`, e `TMDBHelper.WidgetContainer` è viva
esattamente come `TMDbHelper.WidgetContainer`.

I classificatori dei lotti 2 e 3 erano inizialmente case-sensitive. L'effetto è **sotto-rimozione,
mai sovra-rimozione** — una riga viene tolta solo se un riferimento morto viene trovato — ma il
rilevamento del *vivo* dev'essere case-insensitive con la stessa cura, altrimenti il rischio si
inverte. Le variabili del lotto 2 sono state ricontrollate: nessun residuo.

**Da qui in avanti ogni pattern usa `TMD[Bb]Helper\.`**

### Non incluso

`Includes_Overlay.xml` (22 rif. morti) usa proprietà di natura diversa — `IsUpdatingRatings`,
`IsUpdatingDetails`, `IsUpdating`, `Instance`, `Position`, `CurrentWindow` — che governano lo
stato dell'overlay, non le etichette. Merita un lotto proprio.

### Da ricostruire nell'helper

Le sezioni della scheda plot oggi assenti: **Produzione**, **Suono**, **Reparto artistico**,
**Fotografia**, **Montaggio**, **Premi** (vinti e nomination), **Provider streaming**, **dettagli
file**. Fonti TMDb: `/movie/{id}/credits` e `/tv/{id}/credits` con raggruppamento per
`department`, più `/watch/providers`. I premi non sono su TMDb: servono OMDb o MDBList.

---

## Lotto 4 — Cluster scheda info (DialogInfo + le sue path)

Riferimenti morti rimossi: **107**. Primo lotto **non invisibile**, approvato esplicitamente.

### Perché qui la rimozione si vede

Nei lotti 1-3 il codice morto non veniva mai disegnato. Qui no: `_Widget_Row`
([Includes_Widgets.xml:101](skin.arctic.fuse.3/1080i/Includes_Widgets.xml#L101)) rende visibile una
riga se `altvisible` è vero **anche a container vuoto**, e i pannelli morti avevano
`altvisible = CurrentID != BaseID` (vero quando la riga non è a fuoco) o addirittura `true` fisso.
Comparivano quindi come righe con la sola intestazione e nulla sotto.

### Pannelli rimossi (11)

Sceneggiatore, Creatore, Starring primo attore, Starring secondo attore, Stagioni ed Episodi
(3 varianti), Commenti, più i 3 pannelli del contesto persona (film con, serie con, troupe in
comune). Restano 14 pannelli, tutti alimentati da FenLight o dalla libreria locale.

Il pannello **Regista** è stato conservato: il suo `<content>` è già FenLight.

### Tre path che facevano davvero scattare il prompt

Il discriminante è se `$INFO[X,prefisso,]` ha `X` valorizzata — solo allora il prefisso `plugin://`
viene emesso:

| Dove | X | Azione |
|---|---|---|
| folderpath del regista | `Path_FromDirector` **viva** (FenLight) | riscritto su FenLight, allineato al `<content>` sottostante |
| galleria immagini persona | `ListItem.UniqueID(tmdb)` **viva** | `Null.xsp` |
| folderpath parametrico | proprietà morta, mai emesso | rimosso |

### Variabili di Includes_Paths

Eliminate perché orfane: `Path_VideoOSD_TMDbQuery`, `Path_VideoInfo_OnlineFlatSeasons`,
`Path_VideoInfo_OnlineComments`.

Ridotte, applicando la regola del lotto 2:

- `Path_VideoInfo_OnlineFanart` → `Null.xsp` (alimenta un `<content>`);
- `Path_FromWriter`, `Path_InfoParams_TMDbType/TMDbID/Season/Episode` → `<value />` vuoto
  (alimentano `SetProperty`/`param`, non container).

### Nota sullo strumento di verifica

L'invariante dei vivi è scesa da 266 a 265 senza che si fosse persa alcuna funzionalità: il
tokenizer dell'inventario tronca `TMDbHelper.ListItem.$PARAM[type].$PARAM[item].TMDb_ID` a
`ListItem.`, che per prefisso combacia con `base_label`/`base_poster` e veniva quindi contato come
vivo. Quella forma è invece **sempre morta**: il nome si compone a runtime da proprietà che nessuno
scrive. Lo script è stato corretto; la superficie viva reale è **258 rif. / 29 proprietà**.

---

## Fuori lotto — prompt "installa TMDbHelper" nell'OSD video

Anticipato rispetto al piano perché era un disturbo attivo durante la riproduzione, non codice
morto silenzioso.

**Meccanismo:** i bottoni dell'OSD aprono finestre di supporto al solo `onfocus`, non al click.
[VideoOSD.xml:75](skin.arctic.fuse.3/1080i/VideoOSD.xml#L75), bottone "salta avanti":

```xml
<onfocus condition="!VideoPlayer.Content(livetv)">ActivateWindow(1143)</onfocus>
```

La finestra 1143 carica un container il cui path era `plugin://plugin.video.themoviedb.helper/`.
Con l'addon assente, Kodi apre il prompt di installazione. Bastava passare sul bottone.

**Correzione:** rimossi i soli valori `themoviedb.helper`, aggiunto il fallback
`special://skin/extras/playlists/Null.xsp`. I valori nativi sono stati conservati.

| Variabile / file | Valori tolti | Conservato |
|---|---|---|
| `Path_OSD_NextRecommendation` | 3 | `playlistvideo://` — il "prossimo episodio" dalla playlist, che funziona nativamente |
| `Path_OSD_Cast` | 3 | nessuno: era interamente TMDbHelper |
| `Path_OSD_Episodes` | 1 | `playlistvideo://` e `videodb://` |
| `Custom_1193_VideoOSDInfo.xml` | 1 | il ramo `VideoOSD.InfoDialog.Path`, punto di aggancio per l'helper |

### Da ricostruire nell'helper

- **Raccomandazione successiva** (fine film): TMDb `/movie/{id}/recommendations`.
- **Cast nell'OSD**: `/movie/{id}/credits`, `/tv/{id}/credits`.
- **Elenco episodi nell'OSD** quando non c'è playlist: `/tv/{id}/season/{n}`.
- **Scheda info dal player**: va popolata `Window(Home).Property(VideoOSD.InfoDialog.Path)`;
  il ramo che la consuma è già in piedi in `Custom_1193_VideoOSDInfo.xml`.

### Residuo noto

`Custom_1114_Dialog_CustomPlot.xml` conserva un path TMDbHelper, ma è raggiungibile solo dal
dialog info (non durante la riproduzione) ed è dentro un `$INFO[Window.Property(tmdb_id),...]`,
che non emette nulla se la proprietà è vuota. Va trattato insieme al resto di
`Includes_DialogInfo.xml`.
