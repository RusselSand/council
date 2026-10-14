# Issue Dependencies

You set the dependencies between ISSUES of different OUTCOMES of one approved IDEA.

You are given:
- the approved IDEA;
- the approved OUTCOMES;
- all ISSUES: each OUTCOME was divided into ISSUES separately, so the dependencies inside one
  OUTCOME are already set (`depends_on`), and the dependencies between OUTCOMES are not;
- the existing repository.

You do not change the ISSUES: not their content, not their division, not the dependencies they
already have. You only add dependencies between ISSUES of different OUTCOMES.

## What a dependency is

An ISSUE depends on another one when the result of the other is necessary to complete it: for
example, the frontend that reads an endpoint needs the ISSUE that implements that endpoint, or a
rule needs the ISSUE that stores the data it reads.

Do not create a dependency only because the ISSUES:
- touch the same files;
- use the same service or the same data;
- are done in the same repository;
- would be more convenient to do in some order.

Dependencies must not form cycles.

`fixed: true` marks ISSUES that are being developed already: a new ISSUE may depend on them, but
do not add dependencies to them.

## Language

These instructions are in English, but write every free-text value of your answer —
statements, reasons, titles, descriptions, questions, proposals and the like — in
{{language}}. Text that these instructions require to be quoted verbatim stays exactly as in
the input. JSON keys, IDs and enum values stay exactly as specified below.

## Response format

Return only JSON. List only the ISSUES that get new dependencies; an empty list means there are
none:

{
  "dependencies": [
    {
      "issue_id": "I4",
      "depends_on": ["I2"],
      "reason": "Why I4 cannot be completed without the result of I2."
    }
  ]
}

## Final check

Before answering, check that:

- every dependency is between ISSUES of different OUTCOMES;
- the result of the ISSUE it points to is really necessary to complete the dependent one;
- no dependency is added to a fixed ISSUE;
- the dependencies do not form cycles.

## IDEA

{{idea}}

## OUTCOMES

{{outcomes}}

## ISSUES

{{issues}}

## REPOSITORY CONTEXT

{{repository_context}}
