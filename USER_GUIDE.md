# Anime ilustrátor — používateľská príručka

Anime ilustrátor je webová aplikácia, v ktorej sa spolu s asistentom
(Claude) v krátkom rozhovore dohodneš na podobe príbehu, a aplikácia
ti k nemu vyrobí sériu **piatich vizuálne konzistentných anime
ilustrácií**. Samotné kreslenie prebieha na GPU u tretej strany
(RunPod ComfyUI Serverless, model *Illustrious XL* s LoRA postavami z
My Hero Academia), texty a kontrolu kvality má na starosti Claude.

Aplikácia je nasadená ako **súkromné demo** dostupné iba cez pozývací
odkaz alebo prístupový kľúč. Beží v cloude (frontend na Cloudflare
Pages, backend na Fly.io); od teba sa neočakáva žiadna inštalácia.

---

## Prístup

### Cez pozývací odkaz

Najjednoduchšia cesta: prevádzkovateľ ti pošle odkaz v tvare
`https://anime-illustrator.pages.dev/?invite=<kľúč>`. Otvor ho a
aplikácia si tvoj kľúč zapamätá v prehliadači — ďalej už pracuješ
bez zadávania kľúča.

### Cez ručne vložený kľúč

Ak si kľúč dostal iba ako text, choď na
`https://anime-illustrator.pages.dev/`, na uvítacej stránke vlož
kľúč do políčka „Prístupový kľúč" a potvrď. Kľúč sa uloží do
`localStorage` prehliadača a pri ďalšej návšteve už nebudeš musieť
nič zadávať.

### Limity na kľúč

Každý kľúč má pridelený počet **dokončených príbehov**, ktoré môže
v rámci dema vyrobiť (zvyčajne 2–5). Keď ho vyčerpáš, aplikácia ti
to oznámi a požiada o kontakt na prevádzkovateľa. Ak príbeh zlyhá z
dôvodu výpadku GPU alebo iného infraštruktúrneho problému (nie
preto, že by sa Claude vzdal), kvóta sa ti za daný príbeh
**automaticky vráti**.

Jeden chat má strop **20 správ od teba**. Ak ho dosiahneš,
aplikácia ťa pošle začať nový príbeh — staré zostanú dostupné na
prezeranie cez priame URL.

---

## Tvorba príbehu — krok za krokom

### Krok 1 — výber jazyka

Vpravo hore je prepínač jazykov (vlajky **SK / CZ / GB**). Jazyk
ovplyvňuje dve veci:
- jazyk rozhrania (popisy, tlačidlá, hlášky),
- jazyk samotného príbehu — Claude bude rozprávať a písať v tomto
  jazyku.

Jazyk môžeš meniť aj **počas behu** alebo na hotovom príbehu — text
sa preloží, obrázky ostanú rovnaké. Preklad sa cachuje, takže
prepnutie tam a späť je už okamžité.

### Krok 2 — rozhovor s asistentom

Na úvodnej obrazovke je chatové okno. Asistent (Claude v role
„spolutvorcu") sa ťa pýta na nápad, postavy, prostredie, náladu.
Pravidlá, ktoré aplikácia v MVP vyžaduje a o ktorých sa asistent
postará automaticky:

- **Najviac jeden chlapec / muž** (v anime štýle podľa Izuku
  Midoriya, MHA).
- **Najviac jedno dievča / žena** (v štýle Kyoka Jiro, MHA).
- **Matka** ako voliteľná tretia postava, no iba ak je v príbehu
  aspoň jedna z predošlých dvoch.
- Voliteľne **jedna ne-ľudská postava** (zviera, robot, plyšák…) a
  **dôležité predmety**, ktoré v príbehu rezonujú.
- **5 ilustrácií** rozdelených medzi maximálne 5 prostredí, pričom
  hlavná postava sa musí objaviť aspoň 2-krát.

Keď je asistent s briefom spokojný, zhrnie ti ho a požiada o
**potvrdenie**. Stačí napísať „áno" (alebo navrhnúť úpravu — vtedy
sa rozhovor predĺži). Po potvrdení sa pod kapotou spustí druhý
Claude agent, ktorý napíše samotný príbeh a rozplánuje 5
ilustračných scén. Trvá to rádovo 20–40 sekúnd.

### Krok 3 — sledovanie generovania

Po potvrdení briefu sa stránka prepne na detail príbehu
(`/<jazyk>/runs/<id>`). Hore vidíš:

- **Názov príbehu** (najprv krátky topic, potom finálny titul).
- **Stav** (Beží / Hotovo / Zlyhalo / Zrušené) a **počítadlo**
  „Hotové K z 5".
- **Tlačidlo „Zrušiť beh"** počas behu.
- Voliteľný **banner** s vysvetlením, ak beh ako celok zlyhal.

Pod tým sa zobrazuje samotný príbeh — odseky textu sa striedajú s
ilustráciami presne tak, ako budú vyzerať vo finálnej knihe. Kým
sa text alebo obrázok pripravuje, na jeho mieste je skeleton
(svetlosivá plocha v správnom tvare), takže layout neposkakuje.

Stránku **pokojne obnov alebo zavri** a vráť sa neskôr cez tú istú
URL — beh pokračuje na pozadí. Ak pri obnovení zistíš, že sa beh
od posledného otvorenia dokončil, uvidíš výsledok rovno; ak sa
prerušil reštart servera, aplikácia sa automaticky pokúsi
pripojiť späť k bežiacim GPU úlohám (viac v sekcii *Odolnosť*).

### Stavy ilustrácie

Každá z piatich kariet ilustrácií prejde vlastnou postupnosťou
stavov. Najčastejšie uvidíš:

| Štítok                         | Čo sa deje                                                            |
|--------------------------------|-----------------------------------------------------------------------|
| Čaká                           | Karta zatiaľ nezačala (čaká na voľný „slot")                          |
| Vytváranie promptov            | Claude formuluje, čo má GPU vykresliť                                 |
| **V rade na GPU**              | Úloha bola odoslaná na RunPod a čaká na voľného workera               |
| Vytváranie obrázka (pokus K/3) | Worker práve renderuje                                                |
| Hodnotenie                     | Claude vyhodnocuje hotový obrázok proti zadaniu                       |
| Úprava promptov                | Obrázok nesedel, Claude prepisuje prompty a skúša znova               |
| Prepracovanie konceptu         | Po troch neúspešných pokusoch Claude úplne prerobí scénu              |
| Prepracovanie prostredia       | Vo výnimočnom prípade aj prostredie — keď ani Claude nevie scénu „nakŕmiť" renderru |
| Prehodnotenie skorších pokusov | Po vyčerpaní auto-rozpočtu sa Claude vráti k histórii a vyberie najlepší skorší pokus |
| Spoločná tvorba (manuál)       | Auto-pipeline to vzdal, otvára sa chat s „spolu-ilustrátorom"         |
| Hotovo                         | Úspech, obrázok je zobrazený                                          |
| Nepodarilo sa                  | Aj manuálny rozpočet sa minul                                         |
| Zrušené                        | Beh bol zrušený                                                       |

**„V rade na GPU"** je dôležitý rozlišovač: znamená, že úloha čaká
na voľný hardware (typicky pri demo deployoch s 0–1 teplým
workerom). Sám sa stane stavu **Vytváranie obrázka** akonáhle
worker prácu prevezme. Ak by úloha v rade strávila viac než 30
minút, považuje sa to za výpadok kapacity a karta sa vzdá s
hláškou — kvóta sa za takéto zlyhanie vráti.

### Krok 4 — výsledok a interakcia

Keď je karta v stave **Hotovo**, ukáže obrázok priamo v príbehu.
Kliknutím sa otvorí v plnej veľkosti. Pri každej karte je
**trojbodkové menu** vpravo hore s týmito akciami (pokiaľ máš
ešte manuálny rozpočet):

- **„Vyrobiť znova"** — otvorí chat s manuálnym asistentom; pôvodný
  obrázok ostáva ako záloha, kým neakceptuješ nový.
- **„Zobraziť konverzáciu"** — viditeľné, ak karta už nejakou
  manuálnou interakciou prešla; ukáže ti dovtedy uložený dialóg a
  všetky pokusy.

V karte, na ktorej preklik na konceptový popover (malá ikona)
ukáže, **čo Claude o scéne vie** — koncept, charakter, prostredie a
príp. ne-ľudská entita v scéne. Slúži najmä na orientáciu, prečo
obrázok vyzerá tak, ako vyzerá.

### Krok 5 — zrušenie behu

Tlačidlo **„Zrušiť beh"** hore zastaví všetky čakajúce karty.
Pozor: obrázky, ktoré sú **práve teraz** na GPU, sa dokončia — len
ich aplikácia po dokončení už nepoužije (RunPod nemá API na
prerušenie bežiacej úlohy). Hotové karty zostávajú ako sú.

---

## Manuálna spolutvorba („spolu-ilustrátor")

Ak sa auto-pipeline (3 koncepty × 3 obrázky × prípadná záchrana
z histórie) nepodarí, karta sa **nepoloží do zlyhania** — namiesto
toho sa na jej mieste otvorí krátky chat s **„spolu-ilustrátorom"**
(Claude v inej role). Cieľ je dosiahnuť použiteľný obrázok v dialógu
s tebou.

Ako to vyzerá:

1. Asistent ťa privíta a stručne sa spýta, čo si v scéne želáš
   vidieť. Ja ako asistent **nevidím obrázky**, takže každú spätnú
   väzbu mu opíš slovami („zosvetli pozadie", „pridaj úsmev",
   „odstráň okuliare").
2. Keď máš spolu s ním konkrétny koncept, klikni **„Potvrdiť"**.
   Asistent ti vyrobí prompty a pošle ich na render.
3. Po každom rendere uvidíš obrázok priamo v paneli a malé tlačidlá
   **„Akceptovať"** alebo **„Iterovať"**. Akceptovanie ukončí
   manuálnu spolutvorbu a obrázok sa stane súčasťou príbehu.
   Iterovanie pridá ďalšiu spätnú väzbu a posunie sa na ďalší
   pokus.
4. Manuálny rozpočet je **5 pokusov** na jednu kartu. Ak ho minieš,
   karta sa preklopí do „Nepodarilo sa". Aj v takom prípade ostane
   menu **„Zobraziť konverzáciu"** dostupné, takže sa môžeš vrátiť
   k niektorému z 5 minulých pokusov a akceptovať ho dodatočne.

Manuálnu spolutvorbu vieš spustiť aj sám na **hotovom obrázku** cez
trojbodkové menu → „Vyrobiť znova". Vtedy sa pôvodný obrázok
zachová ako záloha a manuálny rozpočet sa neresetuje (zdieľa sa s
prípadným predošlým automatickým fallbackom tej istej karty).

---

## Odolnosť voči výpadkom

Pre demo nasadenie sa kompaktnosť a cena zmestili pred robustnosť,
no aplikácia má niekoľko mechanizmov, ktoré bežné krátkodobé
výpadky znášajú v poriadku:

- **Reštart servera počas behu** (deploy, krátky výpadok pamäte) —
  pri štarte sa všetky bežiace behy klasifikujú a tie, ktoré mali
  rozbehnutú GPU úlohu, sa **znovu pripoja k tomu istému RunPod
  job-id**. Stratíš nanajvýš poradové miesto v rade, nie celý
  rozpočet.
- **Strata SSE pripojenia** (prepnutie WiFi, uspatie počítača) —
  prehliadač sa automaticky reconnectne; pri tom dostaneš aktuálny
  snapshot a SSE pokračuje, akoby sa nič nestalo.
- **Vyplnená GPU fronta** — keď je úloha viac než 30 min v rade,
  karta sa vzdá s hláškou „v rade na GPU sa minul čas"; kvóta sa
  vráti.
- **Stuck worker** — keď GPU začne úlohu spracovávať, ale 10 minút
  nedoručí výsledok, aplikácia úlohu skúsi ešte 2-krát s iným
  semienkom (na inom workerovi). Až potom kartu vzdá.

---

## Často kladené otázky

**Koľko ma to bude stáť?**
Demo má vstavanú kvótu na kľúč — nakoľko aplikácia platí
prevádzkovateľ. Ty sa o ceny nestaráš, len o počet zostávajúcich
príbehov.

**Generovanie ide pomaly / niektoré karty stoja v „V rade na GPU".**
Pri malých demo deployoch obvykle nie sú trvalo bežiaci GPU workeri
— každá nová karta najprv prebudí worker (~30–60 s) a potom začne
renderovať. Päť kariet beží paralelne, takže môžeš v jednom čase
vidieť aj 5× „V rade". Vydrž, posunie sa to.

**Niektoré karty zlyhajú aj po manuále — čo s tým?**
Najčastejšia príčina je, že požadovaná scéna ide nad rámec toho,
čo MHA-LoRA model zvládne (príliš veľa postáv, exotické pozy,
silné štýlové rozpory). Manuálne menu **„Zobraziť konverzáciu"** ti
dovolí akceptovať ktorýkoľvek z 5 historických manuálnych pokusov;
často niektorý z nich vyzerá rozumne, len ho asistent vyhodnotil
ako nedokonalý.

**Môžem si svoj príbeh stiahnuť?**
Nateraz nie — obrázky aj text žijú výlučne na URL behu
(`/<jazyk>/runs/<id>`). Tú si však môžeš uložiť, otvoriť kedykoľvek
neskôr a v ľubovoľnom z troch jazykov.

**Funguje to na mobile?**
Aplikácia je responzívna a v prehliadači na telefóne funguje, ale
pri 5-stĺpcovej mriežke kariet je pohodlnejší tablet alebo
počítač.

**Sú moje vstupy niekde uložené?**
Áno — chat aj výsledný príbeh sa ukladajú v databáze backendu, aby
si sa k behu mohol vrátiť. Pre dema sú dáta privátne na úrovni
URL (kto má URL, vidí beh; URL nikde verejne nesúvisíme).

**Stratil som svoj prístupový kľúč.**
Kontaktuj prevádzkovateľa — kľúče sú jednorazovo generované,
neexistuje samoobslužné obnovenie. Ak máš ešte aktívnu reláciu v
prehliadači, na ktorej bol kľúč použitý, kľúč nájdeš v
`localStorage` pod kľúčom `accessKey`.

---

## Limity (zhrnutie)

| Limit                                          | Hodnota                              |
|------------------------------------------------|--------------------------------------|
| Počet ilustrácií na príbeh                     | presne 5                             |
| Pokusov na koncept                             | 3                                    |
| Konceptov na ilustráciu                        | 3                                    |
| Manuálnych pokusov na ilustráciu               | 5                                    |
| Užívateľských správ na chat                    | 20                                   |
| Celkom správ (vrátane asistentových) na chat   | 60                                   |
| Čakanie v GPU rade                             | 30 minút (potom zlyhanie)            |
| Čakanie na hotový obrázok po prevzatí workerom | 10 minút × 3 pokusy s novým semienkom|
| Podporované jazyky UI a príbehu                | SK, CZ, EN                           |

---

## Hlásenie problémov

Ak narazíš na chybu, ktorá v tejto príručke nie je opísaná,
napíš prevádzkovateľovi (osobe, ktorá ti poslala prístupový kľúč)
spolu s URL behu, na ktorom sa problém prejavil — z URL vie v
backende dohľadať detailný log konkrétneho behu.
