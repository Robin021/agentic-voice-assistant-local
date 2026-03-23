import uuid
import httpx
import numpy as np
import pandas as pd
import gradio as gr
import secrets
import soundfile as sf
from io import BytesIO
from gradio import Blocks
from typing import Dict, Any, Literal, cast
from fastapi import FastAPI, WebSocket
from fastrtc import Stream as _Stream, UIArgs
from fastrtc.webrtc import WebRTC
from fastrtc.tracks import StreamHandlerImpl
from fastrtc.websocket import WebSocketHandler
from litellm.types.router import Deployment
from pynamodb.exceptions import DoesNotExist

from config import configure
from schemas import Scenarios, ScenarioItem, User
from constants import AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME, TEXT_TO_SPEECH_MODEL_NAME
from .router import router
from .websocket import SignalWebSocketHandler, MediaWebSocketHandler


class Stream(_Stream):
    def transcription(self, audio_path: str, language: str | None = None) -> str:
        with open(audio_path, "rb") as f:
            response = router.transcription(
                model=AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME,
                file=f.read(),
                language=language,
                stream=False,
            )
        return response.text.strip() if response.text else ""

    def speech(
        self,
        input,
        reference_file,
        reference_text,
        voice,
        instructions,
        sample_rate: int = 44100,
        speed: float = 1.0,
    ) -> tuple[int, np.ndarray]:
        deployment_on_router: Deployment | None = (
            router.get_deployment_by_model_group_name(
                model_group_name=TEXT_TO_SPEECH_MODEL_NAME
            )
        )
        if deployment_on_router is None:
            raise ValueError(
                f"Deployment not found for model group name: {TEXT_TO_SPEECH_MODEL_NAME}"
            )

        api_base = deployment_on_router.litellm_params.api_base or ""
        if api_base.endswith("/"):
            api_base = api_base.rstrip("/")
        api_base_url = f"{api_base}/audio/inference"

        params: Dict[str, Any] = dict(
            url=api_base_url,
            data=dict(
                input=input,
                sample_rate=sample_rate,
                speed=speed,
                response_format="wav",
            ),
        )
        if voice:
            params["data"]["voice"] = voice
        if instructions:
            params["data"]["instructions"] = instructions
        if reference_text:
            params["data"]["reference_text"] = reference_text
        if reference_file:
            with open(reference_file, "rb") as f:
                params["files"] = dict(reference_file=("audio.wav", f.read()))

        with httpx.Client(timeout=60) as client:
            response = client.post(**params)
            response.raise_for_status()

            audio = response.content
            with BytesIO(audio) as audio_file:
                _audio, sr = sf.read(audio_file)

            return sr, _audio

    def _generate_default_ui(
        self,
        ui_args: UIArgs | None = None,
    ) -> Blocks:
        """
        Generate the default Gradio UI based on mode, modality, and arguments.

        Constructs a `gradio.Blocks` interface with the appropriate WebRTC component
        and any specified additional input/output components.

        Args:
            ui_args: Optional dictionary containing UI customization arguments
                     (title, subtitle, icon, etc.).

        Returns:
            A `gradio.Blocks` instance representing the generated UI.

        Raises:
            ValueError: If `additional_outputs` are provided without
                        `additional_outputs_handler`.
            ValueError: If the combination of `mode` and `modality` is invalid
                        or not supported for UI generation.
        """
        ui_args = ui_args or {}

        with gr.Blocks() as demo:
            with gr.Tab("SPEECH-TO-SPEECH"):
                if not ui_args.get("hide_title"):
                    gr.HTML(
                        f"""
                    <h1 style='text-align: center'>
                    {ui_args.get("title")}
                    </h1>
                    """
                    )
                    if ui_args.get("subtitle"):
                        gr.Markdown(
                            f"""
                    <div style='text-align: center'>
                        {ui_args.get("subtitle")}
                    </div>
                    """
                        )

                sts_conversation_id = gr.Textbox(visible=False)
                sts_username = gr.Textbox(visible=False)
                sts_formatted_scenarios = gr.Textbox(visible=False)

                demo.load(
                    fn=lambda: str(uuid.uuid4()),
                    inputs=[],
                    outputs=[sts_conversation_id],
                )

                with gr.Row():
                    sts_image = WebRTC(
                        label="Stream",
                        rtc_configuration=self.rtc_configuration,
                        track_constraints=self.track_constraints,
                        mode="send-receive",
                        modality="audio",
                        icon=ui_args.get("icon"),
                        icon_button_color=ui_args.get("icon_button_color"),
                        pulse_color=ui_args.get("pulse_color"),
                        icon_radius=ui_args.get("icon_radius"),
                    )
                    self.webrtc_component = sts_image

                with gr.Group(visible=True) as sts_select_group:
                    with gr.Row():
                        with gr.Column():
                            sts_voice = gr.Radio(
                                choices=configure.available_voices,
                                value=secrets.choice(configure.available_voices),
                                label="Voice",
                                interactive=True,
                                info="To begin your conversation, select a voice",
                            )
                            sts_instructions = gr.Textbox(
                                label="Instructions Text",
                                lines=1,
                                placeholder="Control the voice of your generated audio with additional instructions. ",
                            )
                            sts_language = gr.Dropdown(
                                choices=["chinese", "english", "japanese", "korean"],
                                value="chinese",
                                label="Language",
                            )
                            sts_noise_suppression_enabled = gr.Checkbox(
                                value=False,
                                label="Noise Suppression Enabled",
                                interactive=True,
                            )
                            sts_allow_interruption = gr.Checkbox(
                                value=True,
                                label="Allow Interruption",
                                interactive=True,
                            )
                            sts_display_chatbot = gr.Checkbox(
                                value=True,
                                label="Display Chat",
                                interactive=True,
                            )
                            sts_scenarios = gr.Dropdown(
                                interactive=True,
                                label="Scenarios",
                            )

                with gr.Group(visible=False) as sts_conversation_group:
                    with gr.Row():
                        sts_chatbot = gr.Chatbot(
                            type="messages",
                            autoscroll=True,
                        )

            def sts_update_ui(
                operation: Literal["enter", "quit"], display_chatbot: bool
            ):
                if operation == "enter":
                    return [
                        gr.update(visible=False),
                        gr.update(visible=display_chatbot),
                    ]
                elif operation == "quit":
                    return [
                        gr.update(visible=True),
                        gr.update(visible=False),
                    ]

            def format_scenarios(username, voice, scenarios):
                return scenarios.format(voice=voice, username=username)

            sts_voice.change(
                fn=format_scenarios,
                inputs=[sts_username, sts_voice, sts_scenarios],
                outputs=[sts_formatted_scenarios],
            )

            sts_scenarios.change(
                fn=format_scenarios,
                inputs=[sts_username, sts_voice, sts_scenarios],
                outputs=[sts_formatted_scenarios],
            )

            sts_image.stream(
                fn=self.event_handler,
                inputs=[
                    sts_image,
                    sts_formatted_scenarios,
                    sts_conversation_id,
                    sts_voice,
                    sts_instructions,
                    sts_language,
                    sts_allow_interruption,
                    sts_noise_suppression_enabled,
                ],
                outputs=[sts_image],
                time_limit=self.time_limit,
                concurrency_limit=self.concurrency_limit,  # type: ignore
                send_input_on=ui_args.get("send_input_on", "submit"),
            )
            assert self.additional_outputs_handler

            sts_image.on_additional_outputs(
                fn=self.additional_outputs_handler,
                inputs=[sts_chatbot],
                outputs=[sts_chatbot],
                concurrency_limit=self.concurrency_limit_gradio,  # type: ignore
            )

            sts_image.start_recording(
                fn=sts_update_ui,
                inputs=[gr.State("enter"), sts_display_chatbot],
                outputs=[sts_select_group, sts_conversation_group],
            )
            sts_image.stop_recording(
                fn=sts_update_ui,
                inputs=[gr.State("quit"), sts_display_chatbot],
                outputs=[sts_select_group, sts_conversation_group],
            )

            with gr.Tab("SPEECH-TO-TEXT"):
                gr.HTML(
                    """<div>
    <h2 style="font-size: 22px;margin-left: 0px;">Voice Understanding Model: SenseVoice-Small</h2>
    <p style="font-size: 18px;margin-left: 20px;">SenseVoice-Small is an encoder-only speech foundation model designed for rapid voice understanding. It encompasses a variety of features including automatic speech recognition (ASR), spoken language identification (LID), speech emotion recognition (SER), and acoustic event detection (AED). SenseVoice-Small supports multilingual recognition for Chinese, English, Cantonese, Japanese, and Korean. Additionally, it offers exceptionally low inference latency, performing 7 times faster than Whisper-small and 17 times faster than Whisper-large.</p>
    <h2 style="font-size: 22px;margin-left: 0px;">Usage</h2> <p style="font-size: 18px;margin-left: 20px;">Upload an audio file or input through a microphone, then select the task and language. the audio is transcribed into corresponding text along with associated emotions (😊 happy, 😡 angry/exicting, 😔 sad) and types of sound events (😀 laughter, 🎼 music, 👏 applause, 🤧 cough&sneeze, 😭 cry). The event labels are placed in the front of the text and the emotion are in the back of the text.</p>
</div>"""
                )
                with gr.Row(equal_height=True):
                    with gr.Column():
                        stt_audio_inputs = gr.Audio(
                            sources=["upload", "microphone"],
                            label="Upload audio or use the microphone",
                            type="filepath",
                        )

                        stt_language_inputs = gr.Dropdown(
                            choices=[
                                "auto",
                                "zh",
                                "en",
                                "yue",
                                "ja",
                                "ko",
                            ],
                            value="auto",
                            label="Language",
                        )

                    if examples := configure.ui.get(
                        "automatic_speech_recognition", {}
                    ).get("examples", []):
                        gr.Examples(
                            examples=examples,
                            inputs=[stt_audio_inputs, stt_language_inputs],
                            examples_per_page=20,
                        )

                with gr.Row():
                    stt_start_button = gr.Button("Start")

                with gr.Row():
                    stt_text_outputs = gr.Textbox(label="Transcriptions")

                stt_start_button.click(
                    self.transcription,
                    inputs=[
                        stt_audio_inputs,
                        stt_language_inputs,
                    ],
                    outputs=stt_text_outputs,
                )
            with gr.Tab("TEXT-TO-SPEECH"):
                gr.HTML(
                    """<div>
    <h2 style="font-size: 22px;margin-left: 0px;">Text to Speech Model: CosyVoice-300M (v3.0)</h2>
    <p style="font-size: 18px;margin-left: 20px;">CosyVoice 3.0 is an ultra-low latency multilingual speech synthesis model that delivers human-like naturalness, reduces pronunciation errors, and supports bidirectional streaming synthesis with just 150ms first-packet latency while maintaining high prosody, stability, and granular emotional control.</p>
    <h2 style="font-size: 22px;margin-left: 0px;">Usage</h2>
        <ul style="font-size: 18px;margin-left: 20px;">
            <li><strong>Zero-shot In-context Generation:</strong> Provide an audio sample and its transcriptions; the model clones the voice and generates new audio from Script.</li>
            <li><strong>Instructed Voice Generation:</strong> Provide an audio sample and an instruction (e.g., "神秘", "模仿机器人风格"); the model clones the voice and applies fine-grained control before synthesis.</li>
            <li><strong>Speaker:</strong> Select a predefined voice profile and optionally add an instruction; the model generates speech with the chosen voice while following the specified adjustments.</li>
        </ul>
    </div>"""
                )
                with gr.Row(equal_height=True):
                    with gr.Column(scale=6):
                        tts_inference_mode = gr.Radio(
                            choices=[
                                "Zero-shot In-context Generation",
                                "Instructed Voice Generation",
                                "Speaker",
                            ],
                            value="Zero-shot In-context Generation",
                            label="Inference Mode",
                            info="",
                        )
                    with gr.Column(scale=1):
                        tts_auto_transcription = gr.Radio(
                            choices=[
                                "On",
                                "Off",
                            ],
                            value="On",
                            label="Auto Transcription",
                            info="",
                        )

                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            tts_script = gr.Textbox(
                                label="Script",
                                info="To help shape the voice we generate, input something distinctive this AI voice would say",
                                lines=1,
                                value="在这宁静的夜晚，我们可以沿着小路慢慢走，感受微风拂面的轻柔，与自然融为一体。",
                            )
                            tts_reference_file = gr.Audio(
                                sources=["upload", "microphone"],
                                label="Upload audio or use the microphone",
                                type="filepath",
                            )
                            tts_reference_text = gr.Textbox(
                                label="Reference Text",
                                lines=1,
                                placeholder="Please input the text content from the reference audio. The system will automatically recognize it after upload if you enable auto transcriptin. Manual adjustments can be made if necessary.",
                            )
                            tts_voice = gr.Radio(
                                choices=configure.available_voices,
                                visible=False,
                                interactive=True,
                                label="Select Voice",
                                info="The voice to use when generating the audio.",
                            )
                            tts_instructions = gr.Textbox(
                                label="Instructions Text",
                                visible=False,
                                lines=1,
                                placeholder="Control the voice of your generated audio with additional instructions. ",
                            )

                tts_examples_by_inference_mode = {}
                for x in configure.ui.get("text_to_speech", {}).get("examples", []):
                    mode, dataset = x[0], x[1:]
                    if mode not in tts_examples_by_inference_mode.keys():
                        tts_examples_by_inference_mode[mode] = [dataset]
                    else:
                        tts_examples_by_inference_mode[mode].append(dataset)

                def tts_get_examples_dataset(mode):
                    data = tts_examples_by_inference_mode.get(mode, [])

                    results = []
                    if mode == "Zero-shot In-context Generation":
                        for x in data:
                            results.append([x[0], x[1], x[2], x[3]])
                    elif mode == "Instructed Voice Generation":
                        for x in data:
                            results.append([x[0], x[1], x[3]])
                    elif mode == "Speaker":
                        for x in data:
                            results.append([x[0], x[3]])
                    return results

                def tts_get_examples_headers(mode):
                    if mode == "Zero-shot In-context Generation":
                        return [
                            "Script",
                            "Reference File",
                            "Reference Text",
                            "Instructions Text",
                        ]
                    elif mode == "Instructed Voice Generation":
                        return ["Script", "Reference File", "Instructions Text"]
                    elif mode == "Speaker":
                        return ["Script", "Instructions Text"]

                with gr.Row():
                    with gr.Column():
                        tts_examples_input = gr.Dataset(
                            samples=tts_get_examples_dataset(
                                "Zero-shot In-context Generation"
                            ),
                            components=[
                                tts_script,
                                tts_reference_file,
                                tts_reference_text,
                                tts_instructions,
                            ],
                            label="Examples",
                            samples_per_page=10,
                            headers=tts_get_examples_headers(
                                "Zero-shot In-context Generation"
                            ),
                        )

                def tts_transcription_wrapper(audio_path, auto_transcription):
                    if auto_transcription == "Off":
                        return gr.update()
                    return self.transcription(audio_path=audio_path)

                def tts_update_ui(mode):
                    if mode == "Zero-shot In-context Generation":
                        return [
                            gr.Audio(visible=True, interactive=True),
                            gr.Textbox(visible=True, interactive=True),
                            gr.Textbox(visible=False, interactive=True, value=None),
                            gr.Radio(visible=False, interactive=False, value=None),
                            gr.Dataset(
                                visible=True,
                                samples=tts_get_examples_dataset(mode),
                                headers=tts_get_examples_headers(mode),
                            ),
                        ]
                    elif mode == "Instructed Voice Generation":
                        return [
                            gr.Audio(visible=True, interactive=True),
                            gr.Textbox(visible=False, interactive=False, value=None),
                            gr.Textbox(visible=True, interactive=True),
                            gr.Radio(visible=False, interactive=False, value=None),
                            gr.Dataset(
                                visible=True,
                                samples=tts_get_examples_dataset(mode),
                                headers=tts_get_examples_headers(mode),
                            ),
                        ]
                    elif mode == "Speaker":
                        return [
                            gr.Audio(visible=False, interactive=False, value=None),
                            gr.Textbox(visible=False, interactive=False, value=None),
                            gr.Textbox(visible=True, interactive=True),
                            gr.Radio(
                                visible=True,
                                interactive=True,
                                value=configure.available_voices[0],
                            ),
                            gr.Dataset(
                                visible=True,
                                samples=tts_get_examples_dataset(mode),
                                headers=tts_get_examples_headers(mode),
                            ),
                        ]

                def tts_click_dataset(mode, dataset):
                    if mode == "Zero-shot In-context Generation":
                        return ("Off", dataset[0], dataset[1], dataset[2], dataset[3])
                    elif mode == "Instructed Voice Generation":
                        return ("Off", dataset[0], dataset[1], gr.update(), dataset[2])
                    elif mode == "Speaker":
                        return (
                            "Off",
                            dataset[0],
                            gr.update(),
                            gr.update(),
                            dataset[1],
                        )

                tts_inference_mode.change(
                    fn=tts_update_ui,
                    inputs=tts_inference_mode,
                    outputs=[
                        tts_reference_file,
                        tts_reference_text,
                        tts_instructions,
                        tts_voice,
                        tts_examples_input,
                    ],
                )

                tts_reference_file.change(
                    fn=tts_transcription_wrapper,
                    inputs=[tts_reference_file, tts_auto_transcription],
                    outputs=tts_reference_text,
                )

                tts_examples_input.click(
                    fn=tts_click_dataset,
                    inputs=[tts_inference_mode, tts_examples_input],
                    outputs=[
                        tts_auto_transcription,
                        tts_script,
                        tts_reference_file,
                        tts_reference_text,
                        tts_instructions,
                    ],
                )

                tts_generate_button = gr.Button("GENERATE")

                tts_audio_output = gr.Audio(autoplay=True, streaming=True)

                tts_generate_button.click(
                    self.speech,
                    inputs=[
                        tts_script,
                        tts_reference_file,
                        tts_reference_text,
                        tts_voice,
                        tts_instructions,
                    ],
                    outputs=[tts_audio_output],
                )

            # with gr.Tab("CHATBOT"):
            #     chatbot = gr.Chatbot()
            #     choice = gr.Radio(choices=["text", "voice"], value="text", label="Mode")

            #     text_input = gr.Textbox(visible=True)
            #     audio_input = gr.Audio(visible=False)

            #     def toggle_audio_mode(choice):
            #         return gr.Audio(visible=choice == "voice")

            #     def respond(message, chat_history):
            #         if isinstance(message, tuple):
            #             sr, data = message
            #             response = f"识别到 {len(data) / sr:.2f} 秒语音"
            #         else:
            #             response = f"回复文本: {message}"
            #         chat_history.append((message, response))
            #         return chat_history

            #     choice.change(toggle_audio_mode, choice, [audio_input, text_input])

            #     msg = gr.State()
            #     submit_btn = gr.Button("Submit")
            # submit_btn.click(respond, [gr.Textbox() | gr.Audio(), chatbot], chatbot)
            with gr.Tab("SETTINGS"):

                def load_user():
                    try:
                        item = User.get(hash_key="USER", range_key="USER")
                        return item.username, item.gender, item.username
                    except Exception:
                        return ["Demo", "Male", "Demo"]

                def load_scenarios():
                    try:
                        item = Scenarios.get(hash_key="SCENARIO", range_key="SCENARIO")
                        value = []
                        choices = []
                        for scenario in item.scenarios:
                            value.append(
                                [
                                    scenario.name,
                                    scenario.prompt,
                                    scenario.description,
                                    scenario.createdAt,
                                    scenario.updatedAt,
                                ]
                            )
                            choices.append([scenario.name, scenario.prompt])
                        return gr.update(value=value), gr.update(
                            choices=choices, value=choices[0][1] if choices else None
                        )
                    except Exception:
                        return [], None

                def save_settings(username, gender, scenarios):
                    df_scenarios = pd.DataFrame(
                        scenarios,
                        columns=[
                            "Name",
                            "Prompts",
                            "Description",
                        ],
                    )
                    choices_scenarios = [
                        (item["Name"], item["Prompts"])
                        for _, item in df_scenarios.iterrows()
                    ]
                    try:
                        item_scenarios = Scenarios.get(
                            hash_key="SCENARIO", range_key="SCENARIO"
                        )
                        item_scenarios.update(
                            actions=[
                                Scenarios.scenarios.set(
                                    [
                                        ScenarioItem(
                                            name=x["Name"],
                                            prompt=x["Prompts"],
                                            description=x["Description"],
                                        )
                                        for _, x in df_scenarios.iterrows()
                                    ]
                                )
                            ]
                        )
                        item_scenarios.save()
                    except DoesNotExist as e:
                        Scenarios(
                            hash_key="SCENARIO",
                            range_key="SCENARIO",
                            scenarios=[
                                ScenarioItem(
                                    name=x["Name"],
                                    prompt=x["Prompts"],
                                    description=x["Description"],
                                )
                                for _, x in df_scenarios.iterrows()
                            ],
                        ).save()

                    try:
                        item_user = User.get(hash_key="USER", range_key="USER")
                        item_user.update(
                            actions=[
                                User.username.set(username),
                                User.gender.set(gender),
                            ]
                        )
                        item_user.save()
                    except DoesNotExist as e:
                        User(
                            hash_key="USER",
                            range_key="USER",
                            username=username,
                            gender=gender,
                        ).save()

                    return [
                        gr.update(value=username),
                        gr.update(value=gender),
                        gr.update(value=df_scenarios.values.tolist()),
                        gr.update(value=username),
                        gr.update(
                            choices=choices_scenarios,
                            value=(
                                choices_scenarios[0][1] if choices_scenarios else None
                            ),
                        ),
                    ]

                gr.Markdown("# User")
                settings_username = gr.Textbox(label="Username")
                settings_gender = gr.Radio(
                    ["Male", "Female"], label="Gender", value="Male"
                )
                demo.load(
                    fn=load_user,
                    outputs=[settings_username, settings_gender, sts_username],
                )

                gr.Markdown("# Scenarios")
                settings_scenarios = gr.DataFrame(
                    headers=[
                        "Name",
                        "Prompts",
                        "Description",
                    ],
                    datatype=["str", "str", "str"],
                    interactive=True,
                    row_count=(1, "dynamic"),
                    col_count=(3, "fixed"),
                    column_widths=["10%", "70%", "20%"],
                )

                save_btn = gr.Button("Save Data")

                demo.load(
                    fn=load_scenarios, outputs=[settings_scenarios, sts_scenarios]
                )

                save_btn.click(
                    fn=save_settings,
                    inputs=[settings_username, settings_gender, settings_scenarios],
                    outputs=[
                        settings_username,
                        settings_gender,
                        settings_scenarios,
                        sts_username,
                        sts_scenarios,
                    ],
                )

        return demo

    def mount(self, app: FastAPI, path: str = ""):
        from fastapi import APIRouter

        router = APIRouter(prefix=path)
        router.post("/webrtc/offer")(self.offer)
        # router.websocket("/telephone/handler")(self.telephone_handler)
        # router.post("/telephone/incoming")(self.handle_incoming_call)
        router.websocket("/websocket/offer")(self.websocket_offer)
        router.websocket("/telephone/websocket/signal")(self.telephone_websocket_signal)
        router.websocket("/telephone/websocket/media")(self.telephone_websocket_media)
        lifespan = self._inject_startup_message(app.router.lifespan_context)
        app.router.lifespan_context = lifespan
        app.include_router(router)

    async def telephone_websocket_signal(self, websocket: WebSocket):
        handler = cast(StreamHandlerImpl, self.event_handler.copy())  # type: ignore
        handler.phone_mode = False

        async def set_handler(s: str, a: WebSocketHandler):
            if len(self.connections) >= self.concurrency_limit:  # type: ignore
                await cast(WebSocket, a.websocket).send_json(
                    {
                        "status": "failed",
                        "meta": {
                            "error": "concurrency_limit_reached",
                            "limit": self.concurrency_limit,
                        },
                    }
                )
                await websocket.close()
                return

            self.connections[s] = [a]  # type: ignore

        def clean_up(s):
            self.clean_up(s)

        ws = SignalWebSocketHandler(
            handler, set_handler, clean_up, lambda s: self.set_additional_outputs(s)
        )
        await ws.handle_websocket(websocket)

    async def telephone_websocket_media(self, websocket: WebSocket):
        handler = cast(StreamHandlerImpl, self.event_handler.copy())  # type: ignore
        handler.phone_mode = True

        async def set_handler(s: str, a: WebSocketHandler):
            if len(self.connections) >= self.concurrency_limit:  # type: ignore
                await cast(WebSocket, a.websocket).send_json(
                    {
                        "status": "failed",
                        "meta": {
                            "error": "concurrency_limit_reached",
                            "limit": self.concurrency_limit,
                        },
                    }
                )
                await websocket.close()
                return

            self.connections[s] = [a]  # type: ignore

        def clean_up(s):
            self.clean_up(s)

        ws = MediaWebSocketHandler(
            handler, set_handler, clean_up, lambda s: self.set_additional_outputs(s)
        )
        await ws.handle_websocket(websocket)
