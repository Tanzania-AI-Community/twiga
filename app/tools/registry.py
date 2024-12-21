from enum import Enum


class ToolName(str, Enum):
    search_knowledge = "search_knowledge"
    generate_exercise = "generate_exercise"


tools_metadata = [
    {
        "type": "function",
        "function": {
            "name": ToolName.search_knowledge.value,
            "description": "Get relevant information from the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_phrase": {
                        "type": "string",
                        "description": "A message describing the information you are looking for.",
                    }
                },
                "required": ["search_phrase"],
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
