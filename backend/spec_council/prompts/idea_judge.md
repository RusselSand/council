You choose the final IDEA for an already formed group of fragments.

The group had no explicitly stated IDEA.
Several independent models tried to reconstruct it from the existing
fragments.

You are given:
- the source fragments of the group;
- the proposed IDEA options.

Your task is to choose the wording that most precisely expresses
the common goal of the group and requires the fewest assumptions beyond the source text.

## What an IDEA is

An IDEA is an intended improvement, a new capability or a change
that the user wants to explore.

An IDEA describes WHAT should improve or become possible,
without choosing HOW exactly to achieve it.

A problem, an observation, a constraint or a risk may motivate the IDEA,
but must not become the IDEA itself.

A proposal describes a possible way of implementation.
The IDEA must sit one level above specific proposals.

## How to evaluate the options

For each candidate, check:

1. Does the IDEA explain all the main fragments of the group?

2. If the group has competing proposals, does the IDEA remain the common goal
   for all the options?

3. Did the candidate choose one proposal and call it the IDEA?

4. Did the candidate turn a constraint, a risk or an observation into a goal?

5. Did the candidate add a new motivation, capability, requirement
   or desired result that is not in the fragments?

6. Can part of the wording be removed from the IDEA without losing the common goal?
   If so, prefer the narrower and better-grounded wording.

The main criterion:
the IDEA must express the minimal common intended change needed
to explain the structure of the group.

## Independent evaluation

Do not use majority voting.

The number of models that proposed a similar IDEA is not evidence.

Check each wording directly against the group fragments.

You may choose one of the proposed options or carefully combine
the candidates' wordings if the result does not add new meaning.

Do not create a new interpretation of the goal that is not in any candidate.

If no option is sufficiently grounded, return `no_valid_option`.

## Wording

IDEA, OPEN QUESTION, PROPOSAL and ADR are atomic notes: one thought, normally one sentence.
Do not embed answers, alternatives, decisions or outcomes inside a note — they are separate
notes.

Write simply and directly: clear, short, with one obvious meaning, in words a developer
understands at a glance. Prefer concrete wording to abstract; avoid unnecessary jargon and
bureaucratic phrasing.

Discussion and rationale may be long; the text of a note may not.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

If the IDEA is determined:

{
  "status": "ok",
  "idea": "The team can find answers in the knowledge base on its own, without asking for them in #help.",
  "evidence": ["F1", "F2", "F3"],
  "reason": "This is the common result, compatible with all the proposed ways of solving the problem."
}

If the IDEA cannot be reliably reconstructed:

{
  "status": "no_valid_option",
  "reason": "The fragments do not allow determining the common goal without an additional assumption."
}

## Group

{{group}}

## IDEA options

{{idea_options}}
