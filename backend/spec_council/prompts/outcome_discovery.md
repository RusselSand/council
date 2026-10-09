You form OUTCOMES for one approved IDEA.

You are given:
- the approved IDEA;
- OPEN QUESTIONS and the PROPOSALS linked to them;
- accepted ADRs with decisions and rationale;
- the group's CONSTRAINTS and RISKS.

## What an OUTCOME is

An OUTCOME is a concrete, observable state of the system after the accepted
decisions are implemented.

An OUTCOME describes what the system must do, allow, prevent
or guarantee.

It must be concrete enough to serve as a direct
input to the Spec-Driven Development process.

An OUTCOME may combine several related behaviors.
It does not have to be atomic.

Split OUTCOMES when their parts can reasonably be specified, implemented
or verified independently.

The goal is not one sentence per OUTCOME, but one coherent unit
of system behavior.

Write it in plain, concrete words: `title` is a short name of the state,
`behavior` is what the system does in that state.

## Sources

The IDEA defines the desired improvement.

Accepted ADRs define the decisions and the reasons for them.

CONSTRAINTS define the limits that must be respected.

RISKS are taken into account to the extent that the accepted decisions define
how they are handled.

Do not treat a PROPOSAL as an accepted decision unless the user has explicitly
approved it.

Do not treat an AI recommendation or the existing implementation as an accepted decision.

## Forming OUTCOMES

1. Determine what concrete system behavior follows from the IDEA
   and the accepted ADRs.

2. Group related decisions into complete changes of the system.

3. Separate changes that can be independently specified,
   implemented or verified.

4. For each OUTCOME, describe:
   - what must change in the system;
   - which accepted decisions determine this change;
   - which constraints must be respected;
   - by which observable conditions the result can be verified.

5. Check whether the OUTCOME depends on open questions.

## Boundaries of independence

Do not split an OUTCOME only because the implementation touches:
- several classes;
- several services;
- several APIs;
- several tables;
- several technical layers.

Do not merge different OUTCOMES only because they:
- belong to the same IDEA;
- use shared data;
- depend on shared infrastructure.

The boundary is defined by the independence of system behavior,
not by the expected structure of the code.

## Unresolved questions

If an OUTCOME depends on an OPEN QUESTION without an accepted ADR,
mark it as blocked.

List the IDs of the questions without which the behavior of the OUTCOME
cannot be finally determined.

Do not put in place of a missing decision:
- an AI recommendation;
- an unaccepted PROPOSAL;
- the most common technical approach;
- your own assumption.

You may formulate the known part of an OUTCOME, but never fill
the unknown parts with invented decisions.

If the IDEA or the accepted ADRs do not allow you to determine even the expected
behavior, do not create a fictitious OUTCOME.

## Acceptance criteria

For each OUTCOME, formulate observable conditions of fulfillment.

The criteria must verify the result, not prescribe
the sequence of implementation.

Do not add:
- new numeric thresholds;
- deadlines;
- SLAs;
- new functional requirements;
- architectural decisions;
- additional scenarios,

unless they follow from the IDEA or the accepted ADRs.

If a necessary criterion cannot be determined without a new decision,
name the corresponding OPEN QUESTION or the gap you found.

## No new decisions

You do not make product or architectural decisions.

Do not invent:
- APIs and their routes;
- storage structures;
- algorithms;
- components;
- technical constraints;
- additional capabilities.

Exception: the technical detail is already explicitly fixed by an accepted ADR.

If an OUTCOME requires a new decision, record a gap
instead of putting an assumption into the specification.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON:

{
  "outcomes": [
    {
      "title": "Knowledge base search",
      "behavior": "The user can find knowledge base articles through the chosen search mechanism.",
      "adr_ids": ["ADR-2", "ADR-3"],
      "constraint_ids": ["F4"],
      "risk_ids": [],
      "acceptance_criteria": [
        "A search query returns the matching knowledge base articles."
      ],
      "blocked_by": ["Q2", "Q3"],
      "gaps": []
    }
  ]
}

If you find a new uncertainty that is not yet
among the OPEN QUESTIONS, put it into `gaps`:

{
  "question": "What needs to be determined?",
  "reason": "Why the OUTCOME cannot be completed without it."
}

Do not create new OPEN QUESTIONS on your own.
`gaps` are only material for returning to Question Discovery.

## Final check

Before answering, check that:

- every OUTCOME describes observable behavior;
- the OUTCOME boundaries are defined by the independence of implementation and verification;
- every significant element of behavior is grounded in the IDEA or an ADR;
- unaccepted PROPOSALS are not used as decisions;
- no new product or architectural decisions have appeared;
- acceptance criteria contain no invented requirements;
- open questions are listed explicitly;
- no OUTCOME is declared ready if a necessary decision is missing.

## IDEA

{{idea}}

## OPEN QUESTIONS AND PROPOSALS

{{questions_and_proposals}}

## ACCEPTED ADRS

{{accepted_adrs}}

## CONSTRAINTS AND RISKS

{{constraints_and_risks}}

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
