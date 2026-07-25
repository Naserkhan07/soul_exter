# Opening the project in VS Code

## One command

```bash
git clone -b arena/019f98a2-soul-exter https://github.com/Naserkhan07/soul_exter.git && code soul_exter
```

The `-b arena/019f98a2-soul-exter` is **required**. All the work lives on
that branch; `main` is still just an empty README.

Already cloned it?

```bash
cd soul_exter
git fetch
git checkout arena/019f98a2-soul-exter
git pull
```

## Then set it up

In the VS Code terminal (**Ctrl + `**):

**Windows**
```cmd
setup.bat
```

**macOS / Linux**
```bash
./setup.sh
```

That creates `.venv`, installs a bundled ffmpeg, and runs `doctor` to check
everything. Takes about a minute.

## Confirm it works

```cmd
.venv\Scripts\python.exe -m soulclip.cli render examples\lighthouse.txt --provider mock --target 60 -o demo.mp4
```

On macOS/Linux use `.venv/bin/python` instead. You should get a 1m40s
`demo.mp4` — placeholder cards, not AI video, but it proves the whole
pipeline runs.

## Built-in tasks

**Ctrl+Shift+P** > *Tasks: Run Task*:

| Task | Does |
|---|---|
| soulclip: setup | creates the venv and installs ffmpeg |
| soulclip: doctor | checks ffmpeg and which API keys are set |
| soulclip: offline demo | renders a test film |
| soulclip: run tests | runs all 118 tests |

## Selecting the interpreter

`.vscode/settings.json` points VS Code at `.venv` already. If it does not
pick it up, hit **Ctrl+Shift+P** > *Python: Select Interpreter* and choose
the one inside `.venv`.

## What you can and cannot run locally

| | Works on your laptop? |
|---|---|
| Editing code, running tests | yes |
| `--provider mock` (placeholders) | yes |
| `--provider folder` (your own images) | yes |
| `--story` storyboarding | yes |
| Stitching, crossfades, audio mixing | yes |
| `--provider ltx` / `wan` (real AI video) | **no — needs a GPU** |

For real generation, use the Kaggle notebook: **[KAGGLE_SETUP.md](KAGGLE_SETUP.md)**.

## Layout

```
soulclip/          the bot
  cli.py           command line entry point
  storyboard.py    prose -> scenes, character consistency
  script_parser.py scene splitting
  providers.py     mock / folder / replicate / fal / xai
  ltx.py  wan.py   GPU video models
  pipeline.py      orchestration, resume, retries
  ffmpeg.py        stitching, crossfades
  audio.py         narration, music, ambience
tests/             118 tests
notebooks/         Kaggle and Colab notebooks
docs/              setup, hardware and cost guides
examples/          sample scripts
```
