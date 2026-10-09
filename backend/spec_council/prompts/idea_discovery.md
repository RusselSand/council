You reconstruct the IDEA for an already formed group of fragments.

The group has no explicitly stated IDEA, but the other fragments belong
to one common intention.

Your task is to formulate the IDEA that best explains
why these fragments are in one group.

## What an IDEA is

An IDEA is an intended improvement, a new capability or a change
that the user wants to explore.

An IDEA describes WHAT should improve or become possible,
without choosing HOW exactly to achieve it.

A problem, an observation, a constraint or a risk may explain why the IDEA is needed,
but must not become the IDEA itself.

A proposal describes a possible way to implement the IDEA.
Do not raise the details of a proposal to the level of the IDEA unless they are
a standalone part of the desired result.

## How to reconstruct the IDEA

Consider all group fragments together.

Look for the common result that explains why the user needs the questions
and proposals contained in the group.

If several proposals are alternatives, the IDEA must describe
the common goal that all these alternatives serve, not one of the options.

For example:

Proposals:
- full-text search over the knowledge base;
- vector search;
- a Slack bot that replies with a link to an article.

Good IDEA:
"The team can find answers in the knowledge base on its own, without asking
for them in #help."

Bad IDEA:
"Build vector search over the knowledge base."

It chooses one of the proposals.

Bad IDEA:
"Reduce the number of questions in #help with vector search."

It both adds a goal that may not be in the fragments
and chooses a way to implement it.

## Grounding

The IDEA must be fully grounded in the group fragments.

You may generalize the meaning of several fragments, but do not:
- add a new goal;
- invent a new capability;
- add requirements that are not in the fragments;
- choose between competing proposals;
- turn a constraint or a risk into a goal;
- assume a user motivation that is not in the group.

If the fragments are not enough to reconstruct one IDEA with confidence,
the result must reflect this.

## Options

Determine how many substantially different reasonable wordings of the IDEA
the group supports.

One option is a normal and expected result.

Do not create options because of stylistic differences.
Several options are needed only when the fragments allow
different understandings of the group's goal itself.

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

Return only JSON:

{
  "number": 1,
  "options": [
    {
      "idea": "The team can find answers in the knowledge base on its own, without asking for them in #help.",
      "evidence": ["F1", "F2", "F3"],
      "reason": "All three proposals are different ways to solve the same problem of finding an answer."
    }
  ]
}

If the IDEA cannot be reliably reconstructed:

{
  "number": 0,
  "options": [],
  "reason": "Not enough information to determine the desired change without adding new meaning."
}

`idea` is one sentence in plain words: only the desired result, without the way to achieve it.

`evidence` contains the IDs of the fragments that directly support this IDEA.

`reason` briefly explains why exactly this goal unites the group.

## Group

{{group}}
