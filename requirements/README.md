# Pipeline Python environments

Two virtualenvs on the Mac mini, both **Python 3.13**:

| venv            | purpose                                            | lock file          |
|-----------------|----------------------------------------------------|--------------------|
| `~/venvs/pvcons`| pyannote diarization (`pipeline/diarize.py`)       | `pvcons.lock.txt`  |
| `~/venvs/tools` | yt-dlp + stdlib pipeline scripts (merge/analyze/assemble/scitt) | `tools.lock.txt` |

Recreate:

```
/opt/homebrew/bin/python3.13 -m venv ~/venvs/pvcons
~/venvs/pvcons/bin/pip install -r requirements/pvcons.lock.txt
/opt/homebrew/bin/python3.13 -m venv ~/venvs/tools
~/venvs/tools/bin/pip install -r requirements/tools.lock.txt
```

## Why Python 3.13 (not 3.12)

Homebrew `python@3.12` is broken on this machine's macOS (Darwin 25): its
prebuilt `pyexpat` links against a system `libexpat` whose symbols
changed, so `ensurepip`/`pip` and any XML-using tool (including Homebrew
`yt-dlp`) fail with `No module named expat`. `python3.13` works cleanly.

## Load-bearing pins (do not bump casually)

These exact versions were found by trial; the lock files encode them but
the *reasons* live here:

- **torch / torchaudio == 2.7.1** — pyannote.audio 3.4.0 imports
  `torchaudio.AudioMetaData` (removed in torchaudio ≥2.9), and Python
  3.13 has no torch wheel below 2.6. 2.7.1 is the working middle.
- torch ≥2.6 defaults `torch.load(weights_only=True)`, which rejects the
  official pyannote 3.1 checkpoint. `pipeline/diarize.py` monkeypatches
  `torch.load` to `weights_only=False` (the model is fetched from the
  trusted gated HF repo).
- **huggingface_hub == 0.25.2** — ≥1.x removed the `use_auth_token`
  kwarg that pyannote.audio 3.4.0 still passes.
- **pyannote.audio == 3.4.0** — current 3.x; the constraints above are
  all relative to it.

Regenerate the lock files after any intentional change:

```
~/venvs/pvcons/bin/pip freeze | grep -viE '^(pip|setuptools|wheel)==' > requirements/pvcons.lock.txt
~/venvs/tools/bin/pip  freeze | grep -viE '^(pip|setuptools|wheel)==' > requirements/tools.lock.txt
```
