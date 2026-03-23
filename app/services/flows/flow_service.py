import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import app.database.db as db
import app.database.enums as enums
import app.services.flows.utils as flow_utils
import scripts.flows.designing_flows as flows_wip
from app.config import settings
from app.database.models import User
from app.services.flows.handlers.onboarding_flow_handler import OnboardingFlowHandler
from app.services.flows.handlers.subjects_classes_flow_handler import (
    SubjectsClassesFlowHandler,
)


class FlowService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

        self._onboarding_flow_handler = OnboardingFlowHandler(service=self)
        self._subjects_classes_flow_handler = SubjectsClassesFlowHandler(service=self)

        self.data_exchange_action_handlers: dict[
            str, Callable[..., Awaitable[PlainTextResponse | JSONResponse]]
        ] = {}
        self.back_action_handlers: dict[
            str, Callable[..., Awaitable[PlainTextResponse | JSONResponse]]
        ] = {}
        self.init_action_handlers: dict[
            str, Callable[..., Awaitable[dict[str, Any] | PlainTextResponse]]
        ] = {}
        self._register_flow_handlers()

    def _register_flow_handlers(self) -> None:
        onboarding_flow_id = (settings.onboarding_flow_id or "").strip()
        if onboarding_flow_id:
            self.data_exchange_action_handlers[onboarding_flow_id] = (
                self.handle_onboarding_data_exchange_action
            )
            self.init_action_handlers[onboarding_flow_id] = (
                flows_wip.handle_onboarding_init_action
            )
        else:
            self.logger.warning("onboarding_flow_id is not configured.")

        subjects_flow_id = (settings.subjects_classes_flow_id or "").strip()
        if subjects_flow_id:
            self.data_exchange_action_handlers[subjects_flow_id] = (
                self.handle_subjects_classes_data_exchange_action
            )
            self.back_action_handlers[subjects_flow_id] = (
                self.handle_subjects_classes_back_action
            )
            self.init_action_handlers[subjects_flow_id] = (
                flows_wip.handle_subjects_classes_init_action
            )
        else:
            self.logger.warning("subjects_classes_flow_id is not configured.")

    async def handle_flow_request(
        self, request: Request, bg_tasks: BackgroundTasks
    ) -> PlainTextResponse:
        try:
            body = await request.json()
            payload, aes_key, initial_vector = await self._decrypt_flow_request(body)
            action = self._parse_flow_action(payload.get("action"))
            flow_token = payload.get("flow_token")

            if action == flow_utils.FlowRequestAction.PING:
                return await self.handle_health_check(aes_key, initial_vector)

            if not flow_token:
                self.logger.error("Missing flow token")
                return PlainTextResponse(
                    content={
                        "error_msg": "Missing flow token, Unable to process request"
                    },
                    status_code=422,
                )

            # Get the user and flow ID.
            wa_id, flow_id = self._decrypt_flow_token(flow_token)
            user = await db.get_user_by_waid(wa_id)

            if not user:
                self.logger.error(f"User not found for WA ID: {wa_id}")
                raise ValueError("User not found")

            if action == flow_utils.FlowRequestAction.DATA_EXCHANGE:
                handler = self.data_exchange_action_handlers.get(
                    flow_id, self.handle_unknown_flow
                )
                return await handler(user, payload, aes_key, initial_vector, bg_tasks)

            if action == flow_utils.FlowRequestAction.BACK:
                handler = self.back_action_handlers.get(
                    flow_id, self.handle_unknown_flow
                )
                return await handler(user, payload, aes_key, initial_vector, bg_tasks)

            if action == flow_utils.FlowRequestAction.INIT:
                self.logger.warning(f"WIP Flow is being processed: {flow_id}")
                handler = self.init_action_handlers.get(flow_id)
                if handler is None:
                    return await self.handle_unknown_flow(
                        user, payload, aes_key, initial_vector
                    )
                response_payload = await handler(user)
                return await self.process_response(
                    response_payload, aes_key, initial_vector
                )

            return await self.handle_unknown_action(
                user, payload, aes_key, initial_vector
            )

        except ValueError as exc:
            self.logger.error(f"Error decrypting payload: {exc}")
            return PlainTextResponse(content="Decryption failed", status_code=421)
        except flow_utils.FlowTokenError as exc:
            self.logger.error(f"Error decrypting flow token: {exc}")
            return PlainTextResponse(
                content={"error_msg": "Your request has expired please start again"},
                status_code=422,
            )
        except Exception as exc:
            self.logger.error(f"Unexpected error: {exc}")
            return PlainTextResponse(content="Decryption failed", status_code=500)

    async def handle_health_check(
        self, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.debug("Received flow health check event ❤️‍🩹")
        response_payload = {"data": {"status": "active"}}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def process_response(
        self, response_payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.debug(
            f"Processing response: {response_payload} , AES Key: {aes_key} , IV: {initial_vector}"
        )
        try:
            encrypted_response = flow_utils.encrypt_response(
                response=response_payload,
                aes_key=aes_key,
                iv=initial_vector,
            )
            return PlainTextResponse(content=encrypted_response, status_code=200)
        except Exception as exc:
            self.logger.error(f"Error encrypting response: {exc}")
            return PlainTextResponse(content="Encryption failed", status_code=500)

    async def _decrypt_flow_request(self, body: dict) -> tuple[dict, bytes, str]:
        return await flow_utils.decrypt_flow_request(body)

    def _decrypt_flow_token(self, flow_token: str) -> tuple[str, str]:
        return flow_utils.decrypt_flow_token(flow_token)

    def _create_flow_response_payload(
        self, screen: str, data: dict[str, Any], encrypted_flow_token: str | None = None
    ) -> dict[str, Any]:
        if encrypted_flow_token is None:
            return flow_utils.create_flow_response_payload(screen=screen, data=data)
        return flow_utils.create_flow_response_payload(
            screen=screen,
            data=data,
            encrypted_flow_token=encrypted_flow_token,
        )

    def _parse_flow_action(
        self, action_value: object
    ) -> flow_utils.FlowRequestAction | None:
        if not isinstance(action_value, str):
            return None

        normalized_action = action_value.strip()
        if not normalized_action:
            return None

        try:
            return flow_utils.FlowRequestAction(normalized_action)
        except ValueError:
            action_aliases: dict[str, flow_utils.FlowRequestAction] = {
                flow_utils.FlowRequestAction.PING.value.lower(): flow_utils.FlowRequestAction.PING,
                flow_utils.FlowRequestAction.DATA_EXCHANGE.value.lower(): flow_utils.FlowRequestAction.DATA_EXCHANGE,
                flow_utils.FlowRequestAction.INIT.value.lower(): flow_utils.FlowRequestAction.INIT,
                flow_utils.FlowRequestAction.BACK.value.lower(): flow_utils.FlowRequestAction.BACK,
            }
            return action_aliases.get(normalized_action.lower())

    async def handle_unknown_flow(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        **kwargs: Any,
    ) -> PlainTextResponse:
        self.logger.warning(f"Unknown flow received: {payload.get('flow_id')}")
        response_payload = {"unknown": "flow"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_unknown_action(
        self, user: User, payload: dict, aes_key: bytes, initial_vector: str
    ) -> PlainTextResponse:
        self.logger.warning(f"Unknown action received: {payload.get('action')}")
        response_payload = {"unknown": "event"}
        return await self.process_response(response_payload, aes_key, initial_vector)

    async def handle_onboarding_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse:
        return await self._onboarding_flow_handler.handle_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=aes_key,
            initial_vector=initial_vector,
            background_tasks=background_tasks,
        )

    async def handle_subjects_classes_data_exchange_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        return await self._subjects_classes_flow_handler.handle_data_exchange_action(
            user=user,
            payload=payload,
            aes_key=aes_key,
            initial_vector=initial_vector,
            background_tasks=background_tasks,
        )

    async def handle_subjects_classes_back_action(
        self,
        user: User,
        payload: dict,
        aes_key: bytes,
        initial_vector: str,
        background_tasks: BackgroundTasks,
    ) -> PlainTextResponse | JSONResponse:
        return await self._subjects_classes_flow_handler.handle_back_action(
            user=user,
            payload=payload,
            aes_key=aes_key,
            initial_vector=initial_vector,
            background_tasks=background_tasks,
        )

    async def send_user_settings_flow(self, user: User) -> None:
        await self._onboarding_flow_handler.send_user_settings_flow(user)

    async def send_personal_and_school_info_flow(self, user: User) -> None:
        await self._onboarding_flow_handler.send_personal_and_school_info_flow(user)

    async def send_subjects_classes_flow(self, user: User) -> None:
        await self._subjects_classes_flow_handler.send_subjects_classes_flow(user)

    async def _persist_flow_message(
        self, user: User, flow_id: str, header_text: str, body_text: str
    ) -> None:
        flow_message = (
            f"[FLOW_SENT] id={flow_id} | header={header_text} | body={body_text}"
        )
        await self._persist_visible_assistant_message(user, flow_message)

    async def _persist_visible_assistant_message(
        self, user: User, content: str
    ) -> None:
        if user.id is None:
            self.logger.warning(
                "Skipping flow message persistence for user without ID."
            )
            return

        await db.create_new_message_by_fields(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=content,
            is_present_in_conversation=True,
        )


flow_client = FlowService()
