import logging

from fastapi.responses import JSONResponse

from app.database.models import Message, User
from app.services.onboarding_service import onboarding_client
from app.database import db
from app.services.whatsapp_service import whatsapp_client
from app.database.enums import MessageRole, UserState, OnboardingState, Role
from app.utils.string_manager import strings, StringCategory
from app.config import settings
from app.utils.whatsapp_utils import (
    ValidMessageType,
    get_valid_message_type,
)
from app.services.messaging_service import messaging_client
from app.services.rate_limit_service import rate_limit_service
from app.services.flow_service import flow_client


class StateHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_blocked(self, user: User) -> JSONResponse:
        assert user.id is not None

        # Check if we've already sent a blocked message to this user
        recent_messages = await db.get_user_message_history(user.id, limit=3)
        if recent_messages:
            # Check if the last assistant message was a blocked message
            assistant_messages = [
                msg for msg in recent_messages if msg.role == MessageRole.assistant
            ]
            if assistant_messages:
                last_assistant_message = assistant_messages[-1]
                blocked_text = strings.get_string(StringCategory.ERROR, "blocked")

                # If the last assistant message was a blocked message, don't send another
                if last_assistant_message.content == blocked_text:
                    self.logger.info(
                        f"Blocked message already sent to user {user.wa_id}, not sending again"
                    )
                    return JSONResponse(
                        content={"status": "ok"},
                        status_code=200,
                    )

        # Send blocked message (first time)
        response_text = strings.get_string(StringCategory.ERROR, "blocked")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        self.logger.info(f"Sent blocked message to user {user.wa_id}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_rate_limited(self, user: User) -> JSONResponse:
        assert user.id is not None

        # Check if we've already sent a rate limit message to this user
        recent_messages = await db.get_user_message_history(user.id, limit=10)
        if recent_messages:
            # Check if the last assistant message was a rate limit message
            assistant_messages = [
                msg for msg in recent_messages if msg.role == MessageRole.assistant
            ]
            if assistant_messages:
                last_assistant_message = assistant_messages[-1]
                rate_limit_text = strings.get_string(
                    StringCategory.ERROR, "rate_limited"
                )

                # If the last assistant message was a rate limit message, don't send another
                if last_assistant_message.content == rate_limit_text:
                    self.logger.info(
                        f"Rate limit message already sent to user {user.wa_id}, not sending again"
                    )
                    return JSONResponse(
                        content={"status": "ok"},
                        status_code=200,
                    )

        # Send rate limit message (first time)
        response_text = strings.get_string(StringCategory.ERROR, "rate_limited")
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )
        self.logger.info(f"Sent rate limit message to user {user.wa_id}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def check_and_reset_rate_limit_state(self, user: User) -> User:
        """
        Check if user is rate_limited and reset to active if TTL has expired.
        """
        return await rate_limit_service.check_and_reset_rate_limit_state(user)

    async def check_rate_limit_and_update_state(
        self, user: User, phone_number: str
    ) -> tuple[bool, User]:
        """
        Check if user should be rate limited and update their state accordingly.
        """
        return await rate_limit_service.check_rate_limit_and_update_state(
            user, phone_number
        )

    async def _handle_rate_limiting(
        self, user: User, phone_number: str
    ) -> JSONResponse | None:
        """
        Rate limiting check - returns JSONResponse if rate limited, None if not
        """
        # Check and reset rate limit state if TTL expired
        user = await self.check_and_reset_rate_limit_state(user)

        # Check if user should be rate limited and update state accordingly
        is_rate_limited, updated_user = await self.check_rate_limit_and_update_state(
            user, phone_number
        )

        if is_rate_limited:
            return await self.handle_rate_limited(updated_user)

        return None

    async def handle_onboarding(self, user: User) -> JSONResponse:
        await onboarding_client.process_state(user)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_active(
        self, user: User, message_info: dict, user_message: Message
    ) -> JSONResponse:
        message_type = get_valid_message_type(message_info)
        match message_type:
            case ValidMessageType.SETTINGS_FLOW_SELECTION:
                return await messaging_client.handle_settings_selection(
                    user, user_message
                )
            case ValidMessageType.COMMAND:
                return await messaging_client.handle_command_message(user, user_message)
            case ValidMessageType.CHAT:
                return await messaging_client.handle_chat_message(user, user_message)
            case ValidMessageType.OTHER:
                return await messaging_client.handle_other_message(user, user_message)

    async def handle_new_user_registration(
        self, phone_number: str, message_info: dict
    ) -> JSONResponse:
        """Handle new users - create with in_review state and start onboarding flow"""
        try:
            from app.database.engine import get_session
            from app.config import settings, Environment

            # Create a new user with in_review state (will remain in_review until approved by admin)
            new_user = User(
                name=None,  # Will be filled during onboarding flow
                wa_id=phone_number,
                state=UserState.in_review,  # In review until approved
                onboarding_state=OnboardingState.new,  # Start with 'new' for normal onboarding flow
                role=Role.teacher,
            )

            # Save to database
            async with get_session() as session:
                session.add(new_user)
                await session.flush()
                await session.commit()
                await session.refresh(new_user)

            # Check if we should use dummy data (non-prod environments)
            if settings.environment != Environment.PRODUCTION:
                self.logger.info(
                    f"Creating dummy user for {phone_number} in {settings.environment} environment"
                )
                return await self.handle_new_dummy(new_user)

            # Production flow - start the onboarding flow
            await flow_client.send_personal_and_school_info_flow(new_user)

            self.logger.info(f"Started onboarding flow for new user {phone_number}")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        except Exception as e:
            self.logger.error(f"Error handling new user registration: {e}")
            # Send fallback message
            await whatsapp_client.send_message(
                phone_number,
                strings.get_string(StringCategory.ERROR, "registration_error"),
            )
            return JSONResponse(content={"status": "error"}, status_code=500)

    async def handle_in_review_user(self, user: User) -> JSONResponse:
        """Handle messages from users in review (not yet approved) users"""
        assert user.id is not None

        # Check if we've already sent a pending approval message recently
        recent_messages = await db.get_user_message_history(user.id, limit=3)
        if recent_messages:
            assistant_messages = [
                msg for msg in recent_messages if msg.role == MessageRole.assistant
            ]
            if assistant_messages:
                last_assistant_message = assistant_messages[-1]
                pending_text = strings.get_string(
                    StringCategory.REGISTRATION, "pending_approval"
                )

                if last_assistant_message.content == pending_text:
                    self.logger.info(
                        f"Pending approval message already sent to user {user.wa_id}"
                    )
                    return JSONResponse(content={"status": "ok"}, status_code=200)

        # Send pending approval message
        response_text = strings.get_string(
            StringCategory.REGISTRATION, "pending_approval"
        )
        await whatsapp_client.send_message(user.wa_id, response_text)
        await db.create_new_message(
            Message(
                user_id=user.id,
                role=MessageRole.assistant,
                content=response_text,
            )
        )

        return JSONResponse(content={"status": "ok"}, status_code=200)

    async def handle_new_approved_user(self, user: User) -> JSONResponse:
        """Handle users approved by dashboard - send welcome message and move to onboarding"""
        try:
            # Update user state to onboarding (not active)
            user.state = UserState.onboarding
            await db.update_user(user)

            # Send welcome template message
            await whatsapp_client.send_template_message(
                user.wa_id, settings.welcome_template_id
            )

            # Log the template message to database (using template ID as content)
            assert user.id is not None
            await db.create_new_message(
                Message(
                    user_id=user.id,
                    role=MessageRole.assistant,
                    content=f"Welcome template sent: {settings.welcome_template_id}",
                )
            )

            self.logger.info(f"User {user.wa_id} approved and moved to onboarding")
            return JSONResponse(content={"status": "ok"}, status_code=200)

        except Exception as e:
            self.logger.error(f"Error approving user {user.wa_id}: {e}")
            return JSONResponse(content={"status": "error"}, status_code=500)

    async def handle_inactive_user(self, user: User) -> JSONResponse:
        """Handle users who haven't been active for a long time - reactivate them"""
        try:
            # Update user state to active
            user.state = UserState.active
            await db.update_user(user)

            self.logger.info(f"User {user.wa_id} reactivated from inactive state")

            # Continue with normal active user flow - no special message needed
            # The user's message will be processed normally after this
            return JSONResponse(content={"status": "reactivated"}, status_code=200)

        except Exception as e:
            self.logger.error(f"Error reactivating inactive user {user.wa_id}: {e}")
            return JSONResponse(content={"status": "error"}, status_code=500)

    async def handle_new_dummy(self, user: User) -> JSONResponse:
        """Create a dummy user with pre-filled data for dev/test environments"""
        try:
            from app.database.models import ClassInfo
            from app.database.enums import SubjectName, GradeLevel

            # Update the user object with dummy data
            user.state = UserState.active
            user.onboarding_state = OnboardingState.completed
            user.role = Role.teacher
            user.class_info = ClassInfo(
                classes={SubjectName.geography: [GradeLevel.os2]}
            ).model_dump()

            # Read the class IDs from the class info
            class_ids = await db.get_class_ids_from_class_info(user.class_info)

            assert class_ids is not None

            # Update user and create teachers_classes entries
            user = await db.update_user(user)
            assert user.id is not None
            await db.assign_teacher_to_classes(user, class_ids)

            # Send a welcome message to the user
            response_text = strings.get_string(
                StringCategory.ONBOARDING, "onboarding_override"
            )
            await whatsapp_client.send_message(user.wa_id, response_text)
            await db.create_new_message(
                Message(
                    user_id=user.id,
                    role=MessageRole.assistant,
                    content=response_text,
                )
            )
            self.logger.warning(f"Dummy user {user.wa_id} created with data: {user}")
            return JSONResponse(
                content={"status": "ok"},
                status_code=200,
            )
        except Exception as e:
            self.logger.error(f"Error while handling new dummy user: {e}")
            return JSONResponse(
                content={"status": "error"},
                status_code=500,
            )


state_client = StateHandler()
