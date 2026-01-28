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
uv run python -m scripts.database.seed --create --sample-data --vector-data chunks_BAAI.json
```

Hii itaondoa meza zote zilizopo kwenye hifadhidata, kuunda mpya, kusakinisha pgvector na kuingiza data ya sampuli na data ya vekta ili hifadhidata iwe tayari kukubali watumiaji wapya.
