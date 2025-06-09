# 🐣 Mwongozo wa Kuanza na WhatsApp Bandia

Ikiwa unataka kusanidi Twiga kwa njia rahisi zaidi bila kuhitaji akaunti ya Meta API, huu ndio mwongozo wako.

## Hatua ya Kwanza: Kutengeneza Mazingira ya Kazi

Anza kwa kusakinisha [**uv**](https://docs.astral.sh/uv/) meneja wa pakiti ya Python kwenye kompyuta yako. Hakikisha uko kwenye folda kuu ya hazina (repository) kisha endesha amri zifuatazo:

```bash
$ uv sync
$ source .venv/bin/activate
```

> [!Kumbuka]
>
> Kwa Windows tumia `.venv\Scripts\activate`

Utegemezi unapaswa kuwa umefanikishwa sasa, na mazingira yako ya shell yanapaswa kuwekwa kutumia mazingira halisi uliyounda. Sasa unaweza kuendesha programu ya FastAPI.

## 🤫 Unda faili ya `.env`

Anza kwa kutengeneza faili la `.env` kwenye folda kuu ya Twiga, kisha nakili na bandika maudhui ya `.env.template.simple` ndani yake. Ondoa maelezo ya maoni na nafasi zisizo za lazima. Muundo wa faili hii ni rahisi kuelewa.

## 🤖 Pata tokeni ya API ya Together AI au OpenAI

Ili kutumia mifano mikubwa ya lugha na embedding, tunahitaji huduma ya utambuzi yenye utendaji wa hali ya juu. Kwa chaguo msingi, mradi huu unatumia Together AI, ambayo hutupatia ufikiaji wa mifano mbalimbali ya chanzo huria inayoweza kuendeshwa kwa kutumia programu tumizi ya OpenAI (SDK).

- Ikiwa unataka kutumia Together AI, [unda akaunti](https://api.together.ai/) na upate API key
- kiwa unataka kutumia OpenAI, [unda akaunti](https://platform.openai.com/) na upate API key

Watoa huduma wote wawili wana kiwango cha bure chenye salio la kuanzia. Ongeza key kwenye faili `.env`:

```bash
LLM_API_KEY=$YOUR_API_KEY
```

> [!Muhimu]
>
> Tunapendekeza kutumia Together AI, lakini ikiwa utachagua OpenAI, kuna hatua chache za ziada za kufuata.

Tafuta katika hifadhi kwa kitambulisho `XXX:` na hakikisha unasasisha miongozo kulingana na maelekezo ili programu ya FastAPI iendeshe mifano ya program za OpenAI. Wakati wa kuandika hii, hii inapaswa kuwa ndani ya `app/config.py` na `app/database/models.py`.

## 📊 Ufuatiliaji wa LangSmith (Hiari)

Kwa ufuatiliaji na kurekebisha mazungumzo ya LLM, unaweza kuwezesha ufuatiliaji wa LangSmith:

1. Unda [akaunti ya LangSmith](https://smith.langchain.com/) (kuna safu ya bure)
2. Pata ufunguo wako wa API kutoka kwenye dashboard ya LangSmith
3. Ongeza usanidi kwenye faili yako ya `.env`:

```bash
LANGSMITH_API_KEY=$YOUR_LANGSMITH_API_KEY
LANGSMITH_PROJECT=twiga-whatsapp-chatbot
LANGSMITH_TRACING=True
```

Hii itawezesha ufuatiliaji wa kina wa mazungumzo yote ya LLM, matumizi ya zana, na vipimo vya utendaji.

> [!Kumbuka]
>
> Uunganishaji wa LangSmith ni wa hiari na hautaathiri utendaji wa msingi ikiwa hautasanidiwa.

## 🧠 Sanidi hifadhidata yako ya Postgres kwenye kompyuta yako

Kama vile inavyofaa kwa chatbot yoyote, Twiga inafuata historia za mazungumzo, watumiaji, madarasa, rasilimali (yaani, nyaraka zinazohusiana na madarasa), hifadhidata ya vector, n.k. Kwa bahati nzuri, kila kitu (ikiwemo hifadhidata ya vector) kinahifadhiwa katika meza za hifadhidata ya Postgres. Tunatumia Neon kuhudumia hifadhidata yetu, lakini kwa ajili ya maendeleo ya ndani tunatumia PostgreSQL.

Kwanza kabisa, unahitaji kuongeza vigezo vya mazingira vinavyohitajika kwenye faili yako ya `.env`:

```bash
DATABASE_USER=postgres
DATABASE_PASSWORD=$YOUR_PASSWORD
DATABASE_NAME=twiga_db
DATABASE_URL=postgresql+asyncpg://postgres:$YOUR_PASSWORD@db:5432/twiga_db
```

Kiungo hiki kinadhani unatumia hifadhidata ya Postgres kwenye bandari 5432, ambayo ni ya kawaida.

Hatua inayofuata, wacha tujenge picha zote za Docker na data za ndani, ambazo zinahitajika kwa hatua zinazofuata na kwa kuendesha programu. Amri hii itachukua muda, endesha:

```bash
make setup-env
```

## 🖥️ Sanidi programu ya FastAPI

Endesha amri ifuatayo ili kuendesha mradi:

```sh
docker-compose -f docker/dev/docker-compose.yml --env-file .env up
```

Au, kama mbadala,

```sh
make run
```

Ikiwa kila kitu kimeenda vizuri, seva yako iko tayari kukubaliana na maunganisho!

## 🥳 Hongera!

Ikiwa umefika hapa bila matatizo, sasa unapaswa kuwa na seva ya Twiga inayofanya kazi ambayo unaweza kuijaribu na WhatsApp bandia. Ikiwa bado unakutana na matatizo, jiunge na [Discord](https://discord.gg/bCe2HfZY2C) yetu na uandike swali lako kwenye `⚒-tech-support`.
