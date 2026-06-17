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
