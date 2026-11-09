# Muhtasari wa mazungumzo

Twiga huhifadhi historia iliyofupishwa kando na ujumbe asilia. Tazama
[mwongozo wa uhifadhi](UHIFADHI_WA_MUHTASARI.md) na [usanidi wa WhatsApp bandia](KUANZA_NA_WHATSAPP_BANDIA.md).

## Runtime

Runtime inahitaji utegemezi wa `tokenizers` uliowekwa kwenye lock na faili zote
mbili zilizofungwa kwa toleo maalum katika `app/assets/tokenizers/`; tazama
[vyanzo na leseni](../../app/assets/tokenizers/README.md). Provider inayotumika ni
Together, kwa model ya msingi `zai-org/GLM-5.3-Flash` na fallback
`deepseek-ai/DeepSeek-V4.1-Flash`. Michanganyiko mingine hukataliwa. Runtime
huhesabu maandishi yote ya muhtasari unaohifadhiwa, pamoja na wrapper na
provenance, kwa tokenizer zote mbili na huhifadhi hesabu kubwa zaidi bila kujali
model iliyojibu. Faili hupakiwa ndani ya kompyuta; hakuna tokenizer au model
weights zinazopakuliwa wakati wa ombi la mazungumzo.

Sera ya sasa hutumia chunk za herufi 1,500, soft summarization zaidi ya chunk 25
zinazosubiri na hard preparation zaidi ya 30. Hizi si mipaka ya idadi ya rows za
ujumbe. Bajeti ya batch hai kwa pamoja ni tokeni 75,000; rollup ni 25,000.
Compaction huhifadhi batch tano za mwisho, ujumbe asilia na rekodi za coverage ya
batch zilizowekwa kumbukumbu. Rollup mpya hujengwa kwa kutumia rollup ya awali na
batch za zamani zinazoongezwa.

## Kuandaa muktadha wa model

Kwa kila jaribio la generation, agent hunasa ujumbe wa buffer kama tuple kabla ya
preparation. Preparation hukubali ujumbe wa `user` unaoonekana na uliohifadhiwa,
huchukua snapshot thabiti na huchagua historia inayostahili hadi mpaka wa mwisho
wa ujumbe ulionaswa kwa `(created_at, id)`. Ujumbe unaofika baadaye ni wa jaribio
linalofuata. Ujumbe mpya ukifika wakati wa preparation au kazi ya agent, jaribio
hutupwa na buffer hunaswa tena.

Muktadha hupangwa hivi: system prompt kuu; rollup ikiwa ipo; muhtasari wa batch
hai kwa sequence; kisha historia raw na ujumbe wa sasa kwa `(created_at, id)`.
Muhtasari ni maudhui ya kihistoria ya assistant, si system instructions. Ujumbe
raw huondolewa marudio kwa ID; tool messages, assistant tool calls, ujumbe
uliofichwa na flow markers hutengwa. Mwongozo wa uhifadhi una eligibility kamili.

Zaidi ya hard threshold, historia ya zamani hufupishwa huku kila ujumbe wa sasa
wa user ukibaki mzima na raw, hata ukiwa mkubwa kuliko threshold. ID za sasa
hazipaswi kupishana na coverage yoyote ya kudumu, hata ya batch zilizofanyiwa
compaction. Preparation hukagua hilo wakati wa kusoma, stale retry na baada ya
commit; formatter pia hukataa overlap yoyote ya summary/raw. Ujumbe wa sasa
hauondolewi kimya kimya na summary iliyopo hairekebishwi kutatua overlap. Uandishi
wa stale hujaribiwa tena mara moja kwa snapshot mpya; mgongano unaorudiwa, hesabu
zisizo sahihi, timeout au kosa lingine la preparation huzuia main agent call na
hutumia njia ya kawaida ya ujumbe wa hitilafu.

## Jibu lililokubaliwa na soft summary

Baada ya matokeo kukubaliwa, request context hubeba ID za vyanzo vilivyokubaliwa
na ujumbe wa sasa hadi delivery. Rekodi raw za model/tool huhifadhiwa; jibu raw
la mwisho la assistant hufichwa kwenye historia. Messaging huhifadhi maandishi
ya matokeo yanayoonekana, kisha hujaribu soft summary kabla ya kutuma mara ya
kwanza. Soft hutumia tu ID za vyanzo vilivyokubaliwa na matokeo mapya, kwa hiyo
ujumbe uliofika baadaye hubaki ukisubiri. Ikiwa hard threshold ilifikiwa kwenye
jaribio lolote la ombi hilo, soft hurukwa ili kulinda ujumbe. Kosa la soft
halibadilishi summary ya kudumu wala halizuii delivery. Rekodi inayoonekana
inaonyesha maudhui yaliyotengenezwa, si uthibitisho wa delivery.

Citations na LaTeX hutumia maandishi yanayoonekana kama historia, kisha hutumwa
kama picha au maandishi inavyofaa. Lesson plan huhifadhi maandishi yake mara moja
kabla ya kujaribu PDF au text fallback. Exam huhifadhi matokeo yaliyosafishwa
(au ID, subject na topics za exam iliyoandaliwa inapohitajika) kabla ya kutuma
nyaraka; ujumbe wa hali ya delivery unaofuata hubaki raw hadi mzunguko mwingine.
Hakuna maandishi yanayotolewa kutoka PDF kwa historia ya summary. Commands,
matokeo yaliyokataliwa na njia za hitilafu hazitumii soft hook hii.

## Madirisha ya muktadha wa model

[Catalog ya Together](https://docs.together.ai/docs/serverless/models), iliyoangaliwa
2026-11-09, inaonyesha tokeni 1,048,575 kwa `zai-org/GLM-5.3-Flash` na 1,000,000
kwa `deepseek-ai/DeepSeek-V4.1-Flash`. Hizi si nafasi za maandishi ya mtumiaji
pekee: system, historia, zana na matokeo yake huhesabiwa, na nafasi ya output
inahitajika. Dirisha dogo la DeepSeek ndilo la kuzingatia kwa model zote mbili.
Bajeti za summary hazipimi ombi lote; runtime haina mfumo kamili wa bajeti yake.

## Muhtasari uliohifadhiwa tayari

Kabla ya kuwasha runtime hii ikiwa summaries zipo, simamisha waandishi wa
summary na pitia/hesabu upya batch zote hai na rollup kwa msingi mpya. Hifadhi
maandishi, vyanzo na coverage. Snapshot yenye hesabu isiyolingana hukataliwa;
ikivuka bajeti tatua hali hiyo kabla ya kuwasha runtime. Hakuna uhamishaji wa
hesabu kiotomatiki. Hifadhidata mpya haina hesabu za zamani za kuhamisha.

## Muda wa mwisho

Operesheni ya summary ina deadline ya sekunde 60. Kila jaribio la Together lina
kiwango cha sekunde 20 na kila router call sekunde 50, au chini ikiwa usanidi
unataka hivyo. Kazi ya awali ya hifadhidata/model hupunguza muda unaobaki kwa
rollup au shortening. Mipaka hii haiathiri defaults za router kwa wapigaji wengine.

## Vipimo

Weka `ISSUE92_TEST_DATABASE_URL` wazi kwa hifadhidata ya PostgreSQL ya muda yenye
jina linaloanza `issue92_test`, na pgvector iliyosakinishwa. Fixtures huunda na
kuondoa schema kwa kila jaribio na hazitumii URL ya programu kiotomatiki.
Vipimo vya generic service hutumia counters zilizoingizwa na model calls bandia;
runtime hutumia tokenizer zote mbili halisi. Endesha:

```sh
.venv/bin/python -m pytest tests/services/test_conversation_summary_service.py tests/services/test_conversation_summary_runtime.py tests/clients/test_client_base.py tests/clients/test_agent_client.py tests/services/test_messaging_service.py tests/utils/test_llm_failover.py -q -m 'not integration'
```

Kwa PostgreSQL, migration na lifecycle halisi, weka URL hapo juu kisha endesha:

```sh
.venv/bin/python -m pytest tests/database/test_conversation_summary_db.py tests/database/test_conversation_summary_migrations.py tests/services/test_conversation_summary_service.py tests/services/test_conversation_summary_lifecycle.py -q
```

Bila URL, kesi za PostgreSQL hurukwa; migration round trip pia hurukwa bila
pgvector. Kuruka huko huacha uthibitisho unaohitajika wa PostgreSQL haujakamilika.
