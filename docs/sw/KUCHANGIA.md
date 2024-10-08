
# Mwongozo wa Mchangiaji

Tunakaribisha michango ya kila aina na kiwango chochote cha ujuzi. Kama mradi wa chanzo wazi, tunaamini katika kurudisha kwa wachangiaji wetu na tunafurahia kusaidia kwa mwongozo juu ya PRs, uandishi wa kiufundi, na kugeuza wazo lolote la kipengele kuwa uhalisia.

> [!Tip]
>
> **Kwa wachangiaji wapya:** Angalia [https://github.com/firstcontributions/first-contributions](https://github.com/firstcontributions/first-contributions) kwa taarifa muhimu juu ya kuchangia.

## 🖥️ Mwongozo Mfupi wa Kuchangia

Kwa kuwa mradi huu unatumia mchanganyiko wa huduma za wingu, utegemezi, na API's na alama za idhini, tunafanya kazi ili kufanya uzoefu wa maendeleo ya ndani kuwa laini zaidi kwa wachangiaji wa chanzo wazi ( open source ). Katika baadhi ya matukio, unaweza kuhitajika kutumia vitambulisho vyako mwenyewe (kama vile _funguo za API za OpenAI_).

Ikiwa unataka kuweka mradi huu kwenye kompyuta yako mwenyewe, tunapendekeza ukamilishe hatua zifuatazo. Anza kwa kufanya forki :fork*and_knife: ya hifadhi hii. Wakati wa kuforki, hakikisha umeondoa alama ya tiki kwenye "nakili tawi la `main` pekee.

Ukishamaliza kuiga, unaweza kuikopakwenye kompyuta yako. Inapendekezwa kutumia Visual Studio Code kama IDE yako, lakini si lazima. Fanya hatua zifuatazo kwenye folda unayotaka kuhifadhi msimbo (code).

```sh
git clone git@github.com:{USERNAME}/twiga.git
git checkout -b {YOUR BRANCH}
```

Hii inaunda tawi jipya kwa jina unalochagua, ili uweze kufanya kazi kwenye kipengele au tatizo lolote linalokuvutia.

### Kuandaa Mahitaji ya Msingi

Ikiwa unataka kuendesha seva ya ndani na kujaribu Twiga kwenye WhatsApp moja kwa moja, tunapendekeza kufuata baadhi ya hatua kutoka kwa [mafunzo](https://github.com/daveebbelaar/python-whatsapp-bot) yaliyotengenezwa na Dave Ebbelaar. Kumbuka kwamba haya yote ni bure kufanya.

1. Create a Meta [developer account](https://developers.facebook.com/) and [business app](https://developers.facebook.com/docs/development/create-an-app/)
2. [Chagua namba za simu](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-1-select-phone-numbers)
3. [Tuma ujumbe na API](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-2-send-messages-with-the-api)
4. [Sanidi webhooks na ngrok](https://github.com/daveebbelaar/python-whatsapp-bot?tab=readme-ov-file#step-3-configure-webhooks-to-receive-messages)
5. Tengeneza [Akaunti ya OPENAI](https://platform.openai.com/docs/quickstart) ili upate **funguo za API**
6. Kisha unda [msaidizi](https://platform.openai.com/docs/assistants/overview) ili upate **Kitambulisho cha Msaidizi** (mpe mfumo wa prompt uliotolewa katika __TBD__)

Tengeneza faili la `.env` ukitumia `example.env`kama kielezo na uondoe maelezo na nafasi zote.


### Kompyuta Yako



Anza kwa kusakinisha meneja wa kifurushi cha Python kinachoitwa [**Poetry**](https://python-poetry.org/) kwenye kompyuta yako. Hakikisha uko kwenye folda ya mizizi ya hazina na unakimbia amri `poetry install`. Hii itasoma utegemezi unaohitajika kuendesha Twiga na kuupakua kwenye folda ya `.venv/`. Kisha kimbia `poetry shell` ili kuwasha ganda kwenye mstari wa amri kwa kutumia mazingira yaliyotengenezwa. Hatimaye, kimbia mojawapo ya amri zifuatazo ili kuanza seva ya FastAPI. Hizi ni seva za maendeleo, kumaanisha kuwa zinaweza kubadilika moja kwa moja.

```sh
fastapi dev app.main.py
```

```sh
uvicorn app.main:app --port 8000 --reload
```
Ili API ya Meta ifikie seva yako ya FastAPI ya ndani, unahitaji kuwasha njia ya API ya ngrok kwa amri ifuatayo.

```sh
ngrok http 8000 --domain {YOUR-GATEWAY-NAME}.ngrok-free.app
```

Ikiwa kila kitu kimesanidiwa vizuri, unapaswa kuwa na toleo la msingi la Twiga likifanya kazi ambalo unaweza kujaribu kupitia WhatsApp.

### Ndani ya Kontena na Docker


Tunatumia pia Docker kwa Twiga ili uweze kufanya kazi kwenye mradi huu kwenye mazingira yaliyotengwa ili kuepuka matatizo ya utegemezi na matoleo ambayo yanaweza kutokea kwenye kompyuta yako. Faili zetu za `Dockerfile` na `docker-compose.yml` zinahakikisha kuwa toleo sahihi la Python na Poetry linasakinishwa kwenye mfumo. Unachohitaji ni kuwa na [Docker](https://www.docker.com/) inayoendesha kwenye kompyuta yako.

Tunapendekeza usome kuhusu Docker ili kujifunza kuhusu picha (images), upakiaji (containerization), na volumes. Tunatumia Docker Compose na volumes ili hata uwe na uwezo wa kubadilika moja kwa moja katika kontena linaloendesha (soma `docker-compose.yml` na `Dockerfile` kwa maelezo zaidi). Ukishaweka Docker unaweza kukimbia amri ifuatayo.

```sh
docker compose up
```

Ili API ya Meta ifikie seva yako ya FastAPI ya ndani, unahitaji kuwasha njia ya API ya ngrok kwa amri ifuatayo.

```sh
ngrok http 8000 --domain {YOUR-GATEWAY-NAME}.ngrok-free.app
```

## 🤝 Shiriki Mchango Wako Nasi
