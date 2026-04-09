import os
import uvicorn
import argparse
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from litellm.types.router import Deployment

from llms import load_custom_llm
from logger import logger
from config import configure
from server.stream import Stream
from server.router import router
from server.reply_on_pause import ReplyOnPause


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
