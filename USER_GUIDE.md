# Anime ilustrátor — používateľská príručka

Lokálna aplikácia, ktorá zo zadaného textu vyrobí sériu vizuálne
konzistentných **anime ilustrácií**. Analýzu textu a kontrolu výsledku
robí Claude (Anthropic API), samotné kreslenie prebieha v ComfyUI
workflowe (Illustrious XL + MHA-style LoRAs) na RunPod Serverless
endpointe.

Aplikácia beží lokálne na tvojom počítači — backend (Python) aj frontend
(prehliadač). Nič nie je verejne dostupné, kým si to sám nepustíš online.

---

## Čo aplikácia robí

1. Vložíš text príbehu.
2. Claude prečíta celý text a vyberie **max. 5 miest**, ktoré sa hodia
   ilustrovať. Zároveň navrhne spoločný výtvarný štýl, aby všetky obrázky
   pôsobili ako z jednej knihy.
3. Pre každú z piatich ilustrácií prebehne samostatná „dielňa":
   - Claude pripraví prompty pre danú scénu.
   - ComfyUI vykreslí obrázok.
   - Claude obrázok skontroluje. Ak nie je v poriadku, navrhne úpravu
     promptov, alebo úplne nový koncept pre rovnaké miesto v príbehu.
   - V najhoršom prípade sa pre jednu ilustráciu odohrá až **9 pokusov**
     (3 koncepty × 3 obrázky na koncept), kým sa to vzdá.
4. Všetkých 5 ilustrácií beží **paralelne**. Výsledok sa zobrazuje
   priebežne.

Generovanie trvá **niekoľko minút** — jeden ComfyUI beh trvá rádovo
minútu a hĺbka iterácií závisí od toho, ako dobre to vyjde na prvý pokus.

### Aké scény aplikácia v MVP vie ilustrovať

Pre prvú verziu má aplikácia úmyselné obmedzenie: každá ilustrácia musí
zobrazovať **práve jednu postavu** a tá musí byť jedným z troch typov:

- **chlapec alebo muž** (v anime štýle ako Izuku Midoriya),
- **dievča alebo žena** (v anime štýle ako Kyoka Jiro),
- **matka / materská postava** (v anime štýle ako Inko Midoriya).

Claude pri analýze textu vyberá iba také scény, kde takáto postava robí
niečo konkrétne — má jasný výraz tváre, gesto, polohu alebo činnosť.
Scény s viacerými postavami, davom, alebo bez jasného aktéra MVP
nepodporuje.

Ak v zadanom texte žiadna takáto scéna nie je, aplikácia ti to oznámi
slovenskou hláškou (viď FAQ nižšie) a beh neprebehne.

---

## Predpoklady

Predtým, než aplikáciu spustíš, potrebuješ:

- **Python 3.11+** (`python --version`).
- **Node.js 20+** s `npm` (alebo `pnpm`).
- **Účet na RunPod** s nasadeným ComfyUI Serverless endpointom. Postup
  nájdeš v dokumentácii RunPodu — pre štart stačí použiť hotový
  [ComfyUI worker template](https://github.com/runpod-workers/worker-comfyui).
  Z nasadeného endpointu si poznač:
  - API kľúč (User Settings → API Keys).
  - Endpoint ID (na detaile endpointu).
- **API kľúč pre Anthropic** z [console.anthropic.com](https://console.anthropic.com).
- **Workflow JSON v ComfyUI API formáte** — buď ten, ktorý prišiel s
  projektom (`backend/app/workflows/default.json`), alebo vlastný. Vlastný
  musí obsahovať šesticu reťazcov, ktoré aplikácia v texte workflowu nahradí
  vygenerovanými promptmi:
  - `CHARACTER_POSITIVE_PROMPT`
  - `CHARACTER_NEGATIVE_PROMPT`
  - `ENVIRONMENT_PROMPT`
  - `CHARACTER_LORA`
  - `STYLE_POSITIVE_PROMPT`
  - `STYLE_NEGATIVE_PROMPT`

  Tieto reťazce dáš v ComfyUI ako *hodnoty* do príslušných nodes (nie ako
  ich názvy). Workflow potom v ComfyUI ulož cez „Save (API Format)".

---

## Inštalácia

```bash
# Naklonuj projekt
git clone <repo>
cd anime-illustrator

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env               # vyplň hodnoty (viď nižšie)

# Frontend (v novom termináli)
cd ../frontend
npm install
cp .env.example .env               # zvyčajne stačí ponechať default
```

---

## Konfigurácia

V súbore `backend/.env` doplň:

```
ANTHROPIC_API_KEY=sk-ant-...
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
OUTPUT_DIR=./output
WORKFLOW_PATH=./app/workflows/default.json
ALLOWED_ORIGIN=http://localhost:5173
```

Žiadnu z týchto hodnôt nikdy nezdieľaj ani nekomituj do gitu. Súbor `.env`
je v `.gitignore`.

Vo `frontend/.env` zvyčajne stačí default:

```
VITE_API_BASE=http://localhost:8000
```

---

## Spustenie

V dvoch oddelených termináloch:

```bash
# Terminál 1 — backend
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminál 2 — frontend
cd frontend
npm run dev
```

Otvor prehliadač na adrese, ktorú vypíše Vite (typicky
`http://localhost:5173`).

Pri prvom spustení backendu sa automaticky vytvorí SQLite databáza v
priečinku `backend/data/`. Vygenerované obrázky sa ukladajú do
`backend/output/runs/<id_behu>/`.

---

## Použitie

### Krok 1 — vloženie textu

Na úvodnej obrazovke je veľké textové pole „Text príbehu". Vlož doň celý
text, z ktorého chceš ilustrácie vyrobiť. Limit je 50 000 znakov, čo
pokryje aj dlhšie príbehy.

Klikni na **„Vygenerovať ilustrácie"**.

Ak text neobsahuje žiadnu vhodnú scénu (viď „Aké scény aplikácia v MVP
vie ilustrovať" vyššie), aplikácia ti to oznámi červeným bannerom v
detaile behu.

### Krok 2 — sledovanie priebehu

Stránka sa prepne na detail behu. Hore vidíš celkový stav (Beží / Hotovo /
Zlyhalo / Zrušené) a počítadlo dokončených ilustrácií („Hotové: K z N").

Nižšie je mriežka kariet — jedna na ilustráciu. Každá karta nezávisle
ukazuje, čo sa práve s tou jednou ilustráciou deje:

| Stav                       | Čo to znamená                                   |
|----------------------------|-------------------------------------------------|
| Čaká                       | Ilustrácia zatiaľ nezačala                      |
| Pripravujem prompty        | Claude formuluje, čo má ComfyUI vykresliť       |
| Kreslím (pokus K/3)        | ComfyUI generuje obrázok                        |
| Vyhodnocujem výsledok      | Claude kontroluje hotový obrázok                |
| Upravujem prompty          | Obrázok nesedel, Claude upravuje prompty        |
| Premýšľam koncept          | Claude skúša úplne nový koncept tej istej scény |
| Hotovo                     | Úspech, obrázok je zobrazený                    |
| Nepodarilo sa              | Po všetkých pokusoch sa nepodarilo              |
| Zrušené                    | Zastavené užívateľom                            |

Karta, ktorá pracuje, má pulzujúci indikátor. Karta, ktorá je hotová,
zobrazuje obrázok priamo. Karta, ktorá zlyhala, zobrazuje stručný dôvod.

**Stránku môžeš pokojne obnoviť alebo zavrieť a vrátiť sa neskôr.** Beh
pokračuje na pozadí a po návrate sa všetko obnoví podľa toho, ako ďaleko
postúpil.

### Krok 3 — zrušenie

Počas behu je v hornej časti tlačidlo **„Zrušiť beh"**. Po potvrdení sa
ďalšie kroky neuskutočnia a všetky aktívne ilustrácie sa prepnú do stavu
„Zrušené". Pozor: ComfyUI obrázky, ktoré sa už začali kresliť, sa
dokončia (RunPod ich neviem zastaviť uprostred), len sa s ich výsledkom
už nepracuje.

### Krok 4 — výsledok

Po dokončení behu sú obrázky uložené aj na disku, v priečinku
`backend/output/runs/<id_behu>/`. V UI ich vidíš v mriežke; kliknutím na
obrázok sa otvorí v plnej veľkosti.

---

## Často kladené otázky

**Koľko ma to bude stáť?**
Dve nezávislé položky: tokeny v Anthropic API (zopár volaní na ilustráciu,
plus jedna analýza textu na začiatku) a sekundy GPU času na RunPod (pri
serverless endpointe platíš len za reálne vykonané jobs). Pre orientáciu si
pred prvým spustením skontroluj cenníky oboch služieb a nastav si limity na
ich účtoch.

**Aplikácia mi vyhodila hlášku „Zadaný text nie je vhodný ako zdroj ilustrácií". Čo s tým?**
Aplikácia v MVP ilustruje iba scény, kde je práve jedna postava (chlapec/muž,
dievča/žena alebo matka) a robí niečo konkrétne — má jasný výraz, gesto,
alebo činnosť. Ak Claude v tvojom texte takúto scénu nenájde, beh sa
ukončí touto hláškou. Riešenia: skús text, kde sa popisuje aspoň jedna
takáto sólová scéna (napr. „Janka sedela pri okne a plakala", „Otec
zdvihol kameň a zaváhal"), prípadne dlhší text, v ktorom je väčšia šanca,
že sa nejaká vhodná scéna vyskytne.

**Prečo niektoré ilustrácie zlyhajú?**
Claude pri vyhodnocovaní obrázka môže opakovane konštatovať, že to nie je
dosť dobré, a po vyčerpaní 9 pokusov sa scéna vzdá. Najčastejšie príčiny:
nezvyklá scéna, ktorú si workflow nevie poradiť vykresliť; postava, ktorú
LoRA nezachytáva; alebo zlý workflow. Skús ten beh spustiť znova — Claude
môže navrhnúť odlišné koncepty.

**Môžem použiť iný workflow?**
Áno. Stačí svoj API-format workflow JSON uložiť ako
`backend/app/workflows/default.json` (alebo zmeniť cestu v `.env`). Musí
obsahovať šesť spomenutých placeholderov ako hodnoty.

**Môžem generovať viac ako 5 ilustrácií?**
V MVP nie. Limit 5 je zámerný strop na nákladovú bezpečnosť pri testovaní.

**Aplikácia nereaguje / „beží" už pridlho.**
Skontroluj log backendu v termináli. Najčastejšie príčiny:
- Nesprávny `RUNPOD_ENDPOINT_ID` alebo `RUNPOD_API_KEY` — chyby uvidíš v logu.
- Endpoint v RunPode nemá teplých workerov a každý prvý job čaká na cold
  start (typicky 30–60 s pri ComfyUI). Skús v RunPod konzole nastaviť
  aspoň jedného active workera.
- Anthropic vrátil rate-limit chybu. Skús neskôr alebo spracovávaj menej
  textov naraz.

**Ako aplikáciu úplne vyresetujem?**
Zastav backend, vymaž `backend/data/app.db` a `backend/output/`, spusti
backend znova. DB sa vytvorí prázdna.

**Sú moje vstupné texty niekde uložené?**
Lokálne v SQLite databáze (`backend/data/app.db`) na tvojom počítači. Texty
sa posielajú do Anthropic API (na analýzu) podľa ich štandardných
podmienok. Nikam inam neodchádzajú.

---

## Limity (zhrnutie)

| Limit                                    | Hodnota |
|------------------------------------------|---------|
| Max. dĺžka vstupného textu               | 50 000 znakov |
| Max. počet ilustrácií na beh             | 5 |
| Max. počet konceptov na ilustráciu       | 3 |
| Max. počet pokusov na koncept            | 3 |
| Max. počet ComfyUI behov na ilustráciu   | 9 (3 × 3) |
| Max. čakanie na jeden ComfyUI beh        | 10 minút |

---

## Pri probléme

Ak niečo nefunguje a manuál nepomohol, najprv si pozri log v termináli
backendu — väčšina chýb (zlý kľúč, nedostupný endpoint, chyba parsovania
odpovede Claudu) sa tam objaví zrozumiteľne. Pre detailnejšie ladenie sa
pozri do priečinka `backend/output/runs/<id_behu>/`, kde sú obrázky
jednotlivých pokusov.
