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


def diff_ratio(a: str, b: str) -> float:
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def send_mail(to_addr: str, subject: str, body: str) -> None:
    user = os.environ.get("GMAIL_ADDRESS")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        print("[WARN] Gmail credentials missing")
        return
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pwd)
            s.send_message(msg)
        print("[DEBUG] Email sent")
    except Exception as e:
        print(f"[WARN] Email send failed: {e}")


def request_with_retry(client: OpenAI, model: str, instructions: str, history: str, iteration: int) -> str:
    for attempt in range(MAX_RETRIES + 1):
        start_time = time.time()
        done_event = threading.Event()

        def timer():
            while not done_event.is_set():
                elapsed = int(time.time() - start_time)
                print(f"[DEBUG] Iteration {iteration}, attempt {attempt + 1}: {elapsed}s elapsed")
                time.sleep(1)

        thread = threading.Thread(target=timer, daemon=True)
        thread.start()
        try:
            print(f"[DEBUG] Iteration {iteration}, attempt {attempt + 1}: sending request")
            resp = client.responses.create(model=model, instructions=instructions, input=history)
            done_event.set()
            thread.join()
            print(f"[DEBUG] Iteration {iteration}, attempt {attempt + 1}: success")
            return resp.output_text
        except Exception as e:
            done_event.set()
            thread.join()
            print(f"[ERROR] Iteration {iteration}, attempt {attempt + 1}: {e}")
            if attempt == MAX_RETRIES:
                raise
            print(f"[DEBUG] Iteration {iteration}: retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
    raise RuntimeError("Unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instructions", help="Path to instructions UTF-8 file")
    parser.add_argument("filepath", help="Path to input file or directory of UTF files")
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--model", default="o1-pro")
    parser.add_argument("--email", help="Email address to notify each iteration")
    args = parser.parse_args()

    with open(args.instructions, "r", encoding="utf-8") as ins:
        instructions = ins.read()

    if os.path.isdir(args.filepath):
        parts = []
        for fname in sorted(os.listdir(args.filepath)):
            if fname.lower().endswith((".utf", ".txt")):
                with open(os.path.join(args.filepath, fname), "r", encoding="utf-8") as f:
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

    while True:
        try:
            new_text = request_with_retry(client, args.model, instructions, history_text, iteration)
        except Exception as e:
            print(f"[FATAL] Iteration {iteration}: {e}")
            break

        dbg_path = os.path.join(debug_dir, f"{base}_iter_{iteration}.txt")
        with open(dbg_path, "w", encoding="utf-8") as df:
            df.write(new_text)
        print(f"[DEBUG] Iteration {iteration}: response written to {dbg_path}")

        ratio = diff_ratio(current_text, new_text)
        print(f"[DEBUG] Iteration {iteration}: diff_ratio={ratio:.6f}")

        if args.email:
            send_mail(
                args.email,
                f"Iteration {iteration} completed (ratio {ratio:.6f})",
                f"Response saved to {dbg_path}\n\nFirst 500 characters:\n{new_text[:500]}",
            )

        if ratio < args.threshold:
            print(f"[DEBUG] Iteration {iteration}: threshold met, stopping")
            current_text = new_text
            break

        current_text = new_text
        history_text += "\n\n" + new_text
        iteration += 1

    output_path = f"output_{base}.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(current_text)
    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()