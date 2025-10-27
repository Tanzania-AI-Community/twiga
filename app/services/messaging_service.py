import logging
import re
import os

from fastapi.responses import JSONResponse

import app.database.models as models
from app.services.flow_service import flow_client
from app.utils.string_manager import strings, StringCategory
from app.services.whatsapp_service import whatsapp_client
from app.utils.whatsapp_utils import _catch_latex_math, parse_msg_with_latex
import app.database.db as db
from app.services.llm_service import llm_client
import app.database.enums as enums


class MessagingService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    async def handle_settings_selection(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling interactive message with title: {message.content}")
        if message.content == "Personal Info":
            self.logger.debug("Sending update personal and school info flow")
            await flow_client.send_user_settings_flow(user)
        elif message.content == "Classes and Subjects":
            self.logger.debug("Sending update class and subject info flow")
            await flow_client.send_subjects_classes_flow(user)
        else:
            raise Exception(f"Unrecognized user reply: {message.content}")
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_command_message(
        self, user: models.User, message: models.Message
    ) -> JSONResponse:
        self.logger.debug(f"Handling command message: {message.content}")
        assert message.content is not None
        if message.content.lower() == "settings":
            response_text = strings.get_string(StringCategory.SETTINGS, "intro")
            options = [
                strings.get_string(StringCategory.SETTINGS, "personal_info"),
                strings.get_string(StringCategory.SETTINGS, "class_subject_info"),
            ]
            await whatsapp_client.send_message(user.wa_id, response_text, options)
        elif message.content.lower() == "help":
            response_text = strings.get_string(StringCategory.INFO, "help")
            await whatsapp_client.send_message(user.wa_id, response_text)
        else:
            response_text = strings.get_string(
                StringCategory.ERROR, "command_not_found"
            )
            await whatsapp_client.send_message(user.wa_id, response_text)
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_chat_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:
        llm_responses = await llm_client.generate_response(
            user=user, message=user_message
        )
        
        if llm_responses:
            # check if we have latex_math in the llm_response
            found_latex_formula = _catch_latex_math(llm_responses[-1].content) if llm_responses else None
            self.logger.debug(
                f"Sending message to {user.wa_id}: {llm_responses[-1].content}"
            )                
            # Update the database with the responses
            await db.create_new_messages(llm_responses)

            assert llm_responses[-1].content is not None
            # Send the last message back to the user
            if found_latex_formula:
                parsed_messages = parse_msg_with_latex(llm_responses[-1].content)  # Split the content into parts around LaTeX formulas
                temp_files_to_cleanup = []  # Keep track of temp files for cleanup
                
                try:
                    for part in parsed_messages:
                        if part['type'] == 'text':
                            await whatsapp_client.send_message(user.wa_id, part['content'])
                        elif part['type'] == 'latex':
                            # Send the LaTeX formula as an image using the generated image path
                            if part.get('image_path'):
                                temp_files_to_cleanup.append(part['image_path'])
                                await whatsapp_client.send_image_message(
                                    wa_id=user.wa_id,
                                    image_path=part['image_path'],
                                    mime_type='image/png',
                                    caption=f"LaTeX: {part['content']}"
                                )

                            else:
                                # Fallback to text if image generation failed
                                await whatsapp_client.send_message(user.wa_id, f"Formula: {part['content']}")
                finally:
                    # Clean up temporary files
                    for temp_file in temp_files_to_cleanup:
                        try:
                            if os.path.exists(temp_file):
                                os.unlink(temp_file)
                                self.logger.debug(f"Cleaned up temporary file: {temp_file}")
                        except Exception as e:
                            self.logger.warning(f"Failed to clean up temporary file {temp_file}: {e}")
            
            else:
                await whatsapp_client.send_message(user.wa_id, llm_responses[-1].content)
        
        else:
            self.logger.error("No responses generated by LLM")
            err_message = strings.get_string(StringCategory.ERROR, "general")
            await whatsapp_client.send_message(user.wa_id, err_message)

        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )

    async def handle_other_message(
        self, user: models.User, user_message: models.Message
    ) -> JSONResponse:
        assert user.id is not None
        message = models.Message(
            user_id=user.id,
            role=enums.MessageRole.assistant,
            content=strings.get_string(StringCategory.ERROR, "unsupported_message"),
        )
        await db.create_new_message(message)
        # Send message to the user
        await whatsapp_client.send_message(
            user.wa_id, strings.get_string(StringCategory.ERROR, "unsupported_message")
        )
        return JSONResponse(
            content={"status": "ok"},
            status_code=200,
        )


messaging_client = MessagingService()
