# Issue Gap Check

You check GAPS found while dividing OUTCOMES into ISSUES against the questions of the IDEA that
were already asked.

Each OUTCOME was divided separately, and its ISSUES saw only the decisions of that OUTCOME. So a
GAP may be a question that is already asked: decided in another place of the IDEA, or asked and
still open. A GAP like that must not go to the human again.

You are given:
- the approved IDEA;
- the OUTCOMES of the IDEA;
- all questions of the IDEA: a `decided` one with its accepted decision (`adr_id`, `decision`,
  `rationale`) and the OUTCOME that implements it (`implemented_by`, empty if none); an `open`
  one without a decision;
- the GAPS: the question, why it was raised and the OUTCOMES whose ISSUES it holds.

You do not decide anything and do not answer a GAP yourself. You only find where it is already
asked.

## When a GAP is already asked

A GAP is answered by a `decided` question when its decision settles exactly the uncertainty of
the GAP: knowing the decision, nothing of what the GAP asks remains to be chosen. A decision about
the same place of the system that leaves the GAP's choice open is not an answer. A decision
from which the answer follows only by your guess is not an answer either.

A GAP is an `open` question when both ask about the same uncertainty, even in other words, more
precisely or only for one OUTCOME.

Name every question the answer needs: a GAP can be settled by two decisions together. If the GAP
is an `open` question, name it: the ISSUES wait for it. A GAP that is not asked anywhere is not
in your answer.

Read a decision within the question it answers: do not extend it to other parts of the system to
find an answer.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON. List only the GAPS that are already asked; an empty list means none is:

{
  "answers": [
    {
      "gap_id": "G1",
      "question_ids": ["Q10"],
      "reason": "Which part of the decision settles this GAP, or why it is the same uncertainty as the open question."
    }
  ]
}

## Final check

Before answering, check that:

- every `decided` question you name settles exactly what the GAP asks, not only the same place;
- every `open` question you name asks the same uncertainty as the GAP;
- you did not extend a decision beyond the question it answers;
- every `gap_id` and question id is from the input.

## IDEA

{{idea}}

## OUTCOMES

{{outcomes}}

## QUESTIONS OF THE IDEA

{{questions}}

## GAPS

{{gaps}}
