# Installazione passo passo

Guida per chi non è uno sviluppatore. Non serve saper programmare: si tratta di
scaricare una cartella, fare un doppio clic e incollare due chiavi in un file di
testo. In tutto una decina di minuti, la prima volta.

**Indice**
1. [Cosa ti serve prima](#1-cosa-ti-serve-prima)
2. [Scarica la cartella](#2-scarica-la-cartella)
3. [Installa (un doppio clic)](#3-installa-un-doppio-clic)
4. [Incolla le chiavi](#4-incolla-le-chiavi)
5. [Scegli la voce](#5-scegli-la-voce)
6. [Verifica](#6-verifica)
7. [La prima registrazione](#7-la-prima-registrazione)
8. [Dove finisce la puntata](#8-dove-finisce-la-puntata)
9. [Personalizza l'ospite](#9-personalizza-lospite)
10. [Aggiornare all'ultima versione](#10-aggiornare-allultima-versione)
11. [Se qualcosa non va](#11-se-qualcosa-non-va)

---

## 1. Cosa ti serve prima

**Due chiavi API.** Sono stringhe di caratteri che il programma usa per parlare
con i servizi. Sono personali: non condividerle e non metterle in giro.

| Serve per | Dove la prendi |
|---|---|
| Capire quello che dici + le risposte dell'ospite | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (Google Gemini) |
| La voce dell'ospite | [elevenlabs.io](https://elevenlabs.io) → il tuo profilo → *API Keys* |

Gemini è la scelta predefinita perché costa molto meno: trascrivere un'ora di
conversazione sta nell'ordine dei centesimi. In alternativa puoi usare OpenAI
([platform.openai.com/api-keys](https://platform.openai.com/api-keys)): il
programma li supporta entrambi e si cambia con una riga, vedi il
[passo 9](#9-personalizza-lospite).

> **Attenzione a un equivoco comune:** l'abbonamento a ChatGPT Plus **non** dà
> accesso alle API di OpenAI, e allo stesso modo l'app Gemini non dà accesso
> alle API di Google. Sono prodotti separati, con portafogli separati: la chiave
> va presa sui siti qui sopra.

**Delle cuffie.** Non sono obbligatorie ma cambiano la vita: senza, il microfono
risente la voce dell'ospite e te la ritrovi dentro la tua traccia.

**Un microfono decente.** Anche quello delle cuffie va benissimo. Quello interno
del portatile funziona, ma prende molta stanza.

---

## 2. Scarica la cartella

1. Apri questo link:
   **https://github.com/gabbariele/her/archive/refs/heads/claude/interactive-podcast-audio-software-9yczan.zip**
   (parte subito il download di un file `.zip`)
2. Apri il file scaricato: si crea una cartella con un nome lunghissimo tipo
   `her-claude-interactive-podcast-audio-software-9yczan`.
3. **Rinominala `her`** e spostala dove la ritrovi facilmente: la Scrivania va
   benissimo.

---

## 3. Installa (un doppio clic)

### macOS

Apri la cartella `her` e fai **doppio clic su `setup.command`**.

Si apre una finestra nera (il Terminale) che scrive delle righe e va avanti da
sola per un paio di minuti. Quando leggi **"Installazione completata"** hai
finito: premi un tasto per chiudere.

> **Se macOS dice "impossibile aprire perché proviene da uno sviluppatore non
> identificato":** fai **clic destro** su `setup.command` → **Apri** → nella
> finestra che compare, **Apri** di nuovo. Succede solo la prima volta.

> **Se dice che manca Python:** scaricalo da
> [python.org/downloads](https://www.python.org/downloads/), installalo con le
> impostazioni predefinite, poi rifai il doppio clic su `setup.command`.

### Windows

Apri la cartella `her` e fai **doppio clic su `setup.bat`**.

> Se Windows mostra un avviso blu ("Windows ha protetto il PC"), clicca
> **Ulteriori informazioni** → **Esegui comunque**.

> **Se dice che manca Python:** scaricalo da
> [python.org/downloads](https://www.python.org/downloads/) e durante
> l'installazione **spunta la casella "Add Python to PATH"** (è la cosa più
> importante di tutta l'installazione). Poi rifai il doppio clic su `setup.bat`.

---

## 4. Incolla le chiavi

L'installazione ha creato nella cartella un file che si chiama **`.env`**
(sì, comincia con un punto). Dentro ci vanno le tue chiavi.

### macOS — come aprirlo

I file che iniziano con il punto sono nascosti. Per vederli, nella finestra
della cartella premi **Cmd + Shift + punto**: `.env` compare (un po' sbiadito).

Poi **clic destro su `.env` → Apri con → TextEdit**.

### Windows — come aprirlo

**Clic destro su `.env` → Apri con → Blocco note.**
(Se `.env` non si vede: nella finestra della cartella, menu **Visualizza** →
spunta **Elementi nascosti**.)

### Cosa scrivere

Incolla ogni chiave subito dopo il segno `=`, senza spazi e senza virgolette:

```
HER_PRESET=gemini
ELEVENLABS_API_KEY=sk_lamiachiaveelevenlabs
HER_VOICE_ID=
GEMINI_API_KEY=AIzaSy-lamiachiavegoogle
OPENAI_API_KEY=
```

`HER_VOICE_ID` lo riempiamo al passo dopo. `OPENAI_API_KEY` lascialo vuoto se
usi Gemini: le righe vuote non danno nessun fastidio.

> `HER_PRESET` è la riga che decide chi è l'ospite e quali modelli usa.
> Lasciala su `gemini` per la configurazione economica.

**Salva** (Cmd+S o Ctrl+S) e chiudi.

> Le righe che cominciano con `#` sono commenti: lasciale pure lì, non danno
> fastidio.

---

## 5. Scegli la voce

Fai **doppio clic su `voci.command`** (macOS) o **`voci.bat`** (Windows).

Compare l'elenco delle voci del tuo account ElevenLabs, così:

```
  21m00Tcm4TlvDq8ikWAM  Rachel                 accent=american, age=young
  AZnzlk1XvdvUeBnXmlld  Domi                   accent=american, age=young
```

Quella sfilza di lettere a sinistra è l'**id** della voce. Copia l'id della voce
che vuoi usare, riapri `.env` e incollalo dopo `HER_VOICE_ID=`:

```
HER_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```

Salva e chiudi.

> Non trovi voci italiane? Su elevenlabs.io puoi sceglierne dalla loro libreria
> e aggiungerle al tuo account: da quel momento compaiono anche qui. Le voci
> multilingua parlano italiano benissimo.

---

## 6. Verifica

- **macOS:** apri il Terminale dentro la cartella e scrivi `./her.sh check`
  (se non sai come si fa: doppio clic su `registra.command`, se qualcosa manca
  te lo dice comunque lui).
- **Windows:** doppio clic su `verifica.bat`.

Deve uscire una cosa così:

```
Chiavi API:
  --  OpenAI       assente
  OK  Gemini       …a1b2
  OK  ElevenLabs   …c3d4

Configurazione attiva:
  STT   gemini/gemini-2.5-flash-lite (lingua: it)
  LLM   gemini/gemini-3.5-flash-lite, thinking: off
  TTS   elevenlabs/eleven_turbo_v2_5 voce: 21m00Tcm...

Tutto pronto: `her record`
```

`OpenAI assente` va benissimo se usi Gemini. Se invece leggi
`Manca: gemini, tts.voice_id`, torna al passo 4 e 5: qualcosa non è stato
salvato.

---

## 7. La prima registrazione

Fai **doppio clic su `registra.command`** (macOS) o **`registra.bat`**
(Windows).

> **macOS, solo la prima volta:** compare la richiesta *"Terminale vorrebbe
> accedere al microfono"*. Rispondi **OK**. Se per sbaglio hai detto di no:
> Impostazioni di Sistema → Privacy e sicurezza → Microfono → attiva
> **Terminale**, poi richiudi e riapri.

Cosa succede:

1. Ti scrive *"calibrazione del rumore di fondo: resta in silenzio…"*: per un
   secondo stai zitto, sta misurando quanto è rumorosa la stanza.
2. **Parla.** Fai la tua domanda come la faresti a un ospite in carne e ossa.
3. Quando smetti, dopo un attimo di silenzio parte la trascrizione: vedi
   comparire quello che hai detto, e dopo un paio di secondi **l'ospite
   risponde con la voce che hai scelto**.
4. Rispondi, ribatti, cambia argomento: va avanti così finché vuoi.
5. Per **chiudere la puntata premi `Ctrl` e `C` insieme**.

Appena chiudi, monta da solo e ti dice dove ha messo tutto:

```
Montato: sessions/20260826-201500/podcast.wav  (12.4 min, tagliati 6.1 min di vuoti)
MP3:     sessions/20260826-201500/podcast.mp3
```

Quei "vuoti tagliati" sono i secondi in cui l'ospite stava pensando: nel file
finale non ci sono più.

---

## 8. Dove finisce la puntata

Dentro la cartella `her` si crea una cartella `sessions`, e dentro una cartella
per ogni puntata (col nome della data e dell'ora). Lì trovi:

| File | Cos'è |
|---|---|
| `podcast.mp3` | **la puntata montata** — è questo che pubblichi |
| `podcast.wav` | la stessa cosa, qualità piena |
| `transcript.md` | la trascrizione, con i minuti |
| `transcript.srt` | i sottotitoli, se ti serve il video |
| `host.wav` | solo la tua voce |
| `guest.wav` | solo la voce dell'ospite |

Le ultime due servono se vuoi montare a mano: sono perfettamente allineate, le
apri come due tracce in Audacity, GarageBand, Audition o quello che usi.

> **L'MP3 non c'è?** Serve un programma in più, `ffmpeg`. Non è obbligatorio: il
> `.wav` è già pronto e lo pubblichi uguale. Se lo vuoi: su macOS
> `brew install ffmpeg`, su Windows scaricalo da
> [ffmpeg.org](https://ffmpeg.org/download.html).

**Non ti piace il ritmo?** Puoi rimontare la stessa puntata quante volte vuoi
senza registrarla di nuovo, dal Terminale nella cartella:

```
./her.sh render sessions/20260826-201500 --max-gap 0.25   # più serrato
./her.sh render sessions/20260826-201500 --max-gap 1.2    # più respiro
```

(su Windows: `.venv\Scripts\her.exe render sessions\...`)

---

## 9. Personalizza l'ospite

Chi è l'ospite, come parla, quanto è lungo — è tutto scritto in un file di
testo dentro la cartella `presets`. Apri **`presets/intervista.yaml`** con
TextEdit o Blocco note e leggi: è italiano normale.

```yaml
persona:
  name: "Nova"
  greeting: "Ciao, eccomi. Quando vuoi partiamo."
  system_prompt: |
    Sei Nova, ospite di un podcast italiano, in diretta con il conduttore.
    Italiano parlato, 3-4 frasi al massimo, niente elenchi:
    tutto quello che scrivi viene letto ad alta voce.
```

Cambia quelle righe e hai un altro ospite. Le regole che funzionano meglio:

- **Metti un tetto esplicito alla lunghezza** ("3-4 frasi al massimo").
  Senza, l'AI fa monologhi da conferenza e il podcast muore.
- **Vietagli gli elenchi**: viene letto ad alta voce, un elenco puntato suona
  malissimo.
- **Digli chi è e cosa sa**, e digli di ammettere quando non sa una cosa.

Nella cartella ci sono altri esempi già pronti: `gemini.yaml` (quello
economico, predefinito), `intervista.yaml` (lo stesso ospite ma su OpenAI),
`esperto-tech.yaml` (un ospite specializzato) e `veloce.yaml` (risposte
cortissime e latenza minima). **Per cambiare ospite ti basta cambiare la riga
`HER_PRESET=` nel file `.env`.**

### Cambiare modello (o spendere ancora meno)

Dentro il preset, le righe `stt:` e `llm:` dicono quale modello ascolta e quale
risponde. Nel file `gemini.yaml` sono commentate le alternative, dalla più
economica alla migliore. Per vedere quali modelli la tua chiave può davvero
usare — i nomi cambiano spesso — fai **doppio clic su `modelli.command`**
(macOS) o **`modelli.bat`** (Windows).

Poi incolli il nome che preferisci nel preset, alla riga `model:`.

Un'altra riga che vale la pena conoscere è `thinking:`. I modelli Gemini
recenti, se lasciati liberi, "ragionano" prima di rispondere: per una battuta di
tre frasi è tempo e denaro buttati, quindi nel preset è impostata su `off`. Se
un giorno vuoi risposte più meditate, mettila su `low` o `medium`.

**Per il materiale della singola puntata** (una scaletta, degli appunti, un
articolo) non serve toccare i preset: metti il testo in un file, per esempio
`note.md`, nella cartella, e dal Terminale lancia
`./her.sh record --preset intervista --context note.md`.

---

## 10. Aggiornare all'ultima versione

Fai **doppio clic su `aggiorna.command`** (macOS) o **`aggiorna.bat`**
(Windows). Scarica la versione nuova e sostituisce solo i file del programma.

**Non tocca mai** il tuo `.env` (le chiavi) né la cartella `sessions` (le tue
puntate). I preset vengono copiati in `presets-backup/` prima di essere
sostituiti: se ne avevi modificato uno, lo ritrovi lì e puoi ricopiartelo.

---

## 11. Se qualcosa non va

| Cosa vedi o senti | Cosa fare |
|---|---|
| *"Manca: gemini"*, *"Manca: openai"* o *"tts.voice_id"* | Chiavi non salvate: rileggi il passo 4 e 5. Attenzione agli spazi prima e dopo la chiave. |
| *"trascrizione fallita: manca OPENAI_API_KEY"* | Stai usando un preset su OpenAI: metti `HER_PRESET=gemini` nel file `.env`. |
| *"Gemini LLM 404"* o *"modello non trovato"* | Quel nome di modello non esiste più o la tua chiave non ce l'ha: `./her.sh models` mostra quelli veri, poi incollane uno nel preset. |
| *"429"* / *"RESOURCE_EXHAUSTED"* su Gemini | Hai finito la quota gratuita: attiva la fatturazione su Google AI Studio, oppure passa a un modello `-lite`. |
| L'ospite non risponde e leggi *"risposta vuota"* | Il modello ha consumato tutto in ragionamento: nel preset metti `thinking: off` sotto `llm:`, o alza `max_output_tokens`. |
| *"Errore: sounddevice non disponibile"* (Linux) | `sudo apt install libportaudio2` e rilancia. |
| Non registra niente, non reagisce quando parli | Permesso microfono negato (passo 7), o è selezionato il microfono sbagliato: `./her.sh devices` mostra quali ci sono. |
| Parte da solo anche se stai zitto | Stanza rumorosa: nel preset aggiungi in fondo `vad:` e sotto `  threshold_db: 15`. |
| Ti taglia la frase a metà mentre parli | Fai pause lunghe: nel preset aggiungi `vad:` e sotto `  silence_ms: 1000`. |
| Ci mette troppo a rispondere | Usa il preset `veloce`: `./her.sh record --preset veloce`. |
| L'ospite parla troppo | Non è il codice, è il carattere: metti un limite di frasi più severo nel `system_prompt`. |
| Sento la voce dell'ospite dentro la mia traccia | Stai usando gli altoparlanti: metti le cuffie. |
| *"429"* o *"insufficient_quota"* | Credito API finito: ricarica su platform.openai.com o elevenlabs.io. |
| Il Terminale si chiude subito senza dire niente | Aprilo prima (Applicazioni → Utility → Terminale), trascinaci dentro `setup.command` e premi Invio: così vedi l'errore. |

Se resti bloccato, la cosa più utile da riportare è **l'ultima riga che compare
nella finestra nera**: lì c'è sempre scritto il motivo.
