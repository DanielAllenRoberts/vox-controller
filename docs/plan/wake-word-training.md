# Vox Controller — Custom "Hey Vox" Wake Word Training

> **Goal:** replace the stock `hey_jarvis` model (M0) with a custom **"Hey Vox"** openWakeWord model and load it from `config.py`. Research-only plan — no code or installs yet.

## TL;DR

- openWakeWord trains custom models from **100% synthetic positive audio** (TTS via [piper-sample-generator](https://github.com/rhasspy/piper-sample-generator)) plus large pre-collected **negative/background** sets. No human recordings of "Hey Vox" are needed.
- The official path is the **`automatic_model_training.ipynb` notebook**, run on **Google Colab with a free T4 GPU**. It outputs **both `.onnx` and `.tflite`** for the trained phrase.
- **A GPU is effectively required, and training is Linux-only** (Piper TTS dependency). On an Apple-Silicon Mac you do **not** train locally — you train in Colab and download the `.onnx`.
- Plugging in is one config change: point `wake_word_model` at the `.onnx` **file path** and fix the predict-key mismatch (see [Integration](#integration-into-this-project)).
- Rough effort: a demo-quality model in **~1 hour** end-to-end in Colab; a usable daily-driver model needs **larger sample counts + threshold tuning in our actual room**, so budget a few iterations.

## Why synthetic data

openWakeWord's included models were trained on **synthetic positives** (TTS) and **~30,000 hours of negative** speech/noise/music. We never record ourselves saying "Hey Vox"; we generate thousands of varied TTS utterances instead. This is the supported, repeatable workflow.

## The training pipeline (what the notebook does)

Source: [`notebooks/automatic_model_training.ipynb`](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb).

1. **Positives** — clones `rhasspy/piper-sample-generator`, downloads the `en_US-libritts_r-medium.pt` generator checkpoint, and synthesizes spoken "hey vox" clips across varied voices/accents (the generator mixes speaker embeddings; **English-only**). The notebook demo uses `n_samples = 1000` positives; this is explicitly a small demo value, "recommend increasing for full-scale training."
2. **Negatives / background** — downloads, for augmentation and false-positive estimation:
   - **MIT room impulse responses** (reverberation realism),
   - **AudioSet** (one shard, `bal_train09.tar`),
   - **Free Music Archive (FMA)** "small" split,
   - openWakeWord **pre-computed features from ACAV100M** (~2,000 hours training) and a **validation set (~11 hours)** for false-positive-rate estimation.
   - Note: "for the best possible performance it is recommended to download the entire dataset" rather than the demo shards.
3. **Augment + train** — augments positives with the noise/music/RIR data, then trains a small DNN classifier on top of openWakeWord's frozen melspectrogram + embedding feature extractors. Uses "cyclical weight schedules for negative examples to help the model reduce false-positive rates." Demo targets: `target_accuracy = 0.6`, `target_recall = 0.25`; the notebook's stated quality guidance is roughly **accuracy ≥ 0.7, recall ≥ 0.5, false-positive rate ≤ 0.2/hour** — but it stresses you must validate in your **own** deployment environment.
4. **Export** — writes `my_custom_model/<name>.onnx` **and** `<name>.tflite`. "Either version can be used as normal with openwakeword." We take the **`.onnx`** (this project pins `inference_framework="onnx"`).

## GPU / Colab / effort

- **Linux-only:** the notebook states automated training "is only supported on linux systems due to the requirements of the text to speech library used for synthetic sample generation." So **don't train on the Mac** — use Colab (or a Linux box / WSL2).
- **GPU:** strongly recommended. piper-sample-generator is "much faster... if you have a GPU"; the notebook quotes "~10 minutes on a free Google Colab instance with a T4 GPU" just for clip generation.
- **Effort:** the demo end-to-end is roughly **~1 hour** on free Colab. A daily-driver model = more positive samples + full negative sets + tuning, so plan on a couple of training/eval iterations rather than one shot.

## Integration into this project

The resulting `.onnx` is loaded by **path**, not by a built-in name. Verified against the installed `openwakeword==0.6.0` source (`openwakeword/model.py`):

- `Model(wakeword_models=[...])` accepts either built-in names **or filesystem paths** to `.onnx`/`.tflite`.
- When a path exists on disk, the predict() key is derived as **`os.path.splitext(os.path.basename(path))[0]`** — i.e. the **filename without extension**. So `models/hey_vox.onnx` → `predict()` returns the key **`"hey_vox"`**, *not* the full path.

**Steps:**

1. **Place the file** — commit the small `.onnx` (built-in models are ~hundreds of KB) under a tracked path, e.g. `src/vox/wakeword/models/hey_vox.onnx`. (Confirm size before committing; if large, gitignore + document download instead — see overview's "nothing sensitive / data in repo" principle.)
2. **`config.py`** — set `wake_word_model` to the **path** (resolved absolutely at runtime), e.g. derive from the package dir. Keep `wake_threshold` configurable; expect to retune it.
3. **Fix the key mismatch in `openwakeword_detector.py`** — today `self._key = model_name`. With a built-in name that equals the predict key; with a **path** it won't. Set the key to the basename-without-extension:
   - `self._key = os.path.splitext(os.path.basename(model_name))[0]` (only the basename form matches `predict()`'s dict key).
4. **`download_models([...])` is safe with a path** — verified: a non-built-in string matches no official model, so the call is a no-op for the custom model (it still ensures the shared melspectrogram/embedding/VAD extractors exist). No need to special-case it, though guarding it for clarity is reasonable.

## Gotchas

- **"Hey Vox" is short (two syllables).** Short/common-sounding phrases are harder and more prone to false accepts than longer ones; this is *why* "Hey Vox" was chosen over bare "Vox," but it still argues for **more training data and careful threshold tuning**.
- **Threshold is environment-specific.** openWakeWord ships a default of **0.5**, but explicitly says to "determine the best threshold for your environment and use-case through testing." Tune `wake_threshold` against our real mic/room.
- **Second-stage filtering exists** if false accepts persist: openWakeWord supports the `vad_threshold` arg and optional **custom verifier models** (per-voice second-stage filter). Note: this detector hardcodes `inference_framework="onnx"` and doesn't set `vad_threshold` — both are knobs we can add later.
- **Sample count drives quality.** 1,000 positives is a demo; expect to scale to many thousands and use the full negative sets for a daily driver. "Performance seems to increase smoothly with increasing dataset size."
- **Don't expect Mac-local training.** Generating samples + training is Colab/Linux; only **inference** runs on the Mac.

## Open questions / unknowns

- **Exact production sample count** — the notebook says "increase for full-scale training" but gives no hard number; we'll have to find the knee empirically (start ~10–20k positives?).
- **Total Colab wall-clock for a *full* (non-demo) run** with the entire negative dataset — only the ~10-min clip-generation figure is documented; full training time is unstated.
- **Whether to commit the `.onnx`** — depends on final file size vs. the repo's "code only, no data" principle; decide after we have a model.
- **Whether 0.6.0 is the right pin for training-output compat** — we pin `openwakeword>=0.6.0` (0.6.0 installed); confirm the notebook's exported model format loads cleanly in our pinned version, or bump if needed.
- **README vs. notebook drift** — the GitHub README's quick-start references an older `synthetic_speech_dataset_generation` repo; the *current notebook* uses `piper-sample-generator`. Treat the **notebook** as the source of truth.

## Sources

- openWakeWord repo & README — https://github.com/dscripka/openWakeWord
- Automatic training notebook — https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
- piper-sample-generator — https://github.com/rhasspy/piper-sample-generator
- Installed source verified locally: `openwakeword==0.6.0` (`openwakeword/model.py`, `openwakeword/utils.py`)

## Runbook — train & install "Hey Vox"

> Copy-paste runbook. Verified against the **live** official notebook on `main`:
> https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
> (raw: `https://raw.githubusercontent.com/dscripka/openWakeWord/main/notebooks/automatic_model_training.ipynb`)
> and piper-sample-generator: https://github.com/rhasspy/piper-sample-generator
> Training happens in **Colab (Linux + GPU)**; only the exported `.onnx` comes back to this Mac.

### Part A — train `hey_vox.onnx` in Google Colab (free T4 GPU)

1. **Open the notebook in Colab.** Go to
   https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
   (or open Colab → *File → Open notebook → GitHub →* paste `dscripka/openWakeWord` → pick
   `notebooks/automatic_model_training.ipynb`).

2. **Select a GPU runtime.** *Runtime → Change runtime type → Hardware accelerator: **T4 GPU** → Save.*
   Training is **Linux + GPU only** (Piper TTS requirement); do not attempt this on the Mac.

3. **Run the setup cells in order, top to bottom** (do not skip any):
   - clones `rhasspy/piper-sample-generator` and downloads the generator checkpoint
     **`en_US-libritts_r-medium.pt`**;
   - `pip`-installs the training deps (e.g. `piper-phonemize`, `webrtcvad`, `openwakeword`,
     `torch`, `torchmetrics==1.2.0`, `tensorflow-cpu==2.8.1`, `onnx_tf==1.10.0`, `datasets==2.14.6`);
   - downloads the negative/background data: MIT room impulse responses, an AudioSet shard,
     FMA "small", and the pre-computed ACAV100M feature set + validation set.

4. **Edit the config cell for "hey vox".** The notebook loads `openwakeword/examples/custom_model.yml`
   into a `config` dict, then overrides keys. Set **exactly these values** (model name auto-derives
   from the phrase by replacing spaces with underscores → `hey_vox`):

   ```python
   config["target_phrase"] = ["hey vox"]                       # the phrase to synthesize (lowercase)
   config["model_name"]    = config["target_phrase"][0].replace(" ", "_")   # → "hey_vox"
   config["n_samples"]     = 1000     # START HERE (demo). For a daily driver bump to 10k–20k+.
   config["n_samples_val"] = 1000     # validation positives
   config["steps"]         = 10000    # training steps
   config["target_accuracy"] = 0.6    # demo targets; aim higher (≥0.7 acc, ≥0.5 recall) for real use
   config["target_recall"]   = 0.25
   # leave background_paths / false_positive_validation_data_path / feature_data_files
   # pointing at the datasets the earlier cells downloaded.
   ```

   Then write the config to disk as the notebook does, e.g. it dumps to **`my_model.yaml`**.

5. **Run the three training stages, in order** (these are the notebook's invocations):

   ```bash
   python openwakeword/openwakeword/train.py --training_config my_model.yaml --generate_clips
   python openwakeword/openwakeword/train.py --training_config my_model.yaml --augment_clips
   python openwakeword/openwakeword/train.py --training_config my_model.yaml --train_model
   ```

   `--generate_clips` is the Piper TTS step (~10 min on a T4 for the 1k-sample demo);
   `--augment_clips` mixes in RIR/noise/music; `--train_model` trains the classifier and exports.

6. **Download the model.** Training writes **`my_custom_model/hey_vox.onnx`** (and a matching
   `.tflite`). Grab the **`.onnx`** — this project pins `inference_framework="onnx"`.
   In Colab: open the file browser → `my_custom_model/` → download `hey_vox.onnx`,
   or run `from google.colab import files; files.download("my_custom_model/hey_vox.onnx")`.

7. **(Recommended) Validate the export before leaving Colab.** Sanity-check the file is a real,
   loadable openWakeWord model and produces non-zero scores on a positive clip there, so you don't
   discover a broken export only after coming back to the Mac. (Final compatibility check still
   happens locally in Part B step 4 against our **pinned** onnxruntime — see the version caveat.)

### Part B — install into this repo (Mac, inference only)

1. **Place the file.** Put the downloaded model at:

   ```
   src/vox/wakeword/models/hey_vox.onnx
   ```

   Create the `models/` dir if needed. (Built-in models are a few hundred KB; if `hey_vox.onnx`
   is similarly small, committing it is fine — otherwise gitignore it and document the download,
   per the repo's "code only, no data" principle.)

2. **Edit `src/vox/config.py`.** Point `wake_word_model` at the **resolved file path** (not a
   built-in name) and set the spoken/display phrase to "Hey Vox":

   ```python
   from pathlib import Path

   _WAKE_MODEL = Path(__file__).resolve().parent / "wakeword" / "models" / "hey_vox.onnx"

   @dataclass(frozen=True)
   class Config:
       ...
       wake_word_model: str = str(_WAKE_MODEL)   # absolute path to the custom .onnx
       wake_word_spoken: str = "Hey Vox"         # display phrase
       wake_threshold: float = 0.5               # expect to retune for our room (see below)
   ```

   No detector change is required: `OpenWakeWordDetector` already derives its predict key as
   `os.path.splitext(os.path.basename(model_name))[0]`, so a path ending in `hey_vox.onnx`
   yields the predict key **`"hey_vox"`** — which is exactly the dict key openWakeWord returns
   for a file-path model. (`download_models([...])` with a path is a harmless no-op for the custom
   model; it still ensures the shared feature extractors exist.)

3. **Run the diagnostics tool:**

   ```bash
   uv run vox-diagnose
   ```

4. **Validate detection AND runtime compatibility.** Say **"Hey Vox"** into the mic and confirm
   you get a **non-zero wake score** (ideally crossing `wake_threshold` on a clear utterance).
   - A flat **0.0** score on every frame — even when clearly saying the phrase — is the
     signature of the **onnxruntime version gotcha**: newer onnxruntime (e.g. ≥1.21, seen on 1.27)
     **silently returns 0.0** from openWakeWord's melspectrogram/embedding feature models. This repo
     therefore pins **`onnxruntime>=1.17,<1.21`**. If you see all-zeros, first verify the installed
     runtime is in range (`uv run python -c "import onnxruntime; print(onnxruntime.__version__)"`)
     **before** assuming the trained model is bad.
   - If scores are non-zero but detection is flaky, tune `wake_threshold` against the real mic/room.

### Open risks for "Hey Vox" specifically

- **Short two-syllable phrase.** "Hey Vox" is short and easy to false-trigger / under-detect.
  The 1k-sample demo is unlikely to be daily-driver quality — plan to **increase `n_samples`
  (10k–20k+)**, use the full negative sets, and **tune `wake_threshold`** over a couple of
  iterations. Start `wake_threshold` at the 0.5 default and adjust per measured false-accept rate.
- **Export ↔ runtime compatibility is the load-bearing risk.** The model is *trained/exported* under
  Colab's much newer onnxruntime, but we *run inference* under our pinned **`<1.21`**. An exported
  `.onnx` that loads in Colab can still misbehave (most dangerously: **silent 0.0 scores**) under a
  different runtime. **Always re-validate the model under our pinned onnxruntime locally** (Part B
  step 4) — a "successful" Colab export is **not** sufficient proof it works here.
