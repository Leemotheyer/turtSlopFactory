## Your task
Probe the factory live preview. Do not start Docker or uvicorn.

Live preview: $upstream
Health: GET $health_path

Report whether the running preview meets the acceptance contract. If it is down, say so —
do not try to start a replacement container.
