# Project Decisions Discovery

You determine which previously accepted decisions of the project concern the new IDEA.

You are given:
- the approved IDEA;
- the group's source fragments;
- a catalog of previously accepted ADRs in a short format: ID, the IDEA the decision belongs to, OPEN QUESTION, accepted decision, status; some ADRs have a trail in the code (`found_in_code`): a commit with the number of the issue that implemented the OUTCOME of this decision, in a file that the new IDEA, according to the repository map, is going to touch.

## Goal

Independently of the other agents, find the ADRs that must be taken into account in the further elaboration of the IDEA.

The selected decisions will be used in:
- Question Discovery;
- Proposal Discovery;
- Decision Analysis.

You only propose a list. The user makes the final selection.

## What an ADR is

An ADR is the user's previously accepted answer to an OPEN QUESTION together with its rationale.

The catalog contains a short form of the ADRs. A missing rationale in the short catalog does not mean that the decision was not accepted.

Existing ADRs are the project's context, not automatically accepted decisions of the new IDEA.

Take the ADR status into account (`active` — in force; `under_review` — an OPEN QUESTION
revisits it and there is no new decision yet; `superseded` — replaced by another ADR,
named in `superseded_by`):
- do not select `superseded` — select the decision that replaced it (`superseded_by`) if it
  concerns the IDEA;
- select `under_review` only as `potential_conflict` or `uncertain`: the decision is being
  questioned.

## Selection criteria

Select an ADR if the decision:

1. Directly governs functionality that the IDEA touches.
2. Defines an architectural or product rule that the new functionality must take into account.
3. Establishes an existing mechanism that the new functionality must interact with.
4. May contradict the IDEA or the user's proposals.
5. May need revisiting when the IDEA is implemented.

A trail in the code (`found_in_code`) is a strong argument: the IDEA will change code built for this decision. It does not mean automatic inclusion: the file may have been changed for an unrelated issue. Check whether the decision itself concerns what the IDEA changes. No trail is no argument against an ADR: the code may predate issue numbers in commits, and the decision may not concern code at all.

Do not select an ADR only because it:
- belongs to the same project;
- contains similar terms;
- uses a similar technology;
- describes a potentially useful mechanism;
- might be useful in some future implementation.

## Assessment

For each ADR, determine:

- Which part of the IDEA or of the source fragments does it touch?
- Does the ADR have a trail in the code, and does it confirm the link with the IDEA?
- How exactly can it affect future OPEN QUESTIONS and PROPOSALS?
- Is there a potential conflict?
- Is the short description enough for a confident conclusion?

Do not try to find a particular number of ADRs.

An empty list is a valid result.

## Restrictions

- Do not change existing ADRs.
- Do not formulate new OPEN QUESTIONS.
- Do not create PROPOSALS.
- Do not propose architectural decisions.
- Do not resolve the conflicts you find.
- Do not treat an existing ADR as automatically binding for the new IDEA.
- Do not invent the content of an ADR from its title or ID.
- Do not use information that is not in the input data.

If relevance is possible but not established, mark the uncertainty.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON:

{
  "decisions": [
    {
      "adr_id": "ADR-0003",
      "relevance": "applicable",
      "reason": "The IDEA touches the authentication mechanism governed by this decision."
    },
    {
      "adr_id": "ADR-0012",
      "relevance": "potential_conflict",
      "reason": "Changing the storage method may contradict a previously accepted decision."
    },
    {
      "adr_id": "ADR-0018",
      "relevance": "uncertain",
      "reason": "The decision concerns a related component, but its scope is unclear."
    }
  ]
}

Allowed values of relevance:

- `applicable` — the decision directly concerns the IDEA.
- `potential_conflict` — the IDEA may require revisiting the decision.
- `uncertain` — a link is possible but not sufficiently confirmed.

Do not return irrelevant ADRs.

Do not duplicate IDs.

The reason for selection must be concrete and based on the input data.

## Final check

Before answering, check that:

- Every ADR is really linked to the IDEA or to the group fragments.
- The reason for selection follows from the provided catalog.
- Possible conflicts are not resolved on your own.
- No new decisions or requirements have appeared.
- Irrelevant ADRs are excluded.
- The result is suitable for independent comparison with the other agents.

## Catalog record

Each catalog record looks like this:

{
  "adr_id": "ADR-0007",
  "idea": "Payments are accepted without manual reconciliation.",
  "question": "Which provider processes payments?",
  "decision": "Payments go through Stripe.",
  "status": "active",
  "superseded_by": null,
  "found_in_code": [
    {"issue": "ISS-0012", "outcome": "OUT-0004", "commit": "a1b2c3d",
     "file": "billing/api.py"}
  ]
}

## IDEA

{{idea}}

## GROUP FRAGMENTS

{{fragments}}

## PROJECT ADR CATALOG

{{adr_catalog}}