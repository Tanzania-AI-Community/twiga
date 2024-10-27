from enum import Enum


class ToolName(str, Enum):
    get_current_weather = "get_current_weather"
    generate_exercise = "generate_exercise"


tools = [
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
                    "user_query": {
                        "type": "string",
                        "description": "A short message describing the desired question or exercise type and the topic it should be about. Request just one question.",
                    }
                },
                "required": ["user_query"],
            },
        },
    },
]
