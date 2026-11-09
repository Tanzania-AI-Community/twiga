# Uhifadhi wa muhtasari wa mazungumzo

PostgreSQL huhifadhi muhtasari kando na `messages`. `conversation_summary_state`
ina hadi rekodi moja kwa mtumiaji: rollup ya historia ya zamani, idadi ya tokeni,
sequence ya mwisho iliyounganishwa, toleo na muda wa kusasishwa. Thamani za
mwanzo ni rollup tupu na sufuri; uandishi wa kwanza uliofanikiwa huunda toleo 1.
`conversation_summary_batches` huhifadhi muhtasari uliopangwa na chanzo chake.
Meza zote mbili zinarejelea mtumiaji kwa `ON DELETE CASCADE`.

Sequence ya batch ni chanya na ya kipekee kwa kila mtumiaji. Endpoints ni ujumbe
wa kwanza na wa mwisho kwa mpangilio wa `(created_at, id)`, si mipaka ya coverage:
ID zinaweza kuwa na mapengo au kufika baadaye. `covered_message_ids` ni orodha
ya JSON isiyo tupu yenye ID halisi, hata baada ya compaction. Toleo na mpaka wa
state ni sifuri au zaidi, idadi ya tokeni za rollup ni 0–25,000 na idadi ya
batch si hasi. Batch mpya huanza bila compaction; timestamps huanza kwa muda wa
sasa. Batch iliyounganishwa lazima iwe na maandishi tupu na tokeni sifuri.
Kuna index ya batch hai kwa mtumiaji na sequence.

## Kusoma snapshot

`get_conversation_summary_snapshot(user_id)` hutumia muamala mfupi wa kusoma tu
wa repeatable-read na kurudisha data isiyofungamana na session: rollup, toleo,
sequence inayofuata, batch hai, ID zote zilizofunikwa na ujumbe unaosubiri. Bila
state, toleo ni `None`, rollup ni tupu na sequence inayofuata ni 1. Ujumbe wa
mtumiaji huyo lazima uwe unaonekana kwenye mazungumzo na uwe na role `system`,
`user` au `assistant`. Ujumbe wa assistant wenye tool calls na maandishi
yanayoanza na `[FLOW_SENT]` au `[FLOW_COMPLETED]` haujumuishwi. Maandishi tupu
yanaruhusiwa. Ujumbe unaosubiri hupangwa kwa muda na ID; ID zilizo kwenye batch
yoyote, hata iliyounganishwa, huondolewa. Snapshot inaonyesha hali thabiti ya
muamala huo; ujumbe unaofika baadaye unahitaji snapshot mpya.

## Kuandika batch

`commit_conversation_summary` hupokea `SummaryUpdate` iliyoandaliwa na kuongeza
batch, na kwa hiari kusasisha rollup, katika muamala mmoja unaokagua toleo.
`expected_version=None` huunda state ya kwanza kwa namna inayoshughulikia
waandishi wanaoshindana; kwa state iliyopo toleo lazima lilingane na huongezwa.
Mgongano huo hurudisha `STALE`; mafanikio hurudisha `COMMITTED`. Mpango usio
sahihi husababisha `ValueError`, kwa mfano ID zisizo sahihi au zinazorudiwa,
coverage inayopishana, vyanzo visivyopo, visivyostahili au vilivyopangwa vibaya,
au sequence isiyolingana. Makosa ya hifadhidata husambazwa; uandishi ulioshindwa
hurudisha nyuma mabadiliko yote ya state na batch.

Muhtasari mpya unahitaji maandishi yasiyo tupu na idadi iliyotolewa na mpigaji
ya tokeni 0–75,000. Jumla ya batch hai zinazobaki pamoja na mpya haiwezi kuzidi
75,000. Rollup ya hiari inahitaji maandishi yasiyo tupu, tokeni 0–25,000 na
prefix isiyo tupu ya batch hai kwa mpangilio wa sequence. Lazima batch tano za
mwisho zibaki hai ikihesabiwa batch mpya. API hukagua namba na mipaka iliyotolewa;
haiamui wakati wa kufupisha, haihesabu tokeni wala haiiti model.

Compaction hubadilisha rollup na kuashiria prefix imefanyiwa compaction, ikifuta maandishi
na idadi ya tokeni za batch hizo huku ikihifadhi endpoints na coverage kamili.
Mpaka wa `compacted_through_batch` huonyesha batch zote zilizochakatwa, si
kwamba taarifa zake zote zimebaki kwenye rollup mpya.
Batch mpya, rollup, archival na toleo huandikwa pamoja. Ujumbe asilia na shughuli
za mtumiaji hazibadilishwi. Tengeneza na hesabu maandishi nje ya miamala hiyo;
baada ya `STALE`, mpigaji anahitaji snapshot mpya kabla ya kuamua kuandika.

## Uhamishaji na vipimo

Angalia [uhamishaji](UHAMISHAJI.md#schema-ya-muhtasari-wa-mazungumzo-issue-92)
na [amri za vipimo](MUHTASARI_WA_MAZUNGUMZO.md#vipimo) kwa hifadhidata ya muda.
`test_conversation_summary_db.py` hukagua defaults, constraints, eligibility,
snapshot iliyojitenga, mipango isiyo sahihi na stale dhidi ya makosa bila
PostgreSQL (constraints zinazobebeka hutumia SQLite). Kesi za PostgreSQL hukagua
coverage, mpangilio, isolation, ushindani wa waandishi na snapshot, rollback,
compaction, mipaka, uniqueness na cascade. Moduli ya migration hukagua ulingano
wa schema na SQL offline; kesi yake ya PostgreSQL huendesha parent chain na
upgrade/downgrade/upgrade na kukagua users na messages. Vipimo offline havithibitishi
tabia ya PostgreSQL; kesi zilizorukwa huacha uthibitisho huo haujakamilika.
