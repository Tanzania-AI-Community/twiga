from enum import Enum


class SubjectClassStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ResourceType(str, Enum):
    textbook = "textbook"
    curriculum = "curriculum"
    document = "document"


class Role(str, Enum):
    admin = "admin"
    teacher = "teacher"


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class GradeLevel(str, Enum):
    p1 = "p1"
    p2 = "p2"
    p3 = "p3"
    p4 = "p4"
    p5 = "p5"
    p6 = "p6"
    os1 = "os1"
    os2 = "os2"
    os3 = "os3"
    os4 = "os4"
    as1 = "as1"
    as2 = "as2"

    @property
    def display_format(self) -> str:
        """Returns a nicely formatted string for display"""
        grade_display = {
            "p1": "Standard 1",
            "p2": "Standard 2",
            "p3": "Standard 3",
            "p4": "Standard 4",
            "p5": "Standard 5",
            "p6": "Standard 6",
            "os1": "Form 1",
            "os2": "Form 2",
            "os3": "Form 3",
            "os4": "Form 4",
            "as1": "Form 5",
            "as2": "Form 6",
        }
        return grade_display[self]


class OnboardingState(str, Enum):
    new = "new"
    personal_info_submitted = "personal_info_submitted"
    completed = "completed"


class UserState(str, Enum):
    blocked = "blocked"
    rate_limited = "rate_limited"
    approved = "approved"
    onboarding = "onboarding"
    active = "active"
    inactive = "inactive"
    in_review = "in_review"


class SubjectName(str, Enum):
    geography = "geography"
    history = "history"
    biology = "biology"
    english = "english"
    civics = "civics"
    mathematics = "mathematics"
    human_geography = "human_geography"
    physical_geography = "physical_geography"
    agriculture = "agriculture"
    agromechanics = "agromechanics"
    animal_health_and_production = "animal_health_and_production"
    arts_and_design = "arts_and_design"
    auto_body_repair = "auto_body_repair"
    bible_knowledge = "bible_knowledge"
    book_keeping = "book_keeping"
    chemistry = "chemistry"
    computer_science = "computer_science"
    engineering_science = "engineering_science"
    physics = "physics"
    acting = "acting"
    business_studies = "business_studies"
    additional_mathematics = "additional_mathematics"
    auto_electric = "auto_electric"
    carpentry = "carpentry"
    civil_draughting = "civil_draughting"
    horticultural_production = "horticultural_production"
    leather_goods_and_footwear = "leather_goods_and_footwear"
    literature_in_english = "literature_in_english"
    information_and_computer_studies = "information_and_computer_studies"
    commerce = "commerce"

    @property
    def display_format(self) -> str:
        emoji_map = {
            "geography": "🌎",
            "history": "📙",
            "biology": "🧬",
            "english": "📘",
            "civics": "🏛️",
            "mathematics": "➗",
            "human_geography": "👤",
            "physical_geography": "🪨",
            "agromechanics": "🚜",
            "agriculture": "🌽",
            "animal_health_and_production": "🐮",
            "arts_and_design": "👨‍🎨",
            "auto_body_repair": "🔧",
            "bible_knowledge": "✝️",
            "book_keeping": "📚",
            "chemistry": "⚛️",
            "computer_science": "💻",
            "engineering_science": "📐",
            "physics": "🚀",
            "acting": "🎭",
            "business_studies": "💼",
            "additional_mathematics": "➕",
            "auto_electric": "🚗",
            "carpentry": "🪚",
            "civil_draughting": "📏",
            "horticultural_production": "🌱",
            "leather_goods_and_footwear": "👞",
            "literature_in_english": "📖",
            "information_and_computer_studies": "🖥️",
            "commerce": "💹",
        }

        emoji = emoji_map.get(self, "")
        return f"{self.replace('_', ' ').title()} {emoji}".strip()


class ChunkType(str, Enum):
    text = "text"
    exercise = "exercise"
    image = "image"
    table = "table"
    other = "other"


class FeedbackInviteStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    expired = "expired"
    responded = "responded"
    failed = "failed"


class FeedbackResponseType(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    opt_out = "opt_out"
