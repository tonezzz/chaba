Prepare a proposal for review from this synthetic request:

{{TASK}}

Return one JSON object only, with case_id, goal, recommendation,
viewpoints, options, assumptions, open_questions, and
matching_existing_work. Keep each viewpoint concise but substantive.
Copy this structure exactly; keep the JSON types and keys unchanged:
{"case_id":"","goal":"","recommendation":"",
"viewpoints":{"user_value":"","technical":"","operations_safety":"",
"cost_effort":""},
"options":[{"label":"A","benefit":"","tradeoff":""},
{"label":"B","benefit":"","tradeoff":""}],
"assumptions":[],"open_questions":[],
"matching_existing_work":{"status":"not_evaluated","matches":[]}}
Set case_id to the exact value from the synthetic request. Use [] for
assumptions/open_questions if none are needed. Do not claim
existing matches; no repository or SSOT lookup is available. This is
review material only; no task will be executed from this output.
Recommendation must be a non-empty next step; when key details are missing,
recommend holding action until they are clarified. Every explicitly missing
target, budget, model, or compatibility detail must be asked in
open_questions, not silently assumed.
