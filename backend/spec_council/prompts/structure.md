You only structure semantic fragments that are already prepared.

You are given a set of fragments with immutable IDs, text and type:
`idea`, `question`, `proposal`, `constraint`, `risk`.

Your task is to determine which fragments belong to one common initiative,
and to group them.

At this stage, never add new ideas, questions, proposals,
constraints or risks.

## What a group is

A group is a set of fragments that belong to one common initiative:
one desired change, result or independent line of work.

A group must be self-contained enough that later, separately for this group, it is possible to:
- refine the idea;
- look for missing questions;
- consider proposals;
- make decisions;
- form outcomes.

One source text may contain one group or several.

## How to find the groups

First find the explicitly stated `idea` fragments.

Attach fragments that are questions, proposals, constraints or risks
to the idea they belong to by meaning.

If there is no explicit `idea`, but several fragments clearly belong to one
unwritten initiative, they can still form a group.

Do not formulate the missing idea yourself.
Only mark that the group has no explicit `idea`.
It is restored at the next stage.

## When to split groups

Create different groups if the fragments belong to independent initiatives
that can later be refined and implemented independently.

Do not split a group just because it contains:
- several questions;
- several alternative proposals;
- different technical aspects of one initiative;
- several risks or constraints.

Competing proposals for one question belong to one group.

## Shared fragments

One constraint or risk may belong to several groups.

In that case, do not create a new fragment and do not copy it as a new source.
Put the same ID into each relevant group and mark the link as `shared`.

By default, an `idea`, `question` or `proposal` must belong to one group.
If you believe such a fragment really belongs to several groups,
explain why explicitly.

## Relations between groups

If the groups are not independent, state the relation.

Use only:

- `independent` — the groups can be considered independently;
- `depends_on` — one initiative needs the result of the other;
- `related` — the initiatives are related, but no dependency between them follows from the text.

Do not invent a dependency just because the groups are technically similar
or may use the same infrastructure.

## Rules

1. Do not change the text, IDs or types of the fragments.
2. Do not add new semantic fragments.
3. Do not formulate missing ideas.
4. Do not add questions or decisions.
5. Every fragment must end up in at least one group.
6. Do not create groups for the sake of a finer structure.
7. Do not merge independent initiatives just because they are
   in one source text.
8. Base the structure only on the meaning of the given fragments.

## Ambiguity

The structure may have several substantially different reasonable options.

Determine how many such options you actually see.

One option is a normal and expected result.
Do not create alternatives for the sake of variety.

Several options are needed only when there is real
ambiguity about:
- whether two parts are one initiative or different ones;
- which group a fragment belongs to;
- whether a fragment is shared;
- whether there is a relation between groups.

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
      "groups": [
        {
          "id": "A",
          "title": "Short neutral group name",
          "idea_fragment_ids": [1],
          "fragment_ids": [1, 2, 3, 4],
          "missing_idea": false,
          "shared_fragment_ids": []
        },
        {
          "id": "B",
          "title": "Another group",
          "idea_fragment_ids": [],
          "fragment_ids": [5, 6],
          "missing_idea": true,
          "shared_fragment_ids": [4]
        }
      ],
      "relations": [
        {
          "from": "B",
          "to": "A",
          "type": "depends_on",
          "reason": "A brief basis in the source fragments."
        }
      ],
      "reason": null
    }
  ]
}

`title` is only a short label for navigation.
It is not a new idea or a new requirement.

If there are several options, `reason` briefly explains the substantial difference
between the structures.

## Fragments

{{fragments}}