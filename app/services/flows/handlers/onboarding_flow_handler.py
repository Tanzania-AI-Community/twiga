import logging
from datetime import datetime

from dateutil.relativedelta import relativedelta
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse

import app.database.db as db
import app.database.enums as enums
from app.config import settings
from app.database.models import User
from app.services.whatsapp_service import whatsapp_client
from app.utils.string_manager import StringCategory, strings


class OnboardingFlowHandler:
    """
    Orchestrates the teacher onboarding profile flow.

    The flow captures personal and school information, then triggers the
    subjects/classes flow for first-time onboarding. In update mode, the same
    screen is reused to edit existing profile fields without restarting onboarding.
    Submissions are acknowledged immediately and persisted asynchronously.
    """

    def __init__(self, service: object):
        self.service = service
        self.logger = logging.getLogger(__name__)

    async def handle_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        try:
            self.logger.debug(f"Handling onboarding data exchange: {payload}")
            data = payload.get("data", {})
            is_update = data.get("is_updating", False)
            encrypted_flow_token = payload.get("flow_token")

            background_tasks.add_task(self.update_user_profile, user, data, is_update)

            response_payload = self.service._create_flow_response_payload(
                screen="SUCCESS",
                data={},
                encrypted_flow_token=encrypted_flow_token,
            )
            return await self.service.process_response(
                response_payload, aes_key, initial_vector
            )
        except ValueError as exc:
            return PlainTextResponse(content={"error_msg": str(exc)}, status_code=422)
        except Exception as exc:
            return JSONResponse(content={"error_msg": str(exc)}, status_code=500)

    async def update_user_profile(
        self, user: User, data: dict, is_updating: bool
    ) -> None:
        try:
            prefix = "update_" if is_updating else ""
            user.name = data.get(f"{prefix}full_name") or user.name
            user.birthday = (
                datetime.strptime(data[f"{prefix}birthday"], "%Y-%m-%d")
                if data.get(f"{prefix}birthday")
                else None if data.get(f"{prefix}birthday") else None
            )
            user.region = data.get(f"{prefix}region")
            user.school_name = data.get(f"{prefix}school_name")
            user.onboarding_state = enums.OnboardingState.personal_info_submitted

            user = await db.update_user(user)

            if not is_updating:
                await self.service.send_subjects_classes_flow(user)
        except Exception as exc:
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)
            await self.service._persist_visible_assistant_message(user, err_message)
            self.logger.error(f"Failed to update onboarding data: {str(exc)}")

    async def send_user_settings_flow(self, user: User) -> None:
        flow_strings = strings.get_category(StringCategory.FLOWS)
        header_text = flow_strings["personal_settings_header"]
        body_text = flow_strings["personal_settings_body"]
        data = {
            "full_name": user.name or "Name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": True,
            "region": user.region,
            "birthday": user.birthday.strftime("%Y-%m-%d") if user.birthday else None,
            "school_name": user.school_name,
        }
        flow_id = settings.onboarding_flow_id
        if not flow_id or not flow_id.strip():
            self.logger.error("onboarding_flow_id is not configured.")
            return

        await whatsapp_client.send_whatsapp_flow_message(
            user=user,
            flow_id=flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload={
                "screen": "personal_info",
                "data": data,
            },
            flow_cta=flow_strings["personal_settings_cta"],
        )
        await self.service._persist_flow_message(
            user=user,
            flow_id=flow_id,
            header_text=header_text,
            body_text=body_text,
        )

    async def send_personal_and_school_info_flow(self, user: User) -> None:
        flow_strings = strings.get_category(StringCategory.FLOWS)
        header_text = flow_strings["start_onboarding_header"]
        body_text = flow_strings["start_onboarding_body"]
        data = {
            "full_name": user.name or "Name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": False,
        }

        flow_id = settings.onboarding_flow_id
        if not flow_id or not flow_id.strip():
            self.logger.error("onboarding_flow_id is not configured.")
            return

        await whatsapp_client.send_whatsapp_flow_message(
            user=user,
            flow_id=flow_id,
            header_text=header_text,
            body_text=body_text,
            action_payload={
                "screen": "personal_info",
                "data": data,
            },
            flow_cta=flow_strings["start_onboarding_cta"],
        )
        await self.service._persist_flow_message(
            user=user,
            flow_id=flow_id,
            header_text=header_text,
            body_text=body_text,
        )
