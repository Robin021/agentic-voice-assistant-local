import re

VERSION = "1.0.0"

BASIC_LLM_MODEL_NAME = "basic-llm"
CONTEXT_RELEVANCE_MODEL_NAME = "context-relevance"
AUTOMATIC_SPEECH_RECOGNITION_MODEL_NAME = "automatic-speech-recognition"
TEXT_TO_SPEECH_MODEL_NAME = "text-to-speech"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_VERBOSE = False
DEFAULT_TABLE_NAME = "VoiceAssistant"
DEFAULT_AWS_REGION_NAME = "us-east-1"
DEFAULT_AUDIO_INPUT_SAMPLE_RATE = 16000
DEFAULT_AUDIO_OUTPUT_SAMPLE_RATE = 16000
DEFAULT_TTS_OUTPUT_SAMPLE_RATE = 16000
DEFAULT_EXPECTED_AUDIO_LAYOUT = "mono"

DEFAULT_GREETING_ENABLED = True

DEFAULT_WAITING_MESSAGE_POOL = dict(
    chinese=[
        "正在为您分析问题，请稍候...",
        "系统正在处理您的请求，这可能需要一点时间",
        "搜索最佳解决方案中，请耐心等待",
        "正在查阅知识库，马上就好...",
        "我们的AI专家正在为您定制解决方案",
        "正在多维度分析您的问题，确保回答准确",
        "为确保回答质量，正在进行深度校验",
        "让我好好想想这个问题...",
        "正在调取大脑中的知识库，马上回来",
        "这个问题很有深度，我需要多花点时间思考",
        "别着急，我正在为您准备最完善的答案",
        "正在召唤智慧小精灵为您解答...",
        "知识咖啡正在冲泡中，请稍等片刻",
        "脑细胞全力运转中",
        "正在为您打开智慧宝箱...",
    ],
    english=[
        "We're preparing your response. This may take a moment.",
        "Analyzing your request, please wait...",
        "Processing your query - this may take a moment.",
        "Searching for the optimal solution...",
        "Let me think deeply about this one...",
        "Consulting my knowledge banks—be right back!",
        "This is a profound question; I need extra time to refine the answer.",
        "Summoning the wisdom fairies to assist you...",
        "Brewing a fresh cup of knowledge—just a sec!",
        "Brain cells at full throttle! ",
        "Don’t worry, I’m crafting the most thorough response for you.",
        "Quality check in progress to ensure accuracy.",
    ],
    japanese=[
        "お問い合わせを分析中です。少々お待ちください...",
        "最適な解決策を検索中です。",
        "深く検証を行っていますので、もうしばらくお待ちを。",
        "知識の扉を開いています...",
        "脳内データベースを全力スキャン中！",
        "この質問、じっくり考えさせてくださいね。",
        "知恵の玉手箱を開封中...",
        "回答を丁寧に仕上げています、あと少し！",
        "AI茶を淹れています（急がずに待ってね）",
        "頭のなかでパズルを組み立て中！",
        "ロボット魂、フルパワーで考え中！",
    ],
    korean=[
        "요청을 분석 중입니다. 잠시만 기다려주세요...",
        "정확한 답변을 위해 심층 검증 중이에요.",
        "최적의 해결책을 찾고 있어요!",
        "지식 창고를 뒤적이는 중...",
        "두뇌 풀가동! 조금만 기다려주세요~",
        "이 질문, 깊이 고민해 볼게요.",
        "지혜의 요정들을 소환 중...",
        "핵심 답변을 추출하는 중 (커피 추출처럼 섬세하게)",
        "AI 뇌세포가 열일하는 중!",
        "완벽한 답변을 위해 꼼꼼히 준비하고 있어요.",
        "조금만 기다리시면 특별한 답변 드릴게요!",
    ],
)
DEFAULT_AUDIO_PROMPT_DELAY_THRESHOLD = 3
DEFAULT_WAITING_AUDIO_CUES = [
    "assets/wait_melody_119s.wav",
    "assets/wait_melody_138.wav",
    "assets/wait_melody_169s.wav",
]

LEXICAL_PATTERN = re.compile(r"[^\s\W_]", re.UNICODE)
