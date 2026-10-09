You only slice the source text into semantic fragments.

## What a semantic fragment is

A semantic fragment is a minimal continuous passage of the source text
that expresses one complete thought of the author in the context of the task under discussion.

A fragment must keep the semantic links that the author expressed explicitly.
If one part of the text refines, limits, explains, justifies
or sets a condition for another part of the same thought, do not separate it just because
several separate statements can be singled out inside it.

At the same time, a list of several independent decisions, requirements,
problems or ideas may contain several semantic fragments, even if
they are in one sentence.

A boundary between fragments is needed where the author finishes one thought
and moves on to another independent thought.

Do not try to make fragments as small as possible.
The goal is to single out the author's minimal complete thoughts, not minimal
logical statements.

## Examples

Source text:

"Keep the state in files, without a database."

Correct:

[
  "Keep the state in files, without a database."
]

"without a database" refines the same choice of how to store the state and is not
an independent thought.

---

Source text:

"the worker runs locally, accepts jobs from the server over HTTP,
launches codex as a separate process, sends the result back
to callback_url."

Reasonable slicing:

[
  "the worker runs locally,",
  "accepts jobs from the server over HTTP,",
  "launches codex as a separate process,",
  "sends the result back to callback_url."
]

Here the text lists independent decisions about different aspects of how the worker works.

---

Source text:

"The main thing is not to lose the result if something crashes."

Correct:

[
  "The main thing is not to lose the result if something crashes."
]

Wrong:

[
  "The main thing is not to lose the result",
  "if something crashes."
]

The condition is part of the same thought.

## Rules

1. Keep the source text verbatim.
   Do not paraphrase, correct, normalize or add to it.

2. Do not add any statements or links that are not in the source text.

3. Do not lose meaningful text.
   All meaningful parts of the source must be present in the result.

4. Keep the original order of the text.

5. Each fragment must be a continuous passage of the source text.

6. Fragments must not overlap.

7. Do not merge independent thoughts just because they are
   in one sentence or list.

8. Do not split one thought just because it contains several facts,
   objects, actions or technical details.

9. Do not assess the correctness, importance or quality of the statements.

10. Do not design a solution and do not draw conclusions from the text.
    Your task is only to find the boundaries of the thoughts already contained in the source.

## Ambiguity

One text may have several substantially different reasonable slicing
options.

Determine how many such options you actually see.

One option is a normal and expected result.
Do not create additional options just because the text could theoretically
be split differently.

Add a second or further options only when there is
real semantic ambiguity: the same part of the text can reasonably be considered
either part of the neighboring thought or an independent complete thought.

Options must differ in at least one such boundary that matters for the meaning.

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
      "fragments": [
        "...",
        "..."
      ],
      "reason": null
    }
  ]
}

If there are several options, in the `reason` of each option briefly explain
which boundary exactly is ambiguous and why both interpretations are possible.

Do not explain obvious boundaries.

## Final check

Before answering, check each option:

- every fragment is present verbatim in the source text;
- the order of the source text is kept;
- no meaningful text is lost;
- fragments do not overlap;
- inside a fragment there is no obvious transition to another complete thought;
- no fragment is broken up so much that a part of it has lost its own meaning;
- additional options reflect real ambiguity and are not created
  for the sake of variety.

## Source text

{{input}}