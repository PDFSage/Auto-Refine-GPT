#!/usr/bin/env python3
import os
import re
import argparse
import difflib
import time
import threading
import smtplib
import ssl
from email.message import EmailMessage
from openai import OpenAI

INSTRUCTIONS = (
  "without changing or adding any structs, turn these 2 swift files into the most comprehensive and greatest physics learning files possible: "
)
DEFAULT_MODEL = "o3-pro"
MAX_RETRIES = 5
RETRY_DELAY = 2
PROGRAMMING_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".swift", ".sh", ".pl"
}


def is_programming_file(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1] in PROGRAMMING_EXTENSIONS


def diff_ratio(a: str, b: str) -> float:
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def token_len(s: str) -> int:
    return len(re.findall(r"\S+", s))


def request_with_retry(client: OpenAI, model: str, instructions: str,
                       history: str, iteration: int) -> str:
    for attempt in range(MAX_RETRIES + 1):
        start = time.time()
        done = threading.Event()

        def timer():
            while not done.is_set():
                print(f"[DEBUG] model {model} iter {iteration}, try {attempt + 1}: {int(time.time() - start)}s")
                time.sleep(1)

        threading.Thread(target=timer, daemon=True).start()
        try:
            print(f"[DEBUG] model {model} iter {iteration}, try {attempt + 1}: "
                  f"instructions_len={token_len(instructions)}, input_len={token_len(history)}")
            resp = client.responses.create(model=model,
                                           instructions=instructions,
                                           input=history)
            done.set()
            print(f"[DEBUG] model {model} iter {iteration}, try {attempt + 1}: success")
            return resp.output_text
        except Exception as e:
            done.set()
            print(f"[ERROR] model {model} iter {iteration}, try {attempt + 1}: {e}")
            if attempt == MAX_RETRIES:
                raise
            print(f"[DEBUG] model {model} iter {iteration}: retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
    raise RuntimeError("unreachable")


def gather_input(paths):
    parts = []
    for p in paths:
        if os.path.isdir(p):
            for fname in sorted(os.listdir(p)):
                if fname.lower().endswith((".utf", ".txt")):
                    with open(os.path.join(p, fname), encoding="utf-8") as f:
                        parts.append(f.read())
        else:
            with open(p, encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


def parse_multi_file_output(text, input_paths):
    # unified pattern: comments (#, //, ;, ') *or* dash-ruled headings (---, –––)
    marker = re.compile(
        r"(?m)^\s*(?:#|//|;|'|[-–—]{3,})\s*"      # line prefix
        r"(?:file\s*:)?\s*(?:\d+\.\s*)?"          # optional 'file:' / numbering
        r"([A-Za-z0-9_.]+\.\w+)",                 # captured filename
        re.UNICODE | re.I,
    )
    matches = list(marker.finditer(text))
    if not matches:
        return None
    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1).strip(), text[start:end].lstrip("\n")))
    out_map = {}
    remaining = {os.path.basename(p): p for p in input_paths}
    for fname, content in sections:
        base = os.path.basename(fname)
        if base in remaining:
            out_map[remaining.pop(base)] = content
    return out_map or None


def write_outputs(text, args, programming_mode) -> bool:
    if not programming_mode or args.no_direct:
        return True
    if len(args.filepaths) == 1:
        with open(args.filepaths[0], "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[DEBUG] updated {args.filepaths[0]}")
        return True
    out_map = parse_multi_file_output(text, args.filepaths)
    if out_map:
        for path, content in out_map.items():
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[DEBUG] updated {path}")
        return True
    print("[WARN] could not match output to files on this iteration")
    return False


def main():
    global MAX_RETRIES, RETRY_DELAY, PROGRAMMING_EXTENSIONS

    p = argparse.ArgumentParser()
    p.add_argument("--filepaths", nargs="+", required=True)
    p.add_argument("--threshold", type=float, default=0.2)
    p.add_argument("--threshold-percent", type=float)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--email")
    p.add_argument("--no-direct", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    p.add_argument("--retry-delay", type=float, default=RETRY_DELAY)
    p.add_argument("--extensions")
    p.add_argument("--api-key")
    p.add_argument("--debug-dir")
    args = p.parse_args()

    MAX_RETRIES = args.max_retries
    RETRY_DELAY = args.retry_delay
    if args.extensions:
        PROGRAMMING_EXTENSIONS = {e if e.startswith('.') else f'.{e}'
                                  for e in args.extensions.split(',')}

    print(f"[DEBUG] model selected: {args.model}")
    print(f"[DEBUG] instructions_len={token_len(INSTRUCTIONS)}")

    threshold = (args.threshold_percent / 100
                 if args.threshold_percent is not None else args.threshold)

    programming_mode = all(is_programming_file(p) for p in args.filepaths)

    instructions = INSTRUCTIONS
    if len(args.filepaths) == 1 and programming_mode:
        instructions += (
            "\n\nIMPORTANT: Only return the complete, revised source code file. "
            "Do not include any extra text or explanations."
        )

    current_text = gather_input(args.filepaths)
    history_text = current_text
    print(f"[DEBUG] initial input_len={token_len(history_text)}")

    client = OpenAI(api_key=args.api_key or os.environ.get("OPENAI_API_KEY"))

    base = os.path.splitext(os.path.basename(args.filepaths[0]))[0]
    debug_dir = args.debug_dir or f"debug_{base}"
    os.makedirs(debug_dir, exist_ok=True)

    email_server = None
    email_user = None
    if args.email:
        email_user = os.environ.get("GMAIL_ADDRESS")
        email_pwd = os.environ.get("GMAIL_APP_PASSWORD")
        if email_user and email_pwd:
            try:
                email_server = smtplib.SMTP_SSL(
                    "smtp.gmail.com", 465, context=ssl.create_default_context()
                )
                email_server.login(email_user, email_pwd)
                print("[DEBUG] logged into Gmail SMTP")
            except Exception as e:
                print(f"[WARN] Gmail login failed: {e}")

    iteration = 1
    while True:
        if args.limit is not None and iteration > args.limit:
            print(f"[DEBUG] iteration limit {args.limit} reached, stopping")
            break
        try:
            new_text = request_with_retry(
                client, args.model, instructions, history_text, iteration
            )
        except Exception as e:
            print(f"[FATAL] iter {iteration}: {e}")
            break

        dbg_path = os.path.join(debug_dir, f"{base}_iter_{iteration}.txt")
        with open(dbg_path, "w", encoding="utf-8") as df:
            df.write(new_text)
        print(f"[DEBUG] iter {iteration}: response written to {dbg_path}")

        if not write_outputs(new_text, args, programming_mode):
            print(f"[DEBUG] iter {iteration}: stopping due to unmatched outputs")
            break

        ratio = diff_ratio(current_text, new_text)
        print(f"[DEBUG] iter {iteration}: diff_ratio={ratio:.6f}")

        if email_server:
            try:
                msg = EmailMessage()
                msg["From"] = email_user
                msg["To"] = args.email
                msg["Subject"] = f"Iteration {iteration} completed (ratio {ratio:.6f})"
                msg.set_content(
                    f"Response saved to {dbg_path}\n\nFirst 500 chars:\n{new_text[:500]}"
                )
                email_server.send_message(msg)
                print("[DEBUG] email sent")
            except Exception as e:
                print(f"[WARN] email send failed: {e}")

        if ratio < threshold:
            print(f"[DEBUG] iter {iteration}: threshold met, stopping")
            break

        current_text = new_text
        history_text += "\n\n" + new_text
        iteration += 1

    if email_server:
        try:
            email_server.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
