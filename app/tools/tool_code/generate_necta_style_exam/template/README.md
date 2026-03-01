# Exam JSON Templates

This folder defines the base JSON templates for exam generation.

## Question Type Design

### Part A
- `multiple_choice`: One question stem per item, exactly 5 options (`A-E`), one correct answer.
- `item_matching`: `x` items in `listA` matched to `y` responses in `listB` where `y > x`.
- Solution format:
  - MCQ: single correct option letter per item.
  - Matching: mapping from `listA` labels to `listB` labels (`answers_pairs`).

### Part B
- `short_answer`: Definitions, brief explanations, small calculations, short structured prompts.
- Solution format:
  - `example_answer`
  - `accepted_answers` (alternative valid responses)
  - `marking_points` (key points to award marks)

### Part C
- `long_answer`: Extended response and essay-style reasoning.
- Solution format:
  - `example_answer`
  - `accepted_answers`
  - `marking_points`

## Template Files and Example Outputs

## 1) `exam_template.json`
Exam-level structure and section plan.

Example filled output, where question list would contain questions of the specified question types following their format.
```json
{
  "meta": {
    "country": "THE UNITED REPUBLIC OF TANZANIA",
    "office": "PRESIDENT'S OFFICE\nREGIONAL ADMINISTRATION AND LOCAL GOVERNMENT",
    "exam_title": "FORM FOUR EXAMINATION - SERIES 10",
    "subject": "CHEMISTRY",
    "duration": "3:00 Hrs",
    "year": 2024
  },
  "instructions": [
    "This paper consists of three sections A, B and C with a total of fourteen (14) questions.",
    "Answer all questions in section A and B and one (1) question from section C.",
    "Calculators and cellular phones are not allowed in the examination room.",
    "Write your Examination number on every page of your answer sheets/booklet(s)."
  ],
  "constants": {},
  "section_A": {
    "section_title": "SECTION A",
    "section_instructions": "Answer all questions in this section.",
    "marks": 15,
    "total_num_questions": 2,
    "question_types": ["multiple_choice", "item_matching"],
    "question_list": []
  },
  "section_B": {
    "section_title": "SECTION B",
    "section_instructions": "Answer all questions in this section.",
    "marks": 70,
    "total_num_questions": 5,
    "question_types": ["short_answer"],
    "question_list": []
  },
  "section_C": {
    "section_title": "SECTION C",
    "section_instructions": "Answer only one (1) question in this section.",
    "marks": 15,
    "total_num_questions": 2,
    "question_types": ["long_answer"],
    "question_list": []
  }
}
```

## 2) `multiple_choice_question_template.json`
Used for one MCQ item or a block item entry.

Example filled output:
```json
{
  "id": "A-Q1-iii",
  "marks": 1,
  "question": "Which gas is produced when dilute hydrochloric acid reacts with zinc granules?",
  "options": [
    {"label": "A", "text": "Carbon dioxide"},
    {"label": "B", "text": "Hydrogen"},
    {"label": "C", "text": "Chlorine"},
    {"label": "D", "text": "Oxygen"},
    {"label": "E", "text": "Sulphur dioxide"}
  ],
  "answer": "B",
  "metadata": {
    "topic": "Acids and bases",
    "difficulty": "easy"
  }
}
```

## 3) `item_matching_question_template.json`
Used for a matching question with answer mapping.

Example filled output:
```json
{
  "id": "A-Q2",
  "marks": 5,
  "prompt": "Match the items in List A with the responses in List B by writing the letter of the correct response beside the item number provided.",
  "listA": [
    {"label": "i", "text": "A compound that turns blue litmus red"},
    {"label": "ii", "text": "A substance that speeds up a reaction without being used up"},
    {"label": "iii", "text": "The smallest particle of an element that can take part in chemical reaction"},
    {"label": "iv", "text": "Process of loss of electrons"},
    {"label": "v", "text": "A solution that resists change in pH"}
  ],
  "listB": [
    {"label": "A", "text": "Atom"},
    {"label": "B", "text": "Oxidation"},
    {"label": "C", "text": "Catalyst"},
    {"label": "D", "text": "Base"},
    {"label": "E", "text": "Acid"},
    {"label": "F", "text": "Buffer solution"},
    {"label": "G", "text": "Reduction"}
  ],
  "answers_pairs": {
    "i": "E",
    "ii": "C",
    "iii": "A",
    "iv": "B",
    "v": "F"
  },
  "allow_reuse_listB": true,
  "metadata": {
    "topic": "Basic chemical concepts",
    "difficulty": "medium"
  }
}
```

## 4) `short_answer_question_template.json`
Used for structured short-answer content in Section B.

Example filled output:
```json
{
  "id": "B-Q3",
  "marks": 10,
  "question_description": "Define the following terms:",
  "context": null,
  "sub_questions": [
    {"label": "i", "text": "Electrolysis", "marks": 2},
    {"label": "ii", "text": "Mole", "marks": 2},
    {"label": "iii", "text": "Homologous series", "marks": 2},
    {"label": "iv", "text": "State two differences between ionic and covalent compounds.", "marks": 4}
  ],
  "answer": {
    "example_answer": "Electrolysis is decomposition of ionic compounds by electricity. Mole is amount containing 6.02 x 10^23 particles. Homologous series is a family of organic compounds with same functional group and general formula.",
    "marking_scheme": "Award marks per correct definition and valid differences.",
    "accepted_answers": [
      "Electrolysis is chemical decomposition caused by electric current.",
      "A mole contains Avogadro's number of entities."
    ],
    "marking_points": [
      {"point": "Mentions decomposition by electricity", "marks": 1},
      {"point": "Mentions ionic molten/aqueous medium", "marks": 1},
      {"point": "Defines mole using Avogadro number", "marks": 2}
    ]
  },
  "metadata": {
    "topic": "Electrochemistry and mole concept",
    "difficulty": "medium"
  }
}
```

## 5) `long_answer_question_template.json`
Used for Section C extended-response questions.

Example filled output:
```json
{
  "id": "C-Q13",
  "marks": 15,
  "question_description": "Answer in a well-structured paragraph with equations.",
  "question": "Describe the extraction of iron from hematite ore in a blast furnace. Include the role of coke and limestone, and relevant equations.",
  "answer": {
    "example_answer": "Coke burns to form carbon monoxide which reduces iron(III) oxide to iron. Limestone decomposes to calcium oxide which removes silica as slag.",
    "marking_scheme": "Award for process flow, correct role of coke and limestone, and balanced equations.",
    "accepted_answers": [
      "Fe2O3 is reduced by CO to Fe.",
      "CaCO3 decomposes to CaO and CO2, then CaO reacts with SiO2."
    ],
    "marking_points": [
      {"point": "States combustion of coke and formation of CO", "marks": 3},
      {"point": "Correct reduction equation for iron oxide", "marks": 4},
      {"point": "Explains limestone role and slag formation", "marks": 4},
      {"point": "Logical explanation and correct terminology", "marks": 4}
    ]
  },
  "metadata": {
    "topic": "Metallurgy",
    "difficulty": "hard"
  }
}
```

## 6) `constants_template.json`
This is optional and subject-specific. You can override it per subject and per exam.

Example filled output for a chemistry exam:
```json
{
  "atomic_masses": {
    "H": 1,
    "C": 12,
    "N": 14,
    "O": 16,
    "Na": 23
  },
  "avogadro": "6.02 x 10^23 mol^-1",
  "gmv_stp": "22.4 dm^3 mol^-1",
  "std_temp": "273 K"
}
```
