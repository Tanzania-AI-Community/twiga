from enum import Enum

from app.tools.tool_code.generate_exercise.main import generate_exercise
from app.tools.tool_code.get_current_weather.main import get_current_weather


class ToolName(str, Enum):
    get_current_weather = "get_current_weather"
    generate_exercise = "generate_exercise"


tools_metadata = [
    {
        "type": "function",
        "function": {
            "name": ToolName.get_current_weather.value,
            "description": "get the current weather in a given location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "the city and state, e.g. san francisco, ca",
                    },
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": ToolName.generate_exercise.value,
            "description": "Generate one exercise or question for the students based on course literature",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A brief message describing the desired question or exercise type and the topic it should be about. Request just one question.",
                    }
                },
                "required": ["query"],
            },
        },
    },
]


tools_functions = {
    ToolName.get_current_weather.value: get_current_weather,
    ToolName.generate_exercise.value: generate_exercise,
}
