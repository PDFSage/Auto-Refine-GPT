
# Auto-Refine

A command-line tool that iteratively refines text or source code files using the OpenAI API, stopping when changes fall below a configurable diff threshold. Optional in-place edits and email notifications.

## Features

- Iteratively sends file contents plus user instructions to OpenAI, saves each iteration’s output
- Computes a diff ratio; stops when ratio falls below threshold
- Supports directories of `.utf`/`.txt` parts or single programming files
- Optional in-place editing of source files
- Configurable diff threshold (decimal or percentage)
- Retry logic with debug output
- Optional email notification after each iteration

## Requirements

- Python 3.7+
- `openai` Python package

```sh
pip install openai

	•	Set environment variable:
	•	OPENAI_API_KEY – your OpenAI API key
	•	(Optional, for email notifications)
	•	GMAIL_ADDRESS – your Gmail address
	•	GMAIL_APP_PASSWORD – an app password for SMTP

Usage

python3 refine.py INSTRUCTIONS_FILE PATH [options]

	•	INSTRUCTIONS_FILE
Path to a UTF-8 text file containing instructions for the refinement.
	•	PATH
Path to a single file or directory of .utf/.txt parts.

Options
	•	--threshold FLOAT
Diff ratio threshold as a decimal (default: 0.2).
	•	--threshold-percent FLOAT
Diff ratio threshold as a percentage (e.g. 5 for 5%; overrides --threshold).
	•	--model STR
OpenAI model to use (default: o3-pro).
	•	--email STR
Email address to notify after each iteration.
	•	--no-direct
Disable in-place edits even for single programming files.

Examples

Refine a single text file until changes are under 10%:

python3 refine.py instructions.txt article.txt --threshold-percent 10

Refine a directory of .txt parts, send email each iteration, use GPT-4:

python3 refine.py instructions.txt ./chapters \
  --model gpt-4 --email you@example.com

Disable in-place edits (always write to output_<basename>.txt):

python3 refine.py instructions.txt script.py --no-direct

How It Works
	1.	Load instructions from INSTRUCTIONS_FILE.
	2.	Read input from a file or concatenate all .utf/.txt files in a directory.
	3.	Append a hint to output code-only responses when refining a programming file.
	4.	Loop:
	•	Send instructions + history to OpenAI (with retry logic and debug timers)
	•	Save each iteration’s output in debug_<basename>/<basename>_iter_<n>.txt
	•	Compute diff ratio between previous and new text
	•	Optionally send an email notification
	•	Stop when diff ratio < threshold
	5.	Write final result:
	•	If in programming mode and --no-direct not set, overwrite original file
	•	Otherwise, write to output_<basename>.txt

License

MIT License

