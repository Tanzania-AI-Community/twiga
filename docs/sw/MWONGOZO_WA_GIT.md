# Mtiririko wa Maendeleo

Mradi huu unafuata mtiririko wa GitFlow uliorekebishwa kidogo ili kuhakikisha utulivu na kusimamia toleo kwa ufanisi.

## Muundo wa Matawi

- `main`: Inawakilisha hali ya uzalishaji wa sasa.
- `development`: Tawi kuu la ujumuishaji ambapo vipengele huunganishwa kwa ajili ya majaribio.
- `feature/*`: Matawi ya vipengele.
- `hotfix/*`: Matawi ya marekebisho ya haraka.
- `release/v*.*.*`: Matawi ya toleo.
- `chore/*`: Matawi ya matengenezo.

## Miongozo ya Mtiririko wa Kazi

1. **Maendeleo ya Kipengele**

   - Tengeneza tawi jipya la kipengele kutoka `development`:

     ```shell
     git checkout development
     git pull origin development
     git checkout -b feature/jina-la-kipengele-chako
     ```

     - Endeleza kipengele chako na weka commits zako wazi na zenye maana.
     - Ukiwa tayari, fungua ombi la kuvuta (pull request) ili kuunganisha tawi lako kwenye `development`.

2. **Ukaguzi wa Msimbo na Ujumuishaji**

   - Maombi yote ya kuvuta (pull requests) lazima yakaguliwe na msanidi programu mwingine angalau mmoja.
   - Ukaguzi wa CI lazima ufaulu kabla ya kuunganisha.
   - Baada ya kuidhinishwa, unganisha tawi la kipengele kwenye `development`.
   - Futa tawi la kipengele baada ya kuunganisha kwa mafanikio.

3. **Kuandaa Toleo**

   - Ukiwa umeridhika na hali ya tawi la maendeleo, endesha `./scripts/ci/create-release.sh x.y.z`

> [!Kumbuka]
>
> Hati tenzi (script) huunda tawi la toleo kutoka kwa maendeleo, husasisha namba za toleo, na kukuuliza ikiwa ungependa kutambua baadhi ya wachangiaji wapya wa mradi. Kisha itatengeneza ombi la kuvuta kutoka `release/x.y.z` kurudi kwenye `development` ambapo unaweza kufanya ukaguzi wa mikono.

4. **Toleo la Uzalishaji**

   - PR inapaswa kuwa imetengenezwa na hati tenzi kurudi kwenye `development`.
   - Baada ya ukaguzi wako na idhini, unganisha.
   - Hii itaanzisha tendo la GitHub la kutoa toleo ambalo linaunganisha toleo kwenye tawi kuu kiotomatiki, kuunda kumbukumbu ya mabadiliko, na kuweka lebo ya toleo.

5. **Marekebisho ya Haraka**

   - Kwa hitilafu muhimu katika uzalishaji, tengeneza tawi la marekebisho ya haraka kutoka `main`:
     ```shell
     git checkout main
     git checkout -b hotfix/maelezo-ya-jina
     ```
   - Rekebisha hitilafu na uunganishe (ruka PR) mabadiliko moja kwa moja kwenye `main` na kisha kwenye `development`.
   - Wajulishe timu kuhusu mabadiliko ili waweze kuvuta/kupangilia upya.

6. **Uboreshaji wa Msimbo**

   - Kwa masuala ya uboreshaji wa msimbo, tengeneza tawi la uboreshaji kutoka `development`:

   ```shell
   git checkout development
   git checkout -b refactor/maelezo-ya-jina
   ```

   - Fanya uboreshaji na ufungue ombi la kuvuta ili kuunganisha kwenye `development`.

### Sera ya Kuunganisha na Kupangilia Upya

Mradi huu unatumia mchanganyiko wa kupangilia upya na kuunganisha ili kudumisha historia safi na yenye taarifa:

1. **Matawi ya Vipengele:** Tumia upangiliaji upya kuweka matawi ya vipengele sawa na `development`:

   ```shell
   git checkout feature/kipengele-chako
   git rebase development
   ```

   Hii huunda historia ya mstari mnyoofu kwa kipengele, kuifanya iwe rahisi kuelewa na kukagua.

2. **Kuunganisha Vipengele:** Wakati kipengele kimekamilika, kiunganishe kwenye `development` kwa kutumia muunganisho usio wa haraka-mbele:

   ```shell
   git checkout development
   git merge --no-ff feature/kipengele-chako
   ```

   Hii hutunza historia ya tawi la kipengele katika tawi la `development`.

3. **Matawi ya Toleo na Marekebisho ya Haraka:** Tumia muunganisho (sio upangiliaji upya) wakati wa kujumuisha `development` kwenye matawi ya toleo, au wakati wa kuunganisha matoleo na marekebisho ya haraka kwenye `main` na `development`:

   ```shell
   git checkout main
   git merge --no-ff release/v1.x.x
   ```

   Hii hudumisha rekodi ya wakati matoleo na marekebisho ya haraka yalipojumuishwa.

> [!Onyo]
>
> Kamwe usipangilie upya matawi ambayo yamewekwa kwenye hifadhi ya mbali na yanaweza kuwa yanatumika na wanatimu wengine.

### Mbinu Bora

1. **Ujumbe wa Commit**: Tumia ujumbe wa commit ulio wazi na wenye maelezo. Fuata [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/):

   ```shell
   aina(upeo): maelezo

   [kiini cha hiari]

   [kijafungu cha hiari]
   ```

   Aina: feat, fix, docs, style, refactor, test, chore

   **Upeo** unahusu sehemu au moduli iliyoathiriwa na mabadiliko.

   **Maelezo** yanapaswa kuwa sentensi fupi, ya lazima inayoanza na kitenzi.

   **Kijafungu** kinaweza kutumika kurejelea masuala kwa ID, PR, au rasilimali nyingine.

   Mifano maalum:

   a) Kuongeza kipengele kipya:

   ```shell
   feat(knowledge-graph): tekeleza algoritimu mpya ya kuunganisha nodi

   - Sasisha endpoint ya API /api/v1/link-nodes kutumia algoritimu mpya

   Inafunga AIS-123
   ```

   b) Kurekebisha hitilafu:

   ```
   fix(api): tatua hali ya mashindano katika ombi la suluhisho la kuongeza kwa wakati mmoja

   - Ongeza kufuli la mutex katika LLMService
   - Tekeleza utaratibu wa kujaribu tena kwa suluhisho zilizoshindwa
   - Sasisha udhibiti wa makosa kutoa maoni ya kina zaidi

   Inarekebisha AIS-456
   ```

   c) Kuboresha msimbo uliopo:

   ```
   refactor(llm): boresha matumizi ya kianzio katika utengenezaji wa hoja

   - Andika upya QueryGenerator kutumia prompts zenye ufanisi zaidi
   - Punguza muktadha unaojirudia katika maswali ya ufuatiliaji
   - Tekeleza uwekaji wa kache kwa templeti za prompt zinazotumika mara kwa mara

   Uboreshaji wa utendaji wa ~15% katika matumizi ya kianzio
   ```

   d) Kusasisha nyaraka:

   ```
   docs(readme): sasisha mifano ya matumizi ya API

   - Ongeza mifano kwa endpoints mpya za dhana za kihesabu
   - Jumuisha sehemu ya mbinu bora za kushughulikia makosa
   ```

   e) Kufanya mabadiliko yanayovunja:

   ```
   feat(api)!: pitia upya uthibitishaji kwa usalama ulioongezeka

   - Badilisha JWT na OAuth2
   - Sasisha endpoints zote zilizolindwa kutumia mtiririko mpya wa uthibitishaji
   - Tekeleza mzunguko wa ufunguo na kumalizika

   MABADILIKO YANAYOVUNJA: API sasa inahitaji tokeni ya OAuth2 badala ya JWT.
   ```

2. **Maombi ya Kuvuta**:

   - Weka PR ndogo na zilizolenga kipengele kimoja au marekebisho ya hitilafu.
   - Jumuisha maelezo ya mabadiliko na muktadha wowote unaohitajika.
   - Unganisha masuala yanayohusiana katika maelezo ya PR.

3. **Ukaguzi wa Msimbo**:

   - Kagua ubora wa msimbo, utendaji, na uzingatiaji wa viwango vya mradi.
   - Tumia kipengele cha mapendekezo cha GitHub kupendekeza mabadiliko.
   - Idhinisha tu wakati maoni yote yameshughulikiwa.

4. **Kuweka Toleo**:

   - Fuata kuweka toleo kwa kisemantiki (MAJOR.MINOR.PATCH).
   - Sasisha nambari ya toleo katika faili zinazofaa kabla ya kuunda toleo.

5. **Upimaji**:
   - Hakikisha vipimo vyote vinapita kabla ya kuwasilisha PR.
   - Jumuisha vipimo vipya kwa vipengele vilivyoongezwa.
