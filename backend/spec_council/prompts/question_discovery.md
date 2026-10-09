You look for the OPEN QUESTIONS that must be resolved for an already approved IDEA.

You are given:
- the approved IDEA;
- the source fragments of one group with IDs and types:
  `idea`, `question`, `proposal`, `constraint`, `risk`.

Do not change the existing fragments.

## What an OPEN QUESTION is

An OPEN QUESTION is one uncertainty or one decision that must be
resolved so that the IDEA can move forward.

An OPEN QUESTION describes WHAT is not yet known.

It must not contain:
- possible answers;
- existing PROPOSALS;
- a list of alternatives;
- an assumption about which decision will be made.

An OPEN QUESTION must stay valid even if new PROPOSALS that do not exist now
appear later.

Example:

Bad:
"Run deployment manually or automatically after merge?"

Good:
"What should trigger deployment?"

Bad:
"Which search to use: full-text or vector?"

Good:
"How should search be performed?"

PROPOSALS are linked to a question through `proposal_ids`, not listed
in the question text.

## Goal

Form questions of three kinds.

### user

The question is already explicitly present among the source fragments of type `question`.

Keep its text and ID unchanged.

If the user's source question itself contains answer options,
do not rewrite it: the user's source text takes priority.

### inferred

The question is not explicitly stated, but one or more existing `proposal` fragments
are answers to the same uncertainty.

Reconstruct the OPEN QUESTION that these proposals answer.

Formulate the unknown, not a choice between the existing proposals.

Example:

F1 proposal: "full-text search"
F2 proposal: "or vector right away"

→

OPEN QUESTION:
"How should search be performed?"

proposal_ids: ["F1", "F2"]

### discovered

Neither the question nor a ready answer is in the source fragments, but the uncertainty
must be resolved for the IDEA to be defined well enough for implementation.

Add only questions whose answer may substantially change:
- the expected behavior;
- the boundaries of the capability;
- the user scenario;
- the essential design of the solution;
- meeting an existing constraint;
- handling an existing risk.

Do not add questions only because they may be useful during technical
implementation.

Do not ask prematurely about the framework, class structure, logging,
deployment tooling and other details that can be decided locally
during implementation without changing the IDEA.

## Procedure

1. Carry over the existing `question` fragments.
2. Find the existing proposals that are answers to unrecorded
   questions.
3. Determine the common uncertainty that each such set of
   proposals resolves.
4. Formulate a neutral OPEN QUESTION for it, without answer options.
5. Only after that, find the OPEN QUESTIONS that are really missing.

## Rules

- Do not propose answers.
- Do not create new proposals.
- Do not choose between existing proposals.
- Do not list proposals or alternatives in the text of an OPEN QUESTION.
- Do not word a question so that one of the existing proposals looks
  preferable.
- One OPEN QUESTION must describe one uncertainty.
- Do not turn a constraint or a risk into a question unless it requires
  a separate decision.
- Do not ask a question if the answer already follows unambiguously from the approved
  material.
- Do not create several wordings of one uncertainty for the sake of variety.

## Accepted project decisions

ACCEPTED PROJECT DECISIONS are ADRs from previous councils of the project that the user
selected as relevant to this IDEA. Each has `relevance` (`applicable`,
`potential_conflict` or `uncertain`) and `reason`.

- Do not ask an OPEN QUESTION that an `applicable` decision already answers for this IDEA.
- If the IDEA may require revisiting a decision (`potential_conflict`, or `uncertain` with a
  concrete reason), ask that OPEN QUESTION explicitly and put the decision ID into
  `revisits`.
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
      "text": "How should search be performed?",
      "source": "inferred",
      "source_question_id": null,
      "proposal_ids": ["F1", "F2"],
      "reason": "F1 and F2 are answers to one unrecorded uncertainty.",
      "revisits": null
    },
    {
      "text": "How will the success of the change be determined?",
      "source": "discovered",
      "source_question_id": null,
      "proposal_ids": [],
      "reason": "Without this, it is impossible to tell whether the IDEA has been achieved.",
      "revisits": null
    }
  ]
}

For `user`:
- `text` matches the source question verbatim;
- `note` is the same question as an atomic note: one sentence, without answer options or
  decisions. If the source question already is one, repeat it; if it lists options, leave
  them out — the options are separate PROPOSALS;
- `source_question_id` contains its ID;
- `reason` may be null.

For `inferred`:
- `proposal_ids` contains the proposals that answer the question.

For `discovered`:
- `proposal_ids` is usually empty.

For every question:
- `revisits` is the ID of an accepted project decision this question revisits (see
  "Accepted project decisions"), otherwise null.

## IDEA

{{idea}}

## Group fragments

{{fragments}}

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

## ACCEPTED PROJECT DECISIONS

{{accepted_decisions}}
