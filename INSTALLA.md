# Installazione passo passo (Windows)

Guida per chi non è uno sviluppatore. Non serve saper programmare: si scarica
una cartella, si fa un doppio clic e si incollano due chiavi in un file di
testo. In tutto una decina di minuti, la prima volta.

> Su Linux o macOS si usano `setup.sh` e `her.sh` da terminale: stessi passaggi,
> stessi file di configurazione.

**Indice**
1. [Cosa ti serve prima](#1-cosa-ti-serve-prima)
2. [Scarica la cartella](#2-scarica-la-cartella)
3. [Installa (un doppio clic)](#3-installa-un-doppio-clic)
4. [Incolla le chiavi](#4-incolla-le-chiavi)
5. [Scegli la voce](#5-scegli-la-voce)
6. [Verifica](#6-verifica)
7. [La prima registrazione](#7-la-prima-registrazione)
8. [Dove finisce la puntata](#8-dove-finisce-la-puntata)
9. [Regolare l'attesa e la voce](#9-regolare-lattesa-e-la-voce)
10. [Personalizza l'ospite](#10-personalizza-lospite)
11. [Aggiornare all'ultima versione](#11-aggiornare-allultima-versione)
12. [Se qualcosa non va](#12-se-qualcosa-non-va)

---

## 1. Cosa ti serve prima

**Due chiavi API.** Sono stringhe di caratteri che il programma usa per parlare
con i servizi. Sono personali: non condividerle e non metterle in giro.

| Serve per | Dove la prendi |
|---|---|
| Capire quello che dici + le risposte dell'ospite | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (Google Gemini) |
| La voce dell'ospite | [elevenlabs.io](https://elevenlabs.io) → il tuo profilo → *API Keys* |

Gemini è la scelta predefinita perché costa molto meno: trascrivere un'ora di
conversazione sta nell'ordine dei centesimi. In alternativa si può usare OpenAI
([platform.openai.com/api-keys](https://platform.openai.com/api-keys)): il
programma li supporta entrambi e si cambia con una riga.

> **Attenzione a un equivoco comune:** l'abbonamento a ChatGPT Plus **non** dà
> accesso alle API di OpenAI, e allo stesso modo l'app Gemini non dà accesso
> alle API di Google. Sono prodotti separati, con portafogli separati.

**Delle cuffie.** Non obbligatorie, ma cambiano la vita: senza, il microfono
risente la voce dell'ospite e te la ritrovi dentro la tua traccia.

---

## 2. Scarica la cartella

1. Apri questo link:
   **https://github.com/gabbariele/her/archive/refs/heads/claude/interactive-podcast-audio-software-9yczan.zip**
   (parte subito il download di un file `.zip`)
2. Apri il file scaricato, poi **Estrai tutto**: si crea una cartella con un
   nome lunghissimo tipo `her-claude-interactive-podcast-audio-software-9yczan`.
3. **Rinominala `her`** e spostala dove la ritrovi facilmente: il Desktop va
   benissimo.

---

## 3. Installa (un doppio clic)

Apri la cartella `her` e fai **doppio clic su `setup.bat`**.

Si apre una finestra nera che scrive delle righe e va avanti da sola per un paio
di minuti. Quando leggi **"Installazione completata"** hai finito.

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

**Clic destro su `.env` → Apri con → Blocco note.**
Se `.env` non si vede: nella finestra della cartella, menu **Visualizza** →
spunta **Elementi nascosti**.

Incolla ogni chiave subito dopo il segno `=`, senza spazi e senza virgolette:

```
HER_PRESET=gemini
ELEVENLABS_API_KEY=sk_lamiachiaveelevenlabs
HER_VOICE_ID=
HER_PAUSA=1.4
GEMINI_API_KEY=AIzaSy-lamiachiavegoogle
OPENAI_API_KEY=
```

`HER_VOICE_ID` lo riempiamo al passo dopo. `OPENAI_API_KEY` lascialo vuoto se
usi Gemini: le righe vuote non danno nessun fastidio.

**Salva** (Ctrl+S) e chiudi.

> `HER_PRESET` decide chi è l'ospite e quali modelli usa. `HER_PAUSA` sono i
> secondi di silenzio da aspettare prima che l'ospite risponda: ci torniamo al
> [passo 9](#9-regolare-lattesa-e-la-voce).

---

## 5. Scegli la voce

Fai **doppio clic su `voci.bat`**. Compare l'elenco delle voci del tuo account
ElevenLabs:

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

> **Sull'accento.** Il programma dice a ElevenLabs che il podcast è in italiano,
> quindi la pronuncia è corretta. Ma **l'accento resta quello di chi ha inciso
> la voce**: una voce americana parlerà italiano con l'accento americano, e non
> c'è impostazione che lo tolga. Se ti serve un italiano madrelingua, vai su
> elevenlabs.io → *Voices* → *Voice Library*, filtra per **Italian**, aggiungi
> una voce al tuo account: da quel momento compare anche in `voci.bat`.

---

## 6. Verifica

Doppio clic su **`verifica.bat`**. Deve uscire una cosa così:

```
Chiavi API:
  --  OpenAI       assente
  OK  Gemini       …a1b2
  OK  ElevenLabs   …c3d4

Configurazione attiva:
  STT   gemini/gemini-3.5-flash-lite (lingua: it)
  LLM   gemini/gemini-3.5-flash-lite, thinking: off
  TTS   elevenlabs/eleven_turbo_v2_5 voce: 21m00Tcm... (lingua: it)
  Audio 24000 Hz · attesa prima della risposta: 1.4s

Tutto pronto: `her record`
```

`OpenAI assente` va benissimo se usi Gemini. Se invece leggi
`Manca: gemini, tts.voice_id`, torna ai passi 4 e 5: qualcosa non è stato
salvato.

---

## 7. La prima registrazione

Fai **doppio clic su `registra.bat`**. Se Windows chiede il permesso di usare il
microfono, di' di sì.

Cosa succede:

1. Ti scrive *"calibrazione del rumore di fondo: resta in silenzio…"*: per un
   secondo stai zitto, sta misurando quanto è rumorosa la stanza.
2. **Parla.** Fai la tua domanda come la faresti a un ospite in carne e ossa.
3. Quando smetti, dopo il silenzio di attesa parte la trascrizione: vedi
   comparire quello che hai detto, e dopo un paio di secondi **l'ospite
   risponde con la voce che hai scelto**.
4. Rispondi, ribatti, cambia argomento: va avanti finché vuoi.
5. Per **chiudere la puntata premi `Invio`**.

Appena chiudi, monta da solo e ti dice dove ha messo tutto.

> **Usa `Invio`, non `Ctrl-C`.** Su Windows `Ctrl-C` dentro una finestra `.bat`
> fa comparire *"Terminate batch job (Y/N)?"* e può ammazzare il programma prima
> che il montaggio sia scritto sul disco. Con `Invio` chiude con calma. Se ti
> capita comunque di trovarti senza il montato, non hai perso niente: doppio
> clic su **`monta.bat`** e lo rifà dalle tracce già registrate.

---

## 8. Dove finisce la puntata

Dentro la cartella `her` si crea una cartella `sessions`, e dentro una cartella
per ogni puntata (col nome della data e dell'ora). Lì trovi:

| File | Cos'è |
|---|---|
| `podcast.mp3` | **la puntata montata**: le due voci insieme, senza i vuoti — è questo che pubblichi |
| `podcast.wav` | la stessa cosa, qualità piena |
| `registrazione-integrale.wav` | tutto quanto in un file solo, coi tempi veri, pause comprese |
| `transcript.md` | la trascrizione, con i minuti |
| `transcript.srt` | i sottotitoli, se ti serve il video |
| `host.wav` | solo la tua voce |
| `guest.wav` | solo la voce dell'ospite |

`podcast.wav` è quello che cerchi quasi sempre: host e ospite uniti, senza i
secondi di attesa. `registrazione-integrale.wav` è la copia di sicurezza:
contiene esattamente quello che è successo, pause comprese. Le ultime due servono se vuoi montare a mano: sono
perfettamente allineate, le apri come due tracce in Audacity, Reaper, Audition o
quello che usi.

> **L'MP3 non c'è?** Serve un programma in più, `ffmpeg`. Non è obbligatorio: il
> `.wav` è già pronto e lo pubblichi uguale. Se lo vuoi, scaricalo da
> [ffmpeg.org](https://ffmpeg.org/download.html).

**Rimontare a mano.** Doppio clic su **`monta.bat`**: rimonta l'ultima puntata
registrata. Serve quando il montaggio non è stato scritto (finestra chiusa
troppo presto) o quando vuoi solo rifarlo.

Per cambiare il ritmo, apri il Prompt dei comandi nella cartella:

```
.venv\Scripts\her.exe render --max-gap 0.25              (l'ultima puntata)
.venv\Scripts\her.exe render sessions\20260826-201500    (una in particolare)
```

`--max-gap` è la pausa massima lasciata fra un turno e l'altro: `0.25` è
serrato, `1.2` è più disteso.

---

## 9. Regolare l'ospite (quanto parla, quanto ti interroga)

L'ospite si regola da tre righe del `.env`, senza aprire nessun preset:

```
HER_LUNGHEZZA=lunga
HER_DOMANDE=raramente
HER_INDICAZIONI=
```

- **`HER_LUNGHEZZA`** — `breve` (2-3 frasi), `media` (4-6), `lunga` (8-12,
  con esempi e una posizione), `monologo` (anche due o tre minuti). Se ti
  risponde a monosillabi, è questa la riga da alzare.
- **`HER_DOMANDE`** — `mai`, `raramente` (default: al massimo una ogni cinque
  o sei risposte), `spesso`. Se ti rimbalza sempre la palla con «e tu che ne
  pensi?», mettila su `mai`.
- **`HER_INDICAZIONI`** — testo libero, scritto come lo diresti a un ospite
  vero: `sii più ironica`, `non parlare di politica`, `dammi del tu`,
  `parla più lentamente`. Finisce dritto nelle istruzioni dell'ospite.

Chi è l'ospite (nome, carattere, cosa sa) sta invece nel preset: vedi il
[passo 10](#10-personalizza-lospite).

---

**Se l'ospite ti interrompe** perché fai delle pause mentre pensi a cosa dire,
alza `HER_PAUSA` nel file `.env`:

```
HER_PAUSA=2.2
```

Sono i secondi di silenzio che il programma aspetta prima di considerare finito
il tuo turno. Con `2.2` puoi prenderti due secondi buoni di pensiero senza che
lui prenda la parola. Il prezzo è che le risposte arrivano un po' più tardi —
ma tanto quei vuoti spariscono nel montaggio, quindi puoi essere generoso.

**Se invece è troppo lento a partire**, scendi a `0.8`.

**Se parte da solo** quando non stai parlando, la stanza è rumorosa: apri il
preset (cartella `presets`) e sotto `vad:` aggiungi `threshold_db: 15`.

**Per la lingua della voce**, nei preset c'è `language: it` sotto `tts:`. È
quello che impedisce alla voce di leggere l'italiano come se fosse inglese.
Funziona con i modelli `eleven_turbo_v2_5` e `eleven_flash_v2_5`.

---

## 10. Personalizza l'ospite

Chi è l'ospite, come parla, quanto è lungo — è tutto scritto in un file di testo
dentro la cartella `presets`. Apri **`presets/gemini.yaml`** con il Blocco note
e leggi: è italiano normale.

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

Nella cartella ci sono altri esempi pronti: `intervista.yaml` (lo stesso ospite
su OpenAI), `esperto-tech.yaml` (un ospite specializzato) e `veloce.yaml`
(risposte cortissime, latenza minima). **Per cambiare ospite basta cambiare la
riga `HER_PRESET=` nel file `.env`.**

### Cambiare modello (o spendere ancora meno)

Dentro il preset, le righe `stt:` e `llm:` dicono quale modello ascolta e quale
risponde. In `gemini.yaml` sono commentate le alternative, dalla più economica
alla migliore. Per vedere quali modelli la tua chiave può davvero usare — i nomi
cambiano spesso — fai **doppio clic su `modelli.bat`**, poi incolla il nome che
preferisci alla riga `model:`.

Un'altra riga utile è `thinking:`. I modelli Gemini recenti, se lasciati liberi,
"ragionano" prima di rispondere: per una battuta di tre frasi è tempo e denaro
buttati, quindi è impostata su `off`. Per risposte più meditate: `low` o
`medium`.

**Per il materiale della singola puntata** (una scaletta, degli appunti) metti
il testo in un file, per esempio `note.md`, nella cartella, e lancia dal Prompt
dei comandi:

```
.venv\Scripts\her.exe record --context note.md
```

---

## 11. Aggiornare all'ultima versione

Fai **doppio clic su `aggiorna.bat`**. Scarica la versione nuova e sostituisce
solo i file del programma.

**Non tocca mai** il tuo `.env` (le chiavi) né la cartella `sessions` (le tue
puntate). I preset vengono copiati in `presets-backup\` prima di essere
sostituiti: se ne avevi modificato uno, lo ritrovi lì.

---

## 12. Se qualcosa non va

| Cosa vedi o senti | Cosa fare |
|---|---|
| L'ospite prende la parola mentre stai ancora pensando | Alza `HER_PAUSA` nel `.env` (per esempio `2.5`). |
| Risponde con due parole e ti fa subito una domanda | `HER_LUNGHEZZA=lunga` e `HER_DOMANDE=mai` nel `.env`. |
| Manca il file montato (`podcast.wav`) | La finestra si è chiusa prima del montaggio: doppio clic su `monta.bat`. |
| La voce ha l'accento straniero | La pronuncia la impone già `language: it`; l'accento dipende dalla voce: prendine una italiana dalla Voice Library (passo 5). |
| *"Manca: gemini"*, *"Manca: openai"* o *"tts.voice_id"* | Chiavi non salvate: rileggi i passi 4 e 5. Attenzione agli spazi. |
| *"trascrizione fallita: manca OPENAI_API_KEY"* | Stai usando un preset su OpenAI: metti `HER_PRESET=gemini` nel `.env`. |
| *"is no longer available"* / *"404"* su Gemini | Google ha ritirato quel modello. Il programma passa da solo a quello suggerito e te lo dice: per non rivedere l'avviso, apri il preset e scrivi il nome nuovo alla riga `model:`. `modelli.bat` elenca quelli disponibili. |
| *"429"* / *"RESOURCE_EXHAUSTED"* su Gemini | Quota finita: attiva la fatturazione su Google AI Studio o passa a un modello `-lite`. |
| L'ospite non risponde e leggi *"risposta vuota"* | Nel preset, sotto `llm:`, metti `thinking: off` o alza `max_output_tokens`. |
| *"400"* / *"INVALID_ARGUMENT"* su Gemini | Un parametro non gradito da quel modello: il programma riprova da solo semplificando la richiesta e te lo dice. Se fallisce anche così, prova `thinking: auto` nel preset. |
| Non registra niente quando parli | Permesso microfono negato, o microfono sbagliato: `.venv\Scripts\her.exe devices` mostra quali ci sono. |
| Sento la voce dell'ospite dentro la mia traccia | Stai usando gli altoparlanti: metti le cuffie. |
| *"401"* da ElevenLabs | Chiave sbagliata o scaduta: rigenerala su elevenlabs.io. |
| La finestra si chiude subito senza dire niente | Apri il Prompt dei comandi, trascinaci dentro il `.bat` e premi Invio: così vedi l'errore. |

Se resti bloccato, la cosa più utile da riportare è **l'ultima riga che compare
nella finestra nera**: lì c'è sempre scritto il motivo.
