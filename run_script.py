from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
import argparse
import speech_recognition as sr
import os
from dotenv import load_dotenv, find_dotenv
from piper.voice import PiperVoice
import sounddevice as sd
import numpy as np
import signal
from characters import get_character

_ = load_dotenv(find_dotenv()) # read local .env file

defaults = {
    "api_key": os.getenv("OPENAI_API_KEY") ,
    "model": "gpt-4o",
    "temperature": 0.7,
    "voice": "com.apple.eloquence.en-US.Grandpa",
    "volume": 1.0,
    "rate": 200,
    "session_id": "abc123",
    "base_url": "https://api.openai.com/v1",
}

parser = argparse.ArgumentParser()
parser.add_argument("--list_voices", action="store_true", help="List the available voices for the text-to-speech engine")
parser.add_argument("--test_voice", action="store_true", help="Test the text-to-speech engine")
parser.add_argument("--ptt", action="store_true", help="Use push-to-talk mode")
parser.add_argument("--character", type=str, help="which character to use", default="gnome")
parser.add_argument("--api_key", type=str, help="The OpenAI API key")
parser.add_argument("--model", type=str, help="The OpenAI model to use", default=defaults["model"])
parser.add_argument("--temperature", type=float, help="The temperature to use for the OpenAI model", default=defaults["temperature"])
parser.add_argument("--voice", type=str, help="The voice to use for the text-to-speech engine", default="en_GB-alan-medium.onnx")
parser.add_argument("--volume", type=float, help="The volume to use for the text-to-speech engine", default=defaults["volume"])
parser.add_argument("--rate", type=int, help="The rate at which the words are spoken for the text-to-speech engine", default=defaults["rate"])
parser.add_argument("--session_id", type=str, help="The session ID to use for the chat history", default=defaults["session_id"])
parser.add_argument("--base_url", type=str, help="The base URL to use for the OpenAI API", default=defaults["base_url"])

args = parser.parse_args()


# Set up the ChatGPT API client
if args.base_url == defaults["base_url"]:
    if "OPENAI_API_KEY" not in os.environ and args.api_key is None:
        raise ValueError("You must set the OPENAI_API_KEY environment variable to use the OpenAI API")
    else:
      api_key = args.api_key or os.getenv("OPENAI_API_KEY")
else:
    if args.api_key is None:
        api_key = 'sk-no_key'
    else:
      api_key = args.api_key
llm_model = args.model
temperature = min(max(args.temperature, 0.0), 1.0)
interface_voice = args.voice
volume = min(max(args.volume, 0.0), 1.0)
rate = min(max(args.rate, 20), 500)
session_id = args.session_id
base_url = args.base_url
ptt = args.ptt

# set up stuff
llm = ChatOpenAI(temperature=temperature, model=llm_model, base_url=base_url, api_key=api_key)
character = get_character(args.character)

# Define Prompts and interaction messages
system_prompt = character.system_prompt
conversation_start = character.greeting
didnt_understand = character.error_message

prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            system_prompt,
        ),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{input}"),
    ]
)

runnable = prompt | llm
store = {}

# Initialize voice creation with piper 
voice_model = args.voice
try:
    voice = PiperVoice.load("models/"+voice_model)
except Exception as e:
    print(f"Error loading voice model: {e}")
    exit(1)


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]


with_message_history = RunnableWithMessageHistory(
    runnable,
    get_session_history,
    input_messages_key="input",
    history_messages_key="history",
)

# Set up the speech recognition engine
r = sr.Recognizer()

def listen():
  with sr.Microphone() as source:
    audio = r.listen(source, phrase_time_limit=5)
    print("Processing...")
  try:
    text = r.recognize_google(audio)
    return text
  except Exception as e:
    print("Error: " + str(e))
    return None

def generate_response(prompt):
  completions = with_message_history.invoke(
    {"input": prompt},
    config={"configurable": {"session_id": session_id}},
    )
  message = completions.content
  return message

def speak(text):
    """simply streams the text to the speakers"""
    print(f"{character.name}: " + text)
    try:
        stream = sd.OutputStream(samplerate=voice.config.sample_rate, channels=1, dtype='int16')
        stream.start()
        
        for audio_bytes in voice.synthesize_stream_raw(text):
            int_data = np.frombuffer(audio_bytes, dtype=np.int16)
            stream.write(int_data)
        
        stream.stop()
        stream.close()
    except Exception as e:
        print(f"Error during speech synthesis: {e}")

speak(conversation_start)

flag = True
while True:
  if ptt:
    input("Press Enter to start recording...")
  if flag:
    print("Listening...")
    flag = False
  prompt = listen()
  if prompt is not None:
    print("You: " + prompt)
    response = generate_response(prompt)
    flag = True
    speak(response)

  else:
    flag = True
    speak(didnt_understand)

# Graceful shutdown? 
def signal_handler(sig, frame):
    print("\nGracefully shutting down...")
    exit(0)
signal.signal(signal.SIGINT, signal_handler)

# After parsing args
if args.list_voices:
    print("Available voice models:")
    for file in os.listdir("models"):
        if file.endswith(".onnx"):
            print(f"  {file}")
    exit(0)