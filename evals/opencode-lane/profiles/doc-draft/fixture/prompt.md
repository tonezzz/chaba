# Task: repo-grounded document draft — {{TASK}}

Write the document described in the job spec for job {{JOB}} on host
{{HOST}}. Read the checkout first — every claim in the document must be
grounded in files you actually opened (cite real paths, enums,
function names).

- The document lands at the path declared in the job; begin the output
  with `# <that path>` as the first line, then the document itself.
- Emit ONLY the markdown as your final message. You hold no write
  tools; the runner writes the file from your message.
- No bash, no network, no writes — every denied call fails the job.
- If the job declares required sentinel strings, they must appear
  verbatim in the document.
