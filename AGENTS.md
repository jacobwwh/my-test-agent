## Purpose

This repository is about generating unit test cases (Java, C++, Python, ...) with local deployed LLMs.

Your job is to help with code understanding, code generation, refactoring, testing, and debugging **without taking unsafe actions on remote GPU infrastructure**.

When working in this repository, you must prioritize:
1. Safety of the remote GPU server
2. Reproducibility of experiments
3. Minimal and reviewable code changes
4. CPU-first validation before any GPU action
5. Human approval before any high-risk operation

---

## Project environment assumptions

- The actual GPU environment is a **remote SSH server**.
- The remote server may be **offline / air-gapped** and may not have internet access.
- The local machine used to run Codex may not have a GPU.
- Therefore, you must **not assume GPU availability locally**.
- You must **not assume the remote server can install packages from the internet**.
- You must **not introduce workflows that depend on ad hoc remote environment changes**.

---

## Core operating rules

### Rule 1: Never freely operate on the remote GPU server

Do **not** run arbitrary commands on the remote server.

If GPU validation is needed, only use the repository’s approved scripts and commands documented in this file or in project docs.

Allowed pattern:
- run a predefined script
- run a predefined Make target
- read logs produced by a predefined run
- inspect output artifacts

Disallowed pattern:
- exploratory shell usage on remote host
- modifying system configuration
- installing or upgrading drivers, CUDA, Python, or system packages
- killing unrelated processes
- changing shared environment variables or shared storage layout

---

### Rule 2: CPU-first, GPU-last

Before requesting or attempting any GPU-related action, always do the following first when applicable:

1. Read the relevant source files
2. Make the minimal code change
3. Run formatting, lint, static checks, and CPU-only tests
4. Explain what remains unverified without GPU
5. Only then propose a GPU smoke test

Never jump directly to full GPU training or long-running jobs if a smaller verification step is possible.

---

### Rule 3: Only use approved GPU entrypoints

For any GPU-related validation, only use explicitly approved commands such as:

- `make test-gpu-smoke`
- `make test-gpu-integration`
- `bash scripts/test_gpu_smoke.sh`
- `bash scripts/run_remote_debug.sh`
- `bash scripts/collect_logs.sh`

If the repository does not define an approved command for the requested GPU action:
- do not invent one silently
- do not improvise a remote command sequence
- instead, state that the action requires a new approved script or human execution path

---

### Rule 4: Never change the remote environment unless explicitly asked

Do not perform or suggest any of the following as an autonomous action:

- `apt install`, `apt upgrade`, `yum install`, `dnf install`
- `pip install` on the remote server
- `conda install` on the remote server
- changing NVIDIA driver / CUDA / cuDNN / NCCL
- editing `/etc/*`
- editing shell init files for all users
- editing SSH daemon or firewall settings
- mounting disks or changing permissions outside the project directory
- pulling images or dependencies from the internet on the remote host

If the task appears to require environment changes, stop and say so clearly.

---

### Rule 5: Treat GPUs as scarce shared resources

Assume the remote GPUs may be shared and expensive.

Therefore:
- prefer the smallest GPU test that can validate the change
- prefer a single batch / single step / tiny input smoke test
- avoid starting long training runs unless explicitly requested
- avoid occupying multiple GPUs unless explicitly requested
- avoid background jobs unless explicitly requested
- avoid repeated retries of failing GPU runs

If a small test fails, debug from logs before proposing another GPU run.

---

### Rule 6: Never use destructive process control without approval

Do not run commands such as:
- `kill -9`
- `pkill`
- `killall`
- mass process termination
- deleting checkpoints, logs, datasets, caches, or outputs

Exception:
- only if the user explicitly instructs you to terminate a specific project-owned process
- and the target is clearly identified
- and the action is scoped to this project only

If there is ambiguity, do not proceed.

---

### Rule 7: Never modify data, checkpoints, or experiment records silently

Do not delete or overwrite:
- datasets
- checkpoints
- benchmark outputs
- logs
- experiment summaries
- evaluation reports

If a task requires regenerating outputs, write new outputs to a new path or clearly versioned directory.

Prefer additive changes over destructive replacement.

---

### Rule 8: Keep changes minimal, reviewable, and reversible

When editing code:
- make the smallest change that solves the task
- avoid unrelated refactors
- avoid renaming files unless necessary
- avoid changing public APIs unless necessary
- avoid broad dependency updates

When possible:
- explain the rationale
- summarize changed files
- mention how to verify the change
- keep diffs easy for a human to review

---

## Required workflow for GPU-related tasks

When a task involves GPU functionality, follow this workflow strictly:

1. Inspect code paths relevant to the requested feature or bug
2. Identify whether the issue can be checked with CPU-only logic first
3. Make minimal code edits
4. Run local checks that do not require GPU
5. Propose the smallest approved GPU smoke test
6. Read logs and artifacts
7. Suggest the next step based on evidence

Do not skip steps unless the user explicitly asks for a narrower workflow.

---

## What to do when GPU access is required but unavailable

If you cannot directly execute the GPU step from the current environment:

- do not pretend the test was run
- do not claim the code is verified on GPU
- clearly separate:
  - what was verified locally
  - what still requires remote GPU validation
- provide the exact approved command the human should run, or generating scripts that cab be run by the developer themselves
- describe what log/output should be returned for further debugging

Example wording:
- “I validated the non-GPU parts locally. The CUDA path still requires remote verification with `make test-gpu-smoke`.”
- “I did not run the GPU test from here. Please run the approved smoke test and share the last 200 lines of the log.”