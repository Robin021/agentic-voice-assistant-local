import os
import json
import uvicorn
import argparse
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from litellm.types.router import Deployment
from pydantic import BaseModel

from llms import load_custom_llm
from logger import logger
from config import configure
from server.stream import Stream
from server.router import router
from server.reply_on_pause import ReplyOnPause
from prompts.template import get_prompt_template


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
            <p><strong>Note:</strong> the playground uses a live microphone over WebRTC. Browser microphone access usually needs <code>https://</code> or <code>localhost</code>.</p>
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
    rtc_configuration_json = json.dumps(
        configure.server_rtc_configuration or {}, ensure_ascii=False
    )
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
                --accent-3: #6c8d2f;
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
              .hero {{
                display: grid;
                grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr);
                gap: 18px;
                margin-bottom: 18px;
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
              textarea, select {{
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
              button.success {{ background: var(--accent-3); }}
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
              .pill {{
                display: inline-block;
                padding: 6px 10px;
                border-radius: 999px;
                background: #f2e8d9;
                color: var(--accent);
                margin: 0 8px 8px 0;
                font-size: .92rem;
              }}
              .controls {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
              }}
              .chat {{
                min-height: 320px;
                max-height: 420px;
                overflow: auto;
                display: flex;
                flex-direction: column;
                gap: 10px;
              }}
              .bubble {{
                padding: 12px 14px;
                border-radius: 16px;
                border: 1px solid var(--line);
                background: #fff;
              }}
              .bubble.user {{
                background: #f8efe4;
              }}
              .bubble.assistant {{
                background: #f4f7fa;
              }}
              .mono {{
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: .92rem;
              }}
              @media (max-width: 860px) {{
                .hero {{
                  grid-template-columns: 1fr;
                }}
              }}
            </style>
          </head>
          <body>
            <main>
              <div class="hero">
                <section class="card">
                  <h1>Realtime Voicebot Playground</h1>
                  <p class="lead">This page establishes a live WebRTC session against <code>/webrtc/offer</code> and lets you talk to the assistant in real time.</p>
                  <span class="pill">Live microphone</span>
                  <span class="pill">Realtime TTS playback</span>
                  <span class="pill">Data-channel logs</span>
                  <label for="voice">Voice</label>
                  <select id="voice"></select>
                  <label for="instructions">Voice Instructions</label>
                  <textarea id="instructions" placeholder="Optional style instructions for TTS"></textarea>
                  <label for="language">Language</label>
                  <select id="language">
                    <option value="chinese">chinese</option>
                    <option value="english">english</option>
                    <option value="japanese">japanese</option>
                    <option value="korean">korean</option>
                  </select>
                  <div class="controls">
                    <button id="start" class="success">Start Realtime Session</button>
                    <button id="stop" class="secondary">Stop</button>
                  </div>
                  <div class="status" id="status">Idle</div>
                </section>
                <section class="card">
                  <h2>Session Notes</h2>
                  <p class="lead">Microphone access usually requires <code>https://</code> or <code>localhost</code>. If you are opening a raw public IP over HTTP, the browser may block <code>getUserMedia()</code>.</p>
                  <pre class="mono" id="notes">Open this page over HTTPS for browser microphone permissions.\nIf audio does not connect, verify TURN/STUN reachability.\nThe assistant conversation will appear in the transcript panel.</pre>
                  <audio id="remote-audio" autoplay controls playsinline></audio>
                </section>
              </div>
              <div class="grid">
                <section class="card">
                  <h2>Conversation</h2>
                  <div id="chat" class="chat"></div>
                </section>
                <section class="card">
                  <h2>Realtime Logs</h2>
                  <pre id="log-output" class="mono"></pre>
                </section>
              </div>
            </main>
            <script>
              const rtcConfiguration = {rtc_configuration_json};
              const voices = {voices_json};
              const voiceSelect = document.getElementById("voice");
              for (const voice of voices) {{
                const option = document.createElement("option");
                option.value = voice;
                option.textContent = voice;
                voiceSelect.appendChild(option);
              }}

              let pc = null;
              let localStream = null;
              let dataChannel = null;
              let webrtcId = null;
              let updatesSource = null;
              const statusEl = document.getElementById("status");
              const logEl = document.getElementById("log-output");
              const chatEl = document.getElementById("chat");
              const remoteAudio = document.getElementById("remote-audio");

              function setStatus(text) {{
                statusEl.textContent = text;
              }}

              function log(message) {{
                const line = `[${{new Date().toLocaleTimeString()}}] ${{message}}`;
                logEl.textContent = line + "\\n" + logEl.textContent;
              }}

              function renderChat(messages) {{
                if (!Array.isArray(messages)) return;
                chatEl.innerHTML = "";
                for (const message of messages) {{
                  const bubble = document.createElement("div");
                  bubble.className = `bubble ${{message.role || "assistant"}}`;
                  const role = document.createElement("strong");
                  role.textContent = (message.role || "assistant") + ": ";
                  const text = document.createElement("span");
                  text.textContent = message.content || "";
                  bubble.appendChild(role);
                  bubble.appendChild(text);
                  chatEl.appendChild(bubble);
                }}
                chatEl.scrollTop = chatEl.scrollHeight;
              }}

              function openUpdatesStream() {{
                if (!webrtcId) return;
                if (updatesSource) {{
                  updatesSource.close();
                }}
                updatesSource = new EventSource(`/playground/outputs?webrtc_id=${{encodeURIComponent(webrtcId)}}`);
                updatesSource.onmessage = (event) => {{
                  try {{
                    const payload = JSON.parse(event.data);
                    renderChat(payload.messages || payload);
                  }} catch (error) {{
                    log(`Failed to parse output stream: ${{error}}`);
                  }}
                }};
                updatesSource.onerror = () => {{
                  log("Output stream disconnected");
                }};
              }}

              async function sendInput() {{
                if (!webrtcId) return;
                const response = await fetch("/input_hook", {{
                  method: "POST",
                  headers: {{ "Content-Type": "application/json" }},
                  body: JSON.stringify({{
                    webrtc_id: webrtcId,
                    voice: document.getElementById("voice").value,
                    instructions: document.getElementById("instructions").value,
                    language: document.getElementById("language").value,
                    allow_interruption: true,
                    noise_suppression_enabled: false
                  }}),
                }});
                if (!response.ok) {{
                  throw new Error(await response.text());
                }}
              }}

              function stopSession() {{
                if (updatesSource) {{
                  updatesSource.close();
                  updatesSource = null;
                }}
                if (pc) {{
                  if (pc.getTransceivers) {{
                    pc.getTransceivers().forEach((transceiver) => {{
                      if (transceiver.stop) transceiver.stop();
                    }});
                  }}
                  if (pc.getSenders) {{
                    pc.getSenders().forEach((sender) => {{
                      if (sender.track && sender.track.stop) sender.track.stop();
                    }});
                  }}
                  setTimeout(() => pc.close(), 200);
                }}
                if (localStream) {{
                  localStream.getTracks().forEach((track) => track.stop());
                }}
                pc = null;
                localStream = null;
                dataChannel = null;
                webrtcId = null;
                setStatus("Stopped");
                log("Session stopped");
              }}

              async function startSession() {{
                stopSession();
                setStatus("Requesting microphone...");
                try {{
                  if (!window.isSecureContext) {{
                    throw new Error("Browser microphone access requires HTTPS or localhost.");
                  }}
                  webrtcId = Math.random().toString(36).slice(2);
                  pc = new RTCPeerConnection(rtcConfiguration);
                  localStream = await navigator.mediaDevices.getUserMedia({{
                    audio: {{
                      echoCancellation: true,
                      noiseSuppression: true,
                      autoGainControl: true,
                    }},
                    video: false,
                  }});

                  localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

                  pc.addEventListener("track", (event) => {{
                    if (remoteAudio.srcObject !== event.streams[0]) {{
                      remoteAudio.srcObject = event.streams[0];
                      log("Remote audio track attached");
                    }}
                  }});

                  dataChannel = pc.createDataChannel("text");
                  dataChannel.onopen = async () => {{
                    log("Data channel open");
                    openUpdatesStream();
                    await sendInput();
                  }};
                  dataChannel.onmessage = async (event) => {{
                    let payload = null;
                    try {{
                      payload = JSON.parse(event.data);
                    }} catch (error) {{
                      log(`Raw message: ${{event.data}}`);
                      return;
                    }}
                    if (payload.type === "send_input") {{
                      log("Server requested input sync");
                      await sendInput();
                      return;
                    }}
                    if (payload.type === "fetch_output") {{
                      log("Server reported new conversation output");
                      return;
                    }}
                    log(`${{payload.type}}: ${{typeof payload.data === "string" ? payload.data : JSON.stringify(payload.data)}}`);
                  }};

                  const offer = await pc.createOffer();
                  await pc.setLocalDescription(offer);
                  setStatus("Connecting...");
                  const response = await fetch("/webrtc/offer", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{
                      sdp: offer.sdp,
                      type: offer.type,
                      webrtc_id: webrtcId,
                    }}),
                  }});
                  const answer = await response.json();
                  if (answer.status === "failed") {{
                    throw new Error(JSON.stringify(answer.meta));
                  }}
                  await pc.setRemoteDescription(answer);
                  setStatus("Live");
                  log("WebRTC session established");
                }} catch (err) {{
                  setStatus(String(err));
                  log(`Error: ${{err}}`);
                  stopSession();
                }}
              }}

              document.getElementById("start").onclick = startSession;
              document.getElementById("stop").onclick = stopSession;
            </script>
          </body>
        </html>
        """
    )


class PlaygroundInput(BaseModel):
    webrtc_id: str
    voice: str | None = None
    instructions: str | None = None
    language: str | None = None
    allow_interruption: bool = True
    noise_suppression_enabled: bool = False


@app.post("/input_hook")
async def input_hook(payload: PlaygroundInput):
    app.state.stream.set_input(
        payload.webrtc_id,
        get_prompt_template("assistant"),
        payload.webrtc_id,
        payload.voice or configure.available_voices[0],
        payload.instructions,
        payload.language or configure.language.value,
        payload.allow_interruption,
        payload.noise_suppression_enabled,
    )
    return {"ok": True}


def _serialize_additional_output(output) -> str:
    payload = output
    if hasattr(output, "args"):
        args = list(output.args)
        payload = args[0] if len(args) == 1 else args

    if isinstance(payload, dict):
        normalized = payload
    else:
        normalized = {"messages": payload}

    return json.dumps(normalized, ensure_ascii=False)


@app.get("/playground/outputs")
async def playground_outputs(webrtc_id: str):
    async def event_stream():
        async for output in app.state.stream.output_stream(webrtc_id):
            yield f"data: {_serialize_additional_output(output)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
