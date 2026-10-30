# Pravidla spolupráce s AI agentem (agent.md)

Tento dokument definuje závazná pravidla pro práci AI agenta na tomto projektu. Agent je povinen se těmito pravidly řídit při každé interakci.

## 1. Zákaz neautorizovaných zápisů a změn
* **Úpravy souborů**: Agent nesmí vytvářet, editovat ani mazat žádný soubor v projektu bez předchozího explicitního pokynu uživatele.
  * Pokud uživatel zadá explicitní příkaz k zápisu (např. *„vytvoř“*, *„uprav“*, *„přepiš“*, *„smaž“*), agent požadavek rovnou vykoná.
  * Pokud pokyn není jednoznačný nebo jde pouze o diskuzi / návrh, agent se **vždy napřed zeptá na potvrzení** a předloží návrh změn ke schválení.
* **Git operace (commit, push, branch)**: Agent nesmí provádět `git commit`, `git push` ani větvení/mazání větví bez výslovného souhlasu uživatele. Před provedením commitu vždy ukáže navrhovanou commit zprávu a seznam změněných souborů.

## 2. Jediný zdroj pravdy (Single Source of Truth)
* **README.md je jediný zdroj pravdy**: Veškeré informace o projektu – zadání, návrh architektury, datový model, zaznamenaná architektonická a procesní rozhodnutí, popis technologií, spouštěcí instrukce a historie změn – jsou udržovány v souboru `README.md`.
* **Udržování aktuálnosti**: Při každé změně architektury, modelu nebo rozhodnutí agent udržuje `README.md` aktuální, aby dokumentace nikdy nezaostávala za kódem.
* **Separace obsahu**: V souboru `agent.md` se nachází výhradně pravidla chování agenta a spolupráce. Žádné doménové ani technologické informace o samotném projektu se do něj nezapisují.

## 3. Dodržování akademických a technických zásad projektu
* **Třívrstvá architektura**: Striktní jednosměrné závislosti (Prezentační vrstva / API -> Aplikační / Doménová logika -> Datová vrstva / Repozitáře). Přísný zákaz psaní SQL dotazů přímo v obsluze HTTP endpointů.
* **Bezpečnost a data**:
  * Žádné přihlašovací údaje, tajné klíče ani hesla v repozitáři (vše přes proměnné prostředí a `.env`, které musí být v `.gitignore`).
  * Žádná reálná osobní data (výhradně syntetická testovací data).
* **Docker & Reprodukovatelnost**: Vše musí být spustitelné příkazem `docker compose up` bez jakýchkoliv skrytých manuálních kroků.
* **Srozumitelnost a obhajitelnost kódu**: Kód musí být čistý, čitelný, strukturovaný a plně pochopitelný pro studenta, který za něj ručí u obhajoby.
