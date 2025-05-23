# Kuchangia katika Twiga 🦒

Tunakaribisha michango ya ukubwa wowote na kiwango chochote cha ujuzi. Kama mradi wa chanzo wazi, tunaamini katika kurudisha kwa wachangiaji wetu na tunafurahia kusaidia kwa mwongozo juu ya maombi ya kuvuta (PRs), uandishi wa kiufundi, na kugeuza wazo lolote la kipengele kuwa uhalisia.

> [!Kidokezo]
>
> **Kwa wachangiaji wapya 🚼:** Angalia [michango ya kwanza](https://github.com/firstcontributions/first-contributions) kwa taarifa muhimu juu ya kuchangia. Unaweza pia kuuliza maswali katika [Discord](https://discord.gg/bCe2HfZY2C) yetu.

Kwa kuchangia unakubali [**Kanuni zetu za Maadili**](https://github.com/Tanzania-AI-Community/twiga/blob/main/.github/CODE_OF_CONDUCT.md).

## Sera ya Kuunganisha kwa Maombi ya Kuvuta

Tunatumia mtiririko wa kazi wa [Gitflow](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow), ikimaanisha hatufanyi PR za vipengele vipya moja kwa moja kwenye tawi la `main`. Mabadiliko yoyote kwenye msimbo wa chanzo, yawe makubwa au madogo, kwanza huunganishwa kwenye `development`. Kisha yanasambazwa kwenye seva yetu ya maendeleo (kimsingi eneo letu la majaribio) ambapo tunaweza kutathmini ikiwa kuna mabadiliko yanayovunja. Baada ya kila hatua tunaweza kutuma PR kutoka `development` kwenda `main`.

> [!Muhimu]
> Tuma PR yako dhidi ya tawi la `development`, sio `main`. Hatukubali PR moja kwa moja kwenye `main`.

## Kutoka Fork hadi PR na Twiga

> [!Muhimu]
>
> Soma [Mwongozo wetu wa Git](https://github.com/Tanzania-AI-Community/twiga/blob/documentation/docs/sw/MWONGOZO_WA_GIT.md) ili kujifunza jinsi ya kuendeleza kwa ushirikiano kwenye Twiga kama mtaalamu.

Ili kuanza kuchangia kwenye Twiga, fuata hatua hizi:

1. Tengeneza fork ya hifadhi hii na uikopie kwenye kompyuta yako

> [!Onyo]
> Kumbuka kuondoa tiki kwenye "Nakili tawi la `main` pekee" ili upate tawi la `development` pia

2. Nenda kwenye tawi la `development`: `git checkout development`
3. Tengeneza tawi lako la kipengele kutoka tawi la `development`: `git checkout -b jina-la-tawi-lako`
4. Fuata hatua katika [mwongozo wetu wa kuanza](https://github.com/Tanzania-AI-Community/twiga/blob/documentation/docs/sw/KUANZA.md) ili kupata mradi ukifanya kazi kwenye kompyuta yako
5. (Bado haiwezekani) Endesha vipimo kuhakikisha kila kitu kinafanya kazi kama inavyotarajiwa
6. Hifadhi mabadiliko yako: `git commit -m "[aina]: ujumbe wa kuelezea commit"`
7. Sukuma kwenye tawi lako la mbali: `git push origin jina-la-tawi-lako`
8. Wasilisha ombi la kuvuta kwenye tawi la `development` la hifadhi ya awali

## Muundo wa Msimbo na Ukaguzi

Hakikisha unafuata miongozo ya mtindo wa kuandika msimbo iliyowekwa katika mradi huu. Tunaamini muundo thabiti wa msimbo huufanya uwe rahisi kuelewa na kutatua hitilafu. Kwa hivyo, tunatekeleza miongozo mizuri ya muundo kwa kutumia [_pre-commit_](https://pre-commit.com/) ili kuendesha kiotomatiki wapangaji wa Python [_black_](https://github.com/psf/black) na [_ruff_](https://docs.astral.sh/ruff/) kwa kila commit.

Usijali, huhitaji kujifunza njia mpya ya kupanga msimbo - inafanywa kwa ajili yako. Ingawa ikiwa una udadisi kuhusu kuwa na wapangaji na wakaguzi hawa wakati wa maendeleo yako (na sio tu wakati wa commit) tunapendekeza viendelezi hivi kwa VSCode (kihariri tunachokipendelea): [_Black Formatter_](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter) na [_Ruff_](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff). Ukishakamilisha hatua za 1-3 katika [Kutoka Fork hadi PR na Twiga](#kutoka-fork-hadi-pr-na-twiga), unaweza kusakinisha utegemezi kwa:

```bash
uv sync
source .venv/bin/activate
```

> [!Kumbuka]
> Kwa **Windows** amri ya pili itakuwa `.venv\Scripts\activate`

Kisha unaweza kusakinisha hooks za _pre-commit_ kwa:

```bash
pre-commit install

# matokeo
> pre-commit installed at .git/hooks/pre-commit
```

### Mfano wa _pre-commit_ Ikifanya Kazi

> [!Kumbuka]
> Tulichukua mfano huu bila aibu kutoka [gpt-engineer](https://github.com/gpt-engineer-org/gpt-engineer/tree/main). Asante!

Kama utangulizi wa mtiririko halisi wa kazi, hapa kuna mfano wa mchakato utakaokutana nao unapofanya commit:

Wacha tuongeze faili tuliyoibadilisha yenye makosa kadhaa, tuone jinsi hooks za pre-commit zinavyoendesha `black` na kushindwa.
`black` imewekwa kurekebisha kiotomatiki masuala inayopata:

```bash
git add random_code_file.py
git commit -m "ujumbe wa commit"
black....................................................................Failed
- hook id: black
- files were modified by this hook

reformatted random_code_file.py

All done! ✨ 🍰 ✨
1 file reformatted.
```

Unaweza kuona kwamba `random_code_file.py` iko kwenye hatua na sio kwenye hatua ya commit. Hii ni kwa sababu `black` imepanga na sasa ni tofauti na toleo ulilolichukua kwenye saraka yako ya kazi. Ili kurekebisha hii unaweza kukimbia `git add random_code_file.py` tena na sasa unaweza kufanya commit mabadiliko yako.

```bash
git status
On branch pre-commit-setup
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
    modified:   random_code_file.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
    modified:   random_code_file.py
```

Sasa wacha tuongeze faili tena ili kujumuisha commits za hivi karibuni na tuone jinsi `ruff` inavyoshindwa.

```bash
git add random_code_file.py
git commit -m "ujumbe wa commit"
black....................................................................Passed
ruff.....................................................................Failed
- hook id: ruff
- exit code: 1
- files were modified by this hook

Found 2 errors (2 fixed, 0 remaining).
```

Kama awali, unaweza kuona kwamba `random_code_file.py` iko kwenye hatua na sio kwenye hatua ya commit. Hii ni kwa sababu `ruff` imepanga na sasa ni tofauti na toleo ulilolichukua kwenye saraka yako ya kazi. Ili kurekebisha hii unaweza kukimbia `git add random_code_file.py` tena na sasa unaweza kufanya commit mabadiliko yako.

```bash
git add random_code_file.py
git commit -m "ujumbe wa commit"
black....................................................................Passed
ruff.....................................................................Passed
fix end of files.........................................................Passed
[pre-commit-setup f00c0ce] testing
 1 file changed, 1 insertion(+), 1 deletion(-)
```

Sasa faili yako imefanyiwa commit na unaweza kusukuma mabadiliko yako.

Mwanzoni hii inaweza kuonekana kama mchakato wa kuchosha (kuwa na kuongeza faili tena baada ya `black` na `ruff` kuibadilisha) lakini kwa kweli ni muhimu sana. Inakuruhusu kuona ni mabadiliko gani `black` na `ruff` wamefanya kwenye faili zako na kuhakikisha kuwa ni sahihi kabla ya kuzifanyia commit.

> [!Kumbuka]
> Wakati pre-commit inashindwa kwenye pipeline ya ujenzi wakati wa kuwasilisha PR unahitaji kukimbia `pre-commit run --all-files` ili kulazimisha muundo wa faili zote, sio tu zile ulizobadilisha tangu commit iliyopita.

Wakati mwingine `pre-commit` itaonekana kufanikiwa, kama ifuatavyo:

```bash
black................................................(no files to check)Skipped
ruff.................................................(no files to check)Skipped
check toml...........................................(no files to check)Skipped
check yaml...........................................(no files to check)Skipped
detect private key...................................(no files to check)Skipped
fix end of files.....................................(no files to check)Skipped
trim trailing whitespace.............................(no files to check)Skipped
```

Hata hivyo, unaweza kuona `pre-commit` ikishindwa kwenye pipeline ya ujenzi wakati wa kuwasilisha PR. Suluhisho la hili ni kukimbia `pre-commit run --all-files` ili kulazimisha muundo wa faili zote.

## Leseni

Kwa kuchangia kwenye Twiga, unakubali kwamba michango yako itakuwa chini ya [Leseni](https://github.com/Tanzania-AI-Community/twiga/blob/main/LICENSE) ya mradi.

Asante kwa nia yako ya kuchangia kwenye Twiga! Tunatazamia michango yako.
