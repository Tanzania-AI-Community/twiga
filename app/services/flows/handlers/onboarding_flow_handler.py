from datetime import datetime
import logging
from typing import Any

from dateutil.relativedelta import relativedelta
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse

from app.database.models import User


class OnboardingFlowHandler:
    """Flow-specific logic for the onboarding/personal-info flow."""

    def __init__(self, service: Any):
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

            # Add a background task to update the user profile
            background_tasks.add_task(self.update_user_profile, user, data, is_update)

            response_payload = self.service.futil.create_flow_response_payload(
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
            # Get field values using prefix based on update status
            prefix = "update_" if is_updating else ""
            user.name = data.get(f"{prefix}full_name") or user.name
            user.birthday = (
                datetime.strptime(data[f"{prefix}birthday"], "%Y-%m-%d")
                if data.get(f"{prefix}birthday")
                else None if data.get(f"{prefix}birthday") else None
            )
            user.region = data.get(f"{prefix}region")
            user.school_name = data.get(f"{prefix}school_name")
            user.onboarding_state = (
                self.service.enums.OnboardingState.personal_info_submitted
            )

            # Update the database
            user = await self.service.db.update_user(user)

            # Send the select-subjects flow if onboarding
            if not is_updating:
                await self.service.send_subjects_classes_flow(user)
        except Exception as exc:
            err_message = self.service.strings.get_string(
                self.service.StringCategory.ERROR, "general"
            )
            await self.service.whatsapp_client.send_message(user.wa_id, err_message)
            await self.service._persist_visible_assistant_message(user, err_message)
            self.logger.error(f"Failed to update onboarding data: {str(exc)}")

    # The same flow is sent for both settings and onboarding (onboarding_flow_id)
    async def send_user_settings_flow(self, user: User) -> None:
        flow_strings = self.service.strings.get_category(
            self.service.StringCategory.FLOWS
        )
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
        # Check if the flow settings are set
        assert (
            self.service.settings.onboarding_flow_id
            and self.service.settings.onboarding_flow_id.strip()
        )

        await self.service.futil.send_whatsapp_flow_message(
            user=user,
            flow_id=self.service.settings.onboarding_flow_id,
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
            flow_id=self.service.settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
        )

    async def send_personal_and_school_info_flow(self, user: User) -> None:
        flow_strings = self.service.strings.get_category(
            self.service.StringCategory.FLOWS
        )
        header_text = flow_strings["start_onboarding_header"]
        body_text = flow_strings["start_onboarding_body"]
        data = {
            "full_name": user.name or "Name",
            "min_date": "1900-01-01",
            "max_date": (datetime.now() - relativedelta(years=18)).strftime("%Y-%m-%d"),
            "is_updating": False,
        }

        # Check if the flow settings are set
        assert (
            self.service.settings.onboarding_flow_id
            and self.service.settings.onboarding_flow_id.strip()
        )

        await self.service.futil.send_whatsapp_flow_message(
            user=user,
            flow_id=self.service.settings.onboarding_flow_id,
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
            flow_id=self.service.settings.onboarding_flow_id,
            header_text=header_text,
            body_text=body_text,
        )
