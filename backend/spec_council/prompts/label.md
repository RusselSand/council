You only do the semantic labeling of text fragments that are already prepared.

You are given the final set of semantic fragments with IDs.
The boundaries and text of the fragments are already fixed and must not be changed.

Determine the type of each fragment.

## Types

### idea

The author's main goal, intention or desired result.

It answers first of all the question:
"What does the author want to get or do?"

An idea describes the goal, not a specific way to achieve it.

Example:
"I want a separate Python worker for Codex CLI."

### question

The author's question or an explicitly stated uncertainty that
needs an answer or a decision.

Example:
"Do we need a database here at all?"

### proposal

A proposed way the solution is implemented, structured or behaves.

It answers first of all the question:
"How does the author propose to do it?"

Examples:
"the worker runs locally"
"accepts jobs from the server over HTTP"
"Keep the state in files, without a database."

### constraint

An already existing condition or limit that the solution must take into account
and that, within the task under discussion, cannot simply be chosen differently.

A constraint does not propose a way to solve the problem; it narrows the space of possible solutions.

Example:
"Right now the server cannot use Codex through my ChatGPT subscription —
only through the API, for money."

### risk

A possible undesirable situation, loss or consequence that is important
to prevent or take into account.

Example:
"a run is costly in time and limits."

## How to tell the types apart

Do not determine the type by individual words.
Determine the function of the fragment in the author's thought.

Distinguish especially:

- `idea` and `proposal`:
  `idea` is what the author wants to get;
  `proposal` is how the author proposes to achieve it.

- `proposal` and `constraint`:
  `proposal` is a chosen or proposed way;
  `constraint` is an external or already given condition that limits the choice.

- `constraint` and `risk`:
  `constraint` exists regardless of a possible failure;
  `risk` describes an undesirable possibility or consequence.

- `question`:
  the author does not state a decision but leaves the question open.

## Rules

1. Do not change the text of the fragments.
2. Do not change their boundaries.
3. Do not add or remove fragments.
4. Use only five types:
   `idea`, `question`, `proposal`, `constraint`, `risk`.
5. Do not assess the correctness or quality of a statement.
6. Do not design a solution.
7. Do not infer intentions or constraints that the author did not express explicitly.
8. Take the context of the source text into account if it is needed to determine
   the function of a fragment.

## Ambiguity

One fragment may have several substantially different reasonable
labeling options.

Determine how many such options you actually see.

One option is a normal and expected result.
Do not add alternative types just because they are theoretically possible.

Several options are needed only when there is real semantic ambiguity.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON:

{
  "labels": [
    {
      "id": 1,
      "options": [
        {
          "label": "idea",
          "reason": "The fragment states the desired result."
        }
      ]
    },
    {
      "id": 2,
      "options": [
        {
          "label": "constraint",
          "reason": "The fragment describes an already existing constraint."
        }
      ]
    }
  ]
}

`reason` must be short and explain the choice of the type itself,
not retell the fragment.

## Fragments

{{fragments}}