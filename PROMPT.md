# Prompts used in Task-1

The extractor sends one prompt for each CIS recommendation to Gemma-3-1B (`google/gemma-3-1b-it`, chat template, greedy decoding).
In each template, `{requirement title}` and `{description, first 500 characters}` are replaced with text from the PDF.
The model answers with a line `ELEMENT: <name>`. `normalize_element()` in `src/cisdiff/extractor.py` reads that line.

Run `uv run python scripts/make_prompt_md.py` to make this file again after a prompt change.

## zero-shot

```text
You read security requirements from the CIS Docker Benchmark. A key data element (KDE) is the Docker component, resource or setting that a requirement is about, for example 'docker daemon', 'container', 'image', 'docker.sock' or '/etc/docker'.

What is the key data element of this requirement?

Requirement: {requirement title}
Description: {description, first 500 characters}

Answer with one line in this format and nothing else:
ELEMENT: <key data element, 1 to 4 words>
```

## few-shot

```text
You read security requirements from the CIS Docker Benchmark. A key data element (KDE) is the Docker component, resource or setting that a requirement is about, for example 'docker daemon', 'container', 'image', 'docker.sock' or '/etc/docker'.

Here are examples:

Requirement: Ensure that the Docker socket file ownership is set to root:docker
Description: The Docker socket docker.sock is owned by root and group docker.
ELEMENT: docker.sock

Requirement: Ensure that containers use only trusted base images
Description: Ensure that the container image is written either from scratch or is based on another established and trusted base image downloaded over a secure channel.
ELEMENT: image

Requirement: Ensure that the memory usage for containers is limited
Description: By default, all containers on a Docker host share resources equally.
ELEMENT: container

Now do the same for this requirement.

Requirement: {requirement title}
Description: {description, first 500 characters}

Answer with one line in this format and nothing else:
ELEMENT: <key data element, 1 to 4 words>
```

## chain-of-thought

```text
You read security requirements from the CIS Docker Benchmark. A key data element (KDE) is the Docker component, resource or setting that a requirement is about, for example 'docker daemon', 'container', 'image', 'docker.sock' or '/etc/docker'.

Requirement: {requirement title}
Description: {description, first 500 characters}

Think step by step:
1. What does the requirement tell the user to check or change?
2. Which Docker component, file or setting holds that check?
3. Give the shortest common name for that component.

Write at most three short reasoning lines, then end with one line in this format:
ELEMENT: <key data element, 1 to 4 words>
```
