import os
import re
from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_sdk import WebClient
from openai import OpenAI

dotenv_paths = [".env.local", ".env", ".env.development.local", ".env.development"]

for path in dotenv_paths:
    load_dotenv(dotenv_path=path)

openai_api_key = os.getenv("OPENAI_API_KEY")
slack_token = os.getenv("SLACK_BOT_TOKEN")
slack_signing_secret = os.getenv("SLACK_SIGNING_SECRET")
openai_organization_id = os.getenv("OPENAI_ORGANIZATION_ID")
openai_project_id = os.getenv("OPENAI_PROJECT_ID")
port = int(os.getenv('PORT', 3000))

app = AsyncApp(
    token=slack_token,
    signing_secret=slack_signing_secret,
)

openai = OpenAI(
    organization=openai_organization_id,
    project=openai_project_id,
    api_key=openai_api_key,
)

class SlackMessage:
    def __init__(self, text, user, channel, thread_ts=None):
        self.text = text
        self.user = user
        self.channel = channel
        self.thread_ts = thread_ts

async def fetch_recent_messages(channel, limit=10, thread_ts=None):
    try:
        if thread_ts:
            result = await app.client.conversations_replies(channel=channel, ts=thread_ts, limit=limit)
        else:
            result = await app.client.conversations_history(channel=channel, limit=limit)
        if result['messages']:
            messages = [
                SlackMessage(text=msg['text'], user=msg['user'], channel=channel, thread_ts=msg.get('thread_ts'))
                for msg in result['messages']
            ]
            #return [SlackMessage(**msg) for msg in result['messages']]
            return messages
        else:
            return []
    except Exception as e:
        print(f"Error fetching messages: {e}")
        return []

def system_prompt(question=None):
    return {
        "role": "system",
        "content": (
            "You are a helpful assistant. You will summarize the conversation using Korean only. "
            "You should answer the question if the last message starts with `@#*&Question: ` else you just create a helpful summary "
            "WITHOUT ORIGINAL MESSAGES. The summary should contain speaker names. Do not include the messages directly in the summary."
        )
    }

async def get_user_map(users):
    user_map = {}
    for user in users:
        user_info = await app.client.users_info(user=user)
        user_map[user] = user_info.get('user', {}).get('name', 'Unknown')
    return user_map

#FIX
async def summarize_text(chats, question=None):
    try:
        user_map = await get_user_map([chat.user for chat in chats])
        messages = []
        for chat in chats:
            if chat.text.startswith("!summarize"):
                continue
            speaker = user_map.get(chat.user, "Unknown")
            if speaker == "Summarizer-Test": # Might need to change
                continue
            if chat.text.startswith("<@U07AF4DJWRH>"):
                continue

            chat_text = chat.text
            for user_id, user_name in user_map.items():
                chat_text = chat_text.replace(f"<@{user_id}>", user_name)
            messages.append({"role": "user", "content": f"{speaker}: {chat.text}", "user": speaker})
        
        system_prmpt = system_prompt(question)
        if question:
            messages.append({"role": "user", "content": f"@#*&Question: {question}", "user": "definetly not a bot"})
       
        chat_completion = openai.chat.completions.create(
            model="gpt-4o",
            messages=[system_prmpt, *messages],
            temperature=0.5
        )
        return chat_completion.choices[0].message.content if chat_completion.choices[0] else "No summary found."
    except Exception as e:
        print(f"Error summarizing text: {e}")
        return "Error summarizing text."
    
async def post_message(channel_id, text, thread_ts=None):
    try:
        await app.client.chat_postMessage(channel=channel_id, text=text, thread_ts=thread_ts)
    except Exception as e:
        print(f"Error posting message: {e}")

#FIX
async def handle_summarize_request(channel_id, question=None, thread_ts=None, limit=10):
    messages = await fetch_recent_messages(channel_id, limit, thread_ts)
    if messages:
        summary = await summarize_text(messages, question)
        await post_message(channel_id, summary, thread_ts)

options = {
    "--help": "Show help",
    "--version": "Show version",
    "--limit": "Set the limit of messages to summarize",
}

@app.event("app_mention")
async def handle_app_mention(event, say):
    try:
        channel = event["channel"]
        thread_ts = event.get("thread_ts")
        text = event["text"]
        print("Event: ", text)
        prompt = " ".join(text.split(" ")[1:])
        print("Prompt: ", prompt)

        if prompt.strip() == "--help":
            help_text = (
                "```Usage: @Summarizer [summarize|question] [options]\n"
                "If no question is provided but 'summarize', the last 10 messages will be summarized.\n"
            )
            help_text += "\n".join([f"{key}: {options[key]}" for key in options.keys()])
            help_text += "```"
            await post_message(channel, help_text, thread_ts)
            return

        if prompt.strip() == "--version":
            await post_message(channel, "v1.0.0", thread_ts)
            return
        
        question = None
        limit = 10
        if "--limit" in prompt:
            parts = prompt.split("--limit")
            prompt = parts[0]
            limit = int(parts[1].strip()) if parts[1].strip().isdigit() else 10
        
        if prompt.strip() != "summarize":
            question = prompt

        await handle_summarize_request(channel, question, thread_ts, limit)
    except Exception as e:
        print(f"Error handling app_mention event: {e}")

#@app.event("message")
# Check how the app runs when asked a question w/o summarize

@app.message(re.compile(r'!summarize\s*(".*")?\s*([0-9]*)'))
async def handle_message(context, message, say):
    try:
        question = context['matches'][1]
        limit = int(context['matches'][2]) if context['matches'][2].isdigit() else 10
        print("Question: ", question)
        print("Limit: ", limit)
        channel = message['channel']
        thread_ts = message.get('thread_ts')
        await handle_summarize_request(channel, question, thread_ts, limit)
    except Exception as error:
        print(f"Error handling message event: {error}")

if __name__ == "__main__":
    print(f"⚡️ Slack Bolt app is running on port {port}!")
    app.start(port=port)
