# Miundombinu ya Jukwaa

<div align="center">

![Usanifu wa Twiga](https://github.com/user-attachments/assets/33e4e394-b724-4ea4-af2a-7e75f93615aa)

</div>

Mchoro huu ni muhtasari wa miundombinu ya toleo la kwanza la Twiga katika uzalishaji. Tunathamini usanifu rahisi na tunataka kupunguza idadi ya majukwaa tunayotumia wakati wa kudumisha utendaji mzuri.

# Usanifu wa Msimbo

Tumetengeneza backend ya Twiga kwa urahisi na uwezo wa kubadilika.

## `app`

Kila kitu kinachotumika kuendesha programu ya Twiga kipo ndani ya folda ya `app`. Maombi yanayotoka kwa watumiaji wa WhatsApp (kupitia Meta API) kwanza hupokelewa na endpoints zilizo katika faili ya `app/main.py` (endpoint ya `webhooks`). Baadhi ya saini za WhatsApp hudhibitiwa na mapambaji (decorators) katika `app/security.py` na kisha `handle_request` katika `app/services/request_service.py` huelekeza maombi katika mwelekeo sahihi kutegemea na aina ya ombi na hali ya mtumiaji.

Vigezo vyote vya mazingira vinachukuliwa kutoka `app/config.py`, kwa hivyo wakati wa kutumia hivi kwa njia yoyote, lete tu mipangilio kwenye faili yako.

> [!Kumbuka]
>
> Usitumie `dotenv`, tumia tu mipangilio yetu.

Msimbo unaohusiana na AI hushughulikiwa zaidi katika `app/llm_service.py`. Kwa urahisi, ikiwa unapanga kuunda zana zozote mpya, unaweza kuziunda katika folda ya `app/tools/`. Fuata tu mwongozo tulioweka.

Tutakuachia ugundue mengine.

> [!Onyo]
>
> Ikiwa chochote hapa kinaonekana sio sahihi, kinaweza kuwa hakijasasishwa. Tujulishe 😁

## `scripts`

Ndani ya folda ya `scripts` tunahifadhi faili ambazo huendeshwa mara kwa mara kutoka upande wa msanidi programu. Angalia ndani yake ikiwa unataka kujaza toleo lako la hifadhidata na data ya vitabu.

## `tests`

> [!Kumbuka]
>
> Bado hatujafanya vipimo lakini vipo katika mpango wa baadaye.

# Muundo wa Hifadhidata

Tunatumia [SQLModel](https://sqlmodel.tiangolo.com/) ya tiangolos kama [ORM](https://en.wikipedia.org/wiki/Object%E2%80%93relational_mapping) kuingiliana na hifadhidata ya Neon Postgres katika mradi huu. Badala ya kushiriki muundo wa hifadhidata kwa njia tuli (ambayo inaweza kubadilika kwa muda), tunakuelekeza kwenye faili ya `app/database/model.py` ambayo inapaswa kuwa na kila kitu unachohitaji kujua kuhusu meza zinazotumika katika Twiga. Pia tuna [mchoro wa uhusiano wa vitu](https://drive.google.com/file/d/10dKIW6I6_d-712rt0s-7KltTWTmBjRIP/view?usp=sharing) (ERD) unaoonyesha muhtasari wa mahusiano ya meza lakini haudumishwi kila wakati na unaweza kutolingana kabisa na toleo la sasa la hifadhidata.

## `migrations`

Folda hii inaweka rekodi ya historia ya hifadhidata. Tunatumia uhamishaji wa [_alembic_](https://medium.com/@kasperjuunge/how-to-get-started-with-alembic-and-sqlmodel-288700002543). Isipokuwa unataka kutumia _alembic_ kwa nakala yako ya hifadhidata unaweza kupuuza folda hii. Ikiwa uko katika timu kuu na una ufikiaji wa hifadhidata yetu ya Neon, inaweza kuwa vizuri kujua jinsi inavyofanya kazi na kwa nini tunatumia.
