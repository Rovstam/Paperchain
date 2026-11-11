# Candidate sources

This folder is for sources an agent found but a human has not approved yet. `paperchain convert` ignores it, and you cannot cite anything here.

- One file per source: `Candidates/<key>.md`.
- `<key>` should match the name the file will have in `References/originals/`, for example `smith2024.pdf` gives the key `smith2024`.
- `paperchain check` warns while any proposal is still open.

Format:

```
key: smith2024
title: The title as published
where: https://doi.org/10.xxxx/xxxxx
why: supports the claim in section 3 about sampling
```

To approve a candidate, the human downloads the file into `References/originals/`, runs `paperchain convert`, then `paperchain lock`. Delete the proposal file afterwards.
