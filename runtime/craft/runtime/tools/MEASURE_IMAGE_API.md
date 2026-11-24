# Image API comparison measurements

Added 19 November 2026. This wrapper runs the installed image-generation CLI without
modifying that CLI. It measures one text-only GPT-Image-2.6 high generation at
1024 × 1024. The default model is `gpt-image-2.6-sunburst`; Flare is an explicit
option. It does not read previous creative prompts or images.

## Credentials

Run `python3 measure_image_api.py configure-key` in an interactive Terminal. The
prompt is hidden. The command creates an owner-only file at
`~/.config/adopecli-benchmark/openai-api-key`, outside the repository, with mode 600.
It refuses to overwrite an existing file. This is a local plaintext credential,
not an encrypted keychain entry. Never paste credentials into the chat.

Generation reads `OPENAI_API_KEY` if available, otherwise the private file. It sets
the variable only inside the wrapper process for the bundled CLI's prerequisite
check. Restarting the desktop app or exporting the key in another shell is not
required. No credential is written to the attempt records.

## Execution and evidence

Use a Python environment with the `openai` package installed:

```sh
python measure_image_api.py generate \
  --attempt-dir /absolute/path/to/new-attempt \
  --prompt-file /absolute/path/to/newly-authored-prompt.txt
```

Each invocation creates a new directory exclusively. It records the attempt before
prerequisite checks and the API start before calling the provider. SDK retries are
disabled. Any deliberate retry must use a new directory and be included in totals.

Records include the exact request, model, quality, prompt, provider request ID,
HTTP status, full returned usage object, elapsed time, original PNG and its hash.
Usage is saved even when image decoding or PNG validation fails. Missing usage,
timeouts and interrupted calls have unknown cost pending provider reconciliation;
they must never be silently counted as free. A start record without a finish
record remains an incomplete attempt. Provider usage is not an invoice. Calculate
API-equivalent cost using dated public rates and distinguish it from billed cost.

`attempt-result.json` provides the preview path. No SDK response image data enters
the agent's text context. There are no automatic image corrections or creative
prompts embedded in this wrapper.

The default endpoint is fixed to `https://api.openai.com/v1`. The wrapper uses the
SDK's raw-response interface to retain usage before the bundled CLI saves the PNG.
Reference: <https://developers.openai.com/api/reference/python>.

## Power capture

Run `sh start_comparison_power.sh` in the owner's Terminal. It asks for the Mac
password through `sudo`, elevating only `/usr/bin/powermetrics`. It does not change
sudo rules, install a service, or change power settings. The shell creates a new
private log directory and opens the log as the normal user, keeping it readable
by the comparison controller. Each capture lasts at most 30 minutes. Ctrl-C ends
it early. Start a new capture if it expires before the comparison begins.

Plug in the Mac, keep its lid open, and avoid other heavy work. The controller
must collect an idle baseline, correlate samples with every render's timestamps,
and reject gaps or sleep intervals. Preserve gross and baseline-adjusted energy.
Do not run rendering concurrently with another local production task.

Apple describes CPU/GPU/ANE power values as estimates. Integrating those samples
gives estimated chip energy, not measured wall-plug electricity. This excludes
unreported components, charging and conversion losses. Actual whole-machine
electricity requires an external meter. Runtime multiplied by a declared machine
hourly rate is a separate cost basis; CPU seconds are not watt-hours.

Price electricity using the owner's tariff and currency. Report depreciation
separately using an explicit machine-cost and utilization basis. Do not label an
assumed tariff or an allocated machine rate as a measured charge.

## Local verification

`python -m unittest test_measure_image_api -v` runs seven local SDK transport
fixtures: successful usage/image capture, server failure without retries, timeout
with unknown cost, PNG failure retaining usage, missing usage, existing directory
protection, and private credential handling. No fixture sends a network request.
Verified with OpenAI Python 3.55.1 on 19 November 2026. Live model access, billing,
and privileged telemetry remain unverified until owner setup and the paid run.
