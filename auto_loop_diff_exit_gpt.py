#!/usr/bin/env python3
import os
import argparse
import difflib
import time
import threading
import smtplib
import ssl
from email.message import EmailMessage
from openai import OpenAI

MAX_RETRIES = 5
RETRY_DELAY = 2  # seconds

PROGRAMMING_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".swift", ".sh", ".pl"
}


def is_programming_file(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1] in PROGRAMMING_EXTENSIONS


def diff_ratio(a: str, b: str) -> float:
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def request_with_retry(
    client: OpenAI, model: str, instructions: str, history: str, iteration: int
) -> str:
    for attempt in range(MAX_RETRIES + 1):
        start_time = time.time()
        done_event = threading.Event()

        def timer():
            while not done_event.is_set():
                elapsed = int(time.time() - start_time)
                print(f"[DEBUG] Iter {iteration}, try {attempt + 1}: {elapsed}s")
                time.sleep(1)

        thread = threading.Thread(target=timer, daemon=True)
        thread.start()
        try:
            print(f"[DEBUG] Iter {iteration}, try {attempt + 1}: sending request")
            resp = client.responses.create(
                model=model, instructions=instructions, input=history
            )
            done_event.set()
            thread.join()
            print(f"[DEBUG] Iter {iteration}, try {attempt + 1}: success")
            return resp.output_text
        except Exception as e:
            done_event.set()
            thread.join()
            print(f"[ERROR] Iter {iteration}, try {attempt + 1}: {e}")
            if attempt == MAX_RETRIES:
                raise
            print(f"[DEBUG] Iter {iteration}: retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instructions", help="Path to instructions UTF-8 file")
    parser.add_argument("filepath", help="Path to input file or directory of UTF files")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.2,
        help="diff ratio threshold as decimal",
    )
    parser.add_argument(
        "--threshold-percent",
        type=float,
        help="diff ratio threshold as percentage (e.g. 5 for 5%%, overrides --threshold)",
    )
    parser.add_argument("--model", default="o3-pro")
    parser.add_argument("--email", help="Email address to notify each iteration")
    parser.add_argument(
        "--no-direct",
        action="store_true",
        help="Disable in-place edit even for single programming files",
    )
    args = parser.parse_args()

    if os.path.isdir(args.filepath) and not args.no_direct:
        # in-place editing only makes sense for single files
        print("[INFO] Directory input detected, in-place edits disabled")

    # determine threshold
    threshold = (
        args.threshold_percent / 100.0
        if args.threshold_percent is not None
        else args.threshold
    )

    with open(args.instructions, "r", encoding="utf-8") as ins:
        instructions = ins.read()

    # auto-append hint so model returns code only
    if is_programming_file(args.filepath):
        instructions += (
            "\n\nIMPORTANT: Only return the complete, revised source code file. "
            "Do not include any extra text or explanations."
        )

    if os.path.isdir(args.filepath):
        parts = []
        for fname in sorted(os.listdir(args.filepath)):
            if fname.lower().endswith((".utf", ".txt")):
                with open(
                    os.path.join(args.filepath, fname), "r", encoding="utf-8"
                ) as f:
                    parts.append(f.read())
        current_text = "\n".join(parts)
    else:
        with open(args.filepath, "r", encoding="utf-8") as f:
            current_text = f.read()

    history_text = current_text
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    base = os.path.splitext(os.path.basename(args.filepath))[0]
    debug_dir = f"debug_{base}"
    os.makedirs(debug_dir, exist_ok=True)
    iteration = 1

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
                print("[DEBUG] Logged into Gmail SMTP")
            except Exception as e:
                print(f"[WARN] Gmail login failed: {e}")

    while True:
        try:
            new_text = request_with_retry(
                client, args.model, instructions, history_text, iteration
            )
        except Exception as e:
            print(f"[FATAL] Iter {iteration}: {e}")
            break

        dbg_path = os.path.join(debug_dir, f"{base}_iter_{iteration}.txt")
        with open(dbg_path, "w", encoding="utf-8") as df:
            df.write(new_text)
        print(f"[DEBUG] Iter {iteration}: response written to {dbg_path}")

        ratio = diff_ratio(current_text, new_text)
        print(f"[DEBUG] Iter {iteration}: diff_ratio={ratio:.6f}")

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
                print("[DEBUG] Email sent")
            except Exception as e:
                print(f"[WARN] Email send failed: {e}")

        if ratio < threshold:
            print(f"[DEBUG] Iter {iteration}: threshold met, stopping")
            current_text = new_text
            break

        current_text = new_text
        history_text += "\n\n" + new_text
        iteration += 1

    if email_server:
        try:
            email_server.quit()
        except Exception:
            pass

    programming_mode = is_programming_file(args.filepath)

    if programming_mode and not args.no_direct:
        with open(args.filepath, "w", encoding="utf-8") as f:
            f.write(current_text)
        print(f"Updated {args.filepath}")
    else:
        output_path = f"output_{base}.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(current_text)
        print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
