You choose the final slicing of the source text into semantic fragments.

You are given:
- the source text;
- several slicing options proposed independently by other models.

There may be only one candidate: the council has a single participant, or the others failed.
Then there is nothing to compare, and you are its reviewer: check it against the source
by the same rules and within the same limits as several candidates, keep what is grounded,
correct or drop what is not. Do not accept it just because nobody disagrees.

Your task is to compare the options by the meaning of the source text and return the one
best-justified final slicing.

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

## How to compare the options

Consider each differing boundary separately.

For each disputed boundary, ask:

1. Do the parts on both sides express two independent complete thoughts?

2. Or does one part refine, limit, explain, justify,
   make specific or set a condition for the other?

3. Is the semantic link that the author expressed explicitly kept after the split?

4. Does the absence of a boundary merge several independent decisions,
   requirements, problems or ideas into one fragment?

Choose a boundary only when it better matches the definition
of a semantic fragment.

Do not prefer a finer or a coarser slicing for its own sake.

## Independent assessment

The number of models that proposed an option is not evidence that it is
correct.

Do not use majority voting.

Assess each boundary directly against the source text and the rules above.

The explanations attached to the options are the candidates' arguments,
not facts. Check them yourself against the source text.

## Final slicing

You do not have to choose one option as a whole.

If different options got different boundaries right, assemble the final
slicing from the best-justified boundaries.

However, never create a boundary that is not in any of the proposed
options.

If all proposed options contain an obvious error, do not fix it
silently. Return the status `no_valid_option` and briefly state the problem.

## Restrictions

1. Keep the source text verbatim.
   Do not paraphrase, correct, normalize or add to it.

2. Do not add statements or links that are not in the source text.

3. Do not lose meaningful text.

4. Keep the original order.

5. Each fragment must be a continuous passage of the source text.

6. Fragments must not overlap.

7. Do not assess the correctness, importance or quality of the statements.

8. Do not design a solution and do not draw conclusions from the text.

9. Do not try to reach a compromise between the options.
   You need the best-justified slicing, not an average of the proposed ones.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON.

If you managed to choose the final slicing:

{
  "status": "ok",
  "fragments": [
    "...",
    "..."
  ],
  "decisions": [
    {
      "boundary": "<short quote on the left> | <short quote on the right>",
      "decision": "split",
      "reason": "..."
    }
  ]
}

In `decisions`, include only the boundaries on which the proposed options
substantially diverged. Do not list obvious matching boundaries.

`reason` must briefly explain the decision through the semantic structure of the source
text, not through the number of votes.

If no result can be obtained from the proposed options without an obvious
error:

{
  "status": "no_valid_option",
  "problem": "..."
}

## Final check

Before answering, check:

- the result consists only of verbatim continuous parts of the source text;
- the order is kept;
- no meaningful text is lost;
- fragments do not overlap;
- each chosen boundary separates independent complete thoughts;
- where there is no boundary, explicitly linked parts of one thought stay together;
- the decision is not based on model voting;
- you have not added a new boundary that was not among the candidates.

## Source text

{{input}}

## Slicing options

{{options}}