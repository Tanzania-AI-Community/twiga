# Uhamishaji wa Hifadhidata

Unaweza kukutana na matatizo ya hifadhidata ambayo yanahitaji kufanya uhamishaji wa hifadhidata. Katika folda ya `migrations/versions/` utapata orodha ya uhamishaji wa hifadhidata uliopita. Tunatumia [Alembic](https://alembic.sqlalchemy.org/en/latest/). Nyaraka zao si nzuri sana kwa hiyo hapa kuna [makala](https://medium.com/@kasperjuunge/how-to-get-started-with-alembic-and-sqlmodel-288700002543) ya mwanzo kuihusu.

Kwa chaguo-msingi, picha zetu za Docker zinatumia mfumo wa toleo la alembic kuanzisha hifadhidata. Ikiwa unataka kujenga upya hifadhidata kulingana na mahitaji yako, unaweza kuendesha uhamishaji mpya na kujenga upya viwekezi vya Docker.

## Kuendesha uhamishaji ukiwa kwenye Docker (inapendekezwa)

Amri zote zinaendeshwa ndani ya kontena la `app` ili zitumie mazingira ya Python ya kontena na kufikia mwenyeji wa `db` kwenye mtandao wa Docker.

- Anzisha huduma (kama hazijaendelea): `make run`
- Tengeneza uhamishaji mpya: `make generate-migration message="ujumbe wako"`
- Tekeleza uhamishaji wa hivi punde: `make migrate-up`
- Rudisha nyuma hadi toleo fulani: `make migrate-down version=<revision_id>`

Maelezo:
- Makefile tayari huweka `PYTHONPATH=/app` na `DATABASE_URL` kutoka `.env`, hivyo huhitaji kuzitaja mwenyewe.
- Uzalishaji otomatiki wa Alembic hautagundua thamani mpya za enum kwenye nguzo zilizopo; ongeza kauli za `ALTER TYPE ... ADD VALUE` kwenye toleo linalozalishwa ukibadilisha thamani za enum.

Ikiwa hutumii Docker kuendesha Twiga, basi unaweza kuanzisha hifadhidata na kuingiza data ya sampuli kwa kutumia amri:

```bash
uv run python -m scripts.database.seed --create --sample-data --vector-data chunks_gemini.json
```

Hii itaondoa meza zote zilizopo kwenye hifadhidata, kuunda mpya, kusakinisha pgvector na kuingiza data ya sampuli na data ya vekta ili hifadhidata iwe tayari kukubali watumiaji wapya.

## Schema ya muhtasari wa mazungumzo (Issue #92)

Migration `b7e2c9a4f610` inafuata `a1f4c7e2d3b9` na huongeza `conversation_summary_state` na `conversation_summary_batches`. Haifanyi backfill na huhifadhi rows asilia za `messages`. Coverage ni ID halisi hata batch ikiunganishwa. Downgrade huondoa summary state na batches, lakini huhifadhi users na messages. Tekeleza migration kabla ya kutumia API katika `app/database/db.py`; schema peke yake haiwashi summarization.

Upgrade kupitia parent kwanza. Hifadhidata mpya lazima itimize mahitaji ya migration chain ya awali, ikiwemo pgvector. Downgrade hufuta summaries na coverage; kuzirejesha kunahitaji backup au kuzitengeneza upya kutoka ujumbe uliobaki. Tazama [uhifadhi](UHIFADHI_WA_MUHTASARI.md) na [vipimo](MUHTASARI_WA_MAZUNGUMZO.md#vipimo).
