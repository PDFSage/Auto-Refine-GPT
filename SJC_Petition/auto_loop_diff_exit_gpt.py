#!/usr/bin/env python3
import os
import argparse
import difflib
import time
import threading
from openai import OpenAI

def diff_ratio(a: str, b: str) -> float:
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instructions", help="Path to instructions UTF-8 file")
    parser.add_argument("filepath", help="Path to input file or directory of UTF files")
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--model", default="o1-pro")
    args = parser.parse_args()

    with open(args.instructions, "r", encoding="utf-8") as ins:
        instructions = ins.read()

    if os.path.isdir(args.filepath):
        parts = []
        for fname in sorted(os.listdir(args.filepath)):
            if fname.lower().endswith((".utf", ".txt")):
                path = os.path.join(args.filepath, fname)
                with open(path, "r", encoding="utf-8") as f:
                    parts.append(f.read())
        current_text = "\n".join(parts)
    else:
        with open(args.filepath, "r", encoding="utf-8") as f:
            current_text = f.read()

    original_text = current_text
    history_text = original_text
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    base = os.path.splitext(os.path.basename(args.filepath))[0]
    debug_dir = f"debug_{base}"
    os.makedirs(debug_dir, exist_ok=True)
    iteration = 1

    while True:
        start_time = time.time()
        done_event = threading.Event()

        def timer():
            while not done_event.is_set():
                elapsed = int(time.time() - start_time)
                print(f"[DEBUG] Iteration {iteration}: API request in progress: {elapsed}s")
                time.sleep(1)

        thread = threading.Thread(target=timer)
        thread.daemon = True
        thread.start()

        print(f"[DEBUG] Iteration {iteration}: Sending API request with cumulative input")
        response = client.responses.create(
            model=args.model,
            instructions=instructions,
            input=history_text
        )

        done_event.set()
        thread.join()
        total_time = time.time() - start_time
        print(f"[DEBUG] Iteration {iteration}: API request completed in {total_time:.2f}s")
        print(f"[DEBUG] Iteration {iteration}: Successful response received")

        new_text = response.output_text
        dbg_path = os.path.join(debug_dir, f"{base}_iter_{iteration}.txt")
        with open(dbg_path, "w", encoding="utf-8") as df:
            df.write(new_text)
        print(f"[DEBUG] Iteration {iteration}: Response written to {dbg_path}")

        ratio = diff_ratio(current_text, new_text)
        print(f"[DEBUG] Iteration {iteration}: diff_ratio={ratio:.6f}")

        if ratio < args.threshold:
            current_text = new_text
            print(f"[DEBUG] Iteration {iteration}: Diff below threshold, stopping")
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