# her

Registra podcast **parlando davvero** con un ospite AI: tu parli al microfono,
lui ti capisce, ti risponde con la voce che hai scelto, e tutto finisce
registrato su due tracce separate. Alla fine i tempi morti vengono tagliati da
soli e ti ritrovi la puntata montata, con trascrizione e sottotitoli.

Sì: **si può fare**, e con le API che hai già (OpenAI, Gemini, ElevenLabs) non
serve altro. Questa è l'implementazione.

> **Non sei uno sviluppatore?** Salta questo file e segui
> **[INSTALLA.md](INSTALLA.md)**: installazione a doppio clic su Windows,
> spiegata passo passo, senza terminale.

---

## Come funziona

```
microfono ──► VAD ──► STT ──────► LLM ──────► TTS ────────► altoparlanti
 (24 kHz)   (capisce   (OpenAI    (contesto    (ElevenLabs   (in streaming)
             quando     o Gemini)  preimpostato) streaming)
             smetti
             di parlare)
    │                                                            │
    └────────► host.wav ◄── stessa timeline ──► guest.wav ◄──────┘
                            events.jsonl
                                 │
                                 ▼
                    her render ──► podcast.wav + .mp3
                                   transcript.md + .srt
```

Tre scelte che fanno la differenza:

1. **Endpointing automatico.** Non c'è nessun tasto da premere: un VAD a soglia
   adattiva capisce quando hai finito la frase (700 ms di silenzio, regolabile)
   e solo allora manda il turno alla trascrizione.
2. **Tutto in streaming, a cascata.** Appena l'LLM ha finito la *prima frase*,
   quella frase è già in sintesi mentre il modello scrive la seconda. È il
   motivo per cui la voce parte in 1–2 secondi invece che in 6–8.
3. **Registrazione multitraccia.** La tua voce e quella dell'ospite finiscono su
   due file separati e sincronizzati, più una timeline dei turni. Il montaggio
   non deve indovinare dove sono i silenzi: li conosce già.

### Quanto si aspetta davvero

Latenza tipica dalla fine della tua frase alla prima sillaba dell'ospite:

| pezzo | `gpt-4o` + `eleven_turbo` | preset `veloce` |
|---|---|---|
| silenzio di fine turno | 0,7 s | 0,55 s |
| trascrizione | 0,5–1,2 s | 0,3–0,6 s |
| primo token dell'LLM | 0,4–1,0 s | 0,2–0,5 s |
| primo audio dal TTS | 0,3–0,8 s | 0,15–0,4 s |
| **totale percepito** | **~2–3 s** | **~1,2–2 s** |

E comunque: quei buchi **spariscono nel montaggio**, che è esattamente il punto
di partenza da cui sei partito.

---

## Installazione

```bash
git clone <questo-repo> && cd her
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[audio,dev]"
```

Oppure `./setup.sh` (macOS/Linux) o `setup.bat` (Windows), che fanno lo stesso
senza chiedere niente. Per chi non usa il terminale ci sono i lanciatori a
doppio clic (Windows): `setup.bat`, `voci.bat`, `modelli.bat`, `verifica.bat`,
`registra.bat` e `aggiorna.bat` — quest'ultimo riscarica l'ultima versione
lasciando intatti `.env` e `sessions/`.

Su Linux serve PortAudio (`sudo apt install libportaudio2`); su macOS e Windows
`sounddevice` si porta dietro tutto. Per l'export MP3 serve `ffmpeg` nel PATH
(senza, ti resta comunque il WAV).

Poi le chiavi:

```bash
cp .env.example .env
# e dentro: OPENAI_API_KEY, ELEVENLABS_API_KEY, eventualmente GEMINI_API_KEY
```

## Primi cinque minuti

```bash
her check                       # chiavi e configurazione a posto?
her devices                     # quale microfono userà
her voices                      # le tue voci ElevenLabs, con gli id
her say "Ciao, sono il tuo ospite" --voice <voice_id>   # senti come suona
her record --preset intervista --voice <voice_id>       # si registra
```

Parla. Quando smetti, dopo un attimo l'ospite risponde. `Ctrl-C` chiude la
puntata e la monta:

```
Montato: sessions/20260826-201500/podcast.wav  (14.2s, tagliati 41.6s di vuoti)
MP3:     sessions/20260826-201500/podcast.mp3
Testi:   .../transcript.md · .../transcript.srt
```

Non hai il microfono a portata (o vuoi solo provare il contesto)?
`her record --preset intervista --voice <id> --text`: scrivi invece di parlare,
la voce e la registrazione funzionano uguale.

## Il contesto preimpostato

È un file YAML in `presets/`. Ne trovi tre già pronti — `intervista`,
`esperto-tech`, `veloce` — e ne copi uno per farti il tuo:

```yaml
persona:
  name: "Nova"
  greeting: "Ciao, eccomi. Quando vuoi partiamo."
  system_prompt: |
    Sei Nova, ospite di un podcast italiano, in diretta con il conduttore.
    Italiano parlato, 3-4 frasi al massimo, niente elenchi né markdown:
    tutto quello che scrivi viene letto ad alta voce.
tts:
  voice_id: "..."          # da `her voices`
  model: eleven_turbo_v2_5
llm:
  provider: openai         # oppure gemini
  model: gpt-4o
```

### Il materiale della puntata

`contesto.md` (o `--context altro-file.md`) è il briefing della singola puntata:
appunti in italiano normale e, se vuoi, dei link. Prima di registrare le pagine
vengono scaricate, ripulite dall'HTML e condensate in punti dallo stesso modello
che fa l'ospite; il risultato entra nelle sue istruzioni e una copia resta in
`contesto-usato.md` dentro la puntata. Le pagine lette finiscono in cache
(`contesto-cache/`), quindi la seconda registrazione parte subito: `--ricarica`
la ignora, `--no-link` non scarica niente.

Il materiale non viene solo dato all'ospite, le viene detto **come usarlo**
(`persona.context_pace`, anche `HER_CONTESTO`): il difetto naturale di un modello
è svuotare il sacco nelle prime due risposte, quindi la regola di default
(`dosato`) è una cosa per risposta, solo quando la domanda la chiama, mai
anticipando e mai citando la provenienza. `avaro` la tiene ancora più stretta,
`libero` toglie il freno. La regola viene messa subito dopo il materiale nel
prompt: da sola, in fondo, il modello la perde di vista.

`her contesto` mostra il briefing prima di registrare — vale la pena guardarlo:
è quello che l'ospite avrà in testa per tutta la puntata.

Il testo scaricato è dichiarato all'ospite come **materiale, non istruzioni**:
una pagina web è scritta da altri e non deve poter cambiare il comportamento
dell'ospite. Non è una barriera crittografica, ma è la differenza fra dare a
leggere un articolo e prendere ordini da un articolo.

Ogni valore del preset si può scavalcare da riga di comando
(`--llm gemini --llm-model gemini-3.5-flash --stt gemini`), e tutta la
configurazione è documentata in `her/config.py`. Il preset attivo si può fissare
anche con `HER_PRESET` nel `.env`, così i lanciatori a doppio clic lo seguono.

### Scegliere provider e modelli

| | OpenAI | Gemini |
|---|---|---|
| Trascrizione | `gpt-4o-transcribe` | `gemini-3.5-flash-lite`, o `gemini-3.5-transcribe` (dedicato) |
| Risposte | `gpt-4o`, `gpt-4o-mini` | `gemini-3.5-flash-lite`, `gemini-3.5-flash` |

Il preset `gemini` mette entrambe le gambe su Gemini: è la configurazione più
economica e non richiede nessuna chiave OpenAI. Si possono anche mescolare
(Gemini per l'ascolto, OpenAI per la testa): sono due sezioni indipendenti.

I nomi dei modelli cambiano in fretta, quindi non fidarti di questa tabella:
**`her models`** chiede al provider cosa offre davvero la tua chiave. E quando
Google ritira un modello, l'errore 404 dice quale usare al suo posto: `her`
legge quel suggerimento, riprova con il modello nuovo e ti avvisa di aggiornare
il preset, invece di perdere il turno in mezzo a una registrazione.

Sui modelli Gemini c'è anche `thinking:` (`off`, `minimal`, `low`, `medium`,
`high`, `auto` o un numero di token). Per battute da tre frasi il ragionamento è
latenza e costo sprecati: nei preset è `off`.

Le due generazioni si regolano in modi diversi — i 2.5 con un budget di token
(`thinkingBudget`, azzerabile), i 3.x con un livello (`thinkingLevel`, che al
minimo è `minimal` e non si può spegnere del tutto) — e mandare il campo
sbagliato produce un laconico `400 INVALID_ARGUMENT`. `her` sceglie la forma
giusta dal nome del modello, e se la richiesta viene comunque rifiutata la
semplifica per gradi (`minimal` → `low` → niente thinking → parametri
predefiniti) avvisandoti a ogni passo, invece di far cadere la risposta.

## La regia

Durante la registrazione un secondo modello, indipendente dall'ospite, segue la
conversazione e a ogni turno può passare al conduttore una riga da leggere. Sta
in `her/suggester.py`: thread e client HTTP suoi, così una regia lenta o rotta
non tocca la conversazione — un errore viene detto una volta e poi solo annotato
nel registro.

Due scelte fanno la differenza fra utile e fastidioso. **Il momento**: la regia
parte quando l'LLM ha finito di formulare la risposta, non quando l'ospite ha
finito di pronunciarla — il testo è completo ma la voce sta ancora parlando, e il
suggerimento arriva mentre c'è tempo di leggerlo. Perché sia davvero così, il
flusso dell'LLM viene scaricato da un thread dedicato: leggendolo dentro al ciclo
della sintesi restava fermo ad aspettare l'altoparlante, e la regia scattava a
risposta ormai finita. **L'aggancio**: il prompt le
chiede di reagire all'ultima risposta dell'ospite — una parola, un'affermazione
comoda, un buco nel ragionamento — non alla domanda del conduttore, e di dare una
mossa da fare invece di un consiglio generico. La regola è stringente: se non sa
indicare *quale* cosa sta agganciando, non ha una riga e deve tacere. A reggerla
ci sono quattro esempi di righe buone e cinque di righe da non dare mai
(«approfondisci», «chiedile un esempio», i riassunti di ciò che si è appena
sentito, e qualunque frase che andrebbe bene dopo qualsiasi risposta): senza
esempi negativi un modello scivola lì in due turni. Massimo quindici parole, e la
possibilità esplicita di tacere rispondendo `NIENTE`.

Il briefing della puntata non le viene passato (`suggester.use_briefing: false`):
il conduttore ce l'ha davanti, e darlo alla regia la porta a riportare il discorso
sui binari invece di reagire. Le righe passate finiscono in `suggerimenti.md`; si
spegne con `HER_REGIA=off` o `--no-regia`.

## Il montaggio

`her render sessions/<nome>` rifà il montaggio quante volte vuoi, senza
ritoccare le tracce originali:

```bash
her render sessions/20260826-201500 --max-gap 0.25   # ritmo serrato
her render sessions/20260826-201500 --max-gap 1.2    # più respiro
```

Senza argomenti monta l'ultima puntata *registrata* — l'ordine viene dalla data
di `host.wav`, non da quella della cartella, che cambia a ogni montaggio.
`--scegli` fa scegliere dall'elenco (è quello che fa `monta.bat`), `--tutte`
rimonta tutto. `her analizza` è la radiografia di una puntata senza toccarla:
turni in timeline, volumi misurati, spezzoni recuperati, età del montato.
Se `events.jsonl` manca o è vuoto la timeline viene ricostruita ascoltando le
due tracce, così i tagli si fanno lo stesso.
Il saluto iniziale dell'ospite resta fuori dal montato (`render.drop_greeting`,
attivo di default) ma è nella registrazione integrale.
Oltre al montato produce sempre `registrazione-integrale.wav`: le due voci
sommate senza alcun taglio, coi tempi originali.

Cosa fa: prende ogni turno dalla sua traccia, li rimette in fila comprimendo le
pause a `max_gap_s`, tiene le sovrapposizioni vere (quando interrompi l'ospite),
mette un fade di 12 ms su ogni giunta per non sentire i click, normalizza a
−1 dBFS ed esporta WAV + MP3 + `transcript.md` + `transcript.srt`.

**Pareggia anche i volumi, in LUFS.** Misurare una voce con l'RMS dei frame più
forti sbaglia: basta una plosiva o un colpo sul tavolo perché la misura salga di
2-3 dB e un microfono che a orecchio è basso risulti «già a posto». Il livello si
misura quindi come nello standard broadcast (ITU-R BS.1770): K-weighting, blocchi
da 400 ms, cancello assoluto e relativo — `her/audio/loudness.py`, senza
dipendenze, filtro applicato via FFT a blocchi. Ogni voce viene portata a
`target_lufs` (−16, il valore tipico dei podcast) e la voce del conduttore viene
anche compressa (`compress_host`, ratio 3): una voce al microfono è dinamica,
una sintetica è densa, e a parità di misura la prima sembra più lontana. La
correzione totale resta limitata a `max_match_db`, compreso il recupero dopo la
compressione, per non amplificare il fruscio di una traccia quasi muta;
`host_gain_db`/`guest_gain_db` sono il ritocco manuale, applicato per ultimo.

**I tagli lasciano un margine** (`edge_pad_in_s`, `edge_pad_out_s`): l'endpointer
chiude sul silenzio, e senza margine il montato mangia l'attacco e la coda delle
parole. Il margine non invade mai il turno precedente della stessa voce.

Se preferisci montare a mano, hai già tutto: `host.wav` e `guest.wav` sono
allineati campione per campione, quindi li importi come due tracce in Reaper,
Audition o Audacity e sei a casa.

## Cosa trovi in una sessione

```
sessions/20260826-201500/
├── host.wav        la tua voce, dall'inizio alla fine
├── guest.wav       l'ospite, in silenzio quando non parla, perfettamente allineato
├── registrazione-integrale.wav  le due voci in un file solo, pause comprese
├── contesto-usato.md  il materiale che l'ospite aveva davanti
├── events.jsonl    un turno per riga: chi, da quando a quando, cosa ha detto
├── session.json    modelli, voce, persona, durata
├── podcast.wav     il montato
├── podcast.mp3
├── transcript.md
└── transcript.srt
```

## Consigli pratici

- **Cuffie.** Con gli altoparlanti il microfono risente l'ospite e la sua voce
  finisce dentro `host.wav`. Per questo `half_duplex` è attivo di default: il
  microfono resta chiuso mentre l'ospite parla (ma continua a registrare).
- **Interromperlo.** Con le cuffie puoi usare `--barge-in`: parli sopra
  l'ospite e lui si zittisce a metà frase. In cuffia è naturalissimo, sugli
  altoparlanti innesca un loop.
- **Niente di ciò che dici sparisce dal montato per colpa della trascrizione.**
  La traccia del conduttore non viene tagliata seguendo la timeline dei turni
  riconosciuti: un VAD passa su `host.wav` e rimette nel montaggio ogni pezzo di
  parlato che nella timeline non c'è (`kind: recuperato`, `(non trascritto)` nei
  testi), ritagliato in modo da non sovrapporsi mai a un turno già presente.
  Resta fuori solo il parlato sovrapposto alla voce dell'ospite, che senza
  cuffie è il rientro della sua voce nel microfono — `recover_over_guest: true`
  lo include comunque.
- **La calibrazione iniziale usa i frame più silenziosi**, non la media: se
  saluti mentre calibra, il fondo di rumore non si alza (prima bastava quello
  per rendere sorda la soglia per tutta la puntata) e il programma ti avvisa.
- **Se ti taglia le frasi** perché fai pause per pensare, alza l'attesa:
  `--pausa 2.2`, oppure `HER_PAUSA=2.2` nel `.env`, oppure `vad.silence_ms` nel
  preset. Il default è 1,2 s. Se invece è lento a partire, scendi a 0,8.
- **Accento della voce**: `tts.language` (default `it`) impone la lingua al
  modello ElevenLabs, ma l'accento resta quello di chi ha inciso la voce: per un
  italiano madrelingua scegli una voce italiana dalla Voice Library.
- **Se parte da solo** in una stanza rumorosa, alza `vad.threshold_db` da 10 a
  14–16 dB. La soglia effettiva te la stampa a inizio sessione.
- **`registrazione-integrale.wav` viene scritto alla chiusura della sessione**,
  prima e indipendentemente dal montaggio: se il montaggio non parte, la
  registrazione completa c'è comunque. `her sessioni` dice, puntata per
  puntata, quali file ci sono e quali mancano; `her render` senza argomenti
  rimonta l'ultima.
- **Quanto parla e quanto ti interroga** sono due manopole, non un problema di
  prompt da riscrivere: `persona.length` (`breve`/`media`/`lunga`/`monologo`) e
  `persona.questions` (`mai`/`raramente`/`talvolta`/`spesso`), anche da `.env`
  (`HER_LUNGHEZZA`, `HER_DOMANDE`) o da riga di comando. `persona.notes`
  (`HER_INDICAZIONI`) aggiunge un'indicazione libera («sii più ironica»). Il
  tetto di token sale da solo con la lunghezza, così la risposta non si tronca.
- **Nomi propri sbagliati** nella trascrizione: `stt.hint` accetta un elenco di
  termini ricorrenti (nomi, sigle, marchi) e li fa riconoscere molto meglio.

## Costi, per farsi un'idea

Per ogni minuto di conversazione paghi tre pezzi: la trascrizione (frazioni di
centesimo), l'LLM (pochi centesimi con `gpt-4o`, molto meno con i modelli
`mini`/`flash`) e il TTS, che è la voce grossa della spesa. Un'ora di puntata
sta nell'ordine di qualche euro, dominata da ElevenLabs e dal suo piano.
I listini cambiano spesso: guardali sui rispettivi siti prima di fare i conti.

## Perché questa architettura e non l'API "realtime"

Esistono due alternative che vanno sotto il secondo di latenza:

- **OpenAI Realtime API** (voce-a-voce, un solo websocket): più veloce, ma la
  voce è la loro — la voce ElevenLabs che hai scelto non la puoi usare.
- **ElevenLabs Agents**: LLM + le loro voci, latenza intorno al secondo, ma il
  controllo su cosa succede a ogni turno è molto minore.

Qui la cascata STT → LLM → TTS costa qualche secondo in più, e in cambio dà: la
voce che vuoi, il modello che vuoi (puoi mescolare — Gemini per l'ascolto,
OpenAI per la testa), il testo di ogni turno sul disco, e soprattutto la
registrazione multitraccia pulita. Per un podcast, dove i vuoti li tagli
comunque in post, è lo scambio giusto. E l'interfaccia dei provider sta tutta in
`her/providers/`: se domani vuoi provare il realtime, cambi un file.

## Sviluppo

```bash
pytest -q        # 33 test, nessuna rete e nessuna scheda audio richiesta
```

I test coprono l'endpointing del VAD, il taglio in frasi per lo streaming, la
sincronia delle due tracce e la matematica del montaggio; `tests/test_session.py`
fa girare una sessione intera con provider finti.

```
her/
├── cli.py           comandi
├── config.py        default + preset + override
├── session.py       il loop: ascolta, trascrivi, rispondi, registra
├── render.py        montaggio, trascrizione, sottotitoli
├── text.py          pulizia del testo e taglio in frasi
├── audio/           microfono, VAD, riproduzione, registratore multitraccia, WAV
└── providers/       openai, gemini, elevenlabs (+ elenco dei modelli)
```

Il `voice_id` si può mettere nel preset oppure, più comodo, in `HER_VOICE_ID`
dentro il `.env`: il preset ha comunque la precedenza.

## Quando qualcosa si rompe a metà registrazione

Una puntata dura mezz'ora e non si può rifare: il programma è scritto perché un
guasto costi un turno, non la serata.

- **Il thread che ascolta non può morire in silenzio.** Un'eccezione nel ciclo
  del microfono lasciava la sessione viva ma sorda — nessuna trascrizione,
  nessuna risposta, nessun messaggio. Ora ogni frame è protetto: un errore
  isolato salta un turno, un errore sullo stream chiude l'ascolto *dicendolo*.
  E se non arrivano frame per cinque secondi, lo segnala.
- **Un turno che fallisce non chiude la puntata**: rete, provider, audio, quel
  che sia — viene registrato e si va avanti.
- **`sessione.log`** dentro la cartella della puntata: tutto quello che è
  comparso a schermo, con l'ora, più le tracce complete degli errori.
- **`her analizza`** confronta l'ultimo turno riconosciuto con la durata della
  registrazione: se gli ultimi minuti non hanno turni, te lo dice e ti manda al
  registro.
- **`her record --continua`** riprende una puntata: la conversazione viene
  riletta da `events.jsonl` (l'ospite ricorda), e il nuovo audio si aggiunge in
  coda a quello esistente. Il WAV non si può allungare, quindi la traccia
  vecchia viene messa da parte, ricopiata nella nuova e la copia di sicurezza
  sparisce solo a chiusura riuscita.

## Limiti noti

- Un solo conduttore e un solo ospite (una traccia per parte).
- L'ospite non ti interrompe mai di sua iniziativa: parla solo quando hai finito.
- Il VAD è a energia: in una stanza molto rumorosa, o con il microfono del
  portatile a mezzo metro, va tarato a mano.
- Niente interfaccia grafica: è un programma da terminale.
- La ripresa riscrive le tracce per allungarle: su una puntata molto lunga
  richiede qualche secondo e il doppio dello spazio, finché non si chiude.
