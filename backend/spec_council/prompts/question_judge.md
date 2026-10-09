You form the final list of OPEN QUESTIONS for the approved IDEA.

You are given:
- the IDEA;
- the source fragments of the group;
- the results of several independent Question Discovery agents.

You do not look for new questions.
Work only with the proposed candidates and the user's source questions.

## What an OPEN QUESTION is

An OPEN QUESTION is one uncertainty or one decision that must be
resolved so that the IDEA can move forward.

An OPEN QUESTION describes WHAT is not yet known.

It must not contain:
- possible answers;
- existing PROPOSALS;
- a list of alternatives;
- an assumption about the future decision.

Example:

Bad:
"Full-text or vector search?"

Good:
"How should search be performed?"

Related solution options are stored separately through `proposal_ids`.

An OPEN QUESTION must stay valid if new
PROPOSALS appear later.

## Task

Get a minimal canonical set of standalone OPEN QUESTIONS
that really must be resolved for the IDEA.

## The user's source questions

Questions with `source = user` are the user's source material.

Do not remove or reword them.

If the user's source question contains answer options, keep `text` verbatim and give an
atomic wording without the options in `note`: that wording goes into the notes.

If several agents returned the same source question, it is still one question.

If agents gave different `note` wordings for the same source question, choose the clearest
atomic one.

## Semantic duplicates

If different agents formulated the same uncertainty as `inferred`
or `discovered`, merge them into one canonical OPEN QUESTION.

Choose the wording that:
- names the unknown most precisely;
- is neutral toward possible solutions;
- contains no candidate answers;
- does not list existing proposals;
- is broad enough to allow new proposals;
- and at the same time does not combine several independent uncertainties.

Merge the related `proposal_ids`.

## Link to PROPOSALS

For each existing proposal, check which OPEN QUESTION
it actually answers.

If different agents reconstructed different questions for one proposal,
determine which uncertainty the proposal resolves directly.

If several proposals answer one uncertainty, link them
to one OPEN QUESTION.

Do not include the names of these alternatives in the question text.

If one proposal really answers several independent
OPEN QUESTIONS, it may be linked to several questions.

## Discovered questions

Keep a `discovered` question only if it really must be
resolved before moving on to implementing the IDEA.

Remove questions that:
- are optional engineering detail;
- can be decided locally during implementation;
- are already unambiguously answered by the approved material;
- duplicate another uncertainty;
- are based on an assumption that is not in the source material.

## Independent evaluation

Do not use majority voting.

The number of agents that proposed a question does not determine its quality.

Check a question against the IDEA, the source fragments and the related proposals.

Do not add your own questions.

## Accepted project decisions

ACCEPTED PROJECT DECISIONS are ADRs from previous councils of the project that the user
selected as relevant to this IDEA. Each has `relevance` (`applicable`,
`potential_conflict` or `uncertain`) and `reason`.

- Do not ask an OPEN QUESTION that an `applicable` decision already answers for this IDEA.
- If the IDEA may require revisiting a decision (`potential_conflict`, or `uncertain` with a
  concrete reason), keep the candidate OPEN QUESTION that revisits it — do not merge it away
  or drop it as already answered — and keep its `revisits` (the decision ID).
- Do not treat these decisions as answers to questions they do not answer.
- An empty list means there are no such decisions.

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

## Format

Return only JSON:

{
  "questions": [
    {
      "id": "Q1",
      "text": "Where should a person get the answer?",
      "source": "inferred",
      "source_question_id": null,
      "proposal_ids": ["F1", "F2", "F3"],
      "reason": "F1–F3 propose different answers to one uncertainty about the point of interaction.",
      "revisits": null
    },
    {
      "id": "Q2",
      "text": "How should search be performed?",
      "source": "inferred",
      "source_question_id": null,
      "proposal_ids": ["F1", "F2"],
      "reason": "F1 and F2 answer one uncertainty about the way of searching.",
      "revisits": null
    },
    {
      "id": "Q3",
      "text": "Who decides whether a thread is useful — the moderators or the bot?",
      "note": "Who decides whether a thread is useful?",
      "source": "user",
      "source_question_id": "F5",
      "proposal_ids": [],
      "reason": null,
      "revisits": null
    }
  ]
}

Assign IDs sequentially: Q1, Q2, Q3...

Every source `user` question must be present in the result.
Every `inferred` question must have at least one `proposal_id`.
A `discovered` question may have an empty `proposal_ids`.

For `user`:
- `text` matches the source question verbatim;
- `note` is the same question as an atomic note: one sentence, without answer options or
  decisions. If the source question already is one, repeat it; if it lists options, leave
  them out — the options are separate PROPOSALS.

For every question:
- `revisits` is the ID of an accepted project decision this question revisits (see
  "Accepted project decisions"), otherwise null.

Before answering, check every generated OPEN QUESTION:

- it describes the unknown, not answer options;
- it does not list the related proposals;
- it stays valid if one more proposal appears;
- it contains only one uncertainty.

## IDEA

{{idea}}

## Source fragments

{{fragments}}

## ACCEPTED PROJECT DECISIONS

{{accepted_decisions}}

## Question Discovery results

{{question_candidates}}

## REPOSITORY CONTEXT

A map of the existing implementation, checked at the Repository Discovery step: how the system is
built now. `verified` — confirmed by the code, `inferred` — a conclusion from observations,
`unknown` — could not be established. Use it as facts about the current state of the system. The
existing implementation is not an accepted decision and not a requirement: do not turn it into an
ADR and do not choose an option only because it is already done that way.

`complete: false` and `remaining_follow_up` — the investigation is not finished: these places are
not established, do not treat them as resolved. `repositories` — which working copies the map was
taken from (the backend and the frontend are sometimes in different repositories): when there are
several, file paths in the map start with the `folder` of their copy. `uncommitted_changes` — the
map of this copy was taken from a working copy with edits, not from a commit;
`files_outside_checkout` and `not_in_snapshot` — what was not in the snapshot and the models did
not see.

{{repository}}

## DESIGN CONTEXT

A description of the Figma design, checked at the Design Discovery step: what interface and what
behavior the design provides for. `verified` — visible in the design, `inferred` — a conclusion
from its structure, `unknown` — could not be established. The design is the designer's intent, not
an implemented system and not an accepted decision: do not turn it into an ADR and do not choose an
option only because it is drawn that way; a mismatch between the design and the idea, the fragments
or the code is a reason for a question, not a ready answer. Demo values in the design are not
requirements. `complete: false` and `remaining_follow_up` — the investigation of the design is not
finished: these places are not established.

{{design}}
