import os
import json
import base64
import uvicorn
import argparse
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response
from litellm.types.router import Deployment

from llms import load_custom_llm
from logger import logger
from config import configure
from server.stream import Stream
from server.router import router
from server.reply_on_pause import ReplyOnPause
from server.utils import normalize_text
from constants import (
    BASIC_LLM_MODEL_NAME,
    AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
    TEXT_TO_SPEECH_MODEL_NAME,
)


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title=configure.title, description=configure.description, version=configure.version
)


def mount_stream_if_needed() -> None:
    if getattr(app.state, "stream_mounted", False):
        return

    stream = Stream(
        modality="audio",
        mode="send-receive",
        handler=ReplyOnPause(),
        additional_outputs_handler=lambda a, b: b,
        additional_inputs=[],
        additional_outputs=[],
        rtc_configuration=configure.server_rtc_configuration,
        server_rtc_configuration=configure.server_rtc_configuration,
        concurrency_limit=5,
        time_limit=None,
    )
    stream.mount(app=app)
    app.state.stream = stream
    app.state.stream_mounted = True


def bootstrap_runtime(config_path: str | None = None) -> None:
    if getattr(app.state, "runtime_bootstrapped", False):
        return

    if config_path is not None:
        configure.load_config_file(config_path=config_path)
    else:
        configure.refresh_available_voices(prefer_existing=False)

    load_custom_llm()
    for deployment in configure.model_list:
        router.add_deployment(deployment=Deployment(**deployment))  # type: ignore

    mount_stream_if_needed()
    app.state.runtime_bootstrapped = True


if __name__ != "__main__":
    bootstrap_runtime()


@app.get(f"/", response_class=HTMLResponse)
async def check_health():
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Voicebot</title>
            <style>
              body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; color: #111; }
              code { background: #f4f4f5; padding: 2px 6px; border-radius: 6px; }
              ul { line-height: 1.8; }
            </style>
          </head>
          <body>
            <h1>Voicebot is running</h1>
            <p>This deployment exposes API and websocket endpoints for the realtime assistant.</p>
            <p><a href="/playground">Open the interactive playground</a></p>
            <p><strong>Note:</strong> the playground below uses text and audio file upload, so it works over plain HTTP.</p>
            <ul>
              <li><code>POST /webrtc/offer</code></li>
              <li><code>WS /websocket/offer</code></li>
              <li><code>WS /telephone/websocket/signal</code></li>
              <li><code>WS /telephone/websocket/media</code></li>
              <li><code>/docs</code> for FastAPI docs</li>
            </ul>
          </body>
        </html>
        """
    )


@app.get("/playground", response_class=HTMLResponse)
async def playground():
    voices_json = json.dumps(configure.available_voices, ensure_ascii=False)
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Voicebot Playground</title>
            <style>
              :root {{
                --bg: #f5f1e8;
                --card: #fffdf8;
                --ink: #1f1a14;
                --muted: #6f675d;
                --line: #d7cfc2;
                --accent: #9d5c2f;
                --accent-2: #264653;
              }}
              * {{ box-sizing: border-box; }}
              body {{
                margin: 0;
                font-family: Georgia, "Times New Roman", serif;
                color: var(--ink);
                background:
                  radial-gradient(circle at top left, rgba(157,92,47,.12), transparent 30%),
                  linear-gradient(180deg, #f8f4ec 0%, var(--bg) 100%);
              }}
              main {{
                max-width: 1080px;
                margin: 0 auto;
                padding: 32px 20px 48px;
              }}
              h1 {{
                margin: 0 0 8px;
                font-size: clamp(2rem, 4vw, 3.4rem);
                line-height: 1;
              }}
              p.lead {{
                margin: 0 0 24px;
                color: var(--muted);
                font-size: 1.05rem;
              }}
              .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 18px;
              }}
              .card {{
                background: var(--card);
                border: 1px solid var(--line);
                border-radius: 18px;
                padding: 18px;
                box-shadow: 0 14px 40px rgba(0, 0, 0, .05);
              }}
              .card h2 {{
                margin: 0 0 10px;
                font-size: 1.25rem;
              }}
              label {{
                display: block;
                margin: 12px 0 6px;
                font-size: .95rem;
                color: var(--muted);
              }}
              textarea, select, input[type="file"] {{
                width: 100%;
                border: 1px solid var(--line);
                border-radius: 12px;
                padding: 12px;
                background: #fff;
                color: var(--ink);
                font: inherit;
              }}
              textarea {{
                min-height: 120px;
                resize: vertical;
              }}
              button {{
                margin-top: 14px;
                border: 0;
                border-radius: 999px;
                background: var(--accent);
                color: #fff;
                padding: 10px 16px;
                font: inherit;
                cursor: pointer;
              }}
              button.secondary {{ background: var(--accent-2); }}
              pre {{
                white-space: pre-wrap;
                word-break: break-word;
                background: #f7f4ee;
                border: 1px solid var(--line);
                border-radius: 12px;
                padding: 12px;
                min-height: 72px;
              }}
              audio {{
                width: 100%;
                margin-top: 12px;
              }}
              .status {{
                margin-top: 10px;
                color: var(--muted);
                min-height: 20px;
              }}
            </style>
          </head>
          <body>
            <main>
              <h1>Voicebot Playground</h1>
              <p class="lead">Use this page to validate the three live chains separately or run a full uploaded-audio roundtrip.</p>
              <div class="grid">
                <section class="card">
                  <h2>Text -> Reply -> Speech</h2>
                  <label for="text-input">Prompt</label>
                  <textarea id="text-input">你好，请做一个简短的自我介绍。</textarea>
                  <label for="text-voice">Voice</label>
                  <select id="text-voice"></select>
                  <button id="text-submit">Generate Reply</button>
                  <div class="status" id="text-status"></div>
                  <label>Reply</label>
                  <pre id="text-output"></pre>
                  <audio id="text-audio" controls></audio>
                </section>

                <section class="card">
                  <h2>Audio File -> Transcript</h2>
                  <label for="transcribe-file">Audio File</label>
                  <input id="transcribe-file" type="file" accept="audio/*">
                  <label for="transcribe-language">Language</label>
                  <select id="transcribe-language">
                    <option value="">auto</option>
                    <option value="chinese">chinese</option>
                    <option value="english">english</option>
                    <option value="japanese">japanese</option>
                    <option value="korean">korean</option>
                  </select>
                  <button id="transcribe-submit" class="secondary">Transcribe</button>
                  <div class="status" id="transcribe-status"></div>
                  <label>Transcript</label>
                  <pre id="transcribe-output"></pre>
                </section>

                <section class="card">
                  <h2>Audio File -> Full Roundtrip</h2>
                  <label for="roundtrip-file">Audio File</label>
                  <input id="roundtrip-file" type="file" accept="audio/*">
                  <label for="roundtrip-voice">Voice</label>
                  <select id="roundtrip-voice"></select>
                  <button id="roundtrip-submit">Run Roundtrip</button>
                  <div class="status" id="roundtrip-status"></div>
                  <label>Transcript</label>
                  <pre id="roundtrip-transcript"></pre>
                  <label>Reply</label>
                  <pre id="roundtrip-output"></pre>
                  <audio id="roundtrip-audio" controls></audio>
                </section>
              </div>
            </main>
            <script>
              const voices = {voices_json};
              const voiceSelects = [
                document.getElementById("text-voice"),
                document.getElementById("roundtrip-voice"),
              ];
              for (const select of voiceSelects) {{
                for (const voice of voices) {{
                  const option = document.createElement("option");
                  option.value = voice;
                  option.textContent = voice;
                  select.appendChild(option);
                }}
              }}

              function setAudioSource(el, base64) {{
                el.src = base64 ? `data:audio/wav;base64,${{base64}}` : "";
              }}

              async function postJson(url, body) {{
                const response = await fetch(url, {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/json" }},
                  body: JSON.stringify(body),
                }});
                if (!response.ok) {{
                  throw new Error(await response.text());
                }}
                return response.json();
              }}

              document.getElementById("text-submit").onclick = async () => {{
                const status = document.getElementById("text-status");
                status.textContent = "Generating...";
                try {{
                  const data = await postJson("/api/playground/text-roundtrip", {{
                    text: document.getElementById("text-input").value,
                    voice: document.getElementById("text-voice").value,
                  }});
                  document.getElementById("text-output").textContent = data.reply_text;
                  setAudioSource(document.getElementById("text-audio"), data.audio_base64);
                  status.textContent = "Done";
                }} catch (err) {{
                  status.textContent = String(err);
                }}
              }};

              document.getElementById("transcribe-submit").onclick = async () => {{
                const fileInput = document.getElementById("transcribe-file");
                const status = document.getElementById("transcribe-status");
                if (!fileInput.files.length) {{
                  status.textContent = "Choose an audio file first.";
                  return;
                }}
                status.textContent = "Transcribing...";
                try {{
                  const form = new FormData();
                  form.append("file", fileInput.files[0]);
                  form.append("language", document.getElementById("transcribe-language").value);
                  const response = await fetch("/api/playground/transcribe", {{ method: "POST", body: form }});
                  if (!response.ok) throw new Error(await response.text());
                  const data = await response.json();
                  document.getElementById("transcribe-output").textContent = data.transcript;
                  status.textContent = "Done";
                }} catch (err) {{
                  status.textContent = String(err);
                }}
              }};

              document.getElementById("roundtrip-submit").onclick = async () => {{
                const fileInput = document.getElementById("roundtrip-file");
                const status = document.getElementById("roundtrip-status");
                if (!fileInput.files.length) {{
                  status.textContent = "Choose an audio file first.";
                  return;
                }}
                status.textContent = "Running full roundtrip...";
                try {{
                  const form = new FormData();
                  form.append("file", fileInput.files[0]);
                  form.append("voice", document.getElementById("roundtrip-voice").value);
                  const response = await fetch("/api/playground/audio-roundtrip", {{ method: "POST", body: form }});
                  if (!response.ok) throw new Error(await response.text());
                  const data = await response.json();
                  document.getElementById("roundtrip-transcript").textContent = data.transcript;
                  document.getElementById("roundtrip-output").textContent = data.reply_text;
                  setAudioSource(document.getElementById("roundtrip-audio"), data.audio_base64);
                  status.textContent = "Done";
                }} catch (err) {{
                  status.textContent = String(err);
                }}
              }};
            </script>
          </body>
        </html>
        """
    )


@app.post("/api/playground/text-roundtrip")
async def playground_text_roundtrip(payload: dict):
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"reply_text": "", "audio_base64": ""}

    voice = str(payload.get("voice", "")).strip() or configure.available_voices[0]
    response = await router.acompletion(
        model=BASIC_LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a concise and helpful voice assistant."},
            {"role": "user", "content": text},
        ],
        stream=False,
    )
    reply_text = response.choices[0].message.content or ""
    speech = await router.aspeech(
        model=TEXT_TO_SPEECH_MODEL_NAME,
        input=normalize_text(reply_text),
        voice=voice,
        response_format="wav",
        stream=False,
    )
    return {
        "reply_text": reply_text,
        "audio_base64": base64.b64encode(speech.content).decode("utf-8"),
    }


@app.post("/api/playground/transcribe")
async def playground_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default=""),
):
    audio_bytes = await file.read()
    response = await router.atranscription(
        model=AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
        file=audio_bytes,
        language=language or None,
        stream=False,
    )
    return {"transcript": response.text.strip() if response.text else ""}


@app.post("/api/playground/audio-roundtrip")
async def playground_audio_roundtrip(
    file: UploadFile = File(...),
    voice: str = Form(default=""),
):
    selected_voice = voice.strip() or configure.available_voices[0]
    audio_bytes = await file.read()
    transcription = await router.atranscription(
        model=AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
        file=audio_bytes,
        stream=False,
    )
    transcript = transcription.text.strip() if transcription.text else ""
    response = await router.acompletion(
        model=BASIC_LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a concise and helpful voice assistant."},
            {"role": "user", "content": transcript},
        ],
        stream=False,
    )
    reply_text = response.choices[0].message.content or ""
    speech = await router.aspeech(
        model=TEXT_TO_SPEECH_MODEL_NAME,
        input=normalize_text(reply_text),
        voice=selected_voice,
        response_format="wav",
        stream=False,
    )
    return {
        "transcript": transcript,
        "reply_text": reply_text,
        "audio_base64": base64.b64encode(speech.content).decode("utf-8"),
    }


if __name__ == "__main__":
    import litellm

    litellm.modify_params = True

    current_dir = os.path.dirname(os.path.abspath(__file__))
    default_config_path = f"{current_dir}/config.yaml"

    parser = argparse.ArgumentParser(description="Run the Voice Assistant server")
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=default_config_path,
        help=f"Path to the proxy configuration file (default: {default_config_path}).",
    )
    parser.add_argument(
        "-m",
        "--mode",
        default="fastapi",
        choices=["ui", "fastapi"],
        help="Set operation mode. Choices:\n"
        "  ui      : Launch a built-in UI for easily testing and sharing your stream. Built with Gradio.\n"
        "  fastapi : Mount the stream on a FastAPI app.\n",
    )

    args = parser.parse_args()

    bootstrap_runtime(config_path=args.config)

    logger.info("Starting Voice Assistant server")
    if args.mode == "ui":
        stream = Stream(
            modality="audio",
            mode="send-receive",
            handler=ReplyOnPause(),
            additional_outputs_handler=lambda a, b: b,
            rtc_configuration=configure.server_rtc_configuration,
            server_rtc_configuration=configure.server_rtc_configuration,
            concurrency_limit=5,
            time_limit=None,
            ui_args={"title": "Real-time, customizable AI voice"},
        )
        stream.ui.launch(
            server_name=configure.host,
            server_port=configure.port,
            allowed_paths=["/workspace/voicebot"],
        )
    elif args.mode == "fastapi":
        mount_stream_if_needed()
        uvicorn.run(app=app, host=configure.host, port=configure.port)
