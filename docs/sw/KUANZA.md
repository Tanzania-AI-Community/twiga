> [!Tahadhari]
>
> Hati hii inadhani tayari umekamilisha hatua za 1-3 kwenye `docs/CONTRIBUTING.md`.

# 🐣 Mwongozo wa Kuanza

Tafuta katika hifadhi kwa kitambulisho `XXX:` na hakikisha unasasisha miongozo kulingana na maelekezo ili programu ya FastAPI iendeshe mifano ya program za OpenAI. Wakati wa kuandika hii, hii inapaswa kuwa ndani ya `app/config.py` na `app/database/models.py`.
## 📊 Ufuatiliaji wa LangSmith (Hiari)

LangSmith hutoa vipengele vya ufuatiliaji na kurekebisha mazungumzo ya LLM. Ili kuwezesha ufuatiliaji:

1. Unda [akaunti ya LangSmith](https://smith.langchain.com/) (kuna safu ya bure)
2. Pata ufunguo wako wa API kutoka kwenye dashboard ya LangSmith
3. Ongeza usanidi kwenye faili yako ya `.env`:

```bash
LANGSMITH_API_KEY=$YOUR_LANGSMITH_API_KEY
LANGSMITH_PROJECT=twiga-whatsapp-chatbot
LANGSMITH_TRACING=True
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Ukiwezesha LangSmith, utaweza:

- Kufuatilia maombi na majibu yote ya LLM
- Kuangalia matumizi na utendaji wa zana
- Kurekebisha mtiririko wa mazungumzo
- Kuchambua mazungumzo ya watumiaji na tabia za mfano

> [!Kumbuka]
>
> Uunganishaji wa LangSmith ni wa hiari. Ikiwa hautausanidi, programu itafanya kazi kawaida bila ufuatiliaji.anza

Ikiwa unataka kuendesha Twiga kwenye kompyuta yako na hata kujaribu chatbot yako mwenyewe, huu ndio mwongozo wako.

> [!Kumbuka]
>
> Kwa usanidi rahisi zaidi na WhatsApp bandia, tafadhali fuata maelekezo katika [KUANZA_NA_WHATSAPP_BANDIA.md](./KUANZA_NA_WHATSAPP_BANDIA.md).

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

Anza kwa kutengeneza faili la `.env` kwenye folda kuu ya Twiga, kisha nakili na bandika maudhui ya `.env.template` ndani yake. Ondoa maelezo ya maoni na nafasi zisizo za lazima. Muundo wa faili hii ni rahisi kuelewa. Sehemu inayofuata ya hati hii itakusaidia kujaza faili la `.env` kwa maadili yako mwenyewe ili Twiga iweze kufanya kazi vizuri.

## 👾 Maandalizi ya usanidi

> [!Kumbuka]
>
> > Hatua nyingi zilizo katika [mahitaji ya usanidi](#-setup-prerequisites) zinatokana na [mafunzo](https://github.com/daveebbelaar/python-whatsapp-bot) yaliyoandaliwa na Dave Ebbelaar.

Katika faili [`architecture.md`](https://github.com/Tanzania-AI-Community/twiga/blob/main/docs/en/ARCHITECTURE.md), unaweza kuona vipengele vikuu vya miundombinu inayotumika kuendesha Twiga. Hata hivyo, si lazima kutumia Neon na Render, kwani unaweza kuzibadilisha na toleo la 'local'. Lakini, unaweza kuzijaribu ikiwa unapenda, kwani zinatoa matoleo ya bure yenye ukarimu mkubwa.

Kwa kuzingatia hayo, unapaswa kuanza kwa kuunda akaunti ya **Meta API**.

### Akaunti ya Meta (Sio lazima kwa kutumia WhatsApp bandia)

1. Tengeneza akaunti ya msanidi programu wa Meta [hapa](https://developers.facebook.com/)

2. Unda [app ya biashara](https://developers.facebook.com/docs/development/create-an-app/) ndani ya akaunti yako ya msanidi programu

   https://github.com/user-attachments/assets/34877110-2023-4520-b134-ca9efd2f76bb

3. Sanidi programu kwa WhatsApp

   Mara tu unapobofya `Create app` kutoka hatua ya 2, utaelekezwa kwenye **Dashboard ya App**. Chagua `Set up` chini ya kisanduku cha WhatsApp. Hii itaunganisha bidhaa za **WhatsApp** na **Webhooks** kwenye programu yako.

   Nenda kwenye **Mipangilio ya Msingi ya App** katika menyu ya upande na nakili **App ID** na **App Secret** kisha ziweke kwenye faili `.env`.

```bash
META_APP_ID="<App ID>"
META_APP_SECRET="<App Secret>"
```

4. Pata Namba ya Simu na Tengeneza Access Token

   Unapounda programu ya WhatsApp, unapewa **Namba ya Mtihani ya Bure** kutoka Meta, inayokuruhusu kujaribu chatbot yako na watumiaji 5. Nenda kwenye **WhatsApp/API Setup** kwenye menyu ya upande. Ikiwa Namba ya Mtihani haijachaguliwa tayari, chagua na nakili **Phone Number ID**.

   Unaweza pia kuunda **Access Token ya saa 24** kwa kubofya **Generate access token**. Hakikisha umeongeza thamani hizi kwenye faili yako ya `.env`.

   ```bash
   WHATSAPP_CLOUD_NUMBER_ID="<Phone number ID>"
   WHATSAPP_API_TOKEN="<Access token>"
   ```

> [!Maelezo]
>
> Unaweza kuunda **Access Token** ya siku 60 (au zaidi) kwa kufuata hatua zilizo [hapa](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-2-send-messages-with-the-api).

Baada ya hatua hii, unaweza kuongeza namba yako ya simu ndani ya **Dashboard** kama **namba ya mpokeaji** ili programu iwe na ruhusa ya kukutumia ujumbe. Fuata tu hatua zinazotolewa kwenye Dashboard. Kisha, unaweza kutuma **ujumbe wa template** kwa kutumia API ili kuhakikisha inafanya kazi.

> [!Tahadhari]
>
> Ni lazima ujibu ujumbe huu wa template kwenye simu yako ili chatbot iwe na ruhusa ya kukutumia ujumbe mwingine zaidi ya template messages.

## 🪝 Sanidi Webhooks kwa kutumia [Ngrok](https://ngrok.com/)

Unapoendesha programu ya **FastAPI**, kompyuta yako itasikiliza maombi kwenye seva ya ndani kupitia `http://127.0.0.1:8000` (localhost). Ili kuifanya seva hii ionekane kwenye mtandao wa kimataifa, tunatumia **Ngrok**, ambayo hutoa endpoint binafsi (na ya bure) inayoelekeza maombi yote kwenye localhost yetu.

Kisha, nakili **Ngrok Authtoken** yako ya kibinafsi (inapatikana pia ndani ya sehemu ya **Getting Started**) na endesha amri ifuatayo kwenye terminal yako.

```bash
ngrok config add-authtoken $YOUR_AUTHTOKEN
```

Katika upau wa kando wa kushoto wa dashibodi ya Ngrok, fungua **Domains** kisha bonyeza **New Domain** ili upate Ngrok endpoint yako ya bure. Baada ya kukamilisha hili, endesha amri ifuatayo kwenye laini ya amri yako.

```bash
ngrok http 8000 --domain {your-free-domain}.ngrok-free.app
```

Ikiwa kila kitu kimeenda vizuri, matokeo ya laini ya amri yanapaswa kuonyesha kuwa ngrok inatuma maombi kutoka kwa domain ya bure kwenda kwenye localhost yako kwenye port 8000.

> [!Kumbuka]
>
> Haijaunganishwa bado na programu yako ya WhatsApp, lakini tutarudi kwenye hilo mwishoni mwa mwongozo huu..

## 🤖 Pata tokeni ya API ya Together AI au OpenAI

Ili kutumia mifano mikubwa ya lugha na embedding, tunahitaji huduma ya utambuzi yenye utendaji wa hali ya juu. Kwa chaguo msingi, mradi huu unatumia Together AI, ambayo hutupatia ufikiaji wa mifano mbalimbali ya chanzo huria inayoweza kuendeshwa kwa kutumia programu tumizi ya OpenAI (SDK).

- Ikiwa unataka kutumia Together AI, [unda akaunti](https://api.together.ai/) na upate API key
- kiwa unataka kutumia OpenAI, [unda akaunti](https://platform.openai.com/) na upate API key

Watoa huduma wote wawili wana kiwango cha bure chenye salio la kuanzia. Ongeza key kwenye faili `.env`

```bash
LLM_API_KEY=$YOUR_API_KEY
```

> [!Muhimu]
>
> Tunapendekeza kutumia Together AI, lakini ikiwa utachagua OpenAI, kuna hatua chache za ziada za kufuata.

Tafuta katika hifadhi kwa kitambulisho `XXX:` na hakikisha unasasisha miongozo kulingana na maelekezo ili programu ya FastAPI iendeshe mifano ya program za OpenAI. Wakati wa kuandika hii, hii inapaswa kuwa ndani ya a`app/config.py` na `app/database/models.py`

## 🧠 Sanidi hifadhidata yako ya Postgres kwenye kompyuta yako.

Kama vile inavyofaa kwa chatbot yoyote, Twiga inafuata historia za mazungumzo, watumiaji, madarasa, rasilimali (yaani, nyaraka zinazohusiana na madarasa), hifadhidata ya vector, n.k. Kwa bahati nzuri, kila kitu (ikiwemo hifadhidata ya vector) kinahifadhiwa katika meza za hifadhidata ya Postgres. Tunatumia Neon kuhudumia hifadhidata yetu, lakini kwa ajili ya maendeleo ya ndani tunatumia PostgreSQL.

Kwanza kabisa, unahitaji kuongeza vigezo vya mazingira vinavyohitajika kwenye faili yako ya `.env`.

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

## 🖥️ Sanidi programu ya FastAPI.

Endesha amri(command) ifuatayo ili kuendesha mradi:

```sh
docker-compose -f docker/dev/docker-compose.yml --env-file .env up
```

Au, kama mbadala,

```sh
make run
```

Ikiwa kila kitu kimeenda vizuri, seva yako iko tayari kukubaliana na maunganisho!

## 📱 Malizia kiunganishi cha whatsapp

Hatua ya mwisho ni kuunganisha endpoint yako ya Ngrok na bot yako ya WhatsApp.

Anza kwa kwenda kwenye faili yako ya `.env` na tengeneza **Tokeni ya Uthibitisho**. Inaweza kuwa chochote unachotaka, kama neno la siri:

```bash
WHATSAPP_VERIFY_TOKEN=$YOUR_RANDOM_VERIFY_TOKEN
```

Sasa, hakikisha kuwa endpoint yako ya Ngrok inafanya kazi kwenye laini ya amri (terminal) na anzisha upya programu ya FastAPI kwenye laini nyingine ya amri ili itambue faili ya `.env` iliyobadilika. Jinsi ya kuendesha haya ilielezewa kwenye sehemu za Sanidi webhooks na Ngrok na Sanidi programu ya FastAPI.
[Sanidi webhooks na Ngrok](#-configure-webhooks-with-ngrok) na [ Sanidi programu ya FastAPI](#️-set-up-the-fastapi-application).

Sasa, kwenye Dashibodi yako ya Meta App, nenda kwenye **WhatsApp > Configuration**. Katika sehemu ya Webhook, jaza maadili ya **Callback URL** na **Verify Token**.

> [!Muhimu]
>
> URL ya callback inapaswa kuwa `https://{your-free-domain}.ngrok-free.app/webhooks` na tokeni ya uthibitisho inapaswa kuwa ile uliyofafanua kwenye faili ya `.env` `$YOUR_RANDOM_VERIFY_TOKEN`

Mara tu unapobonyeza **Verify and save**, ombi la uthibitisho litatumwa kwa seva yako kupitia endpoint ya Ngrok (unapaswa kuona maandiko yanavyoonekana katika terminal zote mbili). Hatimaye, songa chini hadi sehemu ya Webhook Fields na **jiandikishe** kwa endpoint ya messages.

<img width="1215" alt="Screenshot 2024-11-28 at 13 01 39" src="https://github.com/user-attachments/assets/d5f24761-710f-43fb-a075-345d546e1309">

Ikiwa ulijaza faili la `.env` kwa usahihi, unapaswa kuona mafanikio kwenye maandiko na uthibitisho wa kuona kwenye Dashibodi ya Meta App. Vinginevyo, huenda ukaona logi ya `403 forbidden` kwenye seva yako.

## 🥳 Hongera!

Ikiwa umefikia hapa bila matatizo, sasa unapaswa kuwa na seva inayofanya kazi kwa Twiga ambayo unaweza kutuma ujumbe moja kwa moja kutoka kwa akaunti yako ya WhatsApp. Ikiwa unakutana na matatizo hadi hatua hii, jiunge na [Discord](https://discord.gg/bCe2HfZY2C) yetu na andika swali lako katika `⚒-tech-support`.
